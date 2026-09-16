# PdfToSvg 手順 3 既存不具合の修正 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 手順 3（削除・枠線の編集）で見つかった既存不具合 3 件——入力欄にフォーカスが残って Ctrl+Z が効かない、オーバーレイの一覧取得が追い越されると古い箱が残る、E2E サーバが起動失敗しても黙って別のサーバに繋がる——を直し、ジッター E2E が単独実行でも通るようにする。

**Architecture:** ①`app.js` にキャンバス操作（ラバーバンド開始・編集成功後）で入力欄のフォーカスを外すヘルパを 1 本足し、既存の「入力欄でのキー操作はブラウザ標準の取り消しへ譲る」設計と両立させる。②`rect-overlay.js` の `draw()` に `mountPage` と同じ世代トークンを足し、追い越された古い応答を捨てる。③E2E サーバの待ち合わせを `e2e_server.py` の関数に切り出し、応答があっても子プロセスが死んでいれば起動失敗として止める。

**Tech Stack:** 素の ES モジュール JavaScript、Python 3.13（標準ライブラリ）、pytest + Playwright（Edge チャネル）。

**Spec:** 本計画の「設計（承認済み）」節。2026-09-17 の調査（`.superpowers/sdd/2026-09-16-pdftosvg-step3-ui/progress.md` の【調査】節）と、ユーザーへの選択肢確認 6 問の回答に基づく。

## 設計（承認済み）

1. **入力欄のフォーカスを外す**（ジッター E2E の失敗と、その背後の UX 問題の修正）
   - 何が困るか: 入力欄（上書き語 `#cover-text`・枠線の太さ `#border-width`・色 `#border-color`）に値を打った後、キャンバスを操作してもフォーカスが入力欄に残る。キャンバスの mousedown はテキスト選択を防ぐため `preventDefault()` しており、フォーカスが移らない。その状態の Ctrl+Z は `app.js` の `isTextEntry` ガードで「ブラウザ標準の取り消し」へ譲られ、アプリの Undo に届かない。上書きが戻らず、代わりに入力欄の語が消える。
   - どうするか: **「ラバーバンド開始時」と「編集成功後（`afterEdit`）」の 2 箇所**で、入力欄にフォーカスがあれば外す（`blur()`）。
   - 理由: この 2 箇所は blur による `change` イベントで確定 RPC が飛ばない。ラバーバンド開始時は直前に選択解除（`clearCoverSel` / `clearBorderSel`）を済ませているので、確定処理は「次に置く値」を書くだけで RPC を呼ばない。編集成功後は RPC 済みで、入力欄は同期済みの値なので差分が無い。箱を掴んだ瞬間に外す案は、選択中の要素があると確定 RPC → 再マウント → ドラッグ中の箱が消えるため採らない。
   - 帰結（承認済みの裁定）: 選択中の要素を移動・伸縮したとき、入力欄で編集途中の値があれば確定される（移動と語の変更が 2 段の Undo になる）。利用者が打った値を捨てないという点で自然な挙動として受け入れる。
   - テスト: ジッター E2E に「Ctrl+Z の時点で入力欄にフォーカスが無い」の明示的な確認を足し、実行順への依存を断つ。加えて利用者の操作列そのもの（値を打つ → 範囲を引く → Ctrl+Z）を上書き・枠線それぞれ 1 件ずつ E2E にする。
   - 受け入れ条件: ジッター E2E が**単独実行でも全件実行でも**通る。
2. **`draw()` の世代トークン**
   - 何が困るか: 同じページで `draw()` が 2 回重なると、後から出した一覧 RPC の応答が先に届いたとき、遅れて届いた古い一覧で箱を作り直す。`draw()` は冒頭で箱を全部消すため、古い応答が箱を重複させる。サーバ上のデータは正しく、発生経路は現状ほぼ無いが、将来 `draw()` の呼び元を足すと顕在化する。
   - どうするか: `mountPage` の `mountSeq` と同じ通番トークンを `createRectOverlay` の閉包に持ち、応答が届いた時点で最新の呼び出しでなければ描かない。
   - 理由: 既存の `mountPage` と同じ流儀なので読み手が理解しやすく、`cover.js` / `border.js` の両方が同時に直る。
3. **E2E サーバ起動失敗の即時検知**
   - 何が困るか: E2E はポート 5181 固定でテスト用サーバを起動し、起動できたかを「HTTP 応答があるか」でしか見ない。既に別の E2E が走っていると、後発の子プロセスは bind に失敗して死ぬが、先発のサーバが応答するので「起動成功」と見なされ、2 つのテスト実行が 1 つのサーバを黙って共有して互いの文書を消し合う。
   - どうするか: 応答を確認した後、少し待って子プロセスがまだ生きていることを確かめる。死んでいれば stderr を添えて `RuntimeError` にする。待ち合わせは `e2e_server.py` の関数に切り出し、単体テストで「先にポートを占有されていると失敗する」ことを固定する。
   - 理由: 数行で「黙って混線」を「エラーで止まる」に変えられる。並走できない事実は残るが、次に同じ罠を踏む人が気づける。
