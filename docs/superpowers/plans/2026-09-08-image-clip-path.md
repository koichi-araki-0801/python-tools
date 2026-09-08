# 画像のクリップ形状 (PDF の `W n`) を SVG へ再現する実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PDF がクリップパスで切り抜いて描いている画像 (シェーディングを含む) を、SVG でも同じ形に切り抜いて出力し、不透明な矩形が下の図形を覆い隠す退行をなくす。

**Architecture:** `pymupdf` の `page.get_drawings(extended=True)` が返す `type="clip"` 項目の `scissor` 矩形を索引にし、`page.get_text("dict")` の画像ブロックの bbox と厳密一致で引き当てて、クリップ形状を `ImageElement.clip_d` (SVG path の `d` 文字列) としてモデルへ載せる。エクスポータは同一 `d` ごとに 1 個の `<clipPath>` を `<defs>` へまとめ、各 `<image>` からは `clip-path="url(#...)"` で参照する。

**Tech Stack:** Python 3.13 / PyMuPDF (`engine/` に隔離) / 標準ライブラリのみのエクスポータ / pytest

**Spec:** 本ファイルの「背景と調査結果」節 (別の spec ファイルは無く、実測に基づく仕様をここへ内蔵する)

## Global Constraints

- Python は常に `py -3.13` を明示する。
- pytest の一括実行は禁止。対象ディレクトリを個別指定する (`py -3.13 -m pytest pdf-to-svg`)。
- PyMuPDF (`fitz` / `pymupdf`) の import は `src/engine/pdf_engine.py` に閉じたまま保つ。`model/` `export/` から import しない。
- SVG 属性は必ず `export/svg_exporter.py` の `_attr()` 経由で組む (f-string で `="{...}"` 形を書かない。`test/test_export_escaping.py` のソース走査ガードが検出する)。
- `annotate=False` の書き出し出力は決定的であること (同一モデル → 同一 SVG)。既存の `test/test_pipeline.py` が固定している。
- 外部由来の入力 (PDF) が件数・要素数を決められる箇所には上限を置き、超過は degrade させて回し続けない。
- 新規スクリプトは Python 第一。`.ps1` は追加しない。

---

## 背景と調査結果 (この計画が前提とする実測)

対象 PDF: `https://www.smtam.jp/fund/pdf/_id_140823_type_k.pdf` の 8 ページ目 (0-origin で `doc.pages[7]`)、
「(3) 当社のスチュワードシップ活動」の螺旋図。

### 症状

螺旋図が「四角形が積み重なった図形」として描かれる。グレースケール限定ではなく、カラー出力でも同じく壊れる
(グレースケールでは色差が消えるため、より露骨に矩形に見える)。

### 原因

当該の図は PDF 上で次の 2 層で描かれている。

1. 螺旋の形を**単色のベジエパス塗り**で描く (`page.get_drawings()` の `type="f"`、seqno 20 / 44 / 45 / 46 / 47)。
2. その上に**グラデーション (PDF Shading) を、螺旋形のクリップパスで切り抜いて**重ねる
   (`page.get_bboxlog()` に `fill-shade` が 5 件)。

`src/engine/pdf_engine.py` の `_extract_page` は 2 を `page.get_text("dict")` の画像ブロック経由で受け取る。
この API は**シェーディングを bbox サイズのラスタ画像として返し、クリップ形状は返さない**。
`_image_element` はそれを `rect` の矩形へそのまま貼るため、切り抜きが失われて不透明なグラデ矩形になる。
さらに z 採番でこの画像が seqno 50 に落ち、螺旋パス (z 20〜47 × `_Z_TIER`) より**手前**へ積まれるため、
正しく描かれている螺旋パスを矩形 5 枚が覆い隠す。

### 引き当ての規則 (実測で確定)

`page.get_drawings(extended=True)` は `type="clip"` の項目を返し、その `scissor` 矩形が画像ブロックの bbox と一致する。
16 ページ・画像ブロック 187 件で、`scissor` と bbox を**小数第 1 位で丸めた 4 つ組**による厳密一致の結果は次のとおり。

