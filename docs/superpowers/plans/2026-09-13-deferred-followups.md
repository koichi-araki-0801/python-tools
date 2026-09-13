# 繰延項目の解消（証拠の補強と角ハンドルの集約） 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 不可視 OCR 文字層の上書き描画で繰り延べてきた項目のうち、調査で「直す価値がある」と判断した
ものを解消する。壊しても気付けない箇所へ証拠を足し、設計書が既に嘘になっている重複を消す。

**Architecture:** 2 つの束に分ける。束 A は証拠の補強（テスト 3 種と、1 行のメモリ削減、コメント 2 行）で、
既存の原稿の記述が有効なままなので文書の往復が発生しない。束 B は角ハンドルの伸縮計算とハンドルの
マークアップを `geometry.js` へ集約するもので、設計書 8 章の記述と HTML 再生成とリリース差し替えを伴う。

**Tech Stack:** Python 3.13 / Pillow / PyMuPDF（`src/engine/` に隔離）/ pytest + Playwright（Edge）/
素の JavaScript（ES modules）。

**Spec:** 本計画が正典。根拠となる調査結果は本文の各タスクへ埋め込んである。

## Global Constraints

- Python は常に `py -3.13`。pytest は `pdf-to-svg/` の中から `py -3.13 -m pytest test/...` の形で実行する
  （リポジトリ直下での素の `pytest` は禁止。姉妹プロジェクトに同名のテストモジュールがある）。
- `fitz`（PyMuPDF）を import してよいのは `src/engine/pdf_engine.py` と `src/engine/classify.py` だけ。
- SVG 属性は `svg_exporter._attr` / `_paint` 経由でのみ書く。
- 不可視文字を持たない PDF の出力は 1 バイトも変えない（`test/test_pipeline.py` ほかが固定）。
- 攻撃者が用意できる入力（PDF の画像）は上限を置き、例外ではなく degrade へ倒す。
- ブラウザの `alert` / `prompt` / `confirm` は使わない。
- コメントは日本語の散文、識別子はバッククォート、理由は現在形。日付・経緯・内部のタスク番号を書かない
  （`docs/コメント規約.md`）。`.js` は `// ===` の装飾ボックスヘッダを保つ。
- コミットすると post-commit が auto-push し、pre-push が検証一式（約 2 分）を回す。`--no-verify` を
  使わない。force push もしない（リリースのタグ差し替えを除く）。
- コミットメッセージは日本語の Conventional Commits。本文の末尾に次の 2 行を置く。

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_0126DHJZ8WfffcXsMqETHsLc
  ```

## File Structure

| ファイル | 変更 | 責務 |
|---|---|---|
| `pdf-to-svg/src/export/cover.py` | 変更 | 同一モードでの無駄なコピーを避ける。コメントを部分透明まで広げる |
| `pdf-to-svg/src/export/svg_exporter.py` | 変更 | ラスタ背景のキャッシュキーの前提をコメントで示す |
| `pdf-to-svg/test/test_cover.py` | 変更 | 透明を持つ他形式の採色、採色側とグレー化側の透明判定のずれ検出 |
| `pdf-to-svg/test/test_ocr_layer.py` | 変更 | 索引が照合を諦めたときの抽出結果 |
| `pdf-to-svg/resources/web/geometry.js` | 変更 | 角ハンドルの伸縮計算とハンドルのマークアップを持つ |
| `pdf-to-svg/resources/web/cover.js` / `figure.js` | 変更 | 共有した関数を読む |
| `pdf-to-svg/test/test_pdftosvg_geometry_js.py` | 変更 | 伸縮計算の単体 |
| `docs/pdf-to-svg/src/設計書.md` + 生成 HTML 2 枚 | 変更 | 8 章の記述を実態へ（束 B） |

パスはすべて `C:\Users\caads\python-tools` からの相対。

---

### Task 1: 証拠の補強（束 A）

**Files:**
- Modify: `pdf-to-svg/src/export/cover.py`（`decode_image`）
- Modify: `pdf-to-svg/src/export/svg_exporter.py`（`_cover_sampler` の `image_for`）
- Test: `pdf-to-svg/test/test_cover.py`、`pdf-to-svg/test/test_ocr_layer.py`

**背景（実装前に読むこと）:**

調査で 2 つの前提が誤っていたことが分かった。

第一に、透明を持つ画像の採色で自動テストがあるのは `RGBA` だけだが、**`LA` は主要経路である**。
`grayscale.to_gray_image` は透明を持つ画像を `LA` モードの PNG で返す（実測確認済み）。`_cover_sampler` は
`image_fn` を通した後のバイト列を `decode_image` へ渡すので、「グレー書き出し + 透明を持つ画像 + 上書き」の
組み合わせは必ず `LA` の分岐を通る。稀な経路ではない。

第二に、索引が照合を諦めた（`degraded`）ときの挙動は「上書きが無効になるだけ」ではない。実測すると
**不可視の OCR 文字がすべて可視として書き出される**（`ocr_layer_sample.pdf` で 3 つとも `invisible` が
`False` になる）。画像の字と二重に描かれ、利用者への通知も無い。現状がそうなっているという事実を
固定する回帰テストが要る。将来 `match` の既定値や `matched is not None` の判定を触ったとき、degraded
ページの全文字が不可視扱いになって白紙同然で書き出される退行を、今は誰も検出できない。

第三に、`decode_image` の alpha 経路は `im.convert("RGBA")` を無条件に呼ぶ。Pillow の `convert` は
**同一モードでもフルコピーを作る**（実測確認済み）。入力が既に `RGBA` のときこのコピーは丸ごと無駄で、
上限の 16M 画素で 64MB に相当する。

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_cover.py` に追記する。`_rgba` と `_png` は既存のヘルパ。

