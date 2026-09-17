# PdfToSvg 画面の見直し 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 手順 2・3 のページごとの確認（要確認 / 確認済み / スキップ）を撤去し、レールと右パネルを「辞書に一致したページ」「編集したページ」の件数で組み直す。手順 2・3 にページ移動の部品を置き、手順 1 のスキャン画像の案内を常設バナーとバッジに、グレースケールの選択を 2 択カードにする。手順 4 のまとめを表にし、Undo / Redo に文字ラベルを付ける。

**Architecture:** サーバの `state` RPC が `changed2 / changed3` の代わりにページごとの件数 `matches2`（置換済み・未置換）と `edits3`（削除・枠線・上書き）を返し、クライアントの `state.js` はそれと `scanned` をそのまま持つ（ページの確認状態は持たない）。レール（`rail.js`）・右パネル（`app.js`）・手順 4 のまとめはすべてこの件数から描く。ページ移動は新しい `page-jump.js` の 1 部品を手順 2・3 で共有する。

**Tech Stack:** Python 3.13 標準ライブラリ + PyMuPDF（サーバ）、素の JavaScript（ES module。フレームワーク無し）、pytest + Playwright（実 Edge）で単体・E2E、`docs/_build/build_all.py` で原稿から HTML 生成。

**Spec:** `docs/superpowers/specs/2026-09-18-pdftosvg-ui-review-design.md`

## Global Constraints

