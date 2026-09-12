# 矩形ヘルパの geometry.js への集約（トラック B） 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 手順 3 の上書きオーバーレイ（`cover.js`）が、グレーモード専用の `figure.js` から矩形ヘルパを
読んでいる横方向の依存を断つ。5 つのヘルパを `geometry.js` へ移し、両モジュールがそこから読む形にする。

**Architecture:** `figure.js` が定義して `cover.js` が読んでいる `copyRect` / `pageSizeOf` /
`clampToPage` / `placeRect` / `MIN_SIZE_PT` を `geometry.js` へそのまま移す。`figure.js` は自分が
使う分を `geometry.js` から import する側へ回る。移動であって書き換えではない。

**Tech Stack:** 素の JavaScript（ES modules）/ pytest + Playwright（Edge）。

**Spec:** 本計画が正典。現状の取り決めは `docs/pdf-to-svg/src/設計書.md` の 8 章（`resources/web/` の
ファイル表と「矩形操作の純粋ヘルパは `figure.js` から読み、複製しない」の記述）にある。

**前提:** トラック A（`2026-09-13-ocr-cover-cleanup.md`）のコード変更が先に入っていること。本計画の
最終タスクが、両トラック分の原稿・HTML・リリースをまとめて 1 回で更新する。

## Global Constraints

- 新規・変更した `.js` は `// ===` の装飾ボックスヘッダを保つ。コメントは日本語の散文、識別子は
  バッククォート、理由は現在形。日付・経緯・内部のタスク番号を書かない（`docs/コメント規約.md`。
  pre-commit が `scripts/check_comments.py --staged` で検査する）。
- pytest は `pdf-to-svg/` の中から `py -3.13 -m pytest test/...` の形で実行する。
- ブラウザの `alert` / `prompt` / `confirm` は使わない。
- 手順 3（選択 / 範囲削除 / 枠線 / 上書き）と手順 4（グレーモードの図の採用・伸縮）の**挙動を変えない**。
  本計画は移動のみで、1 つの関数の中身も書き換えない。
- コミットすると post-commit が auto-push し、pre-push が検証一式（約 2 分）を回す。`--no-verify` を
  使わない。force push もしない（リリースのタグ差し替えを除く。最終タスクを参照）。
