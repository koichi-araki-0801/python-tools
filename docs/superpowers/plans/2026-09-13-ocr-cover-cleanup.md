# 不可視 OCR 文字層の上書き描画 残作業の解消（トラック A） 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 不可視 OCR 文字層の上書き描画で残った不具合 2 件を直し、テストの取りこぼし 2 件を塞ぎ、捨てられる計算 3 箇所を省く。

**Architecture:** どれも既存の経路へ局所的に手を入れる。グレー書き出しの採色は、採る画像そのものを書き出しと同じ変換に通してから採ることで、矩形と周囲が構造的に一致するようにする。透明画像の採色は白へ合成してから行う。テストは共有セッションの汚染を断つ方向へ寄せる。

**Tech Stack:** Python 3.13 / Pillow / pytest / Playwright（Edge）/ 素の JavaScript。

**Spec:** 本計画が正典。設計の根拠は `docs/pdf-to-svg/src/設計正典.md` の「不可視 OCR 文字層」「グレー化・切り出しは exporter のオプション」の 2 項。

**文書の扱い:** 本トラックのコード変更に伴う原稿・HTML・リリースの更新は**行わない**。トラック B
（`2026-09-13-rect-helpers-to-geometry.md`）の最終タスクでまとめて 1 回払う。トラック B を実施
しない判断になった場合は、本計画の末尾の「トラック B を実施しない場合」を実行する。

## Global Constraints

- Python は常に `py -3.13`。pytest は `pdf-to-svg/` の中から `py -3.13 -m pytest test/...` の形で実行する（リポジトリ直下での素の `pytest` は禁止。姉妹プロジェクトに同名のテストモジュールがある）。
- `fitz`（PyMuPDF）を import してよいのは `src/engine/pdf_engine.py` と `src/engine/classify.py` だけ。
- SVG 属性は `svg_exporter._attr` / `_paint` 経由でのみ書く。f-string で `="{...}"` を組まない（`test/test_export_escaping.py` が機械検査する）。
- 不可視文字を持たない PDF の出力は 1 バイトも変えない（`test/test_pipeline.py` ほかが固定）。
- グレー書き出しを既定 OFF のまま通した場合の出力も従来とバイト一致（`test/test_export_clip.py`）。
- 攻撃者が用意できる入力（PDF の画像、RPC 引数）は上限を置き、例外ではなく degrade へ倒す。degrade した件数は利用者へ返す。
- コメントは日本語の散文、識別子はバッククォート、理由は現在形。日付・経緯・内部のタスク番号を書かない（`docs/コメント規約.md`。pre-commit が `scripts/check_comments.py --staged` で検査する）。
- コミットすると post-commit が auto-push し、pre-push が検証一式（約 2 分）を回す。`--no-verify` を使わない。force push もしない。
- コミットメッセージは日本語の Conventional Commits。本文の末尾に次の 2 行を置く。

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_0126DHJZ8WfffcXsMqETHsLc
  ```

## File Structure

| ファイル | 変更 | 責務 |
|---|---|---|
| `pdf-to-svg/src/export/svg_exporter.py` | 変更 | `_cover_sampler` が書き出しモードと同じ画像から採色する。`_cover_svg` は採色済みの色を再変換しない。`live_elements()` の重複呼び出しを畳む |
| `pdf-to-svg/src/export/cover.py` | 変更 | `decode_image` が alpha を白へ合成する |
| `pdf-to-svg/src/engine/pdf_engine.py` | 変更 | `_text_element` の docstring に `invisible` を足す。索引が照合を諦めたら不可視 seqno を集めない |
| `pdf-to-svg/test/test_cover.py` | 変更 | 透明画像の採色 |
| `pdf-to-svg/test/test_ocr_layer.py` | 変更 | グレー書き出しで矩形と画像の灰色が一致する |
| `pdf-to-svg/test/test_web_rpc.py` | 変更 | 削除済みの上書きへの `updateCover` を拒否する |
| `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` | 変更 | `reset_session` が辞書も空にする。辞書件数の断言を完全一致へ締める |

パスはすべて `C:\Users\caads\python-tools` からの相対。

---

### Task 1: グレー書き出しで上書き矩形を周囲と同じ灰色にする

**Files:**
- Modify: `pdf-to-svg/src/export/svg_exporter.py`（`page_to_svg` の `sampler` 生成箇所、`_cover_sampler`、`_cover_svg`、要素ループの `_cover_svg` 呼び出し）
- Test: `pdf-to-svg/test/test_ocr_layer.py`

**Interfaces:**
- Consumes: `grayscale.to_gray_image(img_bytes, ext) -> (bytes, ext)`、`cover.decode_image` / `cover.sample_colors`
- Produces: `_cover_sampler(page, image_fn) -> Callable[[TextElement], cover.CoverColors]`（引数が 1 つ増える）。`_cover_svg(el, colors) -> str`（`color_fn` 引数が無くなる）

**背景（実装前に読むこと）:** 現状、上書き矩形の塗りは `color_fn`（グレー時は `to_gray_color`）を通る。
`to_gray_color` は `SMTAM_MONO_COLORS` の対応表を先に引き、外れたら輝度変換する。一方その下の画像は
`to_gray_image` を通り、有彩色なら輝度変換に加えて `tone_curve`（ガンマ 0.8）が掛かる。式が違うので、
矩形だけが周囲より暗く出る。対応表に当たれば大きく外れる。

グレーのチェックは手順 1 にあり、手順 1 はグレーモードでも開ける。ステップバーは前の手順へ戻れる。
切替ハンドラは SVG のキャッシュを捨てるだけで文書も上書きも消さない。よって「カラーで上書きを置く →
手順 1 へ戻る → グレーへ切替 → 書き出す」で到達する。

**直し方:** 採る画像そのものを書き出しと同じ変換（`image_fn`）に通してから採色する。採れた色は既に
出力モードの色なので、`_cover_svg` では再変換せず `sanitize_color` だけを通す。

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_ocr_layer.py` に追記する。`ocr_layer_pdf` の帯は有彩色 `(200, 220, 240)` なので
`to_gray_image` の `tone_curve` が掛かる対象である。

