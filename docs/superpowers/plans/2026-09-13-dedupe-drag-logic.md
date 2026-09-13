# ドラッグ矩形のロジック重複の解消と、それが隠していた不具合の修正 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 手順 3 と手順 4 の 2 つのオーバーレイが同じ決定を別々に持っている状態を解消する。重複が既に
食い違っており、そのせいで「上書きツールでページの端をまたいでドラッグすると何も起きない」という
利用者に見える不具合が出ている。併せてサーバ側の矩形検査の不統一も揃え、残っていた繰延項目を片付ける。

**Architecture:** 共有できる決定は `resources/web/geometry.js` へ寄せる（ドラッグ結果の矩形の確定、
角ハンドルの伸縮のドラッグ配線）。手順 4 が矩形の同一性に依存している制約は、配列の添字を持ち回る形へ
変えて取り除く。これで両オーバーレイの形が揃い、共有が成立する。サーバ側は 3 通りある矩形の受け取りを
`_parse_rect_arg` の 1 本へ寄せ、ページ内を要求するかどうかだけを引数で分ける。

**Tech Stack:** 素の JavaScript（ES modules）/ Python 3.13 / pytest + Playwright（Edge）。

**Spec:** 本計画が正典。重複の洗い出し結果を各タスクへ埋め込んである。

## Global Constraints

- Python は常に `py -3.13`。pytest は `pdf-to-svg/` の中から `py -3.13 -m pytest test/...` の形で実行する。
- `fitz` を import してよいのは `src/engine/` だけ。SVG 属性は `_attr` / `_paint` 経由でのみ書く。
- 手順 3（選択 / 範囲削除 / 枠線 / 上書き）と手順 4（図の採用・伸縮）の**利用者から見た挙動**は、本計画が
  明示的に直す 1 点（ページ外へはみ出したドラッグ）を除いて変えない。
- 外部由来の入力（RPC 引数）は検査し、拒否は `ValueError` で返す。
- ブラウザの `alert` / `prompt` / `confirm` は使わない。
- コメントは日本語の散文、識別子はバッククォート、理由は現在形。日付・経緯・内部のタスク番号を書かない
  （`docs/コメント規約.md`）。`.js` は `// ===` の装飾ボックスヘッダを保つ。
- **消してはならない重複**: `src/web/origin_guard.py` と graph-editor `src/app.py` の並行実装（drift 検査が
  守っている）、`src/engine/pdf_engine.py` の `MAX_RASTER_PIXELS`（`fitz` を import するモジュールにあり
  他から読めない）。本計画はどちらにも触れない。
- コミットすると post-commit が auto-push し、pre-push が検証一式（約 2 分）を回す。`--no-verify` を
  使わない。force push もしない。