- コミットメッセージは日本語の Conventional Commits。本文の末尾に次の 2 行を置く。

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_0126DHJZ8WfffcXsMqETHsLc
  ```

## File Structure

| ファイル | 変更 | 責務 |
|---|---|---|
| `pdf-to-svg/resources/web/geometry.js` | 変更 | ページ座標と矩形操作のヘルパを持つ。冒頭の性格説明を実態へ改める |
| `pdf-to-svg/resources/web/figure.js` | 変更 | 5 つのヘルパの定義と再エクスポートを手放し、`geometry.js` から読む |
| `pdf-to-svg/resources/web/cover.js` | 変更 | `figure.js` への import を無くし、`geometry.js` から読む |
| `pdf-to-svg/test/test_pdftosvg_geometry_js.py` | 変更 | 移した純粋ヘルパ 3 つの単体テスト |
| `docs/pdf-to-svg/src/*.md` + 生成 HTML 2 枚 | 変更 | 両トラック分の原稿更新と再生成（最終タスク） |

パスはすべて `C:\Users\caads\python-tools` からの相対。

### 移すもの（現状の所在）

`figure.js` が定義し、末尾の `export { ... }` で再エクスポートしている 5 つ。

- `MIN_SIZE_PT = 4` — これ未満の矩形は誤クリックとみなして作らない
- `copyRect(r)` — 矩形の複製
- `clampToPage(r, w, h)` — ページ外へはみ出した矩形をページ内へ収める
- `pageSizeOf(svgEl)` — `viewBox` からページ幅・高さ（pt）を読む
- `placeRect(box, r, svgEl, host)` — HTML の箱を SVG 座標の矩形へ重ねる（`style` を書く）

`geometry.js` の現在の住人は `clientToPage` / `rectIoU` / `parseSpec`。冒頭は「純粋ヘルパ（状態非依存）」と
名乗るが、`clientToPage` は既に `getBoundingClientRect()` と `viewBox.baseVal` を読んでいる。移す 5 つの
うち `pageSizeOf` も DOM を読み、`placeRect` は DOM を書く。**「純粋」という看板は現状で既に実態と
合っていない**ので、この機会に「ページ座標と矩形操作のヘルパ」へ改める。

---

### Task 1: 5 つのヘルパを geometry.js へ移す

**Files:**
- Modify: `pdf-to-svg/resources/web/geometry.js`
- Modify: `pdf-to-svg/resources/web/figure.js`
- Modify: `pdf-to-svg/resources/web/cover.js`
- Test: `pdf-to-svg/test/test_pdftosvg_geometry_js.py`、`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`（既存 E2E が回帰を見る）

**Interfaces:**
- Produces: `geometry.js` が `MIN_SIZE_PT` / `copyRect` / `clampToPage` / `pageSizeOf` / `placeRect` を
  追加でエクスポートする。`figure.js` はこれら 5 つをエクスポートしなくなる（`initFigure` /
  `buildFigRail` / `buildFigSelist` / `drawFigOverlay` / `installFigDrag` の 5 つだけを出す）。
- Consumes: `figure.js` と `cover.js` が `geometry.js` から読む。

- [ ] **Step 1: 移した先のテストを先に書く**

`pdf-to-svg/test/test_pdftosvg_geometry_js.py` の末尾に追記する。この harness は実ブラウザで
`/geometry.js` を import するので、移動が済むまでは `undefined` で落ちる。`placeRect` は DOM の箱と
`svgEl` を要するのでここでは扱わない（既存の E2E が実挙動を見ている）。

```python
def test_copyrect_returns_an_independent_copy(geo):
    assert js(geo, """(() => {
        const a = { x: 1, y: 2, w: 3, h: 4 };
        const b = window.__geo.copyRect(a);
        b.x = 99;
        return [a.x, b.x, b.y, b.w, b.h];
    })()""") == [1, 99, 2, 3, 4]


def test_clamptopage_keeps_a_rect_inside_the_page(geo):
    assert js(geo, "window.__geo.clampToPage({x: -10, y: -10, w: 40, h: 40}, 100, 100)") == {
        "x": 0, "y": 0, "w": 30, "h": 30,
    }


def test_clamptopage_collapses_a_rect_fully_outside(geo):
    assert js(geo, "window.__geo.clampToPage({x: 200, y: 200, w: 10, h: 10}, 100, 100)") == {
        "x": 100, "y": 100, "w": 0, "h": 0,
    }


def test_min_size_pt_is_exported(geo):
    assert js(geo, "window.__geo.MIN_SIZE_PT") == 4
```

`pageSizeOf` は `svgEl.viewBox.baseVal` を要するため、harness 上で軽い SVG を作って渡す。

```python
def test_pagesizeof_reads_the_viewbox(geo):
    assert js(geo, """(() => {
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        svg.setAttribute("viewBox", "0 0 300 200");
        document.body.appendChild(svg);
        const r = window.__geo.pageSizeOf(svg);
        svg.remove();
        return r;
    })()""") == {"w": 300, "h": 200}
```

- [ ] **Step 2: 失敗を確認する**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pdftosvg_geometry_js.py -v`
Expected: 新しい 5 本が FAIL（`window.__geo.copyRect` などが `undefined`）。既存の 7 本は PASS。

- [ ] **Step 3: geometry.js へ移す**

`geometry.js` の冒頭のヘッダと説明を次にする。

```js
// =============================================================================
// geometry.js — PdfToSvg のページ座標と矩形操作のヘルパ
// =============================================================================
// 画面の状態 (`state.js` の `S`) には依存しない。DOM は読む (`clientToPage` /
// `pageSizeOf` が `viewBox` と要素の実寸を見る) し、`placeRect` は箱の `style` を書くが、
// どれも「渡された引数だけで決まる」ので手順 3 のオーバーレイ (`cover.js`) と手順 4 の
// 採用矩形 (`figure.js`) が同じ実装を共有できる。
```

`figure.js` から次の 5 つを、コメントごとそのまま `geometry.js` へ移し、`export` を付ける。中身は
1 文字も変えない。

- `MIN_SIZE_PT`
- `copyRect`
- `clampToPage`
- `pageSizeOf`
- `placeRect`

`placeRect` は `svgEl` と `host` の実寸を読むので、`clientToPage` の隣（座標変換の並び）へ置く。

- [ ] **Step 4: figure.js を読む側へ回す**

`figure.js` の import を次にする。

```js
import { clientToPage, rectIoU, copyRect, pageSizeOf, clampToPage, placeRect, MIN_SIZE_PT } from "./geometry.js";
```

移した 5 つの定義を消す。冒頭のブロックコメントから「矩形操作の純粋ヘルパ … ここでエクスポートして
共有する（複製しない）」の 3 行を消し、代わりに 1 行置く。

```js
// 矩形操作のヘルパ (`copyRect` / `pageSizeOf` / `clampToPage` / `placeRect` / `MIN_SIZE_PT`) は
// 手順 3 の上書きオーバーレイ (`cover.js`) と共有するため `geometry.js` にある。
```

末尾の `export { ... }` から 5 つを外す。

```js
export { initFigure, buildFigRail, buildFigSelist, drawFigOverlay, installFigDrag };
```

- [ ] **Step 5: cover.js の依存を切る**

`cover.js` の import 3 行を 2 行にする。

```js
import { clientToPage, copyRect, pageSizeOf, clampToPage, placeRect, MIN_SIZE_PT } from "./geometry.js";
import { S } from "./state.js";
```

冒頭のブロックコメントの「`figure.js` の採用矩形の実装とロジックが同一なので、複製せずそちらから
読む」の 2 行を次に置き換える。

```js
// 矩形操作のヘルパ (`copyRect` / `pageSizeOf` / `clampToPage` / `placeRect` / `MIN_SIZE_PT`) は
// 手順 4 の採用矩形と同じ流儀なので `geometry.js` から共有して読む。
```

`figure.js` への import が 1 つも残っていないことを確かめる。

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pdftosvg_js_smoke.py -v`
Expected: PASS（モジュールの読み込みが壊れていない）。

- [ ] **Step 6: 移動先のテストと既存の挙動を通す**

Run: `cd pdf-to-svg; py -3.13 -m pytest test/test_pdftosvg_geometry_js.py -v`
Expected: 新規 5 本を含め全 PASS。

Run: `cd pdf-to-svg; py -3.13 -m pytest test` と `py -3.13 -m pytest test -m e2e`
Expected: すべて PASS。手順 3 の上書きの配置・伸縮・移動と、手順 4 のグレーモードの採用矩形の
伸縮を見る既存 E2E が、移動で壊れていないことの確認になる。

- [ ] **Step 7: コミット**

```bash
git add pdf-to-svg/resources/web/geometry.js pdf-to-svg/resources/web/figure.js pdf-to-svg/resources/web/cover.js pdf-to-svg/test/test_pdftosvg_geometry_js.py
git commit -m "refactor(ui): 矩形ヘルパを geometry.js へ集約し cover.js の figure.js 依存を切る"
```

---

### Task 2: 両トラックの原稿を更新して HTML を再生成しリリースを差し替える

**Files:**
- Modify: `docs/pdf-to-svg/src/設計正典.md`
- Modify: `docs/pdf-to-svg/src/設計書.md`
- Modify: `docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`
- Generate: `docs/pdf-to-svg/pdf-to-svg_設計.html`、`docs/pdf-to-svg/pdf-to-svg_手引き.html`

**背景:** 原稿・HTML・リリースの更新は 1 セットで払う運用である。トラック A とトラック B の
コード変更は既に入っているので、ここで両方まとめて 1 回だけ反映する。

**書く前に:** 対象の実装を読むこと。原稿の記述は実装が正である。`src/export/svg_exporter.py`
（`_cover_sampler` / `_cover_svg` / `page_to_svg`）、`src/export/cover.py`（`decode_image`）、
`src/engine/pdf_engine.py`（`_extract_page` / `_text_element`）、`resources/web/geometry.js` /
`figure.js` / `cover.js`。原稿は published canon であり、丁寧な日本語の散文で書く。各ファイルの
既存の語り口・見出しの深さ・表の形・識別子のバッククォートの流儀に合わせる。日付・経緯・内部の
タスク番号は本文に書かない（front matter の `rev:` への 1 行追加は例外で、必要）。

- [ ] **Step 1: 設計正典**

「グレー化・切り出しは exporter のオプション」の項へ、上書き矩形の採色は**書き出しに乗る画像**から
行うことを足す。元のカラー画像から採ると、矩形は輝度変換だけ・画像は `tone_curve` も掛かるため
矩形だけが暗い当て板になること、対応表（`SMTAM_MONO_COLORS`）を踏めば大きく外れることを理由として
書く。併せて、グレーのチェックは手順 1 にあり手順 1 へは戻れるため、上書きを置いたままグレーへ
切り替える経路が実在することに触れる。

「不可視 OCR 文字層」の項へ、透明部分を持つ画像は白へ合成してから採色することを 1 文足す
（合成せずに alpha を捨てると、透明画素が格納 RGB のまま最頻色を支配し、隠すはずの矩形が黒い帯に
なる）。

- [ ] **Step 2: 設計書**

- 3.1 節: `_text_element` の説明に `invisible` 引数を反映する（docstring を直した分）。
- 4.1 節: 索引が照合を諦めたときは不可視 seqno を集めないこと。
- 5.1 節: `_cover_sampler` が `image_fn` を通してから採ること、`_cover_svg` が採色済みの色を
  再変換しないこと、`decode_image` の alpha 合成、`page_to_svg` が要素列を 1 度だけ確定させること。
- 8 章: `resources/web/` のファイル表で `geometry.js` の責務を「ページ座標と矩形操作のヘルパ」へ
  改め、`figure.js` の行から「矩形ヘルパを共有のためエクスポートする」旨を外す。「矩形操作の純粋
  ヘルパは `figure.js` から読み、複製しない」と書いている箇所を `geometry.js` へ直す。

- [ ] **Step 3: 仕様一覧**

テスト表へ、本 2 トラックで足した観点の行を既存の行の形に合わせて追加する（グレー書き出しの採色
一致、透明画像の採色、削除済み上書きの拒否、移した矩形ヘルパの単体）。

- [ ] **Step 4: HTML を再生成して差分を確かめる**

Run: `py -3.13 docs/_build/build_all.py --project pdf-to-svg`
Expected: `[ok] pdf-to-svg/pdf-to-svg_設計.html` と `[ok] pdf-to-svg/pdf-to-svg_手引き.html`。
`git status` で 2 枚に差分が出る。

Run: `py -3.13 -m pytest docs/_build -q`
Expected: PASS。

- [ ] **Step 5: コミット**

```bash
git add docs/pdf-to-svg
git commit -m "docs(pdf-to-svg): グレー書き出しの採色・透明画像の合成・矩形ヘルパの移動を原稿へ反映し HTML を再生成する"
```

- [ ] **Step 6: リリースを差し替える**

`gh release list --limit 1` で最新タグを確認する（現時点は `2026.09.08`）。ノートの
`## 含まれる変更` の直後へ `###` の節を足す（既存の節は消さない。`## 検証` を二重にしない）。

```bash
git tag -f <最新タグ> HEAD
git push origin -f refs/tags/<最新タグ>
gh release edit <最新タグ> --notes-file <追記したノート>
```

`git push -f` が権限で拒否された場合は、利用者へ `! git push origin -f refs/tags/<タグ>` の実行を
依頼する。`git tag -f`（手元）と `gh release edit` は通る。

---

## Self-Review

- **移動のみ**である。関数の中身を書き換えないので、手順 3 と手順 4 の挙動は変わらない。既存の E2E が
  両方を通っており、それが回帰の網になる。
- `placeRect` を含めて全部移す判断のため、`cover.js` から `figure.js` への import は 1 つも残らない。
  Task 1 Step 5 でそれを確かめる。
- `geometry.js` の「純粋ヘルパ（状態非依存）」という看板は、移動の前から `clientToPage` が DOM を
  読んでいて実態と合っていない。Step 3 で看板を実態へ改める。
- `MIN_SIZE_PT` は幾何ではなく操作のポリシー定数だが、`clampToPage` と対で使われる（クランプ後に
  この値未満なら作らない）ので同居させる。移動先で孤立しない。
- トラック A の Task 4 が `svg_exporter.py` の `_cover_sampler` の署名を変える。本計画は JavaScript
  しか触らないので衝突しない。
- 文書タスクは両トラック分をまとめる。トラック A を実施せずに本計画だけを走らせる場合は、Step 1 と
  Step 2 のうちトラック A 由来の項目（採色・alpha 合成・`invisible` の docstring・要素列の確定）を
  落とすこと。