- 候補 1 件 / うち有用 1 件: 120 件 → クリップを適用する
- 候補 1 件 / うち有用 0 件: 35 件 (items が `re` 1 個のみ = bbox と同じ矩形。適用しても意味がない)
- 候補 0 件: 18 件 (素の画像。ロゴなど)
- 候補 2〜6 件 / うち有用 0 件: 17 件
- 候補 2 件 / うち有用 2 件: 1 件 → 最も内側 (`level` が最大) の 1 件を採る

「有用」= items が `re` 1 個だけではない clip。`re` 1 個の clip は画像 bbox と同一矩形なので落とす
(切り抜きの効果が無いうえ、`<clipPath>` が 86 件ぶん無駄に増える)。

### `extended=True` への切り替えが安全であることの確認

`page.get_drawings()` と `page.get_drawings(extended=True)` の `type in ("f","s","fs")` 部分は、
対象 PDF の 16 ページすべてで seqno・rect・fill・items 件数が一致した (差異 0)。
よって既存の `get_drawings()` 呼び出しを `extended=True` へ置き換え、`clip` / `group` をスキップする形で
**1 回の呼び出しに統合してよい** (2 回呼ぶと 1 ページあたり 600 件超の走査が二重になる)。

### 修正後の期待

螺旋のグラデーションが螺旋形に切り抜かれて出力され、下の単色パスを覆わない。

---

## ファイル構成

- 変更 `src/model/elements.py`: `ImageElement` に `clip_d: str = ""` を追加する。
- 変更 `src/export/svg_exporter.py`: `<defs>` へ `<clipPath>` を集約し、`<image>` に `clip-path` を付ける。
- 変更 `src/engine/pdf_engine.py`: `get_drawings(extended=True)` へ統合し、clip 索引を作って `ImageElement.clip_d` を埋める。
- 変更 `test/conftest.py`: クリップ付き画像を持つ合成 PDF の fixture を追加する。
- 変更 `test/test_export_clip.py`: エクスポータ側のテストを追加する。
- 新規 `test/test_image_clip.py`: エンジン側 (PDF → モデル) のテストを置く。
- 変更 `docs/pdf-to-svg/src/設計正典.md`: 中核原則へ 1 項を追記する。

---

### Task 1: エクスポータが `ImageElement.clip_d` を `<clipPath>` として出力する

**Files:**
- Modify: `src/model/elements.py:202-207`
- Modify: `src/export/svg_exporter.py:322-337` (`_image_tag`)、`src/export/svg_exporter.py:96-163` (`page_to_svg`)、`src/export/svg_exporter.py:231-233` (`_element_to_svg` の画像分岐)
- Test: `test/test_export_clip.py`

**Interfaces:**
- Consumes: なし (この計画の最初のタスク)
- Produces:
  - `ImageElement.clip_d: str` — SVG path の `d` 文字列。空文字列はクリップ無し。
  - `svg_exporter._image_clip_id(d: str) -> str` — `d` から決定的な `<clipPath>` id を作る。
  - `svg_exporter._image_tag(rect: Rect, data: bytes, ext: str, clip_id: Optional[str] = None) -> str`

- [ ] **Step 1: 失敗するテストを書く**

`test/test_export_clip.py` の末尾へ追記する。`Page` / `ImageElement` / `Rect` / `re` / `_png()` は
このファイルに既にあるので、import の追加は不要。