- Python は常に `py -3.13` で起動する。pytest はディレクトリごとに個別実行する（`py -3.13 -m pytest pdf-to-svg`。`scripts` / `docs/_build` / `graph-editor` と一括にしない）。
- E2E は `py -3.13 -m pytest pdf-to-svg -m e2e` で別に走らせる。既定の実行では `e2e` マーカーは除外される。
- コミットごとに post-commit の auto-push が pre-push の検証一式（`check_comments` → 4 ディレクトリの pytest → E2E 2 種）を同期的に走らせる。メモリ不足で止められたら `git push origin main` を手で再実行する。
- 新規 JS ファイルは先頭に `// ====…` の装飾ボックスヘッダ（既存ファイルと同じ 3 行）を置く（`scripts/check_comments.py` が警告する）。
- 画面の説明文は 1 文ごとに改行し、手順を含む「使い方」は 1 文 1 項目の箇条書きにする。右パネル（幅 318px・本文 12px）の文は全角 19 文字程度に収める。件数を並べる行は項目ごとに `white-space: nowrap`。
- 文言は仕様書 3 節の値を逐語で使う（例: 見出し「このページで置き換えた語」、絞り込み「辞書に一致したページだけ」「すべてのページ」「編集したページだけ」、ボタン「前のページ」「次の一致ページ」「次のページ」「移動」）。
- 原稿（`docs/pdf-to-svg/src/*.md`）・コードコメント・コミットメッセージは通常の日本語（丁寧体）で書く。
- コミットメッセージの末尾に次の 2 行を付ける:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
  ```

---

## ファイル構成

| ファイル | 役割（この計画での変更） |
|---|---|
| `pdf-to-svg/src/web/rpc_methods.py` | `state` に `matches2` / `edits3` を追加、`changed2` / `changed3` を撤去。件数の述語を `_page_match_counts` / `_page_edit_counts` / `_folded_ids` に切り出し、`removedList` と共有 |
| `pdf-to-svg/resources/web/state.js` | 状態モデルの置き換え（`scanned` / `matches2` / `edits3`）。`railPages` / `matchCount` / `editCount` / `nextMatched` / `scannedCountOf` / `matchTotals` / `editTotals` を追加。確認状態と選択集合を撤去 |
| `pdf-to-svg/resources/web/rail.js` | 手順 2・3 のレール（見出し・絞り込み・件数タグ）。一括操作を撤去 |
| `pdf-to-svg/resources/web/page-jump.js`（新規） | 「ページへ移動」部品。`resolveJump`（純粋関数）と `buildPageJump`（描画・配線） |
| `pdf-to-svg/resources/web/app.js` | 右パネル（手順 2・3）、遷移、フッターの案内、手順 4 のまとめ、手順 1 のバナー・バッジ・2 択カード、撤去 |
| `pdf-to-svg/resources/web/index.html` | ガード・`pageact` / `sum` / モーダル / `exp-noskip` / `modebox` / 緑カードの撤去、2 択カード・バナー・ページ移動の器・Undo/Redo ラベル |
| `pdf-to-svg/resources/web/styles.css` | 撤去したクラスの削除、`.mode-card` / `.banner` / `.chip` / `.page-jump` / `.howto` / `.lines` / `.sum-table` の追加 |
| `pdf-to-svg/resources/web/icons.js` | `chevL`（左向きの山形）を追加 |
| `pdf-to-svg/test/test_web_rpc.py` | `state` の件数テスト |
| `pdf-to-svg/test/test_pdftosvg_state_js.py` | 状態モデルのテスト書き換え |
| `pdf-to-svg/test/test_pdftosvg_page_jump_js.py`（新規） | `resolveJump` の単体 |
| `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` | 通し・スキャン・ページ移動の E2E 書き換え |
| `docs/pdf-to-svg/_build/capture_screens.py` | ガード撮影の撤去、2 択カードの操作 |
| `docs/pdf-to-svg/src/設計正典.md` / `設計書.md` / `PdfToSvg_仕様一覧.md` / `操作手順書.md` | 原稿の更新 |
| `docs/pdf-to-svg/images/*.png` | 再撮影（`step2d_guard.png` は削除） |

---

### Task 1: `state` RPC にページごとの件数（`matches2` / `edits3`）を返す

**Files:**
- Modify: `pdf-to-svg/src/web/rpc_methods.py:68-79`（`_page_has_replacements`）, `:102-163`（`rpc_state`）, `:280-298`（`rpc_removedList`）
- Test: `pdf-to-svg/test/test_web_rpc.py`

**Interfaces:**
- Produces: `state` の返り値に `matches2: list[list[int]]`（通しページ順の `[applied, pending]`）と `edits3: list[list[int]]`（`[removed, borders, covers]`）。`changed2` / `changed3` は返さない。

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_web_rpc.py` の `test_state` を次に置き換え、続けて 2 本を足す（`test_state` の直後）。

```python
def test_state(session):
    st = rpc_methods.dispatch(session, "state", {})
    assert st["total"] == 1
    assert st["files"][0]["pages"] == 1
    # ページごとの件数だけを返す (確認状態は持たない)。changed2 / changed3 は廃止
    assert st["matches2"] == [[1, 0]]   # dict_match のある要素 1 つ、未適用の候補 0
    assert st["edits3"] == [[0, 0, 0]]
    assert "changed2" not in st and "changed3" not in st


def test_state_counts_pending_candidates_and_reverted_matches(session):
    """未適用の候補は pending に数え、戻した箇所は applied から pending へ移る。"""
    rpc_methods.dispatch(session, "dictAdd", {"source": "A-1042", "target": "ボルト"})
    assert rpc_methods.dispatch(session, "state", {})["matches2"] == [[1, 1]]
    rpc_methods.dispatch(session, "reapplyDictPage", {"fileIndex": 0, "pageInFile": 0})
    assert rpc_methods.dispatch(session, "state", {})["matches2"] == [[2, 0]]
    body = session.page(0, 0).elements[1]
    rpc_methods.dispatch(session, "revertDictMatch",
                         {"fileIndex": 0, "pageInFile": 0, "elId": body.id})
    assert rpc_methods.dispatch(session, "state", {})["matches2"] == [[1, 1]]


def test_state_counts_removed_borders_and_covers_per_page(session):
    """削除・枠線・上書きの件数を、各一覧 RPC と同じ述語で数える。"""
    page = session.page(0, 0)
    body = page.elements[1]
    rpc_methods.dispatch(session, "applyDelete",
                         {"fileIndex": 0, "pageInFile": 0, "elIds": [body.id]})
    rpc_methods.dispatch(session, "addBorder",
                         {"fileIndex": 0, "pageInFile": 0,
                          "rect": {"x": 5, "y": 5, "w": 100, "h": 80},
                          "color": "#ff0000", "width": 2})
    rpc_methods.dispatch(session, "addCover",
                         {"fileIndex": 0, "pageInFile": 0,
                          "rect": {"x": 10, "y": 100, "w": 60, "h": 12}, "text": "上書き"})
    st = rpc_methods.dispatch(session, "state", {})
    assert st["edits3"] == [[1, 1, 1]]
    # 折返し畳み込みで隠した行は「削除」に数えない (removedList と同じ)
    from model.elements import DictRevertInfo
    hdr = page.elements[0]
    hdr.dict_revert = DictRevertInfo(text="Item", bbox=hdr.bbox, wrap_align=None,
                                     origin_y=hdr.origin_y, extra_ids=[body.id])
    assert rpc_methods.dispatch(session, "state", {})["edits3"] == [[0, 1, 1]]
```

`test_state_changed2_true_for_pending_candidates`（`:597-602`）は削除する（上の 2 本目が同じ観点を件数で固定する）。

- [ ] **Step 2: テストが失敗することを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_web_rpc.py -q -k "test_state"`
Expected: FAIL（`KeyError: 'matches2'`）

- [ ] **Step 3: 実装する**

`rpc_methods.py` の `_page_has_replacements`（`:68-79`）を次の 3 関数に置き換える。

```python
def _page_match_counts(page: Page, store: DictionaryStore) -> Tuple[int, int]:
    """手順 2 のページ件数 `[置換済み, 未置換]`。`rpc_planPage` が返す行と同じ述語で数える
    (置換済み = `dict_match` を持つ文字要素、未置換 = 辞書に一致するが未適用の候補)。
    レールのタグ・件数カード・手順 4 のまとめはこの数から描くため、`planPage` の行数と
    ここの数が食い違うと画面の中で件数が合わなくなる。"""
    applied = sum(
        1 for e in page.elements
        if isinstance(e, TextElement) and not e.deleted and not e.manual_cover
        and e.dict_match is not None
    )
    if not store.all():
        return applied, 0
    pending_ids = {rep.element.id for rep in dict_apply.plan_replacements(page, store)}
    pending = sum(
        1 for e in page.elements
        if isinstance(e, TextElement) and not e.deleted and not e.manual_cover
        and e.dict_match is None and e.id in pending_ids
    )
    return applied, pending


def _folded_ids(page: Page) -> set:
    """辞書の折返し畳み込みで隠した後続行の id。利用者が削除したものではないので
    「削除した要素」から除く (`rpc_removedList` と `_page_edit_counts` が共有する)。"""
    folded = set()
    for el in page.elements:
        if isinstance(el, TextElement) and not el.deleted and el.dict_revert is not None:
            folded.update(el.dict_revert.extra_ids)
    return folded


def _page_edit_counts(page: Page) -> Tuple[int, int, int]:
    """手順 3 のページ件数 `[削除, 枠線, 上書き]`。`removedList` / `borderList` / `coverList`
    と同じ述語で数える。"""
    folded = _folded_ids(page)
    removed = sum(1 for el in page.elements if el.deleted and el.id not in folded)
    borders = sum(
        1 for e in page.elements
        if isinstance(e, RectElement) and e.manual_border and not e.deleted
    )
    covers = sum(
        1 for e in page.elements
        if isinstance(e, TextElement) and e.manual_cover and not e.deleted
    )
    return removed, borders, covers
```

`rpc_state` のループを次に変える（`changed2` / `changed3` の行を削除し、`matches2` / `edits3` を足す）。

```python
    matches2: List[List[int]] = []
    edits3: List[List[int]] = []
    scanned: List[bool] = []
    for fi, d in enumerate(s.docs):
        files.append(
            {
                "id": fi,
                "name": Path(d.source_path).name,
                "pages": len(d.pages),
                "size": _file_size_str(d),
            }
        )
        for pi, pg in enumerate(d.pages):
            pages.append({"fileIndex": fi, "pageInFile": pi})
            # 手順 2: ページごとの置換済み・未置換の件数。手順 3: 削除・枠線・上書きの件数。
            # クライアントはページの確認状態を持たず、レール・右パネル・まとめをこの数から描く。
            matches2.append(list(_page_match_counts(pg, s.store)))
            edits3.append(list(_page_edit_counts(pg)))
            scanned.append(bool(pg.is_scanned))
    ...
    return {
        "files": files,
        "pages": pages,
        "matches2": matches2,
        "edits3": edits3,
        "scanned": scanned,
        ...（scannedPages 以降は変更なし）
    }
```

`rpc_removedList` の `folded` の組み立て（`:284-287`）を `folded = _folded_ids(pg)` に置き換える。`rpc_state` の docstring を「ファイル・ページ一覧と、各ページの置換・編集の件数を返す。」にする。冒頭のコメント「クライアントの読者は files/pages/total/changed2/changed3/scanned のみ」も `matches2/edits3` に直す。`from typing import List` の行に `Tuple` を足す（無ければ）。`RectElement` の import を確認する（`rpc_borderList` が既に使っているので既存）。

- [ ] **Step 4: テストが通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_web_rpc.py -q`
Expected: PASS（`changed2` を参照する他のテストが無いことも確認する: `grep -n changed2 pdf-to-svg/test/*.py` が空）

- [ ] **Step 5: コミット**

```bash
git add pdf-to-svg/src/web/rpc_methods.py pdf-to-svg/test/test_web_rpc.py
git commit -m "feat(pdf-to-svg): state RPC がページごとの置換・編集の件数 (matches2 / edits3) を返し changed2 / changed3 を廃止する"
```

（この時点でクライアントは `changed2` を読めなくなり手順 2 の一覧が「置換なし」になる。次の Task 2〜4 を同じ日のうちに続けて進める。）

---

### Task 2: `state.js` の状態モデルを件数ベースに置き換える

**Files:**
- Modify: `pdf-to-svg/resources/web/state.js`（全体）
- Test: `pdf-to-svg/test/test_pdftosvg_state_js.py`

**Interfaces:**
- Produces（`state.js` の export）:
  - `S.scanned: boolean[]`, `S.matches2: {applied, pending}[]`, `S.edits3: {removed, borders, covers}[]`, `S.filterFor = {2: "matched", 3: "all"}`
  - `matchCount(g): number`, `editCount(g): number`
  - `railPages(phase): number[]`（絞り込みを通した通し index）
  - `nextMatched(from): number`（無ければ -1）
  - `scannedCountOf(fi): number`, `scannedTotal(): number`
  - `matchTotals(): {applied, pending, pages, scanned}`, `editTotals(): {pages, removed, borders, covers}`
  - `skipsPhase2()`, `firstEditablePage2()`, `landOnPhase2()`, `phaseAfterLoad()`, `phaseBeforeTrim()`, `phaseBeforeExport()`, `stepAllowed(n)` は名前と意味を維持
  - `exportPageList` は `page / all / spec` のみ
- 撤去: `counts`, `pass`, `initStatus`, `mergeStatus`, `statusArr`, `changedArr`, `selSet`, `statusOfCur`, `selKeys`, `selCount`, `clearSel`, `nextPending`, `firstPending`, `scannedFiles`, `S.status2/3`, `S.changed2/3`, `S.selFor`, `S.guarding`

- [ ] **Step 1: 失敗するテストを書く**

`test_pdftosvg_state_js.py` の `RESET` を次に置き換える。

```python
RESET = """
window.__reset = () => {
  const m = window.__st;
  m.applyState({
    files: [{ name: "a.pdf", pages: 2 }, { name: "b.pdf", pages: 3 }],
    pages: [
      { fileIndex: 0, pageInFile: 0 }, { fileIndex: 0, pageInFile: 1 },
      { fileIndex: 1, pageInFile: 0 }, { fileIndex: 1, pageInFile: 1 }, { fileIndex: 1, pageInFile: 2 },
    ],
    total: 5,
    matches2: [[1, 0], [0, 0], [2, 1], [0, 1], [0, 0]],
    edits3: [[0, 0, 0], [1, 0, 0], [0, 0, 0], [0, 2, 1], [0, 0, 0]],
    scanned: [false, false, false, false, false],
  });
  m.S.phase = 2; m.S.page = 0;
  m.S.filterFor = { 2: "matched", 3: "all" };
  m.S.expMode = "all"; m.S.expFile = 0;
  m.S.gray = false; m.S.figCand = {}; m.S.figSel = {};
  m.S.tool = null; m.S.coverSel = null; m.S.borderSel = null; m.S.elSel = {}; m.S.dragMoved = false;
};
"""
```

次の既存テストを削除する（撤去する関数・状態のテスト）: `test_pure_helpers_counts_tallies_by_status`, `test_pure_helpers_pass_all_always_passes_others_match_only`, `test_pure_helpers_initstatus_derives_pending_none_from_changed`, `test_applystate_initializes_status_from_changed_and_discards_caches`, `test_applystate_reload_of_same_page_list_preserves_confirmation_status`, `test_applystate_toggles_status_to_pending_or_none_on_changed_flip`, `test_applystate_rebuilds_status_via_initstatus_when_page_list_differs`, `test_applystate_discards_rail_selection_and_file_collapse_when_page_list_changes`, `test_applystate_reload_of_same_page_list_preserves_selection_and_collapse`, `test_derived_statusarr_changedarr_switch_by_phase`, `test_derived_selkeys_selcount_clearsel_scope_to_current_phase`, `test_derived_statusofcur_returns_status_of_current_page`, `test_transition_nextpending_prefers_ahead_and_wraps_to_start`, `test_transition_firstpending_searches_from_start_default_zero`, `test_transition_advancephase_moves_2_to_3_to_4_and_clears_guard_and_target_selection`, `test_export_range_noskip_excludes_pages_skipped_in_either_step`, `test_initstatus_marks_scanned_pages_na_regardless_of_changed`, `test_mergestatus_keeps_na_even_when_changed_flips`, `test_counts_tallies_na`, `test_pass_never_shows_na_even_for_all`, `test_applystate_without_scanned_column_has_no_na`, `test_applystate_maps_scanned_to_na_and_preserves_status_on_reload`, `test_nextpending_and_firstpending_never_land_on_na`, `test_export_noskip_keeps_na_pages`, `test_initstatus_and_mergestatus_treat_a_short_scanned_column_as_not_scanned`, `test_applystate_with_a_new_page_list_maps_scanned_via_initstatus`, `test_landonphase2_moves_off_a_scanned_page_to_the_first_editable_one`。

`_apply_with_scanned` ヘルパ（`:495-505`）を次に置き換える。

```python
def _apply(st, scanned, matches2=None, edits3=None):
    js(st, """(a) => window.__st.applyState({
        files: [{ name: "a.pdf", pages: 2 }, { name: "b.pdf", pages: 3 }],
        pages: [
          { fileIndex: 0, pageInFile: 0 }, { fileIndex: 0, pageInFile: 1 },
          { fileIndex: 1, pageInFile: 0 }, { fileIndex: 1, pageInFile: 1 }, { fileIndex: 1, pageInFile: 2 },
        ],
        total: 5, matches2: a.matches2, edits3: a.edits3, scanned: a.scanned,
    })""", {"scanned": scanned,
            "matches2": matches2 or [[1, 0], [0, 0], [2, 1], [0, 1], [0, 0]],
            "edits3": edits3 or [[0, 0, 0], [1, 0, 0], [0, 0, 0], [0, 2, 1], [0, 0, 0]]})
```

新しいテストを追加する（ファイル末尾）。

```python
# ── 件数ベースの状態モデル ──


def test_applystate_keeps_counts_and_scanned_per_page(st):
    assert js(st, "window.__st.S.matches2[2]") == {"applied": 2, "pending": 1}
    assert js(st, "window.__st.S.edits3[3]") == {"removed": 0, "borders": 2, "covers": 1}
    assert js(st, "window.__st.S.scanned") == [False] * 5
    assert js(st, "window.__st.S.svgCache") == {}
    assert js(st, "window.__st.S.elSel") == {}
    assert js(st, "'status2' in window.__st.S") is False
    assert js(st, "'selFor' in window.__st.S") is False


def test_applystate_tolerates_missing_or_short_columns(st):
    # 旧形式 (列なし) や短い列は 0 件・非スキャン扱いへ倒す (例外にしない)
    js(st, """window.__st.applyState({
        files: [{ name: "a.pdf", pages: 2 }], pages: [{ fileIndex: 0, pageInFile: 0 }, { fileIndex: 0, pageInFile: 1 }],
        total: 2, matches2: [[1, 1]], scanned: [true] })""")
    assert js(st, "window.__st.S.matches2") == [{"applied": 1, "pending": 1}, {"applied": 0, "pending": 0}]
    assert js(st, "window.__st.S.edits3") == [{"removed": 0, "borders": 0, "covers": 0}] * 2
    assert js(st, "window.__st.S.scanned") == [True, False]


def test_applystate_drops_collapse_and_figures_only_when_page_list_changes(st):
    js(st, "window.__st.S.collapsed['2:1'] = true")
    _apply(st, [False] * 5)
    assert js(st, "window.__st.S.collapsed") == {"2:1": True}
    js(st, """window.__st.applyState({ files: [{ name: "a.pdf", pages: 1 }], pages: [{ fileIndex: 0, pageInFile: 0 }],
        total: 1, matches2: [[0, 0]], edits3: [[0, 0, 0]], scanned: [false] })""")
    assert js(st, "window.__st.S.collapsed") == {}


def test_matchcount_editcount_and_totals(st):
    assert js(st, "[0,1,2,3,4].map(g => window.__st.matchCount(g))") == [1, 0, 3, 1, 0]
    assert js(st, "[0,1,2,3,4].map(g => window.__st.editCount(g))") == [0, 1, 0, 3, 0]
    assert js(st, "window.__st.matchTotals()") == {"applied": 3, "pending": 2, "pages": 3, "scanned": 0}
    assert js(st, "window.__st.editTotals()") == {"pages": 2, "removed": 1, "borders": 2, "covers": 1}


def test_railpages_phase2_matched_default_and_all_never_include_scanned(st):
    _apply(st, [False, True, False, False, False])
    assert js(st, "window.__st.S.filterFor[2]") == "matched"
    assert js(st, "window.__st.railPages(2)") == [0, 2, 3]
    js(st, "window.__st.S.filterFor[2] = 'all'")
    assert js(st, "window.__st.railPages(2)") == [0, 2, 3, 4]   # 1 はスキャンなので出ない


def test_railpages_phase3_all_default_includes_scanned_and_edited_filters(st):
    _apply(st, [True, False, False, False, False])
    assert js(st, "window.__st.railPages(3)") == [0, 1, 2, 3, 4]
    js(st, "window.__st.S.filterFor[3] = 'edited'")
    assert js(st, "window.__st.railPages(3)") == [1, 3]


def test_nextmatched_searches_ahead_then_wraps_and_skips_scanned(st):
    _apply(st, [False, False, True, False, False])
    assert js(st, "window.__st.nextMatched(0)") == 3     # 2 は一致があるがスキャンなので飛ばす
    assert js(st, "window.__st.nextMatched(3)") == 0     # 末尾まで無ければ先頭から
    _apply(st, [False] * 5, [[0, 0]] * 5)
    assert js(st, "window.__st.nextMatched(0)") == -1


def test_scannedcountof_counts_per_file(st):
    _apply(st, [True, False, True, True, False])
    assert js(st, "[0, 1].map(fi => window.__st.scannedCountOf(fi))") == [1, 2]
    assert js(st, "window.__st.scannedTotal()") == 3


def test_skipsphase2_only_when_every_page_is_scanned(st):
    _apply(st, [True] * 5)
    assert js(st, "window.__st.skipsPhase2()") is True
    assert js(st, "window.__st.phaseAfterLoad()") == 3
    assert js(st, "window.__st.phaseBeforeTrim()") == 1
    assert js(st, "[1,2,3,4].map(n => window.__st.stepAllowed(n))") == [True, False, True, True]
    _apply(st, [True, True, True, True, False])
    assert js(st, "window.__st.skipsPhase2()") is False
    assert js(st, "window.__st.phaseAfterLoad()") == 2


def test_skipsphase2_is_false_with_no_pages(st):
    js(st, "window.__st.applyState({ files: [], pages: [], total: 0, matches2: [], edits3: [], scanned: [] })")
    assert js(st, "window.__st.skipsPhase2()") is False


def test_firsteditablepage2_prefers_a_matched_page_then_a_non_scanned_one(st):
    assert js(st, "window.__st.firstEditablePage2()") == 0
    _apply(st, [True, False, False, False, False], [[0, 0], [0, 0], [0, 0], [1, 0], [0, 0]])
    assert js(st, "window.__st.firstEditablePage2()") == 3
    _apply(st, [True, False, False, False, False], [[0, 0]] * 5)
    assert js(st, "window.__st.firstEditablePage2()") == 1


def test_landonphase2_moves_off_a_scanned_page_only(st):
    _apply(st, [True, True, False, True, False], [[0, 0], [0, 0], [0, 0], [0, 0], [1, 0]])
    js(st, "window.__st.S.page = 0; window.__st.landOnPhase2()")
    assert js(st, "window.__st.S.page") == 4
    js(st, "window.__st.S.page = 2; window.__st.landOnPhase2()")
    assert js(st, "window.__st.S.page") == 2   # 対象ページに居るときは動かさない


def test_advancephase_moves_2_to_3_to_4_and_resets_ui(st):
    js(st, "window.__st.S.page = 4; window.__st.S.tool = 'cover'")
    js(st, "window.__st.advancePhase()")
    assert js(st, "window.__st.S.phase") == 3
    assert js(st, "window.__st.S.page") == 0
    assert js(st, "window.__st.S.tool") is None
    js(st, "window.__st.advancePhase()")
    assert js(st, "window.__st.S.phase") == 4


def test_export_modes_are_page_all_spec_only(st):
    js(st, "window.__st.S.expMode = 'noskip'")
    assert js(st, "window.__st.exportPageList('', () => [])") == []   # 未知のモードは空
    assert js(st, "typeof window.__st.counts") == "undefined"
    assert js(st, "typeof window.__st.nextPending") == "undefined"
```

残す既存テストのうち `changed2` / `changed3` を `applyState` に渡しているもの（`test_applystate_resets_current_page_when_page_count_shrinks`, `test_apply_state_with_new_page_list_drops_fig_state` など）は、引数を `matches2: [[0, 0]], edits3: [[0, 0, 0]], scanned: [false]`（ページ数分）に書き換える。`test_transition_resetphaseui_*` / `test_transition_advancephase_resets_selection_and_tool` / 書き出し範囲（`all` / `spec` / `page` / `zipname`）/ グレー / 図 / `chunkBySize` のテストは変更なし。

- [ ] **Step 2: テストが失敗することを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_state_js.py -q`
Expected: FAIL（`matchCount is not a function` 等）

- [ ] **Step 3: `state.js` を書き換える**

`S` の定義（`:12-46`）: 次の行を削除する。

```js
  changed2: [], changed3: [],   // ...
  status2: [], status3: [],     // ...
  guarding: false,      // ...
  selFor: { 2: {}, 3: {} },     // ...
```

代わりに次を入れる（`TOTAL: 0,` の直後）。

```js
  scanned: [],          // ページごとの純スキャン判定 (`state` の `scanned[]`)。手順 2 の対象外の判定源
  matches2: [],         // ページごとの {applied, pending} (辞書に一致した箇所の 置換済み / 未置換 の件数)
  edits3: [],           // ページごとの {removed, borders, covers} (削除 / 枠線 / 上書き の件数)
```

`filterFor` を `filterFor: { 2: "matched", 3: "all" },   // レールの絞り込み (手順 2: matched|all / 手順 3: all|edited)` にする。`expMode` のコメントを `// 書き出しモード: page/all/spec` にする。

セクション 2「純粋ヘルパ」の `counts` / `pass` / `initStatus` を削除し、セクション 3 の `statusArr` / `changedArr` / `selSet` / `statusOfCur` / `selKeys` / `selCount` / `clearSel` を削除する（`pkey` / `curElSel` は残す）。

セクション 4 の `mergeStatus`（`:125-142`）と `nextPending` / `firstPending`（`:181-188`）と `scannedFiles`（`:194-203`）を削除し、`applyState` を次に置き換える。

```js
/** サーバの `state` RPC 結果を取り込み、派生列 (FILE_START) とキャッシュを組み直す。
 *
 * ページの確認状態は持たないので、件数 (`matches2` / `edits3`) とスキャン判定 (`scanned`) は
 * 毎回そのまま取り込む。旧形式 (列なし) や短い列は 0 件・非スキャン扱いへ倒す (例外にしない)。
 * ファイル追加・削除でページ列が変わったときだけ、通し index をキーに持つ折り畳み・図の
 * 候補・採用を捨てる (持ち越すと別のページ・別のファイルを指す)。
 */
