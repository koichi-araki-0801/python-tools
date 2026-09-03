# スチュワードシップ図グレースケール書き出しモード 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 運用報告書 PDF から「当社のスチュワードシップ活動」の図だけを文字アンカーで検出し、切り出してグレースケール化したベクタ SVG を書き出す専用モードを pdf-to-svg に追加する。

**Architecture:** 図検出（`model/figure_detect.py`）・グレー化（`export/grayscale.py`）・切り出し（`page_to_svg` の `clip`）はすべてモデルを変更しない純粋関数／書き出しオプションとして実装し、モードはクライアント（`state.js` の `S.gray`）が持って毎リクエスト引数で渡す。UI は手順 1 のチェックボックスで手順 2・3 を飛ばし、手順 4 を「レール + グレープレビュー + 候補矩形 + 書き出しシート」の 3 ペインに切り替える。

**Tech Stack:** Python 3.13（標準ライブラリ + Pillow 12.3 + 既存 PyMuPDF は engine 隔離のまま）、素の ES module JS、pytest（Playwright + Edge channel で JS 単体・E2E）。

**Spec:** `docs/superpowers/specs/2026-09-04-pdf-to-svg-stewardship-figure-gray-design.md`

## Global Constraints

- Python は常に `py -3.13` で起動し、pytest は対象ディレクトリを個別指定する（`py -3.13 -m pytest pdf-to-svg`）。一括実行・xdist 禁止。
- `fitz`（PyMuPDF）を import してよいのは `src/engine/pdf_engine.py` だけ。新モジュール `model/figure_detect.py` と `export/grayscale.py` は import しない。
- SVG 属性は `_attr` / `quoteattr` 経由でのみ組み立てる。`src/export/` 配下で `="{...}"` 形の f-string を書くと `test_export_escaping.py` が落ちる。
- `page_to_svg` の既定引数（`annotate=False, grayscale=False, clip=None`）の出力は従来と**バイト一致**を保つ（`test_pipeline.py` が固定）。
- コミットメッセージ・ドキュメント・コードコメントは通常の日本語で書く。コミット末尾に次の 2 行を付ける。
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Atsc5YmN4J2ka1yLHquFKH
  ```
- コミットすると post-commit フックが自動 push し、pre-push で pytest 一式（約 100 秒）が走る。失敗したら push が止まるので、その出力を読んで直す。
- 実 PDF（smtam.jp の報告書）はテストフィクスチャに入れない。合成 PDF・合成 `Page` だけを使う。
- 作業ブランチ: `feat/pdf-to-svg-stewardship-figure-gray`（作成済み・upstream 設定済み）。

## ファイル構成

| ファイル | 役割 | 状態 |
|---|---|---|
| `pdf-to-svg/src/export/grayscale.py` | 色 hex／CSS 色名／画像バイトをグレーへ変換する純粋関数 | 新規 |
| `pdf-to-svg/src/model/figure_detect.py` | 文字アンカーでスチュワードシップ図の矩形を返す純粋関数 | 新規 |
| `pdf-to-svg/src/export/svg_exporter.py` | `page_to_svg(grayscale, clip)` オプション。塗り変換関数を各出力関数へ引数で渡す | 変更 |
| `pdf-to-svg/src/web/rpc_methods.py` | `figureCandidates` 新設。`pageSvg` / `exportSvg` に `grayscale` / `clip` / `figIndex` | 変更 |
| `pdf-to-svg/resources/web/state.js` | `S.gray` / `S.figCand` / `S.figSel`、遷移ヘルパ、`exportFigureList`、`zipName` | 変更 |
| `pdf-to-svg/resources/web/figure.js` | グレーモード専用の DOM 描画（レール・候補矩形オーバーレイ・ハンドル／ドラッグ） | 新規 |
| `pdf-to-svg/resources/web/app.js` | チェックボックス配線、遷移分岐、手順 4 の 3 ペイン描画、書き出しの図分岐 | 変更 |
| `pdf-to-svg/resources/web/index.html` | 手順 1 のチェックボックス、ステップバーの注記、手順 4 のレール／キャンバス／書き出し範囲 | 変更 |
| `pdf-to-svg/resources/web/styles.css` | `.modebox` / `.fig-cand` / グレーモードのステップバーと手順 4 レイアウト | 変更 |
| `pdf-to-svg/test/test_grayscale.py` | 色・画像変換 | 新規 |
| `pdf-to-svg/test/test_export_clip.py` | `grayscale` / `clip` の出力と既定バイト一致 | 新規 |
| `pdf-to-svg/test/test_figure_detect.py` | 合成 `Page` での検出 | 新規 |
| `pdf-to-svg/test/test_web_rpc.py` | RPC 追加分 | 変更 |
| `pdf-to-svg/test/test_pdftosvg_state_js.py` | `state.js` 追加分 | 変更 |
| `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` | グレーモードの E2E（合成 PDF を fitz で生成） | 変更 |
| `docs/pdf-to-svg/src/設計正典.md` ほか docs 4 冊 + `README.md` | 文書更新 | 変更 |

---

### Task 1: 色のグレー変換 `to_gray_color`

**Files:**
- Create: `pdf-to-svg/src/export/grayscale.py`
- Test: `pdf-to-svg/test/test_grayscale.py`

**Interfaces:**
- Consumes: `model.elements.sanitize_color(value) -> str | None`（許可形以外は `ValueError`）
- Produces: `to_gray_color(value: str | None) -> str | None`。`#rrggbb`（alpha 付きは `#rrggbbaa`）の灰色 hex、`none` / `currentColor` / `None` は素通し。

- [ ] **Step 1: 失敗するテストを書く**

```python
# pdf-to-svg/test/test_grayscale.py
"""色・画像のグレースケール変換 (``export/grayscale.py``)。

ベクタの色も画像も同じ Rec.601 の整数式で灰色にする。SVG フィルタを使わないのは、
Office がフィルタを無視してカラーのまま貼り付き、ブラウザ印刷が文字をラスタ化するため。
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from export import grayscale
from export.grayscale import to_gray_color, to_gray_image


def test_hex6_uses_rec601_integer_luma():
    # 255*299//1000 = 76 = 0x4c / 255*587//1000 = 149 = 0x95 / 255*114//1000 = 29 = 0x1d
    assert to_gray_color("#ff0000") == "#4c4c4c"
    assert to_gray_color("#00ff00") == "#959595"
    assert to_gray_color("#0000ff") == "#1d1d1d"
    assert to_gray_color("#ffffff") == "#ffffff"
    assert to_gray_color("#000000") == "#000000"


def test_short_hex_and_alpha_are_preserved():
    assert to_gray_color("#f00") == "#4c4c4c"
    assert to_gray_color("#f008") == "#4c4c4c88"
    assert to_gray_color("#ff000080") == "#4c4c4c80"


def test_named_color_is_resolved():
    assert to_gray_color("red") == "#4c4c4c"
    assert to_gray_color("White") == "#ffffff"


def test_passthrough_values():
    assert to_gray_color("none") == "none"
    assert to_gray_color("currentColor") == "currentColor"
    assert to_gray_color(None) is None


def test_rejects_what_sanitize_color_rejects():
    with pytest.raises(ValueError):
        to_gray_color("rgb(0,0,0)")
    with pytest.raises(ValueError):
        to_gray_color('#000"/><script>')
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg && py -3.13 -m pytest test/test_grayscale.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'export.grayscale'`）

- [ ] **Step 3: 最小実装を書く**

```python
# pdf-to-svg/src/export/grayscale.py
"""色と画像をグレースケールへ変換する純粋関数。

ベクタ要素の色 (``to_gray_color``) と埋め込み画像 (``to_gray_image``) を**同じ
Rec.601 の整数式** ``(R*299 + G*587 + B*114) // 1000`` で灰色にする (Pillow の
``convert("L")`` と同じ係数なので、文字・線と画像の明度が揃う)。

SVG フィルタ (``feColorMatrix``) を使わないのは意図的で、Office はフィルタを無視して
カラーのまま貼り付き、ブラウザの印刷はフィルタ領域を丸ごとラスタ化して文字を画像に
してしまう。色そのものを書き換えれば、どの消費側でも灰色のまま・文字は文字のままになる。

``fitz`` (PyMuPDF) には依存しない — AGPL 依存は ``engine/pdf_engine.py`` に隔離する。
"""
from __future__ import annotations

import functools
import io
import re
from typing import Optional, Tuple

from PIL import Image, ImageColor

from model.elements import sanitize_color

_HEX = re.compile(r"^#([0-9a-fA-F]{3,8})$")

# 画像 1 枚あたりの変換上限画素数。`engine/pdf_engine.py` の `MAX_RASTER_PIXELS` と同値だが、
# あちらは fitz を import するモジュールなので値を複製する (片方を変えたら両方)。
MAX_GRAY_IMAGE_PIXELS = 16_000_000


def _luma(r: int, g: int, b: int) -> int:
    return (r * 299 + g * 587 + b * 114) // 1000


def to_gray_color(value: Optional[str]) -> Optional[str]:
    """``sanitize_color`` が許す色を灰色 hex にする。``none`` / ``currentColor`` / ``None`` は素通し。

    許可形以外は ``sanitize_color`` と同じく ``ValueError`` (出口の関門をここで緩めない)。
    Pillow が知らない CSS 色名は変換せずそのまま返す (色は残るが、例外で書き出しを止めない)。
    """
    v = sanitize_color(value)
    if v is None or v in ("none", "currentColor"):
        return v
    m = _HEX.match(v)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        alpha = h[6:8].lower()
    else:
        try:
            r, g, b = ImageColor.getrgb(v.lower())[:3]
        except ValueError:
            return v
        alpha = ""
    y = _luma(r, g, b)
    return f"#{y:02x}{y:02x}{y:02x}{alpha}"
```

- [ ] **Step 4: 通ることを確認する**

Run: `cd pdf-to-svg && py -3.13 -m pytest test/test_grayscale.py -v`
Expected: 5 passed

- [ ] **Step 5: コミット**

```bash
git add pdf-to-svg/src/export/grayscale.py pdf-to-svg/test/test_grayscale.py
git commit -m "feat(pdf-to-svg): 色を Rec.601 でグレースケール化する to_gray_color を追加"
```

---

### Task 2: 画像のグレー変換 `to_gray_image`

**Files:**
- Modify: `pdf-to-svg/src/export/grayscale.py`
- Test: `pdf-to-svg/test/test_grayscale.py`

**Interfaces:**
- Produces: `to_gray_image(img_bytes: bytes, ext: str) -> tuple[bytes, str]`。変換できたら `(PNG バイト, "png")`、上限超過・デコード不能は `(原本, ext)`。`functools.lru_cache(maxsize=16)` 付き。

- [ ] **Step 1: 失敗するテストを追加する**

```python
# pdf-to-svg/test/test_grayscale.py に追記


def _png(mode: str, color, size=(2, 2)) -> bytes:
    im = Image.new(mode, size, color)
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def test_rgb_image_becomes_L_png_with_same_luma():
    data, ext = to_gray_image(_png("RGB", (255, 0, 0)), "png")
    assert ext == "png"
    with Image.open(io.BytesIO(data)) as im:
        assert im.mode == "L"
        assert im.getpixel((0, 0)) == 76  # to_gray_color("#ff0000") の 0x4c と一致


def test_rgba_image_keeps_alpha_as_LA():
    data, _ = to_gray_image(_png("RGBA", (0, 255, 0, 128)), "png")
    with Image.open(io.BytesIO(data)) as im:
        assert im.mode == "LA"
        assert im.getpixel((0, 0)) == (149, 128)


def test_jpeg_input_is_reencoded_as_png():
    im = Image.new("RGB", (2, 2), (0, 0, 255))
    out = io.BytesIO()
    im.save(out, format="JPEG")
    data, ext = to_gray_image(out.getvalue(), "jpeg")
    assert ext == "png"
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_undecodable_bytes_fall_back_to_original():
    junk = b"not an image at all"
    assert to_gray_image(junk, "png") == (junk, "png")


def test_oversized_image_falls_back_to_original(monkeypatch):
    monkeypatch.setattr(grayscale, "MAX_GRAY_IMAGE_PIXELS", 3)
    src = _png("RGB", (10, 20, 30), size=(2, 2))  # 4 画素 > 3
    assert to_gray_image(src, "png") == (src, "png")


def test_conversion_is_cached_per_bytes():
    src = _png("RGB", (1, 2, 3), size=(3, 3))
    to_gray_image.cache_clear()
    to_gray_image(src, "png")
    to_gray_image(src, "png")
    assert to_gray_image.cache_info().hits == 1
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg && py -3.13 -m pytest test/test_grayscale.py -v`
Expected: 新規 6 件が FAIL（`ImportError: cannot import name 'to_gray_image'`）

