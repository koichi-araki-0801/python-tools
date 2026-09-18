# =============================================================================
# test_pdftosvg_state_js.py — resources/web/state.js (件数ベースの状態モデル) の単体
# =============================================================================
# ページの確認状態は持たず、サーバの `state` RPC が返す件数 (matches2/edits3) と
# スキャン判定 (scanned) をそのまま取り込む状態機械を、実ブラウザ (Edge) で検証する。
# `S` はモジュールシングルトンのため、`window.__reset` を一度だけ定義し、autouse
# fixture で毎テスト前に呼ぶ (ページ再読込はしない)。
import pytest

from .pdftosvg_js_harness import js

pytestmark = pytest.mark.browser

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


@pytest.fixture(scope="module")
def st(edge_page):
    edge_page.evaluate("import('/state.js').then(m => { window.__st = m; })")
    edge_page.evaluate(RESET)
    return edge_page


@pytest.fixture(autouse=True)
def _reset_state(st):
    js(st, "window.__reset()")


# ── applyState ──


def test_applystate_file_start_is_cumulative_page_counts(st):
    assert js(st, "window.__st.S.FILE_START") == [0, 2]


def test_applystate_resets_current_page_when_page_count_shrinks(st):
    js(st, "window.__st.S.page = 4")
    js(
        st,
        """window.__st.applyState({
          files: [{ name: "a.pdf", pages: 1 }],
          pages: [{ fileIndex: 0, pageInFile: 0 }],
          total: 1, matches2: [[0, 0]], edits3: [[0, 0, 0]], scanned: [false],
        })""",
    )
    assert js(st, "window.__st.S.page") == 0


def test_applystate_discards_rail_selection_and_file_collapse_when_page_list_changes(st):
    js(st, "window.__st.S.collapsed['2:1'] = true")
    js(
        st,
        """window.__st.applyState({
          files: [{ name: "a.pdf", pages: 2 }],
          pages: [{ fileIndex: 0, pageInFile: 0 }, { fileIndex: 0, pageInFile: 1 }],
          total: 2, matches2: [[1, 0], [0, 0]], edits3: [[0, 0, 0], [0, 0, 0]], scanned: [false, false],
        })""",
    )
    assert js(st, "window.__st.S.collapsed") == {}


def test_applystate_reload_of_same_page_list_preserves_selection_and_collapse(st):
    js(st, "window.__st.S.collapsed['2:1'] = true")
    js(
        st,
        """window.__st.applyState({
          files: [{ name: "a.pdf", pages: 2 }, { name: "b.pdf", pages: 3 }],
          pages: [
            { fileIndex: 0, pageInFile: 0 }, { fileIndex: 0, pageInFile: 1 },
            { fileIndex: 1, pageInFile: 0 }, { fileIndex: 1, pageInFile: 1 }, { fileIndex: 1, pageInFile: 2 },
          ],
          total: 5, matches2: [[1, 0], [0, 0], [2, 1], [0, 1], [0, 0]],
          edits3: [[0, 0, 0], [1, 0, 0], [0, 0, 0], [0, 2, 1], [0, 0, 0]], scanned: [false, false, false, false, false],
        })""",
    )
    assert js(st, "window.__st.S.collapsed") == {"2:1": True}


# ── invalidateAll ──


def test_invalidateall_discards_svg_cache_for_all_pages(st):
    js(st, 'window.__st.S.svgCache = { "0:0": { svg: "<svg/>" }, "1:2": { svg: "<svg/>" } }')
    js(st, "window.__st.invalidateAll()")
    assert js(st, "window.__st.S.svgCache") == {}


# ── 導出 ──


def test_derived_pkey_curelsel_key_by_current_page_fi_pi(st):
    js(st, "window.__st.S.page = 2")
    assert js(st, "window.__st.pkey()") == "1:0"
    js(st, "window.__st.curElSel().x = true")
    assert js(st, "window.__st.S.elSel['1:0']") == {"x": True}


# ── 遷移 ──


def test_transition_resetphaseui_clears_element_and_cover_selection_and_tool(st):
    js(st, "window.__st.S.elSel = { '0:0': { e1: true } }")
    js(st, "window.__st.S.coverSel = 'c1'")
    js(st, "window.__st.S.borderSel = 'b1'")
    js(st, "window.__st.S.tool = 'cover'")
    js(st, "window.__st.S.dragMoved = true")
    js(st, "window.__st.resetPhaseUi()")
    assert js(st, "window.__st.S.elSel") == {}
    assert js(st, "window.__st.S.coverSel") is None
    assert js(st, "window.__st.S.borderSel") is None
    assert js(st, "window.__st.S.tool") is None
    assert js(st, "window.__st.S.dragMoved") is False


def test_transition_advancephase_resets_selection_and_tool(st):
    js(st, "window.__st.S.phase = 3")
    js(st, "window.__st.S.elSel = { '0:0': { e1: true } }")
    js(st, "window.__st.S.coverSel = 'c1'")
    js(st, "window.__st.S.borderSel = 'b1'")
    js(st, "window.__st.S.tool = 'crop'")
    js(st, "window.__st.S.dragMoved = true")
    js(st, "window.__st.advancePhase()")
    assert js(st, "window.__st.S.phase") == 4
    assert js(st, "window.__st.S.elSel") == {}
    assert js(st, "window.__st.S.coverSel") is None
    assert js(st, "window.__st.S.borderSel") is None
    assert js(st, "window.__st.S.tool") is None
    assert js(st, "window.__st.S.dragMoved") is False

# ── 書き出し範囲 ──

_PARSE_SPEC_STUB = 'const parseSpecStub = (spec, max) => (spec === "1-2" ? [1, 2].filter((n) => n <= max) : []);'