4. **flake（一過性の失敗）は監視**。今回観測した flake は上記 3 の混線で説明でき、並走させなければ起きない。再発したら `--tb=short` のログを取って調査する。

## Global Constraints

- Python は常に `py -3.13` を明示して呼ぶ。
- **pytest の一括実行は禁止**。`py -3.13 -m pytest <dir>` の形で対象ディレクトリを個別に指定する（本計画で使うのは `pdf-to-svg`・`docs/_build`・`scripts`）。
- **E2E を別ディレクトリ・別プロセスで並走させない。** テスト用サーバはポート 5181 固定で、並走すると混線する（本計画の Task 3 で「黙って混線」は止まるが、並走できるようにはならない）。
- `xdist` / `pytest-randomly` を入れない。
- ブランチ運用は **main への直接コミット**。トピックブランチを作らない。
- コミットすると post-commit フックが auto-push を試み、pre-push フックが `pytest scripts` → `pytest docs/_build` → `pytest pdf-to-svg` → `pytest graph-editor` → `pytest pdf-to-svg -m e2e` → `pytest graph-editor -m e2e` を順に走らせる。コミット 1 回ごとにこの連鎖が同期的に走るので、コミット前にローカルで該当テストを通しておく。
- コード中の日本語コメント・原稿・コミットメッセージは通常の丁寧な日本語で書く。既存の文体・コメント規約に従う。
- コミットメッセージは Conventional Commits 形式。末尾に次の 2 行を付ける。`Co-Authored-By` のモデル名は**実際にそのコミットを書いた実行主体のもの**にする（別のモデルへ委譲して実装した場合はそのモデル名）。

```
Co-Authored-By: <実際に書いた実行主体のモデル名> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
```

- 「実装を変えたら、原稿 → HTML 生成 までが 1 セット」。原稿の更新は各タスクに含め、HTML の再生成は最後のタスクでまとめて行う。

## ファイル構成

| ファイル | 責務 | 変更の種類 |
|---|---|---|
| `pdf-to-svg/resources/web/app.js` | `blurTextEntry()` を足し、ラバーバンド開始時と `afterEdit` から呼ぶ | 変更 |
| `pdf-to-svg/resources/web/rect-overlay.js` | `draw()` に世代トークン | 変更 |
| `pdf-to-svg/test/e2e_server.py` | `wait_until_serving()`（起動の待ち合わせと失敗検知） | 変更 |
| `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` | ジッター E2E にフォーカス確認、新規 E2E 2 件、fixture が `wait_until_serving` を使う | 変更 |
| `pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py` | `draw()` の追い越しを実ブラウザで検証する単体 | **新規** |
| `pdf-to-svg/test/test_e2e_server.py` | `wait_until_serving` の単体（Edge 不使用） | **新規** |
| `docs/pdf-to-svg/src/設計書.md` | 8 章ステップ 3 節・`rect-overlay.js` 行・E2E の節・改訂履歴 | 変更 |
| `docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md` | テスト表に 3 行 | 変更 |

---

### Task 1: キャンバス操作時に入力欄のフォーカスを外す

**Files:**
- Modify: `pdf-to-svg/resources/web/app.js`（`installCropDrag` の mousedown 510-524 行付近、`afterEdit` 563-568 行付近、`isTextEntry` 1119 行付近の隣）
- Modify: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`（`test_manual_cover_jitter_click_does_not_push_noop_undo` 610-640 行付近、新規 2 件）
- Modify: `docs/pdf-to-svg/src/設計書.md`（8 章ステップ 3 節、830 行付近）
- Modify: `docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`（テスト表末尾）

**Interfaces:**
- Consumes: 既存の `isTextEntry(target) -> boolean`（`app.js:1119`。`input` / `textarea` / contentEditable を真とする）、`clearCoverSel()` / `clearBorderSel()`（`cover.js` / `border.js`）
- Produces: `blurTextEntry()`（`app.js` 内部関数。`document.activeElement` が `isTextEntry` なら `blur()` する）

- [ ] **Step 1: 失敗する E2E を書く**

`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` の `test_manual_cover_jitter_click_does_not_push_noop_undo` の `page.keyboard.press("Control+z")` の**直前**に 1 行足す。

```python
    # Ctrl+Z の時点で入力欄にフォーカスが残っていないこと (残っていると Ctrl+Z はブラウザ標準の
    # 取り消しへ譲られ、アプリの Undo に届かない)。上書きを置いた時点でアプリが外している前提を
    # ここで明示し、テストの結果が実行順に依存しないようにする。
    expect(page.locator("#cover-text")).not_to_be_focused()
    page.keyboard.press("Control+z")