- [ ] **Step 3: 実装を追加する**

```python
# pdf-to-svg/src/export/grayscale.py の末尾に追記


@functools.lru_cache(maxsize=16)
def to_gray_image(img_bytes: bytes, ext: str) -> Tuple[bytes, str]:
    """埋め込み画像を灰色 PNG にする。変換できないときは原本を返す (degrade)。

    画像バイトは PDF 由来 = 攻撃者が用意できる入力なので、デコードの前に画素数を
    ``MAX_GRAY_IMAGE_PIXELS`` で切る (``Image.open`` はヘッダしか読まないので寸法は
    デコード前に分かる)。壊れた画像・巨大画像は**原本をそのまま返し**、例外を外へ
    出さない — 1 枚の画像で書き出し全体を止めない。
    キャッシュはバイト列そのものをキーにする (プレビューと書き出しで同じ画像を何度も
    変換しないため)。
    """
    try:
        with Image.open(io.BytesIO(img_bytes)) as im:
            if im.width * im.height > MAX_GRAY_IMAGE_PIXELS:
                return img_bytes, ext
            has_alpha = im.mode in ("RGBA", "LA", "PA") or (
                im.mode == "P" and "transparency" in im.info
            )
            gray = im.convert("LA" if has_alpha else "L")
            out = io.BytesIO()
            gray.save(out, format="PNG")
            return out.getvalue(), "png"
    except Exception:  # noqa: BLE001 - 壊れた画像は原本へ倒す (上記 docstring)
        return img_bytes, ext
```

- [ ] **Step 4: 通ることを確認する**

Run: `cd pdf-to-svg && py -3.13 -m pytest test/test_grayscale.py -v`
Expected: 11 passed

- [ ] **Step 5: 配布物に Pillow が入ることを確認する**

Run: `grep -n -i "exclude\|PIL" pdf-to-svg/scripts/build.bat`
Expected: 出力なし（PIL を除外する指定が無い。PyInstaller は `from PIL import Image` を静的に拾う）。

- [ ] **Step 6: コミット**

```bash
git add pdf-to-svg/src/export/grayscale.py pdf-to-svg/test/test_grayscale.py
git commit -m "feat(pdf-to-svg): 埋め込み画像を Pillow で灰色 PNG にする to_gray_image を追加"
```

---

### Task 3: エクスポータの `grayscale` オプション

**Files:**
- Modify: `pdf-to-svg/src/export/svg_exporter.py`（`page_to_svg` / `_element_to_svg` / `_paint` / `_text_to_svg` / スキャン背景）
- Test: `pdf-to-svg/test/test_export_clip.py`

**Interfaces:**
- Consumes: `to_gray_color`, `to_gray_image`（Task 1・2）
- Produces: `page_to_svg(page, *, annotate=False, grayscale=False, clip=None) -> str`。内部関数は色変換 `color_fn: Callable[[str | None], str | None]` と画像変換 `image_fn: Callable[[bytes, str], tuple[bytes, str]]` を引数で受ける（`if grayscale` を各所に散らさない）。

- [ ] **Step 1: 失敗するテストを書く**

```python
# pdf-to-svg/test/test_export_clip.py
"""``page_to_svg`` の ``grayscale`` / ``clip`` オプション。

既定 (両方 OFF) は従来出力とバイト一致 (``test_pipeline.py`` が固定)。ON の出力は
決定的で、グレーは有彩色 hex を 1 つも残さず、clip は viewBox と要素の取捨に効く。
"""
from __future__ import annotations

import io
import re

from PIL import Image

from export.svg_exporter import page_to_svg
from model.document import Page, RasterBackground
from model.elements import ImageElement, LineElement, PathElement, Rect, RectElement, TextElement

# "#rrggbb" のうち r・g・b が揃っていないもの = 有彩色
_CHROMATIC = re.compile(r"#(?!([0-9a-f]{2})\1\1(?:[0-9a-f]{2})?[\"\s])[0-9a-f]{6}")


def _png(color) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (2, 2), color).save(out, format="PNG")
    return out.getvalue()


def _page() -> Page:
    pg = Page(index=0, width_pt=300, height_pt=200)
    pg.elements = [
        TextElement(bbox=Rect(10, 10, 60, 12), text="Hello", origin_x=10, origin_y=20, color="#3333cc", z=0),
        LineElement(bbox=Rect(10, 30, 100, 0), x0=10, y0=30, x1=110, y1=30, color="#ff0000", z=1),
        RectElement(bbox=Rect(200, 150, 50, 30), rect=Rect(200, 150, 50, 30), fill="#00ff00", stroke="#0000ff", z=2),
        PathElement(bbox=Rect(120, 120, 40, 40), d="M120 120 C 130 100 150 160 160 160", stroke="#ff8800", fill=None, z=3),
        ImageElement(bbox=Rect(20, 100, 40, 40), rect=Rect(20, 100, 40, 40), img_bytes=_png((255, 0, 0)), ext="png", z=4),
    ]
    return pg


def test_default_arguments_do_not_change_output():
    pg = _page()
    assert page_to_svg(pg) == page_to_svg(pg, grayscale=False, clip=None)
    assert 'fill="#3333cc"' in page_to_svg(pg)


def test_grayscale_leaves_no_chromatic_hex():
    svg = page_to_svg(_page(), grayscale=True)
    assert not _CHROMATIC.search(svg), svg
    # #3333cc → (51*299 + 51*587 + 204*114) // 1000 = 68 = 0x44
    assert 'fill="#444444"' in svg


def test_grayscale_converts_images_and_background():
    pg = _page()
    pg.background = RasterBackground(png_bytes=_png((0, 0, 255)), rect=Rect(0, 0, 300, 200))
    svg = page_to_svg(pg, grayscale=True)
    # 画像は 2 枚 (背景 + ImageElement) とも PNG の data URI で、中身は L モード
    hrefs = re.findall(r'xlink:href="data:image/png;base64,([^"]+)"', svg)
    assert len(hrefs) == 2
    import base64
    for b64 in hrefs:
        with Image.open(io.BytesIO(base64.b64decode(b64))) as im:
            assert im.mode == "L"


def test_grayscale_output_is_deterministic():
    pg = _page()
    assert page_to_svg(pg, grayscale=True) == page_to_svg(pg, grayscale=True)
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg && py -3.13 -m pytest test/test_export_clip.py -v`
Expected: `test_default_arguments_do_not_change_output` から FAIL（`TypeError: page_to_svg() got an unexpected keyword argument 'grayscale'`）

- [ ] **Step 3: エクスポータを書き換える**

`pdf-to-svg/src/export/svg_exporter.py` を次のように変更する。

import に追加:

```python
from typing import Callable, List, Optional, Tuple

from export import font_embed
from export.grayscale import to_gray_color, to_gray_image
```

`page_to_svg` を置き換える（`clip` はこの Task では受け取るだけで Task 4 で機能させる）:

```python
ColorFn = Callable[[Optional[str]], Optional[str]]
ImageFn = Callable[[bytes, str], Tuple[bytes, str]]


def _identity_image(data: bytes, ext: str) -> Tuple[bytes, str]:
    return data, ext


def page_to_svg(
    page: Page,
    *,
    annotate: bool = False,
    grayscale: bool = False,
    clip: Optional[Rect] = None,
) -> str:
    """Page を SVG 文字列へ。

    annotate=True のとき各要素タグに ``data-el="<id>"`` を付与する (Web UI が
    要素をクリック選択・ハイライトするため)。デフォルト False で従来出力と完全一致
    (テスト・書き出しは不変)。

    grayscale=True は色を出すすべての箇所 (塗り・線・文字・画像・スキャン背景) を
    ``export/grayscale.py`` で灰色にする。モデルは変更しない。変換関数を引数で
    各出力関数へ渡す形にしてあるのは、``if grayscale`` を出力箇所ごとに散らすと
    新しい色属性を足したときに取りこぼすため。

    clip は書き出し領域 (ページ座標の矩形)。None ならページ全体 (``export_rect``)。
    """
    color_fn: ColorFn = to_gray_color if grayscale else sanitize_color
    image_fn: ImageFn = to_gray_image if grayscale else _identity_image
    rect = clip if clip is not None else page.export_rect()
    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    viewbox = f"{_fmt(rect.x)} {_fmt(rect.y)} {_fmt(rect.w)} {_fmt(rect.h)}"
    lines.append(
        "<svg "
        + _attr("xmlns", "http://www.w3.org/2000/svg")
        + " "
        + _attr("xmlns:xlink", "http://www.w3.org/1999/xlink")
        + " "
        + _attr("width", _fmt(rect.w))
        + " "
        + _attr("height", _fmt(rect.h))
        + " "
        + _attr("viewBox", viewbox)
        + ">"
    )

    # スキャン背景
    if page.background is not None:
        b = page.background
        if _intersects_export(b.rect, rect):
            data, ext = image_fn(b.png_bytes, "png")
            lines.append(_image_tag(b.rect, data, ext))

    text_els: List[TextElement] = []
    for el in page.live_elements():
        if not _intersects_export(el.bbox, rect):
            continue
        svg = _element_to_svg(el, color_fn, image_fn)
        if svg:
            if annotate:
                svg = _with_data_el(svg, el.id)
            lines.append(svg)
            if isinstance(el, TextElement):
                text_els.append(el)

    # 同梱フォント (BIZ UD) を使う場合のみサブセット WOFF2 を埋め込む
    css = font_embed.font_face_css(text_els)
    if css:
        lines.insert(2, f"<style>{css}</style>")

    lines.append("</svg>")
    return "\n".join(lines)
```

`_element_to_svg` / `_paint` / `_text_to_svg` のシグネチャを変える（本体はそのまま、色を出す箇所だけ差し替え）:

```python
def _element_to_svg(el, color_fn: ColorFn = sanitize_color, image_fn: ImageFn = _identity_image) -> str:
    if isinstance(el, TextElement):
        return _text_to_svg(el, color_fn)
    if isinstance(el, LineElement):
        return (
            "<line "
            ...  # 既存のまま
            + _attr("stroke", color_fn(el.color))
            ...
        )
    if isinstance(el, RectElement):
        return (
            ...
            + _paint("fill", el.fill, color_fn)
            + " "
            + _paint("stroke", el.stroke, color_fn)
            ...
        )
    if isinstance(el, PathElement):
        return (
            ...
            + _paint("fill", el.fill, color_fn)
            + " "
            + _paint("stroke", el.stroke, color_fn)
            ...
        )
    if isinstance(el, ImageElement):
        data, ext = image_fn(el.img_bytes, el.ext)
        return _image_tag(el.rect, data, ext)
    return ""


def _paint(attr: str, color, color_fn: ColorFn = sanitize_color) -> str:
    """塗り/線の色属性。**出口側の関門**で、入口 (``rpc_addBorder``) を迂回して
    モデルへ直接不正な色を入れられても、ここで ``ValueError`` になる。
    ``color_fn`` はグレー化のための差し替え点で、``to_gray_color`` も内部で
    ``sanitize_color`` を通すので関門は緩まない。"""
    return _attr(attr, color_fn(color)) if color else _attr(attr, "none")


def _text_to_svg(el: TextElement, color_fn: ColorFn = sanitize_color) -> str:
    ...  # 既存のまま。末尾の fill だけ次に変える
        + _attr("fill", color_fn(el.color))
```

（`...` は既存コードをそのまま残す印。実際のファイルでは省略せず既存行を保つ。）

- [ ] **Step 4: 通ることを確認する（既存テストも）**

Run: `cd pdf-to-svg && py -3.13 -m pytest test/test_export_clip.py test/test_pipeline.py test/test_export_escaping.py -v`
Expected: すべて passed（`test_no_attribute_is_built_with_a_raw_f_string` は走査対象が 4 ファイルになる）

- [ ] **Step 5: コミット**

```bash
git add pdf-to-svg/src/export/svg_exporter.py pdf-to-svg/test/test_export_clip.py
git commit -m "feat(pdf-to-svg): page_to_svg に grayscale オプションを追加し色・画像を出口で灰色化する"
```

---

### Task 4: エクスポータの `clip`（切り出し）

**Files:**
- Modify: `pdf-to-svg/src/export/svg_exporter.py`
- Test: `pdf-to-svg/test/test_export_clip.py`

