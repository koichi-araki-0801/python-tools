# 画像 + 不可視 OCR 文字層の上書き描画 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 画像 + 不可視 OCR 文字層の PDF で、辞書置換した箇所を背景色の矩形で隠して置換語を描き、
置換していない OCR 文字を書き出しから外す。文字が読み取れないページ向けに、範囲をドラッグして
置換語を置く手動の上書き(移動・伸縮・語の変更・Undo 可)を手順 3 に足す。

**Architecture:** 抽出側は PyMuPDF の `get_texttrace()` の描画モードから `TextElement.invisible` を
立てるだけ。矩形と文字色はモデルに持たず、`page_to_svg` が新規モジュール `export/cover.py`
(Pillow による背景画素の採色)を使って書き出し時に合成する。手動の上書きは「不可視かつ
置換済み扱いの `TextElement`」を `AddElementCommand` で足す形にし、描画は自動置換と同じ経路を通す。

**Tech Stack:** Python 3.13 / PyMuPDF (`fitz`、`engine/pdf_engine.py` に隔離) / Pillow / 標準
`ThreadingHTTPServer` + JSON RPC / 素の JavaScript (ES modules) / pytest + Playwright (Edge)。

**Spec:** `docs/superpowers/specs/2026-09-12-ocr-layer-cover-design.md`

## Global Constraints

- Python は常に `py -3.13` で起動し、pytest は `pdf-to-svg/` を個別指定する
  (`py -3.13 -m pytest pdf-to-svg`)。`xdist` / `pytest-randomly` は使わない。
- `fitz` を import してよいのは `src/engine/pdf_engine.py` と `src/engine/classify.py` だけ
  (AGPL 依存の隔離)。`export/` `model/` `web/` から `fitz` を import しない。
- SVG 属性は `svg_exporter._attr` / `_paint` 経由でのみ書く。f-string で `="{...}"` を組まない
  (`test/test_export_escaping.py` が機械検査する)。
- 不可視文字を持たない PDF の出力は 1 バイトも変えない(`test/test_pipeline.py` が固定)。
- 新規 `.py` はモジュール先頭 docstring、新規 `.js` は `// ===` 装飾ボックスヘッダを付ける
  (`docs/コメント規約.md`。pre-commit の `scripts/check_comments.py --staged` が検査する)。
  コメントは「なぜ」を現在形で書き、経緯・日付・所見番号を書かない。
- 攻撃者が用意できる入力(PDF の画像・RPC 引数)は上限を置き、上限に当たったら degrade する。
  例外で書き出し全体を止めない。
- ブラウザの `alert` / `prompt` / `confirm` は使わない。
- コミットは main へ直接。post-commit フックが auto-push し、pre-push が検証一式(約 2 分)を
  回す。コミットメッセージは Conventional Commits の日本語 (`feat(export): ...`)。
- 会話は原始人モードだが、コード・コメント・コミットメッセージ・文書は通常の日本語で書く。

## File Structure

| ファイル | 変更 | 責務 |
|---|---|---|
| `pdf-to-svg/src/model/elements.py` | 変更 | `TextElement.invisible` / `manual_cover` の 2 フィールド追加 |
| `pdf-to-svg/src/engine/pdf_engine.py` | 変更 | texttrace の描画モードから不可視 seqno の集合を作り、照合成功した span だけ `invisible` を立てる |
| `pdf-to-svg/src/export/cover.py` | 新規 | 画像デコード(上限付き)と bbox 内の量子化最頻色から背景色・文字色を決める純粋関数 |
| `pdf-to-svg/src/export/svg_exporter.py` | 変更 | `ExportReport`、不可視文字の 3 分岐、`<g><rect><text>` 合成、採色元の解決、`_with_data_el` の `<g>` 対応 |
| `pdf-to-svg/src/web/commands.py` | 変更 | `UpdateCoverCommand` 追加 |
| `pdf-to-svg/src/web/rpc_methods.py` | 変更 | `state.ocrPages`、`pageSvg`/`exportSvg` の `coverFallback`、`addCover` / `coverList` / `updateCover`、`planPage` の除外、`removedList` のラベル |
| `pdf-to-svg/resources/web/state.js` | 変更 | `coverText` / `coverSel` / `coverDrag` の状態 |
| `pdf-to-svg/resources/web/cover.js` | 新規 | 手順 3「上書き」ツールのオーバーレイ(角ハンドル・移動)と `updateCover` 呼び出し |
| `pdf-to-svg/resources/web/app.js` | 変更 | トースト 2 種、ツール切替、ドラッグ → `addCover`、入力欄 → `updateCover`、オーバーレイの描画呼び出し |
| `pdf-to-svg/resources/web/index.html` | 変更 | 「上書き」ボタンと `cover-opts` 入力欄 |
| `pdf-to-svg/resources/web/styles.css` | 変更 | `.cover-box` とハンドルのスタイル |
| `pdf-to-svg/test/conftest.py` | 変更 | `ocr_layer_pdf` フィクスチャ |
| `pdf-to-svg/test/test_cover.py` | 新規 | `cover.py` 単体 |
| `pdf-to-svg/test/test_ocr_layer.py` | 新規 | 抽出 → 書き出し → RPC の結合 |
| `pdf-to-svg/test/test_web_rpc.py` | 変更 | `ocrPages` / `coverFallback` / `addCover` / `coverList` / `updateCover` |
| `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` | 変更 | 「上書き」ツールの E2E 2 本 |
| `docs/pdf-to-svg/src/設計正典.md` ほか原稿 4 冊 | 変更 | 文書更新と HTML 再生成 |

すべてのパスは `C:\Users\caads\python-tools` からの相対パス。pytest は `pdf-to-svg/` で
実行する(`cd pdf-to-svg` してから `py -3.13 -m pytest test/...`。`conftest.py` が `src/` を
import パスへ載せるので `from engine.pdf_engine import load_document` の形で書く)。

---

### Task 1: 不可視文字の検出(モデル + 抽出)

**Files:**
- Modify: `pdf-to-svg/src/model/elements.py:141-160`(`TextElement`)
- Modify: `pdf-to-svg/src/engine/pdf_engine.py:189-191`(texttrace の収集)、`:224-233`(span ループ)、`:397-425`(`_text_element`)
- Modify: `pdf-to-svg/test/conftest.py`(フィクスチャ追加)
- Test: `pdf-to-svg/test/test_ocr_layer.py`(新規)

**Interfaces:**
- Produces: `TextElement.invisible: bool = False`、`TextElement.manual_cover: bool = False`。
  `pdf_engine._invisible_seqnos(traces: list[dict]) -> set[int]`。
  `pdf_engine._text_element(span: dict, z: int, invisible: bool = False) -> Optional[TextElement]`。
  pytest フィクスチャ `ocr_layer_pdf -> Path`(300×200pt。上 40pt が帯色 `(200, 220, 240)`、
  下は白の全面画像。不可視文字 `Header Text` が帯の上(原点 (20, 30))、`Body line one` が
  白地(原点 (20, 120))、可視文字 `visible text` が (20, 150))。

- [ ] **Step 1: フィクスチャを足す**

`pdf-to-svg/test/conftest.py` の `scanned_pdf` の直後に追加する。

```python
@pytest.fixture(scope="session")
def ocr_layer_pdf() -> Path:
    """全面画像 + 不可視 (render_mode=3) の OCR 文字層を持つ「検索可能 PDF」風の PDF。

    画像は上 40pt が帯色 (200, 220, 240)・下が白。不可視文字は帯の上と白地の上に 1 行ずつ、
    可視文字を 1 行置く (不可視判定が可視文字を巻き込まないことの対照)。
    """
    FIXTURES.mkdir(exist_ok=True)
    path = FIXTURES / "ocr_layer_sample.pdf"
    img = Image.new("RGB", (600, 400), (255, 255, 255))
    for y in range(0, 80):
        for x in range(600):
            img.putpixel((x, y), (200, 220, 240))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_image(page.rect, stream=buf.getvalue())
    page.insert_text((20, 30), "Header Text", fontsize=12, render_mode=3)
    page.insert_text((20, 120), "Body line one", fontsize=12, render_mode=3)
    page.insert_text((20, 150), "visible text", fontsize=12, render_mode=0)
    doc.save(str(path))
    doc.close()
    return path
```

- [ ] **Step 2: 失敗するテストを書く**

`pdf-to-svg/test/test_ocr_layer.py` を新規作成する。

```python
"""画像 + 不可視 OCR 文字層の PDF に対する抽出・書き出し・RPC の結合テスト。

`ocr_layer_pdf` (conftest) は全面画像の上に不可視 (render_mode=3) の文字を 2 行、可視の
文字を 1 行持つ。不可視文字が `invisible` を持ち、書き出しでは未置換なら出ず・置換済みなら
背景色の矩形 + 文字になることを確認する。
"""
from __future__ import annotations

from engine.pdf_engine import load_document
from model.elements import TextElement


def _texts(page):
    return {e.text: e for e in page.elements if isinstance(e, TextElement)}


def test_invisible_spans_are_flagged(ocr_layer_pdf):
    doc = load_document(str(ocr_layer_pdf))
    pg = doc.pages[0]
    assert not pg.is_scanned  # 文字が 10 文字以上あるのでベクター扱い (従来どおり)
    texts = _texts(pg)
    assert texts["Header Text"].invisible is True
    assert texts["Body line one"].invisible is True
    assert texts["visible text"].invisible is False
    assert all(not e.manual_cover for e in texts.values())


def test_visible_only_pdf_has_no_invisible(vector_pdf):
    doc = load_document(str(vector_pdf))
    assert all(
        not e.invisible for e in doc.pages[0].elements if isinstance(e, TextElement)
    )
```

- [ ] **Step 3: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_ocr_layer.py -v`
Expected: FAIL(`TextElement` に `invisible` が無い `AttributeError`)。

- [ ] **Step 4: モデルにフィールドを足す**

`pdf-to-svg/src/model/elements.py` の `TextElement` で `dict_revert` の直後に追加する。

```python
    # PDF の文字描画モードが「描かない」(3) / 「クリップのみ」(7) の文字。スキャン画像の上に
    # OCR 結果を透明で重ねた「検索可能 PDF」の文字層がこれで、字面は画像の画素として存在する。
    # 書き出しは未置換なら描かず、置換済みなら背景色の矩形で隠してから描く (`svg_exporter`)。
    invisible: bool = False
    # 利用者が手順 3 の「上書き」ツールで置いた要素。`invisible=True` + `dict_match` 付きで
    # 自動置換と同じ描画経路を通るが、辞書置換ではないので確認一覧と「戻す」の対象にしない。
    manual_cover: bool = False
```

- [ ] **Step 5: 抽出側で不可視 seqno を集めて span に写す**

`pdf-to-svg/src/engine/pdf_engine.py` の定数群(`_SEQNO_MAX_SCAN` の直後)に追加する。

```python
# 文字を描かない PDF 描画モード (3 = 不可視、7 = クリップへ足すだけ)。`get_text("dict")` の
# span はモードを持たないので、`get_texttrace()` の `type` を seqno 経由で写す。
_INVISIBLE_RENDER_MODES = frozenset({3, 7})