```python
def _page_with_clipped_image() -> Page:
    """クリップ形状を持つ画像 1 枚だけのページ。"""
    pg = Page(index=0, width_pt=100, height_pt=100)
    pg.elements = [
        ImageElement(
            bbox=Rect(10, 10, 40, 40),
            rect=Rect(10, 10, 40, 40),
            img_bytes=_png((255, 0, 0)),
            ext="png",
            z=0,
            clip_d="M10,10 L50,10 L50,50 Z",
        )
    ]
    return pg


def test_image_clip_emits_clippath_and_reference():
    """クリップ形状を持つ画像は <defs><clipPath> を伴い、<image> がそれを参照する。"""
    svg = page_to_svg(_page_with_clipped_image())
    cid = re.search(r'<clipPath id="(imgclip-[0-9a-f]+)">', svg).group(1)
    assert f'<clipPath id="{cid}"><path d="M10,10 L50,10 L50,50 Z"/></clipPath>' in svg
    assert f'clip-path="url(#{cid})"' in svg
    # <image> は単一タグのままであること (annotate の data-el 差し込みが開きタグを壊さない)
    assert svg.count("<image ") == 1


def test_image_without_clip_has_no_clippath():
    """clip_d が空の画像は従来どおり <clipPath> を作らない (既存出力を変えない)。"""
    pg = _page_with_clipped_image()
    pg.elements[0].clip_d = ""
    svg = page_to_svg(pg)
    assert "clipPath" not in svg
    assert "clip-path" not in svg


def test_same_clip_shape_is_defined_once():
    """同じ形状を使う画像が複数あっても <clipPath> の定義は 1 個にまとまる。"""
    from copy import deepcopy

    pg = _page_with_clipped_image()
    dup = deepcopy(pg.elements[0])
    dup.z = 2
    pg.elements.append(dup)
    svg = page_to_svg(pg)
    assert svg.count("<clipPath ") == 1
    assert svg.count("clip-path=") == 2


def test_image_clip_id_is_deterministic():
    """同一モデルからは常に同一の id が出る (決定的出力の不変則)。"""
    a = page_to_svg(_page_with_clipped_image())
    b = page_to_svg(_page_with_clipped_image())
    assert a == b


def test_image_clip_survives_annotate():
    """annotate=True でも <image> の開きタグに data-el が入り、clip-path が残る。"""
    svg = page_to_svg(_page_with_clipped_image(), annotate=True)
    assert re.search(r'<image data-el="\d+" ', svg)
    assert "clip-path=" in svg
```

- [ ] **Step 2: テストを走らせて失敗を確認する**

```
py -3.13 -m pytest pdf-to-svg/test/test_export_clip.py -v
```

期待: `test_image_clip_emits_clippath_and_reference` が `TypeError: ImageElement.__init__() got an unexpected keyword argument 'clip_d'` で失敗する。

- [ ] **Step 3: `ImageElement` に `clip_d` を足す**

`src/model/elements.py` の `ImageElement` (202 行付近) へ 1 フィールド追加する。

```python
class ImageElement(Element):
    kind: str = "image"
    rect: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    # raw 画像バイト列を base64 で SVG に埋め込む。ext は "png"/"jpeg" 等。
    img_bytes: bytes = b""
    ext: str = "png"
    # PDF のクリップパス (`W n`) 由来の切り抜き形状。SVG path の "d" 文字列で、
    # 空文字列はクリップ無し。シェーディングを螺旋等の形へ切り抜いて描く PDF では、
    # これが無いと bbox の矩形がそのまま貼られ、下の図形を覆い隠す。
    clip_d: str = ""
```

- [ ] **Step 4: エクスポータでクリップを出力する**

`src/export/svg_exporter.py` を 3 箇所直す。

(a) ファイル先頭の import に `hashlib` を足し、`_clip_id` の下へ id 生成関数を置く。

```python
def _image_clip_id(d: str) -> str:
    """画像のクリップ形状ごとに決定的な ``<clipPath>`` id を作る。

    同じ形状は同じ id になるので、複数の画像が同じ切り抜きを共有しても定義は 1 個で済む。
    座標を id へ並べる ``_clip_id`` と違い、path の ``d`` は任意長になりうるのでダイジェストを使う
    (id の長さを一定に保つため。値そのものは決定的で、同一モデルからは常に同じ id が出る)。
    """
    return "imgclip-" + hashlib.sha1(d.encode("utf-8")).hexdigest()[:16]
```

(b) `page_to_svg` の、書き出し領域用 `<defs>` を出した直後 (`lines.append("<g " + ...)` の後、
「スキャン背景」のコメントの前) へ、画像クリップの `<defs>` を足す。

```python
    # 画像のクリップ形状はここで <defs> へまとめ、個々の <image> は url(#...) で参照する。
    # 要素タグを単一タグに保つための分離である (`_with_data_el` は開きタグの最初の空白へ
    # 属性を差し込むので、要素の直列化が <defs> で始まると data-el が <defs> に付いてしまう)。
    # 収集は描画と同じ交差判定で行う (書き出し領域の外にある画像の定義を残さない)。
    clip_defs: List[Tuple[str, str]] = []
    seen_clip_ids = set()
    for el in page.live_elements():
        if not isinstance(el, ImageElement) or not el.clip_d:
            continue
        if not _intersects_export(el.bbox, rect):
            continue
        cid = _image_clip_id(el.clip_d)
        if cid not in seen_clip_ids:
            seen_clip_ids.add(cid)
            clip_defs.append((cid, el.clip_d))
    if clip_defs:
        parts = ["<defs>"]
        for cid, d in clip_defs:
            parts.append(
                "<clipPath " + _attr("id", cid) + "><path " + _attr("d", d) + "/></clipPath>"
            )
        parts.append("</defs>")
        lines.append("".join(parts))
```

