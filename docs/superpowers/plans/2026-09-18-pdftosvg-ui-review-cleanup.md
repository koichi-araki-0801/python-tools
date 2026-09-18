# PdfToSvg 画面の見直し 残作業の整理 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 「PdfToSvg 画面の見直し」（計画 `2026-09-18-pdftosvg-ui-review.md`）の最終レビューで「そのままで可」と判定した軽微事項を片付け、`state` RPC のコストを実測して結果を原稿に残す。

**Architecture:** 挙動を変えないコード整理（A）、E2E で固定する小さな挙動修正（B）、計測と結果次第の最適化（C）、原稿・写真・HTML（D）の 4 段。A と B は `app.js` / `state.js` / `rail.js` / `styles.css` / `rpc_methods.py` の局所変更で、既存の設計（件数モデル、`page-jump.js` の 1 部品、1 文 1 行）は変えない。

**Tech Stack:** Python 3.13 標準ライブラリ + PyMuPDF、素の JavaScript（ES module）、pytest + Playwright（実 Edge）、`docs/_build/build_all.py`。

**Spec:** `docs/superpowers/specs/2026-09-18-pdftosvg-ui-review-design.md`（本計画はその残件。利用者の承認済み一覧は本計画 0 節）

## Global Constraints

- Python は常に `py -3.13`。pytest はディレクトリごとに個別実行（`pdf-to-svg` / `docs/_build`。一括にしない）。E2E は `py -3.13 -m pytest pdf-to-svg -m e2e -q`。
- コミットはフックを外して積む（`git -c core.hooksPath=.superpowers/nohooks commit -F <msgfile>`。`.superpowers/nohooks` は空ディレクトリ。無ければ `mkdir -p`）。コミット前に `py -3.13 scripts/check_comments.py --staged` が 0 errors。push は controller が前景で 1 回行う。
- コミットメッセージは Conventional Commits 形式の日本語。末尾に次の 2 行:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
  ```
- コメントは平文の日本語、原稿は丁寧体。コメント・原稿にレビュー所見の識別子（`R1` 等）を書かない。
- 画面の文言は 1 文 1 行、右パネルの文は 1 行に収まる長さ。

## 0. 対象一覧（利用者承認済み）

| 群 | 項目 |
|---|---|
| A | `wirePageFoot2/3` の 1 本化 / `matchTotals` `editTotals` が `matchCount` `editCount` を使う / `invalidateAll` 削除 / `renderConfirm` の到達不能分岐削除 / `renderScanBanner` の二重呼び出し解消 / 孤児 CSS 削除・`rect-overlay.js` コメントの空白 / `_page_match_counts` の pending を `plan_replacements` から直接数える |
| B | 右パネル行「削除」で overlay 選択を先に解く / 枠線行の `b.width` を `esc` / `#trim-dyn` に `gap` / レールの空表示を固定文に / グレーカード説明文の短縮 / ページ移動のファイル選択とファイルまたぎの E2E |
| C | 100 ページ級 PDF + 辞書 50 語で `state` と `pageSvg` の所要を実測。遅ければ `svgCache` の全消しを表示中ページだけに戻す |
| D | 仕様一覧 4.2 のステップ欄・`.note-line` の行・B の文言・C の結果。写真 `step1_select.png` 再撮影、HTML 再生成、リリース差し替え |

---

### Task 1: コード整理（挙動変更なし）

**Files:**
- Modify: `pdf-to-svg/resources/web/app.js`（`wirePageFoot2` / `wirePageFoot3`、`renderConfirm` の `desc`、`renderFileCards` 末尾の `renderScanBanner()`）
- Modify: `pdf-to-svg/resources/web/state.js`（`invalidateAll` 削除、`matchTotals` / `editTotals`）
- Modify: `pdf-to-svg/resources/web/styles.css`（`.pg-row.skipped*` / `.pg-row .pg-tag*` / `.tg.t-skipped` / `.tg.t-none`）
- Modify: `pdf-to-svg/resources/web/rect-overlay.js:51`（「`clearSel` 。」の空白）
- Modify: `pdf-to-svg/src/web/rpc_methods.py`（`_page_match_counts`）
- Test: `pdf-to-svg/test/test_pdftosvg_state_js.py`（`invalidateAll` のテスト削除）、既存の単体・E2E（挙動不変の確認）

**Interfaces:**
- Produces: `wirePageFoot(prevId, nextId, nextIndexFn)`（`app.js` 内部）。`state.js` の export から `invalidateAll` が消える。他の公開名は変えない。