```python
def test_grayscale_output_is_la_and_composites_to_white():
    """`to_gray_image` は透明を持つ画像を `LA` で返す。グレー書き出しの採色はこの分岐を通る。"""
    from export.grayscale import to_gray_image

    src = _png(_rgba(8, 8, (200, 30, 30), alpha_box=(0, 0, 3, 3)))
    gray_bytes, gray_ext = to_gray_image(src, "png")
    with Image.open(io.BytesIO(gray_bytes)) as g:
        assert g.mode == "LA"
    im = cover.decode_image(gray_bytes, gray_ext)
    assert im is not None and im.mode == "RGB"
    assert im.getpixel((7, 7)) == (255, 255, 255)   # 透明部分 → 白
    assert im.getpixel((0, 0)) != (255, 255, 255)   # 不透明部分 → 灰色が残る


def test_palette_transparency_composites_to_white():
    """透過色を持つパレット画像も白へ合成する (`P` + `transparency`)。"""
    im = Image.new("P", (8, 8), 0)
    im.putpalette([255, 0, 0] + [0, 0, 0] * 255)
    im.info["transparency"] = 0
    decoded = cover.decode_image(_png(im), "png")
    assert decoded is not None
    assert decoded.getpixel((0, 0)) == (255, 255, 255)


def test_alpha_predicate_matches_grayscale():
    """採色側とグレー化側の「透明を持つか」の判定は同じでなければならない。

    `cover.decode_image` と `grayscale.to_gray_image` は同じ条件式を別々に持つ。片方だけ形式を
    足すと、グレー化が `LA` を返すのに採色が合成しない (またはその逆) の食い違いが起きる。
    """
    import inspect

    from export import grayscale

    modes = ("RGBA", "LA", "PA")
    for src in (inspect.getsource(cover.decode_image), inspect.getsource(grayscale.to_gray_image)):
        for mode in modes:
            assert f'"{mode}"' in src
        assert '"transparency" in im.info' in src
```

`pdf-to-svg/test/test_ocr_layer.py` に追記する。

```python
def test_degraded_seqno_index_leaves_text_visible(ocr_layer_pdf, monkeypatch):
    """索引が照合を諦めたら不可視の判定を与えない (可視側へ倒す)。

    このとき OCR 文字は画像の字と二重に描かれる。望ましい状態ではないが、逆へ倒すと degraded
    ページの文字がすべて不可視扱いになり白紙同然で書き出される。どちらへ倒れているかを固定する。
    """
    from engine import pdf_engine

    monkeypatch.setattr(pdf_engine, "_SEQNO_MAX_CANDIDATES", 1)
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    texts = _texts(pg)
    assert set(texts) == {"Header Text", "Body line one", "visible text"}
    assert all(not e.invisible for e in texts.values())
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_cover.py test/test_ocr_layer.py -v`
Expected: `test_palette_transparency_composites_to_white` は現状の実装でも通る（分岐は既にある）。
`test_grayscale_output_is_la_and_composites_to_white` と `test_alpha_predicate_matches_grayscale` も
通るはずである。これらは RED を作れない回帰ガードなので、**ガードとして働くことを確かめる**:
`cover.py` の条件式から `"LA"` を一時的に外すと 1 本目が落ちること、`"PA"` を外すと 3 本目が落ちることを
見て、確かめたら必ず戻す。`test_degraded_seqno_index_leaves_text_visible` も同様に、
`pdf_engine.py` の `set() if text_index.degraded else ...` を `_invisible_seqnos(traces)` へ一時的に
戻しても通る（`match` が `None` を返すため）ので、代わりに `matched is not None and` を外すと落ちることを
見て戻す。確認の経過を報告書へ書くこと。