def _invisible_seqnos(traces: List[dict]) -> "set[int]":
    """すべてのエントリが不可視モードである seqno の集合。可視と混在する seqno は含めない
    (誤って本物の文字を消さない側へ倒す)。"""
    visible: "set[int]" = set()
    invisible: "set[int]" = set()
    for t in traces:
        target = invisible if t.get("type") in _INVISIBLE_RENDER_MODES else visible
        target.add(t["seqno"])
    return invisible - visible
```

`_extract_page` の texttrace 収集を次に置き換える(189〜191 行)。

```python
    traces = page.get_texttrace()
    text_seqnos = [(s["seqno"], Rect.from_xyxy(*s["bbox"])) for s in traces]
    invisible_seqnos = _invisible_seqnos(traces)
```

span ループ(224〜233 行)を次に置き換える。照合失敗(`None`)と `degraded` は可視扱いにする。

```python
                for span in line.get("spans", []):
                    bbox = Rect.from_xyxy(*span["bbox"])
                    # 照合失敗は `None`。z は従来どおり直前の seqno へ倒すが、不可視の判定は
                    # 照合できた span にだけ与える (失敗分を不可視にすると本物の文字が消える)。
                    matched = text_index.match(bbox, None)
                    seqno = matched if matched is not None else prev_seqno
                    el = _text_element(
                        span, seqno * _Z_TIER + seq,
                        invisible=(matched is not None and matched in invisible_seqnos),
                    )
                    if el is not None:
                        prev_seqno = seqno
                        if not sink.add(el):
                            break
                        seq += 1
```

`_SeqnoIndex.match` と `_best_seqno` の `default` は `int` 型注釈だが `None` を素通しする
(`best = default` を返すだけ)。型注釈を `Optional[int]` にし、戻り値も `Optional[int]` にする。

`_text_element` のシグネチャと戻り値を変える。

```python
def _text_element(span: dict, z: int, invisible: bool = False) -> Optional[TextElement]:
```

`return TextElement(...)` の引数末尾に `invisible=invisible,` を足す。

- [ ] **Step 6: テストを通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_ocr_layer.py test/test_seqno_match.py test/test_pipeline.py -v`
Expected: すべて PASS。

- [ ] **Step 7: コミット**

```bash
git add pdf-to-svg/src/model/elements.py pdf-to-svg/src/engine/pdf_engine.py pdf-to-svg/test/conftest.py pdf-to-svg/test/test_ocr_layer.py
git commit -m "feat(engine): 不可視の OCR 文字層を texttrace の描画モードから検出し TextElement.invisible に写す"
```

---

### Task 2: 採色モジュール `export/cover.py`

**Files:**
- Create: `pdf-to-svg/src/export/cover.py`
- Test: `pdf-to-svg/test/test_cover.py`(新規)
- Modify: `docs/superpowers/specs/2026-09-12-ocr-layer-cover-design.md`(代表色の 1 行)

**Interfaces:**
- Produces:
  - `MAX_COVER_IMAGE_PIXELS = 16_000_000`、`QUANT_SHIFT = 4`、`MIN_CONTRAST = 48`、
    `FALLBACK_BACKGROUND = "#ffffff"`、`FALLBACK_FOREGROUND = "#000000"`
  - `CoverColors(background: str, foreground: str, fallback: bool)`(frozen dataclass)
  - `decode_image(img_bytes: bytes, ext: str) -> Optional[PIL.Image.Image]`(RGB。上限超過・壊れた
    バイト列は `None`)
  - `sample_colors(img: Optional[PIL.Image.Image], img_rect: Rect, bbox: Rect) -> CoverColors`

代表色は量子化した箱の**中心値ではなく、箱に入った画素の平均値**にする(白い紙が `#f8f8f8` に
ならないため)。spec の 2 節の記述をこの Task で直す。

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_cover.py` を新規作成する。

```python
"""`export/cover.py` (上書き矩形の採色) の単体テスト。

画像は Pillow で小さく合成する。最頻色 = 背景、2 番目 = 文字色、コントラスト不足と
採取不能のときの黒/白への倒し、画素上限、bbox のクランプを確認する。
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from export import cover
from model.elements import Rect


def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _image(w: int, h: int, color, marks=()) -> Image.Image:
    im = Image.new("RGB", (w, h), color)
    for (x, y), c in marks:
        im.putpixel((x, y), c)
    return im


def test_two_colors_background_is_mode_and_text_is_runner_up():
    marks = [((x, 5), (0, 0, 0)) for x in range(3, 8)]  # 5 px の黒
    im = _image(20, 10, (200, 220, 240), marks)
    c = cover.sample_colors(im, Rect(0, 0, 20, 10), Rect(0, 0, 20, 10))
    assert c.background == "#c8dcf0"
    assert c.foreground == "#000000"
    assert c.fallback is False


def test_mean_of_box_not_box_center():
    """白い紙 (255) は箱の中心値 248 ではなく平均値 255 になる。"""
    im = _image(8, 8, (255, 255, 255))
    c = cover.sample_colors(im, Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    assert c.background == "#ffffff"


def test_single_color_picks_text_by_luma():
    light = cover.sample_colors(_image(8, 8, (240, 240, 240)), Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    dark = cover.sample_colors(_image(8, 8, (20, 30, 40)), Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    assert light.foreground == "#000000"
    assert dark.foreground == "#ffffff"
    assert light.fallback is False and dark.fallback is False


def test_low_contrast_runner_up_falls_back_to_black_or_white():
    marks = [((x, 2), (215, 215, 215)) for x in range(0, 4)]  # 背景 200 との差 15 < MIN_CONTRAST
    im = _image(8, 8, (200, 200, 200), marks)
    c = cover.sample_colors(im, Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    assert c.background == "#c8c8c8"
    assert c.foreground == "#000000"


def test_bbox_maps_through_img_rect_scale():
    """画像 40×20px を 20×10pt に貼った場合、pt の bbox は 2 倍して画素へ写す。"""
    marks = [((x, y), (0, 0, 0)) for x in range(20, 40) for y in range(0, 20)]  # 右半分が黒
    im = _image(40, 20, (255, 255, 255), marks)
    left = cover.sample_colors(im, Rect(0, 0, 20, 10), Rect(0, 0, 10, 10))
    right = cover.sample_colors(im, Rect(0, 0, 20, 10), Rect(10, 0, 10, 10))
    assert left.background == "#ffffff"
    assert right.background == "#000000"


def test_bbox_outside_image_is_fallback():
    im = _image(8, 8, (10, 10, 10))
    c = cover.sample_colors(im, Rect(0, 0, 8, 8), Rect(50, 50, 4, 4))
    assert c == cover.CoverColors("#ffffff", "#000000", True)


def test_none_image_is_fallback():
    c = cover.sample_colors(None, Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    assert c == cover.CoverColors("#ffffff", "#000000", True)


def test_decode_image_returns_rgb():
    im = cover.decode_image(_png(_image(4, 4, (1, 2, 3))), "png")
    assert im is not None and im.mode == "RGB" and im.size == (4, 4)


def test_decode_image_rejects_broken_and_oversized(monkeypatch):
    assert cover.decode_image(b"\x89PNG broken", "png") is None
    monkeypatch.setattr(cover, "MAX_COVER_IMAGE_PIXELS", 8)
    assert cover.decode_image(_png(_image(4, 4, (0, 0, 0))), "png") is None


def test_deterministic_tie_break_prefers_smaller_color():
    """同数の 2 色は量子化値の小さい方が背景 (走査順に依存しない)。"""
    marks = [((x, y), (0, 0, 0)) for x in range(0, 4) for y in range(0, 8)]  # 左半分が黒
    im = _image(8, 8, (255, 255, 255), marks)
    c = cover.sample_colors(im, Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    assert c.background == "#000000"
    assert c.foreground == "#ffffff"
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_cover.py -v`
Expected: FAIL(`ModuleNotFoundError: export.cover`)。

- [ ] **Step 3: `cover.py` を書く**

`pdf-to-svg/src/export/cover.py` を新規作成する。

```python
"""上書き矩形の採色。画像の画素から「背景色」と「文字色」を決める純粋関数。

スキャン画像の上に OCR 文字を透明で重ねた PDF では、辞書置換しても元の字面が画像の画素として
残る。置換箇所を隠す矩形の色を画像から採り、白抜き文字の帯でも読めるよう文字色も同じ領域から
採る。``fitz`` には依存しない (AGPL 依存は ``engine/pdf_engine.py`` に隔離する)。