def test_export_range_all_mode_is_all_pages(st):
    expr = f"""(() => {{
      {_PARSE_SPEC_STUB}
      return window.__st.exportPageList("", parseSpecStub).length;
    }})()"""
    assert js(st, expr) == 5


def test_export_range_spec_mode_returns_pages_in_target_file_with_file_index(st):
    js(st, "window.__st.S.expMode = 'spec'")
    js(st, "window.__st.S.expFile = 1")
    expr = f"""(() => {{
      {_PARSE_SPEC_STUB}
      return window.__st.exportPageList("1-2", parseSpecStub);
    }})()"""
    assert js(st, expr) == [
        {"fileIndex": 1, "pageInFile": 0}, {"fileIndex": 1, "pageInFile": 1},
    ]
    js(st, "window.__st.S.expFile = 9")
    assert js(st, expr) == []


def test_export_range_expcount_is_one_in_page_mode_when_pages_exist(st):
    js(st, "window.__st.S.expMode = 'page'")
    expr = f"""(() => {{
      {_PARSE_SPEC_STUB}
      return window.__st.expCount("", parseSpecStub);
    }})()"""
    assert js(st, expr) == 1


def test_export_range_zipname_keeps_source_name_or_generic_when_mixed(st):
    assert js(st, "window.__st.zipName([{ fileIndex: 0 }, { fileIndex: 0 }])") == "a_svg.zip"
    assert js(st, "window.__st.zipName([{ fileIndex: 0 }, { fileIndex: 1 }])") == "svg_export.zip"


# ── ZIP 送信の分割 ──


def test_zip_chunking_splits_into_budget_sized_chunks_in_order(st):
    expr = """(() => {
      const size = (e) => e.n;
      return window.__st.chunkBySize([{ n: 4 }, { n: 4 }, { n: 3 }, { n: 2 }], size, 8);
    })()"""
    assert js(st, expr) == [[{"n": 4}, {"n": 4}], [{"n": 3}, {"n": 2}]]


def test_zip_chunking_keeps_single_oversized_item_as_its_own_chunk(st):
    expr = """(() => {
      const size = (e) => e.n;
      return window.__st.chunkBySize([{ n: 1 }, { n: 99 }, { n: 1 }], size, 8);
    })()"""
    assert js(st, expr) == [[{"n": 1}], [{"n": 99}], [{"n": 1}]]


def test_zip_chunking_empty_input_yields_no_chunks(st):
    expr = """(() => {
      const size = (e) => e.n;
      return window.__st.chunkBySize([], size, 8);
    })()"""
    assert js(st, expr) == []


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
        matches2: [[0, 0]], edits3: [[0, 0, 0]], scanned: [false] })""")
    assert js(st, "Object.keys(window.__st.S.figSel)") == []
    assert js(st, "Object.keys(window.__st.S.figCand)") == []


def test_counting_before_seed_does_not_block_adoption(st):
    r = {"x": 10, "y": 20, "w": 30, "h": 40}
    assert js(st, "window.__st.figCount()") == 0
    js(st, "window.__st.S.expMode = 'all'; window.__st.exportFigureList()")
    js(st, "r => window.__st.seedFigSel(1, [r])", r)
    assert js(st, "window.__st.figSelOf(1)") == [r]
    assert js(st, "window.__st.figCount()") == 1


def test_seed_treats_null_in_flight_marker_as_first_time(st):
    r = {"x": 1, "y": 2, "w": 3, "h": 4}
    js(st, "window.__st.S.figCand['0:0'] = null")
    js(st, "r => window.__st.seedFigSel(0, [r])", r)
    assert js(st, "window.__st.figSelOf(0)") == [r]


def test_svg_keys_returns_both_color_and_gray_keys(st):
    assert js(st, "window.__st.svgKeys(1, 2)") == ["1:2", "1:2:g"]


def test_svg_key_delegates_to_svg_keys(st):
    assert js(st, "window.__st.svgKey(1, 2)") == js(st, "window.__st.svgKeys(1, 2)[0]")
    js(st, "window.__st.S.gray = true")
    assert js(st, "window.__st.svgKey(1, 2)") == js(st, "window.__st.svgKeys(1, 2)[1]")


def test_adopted_figures_lists_all_pages_regardless_of_exp_mode(st):
    a = {"x": 1, "y": 2, "w": 3, "h": 4}
    b = {"x": 5, "y": 6, "w": 7, "h": 8}
    js(st, "([a, b]) => { window.__st.figSelOf(0).push(a); window.__st.figSelOf(3).push(a, b); }", [a, b])
    js(st, "window.__st.S.expMode = 'page'; window.__st.S.page = 0")  # 一覧は expMode に関係なく全ページ
    assert js(st, "window.__st.adoptedFigures()") == [
        {"fileIndex": 0, "pageInFile": 0, "figIndex": 1, "rect": a},
        {"fileIndex": 1, "pageInFile": 1, "figIndex": 1, "rect": a},
        {"fileIndex": 1, "pageInFile": 1, "figIndex": 2, "rect": b},
    ]


def test_adopted_figures_is_empty_before_any_adoption(st):
    assert js(st, "window.__st.adoptedFigures()") == []


# ── 手順 2 の省略 (純スキャンページ) ──


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


def test_gray_mode_wins_over_skipsphase2(st):
    _apply(st, [True, True, True, True, True])
    js(st, "window.__st.S.gray = true")
    assert js(st, "window.__st.phaseAfterLoad()") == 4
    assert js(st, "[1,2,3,4].map(n => window.__st.stepAllowed(n))") == [True, False, False, True]


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