- コミットメッセージは日本語の Conventional Commits。本文の末尾に次の 2 行を置く。

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_0126DHJZ8WfffcXsMqETHsLc
  ```

## File Structure

| ファイル | 変更 | 責務 |
|---|---|---|
| `pdf-to-svg/resources/web/geometry.js` | 変更 | ドラッグ結果の矩形の確定を持つ |
| `pdf-to-svg/resources/web/app.js` | 変更 | 共有した確定処理を使う |
| `pdf-to-svg/resources/web/figure.js` | 変更 | 矩形の同一性への依存を捨て、添字で引く |
| `pdf-to-svg/resources/web/cover.js` | 変更 | 共有した伸縮のドラッグ配線を使う |
| `pdf-to-svg/src/web/rpc_methods.py` | 変更 | 矩形の受け取りを 1 本へ寄せる |
| `pdf-to-svg/test/test_pdftosvg_geometry_js.py` | 変更 | 共有した処理の単体 |
| `pdf-to-svg/test/test_web_rpc.py` | 変更 | 矩形検査の適用範囲 |
| `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` | 変更 | 端をまたぐドラッグ、重複した読み取りの集約 |
| `pdf-to-svg/test/test_resource_limits.py` | 変更 | 対で保守する定数の等値 |
| `docs/pdf-to-svg/src/*.md` + 生成 HTML | 変更 | 実態への反映（最終タスク） |

パスはすべて `C:\Users\caads\python-tools` からの相対。

---

### Task 1: ページの端をまたぐ上書きドラッグが無反応になる不具合を直す

**Files:**
- Modify: `pdf-to-svg/resources/web/geometry.js`、`pdf-to-svg/resources/web/app.js`
- Test: `pdf-to-svg/test/test_pdftosvg_geometry_js.py`、`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`

**背景（実測で確認済み）:**

ドラッグの結果を矩形に変える決定が 2 箇所にある。

- `figure.js` の `installFigDrag` の mouseup は、`clampToPage` でページ内へ収め、`MIN_SIZE_PT` で下限を見る。
- `app.js` の `installCropDrag` の mouseup は、収める処理を持たず、下限を `4` という数値で直接書いている。

この 2 つは既に食い違っている。サーバの `_parse_rect_arg` はページ外の矩形を拒否するので、上書きツールで
ページの端をまたいでドラッグすると `addCover` が `ValueError` になる。mouseup ハンドラに受け止めが無く、
`app.js` は未処理の拒否を拾う仕組みも持たないため、**利用者には成功も失敗も見えない**。上書きが置かれない
だけで、理由が分からない。

枠線と範囲削除は同じ経路を通るが、サーバ側が矩形を検査していないため表に出ない（その不統一は Task 3 で
直す）。

**直し方:** ドラッグ結果の確定を `geometry.js` の 1 つの関数へ寄せ、両方の mouseup がそれを使う。

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_pdftosvg_geometry_js.py` に追記する。

```python
def test_rectfromdrag_clamps_to_the_page(geo):
    """ページの外まで引いた矩形はページ内へ収まる。"""
    assert js(geo, """window.__geo.rectFromDrag(
        {x: 250, y: 150}, {x: 400, y: 300}, {w: 300, h: 200})""") == {
        "x": 250, "y": 150, "w": 50, "h": 50,
    }


def test_rectfromdrag_normalizes_the_direction(geo):
    """右下から左上へ引いても同じ矩形になる。"""
    a = js(geo, "window.__geo.rectFromDrag({x: 10, y: 10}, {x: 60, y: 40}, {w: 300, h: 200})")
    b = js(geo, "window.__geo.rectFromDrag({x: 60, y: 40}, {x: 10, y: 10}, {w: 300, h: 200})")
    assert a == b == {"x": 10, "y": 10, "w": 50, "h": 30}


def test_rectfromdrag_rejects_a_rect_below_the_minimum(geo):
    """`MIN_SIZE_PT` 未満は誤クリックとみなして `null` を返す。"""
    assert js(geo, "window.__geo.rectFromDrag({x: 10, y: 10}, {x: 12, y: 12}, {w: 300, h: 200})") is None


def test_rectfromdrag_rejects_a_rect_clamped_below_the_minimum(geo):
    """ページ外だけを引いた結果、収めると潰れる矩形も `null`。"""
    assert js(geo, "window.__geo.rectFromDrag({x: 310, y: 10}, {x: 400, y: 40}, {w: 300, h: 200})") is None
```

`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` に、不具合そのものを踏む E2E を 1 本足す。既存の
`_goto_step3` と上書きツールの流儀に合わせること。

```python
def test_manual_cover_drag_past_the_page_edge_still_places_a_cover(e2e_page, ocr_layer_pdf):
    """ページの端をまたいでドラッグしても上書きが置かれる (ページ内へ収める)。

    収めずにサーバへ送ると `addCover` がページ外として拒否し、受け止めが無いため利用者には
    成功も失敗も見えないまま何も起きない。
    """
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="cover"]')
    page.fill("#cover-text", "端")
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200
    # ページ右下の外までドラッグする
    page.mouse.move(box["x"] + 250 * sx, box["y"] + 150 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] + 120, box["y"] + box["height"] + 120, steps=5)
    page.mouse.up()
    covers = page.evaluate(
        """async () => (await window.rpc("coverList", { fileIndex: 0, pageInFile: 0 })).covers"""
    )
    assert len(covers) == 1
    r = covers[0]["rect"]
    assert r["x"] + r["w"] <= 300.5 and r["y"] + r["h"] <= 200.5
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pdftosvg_geometry_js.py -k rectfromdrag -v`
Expected: FAIL（`window.__geo.rectFromDrag` が `undefined`）。

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pdftosvg_app_flow_e2e.py -m e2e -k past_the_page_edge -v`
Expected: FAIL。上書きが 1 つも置かれず `len(covers) == 1` が落ちる。**これが直す不具合そのものである。**
失敗の出力を報告書へ残すこと。

- [ ] **Step 3: `geometry.js` へ確定処理を足す**

`clampToPage` の隣へ置く。

```js
/** ドラッグの 2 点からページ内の矩形を作る。引いた向きを正規化し、ページ内へ収め、
 *  収めた結果が `MIN_SIZE_PT` 未満なら `null`（誤クリックとして捨てる）。
 *  ページ外まで引いた矩形をそのままサーバへ送ると、矩形をページ内で検査する RPC
 *  (`addCover`) が拒否し、呼び出し側に受け止めが無いと利用者には何も起きないように見える。 */