function applyState(st) {
  var samePages = samePageList(S.PAGES, st.pages);
  S.FILES = st.files; S.PAGES = st.pages; S.TOTAL = st.total;
  S.scanned = S.PAGES.map(function (_pg, g) { return !!(st.scanned && st.scanned[g]); });
  S.matches2 = S.PAGES.map(function (_pg, g) {
    var m = st.matches2 && st.matches2[g];
    return { applied: m ? (m[0] | 0) : 0, pending: m ? (m[1] | 0) : 0 };
  });
  S.edits3 = S.PAGES.map(function (_pg, g) {
    var e = st.edits3 && st.edits3[g];
    return { removed: e ? (e[0] | 0) : 0, borders: e ? (e[1] | 0) : 0, covers: e ? (e[2] | 0) : 0 };
  });
  if (!samePages) { S.collapsed = {}; S.figCand = {}; S.figSel = {}; }
  S.FILE_START = []; var s = 0;
  S.FILES.forEach(function (f, i) { S.FILE_START[i] = s; s += f.pages; });
  S.svgCache = {}; S.elSel = {};
  if (S.page >= S.TOTAL) S.page = 0;
}
```

`invalidateAll` の直後に次を追加する。

```js
/** 通しページ g の辞書一致の件数 (置換済み + 未置換)。0 なら「辞書に一致しないページ」 */
function matchCount(g) { var m = S.matches2[g]; return m ? m.applied + m.pending : 0; }
/** 通しページ g の編集の件数 (削除 + 枠線 + 上書き)。0 なら「編集していないページ」 */
function editCount(g) { var e = S.edits3[g]; return e ? e.removed + e.borders + e.covers : 0; }

/** レールに出す通しページ index の配列。絞り込み (`S.filterFor`) を通した結果で、
 *  手順 2 はスキャンページを絞り込みに関わらず出さない (辞書が構造的に当たらないため)。
 *  手順 3 はスキャンページも出す (上書きの対象になる)。レールの行・ファイル行の件数はここを通す。 */
function railPages(phase) {
  var filt = S.filterFor[phase]; var out = [];
  S.PAGES.forEach(function (_pg, g) {
    if (phase === 2) {
      if (S.scanned[g]) return;
      if (filt === "matched" && !matchCount(g)) return;
    } else if (filt === "edited" && !editCount(g)) return;
    out.push(g);
  });
  return out;
}
/** 手順 2 の「次の一致ページ」。from より後ろで辞書に一致 (スキャン以外) のページ、無ければ先頭から。
 *  無ければ -1 */
function nextMatched(from) {
  for (var i = from + 1; i < S.TOTAL; i++) if (!S.scanned[i] && matchCount(i)) return i;
  for (var j = 0; j < from; j++) if (!S.scanned[j] && matchCount(j)) return j;
  return -1;
}
/** ファイル fi のスキャンページ数 (手順 1 のカードのバッジ) */
function scannedCountOf(fi) {
  var f = S.FILES[fi]; if (!f) return 0;
  var start = S.FILE_START[fi] || 0; var n = 0;
  for (var p = 0; p < f.pages; p++) if (S.scanned[start + p]) n++;
  return n;
}
/** スキャンページの総数 (手順 1 のバナー・手順 2 の見出し) */
function scannedTotal() { return S.scanned.filter(Boolean).length; }
/** 手順 2 のまとめ: 置換済み・未置換の箇所数、一致のあるページ数、スキャンページ数 */
function matchTotals() {
  var t = { applied: 0, pending: 0, pages: 0, scanned: scannedTotal() };
  S.matches2.forEach(function (m, g) {
    if (S.scanned[g]) return;
    t.applied += m.applied; t.pending += m.pending;
    if (m.applied + m.pending) t.pages++;
  });
  return t;
}
/** 手順 3 のまとめ: 編集したページ数と、削除・枠線・上書きの件数 */
function editTotals() {
  var t = { pages: 0, removed: 0, borders: 0, covers: 0 };
  S.edits3.forEach(function (e) {
    t.removed += e.removed; t.borders += e.borders; t.covers += e.covers;
    if (e.removed + e.borders + e.covers) t.pages++;
  });
  return t;
}
```

`skipsPhase2` / `firstEditablePage2` / `landOnPhase2` を次に置き換える（`phaseAfterLoad` / `phaseBeforeTrim` / `phaseBeforeExport` / `stepAllowed` は変更なし）。

```js
/** 全ページが純スキャンか。ページが無ければ false (手順 1 の「次へ」は別途無効) */
function skipsPhase2() { return S.TOTAL > 0 && S.scanned.every(Boolean); }
/** 手順 2 に入ったとき表示するページ: 辞書に一致 (スキャン以外) の最初、無ければスキャン以外の最初、
 *  無ければ 0 */
function firstEditablePage2() {
  for (var i = 0; i < S.TOTAL; i++) if (!S.scanned[i] && matchCount(i)) return i;
  for (var j = 0; j < S.TOTAL; j++) if (!S.scanned[j]) return j;
  return 0;
}
/** 手順 2 に入る直前に呼ぶ。表示中のページがスキャンならレールに出ているページへ差し替える
 *  (レールに無いページに立つと、キャンバスに画像だけが出て何の画面か分からない)。スキャン以外に
 *  居るときは動かさない (「戻る」で見ていたページを保つ)。 */
function landOnPhase2() { if (S.scanned[S.page]) S.page = firstEditablePage2(); }
```

`resetPhaseUi` の docstring から「未確認ガード」を外し（「手順を移る経路 (「次へ」・「戻る」・ステップバー) はすべてここを通す」）、`advancePhase` を次にする。

```js
/** 手順を 1 つ進める (2→3 / 3→4)。手順 3 の一時状態も戻す。再描画は呼び出し側 */
function advancePhase() {
  resetPhaseUi();
  if (S.phase === 2) { S.phase = 3; S.page = 0; } else if (S.phase === 3) S.phase = 4;
}
```

`exportPageList` から `noskip` の分岐（`:258-260`）を削除する。ファイル冒頭のコメント（`:7`）の「vitest (`test/state.test.js`)」は「実ブラウザの単体 (`test/test_pdftosvg_state_js.py`)」に直す。

`export` を次にする。

```js
export {
  S, pkey, curElSel,
  figKey, svgKey, svgKeys, figSelOf, figSelPeek, figCount, seedFigSel, exportFigureList, adoptedFigures,
  matchCount, editCount, railPages, nextMatched, scannedCountOf, scannedTotal, matchTotals, editTotals,
  phaseAfterLoad, phaseBeforeExport, phaseBeforeTrim, stepAllowed, skipsPhase2, firstEditablePage2, landOnPhase2,
  applyState, invalidateAll, resetPhaseUi, advancePhase,
  exportPageList, expCount, zipName, chunkBySize,
};
```

- [ ] **Step 4: テストが通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_state_js.py pdf-to-svg/test/test_pdftosvg_js_smoke.py -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add pdf-to-svg/resources/web/state.js pdf-to-svg/test/test_pdftosvg_state_js.py
git commit -m "refactor(pdf-to-svg): state.js からページの確認状態と選択集合を撤去し、件数 (matches2 / edits3) とスキャン判定を持つ"
```

（`app.js` / `rail.js` はこの時点で削除済みの export を import しており、ブラウザで読み込めない。Task 3・4 で直す。pre-push の E2E はここで落ちるので、Task 4 までまとめて 1 回の push にするか、落ちた push を Task 4 の後に再実行する。）

---

### Task 3: レール（`rail.js`）を件数タグの一覧に置き換える

**Files:**
- Modify: `pdf-to-svg/resources/web/rail.js`（全体）
- Modify: `pdf-to-svg/resources/web/styles.css:699-716, 753-760`（`.pl-all` / `.pl-skipall` / `.pl-selbar` / `.ck` / `.pl-range` を削除）
- Modify: `pdf-to-svg/resources/web/icons.js`（`chevL` 追加）

**Interfaces:**
- Consumes: `railPages`, `matchCount`, `editCount`, `matchTotals`, `editTotals`（Task 2）
- Produces: `buildRail(navId)` の DOM。`.pl-head > .pl-title` / `select.pl-filter` / `.pl-body > .pl-file[data-fcoll]` / `.pg-row2[data-g]` / `.pg-row2 .tg`。E2E は `#pagenav .pg-row2[data-g="N"]` と `.tg` の文言を見る

- [ ] **Step 1: `rail.js` を書き換える**

```js
// =============================================================================
// rail.js — 左ページレール (一覧・絞り込み・件数タグ) の描画と配線
// =============================================================================
// 状態は `state.js` の `S` を読み、状態変更後の再描画だけは `initRail` で注入された
// `render` (app.js) へ委譲する。レールは手順 2 (`#pagenav`) と手順 3 (`#pagenav-3`) で
// 同一実装を共有する。ページの確認状態は持たず、行のタグは件数 (`S.matches2` / `S.edits3`)
// から毎回描く。

import { esc, svg } from "./dom.js";
import { S, railPages, matchTotals, editTotals } from "./state.js";
import { fileIcon, chevD } from "./icons.js";

var FILTERS = {
  2: [{ v: "matched", t: "辞書に一致したページだけ" }, { v: "all", t: "すべてのページ" }],
  3: [{ v: "all", t: "すべてのページ" }, { v: "edited", t: "編集したページだけ" }],
};
var EMPTY = { 2: "辞書に一致したページはありません", 3: "編集したページはありません" };

// app.js から注入される再描画フック ({ render })
var ui = { render: function () {} };
function initRail(deps) { ui = deps; }

/** 行の右端のタグ。0 の項目は省き、すべて 0 なら出さない */
function rowTag(g) {
  var parts = [];
  if (S.phase === 2) {
    var m = S.matches2[g] || { applied: 0, pending: 0 };
    if (m.applied) parts.push("置換 " + m.applied);
    if (m.pending) parts.push("未置換 " + m.pending);
  } else {
    var e = S.edits3[g] || { removed: 0, borders: 0, covers: 0 };
    if (e.removed) parts.push("削除 " + e.removed);
    if (e.borders) parts.push("枠線 " + e.borders);
    if (e.covers) parts.push("上書き " + e.covers);
  }
  return parts.length ? '<span class="tg t-count">' + parts.join(" ・ ") + "</span>" : "";
}

function railTitle() {
  if (S.phase === 2) {
    var t = matchTotals();
    return "全 <b>" + S.TOTAL + "</b> ページ　辞書に一致 <b>" + t.pages + "</b> ページ" +
      (t.scanned ? "　対象外 <b>" + t.scanned + "</b>" : "");
  }
  return "全 <b>" + S.TOTAL + "</b> ページ　編集したページ <b>" + editTotals().pages + "</b>";
}

function buildRail(navId) {
  var filt = S.filterFor[S.phase];
  var visible = railPages(S.phase);
  var html = '<div class="pl-head"><div class="pl-title">' + railTitle() + "</div>";
  html += '<select class="pl-filter">' + FILTERS[S.phase].map(function (f) {
    return '<option value="' + f.v + '"' + (f.v === filt ? " selected" : "") + ">" + f.t + "</option>";
  }).join("") + "</select></div>";
  html += '<div class="pl-body">';
  var anyRow = false;
  S.FILES.forEach(function (f, fi) {
    var start = S.FILE_START[fi] || 0;
    var idxs = visible.filter(function (g) { return g >= start && g < start + f.pages; });
    if (idxs.length === 0) return;
    anyRow = true;
    var key = S.phase + ":" + fi; var isColl = !!S.collapsed[key];
    html += '<div class="pl-file' + (isColl ? " collapsed" : "") + '">' +
      '<span class="fname" data-fcoll="' + fi + '">' + svg(fileIcon, 13, undefined, "fic") + esc(f.name) + "</span>" +
      '<span class="fcount">' + idxs.length + "</span>" +
      '<span class="fchev" data-fcoll="' + fi + '">' + svg(chevD, 15) + "</span></div>";
    if (!isColl) {
      idxs.forEach(function (g) {
        var n = g - start + 1;
        html += '<div class="pg-row2' + (g === S.page ? " current" : "") + '" data-g="' + g + '">' +
          '<span class="dot">' + n + '</span><span class="lbl">' + n + " ページ</span>" + rowTag(g) + "</div>";
      });
    }
  });
  if (!anyRow) html += '<div class="empty-note" style="padding:48px 16px"><div class="et">' + EMPTY[S.phase] + "</div></div>";
  html += "</div>";
  var nav = document.getElementById(navId);
  nav.innerHTML = html;
  nav.querySelector(".pl-filter").addEventListener("change", function () { S.filterFor[S.phase] = this.value; ui.render(); });
  nav.querySelectorAll("[data-fcoll]").forEach(function (el) {
    el.addEventListener("click", function (e) {
      e.stopPropagation(); var k = S.phase + ":" + el.dataset.fcoll; S.collapsed[k] = !S.collapsed[k]; ui.render();
    });
  });
  nav.querySelectorAll(".pg-row2").forEach(function (r) {
    r.addEventListener("click", function () { S.page = +r.dataset.g; ui.render(); });
  });
}