(c) `_element_to_svg` の画像分岐と `_image_tag` にクリップ参照を通す。

```python
    if isinstance(el, ImageElement):
        data, ext = image_fn(el.img_bytes, el.ext)
        clip_id = _image_clip_id(el.clip_d) if el.clip_d else None
        return _image_tag(el.rect, data, ext, clip_id)
```

```python
def _image_tag(rect: Rect, data: bytes, ext: str, clip_id: Optional[str] = None) -> str:
    b64 = base64.b64encode(data).decode("ascii")
    href = f"data:{_mime(ext)};base64,{b64}"
    clip = " " + _attr("clip-path", "url(#" + clip_id + ")") if clip_id else ""
    return (
        "<image "
        + _attr("x", _fmt(rect.x))
        + " "
        + _attr("y", _fmt(rect.y))
        + " "
        + _attr("width", _fmt(rect.w))
        + " "
        + _attr("height", _fmt(rect.h))
        + " "
        + _attr("xlink:href", href)
        + clip
        + "/>"
    )
```

- [ ] **Step 5: テストが通ることを確認する**

```
py -3.13 -m pytest pdf-to-svg/test/test_export_clip.py -v
```

期待: 追加した 5 件を含め全件 PASS。

- [ ] **Step 6: 既存の出力不変則が壊れていないことを確認する**

```
py -3.13 -m pytest pdf-to-svg
```

期待: 全件 PASS (`clip_d` の既定値が空なので、既存モデルの出力は 1 バイトも変わらない)。

- [ ] **Step 7: コミット**

```bash
git add pdf-to-svg/src/model/elements.py pdf-to-svg/src/export/svg_exporter.py pdf-to-svg/test/test_export_clip.py
git commit -m "$(cat <<'EOF'
feat(export): 画像のクリップ形状を <clipPath> として書き出す

ImageElement に clip_d (SVG path の d 文字列) を足し、エクスポータが同一形状を
1 個の <clipPath> へまとめて <defs> に出し、各 <image> から clip-path で参照する。
clip_d が空のときの出力は従来と完全に一致する。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HNeK1UF1dG6BNd8YpAoypQ
EOF
)"
```

---

### Task 2: エンジンがクリップを引き当てて `clip_d` を埋める

**Files:**
- Modify: `test/conftest.py` (fixture 追加)
- Create: `test/test_image_clip.py`
- Modify: `src/engine/pdf_engine.py:157-235` (`_extract_page`)、`src/engine/pdf_engine.py:421-433` (`_image_element`)

**Interfaces:**
- Consumes: `ImageElement.clip_d`(Task 1)
- Produces:
  - `pdf_engine._clip_index(drawings: list) -> dict`
  - `pdf_engine._clip_path_for(index: dict, bbox: Rect) -> str`
  - `_image_element(block: dict, z: int, clip_d: str = "") -> Optional[ImageElement]`

- [ ] **Step 1: fixture を追加する**

`test/conftest.py` の末尾 (JS ハーネス節の手前) へ足す。

```python
@pytest.fixture(scope="session")
def clipped_image_pdf() -> Path:
    """三角形のクリップパスで切り抜いた画像を 1 枚だけ持つ PDF。

    PyMuPDF には「クリップ付きで画像を貼る」API が無いため、画像を貼った後で
    ページのコンテンツストリームを `q ... W n ... Q` で包み直して作る
    (実 PDF がシェーディングを螺旋形へ切り抜いている構造の最小再現)。
    """
    FIXTURES.mkdir(exist_ok=True)
    path = FIXTURES / "clipped_image_sample.pdf"

    im_bytes = io.BytesIO()
    im = Image.new("RGB", (60, 60))
    for y in range(60):
        for x in range(60):
            im.putpixel((x, y), (255 - 4 * x, 30, 4 * x))
    im.save(im_bytes, format="PNG")

    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_image(fitz.Rect(50, 50, 150, 150), stream=im_bytes.getvalue())
    page.clean_contents()
    xref = page.get_contents()[0]
    src = doc.xref_stream(xref)
    # 三角形 (50,50)-(150,50)-(150,150) でクリップする。bbox は画像と同一の矩形になる。
    doc.update_stream(xref, b"q 50 50 m 150 50 l 150 150 l h W n\n" + src + b"\nQ\n")
    doc.save(str(path))
    doc.close()
    return path
```

