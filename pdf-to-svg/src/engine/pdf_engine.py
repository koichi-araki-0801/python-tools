"""PyMuPDF を用いて PDF を中間ドキュメントモデルへ抽出する。

ライセンス注意: PyMuPDF は AGPL。社内配布前提のため採用しているが、外部配布が
必要になった場合はこのモジュールだけを BSD エンジン (pypdfium2) 等へ差し替える。
"""
from __future__ import annotations

import math
from typing import Dict, Iterator, List, Optional, Tuple

import fitz  # PyMuPDF

from model import fonts
from model.document import Document, Page, RasterBackground
from model.elements import (
    Element,
    ImageElement,
    LineElement,
    PathElement,
    Rect,
    RectElement,
    TextElement,
    sanitize_text,
)
from engine import classify
from engine.colors import int_to_hex, rgbf_to_hex

# span flags ビット
FLAG_ITALIC = 1 << 1
FLAG_BOLD = 1 << 4

SCAN_RENDER_SCALE = 2.0  # スキャンページのラスタ化倍率

# ラスタ化の資源上限。MediaBox は攻撃者が自由に書ける値で、実測では 20000x20000 pt・実体
# 3,610 バイトの PDF が素通りし 40000x40000 = 4.8 GB を確保して 36〜42 秒かかった。
# 上限に当たったら**縮小 degrade** する (GUI 操作の途中で無言の 40 秒停止が最悪であり、
# 可視な劣化のほうがまし)。縮小しても収まらないページは背景を諦めて None を返す。
MAX_RASTER_PIXELS = 16_000_000  # 1 ページの出力ピクセル数 (A4 @2.0 = 2.2M px の約 7 倍)
MIN_RENDER_SCALE = 0.25  # これ以下には縮めない (縮めても読めないため諦めへ倒す)
MAX_DOC_RASTER_PIXELS = 128_000_000  # 文書全体のラスタ予算 (ページ上限だけでは足りない)
MAX_PAGES = 2_000  # 解析するページ数の上限

# 要素数の資源上限。ラスタ予算がページ寸法を押さえるのと同じ理由で、**ベクターページの
# 要素数**も PDF 作成者が自由に決められる値である。要素数は seqno 照合・折返しグループ化
# (`dictionary/apply.py`) など後段すべての係数になるため、抽出の時点で頭を押さえる。
# 上限に当たったページは要素を切り捨てて `Page.truncated` を立てる (無言で固まるより、
# 可視な劣化のほうがまし = ラスタ背景の degrade と同じ判断)。
MAX_PAGE_ELEMENTS = 12_000     # 1 ページに積む要素数 (実運用の密なページで 1〜2 千)
MAX_DOC_ELEMENTS = 60_000      # 文書全体 (上限内のページを大量に並べる形を止める)

# seqno 照合の索引パラメータ。候補は行バンド (高さ `_SEQNO_BAND_PT`) に登録し、
# クエリと y が重なるバンドだけを見る。重なりが正なら y も必ず重なるので、
# バンド絞り込みは結果を変えない (同点は元の並び順で解決する `_best_seqno` 参照)。
_SEQNO_BAND_PT = 16.0
# 1 候補が跨いでよいバンド数。これを超える (= ページ半分より高い) 候補は `tall` へ寄せる。
# `fill-shade` の無限大 bbox がここに落ちる。登録は候補あたり最大この数なので、索引の
# メモリもここで頭が押さえられる。
_SEQNO_MAX_BANDS = 32
# `tall` の上限。超えたらバンド索引が意味を失うので**照合そのものを諦める**
# (z は抽出順のフォールバックになる。走査し続けるより諦めるほうがよい)。
_SEQNO_MAX_TALL = 256
# 索引を組む候補数の上限。索引の構築自体も候補数に比例するので、桁違いの候補が来たら
# 組まずに諦める (`get_texttrace` の件数はページ作成者の裁量で、要素数予算より前に来る)。
_SEQNO_MAX_CANDIDATES = 50_000
# 1 クエリで見る候補数の上限。同一バンドへ候補を敷き詰める細工に対する最後の歯止め。
_SEQNO_MAX_SCAN = 1_024