**Interfaces:**
- Produces: `clip: Rect` を渡すと `viewBox` / `width` / `height` が clip になり、交差しない要素は出力されず、根直下の `<g clip-path="url(#clip-export)">` で交差要素のはみ出しを切る。`clip.w <= 0 or clip.h <= 0` は `ValueError`。

- [ ] **Step 1: 失敗するテストを追加する**

```python
# pdf-to-svg/test/test_export_clip.py に追記
import pytest


def test_clip_sets_viewbox_and_drops_outside_elements():
    svg = page_to_svg(_page(), clip=Rect(0, 0, 100, 100))
    assert 'viewBox="0 0 100 100"' in svg
    assert 'width="100"' in svg and 'height="100"' in svg
    assert "Hello" in svg                      # (10,10) は clip 内
    assert 'x="200"' not in svg               # (200,150) の矩形は clip 外
    assert '<clipPath id="clip-export">' in svg
    assert '<rect x="0" y="0" width="100" height="100"/>' in svg
    assert '<g clip-path="url(#clip-export)">' in svg
    assert svg.rstrip().endswith("</g>\n</svg>")


def test_clip_offset_origin():
    svg = page_to_svg(_page(), clip=Rect(100, 100, 100, 100))
    assert 'viewBox="100 100 100 100"' in svg
    assert "Hello" not in svg                  # clip 外
    assert 'd="M120 120' in svg                # 曲線は clip 内


def test_clip_with_zero_size_is_rejected():
    with pytest.raises(ValueError):
        page_to_svg(_page(), clip=Rect(0, 0, 0, 10))


def test_no_clip_has_no_clippath():
    assert "clipPath" not in page_to_svg(_page())
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg && py -3.13 -m pytest test/test_export_clip.py -v`
Expected: 新規 4 件のうち `test_no_clip_has_no_clippath` 以外が FAIL

- [ ] **Step 3: 実装する**

`page_to_svg` の中、`<svg ...>` を追加した直後（スキャン背景の前）に挿入:

```python
    if clip is not None:
        if clip.w <= 0 or clip.h <= 0:
            raise ValueError(f"clip must have positive size: {clip!r}")
        # 交差する要素のはみ出しは標準の clipPath で切る (Office / Illustrator でも効く)。
        # 属性は _attr 経由で組む (f-string で ="{...}" を書くと test_export_escaping が止める)。
        lines.append(
            "<defs><clipPath "
            + _attr("id", "clip-export")
            + "><rect "
            + _attr("x", _fmt(rect.x))
            + " "
            + _attr("y", _fmt(rect.y))
            + " "
            + _attr("width", _fmt(rect.w))
            + " "
            + _attr("height", _fmt(rect.h))
            + "/></clipPath></defs>"
        )
        lines.append("<g " + _attr("clip-path", "url(#clip-export)") + ">")
```

`lines.append("</svg>")` の直前に:

```python
    if clip is not None:
        lines.append("</g>")
```

`css` の `lines.insert(2, ...)` は `<svg>` 直後（index 2）へ入るので `<defs>` より前に来る。順序は問題ない。

- [ ] **Step 4: 通ることを確認する**

Run: `cd pdf-to-svg && py -3.13 -m pytest test/test_export_clip.py test/test_pipeline.py test/test_export_escaping.py -v`
Expected: すべて passed

- [ ] **Step 5: コミット**

```bash
git add pdf-to-svg/src/export/svg_exporter.py pdf-to-svg/test/test_export_clip.py
git commit -m "feat(pdf-to-svg): page_to_svg に clip オプションを追加し矩形で切り出せるようにする"
```

---

### Task 5: 図検出 `figure_detect.py`

**Files:**
- Create: `pdf-to-svg/src/model/figure_detect.py`
- Test: `pdf-to-svg/test/test_figure_detect.py`
- Modify: `docs/superpowers/specs/2026-09-04-pdf-to-svg-stewardship-figure-gray-design.md`（4.1/4.2 の `LABEL_MAX_WIDTH_RATIO` を 0.45 → 0.5 に直す。実 PDF の URL ラベルが幅 45.4% で、本文段落は 84% 以上なので 0.5 に余裕がある）

**Interfaces:**
- Consumes: `Page.live_elements()`, `Rect(x, y, w, h)` / `Rect.x1` / `Rect.y1` / `Rect.from_xyxy`
- Produces: `detect_stewardship_figure(page: Page) -> Rect | None`、`normalize_label_text(s: str) -> str`、定数 `STEWARDSHIP_HEADING` / `STEWARDSHIP_LABELS` / `MIN_LABEL_HITS` / `FIGURE_EXPAND_TOL` / `LABEL_MAX_WIDTH_RATIO`。テスト用ヘルパ `make_stewardship_page()` を `test_figure_detect.py` に置き、Task 6 が import する。

- [ ] **Step 1: 失敗するテストを書く**

```python
# pdf-to-svg/test/test_figure_detect.py
"""スチュワードシップ図の文字アンカー検出 (``model/figure_detect.py``)。

幾何の指紋ではなく、見出し「当社のスチュワードシップ活動」と図内ラベルの文言で
領域を決める。図のレイアウトが変わっても文言が残れば追従し、文言が無ければ
検出しない (誤検出で強調ボックスを拾うより、候補なし → 手動へ倒すほうが安全)。
"""
from __future__ import annotations

from model.document import Page
from model.elements import ImageElement, LineElement, PathElement, Rect, RectElement, TextElement
from model.figure_detect import (
    MIN_LABEL_HITS,
    STEWARDSHIP_LABELS,
    detect_stewardship_figure,
    normalize_label_text,
)


def _text(x, y, w, h, s, **kw) -> TextElement:
    return TextElement(bbox=Rect(x, y, w, h), text=s, origin_x=x, origin_y=y + h, **kw)


def make_stewardship_page() -> Page:
    """実 PDF (595x842, 図は 85,249-483,650 付近) を模した合成ページ。"""
    pg = Page(index=0, width_pt=600, height_pt=800)
    els = [
        RectElement(bbox=Rect(0, 0, 600, 800), rect=Rect(0, 0, 600, 800), fill="#fdf3ee", stroke=None),   # ページ背景 (面積 100%)
        RectElement(bbox=Rect(0, 0, 600, 40), rect=Rect(0, 0, 600, 40), fill="#7a868d", stroke=None),      # ヘッダ帯 (幅 100%)
        _text(40, 140, 180, 14, "（3）当社のスチュワードシップ活動"),
        _text(40, 160, 510, 14, "当社は「責任ある機関投資家」として、エンゲージメント、議決権行使、投資の意思決定におけるESGの考慮を"),
        _text(40, 176, 510, 14, "3つの柱としてスチュワードシップ活動を推進しています。投資リターンの最大化を目指します。"),
        RectElement(bbox=Rect(113, 249, 370, 35), rect=Rect(113, 249, 370, 35), fill="#009eb4", stroke=None),
        _text(224, 265, 150, 16, "投資リターンの最大化", color="#ffffff"),
        PathElement(bbox=Rect(207, 320, 196, 174), d="M207 320 C 300 300 330 480 403 494", stroke="#c0392b"),
        _text(104, 356, 57, 12, "におけるESGの考慮"),
        _text(430, 344, 48, 12, "議決権行使"),
        _text(85, 468, 72, 12, "エンゲージメント"),
        RectElement(bbox=Rect(113, 526, 370, 70), rect=Rect(113, 526, 370, 70), fill="#009eb4", stroke=None),
        _text(162, 564, 191, 12, "［フィデューシャリー・デューティーの実践］", color="#ffffff"),
        RectElement(bbox=Rect(113, 600, 370, 50), rect=Rect(113, 600, 370, 50), fill=None, stroke="#000000"),
        ImageElement(bbox=Rect(120, 605, 40, 40), rect=Rect(120, 605, 40, 40), img_bytes=b"\x89PNG", ext="png"),
        _text(190, 640, 270, 10, "https://www.smtam.jp/institutional/stewardship_initiatives/"),
        LineElement(bbox=Rect(40, 790, 520, 0), x0=40, y0=790, x1=560, y1=790, color="#000000"),
        _text(40, 700, 160, 14, "（4）自社ESGスコアについて"),
    ]
    for i, el in enumerate(els):
        el.z = i
    pg.elements = els
    return pg


def test_normalize_folds_width_and_spaces():
    assert normalize_label_text("Ｅ Ｓ Ｇ の 考慮") == "ESGの考慮"
    assert normalize_label_text("＜当社の\nスチュワードシップ活動＞") == "<当社のスチュワードシップ活動>"


def test_detects_figure_bounded_by_labels_shapes_and_frame():
    r = detect_stewardship_figure(make_stewardship_page())
    assert r is not None
    assert (r.x, r.y, r.x1, r.y1) == (85, 249, 483, 650)


def test_background_and_header_band_are_not_absorbed():
    r = detect_stewardship_figure(make_stewardship_page())
    assert r.y > 40 and r.x > 0 and r.y1 < 790


def test_heading_only_returns_none():
    pg = Page(index=0, width_pt=600, height_pt=800)
    pg.elements = [_text(40, 140, 180, 14, "当社のスチュワードシップ活動")]
    assert detect_stewardship_figure(pg) is None


def test_fewer_than_min_labels_returns_none():
    pg = Page(index=0, width_pt=600, height_pt=800)
    pg.elements = [
        _text(40, 140, 180, 14, "当社のスチュワードシップ活動"),
        _text(100, 300, 100, 12, "エンゲージメント"),
        _text(100, 320, 100, 12, "議決権行使"),
    ]
    assert MIN_LABEL_HITS == 3
    assert detect_stewardship_figure(pg) is None


def test_wide_body_paragraph_does_not_count_as_label():
    pg = Page(index=0, width_pt=600, height_pt=800)
    pg.elements = [
        _text(40, 140, 180, 14, "当社のスチュワードシップ活動"),
        _text(40, 160, 510, 14, "エンゲージメント、議決権行使、ESGの考慮、投資リターンの最大化、フィデューシャリー"),
    ]
    assert detect_stewardship_figure(pg) is None


def test_labels_above_heading_are_ignored():
    pg = make_stewardship_page()
    # 見出しより上に同じ語が並んでいても数えない (前ページの続きなど)
    pg.elements.append(_text(100, 60, 100, 12, "議決権行使"))
    r = detect_stewardship_figure(pg)
    assert r.y == 249


def test_deleted_elements_are_ignored():
    pg = make_stewardship_page()
    for el in pg.elements:
        if isinstance(el, TextElement) and any(k in normalize_label_text(el.text) for k in STEWARDSHIP_LABELS):
            el.deleted = True
    assert detect_stewardship_figure(pg) is None


def test_expansion_terminates_on_long_chains():
    pg = make_stewardship_page()
    # 図の右端から 10pt 刻みで小矩形を 300 個つなぐ → 全部吸収して必ず返る
    x = 483 + 10
    for i in range(300):
        r = Rect(x, 400, 5, 5)
        pg.elements.append(RectElement(bbox=r, rect=r, fill="#123456", stroke=None, z=1000 + i))
        x += 10
    out = detect_stewardship_figure(pg)
    assert out is not None and out.x1 == x - 10 + 5
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg && py -3.13 -m pytest test/test_figure_detect.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'model.figure_detect'`）

- [ ] **Step 3: 実装する**