- [ ] **Step 3: 同一モードの無駄なコピーを避ける**

`pdf-to-svg/src/export/cover.py` の alpha 分岐を次にする。

```python
                # alpha は捨てずに白へ合成する。`convert("RGB")` は合成せず捨てるので、完全に
                # 透明な画素が格納 RGB (RGBA PNG では黒が多い) のまま最頻色を支配し、隠すはずの
                # 矩形が黒い帯になる。部分的に透明な画素は白と混色する (透明度を二値扱いしない)。
                # 白を敷くのは、採色経路が既に置いている「画像の下は紙」と同じ前提である。
                # 既に `RGBA` ならそのまま使う (`convert` は同一モードでもフルコピーを作るため、
                # 上限の 16M 画素では 64MB を無駄に確保することになる)。
                rgba = im if im.mode == "RGBA" else im.convert("RGBA")
                canvas = Image.new("RGB", rgba.size, (255, 255, 255))
                canvas.paste(rgba, mask=rgba.getchannel("A"))
                return canvas
```

`getchannel("A")` は `split()[3]` と同じ結果を返し、意図が読み取りやすい。

- [ ] **Step 4: キャッシュキーの前提をコメントにする**

`pdf-to-svg/src/export/svg_exporter.py` の `_cover_sampler` の中、`image_for` を呼んでラスタ背景を
採色する箇所（キー `-1`）の直前に 1 行足す。

```python
        # ラスタ背景は要素ではないので負のキーを使う (要素 id は `model/elements.py` の
        # `itertools.count(1)` で必ず 1 以上になり、負の値と衝突しない)。
```

- [ ] **Step 5: テストを通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test` と `py -3.13 -m pytest test -m e2e`
Expected: すべて PASS。`decode_image` の挙動は変えていないので既存の期待値も動かない。

- [ ] **Step 6: コミット**

```bash
git add pdf-to-svg/src/export/cover.py pdf-to-svg/src/export/svg_exporter.py pdf-to-svg/test/test_cover.py pdf-to-svg/test/test_ocr_layer.py
git commit -m "test: 採色とグレー化の透明判定・索引が諦めた経路を固定し、同一モードの複製を避ける"
```

---

### Task 2: 角ハンドルの伸縮計算を geometry.js へ集約（束 B のコード）

**Files:**
- Modify: `pdf-to-svg/resources/web/geometry.js`
- Modify: `pdf-to-svg/resources/web/cover.js`、`pdf-to-svg/resources/web/figure.js`
- Test: `pdf-to-svg/test/test_pdftosvg_geometry_js.py`

**Interfaces:**
- Produces: `geometry.js` が `resizeByCorner(orig, corner, p)` と `CORNER_HANDLES_HTML` を追加で
  エクスポートする。

**背景:** 角ハンドルの伸縮計算（掴んだ角を動かし反対の角を固定し、`MIN_SIZE_PT` でクランプする 3 行）と、
4 つのハンドルのマークアップ文字列が `cover.js` と `figure.js` に逐語で重複している。矩形ヘルパを
`geometry.js` へ集約したときと同じ理由で同じ場所へ行くべき候補である。

**設計書が既に食い違っている:** `docs/pdf-to-svg/src/設計書.md` の 8 章は「矩形操作のヘルパは
`geometry.js` から読み、複製しない」「同じ実装として共有する」と書いているが、伸縮計算とハンドルの
マークアップは複製されたまま残っている。放置するなら設計書のほうを直す必要があり、どちらに転んでも
原稿の往復は避けられない。

**唯一の差:** `cover.js` は `d.rect = {新しい矩形}` と置き換えるが、`figure.js` は `d.rect.x = ...` と
その場で書き換える。`figure.js` が採用矩形の箱を `figSelPeek(S.page).indexOf(d.rect)` と同一性で引く
ためである。共有する関数は**新しい矩形を返す純粋関数**にし、`figure.js` 側は `Object.assign(d.rect, ...)`
で受けて同一性を保つ。

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_pdftosvg_geometry_js.py` に追記する。