- [ ] **Step 1: `invalidateAll` のテストを消し、削除後に import が壊れないことを確かめる準備**

`test_pdftosvg_state_js.py` の `# ── invalidateAll ──` 見出しと `test_invalidateall_discards_svg_cache_for_all_pages`（`:99-105`）を削除する。`grep -rn invalidateAll pdf-to-svg` が `state.js` の 2 行だけになることを確認する。

- [ ] **Step 2: `state.js`**

`invalidateAll`（`:124-129` の docstring 含む）と export の `invalidateAll,` を削除する。`matchTotals` / `editTotals` を次にする。

```js
/** 手順 2 のまとめ: 置換済み・未置換の箇所数、一致のあるページ数、スキャンページ数 */
function matchTotals() {
  var t = { applied: 0, pending: 0, pages: 0, scanned: scannedTotal() };
  S.matches2.forEach(function (m, g) {
    if (S.scanned[g]) return;
    t.applied += m.applied; t.pending += m.pending;
    if (matchCount(g)) t.pages++;
  });
  return t;
}
/** 手順 3 のまとめ: 編集したページ数と、削除・枠線・上書きの件数 */
function editTotals() {
  var t = { pages: 0, removed: 0, borders: 0, covers: 0 };
  S.edits3.forEach(function (e, g) {
    t.removed += e.removed; t.borders += e.borders; t.covers += e.covers;
    if (editCount(g)) t.pages++;
  });
  return t;
}
```

- [ ] **Step 3: `app.js`**

`wirePageFoot2` / `wirePageFoot3`（`:619-634`）を次の 1 本にし、`render()` の呼び出しを `wirePageFoot("prev-page-2", "next-match-2", function () { return nextMatched(S.page); });`（手順 2）と `wirePageFoot("prev-page-3", "next-page-3", function () { return S.page < S.TOTAL - 1 ? S.page + 1 : -1; });`（手順 3）にする。

```js
  // ── 12. ページ送り (右パネル下部) ──
  /** 「前のページ」は通し −1。「次」は手順ごとの行き先関数 (無ければ -1) で決める:
   *  手順 2 は辞書に一致した次のページ (`nextMatched`)、手順 3 は通し +1。
   *  静的なボタンなので `onclick` 代入で配線し、再描画で多重登録にならないようにする。 */
  function wirePageFoot(prevId, nextId, nextIndexFn) {
    var prev = document.getElementById(prevId), next = document.getElementById(nextId);
    prev.disabled = S.page === 0;
    next.disabled = nextIndexFn() < 0;
    prev.onclick = function () { if (S.page > 0) { S.page--; render(); } };
    next.onclick = function () { var n = nextIndexFn(); if (n >= 0) { S.page = n; render(); } };
  }
```

`renderConfirm` の `var desc = total === 0 ? "このページに辞書と一致する語はありません。" : pending === 0 ? … : …;` から `total === 0` の分岐を外す（`var desc = pending === 0 ? "辞書に一致した " + total + " か所をすべて置き換えました。" : "一致 " + total + " か所のうち " + pending + " か所が未置換です。";`）。0 件は関数冒頭の `if (!matchCount(S.page))` が担う旨を 1 行コメントで残す。

`renderFileCards()` 末尾の `renderScanBanner();`（`:183`）を削除する（`render()` が毎回呼ぶ。`renderFileCards` の直後は常に `render()` が続くことを `addFiles` / 削除ボタンの経路で確認する）。

- [ ] **Step 4: CSS・コメント**

`styles.css` から `.pg-row.skipped`、`.pg-row.skipped .dot`、`.pg-row .pg-tag`、`.pg-row .pg-tag.t-done`、`.pg-row .pg-tag.t-skip`（`:611-615`）と `.tg.t-skipped`（`:686`）、`.tg.t-none`（`:688`）を削除する。`.tg.t-done` / `.tg.t-pending` は `figure.js` が使うので残す。直前のコメント「ページ状態：意図的スキップを可視化」も消す。

`rect-overlay.js:51` の「`clearSel` 。」を「`clearSel`。」にする。

- [ ] **Step 5: `_page_match_counts`**

```python
    if not store.all():
        return applied, 0
    # 候補 (未置換) は `plan_replacements` の結果から直接数える。`rpc_planPage` は候補を
    # 「`dict_match` が無い文字要素」の側からも絞るが、`_iter_replacements` が返す要素は
    # その条件を満たすものだけなので、再走査せずに数えても行数は一致する。
    pending = sum(
        1 for rep in dict_apply.plan_replacements(page, store)
        if rep.element.dict_match is None and not rep.element.deleted and not rep.element.manual_cover
    )
    return applied, pending
```