export { initRail, buildRail };
```

- [ ] **Step 2: CSS を整える**

`styles.css` から `.pl-all`（`:703`）、`.pl-skipall`（`:704-706`）、`.pl-selbar`（`:708-712`）、`.ck`（`:714-716`）、`.pl-range`（`:753-760`）を削除する。`.pg-row2 .tg`（`:735`）の直後に次を足す。

```css
.pg-row2 .tg.t-count { background: var(--accent-soft); color: var(--accent-ink); white-space: nowrap; }
```

`.pg-row2.done` / `.pg-row2.skipped` / `.pg-row2.pending` の `dot` の色分け（`:731-733`）は削除する（状態が無くなるため）。

`icons.js` に `var chevL = '<path d="m14 6-6 6 6 6"/>';` を足し、`export` に `chevL` を加える（Task 5 のページ移動で使う）。

- [ ] **Step 3: ブラウザで読み込めることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_js_smoke.py -q`
Expected: PASS（`rail.js` 単体の import 確認は Task 4 の E2E で行う）

- [ ] **Step 4: コミット**

```bash
git add pdf-to-svg/resources/web/rail.js pdf-to-svg/resources/web/styles.css pdf-to-svg/resources/web/icons.js
git commit -m "refactor(pdf-to-svg): レールを件数タグの一覧にし、全選択・まとめてスキップ・範囲指定を撤去する"
```

---

### Task 4: `app.js` / `index.html` から確認モデルを撤去し、遷移・フッター・手順 4 のまとめを組み直す

**Files:**
- Modify: `pdf-to-svg/resources/web/app.js`（import、`renderSummary` / `pageActHTML` / `onPageAct` / `renderPageAct` の削除、`render` / `tryNext` / `back` / `wireNav` / `refreshExport` / `wireExportPane`）
- Modify: `pdf-to-svg/resources/web/index.html`（`#guard`、`#sum-2` / `#sum-3`、`#pageact-2` / `#pageact-3`、`#exp-noskip`、緑カード、手順 4 の説明文）
- Modify: `pdf-to-svg/resources/web/styles.css`（`.guard*` `:689-693`、`.statusbar*` `:632-638`、`.pa-*` `:641-648` を削除。`.sum-table` / `.lines` / `.note-line` を追加）
- Test: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`

**Interfaces:**
- Consumes: Task 2 の export、Task 3 の `buildRail`
- Produces: `#pagefoot-2`（ボタン `#prev-page-2` / `#next-match-2`）、`#pagefoot-3`（`#prev-page-3` / `#next-page-3`）の器（中身の配線は Task 4b・4c）。`#export-summary` は `<table class="sum-table">`。`#nav-hint` の文言（仕様書 3.3 / 3.4 / 3.6）

- [ ] **Step 1: E2E を書き換える（失敗させる）**

`test_four_step_flow`（`:88-205`）の次の行を置き換える。

```python
    # 辞書に語を足しただけで、その語に当たるページは「辞書に一致」に上がる(再適用の前でも)
    expect(page.locator("#nav-hint")).to_contain_text("辞書に一致 1 ページ")
    page.click("#btn-reapply")
    expect(page.locator("#nav-hint")).to_contain_text("置換 1 か所")
    expect(page.locator("#doc-master")).to_contain_text("売上高", timeout=15_000)
```
（旧 `:119-125` の 2 つの「要確認 1」の期待を上の形にする。）

```python
    # ── 3. 不要範囲を削除: 要素クリック選択 → 削除 → Undo → 再削除 ──
    page.click("#btn-next")  # ページごとの確認は無いので「次へ」でそのまま手順 3 へ
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
```
（旧 `:150` の `[data-skipall]`。）手順 3 の「削除した要素（1）」の期待（`:155-169`）は Task 4c で `#trim-dyn [data-kind="removed"]` の件数に置き換えるので、ここでは一旦 `expect(page.locator("#trim-dyn")).to_contain_text("削除した要素（1）")` のままにし、Task 4c で直す。

```python
    # ── 4. SVG に書き出す(1 ページ → 単一 SVG ダウンロード) ──
    page.click("#btn-next")  # 「書き出しへ」
    expect(page.locator("#btn-export")).to_be_visible()
    # まとめは表 (置換の箇所数・編集したページ)
    expect(page.locator("#export-summary")).to_contain_text("置換 1 か所")
    expect(page.locator("#export-summary")).to_contain_text("編集したページ 1")
    # 書き出す範囲は 3 択 (「スキップを除く」は無い)
    expect(page.locator("#exp-modes [data-mode]")).to_have_count(3)
```
（旧 `:170-171`。）

`:218` と `:318` の `page.click('[data-screen="2"] [data-skipall]')` を `page.click("#btn-next")` にする。

`_open_second_page_in_step3`（`:788-793`）を次にする（絞り込みの既定が「すべてのページ」になるため切り替え不要）。

```python
def _open_second_page_in_step3(page, pdf_path):
    """手順 3 で 2 ページ目を開く。絞り込みの既定は「すべてのページ」なので、行をクリックするだけ。"""
    _goto_step3(page, pdf_path)
    page.click('#pagenav-3 .pg-row2[data-g="1"]')
    expect(page.locator("#pgnav-3")).to_contain_text("2 ページ")
```

`_advance_step3_to_step4`（`:796-800`）を次にする。

```python
def _advance_step3_to_step4(page):
    """手順 3 から 4 へ進む。ページごとの確認は無いので「書き出しへ」でそのまま進む。"""
    page.click("#btn-next")
    expect(page.locator('[data-screen="4"]')).to_have_class(re.compile("on"))
```

`test_mixed_scanned_and_vector_pdfs_hide_scanned_rows_without_a_dialog` の `expect(page.locator("#sum-2")).to_contain_text("対象外 1")`（`:1240`）を `expect(page.locator("#pagenav .pl-title")).to_contain_text("対象外 1")` にする。`test_all_scanned_pdf_skips_step2_via_dialog` の `#guard` / `#guard-skip`（`:1199-1200`）の 2 行を削除し、`expect(page.locator("#export-summary")).to_contain_text("対象外 1")` はそのまま残す（このテスト全体は Task 6 で書き換える）。

- [ ] **Step 2: E2E が落ちることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q -k "test_four_step_flow"`
Expected: FAIL（`state.js` の export 変更で `app.js` が読み込めず画面が出ない）

- [ ] **Step 3: `index.html` を直す**

- `<!-- 確認バー -->` から `</div>`（`#guard` 一式。`:261-267`）を削除する。
- 手順 2: `<div class="statusbar" id="sum-2"></div>`（`:126`）を削除。`<div class="panel-foot" id="pageact-2"></div>`（`:129`）を次にする。
  ```html
          <div class="panel-foot" id="pagefoot-2">
            <div class="pa-btns">
              <button class="btn outline" id="prev-page-2">前のページ</button>
              <button class="btn outline" id="next-match-2">次の一致ページ</button>
            </div>
          </div>
  ```
- 手順 3: `<div class="statusbar" id="sum-3"></div>`（`:195`）を削除。`<div class="panel-foot" id="pageact-3"></div>`（`:198`）を次にする。
  ```html
        <div class="panel-foot" id="pagefoot-3">
          <div class="pa-btns">
            <button class="btn outline" id="prev-page-3">前のページ</button>
            <button class="btn outline" id="next-page-3">次のページ</button>
          </div>
        </div>
  ```
  手順 3 の `.panel-head` の `<p class="desc">`（`:189`）を `<p class="desc lines"><span>編集は自動で保存されます。</span><span>編集しないページはそのまま書き出されます。</span></p>` にする。
- 手順 4: `<p class="lead">`（`:216`）を `<p class="lead lines"><span>内容を確かめて、右下の「SVG に書き出す」を押します。</span><span>ファイルはダウンロードフォルダーに保存されます。</span></p>` にする。まとめの `.opt`（`:218-222`）を次にする。
  ```html
          <div class="opt" style="display:flex;align-items:flex-start;gap:24px">
            <div class="big-tally"><span class="num" id="exp-num">0</span><span class="u">個のSVG</span></div>
            <table class="sum-table" id="export-summary"></table>
          </div>
  ```
  `#exp-noskip` の行（`:231`）を削除。`#exp-spec-row` の直後（`#exp-name-hint` の行の前）に `<div class="opt-note" id="exp-range-note">一部のページだけ書き出すときは「ページを指定」で範囲（例: 1-5, 8）を入れます。</div>` を足す。緑カード（`:251-254`）を次にする。
  ```html
          <div class="note-line"><svg viewBox="0 0 24 24" fill="none" stroke="var(--good)" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m4.5 12.5 5 5 10-11"></path></svg><span class="lines"><span>文字は文字のまま書き出します（後から検索・再編集できます）。</span><span>使ったフォントだけを埋め込みます。</span></span></div>
  ```

- [ ] **Step 4: CSS を足す・消す**

削除: `.statusbar*`（`:632-638`）、`.pa-prompt` / `.pa-badge*` / `.pa-link`（`:641, 644-648`。`.pa-btns` と `.pa-btns .btn` は残す）、`.guard*`（`:689-693`）、`.confirm-banner*`（`:473-483, 512`。Task 4b で置き換える）。

追加（ファイル末尾）:

```css
/* ---- 説明文 (1 文 1 行) ---- */
.lines { display: flex; flex-direction: column; gap: 2px; }
/* ---- 手順 4 のまとめ (表) ---- */
.sum-table { flex: 1; border-collapse: collapse; font-size: 13px; }
.sum-table th { text-align: left; color: var(--muted); font-weight: 500; padding: 6px 0; width: 30%; vertical-align: top; }
.sum-table td { padding: 6px 0; border-top: 1px solid var(--border); display: flex; flex-wrap: wrap; gap: 2px 0; }
.sum-table tr:first-child td { border-top: none; }
.sum-table td span { white-space: nowrap; }
.sum-table td span:not(:last-child)::after { content: "・"; color: var(--faint); margin: 0 6px; }
.sum-table td b { font-weight: 700; }
.opt-note { font-size: 12px; color: var(--muted); margin-top: 10px; }
.note-line { display: flex; align-items: flex-start; gap: 6px; margin-top: 14px; font-size: 12px; color: var(--muted); }
.note-line svg { width: 14px; height: 14px; flex: none; margin-top: 3px; }
```

- [ ] **Step 5: `app.js` を直す**

import（`:9-16`）を次にする。

```js
import {
  S, pkey, curElSel,
  applyState, invalidateAll, resetPhaseUi, advancePhase,
  exportPageList, expCount, zipName, chunkBySize,
  figKey, svgKey, svgKeys, figSelOf, figSelPeek, figCount, seedFigSel, exportFigureList, adoptedFigures,
  phaseAfterLoad, phaseBeforeExport, phaseBeforeTrim, stepAllowed, skipsPhase2, firstEditablePage2, landOnPhase2,
  matchCount, nextMatched, scannedCountOf, scannedTotal, matchTotals, editTotals,
} from "./state.js";
```

削除: `renderSummary`（`:271-279`）、セクション 12 の `pageActHTML` / `onPageAct` / `renderPageAct`（`:586-608`。`pageLabel` は残す）。

`render()`（`:770-890`）: `var guard = document.getElementById("guard");` と、`if (S.guarding && …) {…}` / `guard.hidden = !S.guarding;`（`:800-805`）を削除。手順 4（通常）のまとめ（`:829-834`）を次にする。

```js
    } else if (S.phase === 4) {
      var nExp = expCount(expSpecValue(), parseSpec);
      setHint(nExp > 1 ? nExp + " 個の SVG を zip にまとめて保存します" : "1 個の SVG を保存します");
      ctxText.textContent = S.FILES.length + " ファイル・" + S.TOTAL + " ページ";
      refreshExport();
      document.getElementById("export-summary").innerHTML = exportSummaryRows();
```

フッターの案内（`:836-841`）を次にする。

```js
    } else {
      var pg = S.PAGES[S.page];
      if (S.phase === 2) {
        var mt = matchTotals();
        setHint("用語の置換 — 辞書に一致 <b>" + mt.pages + "</b> ページ ・ 置換 <b>" + mt.applied + "</b> か所 / 未置換 <b>" + mt.pending + "</b> か所");
      } else {
        setHint("削除・枠線の編集 — 編集したページ <b>" + editTotals().pages + "</b> / " + S.TOTAL);
      }
      ctxText.textContent = S.FILES[pg.fileIndex].name + " ・ " + (pg.pageInFile + 1) + "/" + S.FILES[pg.fileIndex].pages + " ページ";
    }
```