export function rectFromDrag(a, b, size) {
  var raw = {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    w: Math.abs(a.x - b.x),
    h: Math.abs(a.y - b.y),
  };
  var r = clampToPage(raw, size.w, size.h);
  return r.w < MIN_SIZE_PT || r.h < MIN_SIZE_PT ? null : r;
}
```

- [ ] **Step 4: `app.js` の mouseup を差し替える**

import へ `rectFromDrag` と `pageSizeOf` を足す（`app.js` は現在 `clientToPage` と `parseSpec` しか
読んでいない）。mouseup の矩形を作る部分を次にする。

```js
      var a = clientToPage(svgEl, d.origin.x, d.origin.y);
      var b = clientToPage(svgEl, e.clientX, e.clientY);
      var rect = rectFromDrag(a, b, pageSizeOf(svgEl));
      if (!rect) return;
      var pg = S.PAGES[S.page];
```

以降の 3 分岐（枠線 / 上書き / 範囲削除）は変えない。`if (w < 4 || h < 4) return;` と、`x` / `y` / `w` / `h` を
個別に作っていた行は消える。

- [ ] **Step 5: `figure.js` の mouseup も同じ関数を使う**

`installFigDrag` の mouseup の "add" 側で、2 点から矩形を作り `clampToPage` して `MIN_SIZE_PT` を見ている
一連を `rectFromDrag` の 1 行へ置き換える。`figure.js` は既に `clampToPage` / `pageSizeOf` / `MIN_SIZE_PT` を
import しているので、使わなくなったものがあれば外す（他の用途で使っていないか必ず確かめる）。

- [ ] **Step 6: テストを通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test` と `py -3.13 -m pytest test -m e2e`
Expected: すべて PASS。特に手順 4 の図の採用（`test_gray_figure_flow`）が、ページ外まで引く既存の操作を
含んでいるので、そこが落ちないことを確かめる。

- [ ] **Step 7: コミット**

```bash
git add pdf-to-svg/resources/web/geometry.js pdf-to-svg/resources/web/app.js pdf-to-svg/resources/web/figure.js pdf-to-svg/test/test_pdftosvg_geometry_js.py pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py
git commit -m "fix(ui): ページの端をまたぐドラッグで上書きが置かれない不具合を直し、矩形の確定を 1 箇所へ寄せる"
```

---

### Task 2: 矩形の同一性への依存を捨て、角の伸縮を共有する