`conftest.py` の import 群に `io` と `from PIL import Image` を足すこと (現状はどちらも無い)。

- [ ] **Step 2: 失敗するテストを書く**

`test/test_image_clip.py` を新規作成する。

```python
"""PDF のクリップパス (`W n`) で切り抜かれた画像を、SVG でも同じ形に切り抜く。

シェーディングを螺旋等の形へ切り抜いて描く PDF では、クリップを落とすと bbox の矩形が
そのまま貼られ、下に正しく描かれている図形を不透明な矩形が覆い隠す。
"""
from __future__ import annotations

from engine.pdf_engine import load_document
from export.svg_exporter import page_to_svg
from model.elements import ImageElement


def _images(page):
    return [e for e in page.live_elements() if isinstance(e, ImageElement)]


def test_clipped_image_gets_clip_path(clipped_image_pdf):
    """クリップ下で描かれた画像には clip_d が入る。"""
    doc = load_document(str(clipped_image_pdf))
    imgs = _images(doc.pages[0])
    assert len(imgs) == 1
    assert imgs[0].clip_d != ""
    # 三角形の 3 頂点が d に現れる (M/L の並びは _items_to_path_d の出力形式)
    assert "M50,50" in imgs[0].clip_d
    assert "L150,50" in imgs[0].clip_d


def test_clipped_image_svg_has_clippath(clipped_image_pdf):
    """書き出した SVG に <clipPath> が出て、<image> がそれを参照する。"""
    doc = load_document(str(clipped_image_pdf))
    svg = page_to_svg(doc.pages[0])
    assert "<clipPath id=\"imgclip-" in svg
    assert "clip-path=\"url(#imgclip-" in svg


def test_unclipped_image_has_no_clip(scanned_pdf):
    """クリップの無い画像には clip_d が入らない (既存 PDF の出力を変えない)。"""
    doc = load_document(str(scanned_pdf))
    for pg in doc.pages:
        for img in _images(pg):
            assert img.clip_d == ""


def test_rect_only_clip_is_ignored(vector_pdf):
    """items が矩形 1 個だけの clip は無視する (画像 bbox と同じで切り抜きの効果が無い)。

    ページ全体を覆う既定のクリップは全 PDF に付くため、これを拾うと無意味な
    <clipPath> が画像の数だけ増える。
    """
    doc = load_document(str(vector_pdf))
    svg = page_to_svg(doc.pages[0])
    assert "imgclip-" not in svg
```

- [ ] **Step 3: テストを走らせて失敗を確認する**

```
py -3.13 -m pytest pdf-to-svg/test/test_image_clip.py -v
```

期待: `test_clipped_image_gets_clip_path` が `assert '' != ''` (clip_d が空) で失敗する。

- [ ] **Step 4: エンジンにクリップ索引を実装する**

`src/engine/pdf_engine.py` の定数群 (48 行付近の `MAX_PAGE_ELEMENTS` の並び) へ足す。

```python
# クリップ 1 個あたりの item 数上限。PDF 作成者 (= 攻撃者) が決められる値なので、
# 巨大なパスで `d` 文字列を膨らませる形を止める。超過したクリップは
# **適用せず** 従来どおり矩形で貼る (degrade。読み込み自体は止めない)。
MAX_CLIP_ITEMS = 1_000
```

`_drawing_elements` の下 (`_items_to_path_d` の後) へ 2 関数を足す。