手順 2・3 の描画（`:844, 854`）から `renderSummary(...)` と `renderPageAct()` の呼び出しを外す（`buildRail("pagenav");` / `buildRail("pagenav-3");` だけ残す）。

`render()` の直前（セクション 14 の先頭）に次を足す。

```js
  /** 手順 4 のまとめの表 (PDF / 用語の置換 / 削除・枠線)。0 の項目は省く */
  function exportSummaryRows() {
    var mt = matchTotals(), et = editTotals();
    var terms = [];
    if (mt.applied) terms.push("置換 <b>" + mt.applied + "</b> か所（<b>" + mt.pages + "</b> ページ）");
    if (mt.pending) terms.push("未置換 <b>" + mt.pending + "</b> か所");
    if (mt.scanned) terms.push("対象外（スキャン画像） <b>" + mt.scanned + "</b> ページ");
    if (!terms.length) terms.push("辞書に一致した語はありません");
    var edits = [];
    if (et.pages) {
      edits.push("編集したページ <b>" + et.pages + "</b>");
      if (et.removed) edits.push("削除 <b>" + et.removed + "</b>");
      if (et.borders) edits.push("枠線 <b>" + et.borders + "</b>");
      if (et.covers) edits.push("上書き <b>" + et.covers + "</b>");
    } else edits.push("編集したページはありません");
    function row(th, items) { return "<tr><th>" + th + "</th><td>" + items.map(function (x) { return "<span>" + x + "</span>"; }).join("") + "</td></tr>"; }
    return row("PDF", ["<b>" + S.FILES.length + "</b> ファイル・全 <b>" + S.TOTAL + "</b> ページ"]) +
      row("用語の置換", terms) + row("削除・枠線", edits);
  }
```

`tryNext()`（`:893-921`）を次にする（skip2 モーダルの分岐は Task 6 で撤去するが、ここでは `scannedFiles` を使う行だけ先に消す）。

```js
  function tryNext() {
    if (S.phase === 1) {
      if (!S.TOTAL) return;
      S.phase = phaseAfterLoad(); S.page = 0; resetPhaseUi();
      if (S.phase === 2) S.page = firstEditablePage2();
      render();
      if (S.gray) prefetchFigCand();
      return;
    }
    if (S.phase === 2 || S.phase === 3) { advancePhase(); render(); }
  }
```

`back()` から `S.guarding = false;` を消す。`wireNav()` から `#guard-back` / `#guard-skip` の 2 行と skip2 モーダルの塊（`:1020-1035`）を削除し、ステップバーの click から `S.guarding = false;` と `clearSel();` を消す（`S.phase = n;` だけ残す）。`wireNav()` の docstring を「フッター/ステップバー/Undo・Redo のナビゲーション」にする。`window.__rpcReady` の `initRail({ render: render, tryNext: tryNext });` を `initRail({ render: render });` にする。`#chk-gray` の change ハンドラ（`:980-985`）のコメント「noskip / spec は無い」を「spec は無い」にする（`S.expMode = "all"` は残す）。

`render()` の手順 2 のブロックに、`buildRail("pagenav");` の直後で次を足す（Task 4b で本体を書く `renderConfirm` は既存）。

```js
      wirePageFoot2();
```

同じく手順 3 のブロックの `buildRail("pagenav-3");` の直後に `wirePageFoot3();` を足し、セクション 12 の位置に次の 2 関数を置く。

```js
  // ── 12. ページ送り (右パネル下部) ──
  function wirePageFoot2() {
    var prev = document.getElementById("prev-page-2"), next = document.getElementById("next-match-2");
    prev.disabled = S.page === 0;
    var nm = nextMatched(S.page);
    next.disabled = nm < 0;
    prev.onclick = function () { if (S.page > 0) { S.page--; render(); } };
    next.onclick = function () { var n = nextMatched(S.page); if (n >= 0) { S.page = n; render(); } };
  }
  function wirePageFoot3() {
    var prev = document.getElementById("prev-page-3"), next = document.getElementById("next-page-3");
    prev.disabled = S.page === 0;
    next.disabled = S.page >= S.TOTAL - 1;
    prev.onclick = function () { if (S.page > 0) { S.page--; render(); } };
    next.onclick = function () { if (S.page < S.TOTAL - 1) { S.page++; render(); } };
  }
```

`renderConfirm()` の冒頭（`:285-291`）の `if (!S.changed2[S.page])` を `if (!matchCount(S.page))` にし、文言を `noChangeNote(S.scanned[S.page] ? "このページはスキャン画像のため、用語の置換の対象外です" : "このページに辞書と一致する語はありません")` にする（右パネルの本体は Task 4b）。

- [ ] **Step 6: E2E の通しが通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q -k "test_four_step_flow or test_stale_page or test_list_fetch or keeps_page"`
Expected: PASS（`#trim-dyn` の「削除した要素（1）」は既存の `renderTrim` のまま通る）

- [ ] **Step 7: 単体も通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -q`
Expected: PASS

- [ ] **Step 8: コミット**

```bash
git add pdf-to-svg/resources/web/app.js pdf-to-svg/resources/web/index.html pdf-to-svg/resources/web/styles.css pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py
git commit -m "feat(pdf-to-svg): ページごとの確認 (要確認 / 確認済み / スキップ) と確認バーを撤去し、手順 4 のまとめを表にする"
```

---

### Task 4b: 手順 2 の右パネル（件数カード・一致箇所の置換 / 戻す）

**Files:**
- Modify: `pdf-to-svg/resources/web/app.js:282-352`（`renderConfirm`）
- Modify: `pdf-to-svg/resources/web/styles.css`（`.count-card` を追加）
- Test: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`

- [ ] **Step 1: E2E に期待を足す（失敗させる）**

`test_four_step_flow` の「箇所単位」の段（`:127-137`）の `expect(page.locator("#confirm-dyn")).to_contain_text("未置換 1 件")` を次の 2 行にし、最後の `not_to_contain_text("未置換")` を `expect(page.locator("#confirm-dyn .count-card")).to_contain_text("すべて置き換えました")` にする。

```python
    expect(page.locator("#confirm-dyn .count-card .num")).to_have_text("0")
    expect(page.locator("#confirm-dyn .count-card")).to_contain_text("1 か所が未置換です")
```

- [ ] **Step 2: 落ちることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q -k test_four_step_flow`
Expected: FAIL（`.count-card` が無い）

- [ ] **Step 3: `renderConfirm` の見出し部分を置き換える**

`:322-327`（`confirm-banner` の生成）を次にする。

```js
    var total = data.changes.length;
    var desc = total === 0 ? "このページに辞書と一致する語はありません。"
      : pending === 0 ? "辞書に一致した " + total + " か所をすべて置き換えました。"
      : "一致 " + total + " か所のうち " + pending + " か所が未置換です。";
    el.innerHTML =
      '<div class="count-card"><div class="num">' + applied + '</div><div><div class="t">このページで置き換えた語</div>' +
      '<div class="lines s"><span>' + desc + "</span>" + (pending ? "<span>「置換」で当てられます。</span>" : "") + "</div></div></div>" +
      '<div style="display:flex;flex-direction:column;min-height:0;flex:1;"><div class="field-label">辞書に一致した箇所（番号はページ上のマーカー）</div><div class="change-list">' +
      rows + "</div></div>";
```

CSS（末尾）:

```css
/* ---- 手順 2 の件数カード (0 件でも緑にしない) ---- */
.count-card { display: flex; align-items: center; gap: 12px; background: var(--sunk); border-radius: var(--r-md); padding: 12px 14px; }
.count-card .num { font-family: var(--font-round); font-size: 26px; font-weight: 700; color: var(--ink); flex: none; min-width: 22px; text-align: center; }
.count-card .t { font-weight: 700; font-size: 13.5px; }
.count-card .s { font-size: 12px; color: var(--muted); }
```

- [ ] **Step 4: 通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q -k test_four_step_flow`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add pdf-to-svg/resources/web/app.js pdf-to-svg/resources/web/styles.css pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py
git commit -m "feat(pdf-to-svg): 手順 2 の右パネルを件数カード (0 件でも緑にしない) と一致箇所の一覧にする"
```

---

### Task 4c: 手順 3 の右パネル（このページの編集・使い方）

**Files:**
- Modify: `pdf-to-svg/resources/web/app.js:433-469`（`renderTrim`）
- Modify: `pdf-to-svg/resources/web/styles.css`（`.edit-row` / `.howto` を追加。`.removed-row*` `:773-777` を削除）
- Test: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`

- [ ] **Step 1: E2E を書き換える（失敗させる）**

`test_four_step_flow` の `expect(page.locator("#trim-dyn")).to_contain_text("削除した要素（1）")` をすべて `expect(page.locator('#trim-dyn [data-kind="removed"]')).to_have_count(1)` に、`（0）` を `to_have_count(0)` にする（`:155-169` の 5 か所）。手順 3 で枠線を置く既存テスト `test_border_overlay_resize_and_width_change` の末尾に次を足す（枠線の行が右パネルに載ることの確認）。

```python
    expect(page.locator('#trim-dyn [data-kind="border"]')).to_have_count(1)
    expect(page.locator("#trim-dyn")).to_contain_text("枠線")
```

- [ ] **Step 2: 落ちることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q -k "test_four_step_flow or test_border_overlay_resize"`
Expected: FAIL

- [ ] **Step 3: `renderTrim` を書き換える**

```js
  // ── 10. 編集ペイン (手順3): このページの編集 (削除・枠線・上書き) と使い方 ──
  var HOWTO = {
    normal: ["要素をクリックして「削除」。", "「範囲削除」はドラッグ範囲をまとめて削除。", "「枠線」「上書き」はドラッグで置きます。", "置いた後も動かせます。"],
    scanned: ["画像の文字は辞書で置き換えられません。", "「上書き」を選び、置く所をドラッグします。", "上のボックスに置換語を入れます。", "画像の上に矩形と語が乗ります。", "置いた上書きは後から動かせます。"],
  };
  function howtoHTML() {
    var scanned = !!S.scanned[S.page];
    return '<div class="howto"><b>' + (scanned ? "スキャン画像のページの使い方" : "使い方") + "</b><ul>" +
      HOWTO[scanned ? "scanned" : "normal"].map(function (s) { return "<li>" + s + "</li>"; }).join("") + "</ul></div>";
  }
  async function renderTrim() {
    var el = document.getElementById("trim-dyn");
    var ed3 = app.querySelector('[data-screen="3"] .editor');
    ed3.classList.remove("nochange");
    var pg = S.PAGES[S.page];
    var token = pg.fileIndex + ":" + pg.pageInFile;
    var args = { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile };
    var lists;
    try {
      lists = await Promise.all([rpc("removedList", args), rpc("borderList", args), rpc("coverList", args)]);
    } catch (e) {
      if (token !== S.PAGES[S.page].fileIndex + ":" + S.PAGES[S.page].pageInFile) return; // ページが変わった
      renderPaneError(el, "このページの編集の一覧を取得できませんでした: " + String((e && e.message) || e));
      return;
    }
    if (token !== S.PAGES[S.page].fileIndex + ":" + S.PAGES[S.page].pageInFile) return; // ページが変わった
    var removed = lists[0].removed, borders = lists[1].borders, covers = lists[2].covers;
    var rows = removed.map(function (r) {
      return '<div class="edit-row" data-kind="removed"><span class="k">削除</span><span class="rlabel">' + esc(r.label) + '</span><button class="row-btn" data-restore="' + r.elId + '">戻す</button></div>';
    }).concat(borders.map(function (b) {
      return '<div class="edit-row" data-kind="border"><span class="k">枠線</span><span class="rlabel">' + esc(b.color) + " ・ " + b.width + ' pt</span><button class="row-btn" data-del="' + b.elId + '">削除</button></div>';
    })).concat(covers.map(function (c) {
      return '<div class="edit-row" data-kind="cover"><span class="k">上書き</span><span class="rlabel">' + (c.text ? "「" + esc(c.text) + "」" : "（矩形だけ）") + '</span><button class="row-btn" data-del="' + c.elId + '">削除</button></div>';
    })).join("");
    el.innerHTML = '<div class="field-label">このページの編集</div>' +
      (rows ? '<div class="change-list">' + rows + "</div>" : '<div class="edit-empty">このページに編集はありません</div>') +
      howtoHTML();
    el.querySelectorAll("[data-restore]").forEach(function (b) {
      b.addEventListener("click", async function () {
        // 行の要素だけを戻す。全体の undo は直近 1 件しか戻せず、複数回に分けて削除した
        // 後や別ページで削除した後に押すと無関係な操作を取り消してしまう。
        await rpc("restoreElements", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elIds: [+b.dataset.restore] });
        await afterEdit();
      });
    });
    el.querySelectorAll("[data-del]").forEach(function (b) {
      b.addEventListener("click", async function () {
        await rpc("applyDelete", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elIds: [+b.dataset.del] });
        await afterEdit();
      });
    });
  }
```

CSS（末尾。`.removed-row*` は削除）:

```css
/* ---- 手順 3 の「このページの編集」 ---- */
.edit-row { display: flex; align-items: center; gap: 10px; padding: 9px 12px; background: var(--sunk); border-radius: var(--r-sm); font-size: 13px; }
.edit-row .k { font-size: 11px; font-weight: 700; color: var(--accent-ink); flex: none; }
.edit-row .rlabel { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.edit-row .row-btn { font: inherit; font-size: 11.5px; font-weight: 700; padding: 3px 10px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface); color: var(--ink); cursor: pointer; }
.edit-empty { padding: 10px 12px; border: 1px dashed var(--border); border-radius: var(--r-sm); font-size: 12.5px; color: var(--faint); }
.howto { margin-top: auto; background: var(--accent-soft); border-radius: var(--r-md); padding: 12px 14px; font-size: 12px; color: var(--muted); line-height: 1.7; }
.howto b { display: block; color: var(--accent-ink); margin-bottom: 6px; }
.howto ul { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 4px; }
```

- [ ] **Step 4: 通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q`
Expected: PASS（Task 6 で書き換える 3 本のスキャン系テストだけが失敗していてよい。それ以外は緑）