**Files:**
- Modify: `pdf-to-svg/resources/web/figure.js`、`pdf-to-svg/resources/web/cover.js`、`pdf-to-svg/resources/web/geometry.js`
- Test: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`（既存の伸縮 2 本が回帰の網）

**背景:**

角ハンドルの伸縮は両オーバーレイで同じ手順を踏む。掴んだ点をページ内へ収め、`resizeByCorner` で新しい
矩形を出し、箱を置き直す。それが 2 箇所に書かれている。ハンドルを掴んだときのドラッグ状態の組み立ても
同様に重複している。

共有を妨げているのは 1 点だけである。`figure.js` は採用矩形の箱を `figSelPeek(S.page).indexOf(d.rect)` と
**オブジェクトの同一性**で引くため、矩形を置き換えられず `Object.assign` で中身を書いている。`cover.js` に
この制約は無い。

**この制約は取り除ける。** `drawFigOverlay` は採用矩形を `sel.forEach(function (r, i) ...)` で回しており、
箱に `data-sel = i` を書いている。ハンドルの配線も同じ繰り返しの中にあるので、ドラッグ開始時点で添字 `i` が
手に入る。ドラッグ状態へ添字を持てば、同一性で引く必要が無くなる。

**添字のほうが壊れにくい。** 採用配列が丸ごと差し替わる経路（候補の再取得）では、同一性の照合は箱を
見失うが、添字なら該当の箱を引き当てられる。現状はドラッグ中にその差し替えが起きないので表に出ないが、
弱いほうの前提に依存し続ける理由も無い。

添字が安定であることは確認済みである。採用配列を変える操作（候補の採用、採用の取り消し、空白ドラッグでの
追加）はいずれも単一のポインタ操作で、伸縮ドラッグと同時には起きない。`data-sel` を書くのは
`drawFigOverlay` の 1 箇所、読むのは伸縮の mousemove の 1 箇所だけであり、採用配列に `indexOf` を使う箇所は
他に無い。矩形のオブジェクト同一性に依存するテストも無い。

- [ ] **Step 1: 同一性への依存を外す**

`figure.js` の、ハンドルの mousedown でドラッグ状態を作る箇所へ添字を持たせる。

```js
        S.figDrag = { mode: "resize", index: i, corner: h.dataset.corner, orig: copyRect(r) };
```

伸縮の mousemove を次にする。`d.rect` は使わなくなる。

```js
    var rect = resizeByCorner(d.orig, d.corner, p);
    figSelOf(S.page)[d.index] = rect;
    var box = host.querySelector('.fig-cand.sel[data-sel="' + d.index + '"]');
    if (box) placeRect(box, rect, svgEl, host);
```

`Object.assign` と、同一性で引いていた `indexOf` は消える。`figure.js` の冒頭コメントと `figure.js` 内の
該当箇所のコメント、`geometry.js` の `resizeByCorner` の説明から、同一性の制約に触れている記述を落とす
（制約が無くなるため）。`cover.js` 冒頭の対応する記述も同様。

- [ ] **Step 2: 既存の伸縮が壊れていないことを確かめる**

Run: `cd pdf-to-svg; py -3.13 -m pytest test -m e2e -v`
Expected: すべて PASS。特に `test_gray_figure_flow`（手順 4 の伸縮が実際に効くことを寸法で見る）と
`test_manual_cover_resize_and_retext`（手順 3 の伸縮）。**この 2 本が本タスクの安全網である。**

- [ ] **Step 3: 伸縮のドラッグ配線を共有する**

両オーバーレイの mousemove の伸縮枝が、今や同じ形になっている。`geometry.js` へ寄せる。

```js
/** 角ハンドルのドラッグ中に、掴んだ点から新しい矩形を出す。点はページ内へ収める
 *  (`clientToPage` はページの外へも線形に外挿するため、そのまま使うと枠外の矩形になる)。 */