```python
def _clip_index(drawings: list) -> dict:
    """`get_drawings(extended=True)` の `type="clip"` を scissor 矩形で索引する。

    画像ブロック (`get_text("dict")`) はクリップ形状を持たないので、bbox が一致する
    clip を引き当てて紐づける。キーは座標を小数第 1 位で丸めた 4 つ組で、線形走査
    (画像数 × clip 数) を避ける — どちらの件数も PDF 作成者が決めるため、総当たりは
    O(n^2) が素通りする (`_SeqnoIndex` と同じ理由)。

    items が矩形 1 個だけの clip は索引へ入れない。画像 bbox と同一の矩形で切り抜きの
    効果が無く (ページ全体の既定クリップがこの形)、拾うと無意味な `<clipPath>` が
    画像の数だけ増えるだけだからである。
    """
    index: dict = {}
    for d in drawings:
        if d.get("type") != "clip":
            continue
        items = d.get("items") or []
        if len(items) == 1 and items[0][0] == "re":
            continue
        scissor = d.get("scissor")
        if scissor is None:
            continue
        key = (
            round(scissor.x0, 1), round(scissor.y0, 1),
            round(scissor.x1, 1), round(scissor.y1, 1),
        )
        index.setdefault(key, []).append(d)
    return index


def _clip_path_for(index: dict, bbox: Rect) -> str:
    """画像 bbox に一致するクリップの SVG path `d` を返す。無ければ空文字列。

    候補が複数あるときは最も内側 (`level` が最大) の 1 個を採る。SVG の `<clipPath>` は
    サブパスを足すと**和集合**になり、入れ子クリップの交差にはならないため、複数を
    1 個へ畳むと切り抜きが広がってしまう (最内だけを採るほうが、広げるより安全側)。
    """
    key = (round(bbox.x, 1), round(bbox.y, 1), round(bbox.x1, 1), round(bbox.y1, 1))
    cands = index.get(key)
    if not cands:
        return ""
    best = max(cands, key=lambda c: c.get("level") or 0)
    items = best.get("items") or []
    if len(items) > MAX_CLIP_ITEMS:
        return ""
    return _items_to_path_d(items, True)
```

- [ ] **Step 5: `_extract_page` を `extended=True` の 1 回呼び出しへ統合する**

`_extract_page` の `text_dict = page.get_text("dict")` の直前へ、描画の取得と索引作成を移す。

```python
    # 描画は `extended=True` で 1 回だけ取る。clip / group も返るようになるが、
    # `type in ("f","s","fs")` の内容は `get_drawings()` と一致する (実測)。
    # 2 回呼ぶと 1 ページ数百件の走査が二重になるため、ここで 1 本にまとめる。
    drawings = page.get_drawings(extended=True)
    clip_index = _clip_index(drawings)
```

画像ブロックの分岐を差し替える。

```python
        if block.get("type") == 1:  # 画像ブロック
            bbox = Rect.from_xyxy(*block["bbox"])
            # 照合失敗時は -1 (背景扱い): 画像は下敷きであることが大半
            seqno = image_index.match(bbox, -1)
            img = _image_element(block, seqno * _Z_TIER + seq, _clip_path_for(clip_index, bbox))
            if img is not None and sink.add(img):
                seq += 1
```

ページ末尾の描画ループを、取得済みリストを使う形へ変える。

```python
    for drawing in drawings:
        if sink.full:
            break
        if drawing.get("type") not in ("f", "s", "fs"):
            continue  # clip / group は要素ではない (クリップは画像へ紐づけ済み)
        seqno = int(drawing.get("seqno") or 0)
        for el in _drawing_elements(drawing, seqno * _Z_TIER + seq):
            if not sink.add(el):
                break
            seq += 1
```

`_image_element` にクリップ形状を渡せるようにする。

```python
def _image_element(block: dict, z: int, clip_d: str = "") -> Optional[ImageElement]:
    """画像ブロックを ImageElement へ変換する。バイト列を持たないブロックは None。

    ``clip_d`` は PDF のクリップパス由来の切り抜き形状 (無いときは空文字列)。
    """
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
        clip_d=clip_d,
    )
```

- [ ] **Step 6: テストが通ることを確認する**

```
py -3.13 -m pytest pdf-to-svg/test/test_image_clip.py -v
```

期待: 4 件すべて PASS。

- [ ] **Step 7: 既存テストの全件 PASS を確認する**

```
py -3.13 -m pytest pdf-to-svg
```

期待: 全件 PASS。落ちた場合は `get_drawings(extended=True)` への切り替えで描画要素の件数が変わっていないかを
`test_pipeline.py::test_extract_kinds` の失敗内容から確認する。