```python
# pdf-to-svg/src/model/figure_detect.py
"""「当社のスチュワードシップ活動」の図を文字アンカーで見つける純粋関数。

運用報告書の当該図は号・ファンドごとに掲載ページも位置も違うが、見出しと図内ラベルの
文言は同じ。幾何の指紋 (曲線の本数など) に頼るとレイアウト変更で外れ、強調ボックスの
誤検出も多かったので、**文字で図を特定し、周りの図形へ広げる**方式にする。

- ``Page.live_elements()`` の bbox と文字列だけを見る (PyMuPDF 非依存。合成 ``Page`` で
  単体テストできる)。
- 1 ページにつき最大 1 矩形。見つからなければ ``None`` (UI は候補なし → 手動へ倒す)。
- 資源上限: 不動点ループは「取り込んだ要素は二度と候補にしない」ので、反復は要素数で
  上界される (必ず返る)。
"""
from __future__ import annotations

import unicodedata
from typing import List, Optional, Tuple

from model.document import Page
from model.elements import Element, ImageElement, LineElement, PathElement, Rect, RectElement, TextElement

# 見出し (NFKC 正規化 + 空白除去した文字列に含まれれば一致)
STEWARDSHIP_HEADING = "当社のスチュワードシップ活動"
# 図内ラベル。同じ語は直後の本文段落にも出るので、幅 (LABEL_MAX_WIDTH_RATIO) で本文を除外する。
STEWARDSHIP_LABELS: Tuple[str, ...] = (
    "投資リターンの最大化",
    "エンゲージメント",
    "議決権行使",
    "ESGの考慮",
    "フィデューシャリー",
    "stewardship_initiatives",
)
MIN_LABEL_HITS = 3            # これ未満なら「図が無い / 文言が変わった」と判断して None
FIGURE_EXPAND_TOL = 16.0      # 近傍として取り込む距離 (pt)
LABEL_MAX_WIDTH_RATIO = 0.5   # ラベルとみなす文字要素の最大幅 (ページ幅比)。本文段落は 0.8 超
BACKGROUND_AREA_RATIO = 0.5   # これ以上の面積の図形はページ背景とみなして取り込まない
BAND_WIDTH_RATIO = 0.9        # これ以上の幅の図形はヘッダ帯・区切り罫とみなして取り込まない

_SHAPE_TYPES = (RectElement, PathElement, LineElement, ImageElement)


def normalize_label_text(s: str) -> str:
    """NFKC 正規化して空白を全部落とす (全角・半角・改行の揺れを吸収)。"""
    return "".join(unicodedata.normalize("NFKC", s).split())


def _union(a: Rect, b: Rect) -> Rect:
    return Rect.from_xyxy(min(a.x, b.x), min(a.y, b.y), max(a.x1, b.x1), max(a.y1, b.y1))


def _grow(r: Rect, tol: float) -> Rect:
    return Rect(r.x - tol, r.y - tol, r.w + 2 * tol, r.h + 2 * tol)


def _overlaps(a: Rect, b: Rect) -> bool:
    """辺が触れるだけでも真 (``Rect.intersects`` は開区間なので高さ 0 の罫線を拾えない)。"""
    return not (a.x1 < b.x or b.x1 < a.x or a.y1 < b.y or b.y1 < a.y)


def _contains(outer: Rect, inner: Rect) -> bool:
    return outer.x <= inner.x and outer.y <= inner.y and inner.x1 <= outer.x1 and inner.y1 <= outer.y1


def detect_stewardship_figure(page: Page) -> Optional[Rect]:
    """図の矩形 (ページ座標 pt) を返す。見つからなければ None。"""
    width, height = page.width_pt, page.height_pt
    page_area = width * height
    elements: List[Element] = page.live_elements()
    texts = [(normalize_label_text(e.text), e) for e in elements if isinstance(e, TextElement)]

    heads = [e for t, e in texts if STEWARDSHIP_HEADING in t]
    if not heads:
        return None
    head_y = min(e.bbox.y for e in heads)

    max_label_w = width * LABEL_MAX_WIDTH_RATIO
    labels = [
        e for t, e in texts
        if e.bbox.y > head_y and e.bbox.w < max_label_w and any(k in t for k in STEWARDSHIP_LABELS)
    ]
    if len(labels) < MIN_LABEL_HITS:
        return None

    box = labels[0].bbox
    for e in labels[1:]:
        box = _union(box, e.bbox)

    # 近傍の図形・画像を不動点まで取り込む (背景と帯は除外)
    pending = [
        e for e in elements
        if isinstance(e, _SHAPE_TYPES)
        and e.bbox.w * e.bbox.h < page_area * BACKGROUND_AREA_RATIO
        and e.bbox.w < width * BAND_WIDTH_RATIO
    ]
    grew = True
    while grew and pending:
        grew = False
        probe = _grow(box, FIGURE_EXPAND_TOL)
        rest = []
        for e in pending:
            if _overlaps(e.bbox, probe):
                if not _contains(box, e.bbox):
                    box = _union(box, e.bbox)
                    grew = True
            else:
                rest.append(e)
        pending = rest  # 取り込んだ要素は二度と見ない → 反復は要素数で上界

    # 領域に掛かる短い文字行 (ラベルの説明文) を取り込む
    for _t, e in texts:
        if e.bbox.w < max_label_w and _overlaps(e.bbox, box) and not _contains(box, e.bbox):
            box = _union(box, e.bbox)
    return box
```

- [ ] **Step 4: 通ることを確認する**

Run: `cd pdf-to-svg && py -3.13 -m pytest test/test_figure_detect.py -v`
Expected: 9 passed

- [ ] **Step 5: spec の定数を直す**

`docs/superpowers/specs/2026-09-04-pdf-to-svg-stewardship-figure-gray-design.md` の 4.1 節「幅がページ幅の 45% 未満」（2 箇所）と 4.2 節 `LABEL_MAX_WIDTH_RATIO = 0.45` を 50% / `0.5` に置き換え、4.1 の 2. の末尾に「（実 PDF では URL ラベルが幅 45.4%、本文段落は 84% 以上）」と根拠を添える。

- [ ] **Step 6: コミット**

```bash
git add pdf-to-svg/src/model/figure_detect.py pdf-to-svg/test/test_figure_detect.py docs/superpowers/specs/2026-09-04-pdf-to-svg-stewardship-figure-gray-design.md
git commit -m "feat(pdf-to-svg): スチュワードシップ図を文字アンカーで検出する figure_detect を追加"
```

---

### Task 6: RPC（`figureCandidates` / `pageSvg` / `exportSvg`）

**Files:**
- Modify: `pdf-to-svg/src/web/rpc_methods.py`（import、`rpc_pageSvg`、`rpc_exportSvg`、新 `rpc_figureCandidates`、`HANDLERS`）
- Test: `pdf-to-svg/test/test_web_rpc.py`
- Modify: spec 9 節「`clip` 不正は 400 で返し」→「`clip` 不正は `{ok:false, error}` で返し」（サーバの既存規約に合わせる。`_handle_rpc` は例外を `ok:false` にする）

**Interfaces:**
- Consumes: `detect_stewardship_figure`（Task 5）、`page_to_svg(grayscale, clip)`（Task 3・4）
- Produces:
  - `figureCandidates {fileIndex, pageInFile} -> {"rects": [{"x","y","w","h"}]}`（0 または 1 件）
  - `pageSvg {..., grayscale?: bool, clip?: {x,y,w,h}}`
  - `exportSvg {..., grayscale?: bool, clip?: {x,y,w,h}, figIndex?: int}` → `name` は `<stem>_p<N>[_fig<k>][_gray].svg`
  - 内部 `_parse_clip(args, pg) -> Rect | None`（不正は `ValueError`）

- [ ] **Step 1: 失敗するテストを追加する**

```python
# pdf-to-svg/test/test_web_rpc.py の末尾に追記
import re

from .test_figure_detect import make_stewardship_page

_CHROMATIC = re.compile(r'="#(?!([0-9a-f]{2})\1\1")[0-9a-f]{6}"')


def test_figure_candidates_empty_when_no_heading(session):
    data = rpc_methods.dispatch(session, "figureCandidates", {"fileIndex": 0, "pageInFile": 0})
    assert data == {"rects": []}


def test_figure_candidates_returns_detected_rect(session):
    session.docs[0].pages.append(make_stewardship_page())
    data = rpc_methods.dispatch(session, "figureCandidates", {"fileIndex": 0, "pageInFile": 1})
    assert data["rects"] == [{"x": 85.0, "y": 249.0, "w": 398.0, "h": 401.0}]


def test_page_svg_grayscale_has_no_chromatic_color(session):
    session.docs[0].pages[0].elements[1].color = "#3333cc"
    color = rpc_methods.dispatch(session, "pageSvg", {"fileIndex": 0, "pageInFile": 0})
    gray = rpc_methods.dispatch(session, "pageSvg", {"fileIndex": 0, "pageInFile": 0, "grayscale": True})
    assert _CHROMATIC.search(color["svg"])
    assert not _CHROMATIC.search(gray["svg"])
    assert "data-el=" in gray["svg"]  # プレビュー用の注釈は残る


def test_export_svg_name_and_clip(session):
    args = {"fileIndex": 0, "pageInFile": 0, "grayscale": True,
            "clip": {"x": 0, "y": 0, "w": 100, "h": 100}, "figIndex": 2}
    data = rpc_methods.dispatch(session, "exportSvg", args)
    assert data["name"] == "部品表_p1_fig2_gray.svg"
    assert 'viewBox="0 0 100 100"' in data["svg"]
    assert "data-el=" not in data["svg"]
    # grayscale だけ → _gray、clip だけ → _fig1、どちらも無し → 従来名
    assert rpc_methods.dispatch(session, "exportSvg", {"fileIndex": 0, "pageInFile": 0, "grayscale": True})["name"] == "部品表_p1_gray.svg"
    assert rpc_methods.dispatch(session, "exportSvg", {"fileIndex": 0, "pageInFile": 0, "clip": {"x": 0, "y": 0, "w": 10, "h": 10}})["name"] == "部品表_p1_fig1.svg"
    assert rpc_methods.dispatch(session, "exportSvg", {"fileIndex": 0, "pageInFile": 0})["name"] == "部品表_p1.svg"


@pytest.mark.parametrize("clip", [
    {"x": 0, "y": 0, "w": 0, "h": 10},          # 幅 0
    {"x": -1, "y": 0, "w": 10, "h": 10},        # 負
    {"x": 0, "y": 0, "w": 10},                  # 欠け
    {"x": "a", "y": 0, "w": 10, "h": 10},       # 数値でない
    {"x": 0, "y": 0, "w": 1e400, "h": 10},      # inf
    {"x": 150, "y": 0, "w": 100, "h": 10},      # ページ (200x300) の外
    "0,0,10,10",                                # 型違い
])
def test_bad_clip_is_rejected(session, clip):
    with pytest.raises(ValueError):
        rpc_methods.dispatch(session, "exportSvg", {"fileIndex": 0, "pageInFile": 0, "clip": clip})
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg && py -3.13 -m pytest test/test_web_rpc.py -v -k "figure or grayscale or clip or export_svg_name"`
Expected: `KeyError: 'figureCandidates'` / `AssertionError` で FAIL

- [ ] **Step 3: 実装する**

`pdf-to-svg/src/web/rpc_methods.py`:

import に追加:

```python
from model.figure_detect import detect_stewardship_figure
```

`rpc_pageSvg` の手前にヘルパを追加:

```python
def _parse_clip(args: dict, pg: Page) -> Optional[Rect]:
    """``clip`` 引数 ``{x, y, w, h}`` をページ座標の矩形にする。無ければ None。

    クライアントが送る値なので信用しない: 数値 4 つ・有限・非負・正の寸法・ページ内を
    要求し、外れたら ``ValueError`` (ディスパッチャが ``{ok:false, error}`` にする)。
    """
    c = args.get("clip")
    if c is None:
        return None
    if not isinstance(c, dict):
        raise ValueError("clip must be an object {x, y, w, h}")
    try:
        x, y, w, h = (float(c[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("clip must have numeric x, y, w, h") from exc
    if any(not math.isfinite(v) for v in (x, y, w, h)):
        raise ValueError("clip must be finite")
    if w <= 0 or h <= 0 or x < 0 or y < 0:
        raise ValueError("clip must be inside the page with positive size")
    if x + w > pg.width_pt + 0.5 or y + h > pg.height_pt + 0.5:
        raise ValueError("clip must be inside the page")
    return Rect(x, y, w, h)


def rpc_figureCandidates(s: WebSession, args: dict) -> dict:
    """指定ページのスチュワードシップ図の候補矩形 (0 または 1 件)。

    検出の想定外例外はページ単位で握って候補なしにする (1 ページで全体を止めない)。
    """
    pg = s.page(int(args["fileIndex"]), int(args["pageInFile"]))
    try:
        r = detect_stewardship_figure(pg)
    except Exception:  # noqa: BLE001
        _log.exception("figure detection failed")
        r = None
    return {"rects": [] if r is None else [{"x": r.x, "y": r.y, "w": r.w, "h": r.h}]}
```

`rpc_pageSvg` を置き換え:

```python
def rpc_pageSvg(s: WebSession, args: dict) -> dict:
    pg = s.page(args["fileIndex"], args["pageInFile"])
    return {
        "svg": page_to_svg(
            pg, annotate=True, grayscale=bool(args.get("grayscale")), clip=_parse_clip(args, pg)
        ),
        "width": pg.width_pt,
        "height": pg.height_pt,
    }
```

`rpc_exportSvg` を置き換え:

```python
def rpc_exportSvg(s: WebSession, args: dict) -> dict:
    """指定ページの SVG 文字列と推奨ファイル名を返す (annotate なし=書き出し用・従来出力と一致)。

    ``clip`` があれば ``_fig<k>``、``grayscale`` なら ``_gray`` をファイル名に足す。
    Downloads でカラー版の ``_p<N>.svg`` と衝突させないため。
    """
    fi = int(args["fileIndex"])
    pi = int(args["pageInFile"])
    d = s.doc(fi)
    pg = d.pages[pi]
    grayscale = bool(args.get("grayscale"))
    clip = _parse_clip(args, pg)
    stem = Path(d.source_path).stem
    name = f"{stem}_p{pi + 1}"
    if clip is not None:
        name += f"_fig{int(args.get('figIndex', 1))}"
    if grayscale:
        name += "_gray"
    return {"svg": page_to_svg(pg, grayscale=grayscale, clip=clip), "name": name + ".svg"}
```

`HANDLERS` に追加:

```python
    "figureCandidates": rpc_figureCandidates,
```

- [ ] **Step 4: 通ることを確認する**

Run: `cd pdf-to-svg && py -3.13 -m pytest test/test_web_rpc.py test/test_shell_rpc.py -v`
Expected: すべて passed

- [ ] **Step 5: spec の文言を直してコミット**

spec 9 節の「`clip` 不正は 400 で返し、クライアントはトーストで通知する。」を「`clip` 不正は `ValueError` にし、ディスパッチャが `{ok:false, error}` で返す（既存規約）。クライアントはトーストで通知する。」に置き換える。

```bash
git add pdf-to-svg/src/web/rpc_methods.py pdf-to-svg/test/test_web_rpc.py docs/superpowers/specs/2026-09-04-pdf-to-svg-stewardship-figure-gray-design.md
git commit -m "feat(pdf-to-svg): figureCandidates RPC を追加し pageSvg/exportSvg に grayscale と clip を渡せるようにする"
```

---

### Task 7: `state.js` のグレーモード状態

**Files:**
- Modify: `pdf-to-svg/resources/web/state.js`
- Test: `pdf-to-svg/test/test_pdftosvg_state_js.py`

**Interfaces:**
- Produces（export 追加）:
  - `S.gray: boolean`, `S.figCand: {"fi:pi": Rect[]}`, `S.figSel: {"fi:pi": Rect[]}`, `S.zoomFor[4]`
  - `figKey(pg) -> "fi:pi"`, `svgKey(fi, pi) -> "fi:pi" | "fi:pi:g"`
  - `figSelOf(g) -> Rect[]`（通しページ g の採用配列。無ければ空配列を作る）
  - `figCount() -> number`
  - `seedFigSel(g, rects)`（候補を記録し、未タッチのページだけ採用へ複製）
  - `exportFigureList() -> [{fileIndex, pageInFile, clip, figIndex, grayscale: true}]`
  - `phaseAfterLoad() -> 2 | 4`, `phaseBeforeExport() -> 3 | 1`, `stepAllowed(n) -> boolean`
  - `zipName(list)` が gray のとき `_gray_svg.zip` / `svg_export_gray.zip`

- [ ] **Step 1: 失敗するテストを追加する**

```python
# pdf-to-svg/test/test_pdftosvg_state_js.py の末尾に追記

# ── グレーモード (図の採用と遷移) ──


def test_gray_defaults_off_and_normal_transitions(st):
    assert js(st, "window.__st.S.gray") is False
    assert js(st, "window.__st.phaseAfterLoad()") == 2
    assert js(st, "window.__st.phaseBeforeExport()") == 3
    assert js(st, "[1,2,3,4].map(n => window.__st.stepAllowed(n))") == [True, True, True, True]


def test_gray_skips_steps_2_and_3(st):
    js(st, "window.__st.S.gray = true")
    assert js(st, "window.__st.phaseAfterLoad()") == 4
    assert js(st, "window.__st.phaseBeforeExport()") == 1
    assert js(st, "[1,2,3,4].map(n => window.__st.stepAllowed(n))") == [True, False, False, True]


def test_svg_cache_key_includes_gray(st):
    assert js(st, "window.__st.svgKey(1, 2)") == "1:2"
    js(st, "window.__st.S.gray = true")
    assert js(st, "window.__st.svgKey(1, 2)") == "1:2:g"


def test_seed_fig_sel_adopts_candidates_only_once(st):
    r = {"x": 10, "y": 20, "w": 30, "h": 40}
    js(st, "r => window.__st.seedFigSel(0, [r])", r)
    assert js(st, "window.__st.figSelOf(0)") == [r]
    assert js(st, "window.__st.figCount()") == 1
    # 利用者が外した後に再取得しても、候補を勝手に戻さない
    js(st, "window.__st.figSelOf(0).length = 0")
    js(st, "r => window.__st.seedFigSel(0, [r])", r)
    assert js(st, "window.__st.figSelOf(0)") == []
    assert js(st, "window.__st.S.figCand['0:0']") == [r]


def test_export_figure_list_for_all_and_page(st):
    a = {"x": 1, "y": 2, "w": 3, "h": 4}
    b = {"x": 5, "y": 6, "w": 7, "h": 8}
    js(st, "([a, b]) => { window.__st.figSelOf(0).push(a); window.__st.figSelOf(3).push(a, b); }", [a, b])
    js(st, "window.__st.S.gray = true; window.__st.S.expMode = 'all'")
    assert js(st, "window.__st.exportFigureList()") == [
        {"fileIndex": 0, "pageInFile": 0, "clip": a, "figIndex": 1, "grayscale": True},
        {"fileIndex": 1, "pageInFile": 1, "clip": a, "figIndex": 1, "grayscale": True},
        {"fileIndex": 1, "pageInFile": 1, "clip": b, "figIndex": 2, "grayscale": True},
    ]
    js(st, "window.__st.S.expMode = 'page'; window.__st.S.page = 3")
    assert len(js(st, "window.__st.exportFigureList()")) == 2


def test_zip_name_gets_gray_suffix(st):
    lst = [{"fileIndex": 0, "pageInFile": 0}]
    assert js(st, "l => window.__st.zipName(l)", lst) == "a_svg.zip"
    js(st, "window.__st.S.gray = true")
    assert js(st, "l => window.__st.zipName(l)", lst) == "a_gray_svg.zip"
    mixed = [{"fileIndex": 0, "pageInFile": 0}, {"fileIndex": 1, "pageInFile": 0}]
    assert js(st, "l => window.__st.zipName(l)", mixed) == "svg_export_gray.zip"


def test_apply_state_with_new_page_list_drops_fig_state(st):
    js(st, "window.__st.figSelOf(0).push({x:1,y:1,w:1,h:1}); window.__st.S.figCand['0:0'] = []")
    js(st, """window.__st.applyState({
        files: [{ name: "c.pdf", pages: 1 }], pages: [{ fileIndex: 0, pageInFile: 0 }], total: 1,
        changed2: [false], changed3: [false] })""")
    assert js(st, "Object.keys(window.__st.S.figSel)") == []
    assert js(st, "Object.keys(window.__st.S.figCand)") == []
```

`RESET` 関数（ファイル先頭の `RESET` 文字列）の末尾、`m.S.expMode = "all"; m.S.expFile = 0;` の後に次を足す:

```js
  m.S.gray = false; m.S.figCand = {}; m.S.figSel = {};
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg && py -3.13 -m pytest test/test_pdftosvg_state_js.py -v -k "gray or fig or svg_cache or zip_name_gets"`
Expected: `phaseAfterLoad is not a function` 等で FAIL

- [ ] **Step 3: 実装する**

`S` の定義に追加（`lastChanges` の後）:

```js
  // ── グレーモード (図だけをグレースケールで書き出す) ──
  gray: false,          // 手順 1 のチェック。ON で手順 2・3 を飛ばし、手順 4 が図の選択画面になる
  figCand: {},          // "fi:pi" -> [{x,y,w,h}] サーバが検出した候補 (取得済みページのみ)
  figSel: {},           // "fi:pi" -> [{x,y,w,h}] 採用した矩形 (検出結果はここへ複製され、以後は利用者のもの)
  figDrag: null,        // ハンドル伸縮・空白ドラッグ中の状態 (figure.js が使う)
```

`zoomFor: { 2: 1, 3: 1 }` を `zoomFor: { 2: 1, 3: 1, 4: 1 }` にする。

「3. 導出」の末尾に追加:

```js
function figKey(pg) { return pg.fileIndex + ":" + pg.pageInFile; }
/** ページ SVG キャッシュのキー。グレーは別の SVG なのでキーを分ける (モード切替で混ざらない) */
function svgKey(fi, pi) { return fi + ":" + pi + (S.gray ? ":g" : ""); }
/** 通しページ g の採用矩形配列 (無ければ作る) */
function figSelOf(g) { var k = figKey(S.PAGES[g]); return (S.figSel[k] = S.figSel[k] || []); }
function figCount() { var n = 0; S.PAGES.forEach(function (pg, g) { n += figSelOf(g).length; }); return n; }
/** サーバの候補を記録し、まだ触っていないページだけ採用へ複製する。
 *  利用者が外した候補を再取得のたびに戻さないため、採用配列が既にあるページは触らない。 */
function seedFigSel(g, rects) {
  var k = figKey(S.PAGES[g]);
  S.figCand[k] = rects.map(function (r) { return { x: r.x, y: r.y, w: r.w, h: r.h }; });
  if (!Object.prototype.hasOwnProperty.call(S.figSel, k)) {
    S.figSel[k] = rects.map(function (r) { return { x: r.x, y: r.y, w: r.w, h: r.h }; });
  }
}
```

「4. 状態遷移」の `advancePhase` の前に追加:

```js
/** 手順 1 の「次へ」の行き先。グレーモードは手順 2・3 を飛ばす */
function phaseAfterLoad() { return S.gray ? 4 : 2; }
/** 手順 4 の「戻る」の行き先 */
function phaseBeforeExport() { return S.gray ? 1 : 3; }
/** ステップバーのクリックで移ってよい手順か */
function stepAllowed(n) { return !S.gray || n === 1 || n === 4; }
```

`applyState` の `else` 分岐（ページ列が変わったとき）の `S.selFor = ...; S.collapsed = {};` の直後に:

```js
    S.figCand = {}; S.figSel = {};
```

「5. 書き出し範囲の算出」の `expCount` の後に追加:

```js
/** グレーモードの書き出し対象: 採用矩形を 1 図 = 1 SVG に展開する (page モードは表示中のページだけ) */
function exportFigureList() {
  var pages = S.expMode === "page" ? [S.page] : S.PAGES.map(function (_pg, g) { return g; });
  var out = [];
  pages.forEach(function (g) {
    var pg = S.PAGES[g]; if (!pg) return;
    figSelOf(g).forEach(function (r, i) {
      out.push({ fileIndex: pg.fileIndex, pageInFile: pg.pageInFile,
        clip: { x: r.x, y: r.y, w: r.w, h: r.h }, figIndex: i + 1, grayscale: true });
    });
  });
  return out;
}
```

`zipName` を置き換え:

```js
/** ZIP のファイル名。対象が 1 PDF ならその名前を継ぎ、複数ファイル混在なら汎用名にする。
 *  グレーモードは `_gray` を挟み、Downloads でカラー版と衝突させない */
function zipName(list) {
  var fis = {};
  list.forEach(function (it) { fis[it.fileIndex] = 1; });
  var keys = Object.keys(fis);
  var suffix = S.gray ? "_gray_svg.zip" : "_svg.zip";
  if (keys.length === 1 && S.FILES[+keys[0]]) {
    return S.FILES[+keys[0]].name.replace(/\.pdf$/i, "") + suffix;
  }
  return S.gray ? "svg_export_gray.zip" : "svg_export.zip";
}
```

`export { ... }` に追加:

```js
  figKey, svgKey, figSelOf, figCount, seedFigSel, exportFigureList,
  phaseAfterLoad, phaseBeforeExport, stepAllowed,
```

- [ ] **Step 4: 通ることを確認する**

Run: `cd pdf-to-svg && py -3.13 -m pytest test/test_pdftosvg_state_js.py -v`
Expected: 既存 27 + 新規 7 = 34 passed

- [ ] **Step 5: コミット**

```bash
git add pdf-to-svg/resources/web/state.js pdf-to-svg/test/test_pdftosvg_state_js.py
git commit -m "feat(pdf-to-svg): state.js にグレーモードの状態・遷移・図の採用と書き出し列挙を追加"
```