export function resizeFromPointer(svgEl, drag, clientX, clientY) {
  var p = clientToPage(svgEl, clientX, clientY);
  var sz = pageSizeOf(svgEl);
  p.x = Math.max(0, Math.min(p.x, sz.w));
  p.y = Math.max(0, Math.min(p.y, sz.h));
  return resizeByCorner(drag.orig, drag.corner, p);
}
```

両方の mousemove をこれへ差し替える。`cover.js` は結果を `d.rect` へ入れ、`figure.js` は採用配列の該当
添字へ入れる。この差は残る（前者はドラッグ状態に矩形を持ち、後者は配列が正）ので、そこは共有しない。

- [ ] **Step 4: 全体を回す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test` と `py -3.13 -m pytest test -m e2e`
Expected: すべて PASS。

- [ ] **Step 5: コミット**

```bash
git add pdf-to-svg/resources/web/figure.js pdf-to-svg/resources/web/cover.js pdf-to-svg/resources/web/geometry.js
git commit -m "refactor(ui): 採用矩形を添字で引く形にして同一性の制約を外し、角の伸縮を共有する"
```

---

### Task 3: サーバ側の矩形の受け取りを 1 本へ寄せる

**Files:**
- Modify: `pdf-to-svg/src/web/rpc_methods.py`
- Test: `pdf-to-svg/test/test_web_rpc.py`

**背景:**

クライアントから届く `{x, y, w, h}` の受け取りが 3 通りある。

- `_parse_rect_arg`（有限・正の寸法・ページ内）を通るのは `addCover` / `updateCover` / 切り出し。
- `rpc_deleteRegion` と `rpc_addBorder` は `Rect(float(r["x"]), ...)` と素で組み立てる。

既にずれている。`rpc_addBorder` は線の太さの非有限値を丁寧に弾くのに、その 1 行上で矩形の非有限値を
通している。非有限の値は `_fmt` が SVG へ書き込む。`_parse_rect_arg` を厳しくしても、この 2 つは守られない。

**ページ内の要求だけは分ける。** 範囲削除はページの外まで引いた選択でも成立してよい（内側の要素を選ぶ
だけで、矩形自体は成果物に残らない）。ページ内を要求するかどうかを引数で分ける。

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_web_rpc.py` に追記する。

```python
@pytest.mark.parametrize("method", ["deleteRegion", "addBorder"])
def test_rect_arg_rejects_non_finite_values(session, method):
    """非有限の矩形はどの入口でも拒否する (`_fmt` が SVG へ書き込む値になる)。"""
    args = {"fileIndex": 0, "pageInFile": 0, "rect": {"x": 0, "y": 0, "w": float("inf"), "h": 10}}
    with pytest.raises(ValueError):
        rpc_methods.dispatch(session, method, args)


def test_delete_region_still_accepts_a_rect_past_the_page_edge(session):
    """範囲削除はページの外まで引いた選択でも成立する (矩形は成果物に残らない)。"""
    args = {"fileIndex": 0, "pageInFile": 0, "rect": {"x": 150, "y": 250, "w": 200, "h": 200}}
    rpc_methods.dispatch(session, "deleteRegion", args)  # 例外が出ないこと


def test_add_border_rejects_a_rect_past_the_page_edge(session):
    """枠線は成果物に残るのでページ内を要求する。"""
    args = {
        "fileIndex": 0, "pageInFile": 0,
        "rect": {"x": 150, "y": 250, "w": 200, "h": 200}, "color": "#000000", "width": 1,
    }
    with pytest.raises(ValueError):
        rpc_methods.dispatch(session, "addBorder", args)
```

`session` フィクスチャのページ寸法を確認し、期待値をその寸法に合わせること（上の値は 200×300 を想定して
いる。違えば実寸へ直す）。

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_web_rpc.py -k "rect_arg or past_the_page" -v`
Expected: 非有限の 2 本と枠線の 1 本が FAIL。範囲削除の 1 本は現状でも通る。

- [ ] **Step 3: `_parse_rect_arg` に範囲の要求を分ける引数を足す**