- [ ] **Step 8: コミット**

```bash
git add pdf-to-svg/src/engine/pdf_engine.py pdf-to-svg/test/conftest.py pdf-to-svg/test/test_image_clip.py
git commit -m "$(cat <<'EOF'
fix(engine): クリップ下で描かれた画像に切り抜き形状を持たせる

get_drawings(extended=True) の type="clip" を scissor 矩形で索引し、画像ブロックの
bbox と一致するクリップを ImageElement.clip_d へ載せる。シェーディングを螺旋形へ
切り抜いて描く PDF で、切り抜きが失われた不透明な矩形が下の図形を覆い隠していた。

描画の取得は extended=True の 1 回へ統合する (f/s/fs の内容は従来と一致する)。

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HNeK1UF1dG6BNd8YpAoypQ
EOF
)"
```

---

### Task 3: クリップの資源上限を退行ガードで固定する

**Files:**
- Modify: `test/test_resource_limits.py`
- Modify: `src/engine/pdf_engine.py` (Task 2 で入れた `MAX_CLIP_ITEMS` の確認のみ。実装変更は不要な想定)

**Interfaces:**
- Consumes: `pdf_engine.MAX_CLIP_ITEMS`、`pdf_engine._clip_path_for`
- Produces: なし

- [ ] **Step 1: 失敗するテストを書く**

`test/test_resource_limits.py` の末尾へ追記する。

```python
def test_clip_over_item_limit_degrades_to_no_clip():
    """item 数が上限を超えるクリップは適用しない (読み込みは止めず矩形で貼る)。

    クリップの item 数は PDF 作成者が決められるので、巨大なパスで `d` 文字列を
    膨らませられないようにする。
    """
    import pymupdf

    from engine import pdf_engine
    from model.elements import Rect

    box = pymupdf.Rect(0, 0, 10, 10)
    p = pymupdf.Point(0, 0)
    items = [("l", p, p)] * (pdf_engine.MAX_CLIP_ITEMS + 1)
    index = pdf_engine._clip_index([
        {"type": "clip", "scissor": box, "items": items, "level": 1},
    ])
    assert pdf_engine._clip_path_for(index, Rect.from_xyxy(0, 0, 10, 10)) == ""


def test_clip_within_item_limit_is_applied():
    """上限内のクリップはそのまま適用する (上限が本来の経路を殺していないこと)。"""
    import pymupdf

    from engine import pdf_engine
    from model.elements import Rect

    box = pymupdf.Rect(0, 0, 10, 10)
    items = [
        ("l", pymupdf.Point(0, 0), pymupdf.Point(10, 0)),
        ("l", pymupdf.Point(10, 0), pymupdf.Point(10, 10)),
    ]
    index = pdf_engine._clip_index([
        {"type": "clip", "scissor": box, "items": items, "level": 1},
    ])
    assert pdf_engine._clip_path_for(index, Rect.from_xyxy(0, 0, 10, 10)) != ""


def test_innermost_clip_wins_when_several_match():
    """同じ矩形の候補が複数あるときは最も内側 (level 最大) を採る。

    SVG の <clipPath> はサブパスを足すと和集合になり交差にならないので、
    複数を畳むと切り抜きが広がってしまう。
    """
    import pymupdf

    from engine import pdf_engine
    from model.elements import Rect

    box = pymupdf.Rect(0, 0, 10, 10)
    outer = [("l", pymupdf.Point(0, 0), pymupdf.Point(10, 0)),
             ("l", pymupdf.Point(10, 0), pymupdf.Point(10, 10))]
    inner = [("l", pymupdf.Point(1, 1), pymupdf.Point(9, 1)),
             ("l", pymupdf.Point(9, 1), pymupdf.Point(9, 9))]
    index = pdf_engine._clip_index([
        {"type": "clip", "scissor": box, "items": outer, "level": 1},
        {"type": "clip", "scissor": box, "items": inner, "level": 3},
    ])
    assert "M1,1" in pdf_engine._clip_path_for(index, Rect.from_xyxy(0, 0, 10, 10))
```

- [ ] **Step 2: テストを走らせる**

```
py -3.13 -m pytest pdf-to-svg/test/test_resource_limits.py -v
```