`pending_ids` の集合は消す。`test_web_rpc.py::test_state_counts_pending_candidates_and_reverted_matches` が通ることで一致を確かめる。

- [ ] **Step 6: 検証**

Run: `py -3.13 -m pytest pdf-to-svg -q` → PASS（497 → 496。`invalidateAll` の 1 本減）。`py -3.13 -m pytest pdf-to-svg -m e2e -q` → 35 PASS。`py -3.13 scripts/check_comments.py --staged` → 0 errors。

- [ ] **Step 7: コミット**

```
refactor(pdf-to-svg): ページ送りを 1 本にし、未参照の invalidateAll・到達不能分岐・孤児 CSS を消し、件数の集計を matchCount / editCount に寄せる
```

---

### Task 2: 小さな挙動修正（E2E で固定）

**Files:**
- Modify: `pdf-to-svg/resources/web/app.js`（`renderTrim` の `[data-del]` ハンドラ・枠線行）
- Modify: `pdf-to-svg/resources/web/styles.css`（`#trim-dyn` の `gap`）
- Modify: `pdf-to-svg/resources/web/rail.js`（`EMPTY`）
- Modify: `pdf-to-svg/resources/web/index.html:98`（グレーカードの説明文）
- Test: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`

- [ ] **Step 1: E2E を先に書く（失敗させる）**

(a) 右パネル行「削除」が選択中の枠線を消しても削除ボタンと入力欄が残らないこと。`test_border_overlay_resize_and_width_change` の末尾（Task 4c で足した `[data-kind="border"]` の断言の後）に追加:

```python
    # 選択中の枠線を右パネルの行から削除しても、削除ボタン・入力欄が選択中のまま残らない
    page.locator("#trim-stage .border-box").click()
    expect(page.locator("#trim-stage .border-box.sel")).to_have_count(1)
    page.locator('#trim-dyn [data-kind="border"] [data-del]').click()
    expect(page.locator('#trim-dyn [data-kind="border"]')).to_have_count(0)
    expect(page.locator("#btn-deletesel")).to_be_disabled()
    assert page.evaluate("() => window.__state.borderSel") is None
```

(b) レールの空表示の固定文。`test_page_jump_moves_by_number_and_arrows_including_pages_hidden_from_the_rail` の `expect(page.locator("#pagenav .pg-row2")).to_have_count(0)` の直後に `expect(page.locator("#pagenav .empty-note")).to_contain_text("この絞り込みに該当するページはありません")` を足す。

(c) ページ移動のファイル選択とファイルまたぎ。ファイル末尾に追加:

```python
def test_page_jump_file_select_resets_number_and_arrows_cross_files(e2e_page, vector_pdf, ocr_layer_two_page_pdf):
    """ファイル選択を変えても番号を 1 と上限に戻すだけで移動せず、「移動」で確定する。
    前後ボタンは通し番号なのでファイルをまたぐ。"""
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files([str(vector_pdf), str(ocr_layer_two_page_pdf)])
    expect(page.locator("#filelist-count")).to_contain_text("2 ファイル", timeout=30_000)
    page.click("#btn-next")
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))
    # 2 つ目のファイルを選ぶ: 番号は 1、上限は 2 に変わるが、まだ移動しない
    page.select_option("#pgnav-2 .pj-file", "1")
    expect(page.locator("#pgnav-2 .pj-num")).to_have_value("1")
    assert page.evaluate("() => document.querySelector('#pgnav-2 .pj-num').max") == "2"
    assert page.evaluate("() => window.__state.page") == 0
    # 「移動」で 2 つ目のファイルの 1 ページ目 (通し 1) へ
    page.click("#pgnav-2 .pj-go")
    assert page.evaluate("() => window.__state.page") == 1
    expect(page.locator("#pgnav-2 .pj-file")).to_have_value("1")
    # 「前」で通し 0 (1 つ目のファイル) へ戻る = ファイルをまたぐ
    page.click('#pgnav-2 [data-pj="prev"]')
    assert page.evaluate("() => window.__state.page") == 0
    expect(page.locator("#pgnav-2 .pj-file")).to_have_value("0")
    # 「次」を 2 回で通し 2 (2 つ目のファイルの 2 ページ目)。末尾で無効
    page.click('#pgnav-2 [data-pj="next"]')
    page.click('#pgnav-2 [data-pj="next"]')
    assert page.evaluate("() => window.__state.page") == 2
    expect(page.locator("#pgnav-2 .pj-num")).to_have_value("2")
    expect(page.locator('#pgnav-2 [data-pj="next"]')).to_be_disabled()