- [ ] **Step 5: コミット**

```bash
git add pdf-to-svg/resources/web/app.js pdf-to-svg/resources/web/styles.css pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py
git commit -m "feat(pdf-to-svg): 手順 3 の右パネルを「このページの編集」の一覧と使い方にする"
```

---

### Task 5: 「ページへ移動」部品（`page-jump.js`）

**Files:**
- Create: `pdf-to-svg/resources/web/page-jump.js`
- Create: `pdf-to-svg/test/test_pdftosvg_page_jump_js.py`
- Modify: `pdf-to-svg/resources/web/index.html:103, 182`（`.page-nav` の器）, `app.js`（組み込み）, `styles.css`（`.page-jump`）
- Test: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`

**Interfaces:**
- Produces: `resolveJump(files, fileStart, fileIndex, value): number`（通し index。ファイルが無ければ -1。番号は 1〜ページ数に丸め、数字でなければ 1）、`initPageJump({render})`, `buildPageJump(hostId)`

- [ ] **Step 1: 単体テストを書く（失敗させる）**

`pdf-to-svg/test/test_pdftosvg_page_jump_js.py`:

```python
# =============================================================================
# test_pdftosvg_page_jump_js.py — resources/web/page-jump.js の純粋関数の単体
# =============================================================================
# `resolveJump` はファイル一覧と通し先頭 index を引数で受ける (S を読まない) ので、
# 共有ページの状態を汚さずに境界だけを固定できる。
import pytest

from .pdftosvg_js_harness import js

pytestmark = pytest.mark.browser

FILES = [{"name": "a.pdf", "pages": 2}, {"name": "b.pdf", "pages": 3}]
START = [0, 2]


@pytest.fixture(scope="module")
def pj(edge_page):
    edge_page.evaluate("import('/page-jump.js').then(m => { window.__pj = m; })")
    return edge_page


def _resolve(page, fi, value):
    return js(page, "(a) => window.__pj.resolveJump(a.files, a.start, a.fi, a.value)",
              {"files": FILES, "start": START, "fi": fi, "value": value})


def test_resolvejump_maps_file_and_number_to_global_index(pj):
    assert _resolve(pj, 0, "1") == 0
    assert _resolve(pj, 0, "2") == 1
    assert _resolve(pj, 1, "1") == 2
    assert _resolve(pj, 1, "3") == 4


def test_resolvejump_clamps_out_of_range_and_treats_non_numbers_as_first_page(pj):
    assert _resolve(pj, 1, "99") == 4
    assert _resolve(pj, 1, "0") == 2
    assert _resolve(pj, 1, "-3") == 2
    assert _resolve(pj, 1, "abc") == 2
    assert _resolve(pj, 1, "") == 2
    assert _resolve(pj, 0, "1.7") == 0   # 小数は切り捨て


def test_resolvejump_returns_minus_one_for_an_unknown_file(pj):
    assert _resolve(pj, 5, "1") == -1
```

- [ ] **Step 2: 落ちることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_page_jump_js.py -q`
Expected: FAIL（`/page-jump.js` が 404）

- [ ] **Step 3: `page-jump.js` を書く**

```js
// =============================================================================
// page-jump.js — 「ページへ移動」(ファイル選択 + ページ番号 + 前後) の描画と配線
// =============================================================================
// 手順 2 (`#pgnav-2`) と手順 3 (`#pgnav-3`) が同じ関数から 1 つずつ生成する。レールの絞り込みに
// 出ていないページへも番号で直接移動できる。状態は `state.js` の `S.page` を書き、再描画は
// `initPageJump` で注入された `render` (app.js) へ委譲する。`resolveJump` は S を読まない
// 純粋関数で、単体テスト (`test/test_pdftosvg_page_jump_js.py`) が境界を固定する。

import { esc, svg } from "./dom.js";
import { S } from "./state.js";
import { chevL, chevD } from "./icons.js";

var ui = { render: function () {} };
function initPageJump(deps) { ui = deps; }

/** ファイル fileIndex のページ番号 value (1 始まりの文字列) を通し index にする。
 *  番号は 1〜そのファイルのページ数へ丸め、数字でなければ 1 とみなす。ファイルが無ければ -1 */
function resolveJump(files, fileStart, fileIndex, value) {
  var f = files[fileIndex]; if (!f) return -1;
  var n = parseInt(value, 10);
  if (!isFinite(n)) n = 1;
  n = Math.max(1, Math.min(f.pages, n));
  return (fileStart[fileIndex] || 0) + (n - 1);
}

function buildPageJump(hostId) {
  var host = document.getElementById(hostId); if (!host) return;
  var pg = S.PAGES[S.page]; if (!pg) { host.innerHTML = ""; return; }
  var f = S.FILES[pg.fileIndex];
  host.innerHTML =
    '<button type="button" class="pj-btn" data-pj="prev" title="前のページ"' + (S.page === 0 ? " disabled" : "") + ">" + svg(chevL, 16) + "</button>" +
    '<select class="pj-file" aria-label="ファイル">' + S.FILES.map(function (x, i) {
      return '<option value="' + i + '"' + (i === pg.fileIndex ? " selected" : "") + ">" + esc(x.name) + "</option>";
    }).join("") + "</select>" +
    '<input class="pj-num" type="number" min="1" max="' + f.pages + '" value="' + (pg.pageInFile + 1) + '" aria-label="ページ番号">' +
    '<span class="pj-of">/ ' + f.pages + " ページ</span>" +
    '<button type="button" class="btn primary pj-go" data-pj="go">移動</button>' +
    '<button type="button" class="pj-btn" data-pj="next" title="次のページ"' + (S.page >= S.TOTAL - 1 ? " disabled" : "") + ">" + svg(chevD, 16) + "</button>";
  var sel = host.querySelector(".pj-file"), num = host.querySelector(".pj-num");
  function go() {
    var g = resolveJump(S.FILES, S.FILE_START, +sel.value, num.value);
    if (g < 0) return;
    S.page = g; ui.render();
  }
  host.querySelector('[data-pj="go"]').addEventListener("click", go);
  num.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); go(); } });
  // ファイルを切り替えたら番号入力の上限をそのファイルに合わせ、1 ページ目へ (移動は「移動」で確定)
  sel.addEventListener("change", function () { var x = S.FILES[+sel.value]; if (x) { num.max = x.pages; num.value = 1; } });
  host.querySelector('[data-pj="prev"]').addEventListener("click", function () { if (S.page > 0) { S.page--; ui.render(); } });
  host.querySelector('[data-pj="next"]').addEventListener("click", function () { if (S.page < S.TOTAL - 1) { S.page++; ui.render(); } });
}

export { initPageJump, buildPageJump, resolveJump };
```

（`next` のアイコンは `icons.js` の `chevD`（右向きの山形 `m10 6 6 6-6 6`）をそのまま使う。）

- [ ] **Step 4: 組み込む**

`index.html`: `:103` の `<div class="page-nav"><span class="pg" id="pgnav-2"></span></div>` を `<div class="page-nav page-jump" id="pgnav-2"></div>` に、`:182` も同様に `id="pgnav-3"` で置き換える（`#pgnav-4` は文字表示のまま）。

`app.js`: `import { initPageJump, buildPageJump } from "./page-jump.js";` を足し、`render()` の `document.getElementById("pgnav-2").innerHTML = pageLabel();` を `buildPageJump("pgnav-2");` に、`pgnav-3` も同様にする。起動時（`initRail` の隣）に `initPageJump({ render: render });` を足す。

CSS（末尾）:

```css
/* ---- ページへ移動 (手順 2・3 のキャンバス下) ---- */
.page-jump { gap: 8px; padding: 6px 8px 6px 6px; left: calc(50% - 64px); }
.page-jump .pj-btn { width: 30px; height: 30px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface); color: var(--ink); display: grid; place-items: center; cursor: pointer; }
.page-jump .pj-btn:disabled { opacity: .4; cursor: default; }
.page-jump .pj-btn svg { width: 16px; height: 16px; }
.page-jump .pj-file { height: 30px; max-width: 180px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--paper); font-family: var(--font-ui); font-size: 12.5px; color: var(--ink); padding: 0 8px; }
.page-jump .pj-num { width: 44px; height: 30px; border: 1px solid var(--border-strong); border-radius: 8px; text-align: center; font-family: var(--font-ui); font-size: 13px; font-weight: 700; color: var(--ink); background: var(--surface); }
.page-jump .pj-num::-webkit-outer-spin-button, .page-jump .pj-num::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.page-jump .pj-of { font-size: 12.5px; color: var(--muted); white-space: nowrap; }
.page-jump .pj-go { height: 30px; padding: 0 10px; font-size: 12px; }
```

- [ ] **Step 5: E2E を足す・直す**

`#pgnav-3` / `#pgnav-2` の `to_contain_text("2 ページ")`（`_open_second_page_in_step3` と `:1118, 1132, 1143`）を `expect(page.locator("#pgnav-3 .pj-num")).to_have_value("2")`（手順 2 は `#pgnav-2 .pj-num`）にする。`:1236` の `expect(page.locator("#pgnav-2")).to_contain_text("vector_sample.pdf")` は `expect(page.locator("#pgnav-2 .pj-file")).to_have_value("1")` にする。

新しいテストをファイル末尾に足す。

```python
def test_page_jump_moves_by_number_and_arrows_including_pages_hidden_from_the_rail(e2e_page, ocr_layer_two_page_pdf):
    """画面下の「ページへ移動」: 番号 + 移動 / Enter / 前後ボタンで表示ページが変わる。
    手順 2 のレールは辞書に一致したページだけを出すが、移動はどのページへも効く。"""
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(str(ocr_layer_two_page_pdf))
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル", timeout=30_000)
    page.click("#btn-next")
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))
    # 辞書が空なのでレールに行は無いが、番号で 2 ページ目へ行ける
    expect(page.locator("#pagenav .pg-row2")).to_have_count(0)
    page.fill("#pgnav-2 .pj-num", "2")
    page.click("#pgnav-2 .pj-go")
    assert page.evaluate("() => window.__state.page") == 1
    expect(page.locator("#pgnav-2 .pj-num")).to_have_value("2")
    # 前へ
    page.click('#pgnav-2 [data-pj="prev"]')
    assert page.evaluate("() => window.__state.page") == 0
    # Enter でも移動。範囲外は端に丸める
    page.fill("#pgnav-2 .pj-num", "9")
    page.press("#pgnav-2 .pj-num", "Enter")
    assert page.evaluate("() => window.__state.page") == 1
    expect(page.locator('#pgnav-2 [data-pj="next"]')).to_be_disabled()
    # 手順 3 でも同じ部品
    page.click("#btn-next")
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
    expect(page.locator("#pgnav-3 .pj-num")).to_have_value("1")
    page.click('#pgnav-3 [data-pj="next"]')
    expect(page.locator("#pgnav-3 .pj-num")).to_have_value("2")
```