期待: Task 2 の実装で 3 件とも PASS する。落ちた場合は `_clip_path_for` の上限判定・`level` 選択を直す
(テストが仕様。実装をテストへ合わせる)。

- [ ] **Step 3: コミット**

```bash
git add pdf-to-svg/test/test_resource_limits.py
git commit -m "$(cat <<'EOF'
test(engine): クリップの item 数上限と最内選択を退行ガードで固定する

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HNeK1UF1dG6BNd8YpAoypQ
EOF
)"
```

---

### Task 4: 実 PDF での目視確認と設計正典への追記

**Files:**
- Modify: `docs/pdf-to-svg/src/設計正典.md` (「中核原則」節)

**Interfaces:**
- Consumes: Task 1〜3 の実装
- Produces: なし

- [ ] **Step 1: 実 PDF で修正を目視確認する**

作業用ディレクトリ (リポジトリ外) で次を実行し、螺旋図が矩形でなく螺旋として描かれることを確認する。
PDF は `https://www.smtam.jp/fund/pdf/_id_140823_type_k.pdf` (8 ページ目 = `doc.pages[7]`)。

```python
import sys, os
sys.path.insert(0, os.path.abspath("pdf-to-svg/src"))
from engine.pdf_engine import load_document
from export.svg_exporter import page_to_svg

doc = load_document("smtam.pdf")
for gray in (False, True):
    open(f"p7_{gray}.svg", "w", encoding="utf8").write(page_to_svg(doc.pages[7], grayscale=gray))
```

出力した SVG をブラウザで開き、螺旋の帯が交差して連続していること (矩形の積み重ねでないこと) を確認する。

- [ ] **Step 2: 設計正典へ 1 項を足す**

`docs/pdf-to-svg/src/設計正典.md` の「中核原則」節の末尾へ追記する。

```markdown
- **画像のクリップ形状はモデルへ持ち、SVG の `<clipPath>` で再現する**: `get_text("dict")` の
  画像ブロックは**クリップ形状を返さない**ため、bbox の矩形へそのまま貼ると、シェーディングを
  螺旋等の形へ切り抜いて描く PDF で不透明な矩形が下の図形を覆い隠す。`get_drawings(extended=True)`
  の `type="clip"` を `scissor` 矩形で索引し、画像 bbox と一致するものを `ImageElement.clip_d`
  (SVG path の `d`) へ載せる。候補が複数あるときは**最も内側** (`level` 最大) の 1 個だけを採る
  (`<clipPath>` はサブパスを足すと和集合になり、入れ子クリップの交差にはならないため、畳むと
  切り抜きが広がる)。items が矩形 1 個だけの clip は無視する (画像 bbox と同一で効果が無く、
  ページ全体の既定クリップがこの形)。item 数は `MAX_CLIP_ITEMS` で切り、超過は
  **クリップ無しへ degrade** する (読み込みは止めない)。
```

- [ ] **Step 3: 全テストを走らせる**

```
py -3.13 -m pytest pdf-to-svg
```

期待: 全件 PASS。

- [ ] **Step 4: コミット**

```bash
git add docs/pdf-to-svg/src/設計正典.md
git commit -m "$(cat <<'EOF'
docs(pdf-to-svg): 画像クリップ形状の再現を設計正典へ追記する

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01HNeK1UF1dG6BNd8YpAoypQ
EOF
)"
```

---

## 検討したが採らなかった案

- **シェーディング由来の画像ブロックを捨て、下の単色パスに任せる**: 変更は小さいが、グラデーションが
  平坦色になり、背景がシェーディングだけで描かれている図では絵そのものが消える。
- **z 順だけ直して画像を背面へ回す**: 螺旋は見えるようになるが矩形は残り、下の要素を隠す問題が別の場所へ移るだけ。
- **該当領域を PyMuPDF でラスタ化して貼る**: 見た目は原本一致になるが、領域内の文字ごと焼き込まれ、
  「文字は文字のまま」という本プロジェクトの中核原則に反する (Office 貼り付け・印刷時の品質が落ちる)。
- **クリップをベクタ要素 (パス・文字) にも適用する**: 今回の症状には不要 (YAGNI)。ベクタ側は
  クリップ無しでも形が破綻していない。必要になった時点で `Element` 共通のフィールドへ引き上げる。
