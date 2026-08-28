"""ヘッダ検出と辞書の適用。

PDF には意味的な「表ヘッダ」が無いため、ヒューリスティックで is_header を推定する
(太字、または最上段の行バンド)。取りこぼしは UI から手動トグルで救済する。
適用は「置換案 (Replacement) のリスト」を返し、UndoStack 経由で反映できるようにする。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from model import fonts
from model.document import Page
from model.elements import DictMatch, DictRevertInfo, Rect, TextElement
from dictionary.store import DictionaryStore

TOP_BAND_RATIO = 0.25  # ページ上端からこの割合内の最初の行をヘッダ候補とする
ROW_TOLERANCE = 3.0    # 同一行とみなす baseline の許容差(pt)

# 折返しヘッダ (複数行に分割されたセル) を 1 語として連結照合するためのしきい値。
# PyMuPDF は折返し各行を別 span = 別 TextElement に分けるため、縦に隣接する
# 同一列・同一サイズの要素を 1 グループに束ねて辞書を引く (照合・置換時のみ連結。
# 描画は従来どおり行ごとの <text> のまま)。
COLUMN_OVERLAP_RATIO = 0.5  # 同一列とみなす bbox 横方向オーバーラップ率 (狭い方基準)
# 縦隣接とみなす baseline 差 (フォントサイズ比)。折返し leading は実測で font*1.0〜1.2
# が標準。表の行ピッチ (= 別行のセル) を巻き込んで誤連結しないよう上限を 1.3 に絞る。
LINE_GAP_RATIO = 1.3
FONT_SIZE_TOL = 0.5         # 同一スタイルとみなす font_size 許容差(pt)

# `_wrap_groups` の走査上限。要素は y 昇順に並ぶので通常は「縦ギャップが上限を超えた」
# 時点で打ち切れるが、**同じ y 帯へ大量の要素を並べる**細工ページでは打ち切りが効かず
# 全要素 x 全要素の走査に戻る (1 ページ 10 万 span で約 5e9 回)。そこで 1 要素あたりの
# 走査数を切り、超えたら**折返し探索を諦める** (グループ化の精度が落ちるだけで、置換も
# 描画も成立する = degrade)。実ページで折返しの相手は数百要素以内に必ず現れる。
MAX_WRAP_SCAN = 1024
# 並べ替えキーが `round(origin_y, 1)` なので、走査順の `origin_y` は最大 0.1 だけ前後
# しうる。打ち切り判定にはこの分を足し、**本当の追随候補を切り落とさない**側へ倒す。
_GAP_SORT_EPS = 0.1


@dataclass
class Replacement:
    element: TextElement
    source: str
    target: str
    # 折返しヘッダの 2 行目以降。置換時は描画から除外 (deleted) する。
    extras: List[TextElement] = field(default_factory=list)
    # 折返し畳み込み時、結合テキストを据え直す合成領域 (グループ全体の bbox)。
    # SVG 書き出しは置換後テキストを下揃え (baseline_y) + 元の行揃え (align) で
    # この箱へ収める (`svg_exporter.py` の `_text_to_svg`)。単独行は None で元 bbox のまま。
    new_bbox: Optional[Rect] = None
    # 折返し畳み込み時の水平揃え ("left"/"center"/"right")。元の折返し各行の揃えを
    # 検出して踏襲する (`_detect_wrap_align`)。単独行は None。
    align: Optional[str] = None
    # 折返し畳み込み時のベースライン (= 最終行のベースライン)。縦は常に下揃え。
    baseline_y: Optional[float] = None
    # 置換語の推定幅が収め先の箱幅を超える恐れ ("width_overflow")。レビュー UI / ログ用。
    warning: Optional[str] = None


def _merged_bbox(group: List[TextElement]) -> Rect:
    """折返しグループ全体を包む合成 bbox (置換後テキストの据え直し領域)。"""
    x0 = min(t.bbox.x for t in group)
    y0 = min(t.bbox.y for t in group)
    x1 = max(t.bbox.x1 for t in group)
    y1 = max(t.bbox.y1 for t in group)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def _detect_wrap_align(group: List[TextElement]) -> str:
    """折返し各行の bbox から元の水平揃えを推定する ("left"/"center"/"right")。

    左端・中央・右端それぞれの行間ばらつき (max-min) を比べ、最も揃っている辺を
    元の揃えとみなす。全行同幅などの同点は左揃えを既定とする。
    """
    lefts = [t.bbox.x for t in group]
    centers = [(t.bbox.x + t.bbox.x1) / 2 for t in group]
    rights = [t.bbox.x1 for t in group]
    spreads = [
        ("left", max(lefts) - min(lefts)),
        ("center", max(centers) - min(centers)),
        ("right", max(rights) - min(rights)),
    ]
    return min(spreads, key=lambda kv: kv[1])[0]


def _overflow_warning(target: str, font_size: float, box_w: float) -> Optional[str]:
    """置換語が箱幅を超える恐れなら警告種別を返す (簡易幅推定)。"""
    return "width_overflow" if fonts.is_width_overflow(target, font_size, box_w) else None


def _text_elements(page: Page) -> List[TextElement]:
    return [e for e in page.elements if isinstance(e, TextElement) and not e.deleted]


def _x_overlap_ratio(a: TextElement, b: TextElement) -> float:
    ov = min(a.bbox.x1, b.bbox.x1) - max(a.bbox.x, b.bbox.x)
    narrow = min(a.bbox.w, b.bbox.w)
    return ov / narrow if (ov > 0 and narrow > 0) else 0.0


def _is_wrap_follower(top: TextElement, below: TextElement) -> bool:
    """below が top の直下に折り返された同一セルの続き行とみなせるか。"""
    gap = below.origin_y - top.origin_y
    return (
        0 < gap <= max(top.font_size, below.font_size) * LINE_GAP_RATIO
        and _x_overlap_ratio(top, below) >= COLUMN_OVERLAP_RATIO
        and abs(top.font_size - below.font_size) <= FONT_SIZE_TOL
    )


def _wrap_groups(texts: List[TextElement]) -> List[List[TextElement]]:
    """縦に折り返された同一列・同一スタイルの要素を上→下のグループに束ねる。

    単独行は要素 1 個のグループになる (= 連結対象外)。

    走査量の上限が要点である。要素ごとに `ordered[i + 1:]` を**毎回スライスして
    全部見る**素朴な走査だと、ページ内テキスト要素数 n に対して n^2/2 回の判定 + 同数の
    リストコピーになる。n は PDF 作成者が決める値で上限が無く、再適用ボタンは
    `server.lock` を握ったまま走るのでアプリ全体が固まる。対策は 3 つ:
    ①スライスをやめて添字で回す ②y 昇順である性質を使い、縦ギャップが上限を超えた
    時点で打ち切る ③それでも効かない「同じ y 帯に大量の要素」は `MAX_WRAP_SCAN` で
    諦める。①②は結果が変わらない純粋な高速化で、劣化しうるのは③だけである。

    打ち切りの上限には**残り候補の最大 font_size** を使う。追随判定
    (`_is_wrap_follower`) の許容ギャップが `max(cur, u)` の font_size 基準であるため、
    残りに存在しうる最大サイズで押さえれば追随候補を取りこぼさない。
    """
    ordered = sorted(texts, key=lambda t: (round(t.origin_y, 1), t.origin_x))
    n = len(ordered)
    if n == 0:
        return []
    # suffix_max_font[j] = ordered[j:] の最大 font_size (打ち切り上限の材料)。
    suffix_max_font = [0.0] * (n + 1)
    for j in range(n - 1, -1, -1):
        suffix_max_font[j] = max(ordered[j].font_size, suffix_max_font[j + 1])

    used = [False] * n
    groups: List[List[TextElement]] = []
    for i in range(n):
        if used[i]:
            continue
        cur = ordered[i]
        group = [cur]
        used[i] = True
        j = i + 1
        scanned = 0
        while j < n and scanned < MAX_WRAP_SCAN:
            u = ordered[j]
            limit = max(cur.font_size, suffix_max_font[j]) * LINE_GAP_RATIO
            if u.origin_y - cur.origin_y > limit + _GAP_SORT_EPS:
                break  # 以降はさらに下 = どれも追随になりえない
            scanned += 1
            if not used[j] and _is_wrap_follower(cur, u):
                group.append(u)
                used[j] = True
                cur = u
            j += 1
        groups.append(group)
    return groups


def detect_headers(page: Page) -> None:
    """is_header を推定して各 TextElement に設定する。"""
    texts = _text_elements(page)
    if not texts:
        return

    # 最上段の行バンド (top band 内で最小 y のクラスタ)
    band_limit = page.height_pt * TOP_BAND_RATIO
    top_candidates = [t for t in texts if t.origin_y <= band_limit]
    top_row_ys: List[float] = []
    if top_candidates:
        min_y = min(t.origin_y for t in top_candidates)
        top_row_ys = [
            t.origin_y for t in top_candidates if abs(t.origin_y - min_y) <= ROW_TOLERANCE
        ]

    for t in texts:
        in_top_row = any(abs(t.origin_y - y) <= ROW_TOLERANCE for y in top_row_ys)
        t.is_header = bool(t.bold or in_top_row)

    # 折返しヘッダ: 先頭行がヘッダのグループは後続行も is_header にする
    # (top band 判定だと 2 行目以降は baseline がずれて取りこぼすため)。
    for group in _wrap_groups(texts):
        if group[0].is_header:
            for t in group:
                t.is_header = True


def _lookup_joined(
    store: DictionaryStore, group: List[TextElement]
) -> Optional[Tuple[str, str]]:
    """折返しグループを連結して辞書を引く (区切り無し→空白の順で最初の一致)。

    一致した連結元文字列 (source) と置換先 (target) の組を返す。照合は連結由来
    (`joined=True`) エントリ限定の `lookup_wrap`: 単独行で登録した語が偶然
    連結形と一致して 2 行を畳む事故を防ぐ (連結の可否はエントリ側が記録している)。
    """
    parts = [t.text.strip() for t in group]
    for sep in ("", " "):  # 和文(区切り無し)・欧文(空白)の双方を拾う
        joined = sep.join(parts)
        target = store.lookup_wrap(joined)
        if target is not None:
            return joined, target
    return None


# CJK (漢字・かな等) を含むかの判定。連結候補の区切り (無し/空白) を選ぶのに使う。
_CJK = re.compile(
    r"[぀-ヿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ]"
)


def _join_for_candidate(parts: List[str]) -> str:
    """折返し各行を辞書 source 候補へ連結する (和文=区切り無し / 欧文=空白)。

    `_lookup_joined` は区切り無し・空白の双方を試すため、ここでどちらか一方の
    自然な連結を返せば再適用時に一致する。CJK を含めば区切り無し、無ければ空白。
    """
    return "".join(parts) if _CJK.search("".join(parts)) else " ".join(parts)


def joined_candidate(
    page: Page, element: TextElement, join_wrapped: bool = False
) -> Tuple[str, bool]:
    """`element` の辞書 source 候補と「連結したか」を返す (UI の取り込み用)。

    `join_wrapped=True` のとき、折返しグループをマッチャ (`_wrap_groups` /
    `_lookup_joined`) と同じ束ね方で連結する。返り値をそのまま辞書へ登録すれば
    複数行にまたがる 1 文 (折返しセル) に再適用で一致する。第 2 要素の連結印は
    登録エントリの `joined` フラグ (連結照合の対象にするか) の記録に使う。
    `join_wrapped=False` (既定)・単独行はクリック行のテキストをそのまま返す。
    """
    if not join_wrapped:
        return element.text.strip(), False
    texts = _text_elements(page)
    for group in _wrap_groups(texts):
        if any(t is element for t in group):
            if len(group) < 2:
                return element.text.strip(), False
            return _join_for_candidate([t.text.strip() for t in group]), True
    return element.text.strip(), False


def _iter_replacements(page: Page, store: DictionaryStore):
    """辞書に一致する置換案を出現順に生成する (`plan_replacements` の生成器版)。

    `has_replacement_candidate` が `next(..., None)` で最初の 1 件だけ取り出して
    打ち切れるよう、判定ロジック本体をここへ集約する
    (`plan_replacements` は全件を消費してリスト化するだけの薄いラッパ)。
    """
    texts = _text_elements(page)
    consumed: set = set()

    # 折返し連結照合 (要素単位より優先)。一致は連結由来エントリのみ (`_lookup_joined`
    # 参照)。連結で一致しなければグループは解放され、
    # 各行が従来どおり単独照合される (後方互換)。
    for group in _wrap_groups(texts):
        if len(group) < 2:
            continue
        hit = _lookup_joined(store, group)
        if hit is None:
            continue
        source, target = hit
        top = group[0]
        if target != top.text:
            # 折返しは結合テキストをグループ全体の合成領域へ据え直す。縦は下揃え
            # (最終行のベースライン) 固定、横は元の折返し行の揃えを検出して踏襲する。
            box = _merged_bbox(group)
            yield Replacement(
                top, source, target, extras=group[1:], new_bbox=box,
                align=_detect_wrap_align(group), baseline_y=group[-1].origin_y,
                warning=_overflow_warning(target, top.font_size, box.w),
            )
        for t in group:
            consumed.add(id(t))

    for el in texts:
        if id(el) in consumed:
            continue
        target = store.lookup(el.text)
        if target is not None and target != el.text:
            yield Replacement(
                el, el.text, target,
                warning=_overflow_warning(target, el.font_size, el.bbox.w),
            )


def plan_replacements(page: Page, store: DictionaryStore) -> List[Replacement]:
    """辞書に一致する置換案を列挙する (実際の書き換えはしない)。ヘッダ・本文を問わない。"""
    return list(_iter_replacements(page, store))


def has_replacement_candidate(page: Page, store: DictionaryStore) -> bool:
    """置換候補が 1 件でもあるかだけを判定する (`plan_replacements` の軽量版)。

    `state` RPC はページ単位で毎回呼ばれるホット経路で、全件の置換計画を作る必要は
    無く「1 件でもあるか」だけが要る。`_iter_replacements` を最初の 1 件で打ち切り、
    辞書が空なら (`store.all()` が空) ページの走査自体を省く。
    """
    if not store.all():
        return False
    return next(_iter_replacements(page, store), None) is not None


def apply_replacement(rep: Replacement) -> None:
    """置換案をモデルへ反映 (初期自動適用用。Undo が要る場面では Command を使う)。"""
    # 箇所単位の「戻す」が復元に使う置換前状態 (`ReplaceTextCommand` と同じ内容)。
    rep.element.dict_revert = DictRevertInfo(
        text=rep.element.text, bbox=rep.element.bbox, wrap_align=rep.element.wrap_align,
        origin_y=rep.element.origin_y, extra_ids=[e.id for e in rep.extras],
    )
    rep.element.text = rep.target
    rep.element.dict_match = DictMatch(source=rep.source, target=rep.target)
    if rep.new_bbox is not None:  # 折返し畳み込み: 合成領域へ据え直す
        rep.element.bbox = rep.new_bbox
    if rep.baseline_y is not None:  # 縦は下揃え (最終行のベースライン)
        rep.element.origin_y = rep.baseline_y
    if rep.align is not None:  # 横は元の行揃えを踏襲 (SVG 出力の据え方が変わる)
        rep.element.wrap_align = rep.align
    for ex in rep.extras:  # 折返し 2 行目以降は描画から除外
        ex.deleted = True


def auto_apply(page: Page, store: DictionaryStore) -> int:
    """ヘッダ検出 → 一致を直接適用。適用件数を返す。

    テスト・バッチ用の一括ヘルパ。本番 UI はアップロード時に辞書を適用せず、
    再適用ボタン (Undo 可能な Command マクロ経路) からのみ適用する。
    """
    detect_headers(page)
    plans = plan_replacements(page, store)
    for rep in plans:
        apply_replacement(rep)
    return len(plans)