---

### Task 8: UI（手順 1 チェック・手順 4 の 3 ペイン・書き出し）と E2E

**Files:**
- Modify: `pdf-to-svg/resources/web/index.html`
- Modify: `pdf-to-svg/resources/web/styles.css`
- Create: `pdf-to-svg/resources/web/figure.js`
- Modify: `pdf-to-svg/resources/web/app.js`
- Test: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`

**Interfaces:**
- Consumes: Task 6 の RPC、Task 7 の `state.js` エクスポート、既存 `mountPage` / `scalePage` / `clientToPage` / `downloadBlob` / `rpc`
- Produces: `figure.js` が `initFigure({render})`, `buildFigRail(navId)`, `drawFigOverlay(host)`, `installFigDrag(host)` を export

- [ ] **Step 1: 失敗する E2E を書く**

`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` の末尾に追記:

```python
FIG_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "stewardship_sample.pdf")


@pytest.fixture(scope="module")
def stewardship_pdf():
    """実 PDF を模した合成ページ (見出し・本文・帯・曲線・ラベル・QR 枠)。外部著作物は使わない。"""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((43, 150), "（3）当社のスチュワードシップ活動", fontname="japan", fontsize=11)
    page.insert_text((43, 175), "当社は「責任ある機関投資家」として、エンゲージメント、議決権行使、投資の意思決定におけるESGの考慮を3つの柱として", fontname="japan", fontsize=8)
    page.draw_rect(fitz.Rect(113, 249, 483, 284), color=None, fill=(0, 0.62, 0.71))
    page.insert_text((224, 275), "投資リターンの最大化", fontname="japan", fontsize=13, color=(1, 1, 1))
    shape = page.new_shape()
    shape.draw_bezier((220, 330), (300, 300), (330, 480), (400, 490))
    shape.finish(color=(0.8, 0.2, 0.3), width=6)
    shape.commit()
    page.insert_text((85, 478), "エンゲージメント", fontname="japan", fontsize=9, color=(0.85, 0.55, 0.1))
    page.insert_text((430, 354), "議決権行使", fontname="japan", fontsize=9, color=(0.2, 0.6, 0.3))
    page.insert_text((104, 366), "におけるESGの考慮", fontname="japan", fontsize=9, color=(0.8, 0.2, 0.3))
    page.draw_rect(fitz.Rect(113, 526, 483, 596), color=None, fill=(0, 0.62, 0.71))
    page.insert_text((162, 574), "［フィデューシャリー・デューティーの実践］", fontname="japan", fontsize=9, color=(1, 1, 1))
    page.draw_rect(fitz.Rect(113, 600, 483, 650), color=(0, 0, 0), width=0.8)
    page.insert_text((190, 640), "https://www.smtam.jp/institutional/stewardship_initiatives/", fontsize=8)
    page.insert_text((43, 700), "（4）自社ESGスコアについて", fontname="japan", fontsize=11)
    doc.save(FIG_FIXTURE)
    doc.close()
    return FIG_FIXTURE


def test_gray_figure_flow(e2e_page, stewardship_pdf):
    """手順 1 でチェック → 手順 4 直行 → 検出図が採用済み → 切り出しグレー SVG を書き出す。"""
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)

    page.check("#chk-gray")
    expect(page.locator("#gray-skipnote")).to_be_visible()
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(stewardship_pdf)
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル", timeout=30_000)

    page.click("#btn-next")
    expect(page.locator('[data-screen="4"]')).to_have_class(re.compile("on"))
    expect(page.locator('#stepbar .step[data-step="2"]')).to_be_hidden()
    expect(page.locator("#pagenav-4")).to_be_visible()
    # 検出できたページは最初から採用済み (実線 1 つ)
    expect(page.locator("#fig-stage .fig-cand.sel")).to_have_count(1, timeout=15_000)
    expect(page.locator("#exp-num")).to_have_text("1")
    expect(page.locator("#pagenav-4 .pg-row2.done")).to_have_count(1)

    # × で外すと 0 件になり書き出せない。候補 (点線) をクリックすると戻る
    page.click("#fig-stage .fig-cand.sel .del")
    expect(page.locator("#exp-num")).to_have_text("0")
    expect(page.locator("#btn-export")).to_be_disabled()
    page.click("#fig-stage .fig-cand:not(.sel)")
    expect(page.locator("#exp-num")).to_have_text("1")

    with page.expect_download() as dl_info:
        page.click("#btn-export")
    download = dl_info.value
    assert download.suggested_filename == "stewardship_sample_p1_fig1_gray.svg"
    svg_text = Path(download.path()).read_text(encoding="utf8")
    assert 'clip-path="url(#clip-export)"' in svg_text
    assert not re.search(r'="#(?!([0-9a-f]{2})\1\1")[0-9a-f]{6}"', svg_text)  # 有彩色が残らない
    assert "投資リターンの最大化" in svg_text                                  # 文字は文字のまま
    assert "自社ESGスコア" not in svg_text                                      # 図の外は含まない

    # 戻るは手順 1 へ (手順 3 ではない)
    page.click("#btn-back")
    expect(page.locator('[data-screen="1"]')).to_have_class(re.compile("on"))
    page.uncheck("#chk-gray")
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg && py -3.13 -m pytest test -m e2e -v -k gray_figure`
Expected: `#chk-gray` が無く `page.check` がタイムアウトして FAIL

- [ ] **Step 3: `index.html` を変える**

手順 1: `</div>`（`dropzone` を閉じる行）と `<div class="filelist">` の間に挿入:

```html
          <label class="modebox" id="gray-mode-box">
            <input type="checkbox" id="chk-gray">
            <div>
              <div class="t">図だけをグレースケールで書き出す</div>
              <div class="d">「当社のスチュワードシップ活動」の図を自動で見つけて候補にします。選んだ範囲だけを切り出し、文字・線・画像をすべてグレースケールにした SVG を書き出します。用語の置換と削除・枠線の手順は省略します。</div>
            </div>
          </label>
```

ステップバー: 手順 4 の行を次に変え、末尾に注記を足す:

```html
    <div class="step" data-step="4"><span class="n">4</span><span id="step4-label">SVGに書き出す</span></div>
    <span class="skipnote" id="gray-skipnote" hidden>手順 2・3 は省略されます</span>
```

手順 4 の `<section class="screen" data-screen="4">` の直後（`<div class="center-scroll">` の前）に挿入:

```html
      <nav class="pagenav-rail" id="pagenav-4" hidden></nav>
      <div class="editor" id="fig-editor" hidden>
        <div class="canvas-scroll"><div class="doc-stage" id="fig-stage"></div></div>
        <div class="fig-hint" id="fig-hint"><b>クリック</b>で採用 / 解除 ・ 何もない場所を<b>ドラッグ</b>で範囲を追加</div>
        <div class="page-nav"><span class="pg" id="pgnav-4"></span></div>
        <div class="zoom-ctrl">
          <button class="zb" data-zoomact="out" title="縮小"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"></path></svg></button>
          <button class="zb zlabel" data-zoomact="reset" title="フィットに戻す"><span class="zpct">100%</span></button>
          <button class="zb" data-zoomact="in" title="拡大"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"></path></svg></button>
        </div>
      </div>
```

同じ section の `<div class="center-scroll">` に `id="export-center"` を付ける。`<div class="segment">`（書き出し範囲）の直後に、グレー用の範囲を足す:

```html
            <div class="segment" id="exp-modes-gray" hidden>
              <button data-mode="page" aria-pressed="false">表示中のページの図</button>
              <button data-mode="all" aria-pressed="true">全ページの採用した図</button>
            </div>
```

既存の `<div class="segment">` には `id="exp-modes"` を付ける。`<h1>SVG に書き出す</h1>` に `id="export-title"` を付ける。

`<div id="file-cards"></div>` の下、`.filelist` の中身は変えない。

- [ ] **Step 4: `styles.css` に追記する**

```css
/* ── グレーモード: 手順 1 のチェック・ステップバー・手順 4 の 3 ペイン ── */
.modebox { margin-top: 22px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface); padding: 14px 16px; display: flex; gap: 14px; align-items: flex-start; cursor: pointer; }
.modebox.on { border-color: var(--ink); background: var(--sunk); }
.modebox input { width: 20px; height: 20px; margin: 2px 0 0; accent-color: var(--ink); flex: none; }
.modebox .t { font-family: var(--font-round); font-weight: 700; font-size: 15px; }
.modebox .d { color: var(--muted); font-size: 12.5px; margin-top: 4px; line-height: 1.6; }
.stepbar.gray-mode .step[data-step="2"], .stepbar.gray-mode .step[data-step="3"],
.stepbar.gray-mode .step[data-step="2"] + .step-sep, .stepbar.gray-mode .step[data-step="3"] + .step-sep { display: none; }
.stepbar .skipnote { margin-left: 8px; color: var(--faint); font-size: 12px; }
.screen[data-screen="4"].gray #export-center { flex: none; width: 380px; border-left: 1px solid var(--border); background: var(--surface); padding: 22px 18px; }
.screen[data-screen="4"].gray .sheet { max-width: none; }
.screen[data-screen="4"].gray #exp-modes { display: none; }
#fig-stage svg { display: block; }
.fig-hint { position: absolute; left: 50%; bottom: 62px; transform: translateX(-50%); background: var(--surface); border: 1px solid var(--border); border-radius: 999px; padding: 6px 14px; font-size: 12px; color: var(--muted); box-shadow: var(--shadow-card); white-space: nowrap; z-index: 6; }
.fig-hint b { color: var(--ink); }
.fig-cand { position: absolute; border: 2px dashed var(--accent); background: oklch(0.585 0.105 240 / 0.06); cursor: pointer; border-radius: 3px; box-sizing: border-box; }
.fig-cand.sel { border: 2px solid var(--good); background: transparent; box-shadow: 0 0 0 9999px oklch(0.4 0.02 262 / 0.28); }
.fig-cand .tag { position: absolute; left: -2px; top: -24px; background: var(--accent); color: #fff; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 6px; white-space: nowrap; pointer-events: none; }
.fig-cand.sel .tag { background: var(--good); }
.fig-cand .del { position: absolute; right: -12px; top: -12px; width: 24px; height: 24px; border-radius: 50%; background: var(--surface); border: 1px solid var(--border-strong); display: none; place-items: center; font-size: 13px; color: var(--muted); box-shadow: var(--shadow-card); cursor: pointer; padding: 0; }
.fig-cand.sel .del { display: grid; }
.fig-cand .h { position: absolute; width: 10px; height: 10px; background: #fff; border: 2px solid var(--good); border-radius: 2px; display: none; }
.fig-cand.sel .h { display: block; }
.fig-cand .h.nw { left: -6px; top: -6px; cursor: nwse-resize; } .fig-cand .h.se { right: -6px; bottom: -6px; cursor: nwse-resize; }
.fig-cand .h.ne { right: -6px; top: -6px; cursor: nesw-resize; } .fig-cand .h.sw { left: -6px; bottom: -6px; cursor: nesw-resize; }
#fig-editor .doc-stage { cursor: crosshair; }
```

- [ ] **Step 5: `figure.js` を作る**