- [ ] **Step 6: 通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_page_jump_js.py -q && py -3.13 -m pytest pdf-to-svg -m e2e -q -k "page_jump or keeps_page or resets_tool"`
Expected: PASS

- [ ] **Step 7: コミット**

```bash
git add pdf-to-svg/resources/web/page-jump.js pdf-to-svg/test/test_pdftosvg_page_jump_js.py pdf-to-svg/resources/web/index.html pdf-to-svg/resources/web/app.js pdf-to-svg/resources/web/styles.css pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py
git commit -m "feat(pdf-to-svg): 手順 2・3 の画面下に「ページへ移動」(ファイル選択 + ページ番号 + 前後) を置く"
```

---

### Task 6: 手順 1（書き出し方の 2 択・スキャン画像のバナーとバッジ・モーダルとトーストの撤去）と Undo / Redo のラベル

**Files:**
- Modify: `pdf-to-svg/resources/web/index.html:49-51`（Undo/Redo）, `:83-93`（`modebox` → 2 択カード、バナーの器）, `:281-290`（`#skip2-dialog` を削除）
- Modify: `pdf-to-svg/resources/web/app.js`（`reloadState` のトースト、`renderFileCards`、`renderScanBanner`、`render` のモード表示、`wireStatic` のラジオ配線）
- Modify: `pdf-to-svg/resources/web/styles.css`（`.modebox*` `:825-829`、`dialog.notice*` `:838-846` を削除。`.mode-cards` / `.banner` / `.chip` / `.iconbtn.lbl` を追加）
- Test: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`

- [ ] **Step 1: E2E を書き換える（失敗させる）**

`test_all_scanned_pdf_skips_step2_via_dialog`（`:1146-1208`）を次に置き換える。

```python
def test_all_scanned_pdf_shows_banner_and_skips_step2_without_a_dialog(e2e_page, scanned_pdf):
    """全ページが純スキャン: 手順 1 にバナーとバッジが出て、「次へ」でそのまま手順 3 へ進む。"""
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(str(scanned_pdf))
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル", timeout=30_000)
    # 常設バナー (全ページ用の文言) とカードのバッジ。モーダルもトーストも無い
    expect(page.locator("#scan-banner")).to_be_visible()
    expect(page.locator("#scan-banner")).to_contain_text("すべてスキャン画像です（1 ページ）")
    expect(page.locator("#scan-banner")).to_contain_text("手順 2「用語を置換」は省略し")
    expect(page.locator("#file-cards .chip")).to_have_text(re.compile(r"スキャン画像 1 / 1 ページ"))
    expect(page.locator("#skip2-dialog")).to_have_count(0)
    expect(page.locator("#toast")).not_to_contain_text("スキャン画像")
    # ステップバーの 2 が消え、注記が出る。流れ表示の「2 用語」も打ち消し
    expect(page.locator('#stepbar .step[data-step="2"]')).to_be_hidden()
    expect(page.locator("#scan-skipnote")).to_be_visible()
    expect(page.locator("#flow-step2")).to_have_class(re.compile("skip"))
    expect(page.locator("#nav-hint")).to_contain_text("削除・枠線の編集に進みます")

    page.click("#btn-next")
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
    expect(page.locator("#trim-dyn")).to_contain_text("スキャン画像のページの使い方")
    # 「戻る」は手順 1 へ (手順 2 を飛ばしたので)
    page.click("#btn-back")
    expect(page.locator('[data-screen="1"]')).to_have_class(re.compile("on"))
    page.click("#btn-next")
    page.click("#btn-next")  # 「書き出しへ」
    expect(page.locator('[data-screen="4"]')).to_have_class(re.compile("on"))
    expect(page.locator("#export-summary")).to_contain_text("対象外（スキャン画像） 1 ページ")
    expect(page.locator('#stepbar .step[data-step="2"]')).to_be_hidden()
    page.click("#btn-back")
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
```

`test_mixed_scanned_and_vector_pdfs_hide_scanned_rows_without_a_dialog` の冒頭部分（`:1218-1230`）を次にする（以降のレールの期待は Task 4 で直した形のまま）。

```python
    fc_info.value.set_files([str(scanned_pdf), str(vector_pdf)])
    expect(page.locator("#filelist-count")).to_contain_text("2 ファイル", timeout=30_000)
    # 混在: バナーは混在用の文言、スキャン PDF のカードだけにバッジ
    expect(page.locator("#scan-banner")).to_contain_text("スキャン画像のページが 1 ページあります")
    expect(page.locator("#scan-banner")).to_contain_text("手順 2 の一覧には出ません")
    expect(page.locator("#file-cards .file-card").nth(0).locator(".chip")).to_have_count(1)
    expect(page.locator("#file-cards .file-card").nth(1).locator(".chip")).to_have_count(0)
    # 混在ならステップバーの 2 は残る
    expect(page.locator('#stepbar .step[data-step="2"]')).to_be_visible()
    expect(page.locator("#scan-skipnote")).to_be_hidden()
    expect(page.locator("#flow-step2")).not_to_have_class(re.compile("skip"))

    page.click("#btn-next")
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))
```
`expect(page.locator("#skip2-dialog")).to_be_hidden()` の行は削除する。`:1232-1240` のレールの期待は「辞書が空なのでレールは空」になるため、`expect(page.locator("#pagenav .pg-row2")).to_have_count(1)` と `.pl-file` の 2 行を削除し、代わりに `expect(page.locator("#pagenav .pl-title")).to_contain_text("対象外 1")` を残す。`assert page.evaluate("() => window.__state.status2") == ["na", "none"]` を `assert page.evaluate("() => window.__state.scanned") == [True, False]` にする。

`test_dialog_closed_after_a_vector_pdf_was_added_lands_on_step2`（`:1250-1290`）は削除する。

`test_gray_figure_flow` の `page.check("#chk-gray")`（`:373`）を `page.check("#mode-gray")` に、`page.uncheck("#chk-gray")`（`:466`）を `page.check("#mode-normal")` にする。

- [ ] **Step 2: 落ちることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q -k "scanned or gray_figure"`
Expected: FAIL

- [ ] **Step 3: `index.html` を直す**

Undo / Redo（`:50-51`）: 各ボタンの `</svg>` の直後に `<span class="lbl">元に戻す</span>` / `<span class="lbl">やり直し</span>` を足し、class を `iconbtn labeled` にする。

`modebox`（`:83-89`）を次に置き換える。

```html
          <div class="modepick">
            <div class="lbl">書き出し方</div>
            <div class="mode-cards">
              <label class="mode-card on" id="mode-normal-box">
                <input type="radio" name="mode" id="mode-normal" value="normal" checked>
                <div>
                  <div class="t">ページを SVG にする</div>
                  <div class="d">用語を置き換え、いらない部分を消してから書き出します。</div>
                  <div class="flow"><span>1 PDF</span><i>›</i><span id="flow-step2">2 用語</span><i>›</i><span>3 削除・枠線</span><i>›</i><span>4 SVG</span></div>
                </div>
              </label>
              <label class="mode-card" id="mode-gray-box">
                <input type="radio" name="mode" id="mode-gray" value="gray">
                <div>
                  <div class="t">図だけをグレースケールで書き出す</div>
                  <div class="d">「当社のスチュワードシップ活動」の図を自動で見つけて候補にします。</div>
                  <div class="flow"><span>1 PDF</span><i>›</i><span>4 図を選ぶ・SVG</span></div>
                </div>
              </label>
            </div>
          </div>
```

`.filelist`（`:90-93`）の `.lbl` と `#file-cards` の間に次を足す。

```html
            <div class="banner" id="scan-banner" hidden>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8v5M12 16.5v.5"></path><path d="M10.3 3.9 2.8 17a2 2 0 0 0 1.7 3h15a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"></path></svg>
              <div class="lines" id="scan-banner-text"></div>
            </div>
```

`#skip2-dialog`（コメント含む `:281-290`）を削除する。

- [ ] **Step 4: CSS**

削除: `.modebox*`（`:825-829`）、`dialog.notice*`（`:838-846`）。追加（末尾）:

```css
/* ---- 手順 1: 書き出し方の 2 択 ---- */
.modepick { margin-top: 18px; }
.modepick .lbl { font-size: 12px; font-weight: 700; color: var(--muted); margin-bottom: 8px; }
.mode-cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.mode-card { display: flex; gap: 11px; align-items: flex-start; border: 1.5px solid var(--border); border-radius: var(--r-md); padding: 13px 14px; background: var(--surface); cursor: pointer; }
.mode-card.on { border-color: var(--accent); background: var(--accent-soft); }
.mode-card input { width: 18px; height: 18px; margin: 2px 0 0; accent-color: var(--accent); flex: none; }
.mode-card .t { font-weight: 700; font-size: 14px; }
.mode-card .d { font-size: 12px; color: var(--muted); margin-top: 3px; }
.mode-card .flow { display: flex; align-items: center; gap: 5px; margin-top: 8px; font-size: 11.5px; color: var(--muted); flex-wrap: wrap; }
.mode-card .flow span { background: var(--sunk); border-radius: 999px; padding: 1px 8px; color: var(--ink); font-weight: 700; white-space: nowrap; }
.mode-card .flow span.skip { text-decoration: line-through; color: var(--faint); background: transparent; border: 1px dashed var(--border-strong); }
.mode-card .flow i { font-style: normal; color: var(--faint); }
/* ---- 手順 1: スキャン画像のバナーとカードのバッジ ---- */
.banner { display: flex; gap: 12px; padding: 12px 14px; border-radius: var(--r-md); background: var(--warn-soft); border: 1px solid var(--warn-line); color: var(--ink); font-size: 13px; line-height: 1.6; }
.banner[hidden] { display: none; }
.banner svg { width: 20px; height: 20px; color: var(--warn-ink); flex: none; margin-top: 2px; }
.banner b { color: var(--warn-ink); }
.chip { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 999px; background: var(--warn-soft); color: var(--warn-ink); border: 1px solid var(--warn-line); white-space: nowrap; }
.file-card .fsub { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
/* ---- Undo / Redo の文字ラベル ---- */
.iconbtn.labeled { width: auto; padding: 0 10px; display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; font-family: var(--font-ui); }
```

- [ ] **Step 5: `app.js` を直す**

`reloadState()` から `scannedPages` のトースト（`:132-134`）と `degradedNoticed.scannedPages` の行、`degradedNoticed` の初期値の `scannedPages: 0` を削除する。

`renderFileCards()`（`:167-184`）のカード生成を次にする。

```js
    document.getElementById("file-cards").innerHTML = S.FILES.map(function (f, i) {
      var sc = scannedCountOf(i);
      var chip = sc ? '<span class="chip">スキャン画像 ' + sc + " / " + f.pages + " ページ</span>" : "";
      return '<div class="file-card"><div class="fic">' + svg(fileIcon, 20) +
        '</div><div class="fmeta"><div class="fname">' + esc(f.name) + '</div><div class="fsub"><span>' +
        f.pages + " ページ" + (f.size ? " ・ " + f.size : "") + "</span>" + chip + "</div></div>" +
        '<button class="iconbtn" data-removefile="' + i + '" title="一覧から削除">' + svg(xIcon, 16) + "</button></div>";
    }).join("");
```

`renderFileCards` の直後に次を足し、`renderFileCards()` の末尾（削除ボタンの配線の後）で `renderScanBanner();` を呼ぶ。

```js
  /** 手順 1 のスキャン画像のバナー。スキャンページが 1 ページ以上あるときだけ出す。
   *  グレーモードのときは出さない (手順 2 を通らないため)。文言は全ページ用と混在用の 2 系統。 */
  function renderScanBanner() {
    var el = document.getElementById("scan-banner"), text = document.getElementById("scan-banner-text");
    var n = scannedTotal();
    if (!n || S.gray) { el.hidden = true; return; }
    var all = skipsPhase2();
    var lines = all
      ? ["<b>選んだ PDF はすべてスキャン画像です（" + n + " ページ）。</b>",
         "文字を持たないため、用語の置換はできません。",
         "手順 2「用語を置換」は省略し、「次へ」で手順 3「削除・枠線の編集」に進みます。",
         "文字を置き換えたいときは、手順 3 の「上書き」で矩形と語を置きます。"]
      : ["<b>スキャン画像のページが " + n + " ページあります。</b>",
         "文字を持たないため、用語の置換はできません（手順 2 の一覧には出ません）。",
         "文字を置き換えたいときは、手順 3 の「上書き」で矩形と語を置きます。"];
    text.innerHTML = lines.map(function (s) { return "<span>" + s + "</span>"; }).join("");
    el.hidden = false;
  }
```

`render()`: `document.getElementById("gray-mode-box").classList.toggle("on", S.gray);`（`:793`）を次にする。

```js
    document.getElementById("mode-normal-box").classList.toggle("on", !S.gray);
    document.getElementById("mode-gray-box").classList.toggle("on", S.gray);
    document.getElementById("flow-step2").classList.toggle("skip", skip2);
    renderScanBanner();
```

手順 1 のフッターの案内（`:815-819`）を次にする。

```js
    if (S.phase === 1) {
      var sc = scannedTotal();
      setHint(!S.TOTAL ? "変換するPDFを選びます"
        : S.gray ? "「次へ」で図の選択に進みます（手順 2・3 は省略）"
        : skip2 ? "「次へ」で削除・枠線の編集に進みます（スキャン画像のみのため用語の置換は省略）"
        : "「次へ」で用語の置換に進みます" + (sc ? "（スキャン画像の " + sc + " ページは対象外）" : ""));
```

`wireStatic()` の `#chk-gray` の配線（`:980-985`）を次にする。

```js
    function setGray(on) {
      S.gray = on;
      S.expMode = "all";  // グレーモードに spec は無い (手順 2・3 を通らない)
      S.svgCache = {};    // カラー/グレーで SVG が違う (キーも違うが、古い方を持ち続けない)
      render();
    }
    document.getElementById("mode-gray").addEventListener("change", function () { if (this.checked) setGray(true); });
    document.getElementById("mode-normal").addEventListener("change", function () { if (this.checked) setGray(false); });
```

- [ ] **Step 6: 撮影スクリプトの `#chk-gray` を直す**

`docs/pdf-to-svg/_build/capture_screens.py:172` の `page.check("#chk-gray")` を `page.check("#mode-gray")` にする（`#gray-skipnote` の待ちはそのまま）。`skip_guard_if_present`（`:134-143`）とその呼び出し 2 か所、`step2d_guard.png` の撮影ブロック（`:247-251`）を削除する。