```

同ファイルの `test_manual_cover_jitter_click_does_not_push_noop_undo` の直後へ、新規 2 件を足す。

```python
def test_undo_after_typing_a_word_then_placing_a_cover_undoes_the_cover(e2e_page, ocr_layer_pdf):
    """入力欄に語を打ってから範囲を引いて上書きを置き、そのまま Ctrl+Z を押すと上書きが戻る。

    範囲を引いた時点でアプリが入力欄のフォーカスを外すので、Ctrl+Z がアプリの Undo に届く。
    外さないと Ctrl+Z はブラウザ標準の取り消しへ譲られ、上書きは戻らず入力欄の語が消える。
    """
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="cover"]')
    page.fill("#cover-text", "打った語")
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200
    page.mouse.move(box["x"] + 20 * sx, box["y"] + 110 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 120 * sx, box["y"] + 135 * sy, steps=5)
    page.mouse.up()
    expect(page.locator("#trim-stage .cover-box")).to_have_count(1)
    expect(page.locator("#cover-text")).not_to_be_focused()
    page.keyboard.press("Control+z")
    expect(page.locator("#trim-stage .cover-box")).to_have_count(0)
    # 入力欄の語は消えていない (ブラウザ標準の取り消しに取られていない)
    expect(page.locator("#cover-text")).to_have_value("打った語")