```js
// =============================================================================
// figure.js — グレーモード (手順 4) のレール・候補矩形オーバーレイ・ハンドル操作
// =============================================================================
// 状態は `state.js` の `S.figCand` / `S.figSel` を直接読み書きし、再描画だけは
// `initFigure` で注入された `render` (app.js) へ委譲する。
// オーバーレイは SVG の外 (host 直下の div) に置くので、`bakeSvg` 相当の書き出しには
// 混ざらない (書き出しはサーバの `exportSvg` が clip を受けて別生成する)。
import { esc } from "./dom.js";
import { clientToPage } from "./geometry.js";
import { S, figKey, figSelOf, figCount } from "./state.js";

var ui = { render: function () {} };
function initFigure(deps) { ui = deps; }

var MIN_SIZE_PT = 4; // これ未満の矩形は誤クリックとみなして作らない

function sameRect(a, b) { return a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h; }
function copyRect(r) { return { x: r.x, y: r.y, w: r.w, h: r.h }; }

/** 左レール: ページ一覧 + 候補/採用のバッジ。クリックでページ移動 */
function buildFigRail(navId) {
  var html = '<div class="pl-head"><div class="pl-title">全 <b>' + S.TOTAL + "</b> ページ　採用 <b>" + figCount() + "</b> 図</div></div>";
  html += '<div class="pl-body">';
  var g = 0;
  S.FILES.forEach(function (f) {
    html += '<div class="pl-file"><span class="fname">' + esc(f.name) + "</span></div>";
    for (var p = 0; p < f.pages; p++) {
      var gg = g + p;
      var n = figSelOf(gg).length;
      var cand = (S.figCand[figKey(S.PAGES[gg])] || []).length;
      var cls = n ? "done" : (cand ? "pending" : "none");
      var tag = n ? '<span class="tg t-done">採用 ' + n + "</span>" : (cand ? '<span class="tg t-pending">候補</span>' : "");
      html += '<div class="pg-row2 ' + cls + (gg === S.page ? " current" : "") + '" data-g="' + gg + '">' +
        '<span style="width:17px;flex:none"></span><span class="dot">' + (p + 1) + '</span><span class="lbl">' + (p + 1) + " ページ</span>" + tag + "</div>";
    }
    g += f.pages;
  });
  html += "</div>";
  var nav = document.getElementById(navId);
  nav.innerHTML = html;
  nav.querySelectorAll("[data-g]").forEach(function (row) {
    row.addEventListener("click", function () { S.page = +row.dataset.g; ui.render(); });
  });
}

/** ページ座標 (pt) の矩形を host 相対の px に置く */
function placeRect(box, r, svgEl, host) {
  var sr = svgEl.getBoundingClientRect(), hb = host.getBoundingClientRect(), vb = svgEl.viewBox.baseVal;
  var sx = sr.width / vb.width, sy = sr.height / vb.height;
  box.style.left = ((r.x - vb.x) * sx + sr.left - hb.left) + "px";
  box.style.top = ((r.y - vb.y) * sy + sr.top - hb.top) + "px";
  box.style.width = (r.w * sx) + "px";
  box.style.height = (r.h * sy) + "px";
}

/** 候補 (点線) と採用 (実線) を host に重ねる。呼ぶたびに全部描き直す */
function drawFigOverlay(host) {
  host.querySelectorAll(".fig-cand").forEach(function (b) { b.remove(); });
  var svgEl = host.querySelector("svg"); if (!svgEl || !S.PAGES[S.page]) return;
  var sel = figSelOf(S.page);
  var cands = S.figCand[figKey(S.PAGES[S.page])] || [];
  cands.forEach(function (r, i) {
    if (sel.some(function (s) { return sameRect(s, r); })) return; // 採用済みは実線側で描く
    var box = document.createElement("div");
    box.className = "fig-cand"; box.setAttribute("role", "button"); box.tabIndex = 0;
    box.innerHTML = '<span class="tag">候補 ' + (i + 1) + "</span>";
    placeRect(box, r, svgEl, host);
    box.addEventListener("click", function (e) { e.stopPropagation(); sel.push(copyRect(r)); ui.render(); });
    host.appendChild(box);
  });
  sel.forEach(function (r, i) {
    var box = document.createElement("div");
    box.className = "fig-cand sel"; box.dataset.sel = i;
    box.innerHTML = '<span class="tag">採用 ' + (i + 1) + " ・ " + Math.round(r.w) + " × " + Math.round(r.h) + " pt</span>" +
      '<button type="button" class="del" title="採用を外す">×</button>' +
      '<span class="h nw" data-corner="nw"></span><span class="h ne" data-corner="ne"></span>' +
      '<span class="h sw" data-corner="sw"></span><span class="h se" data-corner="se"></span>';
    placeRect(box, r, svgEl, host);
    box.querySelector(".del").addEventListener("click", function (e) { e.stopPropagation(); sel.splice(i, 1); ui.render(); });
    box.querySelectorAll(".h").forEach(function (h) {
      h.addEventListener("mousedown", function (e) {
        e.stopPropagation(); e.preventDefault();
        S.figDrag = { mode: "resize", rect: r, corner: h.dataset.corner, orig: copyRect(r) };
      });
    });
    box.addEventListener("click", function (e) { e.stopPropagation(); });
    host.appendChild(box);
  });
}

/** 空白ドラッグで矩形追加、角ハンドルで伸縮。起動時に一度だけ張る (多重登録防止) */
function installFigDrag(host) {
  host.addEventListener("mousedown", function (e) {
    if (S.phase !== 4 || !S.gray) return;
    if (e.target.closest(".fig-cand")) return;
    if (!host.querySelector("svg")) return;
    var rubber = document.createElement("div");
    rubber.className = "crop-rubber";
    host.appendChild(rubber);
    S.figDrag = { mode: "add", origin: { x: e.clientX, y: e.clientY }, rubber: rubber };
    e.preventDefault();
  });
  window.addEventListener("mousemove", function (e) {
    var d = S.figDrag; if (!d) return;
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    if (d.mode === "add") {
      var hb = host.getBoundingClientRect();
      var x1 = Math.min(d.origin.x, e.clientX), y1 = Math.min(d.origin.y, e.clientY);
      var x2 = Math.max(d.origin.x, e.clientX), y2 = Math.max(d.origin.y, e.clientY);
      d.rubber.style.left = (x1 - hb.left) + "px"; d.rubber.style.top = (y1 - hb.top) + "px";
      d.rubber.style.width = (x2 - x1) + "px"; d.rubber.style.height = (y2 - y1) + "px";
      return;
    }
    // resize: 掴んだ角を動かし、反対の角は固定する
    var p = clientToPage(svgEl, e.clientX, e.clientY);
    var o = d.orig, c = d.corner;
    var left = c.indexOf("w") >= 0 ? p.x : o.x, right = c.indexOf("e") >= 0 ? p.x : o.x + o.w;
    var top = c.indexOf("n") >= 0 ? p.y : o.y, bottom = c.indexOf("s") >= 0 ? p.y : o.y + o.h;
    d.rect.x = Math.min(left, right); d.rect.y = Math.min(top, bottom);
    d.rect.w = Math.max(MIN_SIZE_PT, Math.abs(right - left)); d.rect.h = Math.max(MIN_SIZE_PT, Math.abs(bottom - top));
    var box = host.querySelector('.fig-cand.sel[data-sel="' + figSelOf(S.page).indexOf(d.rect) + '"]');
    if (box) placeRect(box, d.rect, svgEl, host);
  });
  window.addEventListener("mouseup", function (e) {
    var d = S.figDrag; if (!d) return;
    S.figDrag = null;
    if (d.mode === "resize") { ui.render(); return; }
    d.rubber.remove();
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    var a = clientToPage(svgEl, d.origin.x, d.origin.y);
    var b = clientToPage(svgEl, e.clientX, e.clientY);
    var w = Math.abs(a.x - b.x), h = Math.abs(a.y - b.y);
    if (w < MIN_SIZE_PT || h < MIN_SIZE_PT) return;
    figSelOf(S.page).push({ x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: w, h: h });
    ui.render();
  });
}

export { initFigure, buildFigRail, drawFigOverlay, installFigDrag };
```

- [ ] **Step 6: `app.js` を変える**

import を変更:

```js
import {
  S, counts, pass, initStatus,
  statusArr, changedArr, selSet, pkey, curElSel, statusOfCur, selKeys, selCount, clearSel,
  applyState, invalidateAll, nextPending, firstPending, advancePhase,
  exportPageList, expCount, zipName, chunkBySize,
  figKey, svgKey, figSelOf, figCount, seedFigSel, exportFigureList,
  phaseAfterLoad, phaseBeforeExport, stepAllowed,
} from "./state.js";
import { fileIcon, xIcon, checkD, ckMark } from "./icons.js";
import { initRail, buildRail } from "./rail.js";
import { initFigure, buildFigRail, drawFigOverlay, installFigDrag } from "./figure.js";
```

`ensureSvg` / `invalidate` を置き換え（キーにグレーを含める）:

```js
  async function ensureSvg(fi, pi) {
    var k = svgKey(fi, pi);
    if (!S.svgCache[k]) S.svgCache[k] = await rpc("pageSvg", { fileIndex: fi, pageInFile: pi, grayscale: S.gray });
    return S.svgCache[k];
  }
  function invalidate(fi, pi) { delete S.svgCache[fi + ":" + pi]; delete S.svgCache[fi + ":" + pi + ":g"]; }
```

`rescaleCurrent` の host 選択と再描画を置き換え:

```js
  function rescaleCurrent() {
    var host = document.getElementById(S.phase === 2 ? "doc-master" : (S.phase === 3 ? "trim-stage" : "fig-stage"));
    if (!host) return;
    var svgEl = host.querySelector("svg");
    var pg = S.PAGES[S.page];
    var data = pg && S.svgCache[svgKey(pg.fileIndex, pg.pageInFile)];
    if (svgEl && data) {
      scalePage(svgEl, data.width, data.height, app.querySelector('[data-screen="' + S.phase + '"] .editor'));
      if (S.phase === 3) drawSelBoxes(host); // sel-box は host 相対なので再計算
      if (S.phase === 4) drawFigOverlay(host);
    }
    updateZoomLabel();
  }
```

`mountPage` 内の `if (!S.svgCache[pg.fileIndex + ":" + pg.pageInFile])` を `if (!S.svgCache[svgKey(pg.fileIndex, pg.pageInFile)])` にする。

`render()` を次のように変える（差分箇所のみ。他は既存のまま）:

```js
    var stepbar = document.getElementById("stepbar");
    stepbar.classList.toggle("gray-mode", S.gray);
    document.getElementById("gray-skipnote").hidden = !S.gray;
    document.getElementById("step4-label").textContent = S.gray ? "図をグレーで書き出す" : "SVGに書き出す";
    var screen4 = app.querySelector('[data-screen="4"]');
    screen4.classList.toggle("gray", S.gray);
    document.getElementById("pagenav-4").hidden = !S.gray;
    document.getElementById("fig-editor").hidden = !S.gray;
    document.getElementById("exp-modes-gray").hidden = !S.gray;
    document.getElementById("export-title").textContent = S.gray ? "図をグレーで書き出す" : "SVG に書き出す";
    document.getElementById("gray-mode-box").classList.toggle("on", S.gray);
```

（`screens.forEach(...)` の直後に置く。）

`if (S.phase === 4)` の分岐（`else if (S.phase === 4) {` ブロック）を置き換え:

```js
    } else if (S.phase === 4 && S.gray) {
      var pg4 = S.PAGES[S.page];
      setHint("図を確認して書き出します。採用 <b>" + figCount() + "</b> 図");
      ctxText.textContent = S.FILES[pg4.fileIndex].name + " ・ " + (pg4.pageInFile + 1) + "/" + S.FILES[pg4.fileIndex].pages + " ページ";
      refreshExport();
      document.getElementById("export-summary").innerHTML =
        S.FILES.length + "ファイル・全" + S.TOTAL + "ページ<br/>採用 " + figCount() + " 図・グレースケール";
    } else if (S.phase === 4) {
      ...  // 既存のまま
```

`render()` の末尾（`if (S.phase === 3 && S.TOTAL) {...}` の後）に追加:

```js
    if (S.phase === 4 && S.gray && S.TOTAL) {
      buildFigRail("pagenav-4");
      document.getElementById("pgnav-4").innerHTML = pageLabel();
      var host4 = document.getElementById("fig-stage");
      ensureFigCand(S.page);
      // 検出ゼロ (取得済みで候補も採用も無い) のページは手動へ誘導する (spec 2 節 4.)
      var candCur = S.figCand[figKey(S.PAGES[S.page])];
      document.getElementById("fig-hint").innerHTML =
        (Array.isArray(candCur) && !candCur.length && !figSelOf(S.page).length)
          ? "このページに図は見つかりませんでした。範囲を<b>ドラッグ</b>で指定してください"
          : "<b>クリック</b>で採用 / 解除 ・ 何もない場所を<b>ドラッグ</b>で範囲を追加";
      mountPage(host4, app.querySelector('[data-screen="4"] .editor'), false, function () { drawFigOverlay(host4); });
      updateZoomLabel();
    }
```

`render()` の直前にヘルパを追加:

```js
  // 候補を未取得のページだけ取りに行き、届いたら 1 回だけ再描画する (取得済みなら何もしないので再帰しない)。
  async function ensureFigCand(g) {
    var pg = S.PAGES[g]; if (!pg) return;
    var k = figKey(pg);
    if (S.figCand[k] !== undefined) return;
    S.figCand[k] = null; // 取得中の印 (二重要求を防ぐ)
    try {
      var res = await rpc("figureCandidates", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
      seedFigSel(g, res.rects || []);
    } catch (e) {
      delete S.figCand[k];
      toast("図の検出に失敗しました: " + String((e && e.message) || e));
      return;
    }
    if (S.phase === 4 && S.gray) render();
  }
```