```

(d) グレーカードの説明文。`test_gray_figure_flow` の `page.check("#mode-gray")` の前に `expect(page.locator("#mode-gray-box .d")).to_have_text("「当社のスチュワードシップ活動」の図を自動で見つけます。")` を足す。

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q -k "border_overlay_resize or page_jump or gray_figure"` → 新しい断言で FAIL。

- [ ] **Step 2: 実装**

`app.js` `renderTrim` の `[data-del]` ハンドラを次にする（`#btn-deletesel` と同じ規律）。

```js
    el.querySelectorAll("[data-del]").forEach(function (b) {
      b.addEventListener("click", async function () {
        // 選択中の枠線・上書きを消すことがあるので、先に選択を解く。残すと `syncDeleteButton`
        // が消えた id を選択中と見なし、入力欄も消えた要素の値のまま残る (`#btn-deletesel` と同じ)。
        clearCoverSel();
        clearBorderSel();
        await rpc("applyDelete", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elIds: [+b.dataset.del] });
        await afterEdit();
      });
    });
```

枠線行の `" ・ " + b.width + " pt"` を `" ・ " + esc(String(b.width)) + " pt"` にする。

`styles.css`: `#trim-dyn` は `index.html` の inline style（`display:flex;flex-direction:column;min-height:0;flex:1;`）で組まれているので、そこに `gap:10px;` を足す。

`rail.js`: `var EMPTY = { 2: …, 3: … };` を `var EMPTY_NOTE = "この絞り込みに該当するページはありません";` にし、`EMPTY[S.phase]` を `EMPTY_NOTE` にする。

`index.html:98` の `.d` を `「当社のスチュワードシップ活動」の図を自動で見つけます。` にする。

- [ ] **Step 3: 検証**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q` → 36 PASS。`py -3.13 -m pytest pdf-to-svg -q` → PASS。`check_comments --staged` → 0 errors。

- [ ] **Step 4: コミット**

```
fix(pdf-to-svg): 右パネルの行から削除するとき選択を先に解き、ページ移動のファイル選択とファイルまたぎを E2E で固定し、グレーカードの説明文と空表示の文言を整える
```

---

### Task 3: `state` のコスト実測（結果次第で最適化）

**Files:**
- Create（作業用・追跡外）: `C:\Users\caads\AppData\Local\Temp\claude\...\scratchpad\perf\perf_state.py`（scratchpad。コミットしない）
- Modify（遅かった場合のみ）: `pdf-to-svg/resources/web/state.js`（`applyState`）, `app.js`（`afterEdit`）, `pdf-to-svg/test/test_pdftosvg_state_js.py`

- [ ] **Step 1: 計測スクリプト**

`pdf-to-svg/test/test_web_rpc.py` の `FakeUndo` と `WebSession` の組み方（`:16-80`）を写し、次を測る。PDF は fitz で 100 ページ（各ページに「Item No.」「A-1042」など辞書に当たる語 5 行 + 当たらない語 20 行）を生成し、`pdf_engine.load_document` で読む（`src/engine/pdf_engine.py` の公開関数名を確認する）。辞書は `store.add(f"WORD{i}", f"語{i}")` を 50 語 + 当たる語 5 語。

```python
import time, statistics
def bench(fn, n=5):
    xs = []
    for _ in range(n):
        t = time.perf_counter(); fn(); xs.append((time.perf_counter() - t) * 1000)
    return statistics.median(xs)