```python
def _parse_rect_arg(
    args: dict, key: str, pg: Page, *, inside_page: bool = True
) -> Optional[Rect]:
```

ページ内を見る 2 つの検査を `if inside_page:` で囲む。有限性と正の寸法は常に見る。docstring へ、
`inside_page=False` は「矩形自体が成果物に残らない用途（範囲削除の選択）」のためだと書く。

`rpc_deleteRegion` を `rect = _parse_rect_arg(args, "rect", pg, inside_page=False)` に、
`rpc_addBorder` を `rect = _parse_rect_arg(args, "rect", pg)` にする。どちらも `rect is None` のときは
`ValueError` にする（引数が欠けている場合。`addCover` と同じ扱い）。

- [ ] **Step 4: テストを通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test` と `py -3.13 -m pytest test -m e2e`
Expected: すべて PASS。E2E の範囲削除（ページ外まで引く操作を含む）が落ちないことを確かめる。

- [ ] **Step 5: コミット**

```bash
git add pdf-to-svg/src/web/rpc_methods.py pdf-to-svg/test/test_web_rpc.py
git commit -m "fix(web): 矩形の受け取りを 1 本へ寄せ、範囲削除以外でページ内と有限性を要求する"
```

---

### Task 4: テストの重複と、対で保守する定数の検査

**Files:**
- Modify: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`
- Modify: `pdf-to-svg/test/test_resource_limits.py`

**背景:**

E2E に同じ読み取りが逐語で 2 度ある（伸縮の前後で採用矩形を読む）。また、`src/engine/pdf_engine.py` の
`MAX_RASTER_PIXELS` と `src/export/grayscale.py` の `MAX_GRAY_IMAGE_PIXELS` は「片方を変えたら両方」と
コメントで約束しているのに、等値を確かめる検査が無い。前者は `fitz` を import するモジュールにあるため
寄せられず、複製が正しい形である。ならば検査で守る。

- [ ] **Step 1: E2E の読み取りを 1 つのヘルパへ**

`test_pdftosvg_app_flow_e2e.py` の、採用矩形を `window.__state` から読む `page.evaluate` が 2 箇所ある。
モジュール内のヘルパへ畳む。矩形の全体（`x` / `y` / `w` / `h`）を返す形にして、将来の移動の検査でも
使えるようにする。

```python
def _adopted_rect(page, index=0):
    """手順 4 で採用している矩形をモデル側から読む (表示の箱ではなく `S.figSel` が正)。"""
    return page.evaluate(
        """(i) => {
            const S = window.__state; const pg = S.PAGES[S.page]; if (!pg) return null;
            const sel = S.figSel[pg.fileIndex + ":" + pg.pageInFile];
            const r = sel && sel[i];
            return r ? { x: r.x, y: r.y, w: r.w, h: r.h } : null;
        }""",
        index,
    )
```

呼び出し側 2 箇所をこれに差し替える。断言は今までどおり幅と高さが増えたことを見る。

- [ ] **Step 2: 対で保守する定数の等値を固定する**

`test_resource_limits.py`（既に `MAX_RASTER_PIXELS` を import している）へ 1 本足す。

```python
def test_raster_and_gray_pixel_caps_stay_equal():
    """`pdf_engine` と `grayscale` の画素上限は対で保守する。

    `pdf_engine` は `fitz` を import するため `grayscale` から読めず、値を複製している。
    複製が正しい形なので、ずれていないことを検査で守る。
    """
    from export.grayscale import MAX_GRAY_IMAGE_PIXELS

    assert MAX_RASTER_PIXELS == MAX_GRAY_IMAGE_PIXELS
```