def _fmt(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


def _pt(p) -> str:
    return f"{_fmt(p.x)},{_fmt(p.y)}"


class RasterBudget:
    """文書全体のラスタ化ピクセル予算。1 ページの上限だけでは「上限内のページを大量に
    並べる」形を止められないので、`LcsBudget` と同じく文書単位の予算を持ち回る。"""

    def __init__(self, total: int = MAX_DOC_RASTER_PIXELS) -> None:
        self.remaining = total

    def take(self, pixels: int) -> bool:
        if pixels > self.remaining:
            return False
        self.remaining -= pixels
        return True


class ElementBudget:
    """文書全体の要素数予算 (`RasterBudget` と同じ持ち回り方)。

    1 ページの上限だけでは「上限内のページを大量に並べる」形を止められない。
    """

    def __init__(self, total: int = MAX_DOC_ELEMENTS) -> None:
        self.remaining = total

    def take(self, count: int = 1) -> bool:
        if count > self.remaining:
            return False
        self.remaining -= count
        return True


class _PageElements:
    """1 ページへ積む要素の受け皿。ページ上限と文書予算のどちらかに当たったら
    `full` を立て、以降の追加を捨てて `Page.truncated` を立てる。

    呼び出し側は `full` を見てループを畳む (ループを続けても捨てられるだけなので、
    「上限に当たった後も全 span を走査する」無駄を作らない)。
    """

    def __init__(self, page: Page, budget: "ElementBudget | None") -> None:
        self.page = page
        self.budget = budget
        self.full = False

    def add(self, element: Element) -> bool:
        if self.full:
            return False
        if len(self.page.elements) >= MAX_PAGE_ELEMENTS or (
            self.budget is not None and not self.budget.take()
        ):
            self.full = True
            self.page.truncated = True
            return False
        self.page.elements.append(element)
        return True


def load_document(path: str) -> Document:
    """PDF を開き Document を構築する。"""
    doc = Document(source_path=path)
    budget = RasterBudget()
    elements = ElementBudget()
    with fitz.open(path) as pdf:
        if pdf.page_count > MAX_PAGES:
            raise ValueError(
                f"PDF has {pdf.page_count} pages (limit {MAX_PAGES}); refusing to load."
            )
        for i, page in enumerate(pdf):
            doc.pages.append(_extract_page(page, i, budget, elements))
    return doc


def _extract_page(
    page: "fitz.Page", index: int, budget: "RasterBudget | None" = None,
    elements: "ElementBudget | None" = None,
) -> Page:
    """1 ページを Page へ抽出する。スキャン判定ならラスタ背景のみ、ベクターなら
    テキスト/画像/描画を PDF の実ペイント順 (seqno) を復元した z 付きで積む。"""
    rect = page.rect
    scanned = classify.is_scanned_page(page)
    p = Page(
        index=index,
        width_pt=rect.width,
        height_pt=rect.height,
        is_scanned=scanned,
    )

    if scanned:
        # `None` = ラスタ化を省略した (上限超過)。背景無しのまま返し、`web/rpc_methods.py` の
        # `rpc_state` が `noBackground` として数え `app.js` がトーストで伝える
        # (`Page.truncated` と同じ通知経路。無言で欠落させない)。
        p.background = _render_background(page, budget)
        return p

    # z は PDF の実ペイント順 (コンテンツストリームの seqno) を復元して採番する。
    # get_text は読み順・get_drawings はパス順で返すため、抽出順のままだと
    # 「帯の塗り矩形が先・白文字が後」の前後関係が逆転し文字が矩形に隠れる。
    # z = seqno * _Z_TIER + 連番 (連番は同一 seqno 内・全体の安定順序用)。
    text_seqnos = [
        (s["seqno"], Rect.from_xyxy(*s["bbox"])) for s in page.get_texttrace()
    ]
    image_seqnos = [
        (i, Rect.from_xyxy(*r))
        for i, (kind, r) in enumerate(page.get_bboxlog())
        if kind in ("fill-image", "fill-shade")
    ]

    # 候補は行バンド索引に載せる。span 1 個ごとに候補**全件**を線形走査すると、
    # どちらも PDF 作成者が決める件数なので O(n^2) が素通りする (1 ページ 10 万 span で
    # 約 1e10 回 = 事実上終わらない。`upload_lock` を握ったままなので以後どのファイルも
    # 開けなくなる)。索引は結果を変えず、当たらない候補を見ないだけである。
    text_index = _SeqnoIndex(text_seqnos)
    image_index = _SeqnoIndex(image_seqnos)

    sink = _PageElements(p, elements)
    seq = 0
    prev_seqno = 0
    text_dict = page.get_text("dict")
    for block in text_dict.get("blocks", []):
        if sink.full:
            break
        if block.get("type") == 1:  # 画像ブロック
            bbox = Rect.from_xyxy(*block["bbox"])
            # 照合失敗時は -1 (背景扱い): 画像は下敷きであることが大半
            seqno = image_index.match(bbox, -1)
            img = _image_element(block, seqno * _Z_TIER + seq)
            if img is not None and sink.add(img):
                seq += 1
        else:  # テキストブロック
            for line in block.get("lines", []):
                if sink.full:
                    break
                for span in line.get("spans", []):
                    bbox = Rect.from_xyxy(*span["bbox"])
                    seqno = text_index.match(bbox, prev_seqno)
                    el = _text_element(span, seqno * _Z_TIER + seq)
                    if el is not None:
                        prev_seqno = seqno
                        if not sink.add(el):
                            break
                        seq += 1

    for drawing in page.get_drawings():
        if sink.full:
            break
        seqno = int(drawing.get("seqno") or 0)
        for el in _drawing_elements(drawing, seqno * _Z_TIER + seq):
            if not sink.add(el):
                break
            seq += 1

    return p


# 1 ページ内の要素数を超える十分大きな tier 幅 (z = seqno * tier + 連番)
_Z_TIER = 1_000_000


def _overlap_area(a: Rect, b: Rect) -> float:
    w = min(a.x1, b.x1) - max(a.x, b.x)
    h = min(a.y1, b.y1) - max(a.y, b.y)
    return w * h if (w > 0 and h > 0) else 0.0


def _best_seqno(
    bbox: Rect, entries: "Iterator[Tuple[int, int, Rect]]", default: int, limit: int
) -> int:
    """`(元の並び順, seqno, Rect)` の列から IoU 最大の seqno を選ぶ (走査上限 `limit`)。

    重なり「面積」最大で照合すると、軸ラベル全体を 1 度の text-show で描いた
    巨大 span が、その内側の小さな凡例ラベル span を吸い込み、誤って早い描画順
    (seqno) を与えてしまう (→ 後から塗られる凡例ボックス背景に隠れて消える)。
    IoU (重なり / 和集合) なら巨大候補は和集合が大きく自然に弾かれ、最もフィット
    する狭い span が選ばれる。fill-shade のような無限大 bbox の候補も IoU≈0 で
    排除されるため、画像照合側の「無限 bbox 吸い込み」対策も兼ねる。

    同点は**元の並び順が先**を採る。かつての線形走査は「最初に見つかった最大」を
    残していたので、索引で走査順が変わっても出力 SVG が 1 バイトも変わらないよう
    順序を明示的に持ち込む (`test_pipeline` の決定性はこの性質に依存する)。
    """
    best = default
    best_iou = 0.0
    best_idx = -1
    qa = bbox.w * bbox.h
    scanned = 0
    for idx, seqno, r in entries:
        if scanned >= limit:
            break  # 走査上限に当たったらそこまでで決める (回し続けない)
        scanned += 1
        ov = _overlap_area(bbox, r)
        if ov <= 0:
            continue
        iou = ov / (qa + r.w * r.h - ov)
        if iou > best_iou or (iou == best_iou and 0 <= idx < best_idx):
            best_iou = iou
            best = seqno
            best_idx = idx
    return best


def _match_seqno(bbox: Rect, candidates: List[Tuple[int, Rect]], default: int) -> int:
    """bbox に最もフィットする候補の seqno を返す (IoU 最大、無ければ default)。

    候補列を丸ごと走査する参照実装。ページ抽出は候補数が攻撃者の裁量なので
    `_SeqnoIndex` 経由で使い、ここは小さな候補列 (テスト・単発照合) 用に残す。
    """
    entries = ((i, seqno, r) for i, (seqno, r) in enumerate(candidates))
    return _best_seqno(bbox, entries, default, len(candidates))


def _band_range(y0: float, y1: float) -> "Tuple[int, int] | None":
    """y 範囲が跨ぐ行バンドの添字範囲。非有限・`_SEQNO_MAX_BANDS` 超は `None`。"""
    lo, hi = (y0, y1) if y0 <= y1 else (y1, y0)
    if not (math.isfinite(lo) and math.isfinite(hi)):
        return None
    b0 = int(math.floor(lo / _SEQNO_BAND_PT))
    b1 = int(math.floor(hi / _SEQNO_BAND_PT))
    if b1 - b0 + 1 > _SEQNO_MAX_BANDS:
        return None
    return b0, b1


class _SeqnoIndex:
    """seqno 候補の行バンド索引。`match` は y が重なる候補だけを見る。

    重なり面積が正なら y も必ず重なるため、バンドで絞っても選ばれる候補は変わらない
    (同点解決は `_best_seqno` が元の並び順で行う)。ページ高さ級に高い候補
    (`fill-shade` の無限大 bbox 等) はどのバンドにも属さないので `tall` に集め、常に見る。

    それでも潰れる形が 3 つあるので上限を置く: ①候補そのものが桁違いに多い
    ②`tall` を大量に並べる → どちらも索引が意味を失うので `degraded` を立てて
    **照合を諦める** (z は抽出順へフォールバック) ③同一バンドへ候補を敷き詰める →
    `_SEQNO_MAX_SCAN` で 1 クエリの走査量を切る。いずれも「上限に当たったら諦める」
    であって、無限に回らないことが要点である。
    """

    def __init__(self, candidates: List[Tuple[int, Rect]]) -> None:
        self.bands: Dict[int, List[Tuple[int, int, Rect]]] = {}
        self.tall: List[Tuple[int, int, Rect]] = []
        if len(candidates) > _SEQNO_MAX_CANDIDATES:
            # 索引を組むこと自体が候補数に比例する。桁違いなら組まずに諦める。
            self.entries: List[Tuple[int, int, Rect]] = []
            self.degraded = True
            return
        self.entries = [(i, seqno, r) for i, (seqno, r) in enumerate(candidates)]
        for entry in self.entries:
            _idx, _seqno, r = entry
            rng = _band_range(r.y, r.y1)
            if rng is None:
                self.tall.append(entry)
                continue
            for band in range(rng[0], rng[1] + 1):
                self.bands.setdefault(band, []).append(entry)
        self.degraded = len(self.tall) > _SEQNO_MAX_TALL

    def match(self, bbox: Rect, default: int) -> int:
        if self.degraded:
            return default
        return _best_seqno(bbox, self._nearby(bbox), default, _SEQNO_MAX_SCAN)

    def _nearby(self, bbox: Rect) -> "Iterator[Tuple[int, int, Rect]]":
        """y が重なりうる候補を返す。バンドを先に、`tall` を後に回す
        (走査上限に当たるときは、当たりやすい近傍のほうを見ておきたい)。"""
        rng = _band_range(bbox.y, bbox.y1)
        if rng is None:
            # 非有限・極端に高いクエリはバンドで絞れない。全件を返し、上限で切る。
            yield from self.entries
            return
        for band in range(rng[0], rng[1] + 1):
            found = self.bands.get(band)
            if found:
                yield from found
        yield from self.tall


def _render_background(
    page: "fitz.Page", budget: "RasterBudget | None" = None
) -> "RasterBackground | None":
    """スキャンページ全面を PNG にラスタ化して背景要素にする (倍率 `SCAN_RENDER_SCALE`)。

    ページ寸法は攻撃者が書ける値なので、**確保の直前**に目標ピクセル数を見て倍率を
    下げる。`MIN_RENDER_SCALE` まで下げても上限を超えるページ、および文書全体の予算を
    使い切った以降のページは背景を作らず ``None`` を返す (通知経路は `_extract_page` の注記)。
    """
    r = page.rect
    scale = SCAN_RENDER_SCALE
    while scale > MIN_RENDER_SCALE and r.width * scale * r.height * scale > MAX_RASTER_PIXELS:
        scale /= 2
    pixels = int(r.width * scale * r.height * scale)
    if pixels > MAX_RASTER_PIXELS:
        return None
    if budget is not None and not budget.take(pixels):
        return None
    mat = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    png = pix.tobytes("png")
    return RasterBackground(png_bytes=png, rect=Rect(0, 0, r.width, r.height))


def _text_element(span: dict, z: int) -> Optional[TextElement]:
    """get_text("dict") の span 1 個を TextElement へ変換する。空白のみは None。
    フォントは同梱 2 書体へマッピングし、ウェイトは名前優先 + bold フラグで補正。"""
    text = sanitize_text(span.get("text", ""))
    if text == "" or text.isspace():
        return None
    bbox = span["bbox"]
    origin = span.get("origin", (bbox[0], bbox[3]))
    flags = span.get("flags", 0)
    raw_font = _clean_font(span.get("font", "sans-serif"))
    mapped = fonts.map_font(raw_font, text)
    # ウェイトはフォント名由来 (Light/Regular/Medium/Bold) を尊重し、名前に重み指定が
    # 無く PyMuPDF の bold フラグだけ立つ場合に限り太字へ持ち上げる。
    weight = mapped.weight
    if (flags & FLAG_BOLD) and weight < 600:
        weight = 700
    return TextElement(
        bbox=Rect.from_xyxy(*bbox),
        z=z,
        text=text,
        font_family=mapped.family,
        font_size=float(span.get("size", 12.0)),
        weight=weight,
        italic=bool(flags & FLAG_ITALIC) or mapped.italic,
        color=int_to_hex(span.get("color", 0)),
        origin_x=origin[0],
        origin_y=origin[1],
    )


def _clean_font(font: str) -> str:
    """埋め込みフォント名 ("ABCDEF+NotoSansJP") からサブセット接頭辞を除去。"""
    if "+" in font and len(font.split("+", 1)[0]) == 6:
        font = font.split("+", 1)[1]
    return font


def _image_element(block: dict, z: int) -> Optional[ImageElement]:
    """画像ブロックを ImageElement へ変換する。バイト列を持たないブロックは None。"""
    data = block.get("image")
    if not data:
        return None
    bbox = block["bbox"]
    return ImageElement(
        bbox=Rect.from_xyxy(*bbox),
        z=z,
        rect=Rect.from_xyxy(*bbox),
        img_bytes=data,
        ext=block.get("ext", "png"),
    )


def _drawing_elements(drawing: dict, z: int) -> List[Element]:
    """get_drawings() の 1 描画を要素へ変換する。単一の線/矩形は編集しやすい
    専用要素 (Line/Rect) に、それ以外は path d 文字列の PathElement に落とす。"""
    dtype = drawing.get("type", "s")  # "s" stroke / "f" fill / "fs" both
    stroke = rgbf_to_hex(drawing.get("color")) if dtype in ("s", "fs") else None
    fill = rgbf_to_hex(drawing.get("fill")) if dtype in ("f", "fs") else None
    width = float(drawing.get("width", 1.0) or 1.0)
    items = drawing.get("items", [])
    rect_b = drawing.get("rect")
    bbox = Rect.from_xyxy(rect_b.x0, rect_b.y0, rect_b.x1, rect_b.y1) if rect_b else Rect(0, 0, 0, 0)

    # 単純形状は専用要素に (選択・編集しやすい)
    if len(items) == 1:
        it = items[0]
        if it[0] == "l":
            p0, p1 = it[1], it[2]
            return [
                LineElement(
                    bbox=bbox, z=z, x0=p0.x, y0=p0.y, x1=p1.x, y1=p1.y,
                    width=width, color=stroke or "#000000",
                )
            ]
        if it[0] == "re":
            r = it[1]
            return [
                RectElement(
                    bbox=bbox, z=z,
                    rect=Rect.from_xyxy(r.x0, r.y0, r.x1, r.y1),
                    stroke=stroke, fill=fill, stroke_width=width,
                )
            ]

    d = _items_to_path_d(items, bool(drawing.get("closePath")))
    if not d:
        return []
    return [
        PathElement(
            bbox=bbox, z=z, d=d, stroke=stroke, fill=fill, stroke_width=width,
        )
    ]


def _items_to_path_d(items: list, close: bool) -> str:
    """描画 items (l/c/re/qu) を SVG path の d 文字列へ直列化する。連続セグメントは
    始点一致なら M を挟まず繋ぎ、re/qu は独立サブパスとして出力する。"""
    parts: List[str] = []
    last = None

    def moveto(p):
        nonlocal last
        parts.append(f"M{_pt(p)}")
        last = p

    for it in items:
        op = it[0]
        if op == "l":
            p0, p1 = it[1], it[2]
            if last is None or (last.x, last.y) != (p0.x, p0.y):
                moveto(p0)
            parts.append(f"L{_pt(p1)}")
            last = p1
        elif op == "c":
            p0, c1, c2, p1 = it[1], it[2], it[3], it[4]
            if last is None or (last.x, last.y) != (p0.x, p0.y):
                moveto(p0)
            parts.append(f"C{_pt(c1)} {_pt(c2)} {_pt(p1)}")
            last = p1
        elif op == "re":
            r = it[1]
            parts.append(
                f"M{_fmt(r.x0)},{_fmt(r.y0)}"
                f"H{_fmt(r.x1)}V{_fmt(r.y1)}H{_fmt(r.x0)}Z"
            )
            last = None
        elif op == "qu":
            q = it[1]
            parts.append(
                f"M{_pt(q.ul)}L{_pt(q.ur)}L{_pt(q.lr)}L{_pt(q.ll)}Z"
            )
            last = None

    d = " ".join(parts)
    if close and d:
        d += " Z"
    return d