- [ ] **Step 7: 通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q && py -3.13 -m pytest pdf-to-svg -q`
Expected: 両方 PASS

- [ ] **Step 8: コミット**

```bash
git add pdf-to-svg/resources/web pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py docs/pdf-to-svg/_build/capture_screens.py
git commit -m "feat(pdf-to-svg): 手順 1 のスキャン画像の案内をバナーとバッジにし、書き出し方を 2 択カードに、Undo / Redo に文字ラベルを付ける"
```

---

### Task 7: 原稿 4 冊・画面写真・生成 HTML

**Files:**
- Modify: `docs/pdf-to-svg/src/設計正典.md:179-189`, `設計書.md`（2 章の図、7.2、8 章、8.1、8.2、13 章、改訂履歴）, `PdfToSvg_仕様一覧.md`（3.1〜3.3、4.1、18、19.1、20、入出力 6、テスト 43 ほか）, `操作手順書.md`（用語表、3 章 INFO、3.1、4 章、4.3、5 章、6 章、7 章、改訂履歴）
- Delete: `docs/pdf-to-svg/images/step2d_guard.png`
- Regenerate: `docs/pdf-to-svg/images/*.png`（`capture_screens.bat`）, `docs/pdf-to-svg/pdf-to-svg_手引き.html` / `_設計.html`（`build_all.py`）

- [ ] **Step 1: 設計正典**

`:179-189` の項を次に置き換える。

```markdown
- **ページごとの確認状態を持たない**: 手順 2・3 に「要確認 / 確認済み / スキップ」は無い。
  画面が持つのは `state` RPC が返すページごとの件数だけで、手順 2 は `matches2`（置換済み /
  未置換の箇所数）、手順 3 は `edits3`（削除 / 枠線 / 上書きの件数）から、レールの絞り込みと
  タグ・右パネル・手順 4 のまとめを毎回描く（`railPages` / `matchTotals` / `editTotals`）。
  「次へ」はどの手順でも無条件に進み、除外したいページは書き出しの「ページを指定」で選ぶ
  （「スキップを除く」は無い）。確認バーやまとめてスキップを足して戻さない。
- **純スキャンページは手順 2 の対象外にし、全ページ該当なら手順 2 を省略する**: 文字を持たない
  ページ（`Page.is_scanned`）は辞書が構造的に当たらない。`state` RPC の `scanned[]` を
  `S.scanned` にそのまま持ち、判定源はそれだけにする。手順 2 のレールは絞り込みに関わらず
  スキャンページを出さず（手順 3 は出す。上書きの対象になる）、全ページがスキャンなら手順 1 の
  「次へ」で手順 3 へ直行する（`skipsPhase2` / `phaseAfterLoad` / `phaseBeforeTrim` /
  `stepAllowed`。グレーモードが優先）。案内は手順 1 の常設バナー（`#scan-banner`）と
  ファイルカードのバッジ（`scannedCountOf`）で常に見えるようにし、モーダルやトーストで
  一度だけ見せる形へ戻さない。不可視 OCR 文字のページは対象外にしない（辞書が当たりうる）。
- **ページ移動は `page-jump.js` の 1 部品**: 手順 2・3 のキャンバス下の「ページへ移動」
  （ファイル選択 + ページ番号 + 前後）は同じ関数から 2 つ生成し、レールの絞り込みに出ていない
  ページへも番号で移動できる。番号の丸めは純粋関数 `resolveJump` に閉じる。
- **画面の説明文は 1 文 1 行**: 説明文は句点で改行し、手順を含む「使い方」は 1 文 1 項目の
  箇条書きにする。右パネル（幅 318px）の文は 1 行に収まる長さにし、件数を並べる行は項目ごとに
  `white-space: nowrap` にして項目の区切りでだけ折り返す。
```

- [ ] **Step 2: 設計書**

- 改訂履歴（`:33` の次）に `  - 2.23 | 2026-09-18 | 手順 2・3 のページごとの確認（要確認 / 確認済み / スキップ）と確認バー・「スキップを除く」を撤去し、state の matches2 / edits3 でレールと右パネルを組み直した。ページへ移動する部品（page-jump.js）、手順 1 のバナー・バッジ・書き出し方の 2 択、手順 4 のまとめの表、Undo / Redo の文字ラベルを追記` を足す。
- 2 章の Mermaid（`:66, :81`）から未確認ガードのノードと説明を外す。
- 7.2 節（`:781`）の `state` の項目を「files / pages / total / matches2（ページごとの `[置換済み, 未置換]`）/ edits3（`[削除, 枠線, 上書き]`）/ scanned / scannedPages / truncated / noBackground / ocrPages」に直し、「ガードバー」の記述を外す。
- 8 章の表（`:817-828`）: `index.html` の役割から「ガードバー」を外し、`page-jump.js` の行を足す（「手順 2・3 の「ページへ移動」部品。`resolveJump` は純粋関数」）。`:833` の絞り込みの記述を「絞り込み `S.filterFor` の既定は手順 2 が「辞書に一致したページだけ」、手順 3 が「すべてのページ」。ページの確認状態は無い」に直す。`:834` ステップ 2 に「右パネルの件数カード（`.count-card`。0 件でも緑にしない）と一致箇所の一覧、下部の「前のページ / 次の一致ページ」（`nextMatched`）」を、`:835` ステップ 3 に「右パネルは `removedList` / `borderList` / `coverList` の 3 本を引いた「このページの編集」の一覧（`.edit-row[data-kind]`）と、表示中ページがスキャンかどうかで切り替わる「使い方」（`HOWTO`）」を足す。`:841` の「未確認ガードバー」の段落を削除し、代わりに「**ページごとの確認を持たない理由**: 手順 3 は編集する操作であって確認する操作ではなく、編集していないページはそのまま書き出される。手順 2 も辞書に一致したページを見て回るだけで足りる。確認状態を持つと、全ページに「確認しました」を求める手間と、絞り込みに出ないページが生まれる」を置く。
- 8.1（`:847, :860`）: `#chk-gray` を「書き出し方」の 2 択カード（`#mode-normal` / `#mode-gray`。`.mode-card.on` で選択中を示し、流れ表示 `#flow-step2` は手順 2 省略時に打ち消し）に直す。
- 8.2（`:868-878`）: 判定源を `S.scanned`、レールを `railPages`、画面の段落をバナー（`#scan-banner`。全ページ用 / 混在用の文言）とバッジに書き換え、案内モーダル（`#skip2-dialog`）と `scannedPages` トーストの記述を削除。書き出しの段落は「`noskip` は無く、除外は「ページを指定」で行う」に。
- 13 章（`:995`）: テスト名を `test_state_counts_pending_candidates_and_reverted_matches` / `test_state_counts_removed_borders_and_covers_per_page`、`test_pdftosvg_state_js.py` の `test_railpages_*` / `test_nextmatched_*` / `test_skipsphase2_only_when_every_page_is_scanned`、`test_pdftosvg_page_jump_js.py`、E2E の `test_all_scanned_pdf_shows_banner_and_skips_step2_without_a_dialog` / `test_page_jump_moves_by_number_and_arrows_including_pages_hidden_from_the_rail` に更新する。

- [ ] **Step 3: 仕様一覧**

- 画面項目: 3.1 を「書き出し方 | `#mode-normal` / `#mode-gray` | 2 択カード。グレーは手順 2・3 を省略」、3.2 を「スキャン画像のバナー | `#scan-banner` | スキャンページが 1 ページ以上あるとき常設。全ページ用 / 混在用の文言」、3.3 を「ファイルカードのバッジ | `.file-card .chip` | 「スキャン画像 n / m ページ」」に。4.1 を「ページレール | `#pagenav` | 既定は「辞書に一致したページだけ」。各行に「置換 a ・ 未置換 b」。スキャンページは出さない。見出しに「対象外 k」」に。新規 4.2「ページへ移動 | `#pgnav-2` / `#pgnav-3`（`.page-jump`） | ファイル選択 + ページ番号 + 移動 + 前後」、4.3「件数カード | `.count-card` | このページで置き換えた語。0 件でも緑にしない」、14.2「このページの編集 | `#trim-dyn .edit-row` | 削除 / 枠線 / 上書きの一覧。行ごとに戻す / 削除」、14.3「使い方 | `.howto` | 通常 / スキャン画像で文言を切り替える」。18 を「表示中のページのみ / 全ページ / ページを指定」、19.1 を「まとめ | `#export-summary`（`.sum-table`） | PDF / 用語の置換（置換 a か所（p ページ）・未置換 b か所・対象外 k ページ）/ 削除・枠線（編集したページ n・削除 x・枠線 y・上書き z）」、20 を「Undo/Redo | `#btn-undo` / `#btn-redo` | 文字ラベル「元に戻す」「やり直し」付き。Ctrl+Z / Ctrl+Y」。
- 入出力 6: 「表示中のページのみ / 全ページ / ページを指定」。
- テスト表: 42・43 を新しいテスト名と観点に書き換え、44「`test_pdftosvg_page_jump_js.py` / E2E `test_page_jump_*`」を足す。

- [ ] **Step 4: 操作手順書**

- 改訂履歴に `  - 2.9 | 2026-09-18 | ページごとの「確認しました / スキップ」と黄色いバーを廃止（4 章・4.3 節・5 章・6 章・7 章）、ページへ移動（4 章）、スキャン画像の案内（3 章）、書き出し方の 2 択（3.1 節）を反映`（既存の 2.9 がある場合は 2.10）。
- 用語表（`:44`）の「スキップ」の行を削除する。
- 3 章の INFO（`:80`）を「選んだ PDF にスキャン画像のページがあると、ファイル一覧の上に黄色い案内が出て、各 PDF に「スキャン画像 n / m ページ」の印が付きます。すべてがスキャン画像のときはステップ 2 を省略し、「次へ」でステップ 3 に直接進みます。文字を置き換えたいときは、ステップ 3 の「上書き」ツール（5.5 節）で矩形と置換語を置いてください。」に。
- 3.1（`:83-93`）: 「ドロップゾーンの下の「書き出し方」で **「図だけをグレースケールで書き出す」** を選びます」に直す（画像は再撮影）。
- 4 章（`:95-107`）: 手順 4「内容がよければ「確認しました」…」を削除し、番号を詰める。「ページが複数あるときは、左の一覧（辞書に一致したページだけが出ます）か、画面下の「ページへ移動」（ファイルと番号を選んで「移動」、または ‹ › で前後）で次のページへ移ります」を足す。
- 4.3（`:136-145`）を節ごと削除する。
- 5 章（`:149, :209, :211`）: 「編集が不要なら…確認しました」を削除。INFO の「すでに「確認しました」を押したページは…」を削除。「各ページの編集が済んだら…」を「編集が済んだら、右下の **「書き出しへ」** を押します。編集していないページはそのまま書き出されます。」に。
- 6 章（`:222-224`）: 「スキップを除く」の行を削除。
- 7 章（`:256`）: 「黄色い警告バーが出た」の行を削除。

- [ ] **Step 5: 写真と HTML を再生成する**

```bash
git rm docs/pdf-to-svg/images/step2d_guard.png
docs\pdf-to-svg\_build\capture_screens.bat
py -3.13 docs/_build/build_all.py
py -3.13 -m pytest docs/_build -q
```
Expected: 撮影が 6 枚 + グレー 3 枚保存され、`build_all.py` が `[ok]` を 4 行出し、`docs/_build` の pytest が PASS。`git status` で `docs/pdf-to-svg/images/*.png` と `pdf-to-svg_手引き.html` / `_設計.html` に差分が出る。

- [ ] **Step 6: コミット**

```bash
git add docs/pdf-to-svg docs/superpowers/plans/2026-09-18-pdftosvg-ui-review.md
git commit -m "docs(pdf-to-svg): 画面の見直し（確認の撤去・ページへ移動・手順 1 の案内と書き出し方・手順 4 の表）を原稿 4 冊に反映し、写真と HTML を再生成する"
```

---

### Task 8: リリースの差し替え

- [ ] **Step 1: push が済んでいることを確認する**

Run: `git status -sb`（`main...origin/main` で ahead が無いこと。ある場合は `git push origin main` を手で実行し、pre-push の検証一式が通るのを待つ）

- [ ] **Step 2: リリースノートに今回分の節を足す**

`gh release view 2026.09.08 --json body -q .body` で本文を取り、`## 含まれる変更` の直後に次の `###` 節を追記したファイルを作る（既存の節は消さない）。

```markdown
### 画面の見直し: ページごとの確認の撤去・ページへ移動・手順 1 の案内と書き出し方（2026-09-18）

- 手順 2・3 の「要確認 / 確認済み / スキップ」、黄色い確認バー、まとめてスキップ・範囲指定、書き出しの「スキップを除く」を撤去。手順 2 のレールは辞書に一致したページ（置換 / 未置換の件数）、手順 3 は編集したページ（削除 / 枠線 / 上書きの件数）を出す。`state` RPC は `changed2 / changed3` の代わりに `matches2 / edits3` を返す
- 手順 2・3 の画面下に「ページへ移動」（ファイル選択 + ページ番号 + 前後。`page-jump.js`）
- 手順 1: スキャン画像の案内をモーダルとトーストから常設バナーとカードのバッジへ。グレースケールのチェックボックスを「書き出し方」の 2 択カードへ
- 手順 2 の件数カード（0 件でも緑にしない）、手順 3 の「このページの編集」と使い方、手順 4 のまとめの表、Undo / Redo の文字ラベル
- 画面の説明文は 1 文 1 行・使い方は箇条書き。原稿 4 冊・写真・生成 HTML を更新
```

- [ ] **Step 3: タグを動かしてノートを差し替える**

```bash
git tag -f 2026.09.08 <HEAD の SHA>
git push origin -f refs/tags/2026.09.08
gh release edit 2026.09.08 --notes-file <上で作ったファイル>
```
（自動モードではタグの force push が拒否されることがある。その場合は利用者に上の 2 行を提示して実行してもらう。）

---

## 自己レビュー

- 仕様書 3.1（Undo/Redo・撤去・無条件の「次へ」・説明文の書き方）→ Task 4 / 6。3.2（手順 1）→ Task 6。3.3（手順 2）→ Task 3 / 4 / 4b / 5。3.4（手順 3）→ Task 3 / 4 / 4c / 5。3.5（ページへ移動）→ Task 5。3.6（手順 4）→ Task 4。4.1（状態）→ Task 2。4.2（`state` RPC）→ Task 1。4.3（手順 3 の一覧）→ Task 4c。5（撤去一覧）→ Task 3 / 4 / 6。6（テスト）→ 各 Task。7（原稿・写真）→ Task 7。8（段階）→ Task の順序。
- 型の一貫性: `matches2` は RPC で `[[applied, pending]]`、`S.matches2` で `{applied, pending}`（`applyState` が変換）。`edits3` も同様。`railPages(phase)` は通し index の配列。`resolveJump(files, fileStart, fileIndex, value)` は通し index か -1。
- 順序の注意: Task 1 → 2 → 3 → 4 は連続して行い、Task 4 まで終えてから push の検証（E2E）を通す。