`figure.js` の `buildFigRail` は `S.figCand[k]` が `null`（取得中）でも `[]` 扱いになるよう `(S.figCand[...] || [])` で読んでいるので変更不要。

`tryNext` / `back` / ステップクリックを置き換え:

```js
  function tryNext() {
    if (S.phase === 1) { if (!S.TOTAL) return; S.phase = phaseAfterLoad(); S.page = 0; S.guarding = false; render(); return; }
    ...  // 既存のまま
  }
  function back() {
    S.guarding = false;
    if (S.phase === 2) S.phase = 1; else if (S.phase === 3) { S.phase = 2; S.page = 0; } else if (S.phase === 4) { S.phase = phaseBeforeExport(); S.page = 0; }
    render();
  }
```

`wireNav` のステップクリック:

```js
        var n = +st.dataset.step; if (n > S.phase || !S.TOTAL || !stepAllowed(n)) return;
```

`wireLoadUi` の末尾に追加:

```js
    document.getElementById("chk-gray").addEventListener("change", function () {
      S.gray = this.checked;
      S.expMode = "all";  // グレーモードに noskip / spec は無い (手順 2・3 を通らない)
      S.svgCache = {};    // カラー/グレーで SVG が違う (キーも違うが、古い方を持ち続けない)
      render();
    });
```

`wireZoom` のセレクタと phase 判定に手順 4 を足す:

```js
    app.querySelectorAll('[data-screen="2"] .editor, [data-screen="3"] .editor, [data-screen="4"] .editor').forEach(function (ed) {
      ed.addEventListener("wheel", function (e) {
        if (!e.ctrlKey || (S.phase !== 2 && S.phase !== 3 && S.phase !== 4)) return;
```

`wireStatic` に `installFigDrag(document.getElementById("fig-stage"));` を追加し、起動部の `initRail(...)` の次に `initFigure({ render: render });` を足す。

`refreshExport` の末尾の 1 行を置き換え:

```js
    var num = S.gray ? (S.expMode === "page" ? figSelOf(S.page).length : figCount()) : expCount(expSpecValue(), parseSpec);
    document.getElementById("exp-num").textContent = num;
    var btn = document.getElementById("btn-export");
    if (btn) btn.disabled = S.gray && num === 0;
```

`wireExportPane` の `.segment [data-mode]` のクリックは `#exp-modes-gray` のボタンにも同じリスナーが付く（セレクタが両方に一致する）。グレーモードで `noskip` / `spec` が残らないよう、上の `chk-gray` リスナーで `S.expMode` を `"all"` へ戻している。

`doExport` の先頭（`try {` の直後）に図の分岐を足し、以降の ZIP 処理を共通化する:

```js
  async function doExport() {
    var btn = document.getElementById("btn-export");
    var prog = document.getElementById("exp-progress");
    try {
      if (S.gray) {
        var figs = exportFigureList();
        if (!figs.length) { setHint("採用した図がありません。ページ上の候補をクリックしてください。"); return; }
        await exportEntries(figs, btn, prog);
        return;
      }
      if (S.expMode === "page") {
        ...  // 既存のまま
      }
      var list = exportPageList(expSpecValue(), parseSpec);
      if (!list.length) { setHint("書き出す対象のページがありません。"); return; }
      await exportEntries(list, btn, prog);
    } catch (e) {
      ...  // 既存のまま
    } finally {
      ...  // 既存のまま
    }
  }

  // `exportSvg` をページ (または図) ごとに呼び、1 件なら直接ダウンロード、複数は ZIP へ集約する。
  // 既存の全ページ書き出しと図の書き出しで同じ経路を使う (進捗・ZIP 分割・文言を二重に持たない)。
  async function exportEntries(list, btn, prog) {
    if (btn) btn.disabled = true;
    if (prog) { prog.hidden = false; prog.max = list.length; prog.value = 0; }
    var entries = [];
    for (var i = 0; i < list.length; i++) {
      setHint("書き出し中 " + (i + 1) + "/" + list.length);
      var item = await rpc("exportSvg", list[i]);
      entries.push({ name: item.name, text: item.svg });
      if (prog) prog.value = i + 1;
    }
    if (entries.length === 1) {
      downloadBlob(entries[0].name, entries[0].text, "image/svg+xml");
      setHint('<b style="color:var(--good-ink)">1個のSVGのダウンロードを開始しました。</b>');
      toast("1個のSVGのダウンロードを開始しました");
      return;
    }
    var chunks = chunkBySize(entries, entryRequestBytes, ZIP_REQUEST_BUDGET);
    var base = zipName(list);
    var total = 0;
    for (var c = 0; c < chunks.length; c++) {
      setHint(chunks.length === 1 ? "ZIP にまとめています…" : "ZIP にまとめています… " + (c + 1) + "/" + chunks.length);
      var z = await rpc("zipEntries", { entries: chunks[c] });
      downloadBlob(chunks.length === 1 ? base : zipPartName(base, c + 1), b64ToBytes(z.zipBase64), "application/zip");
      total += z.count;
    }
    var suffix = chunks.length === 1 ? " ZIP でダウンロード開始しました。" : " ZIP " + chunks.length + " 本に分けてダウンロード開始しました。";
    setHint('<b style="color:var(--good-ink)">' + total + "個のSVGを" + suffix + "</b>");
    toast(total + "個のSVGを" + (chunks.length === 1 ? " ZIP 1 ファイルで" : " ZIP " + chunks.length + " ファイルに分けて") + "ダウンロード開始しました");
  }
```

（既存 `doExport` の「全ページ」経路の本体をそのまま `exportEntries` へ移し、`doExport` 側からは削る。元のコメントも一緒に移す。）

- [ ] **Step 7: E2E と JS 単体を通す**

Run: `cd pdf-to-svg && py -3.13 -m pytest test -m e2e -v`
Expected: 既存 5 + 新規 1 = 6 passed

Run: `cd pdf-to-svg && py -3.13 -m pytest test -v`
Expected: すべて passed（`test_pdftosvg_js_smoke.py` が新モジュールの構文も読む）

- [ ] **Step 8: 実 PDF で目視確認する（テストではない）**

Run: `cd pdf-to-svg && py -3.13 src/app.py`
手順: `_id_140823_type_k.pdf` を取り込み → チェック ON → 次へ → 8 ページ目に採用矩形が出る → 書き出し → Downloads の `_id_140823_type_k_p8_fig1_gray.svg` を Edge と PowerPoint で開き、灰色・文字選択可・図の外が無いことを見る。ずれがあれば `FIGURE_EXPAND_TOL` ではなく E2E フィクスチャとの差を疑う。

- [ ] **Step 9: コミット**

```bash
git add pdf-to-svg/resources/web/index.html pdf-to-svg/resources/web/styles.css pdf-to-svg/resources/web/figure.js pdf-to-svg/resources/web/app.js pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py
git commit -m "feat(pdf-to-svg): 図だけをグレースケールで書き出すモードの UI を追加する"
```

`test/fixtures/stewardship_sample.pdf` は fixture が毎回生成するので、他の生成物（`vector_sample.pdf` 等）と同じ扱いにする（既にコミットされていれば追加、`.gitignore` 対象ならそのまま）。`git status` で確認する。

---

### Task 9: ドキュメント

**Files:**
- Modify: `docs/pdf-to-svg/src/設計正典.md`
- Modify: `docs/pdf-to-svg/src/設計書.md`
- Modify: `docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`
- Modify: `docs/pdf-to-svg/src/操作手順書.md`
- Modify: `README.md`

すべて通常の日本語・既存の文体で書く。原稿は本リポが単独の正典で、monorepo との突き合わせは不要。

- [ ] **Step 1: 設計正典**

「モジュール構成」の表に 2 行を足す:

```
| `src/model/figure_detect.py` | 「当社のスチュワードシップ活動」の図を文字アンカーで検出する純粋関数（fitz 非依存） |
| `src/export/grayscale.py` | 色 hex／色名／画像バイトを Rec.601 でグレースケール化する純粋関数（Pillow） |
```

「中核原則」の末尾に 2 項を足す:

```
- **図検出は model 層の純粋関数・fitz 非依存**: `figure_detect.py` は `Page.live_elements()` の
  bbox と文字列だけで判定する。見出し「当社のスチュワードシップ活動」+ 図内ラベル 3 件以上を
  文字で探し、近傍の図形へ不動点まで広げる。幾何の指紋（曲線の本数等）へ戻さない（レイアウト
  変更で外れ、強調ボックスの誤検出が多い）。候補は 1 ページ最大 1 件、無ければ手動へ倒す。
- **グレー化・切り出しは exporter のオプション**（`page_to_svg(grayscale, clip)`）: モデルは
  変更せず、モードはクライアントが持って毎リクエスト引数で渡す。クライアントで SVG を書き換えない。
  **SVG フィルタ（feColorMatrix）は使わない**（Office はフィルタを無視してカラーのまま貼り付き、
  ブラウザ印刷は文字をラスタ化する）。色は Rec.601 整数式、画像は Pillow の `L`/`LA` で、係数を
  揃える。既定 OFF は従来出力とバイト一致。
```

- [ ] **Step 2: 設計書**

3 章の末尾に「## 3.4 図検出（`src/model/figure_detect.py`）」を追加し、spec 4 節（判定手順・定数・資源上限・実測表）を設計書の文体で書く。5 章の末尾に「## 5.3 グレースケールと切り出し（`src/export/grayscale.py`、`page_to_svg` の `grayscale` / `clip`）」を追加し、spec 5・6 節を書く。7.2 節の RPC 一覧に `figureCandidates` と `pageSvg` / `exportSvg` の引数追加を書く。8 章に「グレーモード」の小節を足し、spec 8 節（状態・遷移・3 ペイン）を書く。

- [ ] **Step 3: 仕様一覧**

「画面項目定義」に手順 1 のチェックボックス（`#chk-gray`）、手順 4 のレール（`#pagenav-4`）・キャンバス（`#fig-stage`）・候補矩形（`.fig-cand`）・書き出し範囲（`#exp-modes-gray`）を行として足す。「入出力定義」に出力ファイル名 `<元ファイル名>_p<N>_fig<k>_gray.svg` / `<元ファイル名>_gray_svg.zip` を足す。「RPC・HTTP」に `figureCandidates` を足し、`pageSvg` / `exportSvg` の引数欄に `grayscale` / `clip` / `figIndex` を足す。「テスト仕様」に `test_grayscale.py` / `test_export_clip.py` / `test_figure_detect.py` と E2E `test_gray_figure_flow` を足す。

- [ ] **Step 4: 操作手順書**

3 章（ステップ 1）の末尾に「3.x 図だけをグレースケールで書き出したいとき」を追加: チェックの場所、ON にすると手順 2・3 が省略されること、対象は「当社のスチュワードシップ活動」の図であること。6 章（ステップ 4）に「6.x 図の選択画面」を追加: 点線 = 候補（クリックで採用）、実線 = 採用済み（角で伸縮・× で外す）、空白ドラッグで自前の範囲、見つからないときは手動で囲む、ファイル名の規則。スクリーンショットは「（画面写真は後日差し替え）」と注記し、撮影は別タスクとする。

- [ ] **Step 5: README**

`- pdf-to-svg: ...` の行の直後に 1 行:

```
  - 運用報告書の「当社のスチュワードシップ活動」の図だけを切り出してグレースケール SVG にする専用モードあり。
```

- [ ] **Step 6: HTML 生成が壊れていないことを確認する**

Run: `py -3.13 -m pytest docs/_build -v`
Expected: passed

- [ ] **Step 7: コミット**

```bash
git add docs/pdf-to-svg/src/設計正典.md docs/pdf-to-svg/src/設計書.md docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md docs/pdf-to-svg/src/操作手順書.md README.md
git commit -m "docs(pdf-to-svg): 図のグレースケール書き出しモードを設計正典・設計書・仕様一覧・操作手順書へ反映"
```

---

## 完了条件

- `py -3.13 -m pytest pdf-to-svg` と `py -3.13 -m pytest pdf-to-svg -m e2e` が全通過（pre-push フックが実行する）。
- `py -3.13 -m pytest scripts` / `docs/_build` / `graph-editor` も通過（同フック）。
- 実 PDF での目視確認（Task 8 Step 8）を済ませ、結果を最終報告に書く。
- 完了後は `superpowers:finishing-a-development-branch` でブランチの扱い（main へのマージ）を決める。