```python
def test_grayscale_cover_matches_the_grayscaled_image(ocr_layer_pdf, tmp_path):
    """グレー書き出しでは、矩形の灰色は「グレー化した画像」から採った色と一致する。

    採色を元のカラー画像から行うと、矩形は輝度変換だけ・画像は `tone_curve` も掛かるため、
    矩形だけが暗い当て板になる。
    """
    import io

    from PIL import Image

    from export.grayscale import to_gray_image

    pg = load_document(str(ocr_layer_pdf)).pages[0]
    _replace(pg, tmp_path, "Header Text", "見出し")
    el = _texts(pg)["見出し"]
    img = next(e for e in pg.live_elements() if e.kind == "image")

    # 期待値: 書き出しに乗るのと同じ灰色画像から、同じ領域を採色した色
    gray_bytes, gray_ext = to_gray_image(img.img_bytes, img.ext)
    expected = cover.sample_colors(cover.decode_image(gray_bytes, gray_ext), img.rect, el.bbox)

    line = _line_with(page_to_svg(pg, grayscale=True), "見出し")
    assert f'fill="{expected.background}"' in line.split("<text")[0]
    assert f'fill="{expected.foreground}"' in line.split("<text")[1]


def test_color_cover_is_unchanged_by_the_grayscale_fix(ocr_layer_pdf, tmp_path):
    """カラー書き出しの採色は従来どおり元画像から採る (帯色 `#c8dcf0`)。"""
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    _replace(pg, tmp_path, "Header Text", "見出し")
    line = _line_with(page_to_svg(pg), "見出し")
    assert 'fill="#c8dcf0"' in line.split("<text")[0]
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_ocr_layer.py -k grayscale_cover -v`
Expected: FAIL。矩形の塗りが `to_gray_color` 由来の値になっており、期待値と一致しない。

- [ ] **Step 3: 採色元を書き出しモードへ合わせる**

`_cover_sampler` の署名と本体を次にする。

```python
def _cover_sampler(page: Page, image_fn: ImageFn) -> Callable[[TextElement], cover.CoverColors]:
    """要素の bbox の下にある画像 (z 最大の `ImageElement` → スキャン背景の順) から採色する。

    採る前に画像を `image_fn` へ通すのは、矩形の色を**書き出しに乗る画像**から採るためである
    (グレー書き出しで元のカラー画像から採ると、矩形は輝度変換だけ・画像は `tone_curve` も
    掛かるため、矩形だけが暗い当て板になる)。デコードは 1 回の書き出しの中で画像ごと 1 度。
    """
    images = sorted(
        (e for e in page.live_elements() if isinstance(e, ImageElement)), key=lambda e: -e.z
    )
    decoded: Dict[int, Optional[object]] = {}  # 値は Pillow の Image (型は cover.py に閉じる)

    def image_for(key: int, data: bytes, ext: str):
        if key not in decoded:
            decoded[key] = cover.decode_image(*image_fn(data, ext))
        return decoded[key]
    ...