採り方: bbox 内の画素を各チャンネル 16 階調 (``QUANT_SHIFT``) に量子化し、最も多い箱を背景・
2 番目を文字色にする。代表色は箱に入った画素の平均 (箱の中心値だと白い紙が ``#f8f8f8`` になる)。
2 番目が無い、または背景との差が ``MIN_CONTRAST`` 未満なら、背景の輝度で黒か白へ倒す。
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image, ImageChops, ImageStat

from model.elements import Rect

# 画像 1 枚あたりのデコード上限画素数。`grayscale.MAX_GRAY_IMAGE_PIXELS` と同値 (片方を変えたら両方)。
MAX_COVER_IMAGE_PIXELS = 16_000_000
# 量子化の右シフト量。4 = 各チャンネル 16 階調 (JPEG ノイズで最頻色が割れるのを防ぐ)。
QUANT_SHIFT = 4
# 文字色と背景色のチャンネル差の最大がこれ未満なら、文字色を黒/白へ倒す。
MIN_CONTRAST = 48
FALLBACK_BACKGROUND = "#ffffff"
FALLBACK_FOREGROUND = "#000000"

_QUANT_TABLE = [v >> QUANT_SHIFT for v in range(256)] * 3


@dataclass(frozen=True)
class CoverColors:
    """採色結果。``fallback`` は画像から採れず既定の白/黒へ倒したことを示す。"""

    background: str
    foreground: str
    fallback: bool


_FALLBACK = CoverColors(FALLBACK_BACKGROUND, FALLBACK_FOREGROUND, True)


def decode_image(img_bytes: bytes, ext: str) -> Optional[Image.Image]:
    """画像バイト列を RGB の Pillow 画像へ。上限超過・壊れたバイト列は ``None``。

    画像は PDF 由来 = 攻撃者が用意できる入力なので、デコードの前に画素数を
    ``MAX_COVER_IMAGE_PIXELS`` で切る (``Image.open`` はヘッダしか読まない)。例外は外へ出さない
    (1 枚の画像で書き出し全体を止めない)。
    """
    del ext  # 形式は Pillow がヘッダから判定する
    try:
        with Image.open(io.BytesIO(img_bytes)) as im:
            if im.width * im.height > MAX_COVER_IMAGE_PIXELS:
                return None
            return im.convert("RGB")
    except Exception:  # noqa: BLE001 - 壊れた画像は採色を諦めるだけ
        return None


def _luma(r: int, g: int, b: int) -> int:
    # `grayscale._luma` と同じ固定小数点式 (ITU-R 601-2)。
    return (r * 19595 + g * 38470 + b * 7471 + 0x8000) >> 16


def _hex(rgb: Tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _pixel_box(img_rect: Rect, bbox: Rect, width: int, height: int) -> Optional[Tuple[int, int, int, int]]:
    """pt の bbox を画像画素の (x0, y0, x1, y1) へ線形写像し、画像の範囲でクランプする。空なら None。"""
    if img_rect.w <= 0 or img_rect.h <= 0:
        return None
    sx = width / img_rect.w
    sy = height / img_rect.h
    x0 = int(math.floor((bbox.x - img_rect.x) * sx))
    y0 = int(math.floor((bbox.y - img_rect.y) * sy))
    x1 = int(math.ceil((bbox.x1 - img_rect.x) * sx))
    y1 = int(math.ceil((bbox.y1 - img_rect.y) * sy))
    x0, x1 = max(0, min(x0, width)), max(0, min(x1, width))
    y0, y1 = max(0, min(y0, height)), max(0, min(y1, height))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _box_mean(region: Image.Image, quantized: Image.Image, box: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """量子化値が ``box`` に一致する画素の平均色 (整数へ丸め)。マスクは Pillow の C 実装で作る。"""
    solid = Image.new("RGB", quantized.size, box)
    bands = [b.point(lambda v: 255 if v == 0 else 0) for b in ImageChops.difference(quantized, solid).split()]
    mask = ImageChops.multiply(ImageChops.multiply(bands[0], bands[1]), bands[2])
    mean = ImageStat.Stat(region, mask).mean
    return tuple(int(round(m)) for m in mean)  # type: ignore[return-value]


def sample_colors(img: Optional[Image.Image], img_rect: Rect, bbox: Rect) -> CoverColors:
    """``img`` (``img_rect`` へ貼られた画像) の ``bbox`` 内から背景色と文字色を採る。

    採れない (画像無し・bbox が画像の外) ときは白/黒の ``fallback=True``。文字色が決まらない
    ときの黒/白への倒しは背景が採れているので ``fallback=False``。
    """
    if img is None:
        return _FALLBACK
    px = _pixel_box(img_rect, bbox, img.width, img.height)
    if px is None:
        return _FALLBACK
    region = img.crop(px)
    quantized = region.point(_QUANT_TABLE)
    colors: List[Tuple[int, Tuple[int, int, int]]] = quantized.getcolors(1 << (3 * (8 - QUANT_SHIFT))) or []
    if not colors:
        return _FALLBACK
    # 同数は量子化値の小さい方を先にする (走査順に依存せず決定的)。
    ranked = sorted(colors, key=lambda kv: (-kv[0], kv[1]))
    bg = _box_mean(region, quantized, ranked[0][1])
    fg: Optional[Tuple[int, int, int]] = None
    if len(ranked) > 1:
        fg = _box_mean(region, quantized, ranked[1][1])
        if max(abs(a - b) for a, b in zip(bg, fg)) < MIN_CONTRAST:
            fg = None
    if fg is None:
        fg = (0, 0, 0) if _luma(*bg) >= 128 else (255, 255, 255)
    return CoverColors(_hex(bg), _hex(fg), False)
```

- [ ] **Step 4: テストを通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_cover.py -v`
Expected: すべて PASS。`test_two_colors_...` の背景が `#c8dcf0` にならない場合は
`_box_mean` のマスクを疑う(黒画素が平均に混ざると値が下がる)。

- [ ] **Step 5: spec の代表色の記述を直す**

`docs/superpowers/specs/2026-09-12-ocr-layer-cover-design.md` の 2 節にある
「代表色は量子化した箱の中心値を使う(決定的で、JPEG ノイズに引かれない)。」を
「代表色は箱に入った画素の平均値(整数へ丸め)を使う(箱の中心値だと白い紙が `#f8f8f8` になる)。」に、
5 節の「白地では `#f8f8f8` 相当(量子化後の白の箱の中心値)になる」を「白地では `#ffffff` になる」に
置き換える。

- [ ] **Step 6: コミット**

```bash
git add pdf-to-svg/src/export/cover.py pdf-to-svg/test/test_cover.py docs/superpowers/specs/2026-09-12-ocr-layer-cover-design.md
git commit -m "feat(export): 上書き矩形の背景色と文字色を画像の画素から採る cover.py を追加する"
```

---

### Task 3: 書き出しの 3 分岐と矩形合成(`svg_exporter.py`)

**Files:**
- Modify: `pdf-to-svg/src/export/svg_exporter.py:104-110`(シグネチャ)、`:196-215`(要素ループ)、`:223-230`(`_with_data_el`)、`:246-248`(`_element_to_svg`)、`:347-417`(`_text_to_svg`)
- Test: `pdf-to-svg/test/test_ocr_layer.py`(追記)

**Interfaces:**
- Consumes: `cover.decode_image` / `cover.sample_colors` / `cover.CoverColors`(Task 2)、`TextElement.invisible`(Task 1)
- Produces:
  - `ExportReport`(dataclass、`cover_fallback: int = 0`)を `svg_exporter` に定義
  - `page_to_svg(page, *, annotate=False, grayscale=False, clip=None, report: Optional[ExportReport] = None) -> str`
  - `_text_to_svg(el, color_fn=sanitize_color, *, fill: Optional[str] = None, transparent: bool = False, edited: Optional[bool] = None) -> str`
  - 出力形: 不可視・未置換は `annotate=True` のとき `<text data-el=".." ... fill-opacity="0">`、
    不可視・置換済みは `<g data-el=".."><rect .../><text ...>..</text></g>`(`text` が空なら
    `<g data-el=".."><rect .../></g>`)

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_ocr_layer.py` に追記する。

```python
import re

from dictionary import apply as dict_apply
from dictionary.store import DictionaryStore
from export.svg_exporter import ExportReport, page_to_svg
from export import cover


def _line_with(svg: str, needle: str) -> str:
    return next(ln for ln in svg.splitlines() if needle in ln)


def _replace(pg, tmp_path, source, target):
    store = DictionaryStore(tmp_path / "d.json")
    store.add(source, target)
    n = dict_apply.auto_apply(pg, store)
    store.close()
    assert n == 1


def test_unreplaced_invisible_text_is_omitted_from_export(ocr_layer_pdf):
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    svg = page_to_svg(pg)
    assert "Header Text" not in svg and "Body line one" not in svg
    assert "visible text" in svg  # 可視文字は従来どおり


def test_unreplaced_invisible_text_is_transparent_in_annotate(ocr_layer_pdf):
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    svg = page_to_svg(pg, annotate=True)
    line = _line_with(svg, "Header Text")
    assert line.startswith("<text data-el=")
    assert 'fill-opacity="0"' in line
    assert 'fill="' in line  # fill を残さないと当たり判定から外れる (クリック取り込みが効かなくなる)
    assert 'fill-opacity' not in _line_with(svg, "visible text")


def test_replaced_invisible_text_is_covered_with_sampled_colors(ocr_layer_pdf, tmp_path):
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    _replace(pg, tmp_path, "Header Text", "見出し")
    el = _texts(pg)["見出し"]
    svg = page_to_svg(pg)
    line = _line_with(svg, "見出し")
    assert line.startswith("<g><rect ")
    assert line.endswith("</text></g>")
    assert 'fill="#c8dcf0"' in line.split("<text")[0]  # 帯色 (200, 220, 240)
    assert 'fill="#000000"' in line.split("<text")[1]  # 単色領域 → 輝度で黒
    assert 'dominant-baseline="central"' in line  # 置換枝の据え方を流用


def test_replaced_invisible_text_on_white_uses_white(ocr_layer_pdf, tmp_path):
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    _replace(pg, tmp_path, "Body line one", "本文")
    line = _line_with(page_to_svg(pg), "本文")
    assert 'fill="#ffffff"' in line.split("<text")[0]


def test_replaced_invisible_text_annotate_puts_data_el_on_group(ocr_layer_pdf, tmp_path):
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    _replace(pg, tmp_path, "Header Text", "見出し")
    el = _texts(pg)["見出し"]
    line = _line_with(page_to_svg(pg, annotate=True), "見出し")
    assert line.startswith(f'<g data-el="{el.id}"><rect ')
    assert line.count("data-el=") == 1


def test_grayscale_converts_cover_colors(ocr_layer_pdf, tmp_path):
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    _replace(pg, tmp_path, "Header Text", "見出し")
    line = _line_with(page_to_svg(pg, grayscale=True), "見出し")
    assert not re.search(r'="#(?!([0-9a-f]{2})\1\1")[0-9a-f]{6}"', line)  # 有彩色が残らない


def test_cover_fallback_is_counted(ocr_layer_pdf, tmp_path, monkeypatch):
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    _replace(pg, tmp_path, "Header Text", "見出し")
    monkeypatch.setattr(cover, "MAX_COVER_IMAGE_PIXELS", 10)  # 画像をデコードできない状況
    report = ExportReport()
    svg = page_to_svg(pg, report=report)
    line = _line_with(svg, "見出し")
    assert 'fill="#ffffff"' in line.split("<text")[0]
    assert report.cover_fallback == 1


def test_report_is_optional_and_zero_without_invisible(vector_pdf):
    pg = load_document(str(vector_pdf)).pages[0]
    report = ExportReport()
    assert page_to_svg(pg, report=report) == page_to_svg(pg)
    assert report.cover_fallback == 0


def test_font_embedding_skips_omitted_invisible_text(ocr_layer_pdf, tmp_path):
    """書き出しで出さない不可視文字は、埋め込みフォントの収集にも入らない。"""
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    for e in pg.elements:
        if isinstance(e, TextElement) and e.invisible:
            e.font_family = "BIZ UDPGothic"
    assert "<style>" not in page_to_svg(pg)
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_ocr_layer.py -v`
Expected: `ExportReport` の ImportError で収集時に失敗。

- [ ] **Step 3: `ExportReport` とシグネチャ**

`pdf-to-svg/src/export/svg_exporter.py` の import に `from dataclasses import dataclass, field` と
`from typing import Callable, Dict, List, Optional, Tuple`(`Dict` 追加)、
`from export import cover`、`from model.elements import (... ImageElement ...)` はそのまま。
`CLIP_MARGIN` の直後に追加する。

```python
@dataclass
class ExportReport:
    """書き出し 1 回で起きた degrade の件数。呼び手が渡したときだけ exporter が加算する
    (exporter 自体は状態を持たない)。``cover_fallback`` は上書き矩形の色を画像から採れず
    白/黒へ倒した箇所の数。"""

    cover_fallback: int = 0
```

`page_to_svg` のシグネチャに `report: Optional[ExportReport] = None,` を足す(`clip` の後)。
docstring に「`report` を渡すと degrade 件数を書き込む」を 1 行足す。

- [ ] **Step 4: `_with_data_el` を `<g>` に対応させる**

```python
def _with_data_el(svg: str, el_id: int) -> str:
    """要素の開きタグに data-el 属性を差し込む。"""
    # 先頭は必ず "<tagname"。属性を持つタグは最初の空白、`<g>` のように属性の無い開きタグは
    # 最初の ">" の位置へ差す (空白を探すだけだと内側の <rect> に付いてしまう)。
    sp = svg.find(" ")
    gt = svg.find(">")
    pos = sp if 0 <= sp < gt else gt
    if pos < 0:
        return svg
    return f"{svg[:pos]} {_attr('data-el', el_id)}{svg[pos:]}"
```

- [ ] **Step 5: `_text_to_svg` に `fill` / `transparent` / `edited` を足す**

シグネチャを次にする。

```python
def _text_to_svg(
    el: TextElement,
    color_fn: ColorFn = sanitize_color,
    *,
    fill: Optional[str] = None,
    transparent: bool = False,
    edited: Optional[bool] = None,
) -> str:
```

本文の `if el.text == el.original_text:` を
`if not (edited if edited is not None else el.text != el.original_text):` に置き換える
(手動の上書きは `text == original_text` だが置換枝で描く)。

末尾の組み立てで `_attr("fill", color_fn(el.color))` を
`_attr("fill", color_fn(fill if fill is not None else el.color))` にし、`weight` の直前に
`opacity = ' fill-opacity="0"' if transparent else ""` を定義して `f"{weight}{style}{stretch}"` を
`f"{opacity}{weight}{style}{stretch}"` にする。`fill-opacity="0"` は値が固定なので `_attr` を
通さなくても `test_export_escaping` の走査に掛からないが、揃えて `" " + _attr("fill-opacity", 0)`
で書く。

- [ ] **Step 6: 矩形合成と採色元の解決**

`_element_to_svg` の直前に追加する。

```python
def _cover_svg(el: TextElement, colors: cover.CoverColors, color_fn: ColorFn) -> str:
    """不可視・置換済みの文字: 背景色の矩形で元の字面を隠し、その上に置換語を描く。
    `<g>` で包むのは `_with_data_el` が 1 要素 1 開きタグを前提にするため。"""
    rect = (
        "<rect "
        + _attr("x", _fmt(el.bbox.x))
        + " "
        + _attr("y", _fmt(el.bbox.y))
        + " "
        + _attr("width", _fmt(el.bbox.w))
        + " "
        + _attr("height", _fmt(el.bbox.h))
        + " "
        + _attr("fill", color_fn(colors.background))
        + "/>"
    )
    text = _text_to_svg(el, color_fn, fill=colors.foreground, edited=True) if el.text else ""
    return "<g>" + rect + text + "</g>"


def _cover_sampler(page: Page) -> Callable[[TextElement], cover.CoverColors]:
    """要素の bbox の下にある画像 (z 最大の `ImageElement` → スキャン背景の順) から採色する。
    画像のデコードは 1 回の書き出しの中で画像ごと 1 度 (要素 id をキーにした辞書)。"""
    images = sorted(
        (e for e in page.live_elements() if isinstance(e, ImageElement)), key=lambda e: -e.z
    )
    decoded: Dict[int, Optional[object]] = {}  # 値は Pillow の Image (型は cover.py に閉じる)

    def image_for(key: int, data: bytes, ext: str):
        if key not in decoded:
            decoded[key] = cover.decode_image(data, ext)
        return decoded[key]

    def sample(el: TextElement) -> cover.CoverColors:
        cx = el.bbox.x + el.bbox.w / 2
        cy = el.bbox.y + el.bbox.h / 2
        for img in images:
            r = img.rect
            if r.x <= cx <= r.x1 and r.y <= cy <= r.y1:
                return cover.sample_colors(image_for(img.id, img.img_bytes, img.ext), r, el.bbox)
        bg = page.background
        if bg is not None:
            return cover.sample_colors(image_for(-1, bg.png_bytes, "png"), bg.rect, el.bbox)
        return cover.sample_colors(None, el.bbox, el.bbox)

    return sample
```

`page_to_svg` の要素ループを次に置き換える(`text_els` の宣言から `css` の直前まで)。

```python
    text_els: List[TextElement] = []
    sampler = _cover_sampler(page)
    for el in page.live_elements():
        if not _intersects_export(el.bbox, select):
            continue
        if isinstance(el, TextElement) and el.invisible:
            if el.dict_match is None:
                # 未置換の OCR 文字: 字面は画像にあるので書き出しでは描かない。編集画面では
                # 透明で描き、クリック取り込みと確認一覧のマーカーの当たり判定を残す。
                if not annotate:
                    continue
                svg = _text_to_svg(el, color_fn, transparent=True)
                emits_text = True
            else:
                colors = sampler(el)
                if colors.fallback and report is not None:
                    report.cover_fallback += 1
                svg = _cover_svg(el, colors, color_fn)
                emits_text = bool(el.text)
        else:
            svg = _element_to_svg(el, color_fn, image_fn)
            emits_text = isinstance(el, TextElement)
        if svg:
            if annotate:
                svg = _with_data_el(svg, el.id)
            lines.append(svg)
            if emits_text:  # 埋め込みフォントの収集は実際に <text> を出した要素だけ
                text_els.append(el)
```

- [ ] **Step 7: テストを通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_ocr_layer.py test/test_pipeline.py test/test_export_clip.py test/test_export_escaping.py test/test_export_punctuation.py test/test_image_clip.py -v`
Expected: すべて PASS。`test_export_escaping` が `_attr` 未経由の属性を検出したら、該当箇所を
`_attr` に置き換える。

- [ ] **Step 8: コミット**

```bash
git add pdf-to-svg/src/export/svg_exporter.py pdf-to-svg/test/test_ocr_layer.py
git commit -m "feat(export): 不可視 OCR 文字を未置換なら書き出しから外し、置換済みは採色した矩形で隠して描く"
```

---

### Task 4: RPC の通知経路(`ocrPages` / `coverFallback`)

**Files:**
- Modify: `pdf-to-svg/src/web/rpc_methods.py:99-140`(`rpc_state`)、`:180-189`(`rpc_pageSvg`)、`:476-494`(`rpc_exportSvg`)
- Test: `pdf-to-svg/test/test_web_rpc.py`(追記)

**Interfaces:**
- Consumes: `ExportReport`、`page_to_svg(..., report=)`(Task 3)
- Produces: `state.ocrPages: int`、`pageSvg.coverFallback: int`、`exportSvg.coverFallback: int`

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_web_rpc.py` の `test_state_counts_scanned_pages_that_lost_their_background`
の直後に追記する。

```python
def test_state_counts_pages_with_invisible_ocr_text(session):
    """不可視の OCR 文字を持つページ数を `ocrPages` で返す。手動の上書きは数えない。"""
    doc = session.docs[0]
    ocr = Page(index=1, width_pt=200.0, height_pt=300.0)
    ocr.elements = [TextElement(bbox=Rect(10, 10, 40, 12), text="OCR", invisible=True)]
    manual = Page(index=2, width_pt=200.0, height_pt=300.0)
    manual.elements = [
        TextElement(bbox=Rect(10, 10, 40, 12), text="手動", invisible=True, manual_cover=True,
                    dict_match=DictMatch(source="", target="手動"))
    ]
    doc.pages.extend([ocr, manual])
    st = rpc_methods.dispatch(session, "state", {})
    assert st["ocrPages"] == 1


def test_page_svg_and_export_svg_report_cover_fallback(session):
    """下に画像が無い不可視・置換済み文字は白で隠し、その件数を応答に載せる。"""
    pg = session.docs[0].pages[0]
    pg.elements.append(
        TextElement(bbox=Rect(10, 60, 40, 12), text="置換後", original_text="before",
                    invisible=True, dict_match=DictMatch(source="before", target="置換後"))
    )
    shown = rpc_methods.dispatch(session, "pageSvg", {"fileIndex": 0, "pageInFile": 0})
    assert shown["coverFallback"] == 1
    assert "<g data-el=" in shown["svg"]
    out = rpc_methods.dispatch(session, "exportSvg", {"fileIndex": 0, "pageInFile": 0})
    assert out["coverFallback"] == 1
    assert "<g><rect " in out["svg"]


def test_page_svg_reports_zero_without_invisible(session):
    shown = rpc_methods.dispatch(session, "pageSvg", {"fileIndex": 0, "pageInFile": 0})
    assert shown["coverFallback"] == 0
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_web_rpc.py -k "ocr or cover_fallback or without_invisible" -v`
Expected: FAIL(`KeyError: 'ocrPages'` / `'coverFallback'`)。

- [ ] **Step 3: 実装**

`pdf-to-svg/src/web/rpc_methods.py` の import を
`from export.svg_exporter import ExportReport, page_to_svg` にする。

`rpc_state` の戻り値 dict の `noBackground` の直後に追加する。

```python
        # 不可視の OCR 文字層 (画像 + 透明な文字) を持つページ数。置換箇所が画像の上に矩形で
        # 上書きされることを利用者へ伝えるための通知経路 (`truncated` と同じ)。手動の上書き
        # (`manual_cover`) も `invisible` だが利用者が置いたものなので数えない。
        "ocrPages": sum(
            1
            for d in s.docs
            for pg in d.pages
            if any(
                isinstance(e, TextElement) and e.invisible and not e.manual_cover
                for e in pg.elements
            )
        ),
```

`rpc_pageSvg` を次にする。

```python
def rpc_pageSvg(s: WebSession, args: dict) -> dict:
    pg = s.page(args["fileIndex"], args["pageInFile"])
    report = ExportReport()
    svg = page_to_svg(
        pg, annotate=True, grayscale=bool(args.get("grayscale")), clip=_parse_clip(args, pg),
        report=report,
    )
    return {
        "svg": svg,
        "width": pg.width_pt,
        "height": pg.height_pt,
        # 上書き矩形の色を画像から採れず白へ倒した件数 (黙って白抜きにしない)。
        "coverFallback": report.cover_fallback,
    }
```

`rpc_exportSvg` の末尾を次にする。

```python
    report = ExportReport()
    svg = page_to_svg(pg, grayscale=grayscale, clip=clip, report=report)
    return {"svg": svg, "name": name + ".svg", "coverFallback": report.cover_fallback}
```

- [ ] **Step 4: テストを通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_web_rpc.py test/test_shell_rpc.py test/test_zip_entries.py -v`
Expected: すべて PASS。

- [ ] **Step 5: コミット**

```bash
git add pdf-to-svg/src/web/rpc_methods.py pdf-to-svg/test/test_web_rpc.py
git commit -m "feat(web): OCR 文字層のページ数と上書き矩形の採色失敗件数を RPC で返す"
```

---

### Task 5: 手動の上書きの RPC とコマンド

**Files:**
- Modify: `pdf-to-svg/src/web/commands.py`(`UpdateCoverCommand` 追加)
- Modify: `pdf-to-svg/src/web/rpc_methods.py`(`_parse_clip` の一般化、`rpc_addCover` / `rpc_coverList` / `rpc_updateCover`、`rpc_planPage` の除外、`rpc_removedList` のラベル、`HANDLERS`)
- Test: `pdf-to-svg/test/test_web_rpc.py`(追記)

**Interfaces:**
- Consumes: `TextElement.invisible` / `manual_cover`(Task 1)、`AddElementCommand`(既存)
- Produces:
  - RPC `addCover {fileIndex, pageInFile, rect: {x,y,w,h}, text: str} -> {"elId": int}`
  - RPC `coverList {fileIndex, pageInFile} -> {"covers": [{"elId", "rect": {x,y,w,h}, "text"}]}`
  - RPC `updateCover {fileIndex, pageInFile, elId, rect?: {x,y,w,h}, text?: str} -> {}`
  - `commands.UpdateCoverCommand(el: TextElement, rect: Optional[Rect], text: Optional[str])`
  - `rpc_methods.MAX_COVER_TEXT_CHARS = 200`、`rpc_methods.cover_font_size(h: float) -> float`
    (`min(200.0, max(4.0, h * 0.7))`)
  - `rpc_methods._parse_rect_arg(args: dict, key: str, pg: Page) -> Optional[Rect]`
    (`_parse_clip(args, pg)` は `_parse_rect_arg(args, "clip", pg)` を呼ぶだけになる)

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_web_rpc.py` に追記する。

```python
def _cover_args(**extra):
    base = {"fileIndex": 0, "pageInFile": 0}
    base.update(extra)
    return base


def test_add_cover_creates_invisible_replaced_text(session):
    res = rpc_methods.dispatch(
        session, "addCover", _cover_args(rect={"x": 10, "y": 100, "w": 80, "h": 20}, text="置換語")
    )
    pg = session.docs[0].pages[0]
    el = next(e for e in pg.elements if e.id == res["elId"])
    assert isinstance(el, TextElement)
    assert el.invisible and el.manual_cover and not el.deleted
    assert el.text == "置換語" and el.dict_match == DictMatch(source="", target="置換語")
    assert el.bbox == Rect(10, 100, 80, 20)
    assert (el.origin_x, el.origin_y) == (10, 120)
    assert el.font_size == pytest.approx(14.0)  # 高さ 20 × 0.7
    assert el.z == max(e.z for e in pg.elements)
    assert el.font_family == "BIZ UDPGothic"  # 和文 → 同梱ゴシック
    shown = rpc_methods.dispatch(session, "pageSvg", _cover_args())
    assert f'<g data-el="{el.id}"><rect ' in shown["svg"]
    assert "置換語" in shown["svg"]


def test_add_cover_with_empty_text_draws_rect_only(session):
    res = rpc_methods.dispatch(
        session, "addCover", _cover_args(rect={"x": 10, "y": 100, "w": 80, "h": 20}, text="")
    )
    shown = rpc_methods.dispatch(session, "pageSvg", _cover_args())
    line = next(ln for ln in shown["svg"].splitlines() if f'data-el="{res["elId"]}"' in ln)
    assert "<text" not in line and line.endswith("/></g>")


def test_add_cover_sanitizes_and_caps_text(session):
    res = rpc_methods.dispatch(
        session, "addCover",
        _cover_args(rect={"x": 10, "y": 100, "w": 80, "h": 20}, text="a\x00b" + "x" * 300),
    )
    el = next(e for e in session.docs[0].pages[0].elements if e.id == res["elId"])
    assert "\x00" not in el.text and len(el.text) == rpc_methods.MAX_COVER_TEXT_CHARS


def test_add_cover_rejects_rect_outside_page(session):
    with pytest.raises(ValueError):
        rpc_methods.dispatch(
            session, "addCover", _cover_args(rect={"x": 150, "y": 0, "w": 100, "h": 10}, text="x")
        )


def test_add_cover_is_undoable(session):
    res = rpc_methods.dispatch(
        session, "addCover", _cover_args(rect={"x": 10, "y": 100, "w": 80, "h": 20}, text="x")
    )
    rpc_methods.dispatch(session, "undo", {})
    el = next(e for e in session.docs[0].pages[0].elements if e.id == res["elId"])
    assert el.deleted
    assert rpc_methods.dispatch(session, "coverList", _cover_args())["covers"] == []


def test_cover_list_returns_live_manual_covers_only(session):
    a = rpc_methods.dispatch(
        session, "addCover", _cover_args(rect={"x": 10, "y": 100, "w": 80, "h": 20}, text="A")
    )["elId"]
    b = rpc_methods.dispatch(
        session, "addCover", _cover_args(rect={"x": 10, "y": 130, "w": 80, "h": 20}, text="B")
    )["elId"]
    rpc_methods.dispatch(session, "applyDelete", _cover_args(elIds=[b]))
    covers = rpc_methods.dispatch(session, "coverList", _cover_args())["covers"]
    assert covers == [{"elId": a, "rect": {"x": 10.0, "y": 100.0, "w": 80.0, "h": 20.0}, "text": "A"}]


def test_update_cover_rect_and_text_are_undoable(session):
    el_id = rpc_methods.dispatch(
        session, "addCover", _cover_args(rect={"x": 10, "y": 100, "w": 80, "h": 20}, text="A")
    )["elId"]
    el = next(e for e in session.docs[0].pages[0].elements if e.id == el_id)
    rpc_methods.dispatch(
        session, "updateCover", _cover_args(elId=el_id, rect={"x": 20, "y": 110, "w": 60, "h": 30})
    )
    assert el.bbox == Rect(20, 110, 60, 30)
    assert (el.origin_x, el.origin_y) == (20, 140)
    assert el.font_size == pytest.approx(21.0)
    assert el.text == "A"
    rpc_methods.dispatch(session, "updateCover", _cover_args(elId=el_id, text="B"))
    assert el.text == "B" and el.original_text == "B"
    assert el.dict_match == DictMatch(source="", target="B")
    assert el.bbox == Rect(20, 110, 60, 30)
    rpc_methods.dispatch(session, "undo", {})
    assert el.text == "A" and el.dict_match.target == "A"
    rpc_methods.dispatch(session, "undo", {})
    assert el.bbox == Rect(10, 100, 80, 20) and el.font_size == pytest.approx(14.0)
    assert (el.origin_x, el.origin_y) == (10, 120)


def test_update_cover_rejects_non_cover_and_empty_update(session):
    pg = session.docs[0].pages[0]
    body = next(e for e in pg.elements if isinstance(e, TextElement) and e.text == "A-1042")
    with pytest.raises(ValueError):
        rpc_methods.dispatch(session, "updateCover", _cover_args(elId=body.id, text="x"))
    el_id = rpc_methods.dispatch(
        session, "addCover", _cover_args(rect={"x": 10, "y": 100, "w": 80, "h": 20}, text="A")
    )["elId"]
    with pytest.raises(ValueError):
        rpc_methods.dispatch(session, "updateCover", _cover_args(elId=el_id))
    with pytest.raises(ValueError):
        rpc_methods.dispatch(
            session, "updateCover", _cover_args(elId=el_id, rect={"x": -1, "y": 0, "w": 10, "h": 10})
        )


def test_manual_cover_is_not_a_dictionary_change(session):
    el_id = rpc_methods.dispatch(
        session, "addCover", _cover_args(rect={"x": 10, "y": 100, "w": 80, "h": 20}, text="A")
    )["elId"]
    changes = rpc_methods.dispatch(session, "planPage", _cover_args())["changes"]
    assert all(c["elId"] != el_id for c in changes)
    rpc_methods.dispatch(session, "applyDelete", _cover_args(elIds=[el_id]))
    removed = rpc_methods.dispatch(session, "removedList", _cover_args())["removed"]
    assert {"elId": el_id, "kind": "text", "label": "上書き「A」"} in removed
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_web_rpc.py -k "cover" -v`
Expected: FAIL(`KeyError: 'addCover'`)。

- [ ] **Step 3: `UpdateCoverCommand`**

`pdf-to-svg/src/web/commands.py` の import を確認し(`Optional`、`Rect`、`DictMatch`、`TextElement`)、
末尾に追加する。

```python
class UpdateCoverCommand:
    """手動の上書き (`TextElement.manual_cover`) の位置・大きさ・置換語を変える。

    ``rect`` を渡すと bbox とベースライン原点 (左下) を据え直し、文字サイズを新しい高さから
    計算し直す。``text`` を渡すと置換語と `dict_match.target` を変える。矩形色・文字色は
    書き出し時に新しい bbox から採り直されるので、ここでは持たない。
    """

    def __init__(self, el: TextElement, rect: Optional[Rect], text: Optional[str], font_size: Optional[float]):
        self.label = "上書きの変更"
        self.el = el
        self.new_bbox = rect
        self.new_font_size = font_size
        self.new_text = text
        self.old_bbox = el.bbox
        self.old_origin = (el.origin_x, el.origin_y)
        self.old_font_size = el.font_size
        self.old_text = el.text
        self.old_original_text = el.original_text
        self.old_match = el.dict_match

    def redo(self) -> None:
        if self.new_bbox is not None:
            self.el.bbox = self.new_bbox
            self.el.origin_x = self.new_bbox.x
            self.el.origin_y = self.new_bbox.y1
            if self.new_font_size is not None:
                self.el.font_size = self.new_font_size
        if self.new_text is not None:
            self.el.text = self.new_text
            self.el.original_text = self.new_text
            self.el.dict_match = DictMatch(source="", target=self.new_text)

    def undo(self) -> None:
        self.el.bbox = self.old_bbox
        self.el.origin_x, self.el.origin_y = self.old_origin
        self.el.font_size = self.old_font_size
        self.el.text = self.old_text
        self.el.original_text = self.old_original_text
        self.el.dict_match = self.old_match
```

- [ ] **Step 4: RPC 3 本と既存 2 本の変更**

`pdf-to-svg/src/web/rpc_methods.py`:

import に `sanitize_text` を足し(`from model.elements import DictMatch, Rect, RectElement, TextElement, sanitize_color, sanitize_text`)、
`from web.commands import (...)` に `UpdateCoverCommand` を足す。

`_parse_clip` を一般化する(既存の本文をそのまま `_parse_rect_arg` に移し、`args.get("clip")` を
`args.get(key)` に、エラーメッセージの `clip` を `key` に置き換える)。

```python
def _parse_rect_arg(args: dict, key: str, pg: Page) -> Optional[Rect]:
    """``args[key]`` の ``{x, y, w, h}`` をページ座標の矩形にする。無ければ None。
    数値でない・非有限・ページ外・大きさが正でない値は ``ValueError``。"""
    ...


def _parse_clip(args: dict, pg: Page) -> Optional[Rect]:
    """``clip`` 引数をページ座標の矩形にする (`_parse_rect_arg` の別名)。"""
    return _parse_rect_arg(args, "clip", pg)
```

`rpc_addBorder` の直後に追加する。

```python
# 手動の上書きの置換語の上限文字数 (外部由来の入力なので上限を置く)。
MAX_COVER_TEXT_CHARS = 200


def cover_font_size(h: float) -> float:
    """上書き矩形の高さから文字サイズを決める (矩形の縦に収まる 0.7 倍。4〜200pt に丸める)。"""
    return min(200.0, max(4.0, h * 0.7))


def _cover_text(args: dict) -> str:
    return sanitize_text(str(args.get("text") or "")).strip()[:MAX_COVER_TEXT_CHARS]


def _manual_cover(pg: Page, el_id) -> TextElement:
    try:
        eid = int(el_id)
    except (TypeError, ValueError):
        raise ValueError(f"elId must be an integer: {el_id!r}") from None
    for e in pg.elements:
        if e.id == eid and isinstance(e, TextElement) and e.manual_cover and not e.deleted:
            return e
    raise ValueError(f"elId {el_id!r} is not a manual cover on this page")


def rpc_addCover(s: WebSession, args: dict) -> dict:
    """ドラッグした矩形へ手動の上書き (背景色の矩形 + 置換語) を 1 つ置く (Undo 可)。

    要素は「不可視かつ置換済み扱いの `TextElement`」で、描画は自動置換と同じ経路
    (`svg_exporter._cover_svg`) を通る。辞書置換ではないので `dict_revert` は持たない。
    """
    pg = s.page(args["fileIndex"], args["pageInFile"])
    rect = _parse_rect_arg(args, "rect", pg)
    if rect is None:
        raise ValueError("rect is required")
    text = _cover_text(args)
    mapped = fonts.map_font("sans-serif", text)  # フォント名は無いので文字種の既定へ倒す
    z = max((e.z for e in pg.elements), default=0) + 1
    el = TextElement(
        bbox=rect, z=z, text=text, font_family=mapped.family, font_size=cover_font_size(rect.h),
        weight=mapped.weight, italic=mapped.italic, origin_x=rect.x, origin_y=rect.y1,
        invisible=True, manual_cover=True, dict_match=DictMatch(source="", target=text),
    )
    s.undo.push(AddElementCommand(pg, el))
    return {"elId": el.id}


def rpc_coverList(s: WebSession, args: dict) -> dict:
    """ページ上の手動の上書き (未削除) を要素の並び順で返す。UI のオーバーレイの元データ
    (表示 SVG から座標を拾わず、モデルを正にする)。"""
    pg = s.page(args["fileIndex"], args["pageInFile"])
    covers = [
        {
            "elId": e.id,
            "rect": {"x": e.bbox.x, "y": e.bbox.y, "w": e.bbox.w, "h": e.bbox.h},
            "text": e.text,
        }
        for e in pg.elements
        if isinstance(e, TextElement) and e.manual_cover and not e.deleted
    ]
    return {"covers": covers}


def rpc_updateCover(s: WebSession, args: dict) -> dict:
    """手動の上書きの矩形 (`rect`) と置換語 (`text`) のどちらか以上を変える (Undo 可)。"""
    pg = s.page(args["fileIndex"], args["pageInFile"])
    el = _manual_cover(pg, args.get("elId"))
    rect = _parse_rect_arg(args, "rect", pg)
    text = _cover_text(args) if "text" in args else None
    if rect is None and text is None:
        raise ValueError("rect or text is required")
    font_size = cover_font_size(rect.h) if rect is not None else None
    s.undo.push(UpdateCoverCommand(el, rect, text, font_size))
    return {}
```

`rpc_planPage` のループ先頭の `if not isinstance(el, TextElement) or el.deleted:` を
`if not isinstance(el, TextElement) or el.deleted or el.manual_cover:` にし、コメントを 1 行足す
(「手動の上書きは辞書置換ではなく、戻すの対象でもない」)。

`rpc_removedList` の `if isinstance(el, TextElement):` ブロックを次にする。

```python
        if isinstance(el, TextElement):
            snippet = el.text.strip()[:16]
            kind_label = "上書き" if el.manual_cover else "文字"
            label = f"{kind_label}「{snippet}」" if snippet else kind_label
```

`HANDLERS` に `"addCover": rpc_addCover, "coverList": rpc_coverList, "updateCover": rpc_updateCover,`
を `addBorder` の直後に足す。

- [ ] **Step 5: テストを通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_web_rpc.py test/test_shell_rpc.py test/test_export_clip.py test/test_dict_revert.py -v`
Expected: すべて PASS。`font_family` が `BIZ UDPGothic` にならない場合は `fonts.map_font` の
既定表(`_DEFAULTS[("ja", "sans-serif")]`)を確認し、テストの期待値をその値に合わせる。

- [ ] **Step 6: コミット**

```bash
git add pdf-to-svg/src/web/commands.py pdf-to-svg/src/web/rpc_methods.py pdf-to-svg/test/test_web_rpc.py
git commit -m "feat(web): 手動の上書きを置く・一覧する・動かす RPC と UpdateCoverCommand を追加する"
```

---

### Task 6: UI — トーストと「上書き」ツール(置く)

**Files:**
- Modify: `pdf-to-svg/resources/web/state.js:25-31`
- Modify: `pdf-to-svg/resources/web/index.html:163-172`
- Modify: `pdf-to-svg/resources/web/styles.css`(`.border-opts` の直後)
- Modify: `pdf-to-svg/resources/web/app.js`(`reloadState` 114-130、`ensureSvg` 178、`installCropDrag` 491-523、`render` 804-808、`wireEditTools` 946-949、`exportSvg` の呼び出し 1106/1141/1146)
- Test: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`(追記)

**Interfaces:**
- Consumes: RPC `addCover`(Task 5)、`state.ocrPages` / `pageSvg.coverFallback` / `exportSvg.coverFallback`(Task 4)
- Produces: `S.tool === "cover"`、`S.coverText: string`、`S.coverSel: number|null`、`S.coverDrag: object|null`、
  `#cover-opts` / `#cover-text`、ツールボタン `[data-tool="cover"]`、CSS `.editor.tool-cover`

- [ ] **Step 1: E2E テストを書く**

`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` の末尾に追記する。フィクスチャ `ocr_layer_pdf`
は `conftest.py` のもの(Task 1)を使う。

```python
def _goto_step3(page, pdf_path):
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(str(pdf_path))
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル", timeout=30_000)
    page.click("#btn-next")
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))
    page.click("#btn-next")  # 辞書が空なので未確認ガードは出ない
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
    expect(page.locator("#trim-stage svg")).to_be_visible()


def test_ocr_layer_upload_notifies(e2e_page, ocr_layer_pdf):
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(str(ocr_layer_pdf))
    expect(page.locator("#toast")).to_contain_text("OCR 文字のページを 1 ページ検出", timeout=30_000)


def test_manual_cover_tool_places_cover(e2e_page, ocr_layer_pdf):
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="cover"]')
    expect(page.locator("#cover-opts")).to_be_visible()
    page.fill("#cover-text", "手動語")
    box = page.locator("#trim-stage svg").bounding_box()
    # ページ座標 (20,120)-(120,140) 付近 (白地の不可視文字の上) をドラッグする
    sx, sy = box["width"] / 300, box["height"] / 200
    page.mouse.move(box["x"] + 20 * sx, box["y"] + 110 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 120 * sx, box["y"] + 135 * sy, steps=5)
    page.mouse.up()
    expect(page.locator('#trim-stage svg g[data-el] text', has_text="手動語")).to_have_count(1)
    covers = page.evaluate("""async () => {
        const st = await window.rpc("state");
        return (await window.rpc("coverList", { fileIndex: 0, pageInFile: 0 })).covers;
    }""")
    assert len(covers) == 1 and covers[0]["text"] == "手動語"
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pdftosvg_app_flow_e2e.py -m e2e -k "ocr_layer or manual_cover" -v`
Expected: FAIL(トーストが出ない / `[data-tool="cover"]` が無い)。

- [ ] **Step 3: 状態・マークアップ・スタイル**

`state.js` の `borderWidth` の直後に追加する。

```js
  coverText: "",        // 上書きツールの置換語 (空なら矩形だけ)
  coverSel: null,       // 上書きツールで選んでいる要素 id (null = 未選択。入力欄は次に置く語)
  coverDrag: null,      // 上書きの移動・伸縮中の状態 (cover.js が使う)
```

`tool:` のコメントを `(select/crop/border/cover)` にする。

`index.html` の `float-tools` の `segment` に枠線ボタンの直後で追加する。

```html
            <button data-tool="cover" aria-pressed="false"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="8" width="16" height="9" rx="1.5"></rect><path d="M8 12.5h8"></path></svg>上書き</button>
```

`border-opts` の直後に追加する。

```html
          <div class="cover-opts" id="cover-opts" hidden="">
            <input type="text" id="cover-text" maxlength="200" placeholder="置換語（空なら矩形だけ）" title="矩形の上に描く語。選んだ上書きがあればその語を変える">
          </div>
```

`index.html` 冒頭の `<style>` の `.editor.tool-border` の行に `.editor.tool-cover .page-host, .editor.tool-cover .doc-stage` を足す(カーソルを十字に)。

`styles.css` の `.border-opts[hidden]` の直後に追加する。

```css
.cover-opts { display: flex; align-items: center; gap: 8px; }
.cover-opts[hidden] { display: none; }
.cover-opts input { width: 200px; height: 30px; border: 1px solid var(--border); border-radius: 8px; padding: 0 10px; font-size: 13px; }
.cover-rubber { position: absolute; border: 1.5px dashed var(--good); background: oklch(0.62 0.12 150 / 0.08); pointer-events: none; border-radius: 2px; }
```

- [ ] **Step 4: app.js — トースト**

`reloadState` の `degradedNoticed` を `{ truncated: 0, noBackground: 0, ocrPages: 0 }` にし、
`noBackground` の `if` の直後に追加する。

```js
    if (st.ocrPages && st.ocrPages !== degradedNoticed.ocrPages) {
      msgs.push("画像 + OCR 文字のページを " + st.ocrPages + " ページ検出しました。置換箇所は画像の上に矩形で上書きします");
    }
```

`degradedNoticed.ocrPages = st.ocrPages || 0;` も足す。

`ensureSvg`(178 行)で `pageSvg` の結果を受けた直後に追加する。

```js
    if (S.svgCache[k].coverFallback) toast("背景色を採れなかった " + S.svgCache[k].coverFallback + " 箇所は白で上書きしました");
```

`exportSvg` を呼ぶ 3 箇所(1106・1141・1146 行)の直後で、結果の `coverFallback` を合計し、
書き出し完了のトーストに「/ 背景色を採れなかった N 箇所は白で上書きしました」を連結する
(既存の完了トーストの文言は変えない。`N` が 0 なら足さない)。

- [ ] **Step 5: app.js — ツールとドラッグ**

`installCropDrag` の mousedown の条件を
`if (S.phase !== 3 || (S.tool !== "crop" && S.tool !== "border" && S.tool !== "cover")) return;` にし、
`rubber.className` を
`S.tool === "border" ? "border-rubber" : S.tool === "cover" ? "cover-rubber" : "crop-rubber"` にする。
mousedown の先頭で、上書きのオーバーレイ上の操作はここで扱わない: `if (e.target.closest(".cover-box")) return;` を足す。

mouseup の分岐を次にする。

```js
      if (d.mode === "border") {
        await rpc("addBorder", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, rect: rect, color: S.borderColor, width: S.borderWidth });
      } else if (d.mode === "cover") {
        await rpc("addCover", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, rect: rect, text: S.coverText });
      } else {
        await rpc("deleteRegion", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, rect: rect });
      }
```

`render` の手順 3 で `ed3.classList.toggle("tool-cover", S.tool === "cover");` を足し、
`var co = document.getElementById("cover-opts"); if (co) co.hidden = S.tool !== "cover";` を足す。

`wireEditTools` の枠線の配線の直後に追加する。

```js
    // 上書きツールの置換語。上書きを選んでいれば `change` でその語を変える (Task 7 の cover.js)。
    document.getElementById("cover-text").addEventListener("input", function () { S.coverText = this.value; });
```

- [ ] **Step 6: E2E を通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pdftosvg_app_flow_e2e.py -m e2e -v`
Expected: 既存分を含めすべて PASS。ドラッグの座標が合わず要素が置かれない場合は、
`page.mouse` の座標を `#trim-stage svg` の `bounding_box()` から計算し直す。

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pdftosvg_js_smoke.py test/test_pdftosvg_state_js.py -v`
Expected: PASS(`state.js` の追加フィールドで壊れない)。

- [ ] **Step 7: コミット**

```bash
git add pdf-to-svg/resources/web/state.js pdf-to-svg/resources/web/index.html pdf-to-svg/resources/web/styles.css pdf-to-svg/resources/web/app.js pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py
git commit -m "feat(ui): 手順 3 に「上書き」ツールを足し OCR 文字層と採色失敗をトーストで伝える"
```

---

### Task 7: UI — 上書きの移動・伸縮・置換語の変更(`cover.js`)

**Files:**
- Create: `pdf-to-svg/resources/web/cover.js`
- Modify: `pdf-to-svg/resources/web/app.js`(import、`render` 手順 3 の `mountPage` の `onMounted`、`wireEditTools` の `cover-text`、起動時の `installCoverDrag`)
- Modify: `pdf-to-svg/resources/web/styles.css`(`.cover-box`)
- Test: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`(追記)

**Interfaces:**
- Consumes: RPC `coverList` / `updateCover`(Task 5)、`S.coverSel` / `S.coverDrag` / `S.coverText`(Task 6)、
  `geometry.js` の `clientToPage(svgEl, clientX, clientY)`
- Produces: `cover.js` の `initCover({ rpc, afterEdit, pageOf })`、`drawCoverOverlay(host)`、
  `installCoverDrag(host)`、`commitCoverText(text)`

- [ ] **Step 1: E2E テストを書く**

`test_pdftosvg_app_flow_e2e.py` の末尾に追記する。

```python
def test_manual_cover_resize_and_retext(e2e_page, ocr_layer_pdf):
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="cover"]')
    page.fill("#cover-text", "初期")
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200
    page.mouse.move(box["x"] + 20 * sx, box["y"] + 110 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 120 * sx, box["y"] + 135 * sy, steps=5)
    page.mouse.up()
    overlay = page.locator("#trim-stage .cover-box")
    expect(overlay).to_have_count(1)

    # 右下ハンドルで伸縮 → updateCover(rect)
    h = overlay.locator(".h.se").bounding_box()
    page.mouse.move(h["x"] + h["width"] / 2, h["y"] + h["height"] / 2)
    page.mouse.down()
    page.mouse.move(h["x"] + 40 * sx, h["y"] + 20 * sy, steps=5)
    page.mouse.up()
    rect = page.evaluate("""async () => (await window.rpc("coverList", { fileIndex: 0, pageInFile: 0 })).covers[0].rect""")
    assert rect["w"] > 100 and rect["h"] > 25

    # オーバーレイをクリックして選び、入力欄で語を変える → updateCover(text)
    page.locator("#trim-stage .cover-box").click()
    expect(page.locator("#cover-text")).to_have_value("初期")
    page.fill("#cover-text", "変更後")
    page.press("#cover-text", "Enter")
    expect(page.locator('#trim-stage svg g[data-el] text', has_text="変更後")).to_have_count(1)
    text = page.evaluate("""async () => (await window.rpc("coverList", { fileIndex: 0, pageInFile: 0 })).covers[0].text""")
    assert text == "変更後"

    # Undo で語が戻る
    page.keyboard.press("Control+z")
    expect(page.locator('#trim-stage svg g[data-el] text', has_text="初期")).to_have_count(1)
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pdftosvg_app_flow_e2e.py -m e2e -k "resize_and_retext" -v`
Expected: FAIL(`.cover-box` が無い)。

- [ ] **Step 3: `cover.js`**

`pdf-to-svg/resources/web/cover.js` を新規作成する。

```js
// =============================================================================
// cover.js — 手順 3「上書き」ツールのオーバーレイ (移動・角ハンドル伸縮・置換語の変更)
// =============================================================================
// 置いた上書きは `coverList` RPC が返す矩形をモデルの正として HTML の箱で重ね、ドラッグ中は
// 箱だけを動かし、mouseup の 1 回だけ `updateCover` を送る (`figure.js` の採用矩形と同じ流儀)。
import { clientToPage } from "./geometry.js";
import { S } from "./state.js";

const MIN_SIZE_PT = 4;
let ui = null; // { rpc, afterEdit, pageOf } を app.js が注入する

function initCover(deps) { ui = deps; }

function copyRect(r) { return { x: r.x, y: r.y, w: r.w, h: r.h }; }

function pageSizeOf(svgEl) {
  var vb = svgEl.viewBox.baseVal;
  return { w: vb.width, h: vb.height };
}

function clampToPage(r, w, h) {
  var x0 = Math.max(0, Math.min(r.x, w)), y0 = Math.max(0, Math.min(r.y, h));
  var x1 = Math.max(0, Math.min(r.x + r.w, w)), y1 = Math.max(0, Math.min(r.y + r.h, h));
  return { x: x0, y: y0, w: Math.max(0, x1 - x0), h: Math.max(0, y1 - y0) };
}

function placeRect(box, r, svgEl, host) {
  var sr = svgEl.getBoundingClientRect(), hb = host.getBoundingClientRect(), vb = svgEl.viewBox.baseVal;
  var sx = sr.width / vb.width, sy = sr.height / vb.height;
  box.style.left = ((r.x - vb.x) * sx + sr.left - hb.left) + "px";
  box.style.top = ((r.y - vb.y) * sy + sr.top - hb.top) + "px";
  box.style.width = (r.w * sx) + "px";
  box.style.height = (r.h * sy) + "px";
}

/** 手順 3 で上書きツールが選ばれている間だけ、ページ上の上書きを箱で重ねる。呼ぶたびに描き直す */
async function drawCoverOverlay(host) {
  host.querySelectorAll(".cover-box").forEach(function (b) { b.remove(); });
  if (S.phase !== 3 || S.tool !== "cover") { S.coverSel = null; return; }
  var svgEl = host.querySelector("svg"); if (!svgEl) return;
  var pg = ui.pageOf();
  var res = await ui.rpc("coverList", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
  if (host.querySelector("svg") !== svgEl) return; // 取得中にページが変わった
  var covers = res.covers || [];
  if (S.coverSel !== null && !covers.some(function (c) { return c.elId === S.coverSel; })) S.coverSel = null;
  covers.forEach(function (c) {
    var box = document.createElement("div");
    box.className = "cover-box" + (c.elId === S.coverSel ? " sel" : "");
    box.dataset.elId = c.elId;
    box.innerHTML =
      '<span class="h nw" data-corner="nw"></span><span class="h ne" data-corner="ne"></span>' +
      '<span class="h sw" data-corner="sw"></span><span class="h se" data-corner="se"></span>';
    placeRect(box, c.rect, svgEl, host);
    box.querySelectorAll(".h").forEach(function (h) {
      h.addEventListener("mousedown", function (e) {
        e.stopPropagation(); e.preventDefault();
        S.coverDrag = { mode: "resize", elId: c.elId, rect: copyRect(c.rect), orig: copyRect(c.rect), corner: h.dataset.corner, box: box, moved: false };
      });
    });
    box.addEventListener("mousedown", function (e) {
      e.stopPropagation(); e.preventDefault();
      S.coverDrag = { mode: "move", elId: c.elId, rect: copyRect(c.rect), orig: copyRect(c.rect), origin: { x: e.clientX, y: e.clientY }, box: box, moved: false };
    });
    box.addEventListener("click", function (e) { e.stopPropagation(); });
    host.appendChild(box);
  });
  syncTextInput(covers);
}

/** 選んでいる上書きの語を入力欄へ (未選択なら利用者の入力をそのまま残す) */
function syncTextInput(covers) {
  var input = document.getElementById("cover-text"); if (!input) return;
  var sel = covers.find(function (c) { return c.elId === S.coverSel; });
  if (sel) { input.value = sel.text; }
}

/** 入力欄の確定 (Enter / change)。上書きを選んでいれば語を変え、未選択なら次に置く語にする */
async function commitCoverText(text) {
  S.coverText = text;
  if (S.coverSel === null) return;
  var pg = ui.pageOf();
  var res = await ui.rpc("coverList", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
  var cur = (res.covers || []).find(function (c) { return c.elId === S.coverSel; });
  if (!cur || cur.text === text) return;
  await ui.rpc("updateCover", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elId: S.coverSel, text: text });
  await ui.afterEdit();
}

/** 移動・伸縮のドラッグ。起動時に一度だけ張る (多重登録防止) */
function installCoverDrag(host) {
  window.addEventListener("mousemove", function (e) {
    var d = S.coverDrag; if (!d) return;
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    var sz = pageSizeOf(svgEl);
    d.moved = true;
    if (d.mode === "move") {
      var a = clientToPage(svgEl, d.origin.x, d.origin.y);
      var b = clientToPage(svgEl, e.clientX, e.clientY);
      var moved = { x: d.orig.x + (b.x - a.x), y: d.orig.y + (b.y - a.y), w: d.orig.w, h: d.orig.h };
      // 大きさを保ったままページ内へ収める
      moved.x = Math.max(0, Math.min(moved.x, sz.w - moved.w));
      moved.y = Math.max(0, Math.min(moved.y, sz.h - moved.h));
      d.rect = moved;
    } else {
      var p = clientToPage(svgEl, e.clientX, e.clientY);
      p.x = Math.max(0, Math.min(p.x, sz.w)); p.y = Math.max(0, Math.min(p.y, sz.h));
      var o = d.orig, c = d.corner;
      var left = c.indexOf("w") >= 0 ? p.x : o.x, right = c.indexOf("e") >= 0 ? p.x : o.x + o.w;
      var top = c.indexOf("n") >= 0 ? p.y : o.y, bottom = c.indexOf("s") >= 0 ? p.y : o.y + o.h;
      d.rect = { x: Math.min(left, right), y: Math.min(top, bottom), w: Math.max(MIN_SIZE_PT, Math.abs(right - left)), h: Math.max(MIN_SIZE_PT, Math.abs(bottom - top)) };
    }
    placeRect(d.box, d.rect, svgEl, host);
  });
  window.addEventListener("mouseup", async function () {
    var d = S.coverDrag; if (!d) return;
    S.coverDrag = null;
    S.coverSel = d.elId;
    if (!d.moved) { // クリック = 選択だけ
      await drawCoverOverlay(host);
      return;
    }
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    var sz = pageSizeOf(svgEl);
    var r = clampToPage(d.rect, sz.w, sz.h);
    if (r.w < MIN_SIZE_PT || r.h < MIN_SIZE_PT) { await drawCoverOverlay(host); return; }
    var pg = ui.pageOf();
    await ui.rpc("updateCover", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elId: d.elId, rect: r });
    await ui.afterEdit();
  });
}

export { initCover, drawCoverOverlay, installCoverDrag, commitCoverText };
```

- [ ] **Step 4: app.js の配線**

- import に `import { initCover, drawCoverOverlay, installCoverDrag, commitCoverText } from "./cover.js";` を足す。
- `initFigure(...)` を呼んでいる起動箇所の直後で `initCover({ rpc: rpc, afterEdit: afterEdit, pageOf: function () { return S.PAGES[S.page]; } });` と
  `installCoverDrag(document.getElementById("trim-stage"));` を呼ぶ(`installCropDrag()` の隣)。
- `render` の手順 3 の `mountPage(document.getElementById("trim-stage"), ed3, true, wireTrimStage);` を
  `mountPage(document.getElementById("trim-stage"), ed3, true, function () { wireTrimStage(); drawCoverOverlay(document.getElementById("trim-stage")); });` にする。
- `wireEditTools` の `cover-text` の `input` リスナーの直後に追加する。

```js
    var coverInput = document.getElementById("cover-text");
    coverInput.addEventListener("change", function () { commitCoverText(this.value); });
    coverInput.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); this.blur(); } });
```

  `blur` で `change` が発火し、語が変わっていれば `updateCover` が飛ぶ。
- ツール切替のクリックハンドラ(`S.tool = b.dataset.tool;` の直後)に `S.coverSel = null;` を足す
  (ツールを離れたら選択を解く)。
- `installCropDrag` の mousedown で `S.tool === "cover"` かつ `e.target.closest(".cover-box")` が無い
  空白クリックのときは `S.coverSel = null;` にする(選択解除。Task 6 の `return` の手前ではなく
  ラバーバンド開始の直前)。

- [ ] **Step 5: スタイル**

`styles.css` の `.cover-rubber` の直後に追加する。

```css
.cover-box { position: absolute; border: 2px solid var(--good); background: transparent; cursor: move; border-radius: 3px; box-sizing: border-box; }
.cover-box.sel { box-shadow: 0 0 0 3px oklch(0.62 0.12 150 / 0.25); }
.cover-box .h { position: absolute; width: 10px; height: 10px; background: #fff; border: 2px solid var(--good); border-radius: 2px; }
.cover-box .h.nw { left: -6px; top: -6px; cursor: nwse-resize; } .cover-box .h.se { right: -6px; bottom: -6px; cursor: nwse-resize; }
.cover-box .h.ne { right: -6px; top: -6px; cursor: nesw-resize; } .cover-box .h.sw { left: -6px; bottom: -6px; cursor: nesw-resize; }
```

- [ ] **Step 6: E2E を通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pdftosvg_app_flow_e2e.py -m e2e -v`
Expected: すべて PASS。Undo のショートカットが手順 3 で `undo` RPC を撃つことは既存の
`test_four_step_flow` が前提にしている(撃たない場合は `#btn-undo` 相当のボタンをクリックする形へ
テストを変える)。

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pdftosvg_js_smoke.py -v`
Expected: PASS(新モジュールの import で壊れない)。

- [ ] **Step 7: コミット**

```bash
git add pdf-to-svg/resources/web/cover.js pdf-to-svg/resources/web/app.js pdf-to-svg/resources/web/styles.css pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py
git commit -m "feat(ui): 手動の上書きを角ハンドルで伸縮・ドラッグで移動・入力欄で語を変更できるようにする"
```

---

### Task 8: 文書と HTML 再生成・リリース差し替え

**Files:**
- Modify: `docs/pdf-to-svg/src/設計正典.md`(中核原則・セキュリティ)
- Modify: `docs/pdf-to-svg/src/設計書.md`(3.1 / 4.1 / 5.1 / 7.2 / 7.3 / 8 節)
- Modify: `docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`(出力・RPC・テストの表)
- Modify: `docs/pdf-to-svg/src/操作手順書.md`(手順 3「上書き」)
- Generate: `docs/pdf-to-svg/pdf-to-svg_設計.html` / `docs/pdf-to-svg/pdf-to-svg_手引き.html`

- [ ] **Step 1: 設計正典**

「中核原則」の末尾(画像のクリップ形状の項の直後)に追加する。

```markdown
- **不可視 OCR 文字層は「未置換は描かず、置換済みは隠して描く」**: スキャン画像の上に OCR 結果を
  透明(描画モード 3 / 7)で重ねた PDF は文字数でベクター扱いになり、そのまま描くと画像の字面と
  二重になる。`get_texttrace()` の `type` を seqno 経由で `TextElement.invisible` に写し
  (`get_text("dict")` の span はモードを持たない。照合失敗は可視へ倒す)、書き出しでは未置換を
  出さず、置換済みは `export/cover.py` が画像の画素から採った背景色の矩形で隠してから描く
  (`<g><rect/><text/></g>`)。編集画面(`annotate=True`)では未置換も `fill-opacity="0"` で描き、
  クリック取り込みの当たり判定を残す。矩形はモデルに持たず書き出し時に合成する(グレー化・
  切り出しと同じ生成点の規律)。文字が読み取れないページ向けの手動の上書き(手順 3 の「上書き」
  ツール)は「不可視かつ置換済み扱いの `TextElement`」(`manual_cover`)で、同じ経路で描く。
```

「セキュリティ」の資源上限の項(「外部由来の入力は…」)に 1 文足す:
「上書き矩形の採色で画像をデコードするときも `MAX_COVER_IMAGE_PIXELS`(`export/cover.py`)で切り、
超過・壊れた画像は白へ degrade して件数(`coverFallback`)を UI へ返す。」

- [ ] **Step 2: 設計書**

- 3.1 節の `TextElement` の表と定義に `invisible` / `manual_cover` を足す。
- 4.1 節に「texttrace の `type` から不可視 seqno の集合を作り、照合できた span だけに
  `invisible` を与える(混在 seqno・照合失敗・degraded は可視)」を 1 段落足す。
- 5.1 節に「不可視文字の 3 分岐」の表(spec の 2 節の表をそのまま)と `_cover_svg` / `_cover_sampler`
  / `ExportReport`、`cover.py` の採り方(量子化 16 階調・最頻色・平均値・`MIN_CONTRAST`・採取元の
  順序 画像 → スキャン背景 → 白)を足す。
- 7.2 節の `HANDLERS` の表を **28 メソッド**にし、編集の行に `addCover`, `coverList`, `updateCover` を
  足す。要点に `state.ocrPages`、`pageSvg` / `exportSvg` の `coverFallback` を足す。
- 7.3 節のコマンド一覧を 6 種にし、`UpdateCoverCommand` を足す。
- 8 節のステップ 3 の説明に「上書き」ツール(置換語の入力欄・ドラッグで置く・角ハンドルで伸縮・
  本体ドラッグで移動・選んで入力欄で語を変える・削除は選択ツール)を足し、ファイル表に
  `cover.js` の行を足す。トースト 2 種も足す。

- [ ] **Step 3: 仕様一覧と操作手順書**

- 仕様一覧の入力の表に「上書きの矩形/置換語 | `{x,y,w,h}` / 200 文字まで | 手動の上書き」、
  出力の表に「上書き矩形 | `<g><rect><text>` | 不可視 OCR 文字の置換箇所・手動の上書き。色は画像から採色」、
  RPC の表に `addCover` / `coverList` / `updateCover`、テストの表に `test_cover.py` と
  `test_ocr_layer.py` と E2E 2 本の行を足す。
- 操作手順書の手順 3 に「上書き」ツールの使い方(文字が読み取れない PDF で、範囲をドラッグして
  置換語を置く。角で大きさ、本体で位置、入力欄で語を変える。消すときは選択ツールで選んで削除)
  を 1 節足す。手順 1 に「画像 + OCR 文字のページを検出したときの通知」を 1 文足す。

- [ ] **Step 4: HTML を再生成して差分を確認する**

Run: `py -3.13 docs/_build/build_all.py --project pdf-to-svg`
Expected: `[ok] pdf-to-svg/pdf-to-svg_設計.html` と `[ok] pdf-to-svg/pdf-to-svg_手引き.html`。
`git status` で 2 枚の HTML に差分が出る。

Run: `py -3.13 -m pytest docs/_build -q`
Expected: PASS。

- [ ] **Step 5: コミット**

```bash
git add docs/pdf-to-svg
git commit -m "docs(pdf-to-svg): 不可視 OCR 文字層の上書き描画と手動の上書きを設計書・仕様一覧・操作手順書へ反映し HTML を再生成する"
```

- [ ] **Step 6: リリースを差し替える**

`gh release list --limit 1` で最新タグを確認し、ノートに `### 不可視 OCR 文字層の上書き描画と手動の上書き`
の節を「## 含まれる変更」の先頭へ追記する(既存の節は消さない。`## 検証` を二重にしない)。

```bash
git tag -f <最新タグ> HEAD
git push origin -f refs/tags/<最新タグ>    # 拒否されたら利用者へ `! git push origin -f refs/tags/<タグ>` を依頼
gh release edit <最新タグ> --notes-file <追記したノート>
```

---

## Self-Review

- **Spec 1 節(検出)**: Task 1。混在 seqno・照合失敗・degraded の可視倒しを含む。
- **Spec 2 節(書き出し)**: Task 2(採色)+ Task 3(3 分岐・`<g>`・`ExportReport`・採取元の順序・
  `text_els` の絞り込み・グレー化)。代表色を「箱の平均」に変えた点は Task 2 Step 5 で spec へ反映。
- **Spec 3 節(辞書)**: 変更なし。Task 3 のテストが `auto_apply` 経由で置換している。
- **Spec 4 節(Web/UI 通知)**: Task 4(RPC)+ Task 6 Step 4(トースト)。
- **Spec 5 節(テスト)**: 各 Task に分散。`vector_pdf` のバイト一致は Task 3
  `test_report_is_optional_and_zero_without_invisible` と既存 `test_pipeline`。
- **Spec 6 節(手動の上書き)**: Task 5(RPC・コマンド・確認一覧の除外・削除一覧のラベル)+
  Task 6(置く)+ Task 7(移動・伸縮・語の変更)。スキャン背景からの採色は Task 3 の
  `_cover_sampler` が担い、`test_web_rpc` の fallback テストは画像無しの経路を確認する。
  スキャン背景からの採色そのものは `test_ocr_layer.py` に
  `RasterBackground` を持つ `Page` を組んで `page_to_svg` を呼ぶテストを Task 3 Step 1 へ 1 本足すこと:

  ```python
  def test_scanned_background_is_used_for_sampling():
      from model.document import Page, RasterBackground
      from model.elements import DictMatch
      import io
      from PIL import Image
      buf = io.BytesIO(); Image.new("RGB", (20, 20), (10, 20, 30)).save(buf, format="PNG")
      pg = Page(index=0, width_pt=100, height_pt=100, is_scanned=True,
                background=RasterBackground(png_bytes=buf.getvalue(), rect=Rect(0, 0, 100, 100)))
      pg.elements.append(TextElement(bbox=Rect(10, 10, 30, 10), text="X", invisible=True, manual_cover=True,
                                     dict_match=DictMatch(source="", target="X")))
      line = _line_with(page_to_svg(pg), "<g><rect ")
      assert 'fill="#0a141e"' in line.split("<text")[0]
      assert 'fill="#ffffff"' in line.split("<text")[1]  # 暗い背景 → 白文字
  ```

  (`Rect` を `model.elements` から import する。)
- **Spec 7 節(文書)**: Task 8。
- **Placeholder**: 「Similar to Task N」「TBD」無し。
- **型の整合**: `ExportReport` / `page_to_svg(report=)` は Task 3 → 4 で同名。
  `UpdateCoverCommand(el, rect, text, font_size)` は Task 5 内で定義と呼び出しが一致。
  `cover.CoverColors(background, foreground, fallback)` は Task 2 → 3 で一致。
  `S.coverText` / `S.coverSel` / `S.coverDrag` は Task 6 で定義、Task 7 で使用。