def test_undo_after_typing_a_width_then_placing_a_border_undoes_the_border(e2e_page, ocr_layer_pdf):
    """太さを打ってから枠線を引き、そのまま Ctrl+Z を押すと枠線が戻る (枠線ツールでも同じ)。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    _place_border(page, width="3")
    expect(page.locator("#border-width")).not_to_be_focused()
    page.keyboard.press("Control+z")
    expect(page.locator("#trim-stage .border-box")).to_have_count(0)
    expect(page.locator("#border-width")).to_have_value("3")
```

`_place_border(page, width)` は同ファイルに既にあるヘルパで、枠線ツールを選び `#border-width` に `width` を入れてページ座標 (20,110)-(120,135) へ枠線を 1 つ置き、`.border-box` が 1 個になるまで待つ。

- [ ] **Step 2: テストを走らせて失敗を確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -k "jitter or undo_after_typing" -v`
Expected: 3 件とも FAIL。`not_to_be_focused` で「フォーカスが残っている」旨のタイムアウト。ジッター E2E は**単独実行**で確実に落ちる（全件実行では前のテストの状態次第で通ることがある——それがこの Task で断つ実行順依存）。

- [ ] **Step 3: `blurTextEntry()` を書く**

`pdf-to-svg/resources/web/app.js` の `isTextEntry` の直後（1124 行付近）へ足す。

```javascript
  /** 入力欄にフォーカスが残っていれば外す。キャンバスの操作 (ラバーバンドの開始・編集の成功) の
   *  あとに呼ぶ。入力欄にフォーカスがある間の Ctrl+Z は「ブラウザ標準の取り消しへ譲る」
   *  (`isTextEntry` のガード) ため、外さないと「語を打つ → 範囲を引く → Ctrl+Z」で上書きが戻らず、
   *  代わりに入力欄の語が消える。キャンバスの mousedown はテキスト選択を防ぐため
   *  `preventDefault()` しており、それだけではフォーカスが移らない。
   *  blur で `change` が発火し確定処理 (`commitCoverText` / `commitBorderStyle`) が走るが、
   *  ラバーバンド開始時は直前に選択を解いているので「次に置く値」を書くだけで RPC は飛ばず、
   *  編集成功後は RPC 済みで入力欄は同期済みなので差分が無い。箱を掴んだ瞬間には呼ばない
   *  (選択中の要素があると確定 RPC → 再マウント → ドラッグ中の箱が消えるため)。 */
  function blurTextEntry() {
    var el = document.activeElement;
    if (isTextEntry(el)) el.blur();
  }
```

- [ ] **Step 4: ラバーバンド開始時に呼ぶ**

`installCropDrag` の mousedown ハンドラ内、`if (S.tool === "border") clearBorderSel();` の**直後**（`var rubber = ...` の前）へ 1 行足す。選択解除の**後**に置くこと——前に置くと選択中の要素があれば `change` → 確定 RPC が飛ぶ。

```javascript
      if (S.tool === "cover") clearCoverSel(); // 上書きの空白クリックは選択解除 (新規追加のラバーバンドへ進む)
      if (S.tool === "border") clearBorderSel(); // 枠線も同様
      blurTextEntry(); // 選択を解いたあとで外す (順序を入れ替えると確定 RPC が飛ぶ)
      var rubber = document.createElement("div");
```

- [ ] **Step 5: 編集成功後に呼ぶ**

`afterEdit` を次にする。

```javascript
  async function afterEdit() {
    var pg = S.PAGES[S.page];
    invalidate(pg.fileIndex, pg.pageInFile);
    curElSel(); S.elSel[pkey()] = {};
    blurTextEntry(); // 編集が成功した時点で入力欄のフォーカスを外し、続く Ctrl+Z をアプリの Undo へ通す
    render();
  }
```

- [ ] **Step 6: テストが通ることを確認する（単独実行）**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -k "jitter or undo_after_typing" -v`
Expected: 3 件とも PASS

- [ ] **Step 7: 手順 3 の E2E 全件が通ることを確認する（全件実行）**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q`
Expected: PASS（全件）。特にジッター E2E が全件実行でも通ること、既存の上書き・枠線の E2E（`_place_cover` / `_place_border` の直後に `page.fill` する流れを含む）が blur の追加で壊れていないこと。

- [ ] **Step 8: 非 E2E の全件を確認する**

Run: `py -3.13 -m pytest pdf-to-svg -q`
Expected: PASS

- [ ] **Step 9: 設計書に Ctrl+Z とフォーカスの扱いを書く**

`docs/pdf-to-svg/src/設計書.md` の 8 章、「- 箱をクリックして選ぶと、枠線なら色・太さの入力欄……」で始まる箇条書き（830 行台）の**直後**へ、次の 1 項を足す。

```markdown
- 入力欄（`#cover-text` / `#border-color` / `#border-width`）にフォーカスがある間の Ctrl+Z / Ctrl+Y は、`isTextEntry` のガードでブラウザ標準の取り消しへ譲り、アプリの Undo / Redo は動かさない。キャンバスの mousedown はテキスト選択を防ぐため `preventDefault()` しており、それだけではフォーカスが入力欄から移らないので、**ラバーバンドの開始時と編集の成功後（`afterEdit`）に `blurTextEntry()` でフォーカスを外す**。外さないと「語を打つ → 範囲を引く → Ctrl+Z」で上書きが戻らず、代わりに入力欄の語が消える。この 2 箇所を選ぶのは、blur で発火する `change`（確定処理）が確定 RPC を飛ばさない位置だからである——ラバーバンド開始時は直前に選択を解いているので「次に置く値」を書くだけ、編集成功後は RPC 済みで入力欄は同期済み。箱を掴んだ瞬間には外さない（選択中の要素があると確定 RPC → 再マウント → ドラッグ中の箱が消える）。帰結として、選択中の要素を移動・伸縮したとき入力欄で編集途中の値があれば確定される（移動と語の変更が 2 段の Undo になる）。
```

- [ ] **Step 10: 仕様一覧のテスト表に足す**

`docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md` のテスト表末尾（項番 35 の次）へ 1 行足す。

```markdown
| 36 | `test_pdftosvg_app_flow_e2e.py::test_undo_after_typing_a_word_then_placing_a_cover_undoes_the_cover` ほか | 入力欄に値を打ってから範囲を引いて置き、そのまま Ctrl+Z で戻ること（上書き・枠線それぞれ）。範囲を引いた時点で入力欄のフォーカスが外れ、Ctrl+Z がアプリの Undo に届く（E2E）。ジッター E2E にも Ctrl+Z 時点でフォーカスが無いことの明示的な確認を足し、実行順への依存を断つ | 値を打った直後の Ctrl+Z がアプリの Undo として効く | 未 |
```

- [ ] **Step 11: コミット**

```bash
git add pdf-to-svg/resources/web/app.js pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py docs/pdf-to-svg/src/設計書.md docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md
git commit -m "$(cat <<'EOF'
fix(pdf-to-svg): 範囲を引いたあとの Ctrl+Z がアプリの Undo に届くよう入力欄のフォーカスを外す

Co-Authored-By: <実際に書いた実行主体のモデル名> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

---

### Task 2: `rect-overlay.js` の `draw()` に世代トークンを足す

**Files:**
- Modify: `pdf-to-svg/resources/web/rect-overlay.js`（`createRectOverlay` 冒頭 27-28 行付近、`draw()` 38-46 行付近）
- Create: `pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py`
- Modify: `docs/pdf-to-svg/src/設計書.md`（JS モジュール表の `rect-overlay.js` 行、819 行付近）
- Modify: `docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`（テスト表末尾）

**Interfaces:**
- Consumes: `createRectOverlay(opts)`（既存。`opts.ui.rpc(method, args) -> Promise`、`opts.listRpc` / `opts.listKey` / `opts.boxClass` / `opts.tool` / `opts.getSel` / `opts.setSel` / `opts.getDrag` / `opts.setDrag` / `opts.onSelect`）、`conftest.py` の `edge_page`（headless Edge の共有ページ。`resources/web` を配信する静的サーバの origin）、`pdftosvg_js_harness.js(page, expr)`
- Produces: なし（`draw()` の外から見える契約は変わらない）

- [ ] **Step 1: 失敗する単体テストを書く**

`pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py` を新規作成する。実ブラウザ（`edge_page`）で `rect-overlay.js` を dynamic import し、`ui.rpc` を「外から resolve できる Promise」に差し替えて追い越しを再現する。

```python
# =============================================================================
# test_pdftosvg_rect_overlay_js.py — resources/web/rect-overlay.js の単体（実ブラウザ）
# =============================================================================
# `createRectOverlay` の `draw()` は一覧 RPC を待ってから箱を作る。同じページで `draw()` が
# 重なったとき、後から出した要求の応答が先に届き、遅れて届いた古い一覧で箱を作り直さない
# こと（`mountPage` と同じ世代トークン）を、`ui.rpc` を外から resolve できる Promise に
# 差し替えて確かめる。DOM（`placeRect` の `getBoundingClientRect`）を読むので実ブラウザで回す。
import json

import pytest

from .pdftosvg_js_harness import js

pytestmark = pytest.mark.browser

SETUP = """
window.__roSetup = async () => {
  const st = await import('/state.js');
  const ro = await import('/rect-overlay.js');
  st.S.phase = 3; st.S.tool = "cover";
  const host = document.createElement("div");
  host.style.cssText = "position:relative;width:300px;height:200px";
  host.innerHTML = '<svg viewBox="0 0 300 200" width="300" height="200"></svg>';
  document.body.appendChild(host);
  const pending = [];  // draw() ごとの一覧 RPC の resolve。テストが届く順を決める
  const ui = {
    rpc: () => new Promise((resolve) => { pending.push(resolve); }),
    afterEdit: async () => {},
    pageOf: () => ({ fileIndex: 0, pageInFile: 0 }),
  };
  let sel = null, drag = null;
  const ov = ro.createRectOverlay({
    ui, boxClass: "t-box", tool: "cover", listRpc: "coverList", listKey: "covers", updateRpc: "updateCover",
    getSel: () => sel, setSel: (v) => { sel = v; }, getDrag: () => drag, setDrag: (v) => { drag = v; },
    onSelect: () => {},
  });
  window.__ro = { host, pending, ov, promises: [] };
};
"""

RECT = {"x": 10, "y": 10, "w": 50, "h": 30}


@pytest.fixture(scope="module")
def ro(edge_page):
    edge_page.evaluate(SETUP)
    edge_page.evaluate("window.__roSetup()")
    return edge_page


def _box_ids(page):
    return js(page, "[...window.__ro.host.querySelectorAll('.t-box')].map(b => b.dataset.elId)")


def test_draw_discards_a_stale_list_that_arrives_after_a_newer_one(ro):
    """同じページで draw() が 2 回重なり、先に出した要求の応答が後から届いても、
    古い一覧で箱を作り直さない。"""
    # 2 回続けて draw() を始める。どちらも一覧 RPC の応答待ちで止まる
    n = js(ro, "(() => { const c = window.__ro; c.promises.push(c.ov.draw(c.host)); c.promises.push(c.ov.draw(c.host)); return c.pending.length; })()")
    assert n == 2
    # 2 回目 (新しい方) の応答を先に届ける → 箱は elId 2
    js(ro, "(() => { window.__ro.pending[1]({ covers: [{ elId: 2, rect: %s, text: 'b' }] }); return 0; })()" % json.dumps(RECT))
    js(ro, "window.__ro.promises[1]")  # 2 回目の draw() の完了を待つ
    assert _box_ids(ro) == ["2"]
    # 1 回目 (古い方) の応答を後から届ける → 世代が古いので捨てられ、箱は elId 2 のまま
    js(ro, "(() => { window.__ro.pending[0]({ covers: [{ elId: 1, rect: %s, text: 'a' }] }); return 0; })()" % json.dumps(RECT))
    js(ro, "window.__ro.promises[0]")  # 1 回目の draw() の完了を待つ
    assert _box_ids(ro) == ["2"]
```

- [ ] **Step 2: テストを走らせて失敗を確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py -v`
Expected: FAIL。最後の `assert _box_ids(ro) == ["2"]` が `["1"]` になる（古い応答が箱を消して作り直している）。

- [ ] **Step 3: 世代トークンを足す**

`pdf-to-svg/resources/web/rect-overlay.js` の `createRectOverlay` 冒頭、`var ui = opts.ui;` の直後へ足す。

```javascript
function createRectOverlay(opts) {
  var ui = opts.ui;
  // draw() の世代。同じページで draw() が重なったとき、後から出した要求の応答が先に届くと、
  // 遅れて届いた古い一覧で箱を作り直してしまう (draw() は冒頭で箱を全部消すので、古い応答は
  // 箱を重複させる)。`mountPage` の token と同じ考え方で、応答が届いた時点で最新の呼び出しで
  // なければ描かない。
  var drawSeq = 0;
```

`draw()` を次のように変える（冒頭で番号を取り、RPC の直後で照合する）。

```javascript
  async function draw(host) {
    var seq = ++drawSeq;
    host.querySelectorAll("." + opts.boxClass).forEach(function (b) { b.remove(); });
    if (S.phase !== 3 || S.tool !== opts.tool) { clearSel(); return; }
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    var pg = ui.pageOf();
    var res = await ui.rpc(opts.listRpc, { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
    if (seq !== drawSeq) return;                     // 取得中に新しい draw() が始まった (追い越された)
    if (host.querySelector("svg") !== svgEl) return; // 取得中にページが変わった
```

これより下は変えない。

- [ ] **Step 4: テストが通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py -v`
Expected: PASS

- [ ] **Step 5: 手順 3 の E2E で回帰を確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -k "cover or border" -q`
Expected: PASS（上書き・枠線のオーバーレイ操作が従来どおり動く）

- [ ] **Step 6: 設計書の `rect-overlay.js` 行を直す**

`docs/pdf-to-svg/src/設計書.md` の JS モジュール表、`rect-overlay.js` の行（819 行付近）の末尾「……ジッター判定・取得中のページ切替の検知）は共通 |」を次に変える。

```markdown
……ジッター判定・取得中のページ切替の検知・同じページで `draw()` が重なったときの追い越し検知）は共通。追い越し検知は `mountPage` の `mountSeq` と同じ世代トークンで、`draw()` の呼び出しごとに番号を振り、一覧 RPC の応答が届いた時点で最新の呼び出しでなければ描かない（`draw()` は冒頭で箱を全部消すため、遅れて届いた古い応答をそのまま描くと箱が重複する） |
```

- [ ] **Step 7: 仕様一覧のテスト表に足す**

`docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md` のテスト表末尾（項番 36 の次）へ 1 行足す。

```markdown
| 37 | `test_pdftosvg_rect_overlay_js.py::test_draw_discards_a_stale_list_that_arrives_after_a_newer_one` | `rect-overlay.js` の `draw()` が同じページで 2 回重なり、先に出した一覧 RPC の応答が後から届いても、古い一覧で箱を作り直さないこと（`ui.rpc` を外から resolve できる Promise に差し替えて届く順を制御。実ブラウザ単体） | 追い越された古い応答が箱を重複させない | 未 |
```

- [ ] **Step 8: コミット**

```bash
git add pdf-to-svg/resources/web/rect-overlay.js pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py docs/pdf-to-svg/src/設計書.md docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md
git commit -m "$(cat <<'EOF'
fix(pdf-to-svg): オーバーレイの一覧取得が追い越されても古い一覧で箱を作り直さないようにする

Co-Authored-By: <実際に書いた実行主体のモデル名> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

---

### Task 3: E2E サーバの起動失敗を即時に検知する

> **実装時の訂正（2026-09-17）**: この Task は当初「応答を確認したあと 3 秒待って子プロセスの
> 生死を見る」形で書いたが、実装で前提が崩れた。`ThreadingHTTPServer` は `allow_reuse_address = 1`
> （`SO_REUSEADDR`）を持ち、**Windows では LISTEN 中のポートへの二重 bind が成功する**（Linux は
> TIME_WAIT の再利用のみ）。ポートを先に占有しても子は bind に失敗せず死なない。2 つのサーバが同じ
> ポートで LISTEN し、接続がどちらに届くかは不定になる。
> そこで検知を**「起動前に応答の有無を見る」**へ変える。fixture は子を起動する前に `base_url` へ
> GET し、応答があれば「別のサーバが既に動いている」として `RuntimeError` にする（関数名
> `ensure_port_is_free(base_url)`）。子を起動したあとの待ち合わせ（`wait_until_serving`）は
> 「応答があるまで待つ。応答が無いまま子が死んだら stderr を添えて `RuntimeError`」に留め、
> `settle` は持たない。本番コード（`create_server`。graph-editor `app.py` との並行実装で drift
> 検出の対象）には触らない。先発の子が listening する前の 1〜2 秒の窓で並走を始めた 2 本は
> 検知できないが、並走の検知には十分。根本対策（空きポートを OS に選ばせる）は別途。
> 以下の Step 1・3・4・8・9 はこの方針で読み替える。訂正後の具体的なコードは実装者への指示に
> 記録した（`.superpowers/sdd/2026-09-17-pdftosvg-step3-followup/progress.md`）。

**Files:**
- Modify: `pdf-to-svg/test/e2e_server.py`（`main()` の前に `wait_until_serving()` を足す）
- Modify: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`（`e2e_server` fixture 29-52 行付近）
- Create: `pdf-to-svg/test/test_e2e_server.py`
- Modify: `docs/pdf-to-svg/src/設計書.md`（E2E の節、967 行付近と改訂履歴）
- Modify: `docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`（テスト表末尾）
- Regenerate: `docs/pdf-to-svg/pdf-to-svg_設計.html`

**Interfaces:**
- Consumes: `subprocess.Popen` の子プロセス（`stdout=DEVNULL, stderr=PIPE` で起動したもの）
- Produces: `wait_until_serving(proc, base_url: str, *, attempts: int = 100, interval: float = 0.2, settle: float = 3.0) -> None`（`e2e_server.py`。応答が無ければ待ち、応答があっても `settle` 秒後に子が死んでいれば `RuntimeError`）

- [ ] **Step 1: 失敗する単体テストを書く**

`pdf-to-svg/test/test_e2e_server.py` を新規作成する。Edge は使わない（`e2e` マーカーを付けない）。

```python
# =============================================================================
# test_e2e_server.py — E2E 用サーバの起動待ち合わせ (`e2e_server.wait_until_serving`)
# =============================================================================
# E2E はテスト用サーバを固定ポートで起動する。既に別のサーバが同じポートで動いていると、
# 子プロセスは bind に失敗して死ぬが、先発のサーバが HTTP 応答するので「起動成功」に見え、
# 2 つのテスト実行が 1 つのサーバを黙って共有して互いの文書を消し合う。ここでは、応答が
# あっても子が死んでいれば起動失敗として止まることを、ポートを先に占有して確かめる。
import http.server
import os
import subprocess
import sys
import threading

import pytest

from .e2e_server import wait_until_serving


class _Occupier(http.server.BaseHTTPRequestHandler):
    """ポートを先に取って 200 を返すだけのサーバ (別の E2E が走っている状況の代わり)。"""

    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_wait_until_serving_fails_when_another_server_already_holds_the_port():
    """先にポートを占有されていると、子は bind に失敗して死ぬ。応答はあるが自分の子ではないので
    黙って混線させず RuntimeError にする。"""
    occupier = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Occupier)
    port = occupier.server_address[1]
    threading.Thread(target=occupier.serve_forever, daemon=True).start()
    try:
        env = dict(os.environ, PDFTOSVG_E2E_PORT=str(port))
        proc = subprocess.Popen(
            [sys.executable, os.path.join(os.path.dirname(__file__), "e2e_server.py")],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            with pytest.raises(RuntimeError, match="別のサーバ"):
                wait_until_serving(proc, f"http://127.0.0.1:{port}")
        finally:
            proc.kill()
            proc.wait()
    finally:
        occupier.shutdown()
        occupier.server_close()


def test_wait_until_serving_returns_when_the_child_itself_is_serving():
    """ポートが空いていれば子が起動し、応答した時点で戻る (子は生きている)。"""
    # 空きポートを OS から借りて、閉じた直後に子へ渡す (probe と bind の間に他プロセスが奪う
    # 可能性は残るが、テストとしては十分低い)
    probe = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Occupier)
    port = probe.server_address[1]
    probe.server_close()
    env = dict(os.environ, PDFTOSVG_E2E_PORT=str(port))
    proc = subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(__file__), "e2e_server.py")],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        wait_until_serving(proc, f"http://127.0.0.1:{port}")  # 例外が出ないこと
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()
```

- [ ] **Step 2: テストを走らせて失敗を確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_e2e_server.py -v`
Expected: FAIL（`ImportError: cannot import name 'wait_until_serving'`）

- [ ] **Step 3: `wait_until_serving()` を書く**

`pdf-to-svg/test/e2e_server.py` の `TOKEN = ...` の直後、`def main()` の前へ足す。ファイル冒頭の `import` に `import time`、`import urllib.error`、`import urllib.request` を加える。

```python
def _stderr_text(proc: subprocess.Popen) -> str:
    return proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""


def wait_until_serving(
    proc: subprocess.Popen, base_url: str, *, attempts: int = 100, interval: float = 0.2, settle: float = 3.0
) -> None:
    """子プロセス ``proc`` が ``base_url`` で応答し始めるまで待ち、起動失敗なら ``RuntimeError``。

    応答があっただけでは「自分の子が起動した」とは言えない。同じポートで別のサーバが既に
    動いていると、子は bind に失敗して死ぬが、先発のサーバが応答するので起動成功に見える
    (2 つのテスト実行が 1 つのサーバを黙って共有し、互いの文書を消し合う)。そこで応答を
    確認したあと ``settle`` 秒待ち、子がまだ生きていることまで確かめる。``settle`` を 3 秒に
    しているのは、子が Python の起動と import を終えて bind に失敗し終了するまで 2 秒程度
    かかるため (短いと、まだ import 中の子を「生きている」と見誤る)。
    """
    for _ in range(attempts):
        try:
            urllib.request.urlopen(base_url + "/", timeout=1)
        except urllib.error.HTTPError:
            pass  # 4xx/5xx でも「サーバが応答した」= 誰かが待ち受けている
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError("e2e server が起動前に終了した: " + _stderr_text(proc))
            time.sleep(interval)
            continue
        break
    else:
        raise RuntimeError("e2e server が起動しない")
    time.sleep(settle)
    if proc.poll() is not None:
        raise RuntimeError(
            f"e2e server を {base_url} で起動できなかった (別のサーバが同じポートで応答している): "
            + _stderr_text(proc)
        )
```

`subprocess` は型注釈にだけ使うので、冒頭の `import` に `import subprocess` も加える。

- [ ] **Step 4: E2E の fixture を乗せ換える**

`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` の `e2e_server` fixture を次にする。ファイル冒頭に `from .e2e_server import wait_until_serving` を加える。fixture で使っていた `time` / `urllib.error` / `urllib.request` の import は、`grep -n "time\.\|urllib\." pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` で fixture 以外に使用箇所が無ければ外す（あれば残す）。

```python
@pytest.fixture(scope="module")
def e2e_server():
    env = dict(os.environ, PDFTOSVG_E2E_PORT=str(PORT))
    proc = subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(__file__), "e2e_server.py")],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        # 応答の有無だけでなく子の生死も見る。同じポートで別の E2E が動いていると、子は bind に
        # 失敗して死ぬのに先発のサーバが応答して起動成功に見え、黙って混線するため
        wait_until_serving(proc, BASE)
        yield BASE
    finally:
        proc.kill()
        proc.wait()
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_e2e_server.py -v`
Expected: PASS（2 件。1 件目は 3 秒ほどかかる）

- [ ] **Step 6: E2E が従来どおり起動して通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q`
Expected: PASS（fixture の乗せ換えで起動が壊れていないこと。起動が 3 秒遅くなるのは想定どおり）

- [ ] **Step 7: 非 E2E の全件を確認する**

Run: `py -3.13 -m pytest pdf-to-svg -q`
Expected: PASS（`test_e2e_server.py` の 2 件を含む）

- [ ] **Step 8: 設計書の E2E の節と改訂履歴を直す**

`docs/pdf-to-svg/src/設計書.md` の、E2E を説明している段落（「ページの端をまたいでドラッグしても上書きが置かれること……`test_pdftosvg_app_flow_e2e.py::test_manual_cover_drag_past_the_page_edge_still_places_a_cover` が実 Edge で確かめる。」を含む段落、967 行付近）の末尾へ次を足す。

```markdown
E2E のテスト用サーバは `e2e_server.py` がポート 5181 固定で起動し、`e2e_server` fixture は `wait_until_serving` で待ち合わせる。応答の有無だけでなく、応答を確認したあと 3 秒待って子プロセスがまだ生きていることまで確かめる——同じポートで別の E2E が動いていると、子は bind に失敗して死ぬのに先発のサーバが応答して起動成功に見え、2 つのテスト実行が 1 つのサーバを黙って共有して互いの文書を消し合うためである。`test_e2e_server.py` がポートを先に占有した状況で `RuntimeError` になることを固定する。E2E を別ディレクトリ・別プロセスで並走させてはならない。
```

同ファイル冒頭の改訂履歴（`- 2.16 | 2026-09-17 | ……` の行）の直後へ 1 行足し、`version: "2.16"` を `version: "2.17"` に上げる。

```markdown
  - 2.17 | 2026-09-17 | 8 章ステップ 3 節に入力欄のフォーカスと Ctrl+Z の扱い（`blurTextEntry`）を追記、JS モジュール表の `rect-overlay.js` 行に `draw()` の追い越し検知（世代トークン）を追記、E2E の節にテスト用サーバの起動失敗検知（`wait_until_serving`）を追記
```

- [ ] **Step 9: 仕様一覧のテスト表に足す**

`docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md` のテスト表末尾（項番 37 の次）へ 1 行足す。

```markdown
| 38 | `test_e2e_server.py::test_wait_until_serving_fails_when_another_server_already_holds_the_port` ほか | E2E 用サーバの待ち合わせ `wait_until_serving` が、同じポートを先に占有された状況では子プロセスの死を検知して `RuntimeError` になること、ポートが空いていれば子の起動を待って戻ること（Edge 不使用の単体） | E2E の並走が黙って混線せずエラーで止まる | 未 |
```

- [ ] **Step 10: HTML を再生成する**

Run: `py -3.13 docs/_build/build_all.py --project pdf-to-svg`
Expected: `docs/pdf-to-svg/pdf-to-svg_設計.html` が更新される（Task 1〜3 の原稿変更をまとめて反映）

- [ ] **Step 11: 原稿まわりのテストを走らせる**

Run: `py -3.13 -m pytest docs/_build -q`
Expected: PASS

Run: `py -3.13 -m pytest scripts -q`
Expected: PASS（コメント規約検査）

- [ ] **Step 12: コミット**

```bash
git add pdf-to-svg/test/e2e_server.py pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py pdf-to-svg/test/test_e2e_server.py docs/pdf-to-svg/src/設計書.md docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md docs/pdf-to-svg/pdf-to-svg_設計.html docs/superpowers/plans/2026-09-17-pdftosvg-step3-followup.md
git commit -m "$(cat <<'EOF'
test(pdf-to-svg): E2E 用サーバの起動失敗を検知し、別のサーバへ黙って繋がらないようにする

Co-Authored-By: <実際に書いた実行主体のモデル名> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

計画書（`docs/superpowers/plans/2026-09-17-pdftosvg-step3-followup.md`）はこのコミットへ同梱する。

---

## 完了の確認

すべてのタスクを終えたら、pre-push フックと同じ順で通しておく。**E2E は並走させない。**

```
py -3.13 -m pytest scripts
py -3.13 -m pytest docs/_build
py -3.13 -m pytest pdf-to-svg
py -3.13 -m pytest graph-editor
py -3.13 -m pytest pdf-to-svg -m e2e
py -3.13 -m pytest graph-editor -m e2e
```

さらに、ジッター E2E を**単独で**回して通ることを確認する（この計画の受け入れ条件）。

```
py -3.13 -m pytest pdf-to-svg -m e2e -k jitter
```

実際のアプリを起動して手で触り、次を確かめる。

1. 上書き語を打ち、範囲を引いて上書きを置き、そのまま Ctrl+Z を押すと上書きが戻り、入力欄の語は残る。
2. 枠線の太さを打ち、枠線を引き、そのまま Ctrl+Z を押すと枠線が戻る。
3. 置いた上書き・枠線の移動・伸縮・色・太さの変更が従来どおり動く。