```

以降の `sample` は変更しない。

`_cover_svg` から `color_fn` を外し、採色済みの色は `sanitize_color` だけを通す。

```python
def _cover_svg(el: TextElement, colors: cover.CoverColors) -> str:
    """不可視・置換済みの文字: 背景色の矩形で元の字面を隠し、その上に置換語を描く。

    色は `_cover_sampler` が**書き出しに乗る画像**から採った値なので、ここで
    `color_fn` を通さない (通すと灰色をもう一度灰色化することになり、周囲とずれる)。
    `<g>` で包むのは `_with_data_el` が 1 要素 1 開きタグを前提にするためである。
    """
```

本体の `_attr("fill", color_fn(colors.background))` を `_attr("fill", sanitize_color(colors.background))`
に、`_text_to_svg(el, color_fn, fill=colors.foreground, edited=True)` を
`_text_to_svg(el, sanitize_color, fill=colors.foreground, edited=True)` にする。

`page_to_svg` 内の `sampler = _cover_sampler(page)` を `sampler = _cover_sampler(page, image_fn)` に、
`svg = _cover_svg(el, colors, color_fn)` を `svg = _cover_svg(el, colors)` にする。

- [ ] **Step 4: テストを通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_ocr_layer.py test/test_export_clip.py test/test_pipeline.py test/test_grayscale.py -v`
Expected: すべて PASS。`test_grayscale_converts_cover_colors`（既存）は「有彩色が残らない」ことだけを
見ているので、採色元が変わっても通る。通らない場合は期待値が対応表の値に固定されていないか確認する。

- [ ] **Step 5: コミット**

```bash
git add pdf-to-svg/src/export/svg_exporter.py pdf-to-svg/test/test_ocr_layer.py
git commit -m "fix(export): グレー書き出しの上書き矩形を書き出し後の画像から採色し周囲と揃える"
```

---

### Task 2: 透明部分を持つ画像の採色を白へ合成してから行う

**Files:**
- Modify: `pdf-to-svg/src/export/cover.py`（`decode_image`）
- Test: `pdf-to-svg/test/test_cover.py`

**Interfaces:**
- Consumes: なし（Task 1 と独立）
- Produces: `decode_image` の戻り値は従来どおり RGB の Pillow 画像または `None`。挙動だけが変わる

**背景:** `decode_image` は `im.convert("RGB")` で alpha を捨てる。Pillow は合成せず捨てるので、
完全に透明な画素は格納されている RGB（RGBA PNG では黒が多い）のまま残る。その結果、透明部分の多い
画像の上では最頻色が黒になり、隠すはずの矩形が黒い帯として目立つ。

**合成先を白に固定する理由:** ページは白紙であり、`_cover_sampler` は bbox 中心を含む画像 1 枚しか
見ない（下にある塗り矩形は見ていない）。白は「画像の下は紙」という、採色経路が既に置いている前提と
同じである。前提を変えずに、透明画素を利用者の目に映る色へ寄せる。

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_cover.py` に追記する。

```python
def _rgba(w: int, h: int, color, alpha_box=None) -> Image.Image:
    """`alpha_box` (x0, y0, x1, y1) の内側だけ不透明、外は完全透明の RGBA 画像。"""
    im = Image.new("RGBA", (w, h), color + (0,))
    if alpha_box is not None:
        x0, y0, x1, y1 = alpha_box
        for x in range(x0, x1):
            for y in range(y0, y1):
                im.putpixel((x, y), color + (255,))
    return im