```python
def test_resizebycorner_moves_the_grabbed_corner(geo):
    """南東を掴んで動かすと、北西は固定されたまま幅と高さが変わる。"""
    assert js(geo, """window.__geo.resizeByCorner(
        {x: 10, y: 10, w: 20, h: 20}, "se", {x: 40, y: 50})""") == {
        "x": 10, "y": 10, "w": 30, "h": 40,
    }


def test_resizebycorner_moves_the_opposite_corner(geo):
    """北西を掴んで動かすと、南東が固定される。"""
    assert js(geo, """window.__geo.resizeByCorner(
        {x: 10, y: 10, w: 20, h: 20}, "nw", {x: 5, y: 5})""") == {
        "x": 5, "y": 5, "w": 25, "h": 25,
    }


def test_resizebycorner_handles_dragging_past_the_opposite_edge(geo):
    """反対の辺を越えて引いても矩形は正の寸法で返る (左右・上下が入れ替わる)。"""
    assert js(geo, """window.__geo.resizeByCorner(
        {x: 10, y: 10, w: 20, h: 20}, "se", {x: 0, y: 0})""") == {
        "x": 0, "y": 0, "w": 10, "h": 10,
    }


def test_resizebycorner_clamps_to_the_minimum_size(geo):
    """掴んだ角を反対の角へ寄せきっても `MIN_SIZE_PT` より小さくしない。"""
    assert js(geo, """window.__geo.resizeByCorner(
        {x: 10, y: 10, w: 20, h: 20}, "se", {x: 10, y: 10})""") == {
        "x": 10, "y": 10, "w": 4, "h": 4,
    }


def test_corner_handles_html_has_four_corners(geo):
    assert js(geo, """(() => {
        const d = document.createElement("div");
        d.innerHTML = window.__geo.CORNER_HANDLES_HTML;
        return Array.from(d.querySelectorAll(".h")).map(e => e.dataset.corner);
    })()""") == ["nw", "ne", "sw", "se"]
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pdftosvg_geometry_js.py -v`
Expected: 新しい 5 本が FAIL（`window.__geo.resizeByCorner` などが `undefined`）。既存は PASS。

- [ ] **Step 3: `geometry.js` へ足す**

`clampToPage` の隣に置く。

```js
/** 掴んだ角 `corner` を点 `p` へ動かしたときの矩形。反対の角は固定し、`MIN_SIZE_PT` より小さくしない。
 *  新しい矩形を返す純粋関数にしてあるのは、呼び出し側で同一性を保ちたい場合 (`figure.js` は
 *  採用矩形の箱を配列の同一性で引く) に `Object.assign` で受けられるようにするため。 */
export function resizeByCorner(orig, corner, p) {
  var left = corner.indexOf("w") >= 0 ? p.x : orig.x;
  var right = corner.indexOf("e") >= 0 ? p.x : orig.x + orig.w;
  var top = corner.indexOf("n") >= 0 ? p.y : orig.y;
  var bottom = corner.indexOf("s") >= 0 ? p.y : orig.y + orig.h;
  return {
    x: Math.min(left, right),
    y: Math.min(top, bottom),
    w: Math.max(MIN_SIZE_PT, Math.abs(right - left)),
    h: Math.max(MIN_SIZE_PT, Math.abs(bottom - top)),
  };
}

// 角ハンドル 4 つのマークアップ。伸縮の当たり判定は `.h` の `data-corner` で拾う。
export var CORNER_HANDLES_HTML =
  '<span class="h nw" data-corner="nw"></span><span class="h ne" data-corner="ne"></span>' +
  '<span class="h sw" data-corner="sw"></span><span class="h se" data-corner="se"></span>';
```

`x` と `y` を `Math.min` で取るため、反対の辺を越えて引いても正の寸法になる（既存の挙動と同じ）。

- [ ] **Step 4: 両方の呼び出し側を差し替える**

`cover.js`: import へ `resizeByCorner` と `CORNER_HANDLES_HTML` を足す。ハンドルの文字列を
`CORNER_HANDLES_HTML` に置き換える。伸縮の枝を次にする。

```js
    } else {
      var p = clientToPage(svgEl, e.clientX, e.clientY);
      p.x = Math.max(0, Math.min(p.x, sz.w)); p.y = Math.max(0, Math.min(p.y, sz.h));
      d.rect = resizeByCorner(d.orig, d.corner, p);
    }
```

`figure.js`: 同じ import を足し、ハンドルの文字列を置き換え、伸縮の枝を次にする。`d.rect` の同一性を
保つため `Object.assign` で受ける。

```js
    // `d.rect` は採用矩形そのもの (`figSelPeek` が同一性で箱を引く) なので、置き換えず中身を書く。
    Object.assign(d.rect, resizeByCorner(d.orig, d.corner, p));
```

`MIN_SIZE_PT` が両ファイルで他に使われていなければ import から外す（`figure.js` は空白ドラッグの
下限judgeでも使っているはずなので、現物を確認してから外すこと）。