print("state ms:", bench(lambda: rpc_methods.dispatch(session, "state", {})))
print("pageSvg ms:", bench(lambda: rpc_methods.dispatch(session, "pageSvg", {"fileIndex": 0, "pageInFile": 50, "grayscale": False})))
print("planPage ms:", bench(lambda: rpc_methods.dispatch(session, "planPage", {"fileIndex": 0, "pageInFile": 50})))
```

Run: `py -3.13 <scratchpad>/perf/perf_state.py`（`pdf-to-svg/src` を `sys.path` に足す。`conftest.py` と同じ環境変数 `QT_QPA_PLATFORM=offscreen`）。結果 3 行を報告に写す。

- [ ] **Step 2: 判定**

- `state` の中央値が 200 ms 未満かつ `pageSvg` が 300 ms 未満 → 最適化しない。Task 4 で設計書 13 章に計測値を 1 行残す。
- `state` が 200 ms 以上 → `_page_match_counts` の `plan_replacements` を「辞書に一致しうる文字要素が無いページは呼ばない」形にする案を報告に書き、controller の判断を待つ（このタスクでは実装しない）。
- `pageSvg` が 300 ms 以上 → 次の Step 3 を実施する（編集ごとに表示中ページの SVG を作り直すのが体感に効くため）。

- [ ] **Step 3（`pageSvg` ≥ 300 ms のときだけ）: `svgCache` の全消しを表示中ページだけに戻す**

`state.js` `applyState`: `S.svgCache = {}; S.elSel = {};` を `if (!samePages) S.svgCache = {}; S.elSel = {};` にし、docstring に「ページ列が同じなら SVG キャッシュは呼び出し側が必要な分だけ捨てる」を足す。`app.js` `afterEdit(all)` に引数を足し、`svgKeys(pg.fileIndex, pg.pageInFile).forEach(delete)` を既定、`all === true` で `S.svgCache = {}`（Undo / Redo の 3 経路は `afterEdit(true)`。`cover.js` / `border.js` からの `afterEdit()` は既定）。単体テスト `test_applystate_keeps_counts_and_scanned_per_page` の `svgCache == {}` の断言を「同じページ列では保つ」に直し、ページ列が変わると消える断言を足す。E2E 全通し。

- [ ] **Step 4: コミット（Step 3 を実施した場合のみ）**

```
perf(pdf-to-svg): 編集後の SVG キャッシュの破棄を表示中ページだけにし、Undo / Redo のときだけ全ページ分を捨てる
```

---

### Task 4: 原稿・写真・HTML・リリース

**Files:**
- Modify: `docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`（4.2 のステップ欄、`.note-line` の行、グレーカードの文言）, `設計書.md`（13 章に計測値、改訂履歴 2.24）, `操作手順書.md`（3.1 節のグレーカード文言）
- Regenerate: `docs/pdf-to-svg/images/step1_select.png`（`capture_screens.bat`。他の写真も再撮影される。差分が出た分をそのまま採る）, `docs/pdf-to-svg/pdf-to-svg_*.html`

- [ ] **Step 1: 原稿**

- 仕様一覧 4.2 のステップ欄「2・3 共通」を「2. 用語置換 / 3. 削除・枠線」に。手順 4 の表に行を足す: `| 19.2 | 4. 書き出し | 注記 | `.note-line` | 「文字は文字のまま書き出します（後から検索・再編集できます）。」「使ったフォントだけを埋め込みます。」の 1 行注記（旧 緑カードの置き換え） |`。3.1 のグレーカードの説明文を新文言に。
- 設計書 13 章の末尾に「`state` RPC の所要（100 ページ・辞書 55 語、2026-09-18 実測）: state N ms / pageSvg N ms / planPage N ms（Task 3 の値）。編集ごとに `state` を取り直す設計（8 章）の根拠」を 1 段落。改訂履歴に `2.24 | 2026-09-18 | 残作業の整理（ページ送りの 1 本化、右パネル行の削除時の選択解除、空表示の文言、グレーカードの説明文、`state` の所要の実測）` を足す（Task 3 で最適化したならその旨も）。
- 操作手順書 3.1 節にグレーカードの文言が引用されていれば新文言に。改訂履歴 2.11。

- [ ] **Step 2: 写真と HTML**

Run: `docs\pdf-to-svg\_build\capture_screens.bat` → `py -3.13 docs/_build/build_all.py` → `py -3.13 -m pytest docs/_build -q` → PASS。graph-editor の HTML に生成日だけの差分が出たら `git checkout` で戻す。`step1_select.png` を Read して説明文が 1 行に収まっていることを確認する。

- [ ] **Step 3: コミット**

```
docs(pdf-to-svg): 残作業の整理を原稿に反映し（仕様一覧の注記行と書式、設計書 13 章の計測値）、写真と HTML を再生成する
```

- [ ] **Step 4: push とリリース差し替え（controller）**

`git push origin main`（前景）→ `git tag -f 2026.09.08 <HEAD>` → `git push origin -f refs/tags/2026.09.08` → リリースノートの今回の節に「残作業の整理」の 1 行を追記して `gh release edit`。

---

## 自己レビュー

- 0 節の A〜D の全項目が Task 1〜4 のいずれかに対応（A → Task 1、B → Task 2、C → Task 3、D → Task 4）。
- 名前の一貫性: `wirePageFoot(prevId, nextId, nextIndexFn)`、`EMPTY_NOTE`、`afterEdit(all)`（Task 3 Step 3 のみ）。
- Task 3 の判定基準（200 ms / 300 ms）は本計画で決めた閾値。実測値で controller が最終判断する。