def test_transparent_pixels_composite_onto_white():
    """透明画素は格納 RGB ではなく白として数える (合成せずに捨てると黒い当て板になる)。"""
    im = cover.decode_image(_png(_rgba(8, 8, (0, 0, 0), alpha_box=(0, 0, 2, 2))), "png")
    assert im is not None and im.mode == "RGB"
    assert im.getpixel((7, 7)) == (255, 255, 255)   # 透明部分 → 白
    assert im.getpixel((0, 0)) == (0, 0, 0)         # 不透明部分 → そのまま


def test_mostly_transparent_image_samples_white_background():
    """透明が多数派の画像では背景色が白になる (黒い矩形で隠さない)。"""
    im = cover.decode_image(_png(_rgba(8, 8, (0, 0, 0), alpha_box=(0, 0, 2, 2))), "png")
    c = cover.sample_colors(im, Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    assert c.background == "#ffffff"
    assert c.fallback is False
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_cover.py -k transparent -v`
Expected: FAIL。透明部分が `(0, 0, 0)` のまま残り、背景色が `#000000` になる。

- [ ] **Step 3: 合成してから RGB へ**

`decode_image` の `return im.convert("RGB")` を次に置き換える。

```python
            if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
                # alpha は捨てずに白へ合成する。`convert("RGB")` は合成せず捨てるので、完全に
                # 透明な画素が格納 RGB (RGBA PNG では黒が多い) のまま最頻色を支配し、隠すはずの
                # 矩形が黒い帯になる。白を敷くのは、採色経路が既に置いている「画像の下は紙」と
                # 同じ前提である。
                rgba = im.convert("RGBA")
                canvas = Image.new("RGB", rgba.size, (255, 255, 255))
                canvas.paste(rgba, mask=rgba.split()[3])
                return canvas
            return im.convert("RGB")
```

- [ ] **Step 4: テストを通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_cover.py test/test_ocr_layer.py -v`
Expected: すべて PASS。

- [ ] **Step 5: コミット**

```bash
git add pdf-to-svg/src/export/cover.py pdf-to-svg/test/test_cover.py
git commit -m "fix(export): 透明部分を持つ画像の採色を白へ合成してから行う"
```

---

### Task 3: テストの取りこぼしを塞ぐ

**Files:**
- Modify: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`（`reset_session`、辞書件数の断言）
- Modify: `pdf-to-svg/test/test_web_rpc.py`（削除済みの上書きへの `updateCover`）

**Interfaces:**
- Consumes: RPC `dictList` / `dictDelete`（`{entries: [{id, ...}]}` / `{id}`）、`applyDelete`、`updateCover`
- Produces: なし（テストのみ）

**背景 1:** `reset_session` は読み込み済みファイルしか消さない。辞書は共有セッションに残り続ける。
現在の後始末はテスト末尾の `dictDelete` だけで、アサートが落ちると実行されない。同じファイルの
`test_four_step_flow` と `test_list_fetch_failure_clears_rows_and_offers_retry` は後始末を一切していない。
`test_four_step_flow` の辞書件数の断言は部分一致なので、`11` 件でも `1` として通る。つまり現在この
汚染は検出できていない。

**背景 2:** `updateCover` は削除済みの上書きを `_manual_cover` の `not e.deleted` で弾き `ValueError` を
投げる。この挙動を固定するテストが無い。UI は通常この経路へ届かないが、Undo でオーバーレイが古い
`elId` を握ったまま操作すると届く。サーバは拒否のままにする（他の不正な `elId` と同じ扱いで、黙って
何もしないより原因が見える）。

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_web_rpc.py` の `updateCover` のテスト群の直後に追記する。

```python
def test_update_cover_rejects_a_deleted_cover(session):
    """削除した上書きは `updateCover` の対象にならない (Undo でオーバーレイが古い id を
    握ったまま操作しても、消えた要素を書き換えない)。"""
    el_id = rpc_methods.dispatch(
        session, "addCover", _cover_args(rect={"x": 10, "y": 100, "w": 80, "h": 20}, text="A")
    )["elId"]
    rpc_methods.dispatch(session, "applyDelete", _cover_args(elIds=[el_id]))
    with pytest.raises(ValueError):
        rpc_methods.dispatch(session, "updateCover", _cover_args(elId=el_id, text="B"))
```

`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` の `reset_session` を次にする。

```python
# サーバのセッション(開いている文書・辞書・Undo)はテスト間で共有される。各テストは自分が
# 前提とする構成を作れるよう、先に文書と辞書を空にする。辞書をテスト末尾で消す形にすると、
# アサートが落ちたときに実行されず、次のテストへ語が漏れる。
def reset_session(page):
    page.evaluate("""async () => {
        const w = window;
        for (let i = 0; i < 20; i++) {
            const st = await w.rpc("state");
            if (!st.files.length) break;
            await w.rpc("removeFile", { fileIndex: 0 });
        }
        const dict = await w.rpc("dictList");
        for (const e of dict.entries) await w.rpc("dictDelete", { id: e.id });
    }""")
```

`test_four_step_flow` の辞書件数の断言を完全一致へ締める（汚染が残れば落ちるようにする）。

```python
    expect(page.locator("#dict-count")).to_have_text("1")
```

（`#dict-count` の実際の表示が `1` そのものでない場合は、現物の文字列に合わせて完全一致で書く。）

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_web_rpc.py -k deleted_cover -v`
Expected: FAIL（テスト未追加の状態なら収集されない。追加後は実装済みのため PASS になる。この 1 本は
回帰ガードであり RED を作れない。ガードとして機能することは、`rpc_methods.py` の `_manual_cover` から
`and not e.deleted` を一時的に外すと落ちることで確かめ、確かめたら必ず戻す）。

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pdftosvg_app_flow_e2e.py -m e2e -v`
Expected: 既存分を含め PASS。`to_have_text` へ締めた断言が落ちる場合は、`#dict-count` の実表示に
合わせて期待値を直す。

- [ ] **Step 3: 全体を回す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test` と `py -3.13 -m pytest test -m e2e`
Expected: すべて PASS。

- [ ] **Step 4: コミット**

```bash
git add pdf-to-svg/test/test_web_rpc.py pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py
git commit -m "test: 共有セッションの辞書をテスト冒頭で空にし、削除済み上書きの拒否を固定する"
```

---

### Task 4: 捨てられる計算を省く

**Files:**
- Modify: `pdf-to-svg/src/export/svg_exporter.py`（`page_to_svg` / `_cover_sampler`）
- Modify: `pdf-to-svg/src/engine/pdf_engine.py`（`_extract_page` / `_text_element`）

**Interfaces:**
- Consumes: Task 1 が変えた `_cover_sampler(page, image_fn)`
- Produces: `_cover_sampler(elements, image_fn, background)`（ページではなく確定済みの要素列を受け取る）

**背景:** どれも結果が捨てられる計算であり、速さを狙う変更ではない。`page.live_elements()` は呼ぶたびに
絞り込みと並べ替えをやり直すが、`page_to_svg` の中で 3 回呼ばれ、その間に要素リストは変わらない。
`_invisible_seqnos(traces)` は索引が照合を諦めた（`degraded`）ときに結果が一度も参照されない。

測定はしない。捨てられる作業を省くだけで、出力は 1 バイトも変わらないことをテストが固定している。

- [ ] **Step 1: 出力不変を先に固定する**

既存のテストがこれを担う。変更前に基準を取っておく。

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pipeline.py test/test_export_clip.py test/test_image_clip.py test/test_ocr_layer.py test/test_seqno_match.py -v`
Expected: すべて PASS（変更前の基準）。

- [ ] **Step 2: `live_elements()` を 1 回に畳む**

`page_to_svg` の中で、画像クリップの `<defs>` を集めるループの手前に 1 行置く。

```python
    # 要素列はこの関数の中で変わらないので 1 度だけ確定させる (`live_elements` は呼ぶたびに
    # 絞り込みと並べ替えをやり直す)。
    live = page.live_elements()
```

`<defs>` 収集ループ・主ループの `for el in page.live_elements():` を `for el in live:` にする。
`_cover_sampler` は確定済みの要素列を受け取る形へ変える。

```python
def _cover_sampler(
    live: List[Element], image_fn: ImageFn, background: Optional[RasterBackground]
) -> Callable[[TextElement], cover.CoverColors]:
```

本体の `images = sorted((e for e in page.live_elements() if ...), ...)` を
`images = sorted((e for e in live if ...), ...)` に、`bg = page.background` を `bg = background` にする。
呼び出しは `sampler = _cover_sampler(live, image_fn, page.background)`。

`Element` と `RasterBackground` の import を足す（`RasterBackground` は `model.document` にある。
`model.document` は `model.elements` しか読まないので循環しない）。

- [ ] **Step 3: 索引が諦めたら不可視 seqno を集めない**

`pdf-to-svg/src/engine/pdf_engine.py` の `_extract_page` で、`invisible_seqnos` を作る行を
`_SeqnoIndex` の構築より後ろへ移し、次にする。

```python
    # 索引が照合を諦めたときは `match` が常に既定値を返し、不可視の判定は一度も使われない。
    # 集合を作る作業ごと省く (上限に当たったら諦める、という索引側の規律に揃える)。
    invisible_seqnos = set() if text_index.degraded else _invisible_seqnos(traces)
```

- [ ] **Step 4: docstring に `invisible` を足す**

`_text_element` の docstring の末尾に 1 行足す。

```python
    ``invisible`` は文字を描かない描画モード (3 / 7) で出力された span か。
```

- [ ] **Step 5: 出力が変わっていないことを確かめる**

Run: `cd pdf-to-svg; py -3.13 -m pytest test` と `py -3.13 -m pytest test -m e2e`
Expected: すべて PASS。1 件でも落ちたら、畳んだ `live` を要素の追加後に参照していないか確認する。

- [ ] **Step 6: コミット**

```bash
git add pdf-to-svg/src/export/svg_exporter.py pdf-to-svg/src/engine/pdf_engine.py
git commit -m "refactor: 書き出しと抽出で捨てられる計算を省く"
```

---

## トラック B を実施しない場合

トラック B（`2026-09-13-rect-helpers-to-geometry.md`）を見送る判断になったときは、本トラックの
コード変更だけを対象に、次を 1 コミットで行う。

- `docs/pdf-to-svg/src/設計正典.md`: 「グレー化・切り出しは exporter のオプション」の項へ、上書き矩形の
  色は**書き出しに乗る画像**から採る（元のカラー画像から採ると矩形だけが暗くなる）ことを 1 文足す。
- `docs/pdf-to-svg/src/設計書.md` 5.1 節: `_cover_sampler` が `image_fn` を通してから採ること、
  `_cover_svg` が採色済みの色を再変換しないこと、`decode_image` が alpha を白へ合成すること。
- `docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`: テスト表へ本計画で足した観点の行。
- `py -3.13 docs/_build/build_all.py --project pdf-to-svg` で HTML を再生成し、`py -3.13 -m pytest docs/_build -q` を通す。
- リリース `2026.09.08` を現在の `main` へ差し替える（`git tag -f` → `git push origin -f refs/tags/2026.09.08` → `gh release edit` でノートへ追記）。

## Self-Review

- **Task 1** はグレー書き出しの出力を意図的に変える。カラー書き出しの出力は変わらないことを
  `test_color_cover_is_unchanged_by_the_grayscale_fix` と `test_pipeline.py` が固定する。
- **Task 2** は不透明な画像の採色を変えない（`convert("RGB")` の経路をそのまま残す）。既存の
  `test_cover.py` の期待値はすべて不透明画像なので影響しない。
- **Task 3** の 1 本は RED を作れない回帰ガードである。ガードとして働くことの確認手順を Step 2 に書いた。
- **Task 4** は Task 1 が変えた `_cover_sampler` の署名をさらに変える。Task 1 を先に入れること。
- 型の整合: `_cover_sampler` は Task 1 で `(page, image_fn)`、Task 4 で `(live, image_fn, background)` に
  なる。`_cover_svg` は Task 1 で `color_fn` を失う。`page_to_svg` の呼び出しを両方で直すこと。