- [ ] **Step 5: テストを通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pdftosvg_geometry_js.py -v`
Expected: 新規 5 本を含め全 PASS。

Run: `cd pdf-to-svg; py -3.13 -m pytest test` と `py -3.13 -m pytest test -m e2e`
Expected: すべて PASS。手順 3 の上書きの伸縮と手順 4 の採用矩形の伸縮を見る既存 E2E が、
差し替えで壊れていないことの確認になる。

- [ ] **Step 6: コミット**

```bash
git add pdf-to-svg/resources/web/geometry.js pdf-to-svg/resources/web/cover.js pdf-to-svg/resources/web/figure.js pdf-to-svg/test/test_pdftosvg_geometry_js.py
git commit -m "refactor(ui): 角ハンドルの伸縮計算とマークアップを geometry.js へ集約する"
```

---

### Task 3: 原稿を実態へ揃えて HTML を再生成する（束 B の文書）

**Files:**
- Modify: `docs/pdf-to-svg/src/設計書.md`
- Generate: `docs/pdf-to-svg/pdf-to-svg_設計.html`、`docs/pdf-to-svg/pdf-to-svg_手引き.html`

**書く前に:** 対象の実装を読むこと。原稿の記述は実装が正である。原稿は published canon であり、
丁寧な日本語の散文で書く。既存の語り口・見出しの深さ・表の形・識別子のバッククォートの流儀に合わせる。
日付・経緯・内部のタスク番号は本文に書かない（front matter の `rev:` への 1 行追加は例外で、必要）。

- [ ] **Step 1: 設計書 8 章**

`resources/web/` のファイル表と周辺の記述で、`geometry.js` が持つものに角ハンドルの伸縮計算
（`resizeByCorner`）とハンドルのマークアップ（`CORNER_HANDLES_HTML`）を加える。「矩形操作のヘルパは
`geometry.js` から読み、複製しない」という既存の記述が、今回の集約で初めて字義どおり真になったので、
伸縮計算まで含むことが読み取れる書き方にする。

`figure.js` 側が `Object.assign` で受ける理由（採用矩形の箱を配列の同一性で引くため、矩形を置き換えず
中身を書く）を 1 文添える。共有関数が新しい矩形を返す純粋関数である理由がこれである。

- [ ] **Step 2: 仕様一覧のテスト表**

`docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md` のテスト表へ、本計画で足した観点の行を既存の形に合わせて
足す（透明を持つ他形式の採色と判定のずれ検出、索引が諦めたときの抽出、角ハンドルの伸縮計算）。

- [ ] **Step 3: HTML を再生成して差分を確かめる**

Run: `py -3.13 docs/_build/build_all.py --project pdf-to-svg`
Expected: `[ok]` が 2 枚。`git status` で 2 枚に差分が出る。

Run: `py -3.13 -m pytest docs/_build -q`
Expected: PASS。

- [ ] **Step 4: コミット**

```bash
git add docs/pdf-to-svg
git commit -m "docs(pdf-to-svg): 角ハンドルの伸縮計算の集約と新しいテストの観点を原稿へ反映し HTML を再生成する"
```

- [ ] **Step 5: リリースを差し替える**

これは実装者の担当ではない。controller が行う。

---

## Self-Review

- **Task 1 の 3 本はいずれも RED を作れない回帰ガード**である。ガードとして働くことの確認手順を Step 2 に
  具体的に書いた（何を一時的に外すと何が落ちるか）。確認したら必ず戻すこと。
- Task 1 の `decode_image` の変更は挙動を変えない。同一モードのときコピーを省くだけで、合成の結果は同じ。
  既存の期待値はすべて不透明な画像なので影響しない。
- Task 2 は挙動を変えない移動である。ただし `figure.js` の受け方だけは `Object.assign` へ変える必要があり、
  ここを素直に代入へ置き換えると採用矩形の箱が引けなくなって伸縮が画面へ反映されなくなる。Step 4 に
  理由ごと明記した。
- Task 3 は Task 2 の後に置く。Task 2 を実施しない判断になった場合、設計書 8 章の「複製しない」という
  記述は嘘のままなので、代わりに「伸縮計算とハンドルのマークアップは各モジュールが持つ」へ直す必要がある。
- 調査で「却下」と判断した項目（`_cover_sampler` の引数を狭める案）は本計画に含めない。現形は設計書の
  説明と対応が取れており、狭めると原稿も触ることになる。
- 調査が繰延 7 件の外で見つけた 1 件（デコード済み画像を 1 回の書き出しの間に枚数無制限で保持する）は
  本計画に含めない。発火に利用者の操作が要り、現実のスキャンページは画像 1 枚である。