- [ ] **Step 3: 通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test` と `py -3.13 -m pytest test -m e2e`
Expected: すべて PASS。

- [ ] **Step 4: コミット**

```bash
git add pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py pdf-to-svg/test/test_resource_limits.py
git commit -m "test: 採用矩形の読み取りを 1 箇所へ畳み、対で保守する画素上限の等値を固定する"
```

---

### Task 5: 原稿を実態へ揃えて HTML を再生成する

**Files:**
- Modify: `docs/pdf-to-svg/src/設計正典.md`、`docs/pdf-to-svg/src/設計書.md`、`docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`
- Generate: 閲覧用 HTML 2 枚

**書く前に:** 対象の実装を読むこと。原稿は published canon であり、丁寧な日本語の散文で書く。既存の
語り口・見出しの深さ・表の形・識別子のバッククォートの流儀に合わせる。日付・経緯・内部のタスク番号は
本文に書かない（front matter の `rev:` への 1 行追加は例外で、必要）。

- [ ] **Step 1: 設計正典**

中核原則へ、ドラッグから矩形を作る決定を 1 箇所に置くことを足す。ページ外まで引いた矩形をそのまま
サーバへ送ると、矩形をページ内で検査する RPC が拒否し、呼び出し側に受け止めが無いと利用者には何も
起きないように見える、という理由を添える。

サーバ側の矩形の受け取りが `_parse_rect_arg` の 1 本であること、ページ内を要求するかどうかだけを
引数で分けること（範囲削除は矩形が成果物に残らないので要求しない）も足す。

- [ ] **Step 2: 設計書**

- 7.2 節: 矩形を受け取る RPC の検査が 1 本に揃ったこと。
- 8 章: `geometry.js` が `rectFromDrag` と `resizeFromPointer` を持つこと。手順 4 が採用矩形を添字で
  引くようになり、矩形のオブジェクト同一性への依存が無くなったこと。**同一性の制約に触れている既存の
  記述をすべて落とすこと**（制約が消えたので、残すと嘘になる）。
- 13 章: 足した単体テストと E2E の観点。

- [ ] **Step 3: 仕様一覧**

RPC の表で、矩形を取るメソッドの検査を揃えたことを反映する。テスト表へ本計画で足した観点の行を足す。

- [ ] **Step 4: HTML を再生成する**

Run: `py -3.13 docs/_build/build_all.py --project pdf-to-svg`、`py -3.13 -m pytest docs/_build -q`
Expected: 生成が 2 枚とも成功し、docs のテストが通る。

- [ ] **Step 5: コミット**

```bash
git add docs/pdf-to-svg
git commit -m "docs(pdf-to-svg): ドラッグ矩形の一元化と矩形検査の統一を原稿へ反映し HTML を再生成する"
```

- [ ] **Step 6: リリースの差し替えは controller が行う**

実装者は触らないこと。

---

## Self-Review

- **Task 1 は実害のある不具合の修正である。** E2E は RED から入る唯一のタスクなので、失敗の出力を必ず
  報告書へ残すこと。
- Task 2 は Task 1 の後に置く。どちらも `figure.js` の mouseup 付近を触るため。
- Task 2 で消える制約について、原稿の記述を Task 5 で落とすのを忘れないこと。制約が無くなったのに
  「同一性で引くため置き換えられない」と書き続けると、今度は逆向きの嘘になる。
- Task 3 の `inside_page=False` は範囲削除だけに与える。切り出し（`clip`）は成果物の領域を決めるので
  ページ内を要求したままにする。
- 本計画は**消してはならない重複**に触れない。別プロジェクトとの並行実装と、`fitz` を import する
  モジュールの定数。後者は Task 4 で等値の検査を足すだけで、複製自体は残す。
- 洗い出しが挙げた他の項目（書き出しファイル名がクライアントとサーバで別々に組まれる、オーバーレイの
  箱の組み立て、ハンドルの CSS が 2 箇所、E2E の配置ドラッグが 4 回）は本計画に含めない。前者 2 つは
  片方だけ変えても検出される仕組みが既にあるか、merge するとかえって読みにくい。後者 2 つは見た目と
  テストの中だけの重複で、実害の経路が無い。
