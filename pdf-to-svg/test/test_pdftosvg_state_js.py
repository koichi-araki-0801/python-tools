# =============================================================================
# test_pdftosvg_state_js.py — resources/web/state.js の単体移植
# =============================================================================
# 旧 state.test.js (vitest) の describe 7 / it 27 と 1:1。期待値・入力は旧テストから
# 逐語で写す。`S` はモジュールシングルトンのため、旧 beforeEach(reset) を window 関数
# として一度だけ定義し、autouse fixture で毎テスト前に呼ぶ(ページ再読込はしない)。
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
    changed2: [true, false, true, true, false],
    changed3: [false, false, false, false, false],
  });
  m.S.phase = 2; m.S.page = 0; m.S.guarding = false;
  m.S.selFor = { 2: {}, 3: {} };
  m.S.expMode = "all"; m.S.expFile = 0;
  m.S.gray = false; m.S.figCand = {}; m.S.figSel = {};
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


# ── 純粋ヘルパ ──


def test_pure_helpers_counts_tallies_by_status(st):
    result = js(st, "window.__st.counts(['pending', 'reviewed', 'skipped', 'none', 'pending'])")
    assert result == {"done": 1, "skip": 1, "pend": 2, "none": 1}


def test_pure_helpers_pass_all_always_passes_others_match_only(st):
    assert js(st, "window.__st.pass('pending', 'all')") is True
    assert js(st, "window.__st.pass('pending', 'pending')") is True
    assert js(st, "window.__st.pass('reviewed', 'pending')") is False


def test_pure_helpers_initstatus_derives_pending_none_from_changed(st):
    assert js(st, "window.__st.initStatus([true, false])") == ["pending", "none"]


# ── applyState ──


def test_applystate_file_start_is_cumulative_page_counts(st):
    assert js(st, "window.__st.S.FILE_START") == [0, 2]


def test_applystate_initializes_status_from_changed_and_discards_caches(st):
    assert js(st, "window.__st.S.status2") == ["pending", "none", "pending", "pending", "none"]
    assert js(st, "window.__st.S.svgCache") == {}
    assert js(st, "window.__st.S.elSel") == {}


def test_applystate_resets_current_page_when_page_count_shrinks(st):
    js(st, "window.__st.S.page = 4")
    js(
        st,
        """window.__st.applyState({
          files: [{ name: "a.pdf", pages: 1 }],
          pages: [{ fileIndex: 0, pageInFile: 0 }],
          total: 1, changed2: [false], changed3: [false],
        })""",
    )
    assert js(st, "window.__st.S.page") == 0


def test_applystate_reload_of_same_page_list_preserves_confirmation_status(st):
    js(st, "window.__st.S.status2 = ['reviewed', 'skipped', 'pending', 'pending', 'none']")
    js(
        st,
        """window.__st.applyState({
          files: [{ name: "a.pdf", pages: 2 }, { name: "b.pdf", pages: 3 }],
          pages: [
            { fileIndex: 0, pageInFile: 0 }, { fileIndex: 0, pageInFile: 1 },
            { fileIndex: 1, pageInFile: 0 }, { fileIndex: 1, pageInFile: 1 }, { fileIndex: 1, pageInFile: 2 },
          ],
          total: 5,
          changed2: [true, true, true, true, false],
          changed3: [false, false, false, false, false],
        })""",
    )
    assert js(st, "window.__st.S.status2") == ["reviewed", "skipped", "pending", "pending", "none"]


def test_applystate_toggles_status_to_pending_or_none_on_changed_flip(st):
    js(st, "window.__st.S.status2 = ['reviewed', 'none', 'pending', 'pending', 'none']")
    js(
        st,
        """window.__st.applyState({
          files: [{ name: "a.pdf", pages: 2 }, { name: "b.pdf", pages: 3 }],
          pages: [
            { fileIndex: 0, pageInFile: 0 }, { fileIndex: 0, pageInFile: 1 },
            { fileIndex: 1, pageInFile: 0 }, { fileIndex: 1, pageInFile: 1 }, { fileIndex: 1, pageInFile: 2 },
          ],
          total: 5,
          changed2: [false, true, true, true, false],
          changed3: [false, false, false, false, false],
        })""",
    )
    assert js(st, "window.__st.S.status2[0]") == "none"
    assert js(st, "window.__st.S.status2[1]") == "pending"
    assert js(st, "window.__st.S.status2[2]") == "pending"


def test_applystate_rebuilds_status_via_initstatus_when_page_list_differs(st):
    js(st, "window.__st.S.status2 = ['reviewed', 'skipped']")
    js(
        st,
        """window.__st.applyState({
          files: [{ name: "c.pdf", pages: 3 }],
          pages: [
            { fileIndex: 0, pageInFile: 0 }, { fileIndex: 0, pageInFile: 1 }, { fileIndex: 0, pageInFile: 2 },
          ],
          total: 3,
          changed2: [true, false, true],
          changed3: [false, false, false],
        })""",
    )
    assert js(st, "window.__st.S.status2") == ["pending", "none", "pending"]


def test_applystate_discards_rail_selection_and_file_collapse_when_page_list_changes(st):
    js(st, "window.__st.S.selFor[2] = { 0: true, 3: true }")
    js(st, "window.__st.S.collapsed['2:1'] = true")
    js(
        st,
        """window.__st.applyState({
          files: [{ name: "a.pdf", pages: 2 }],
          pages: [{ fileIndex: 0, pageInFile: 0 }, { fileIndex: 0, pageInFile: 1 }],
          total: 2, changed2: [true, false], changed3: [false, false],
        })""",
    )
    assert js(st, "window.__st.S.selFor") == {"2": {}, "3": {}}
    assert js(st, "window.__st.S.collapsed") == {}


def test_applystate_reload_of_same_page_list_preserves_selection_and_collapse(st):
    js(st, "window.__st.S.selFor[2] = { 0: true }")
    js(st, "window.__st.S.collapsed['2:1'] = true")
    js(
        st,
        """window.__st.applyState({
          files: [{ name: "a.pdf", pages: 2 }, { name: "b.pdf", pages: 3 }],
          pages: [
            { fileIndex: 0, pageInFile: 0 }, { fileIndex: 0, pageInFile: 1 },
            { fileIndex: 1, pageInFile: 0 }, { fileIndex: 1, pageInFile: 1 }, { fileIndex: 1, pageInFile: 2 },
          ],
          total: 5, changed2: [true, false, true, true, false], changed3: [false, false, false, false, false],
        })""",
    )
    assert js(st, "window.__st.S.selFor[2]") == {"0": True}
    assert js(st, "window.__st.S.collapsed") == {"2:1": True}


# ── invalidateAll ──


def test_invalidateall_discards_svg_cache_for_all_pages(st):
    js(st, 'window.__st.S.svgCache = { "0:0": { svg: "<svg/>" }, "1:2": { svg: "<svg/>" } }')
    js(st, "window.__st.invalidateAll()")
    assert js(st, "window.__st.S.svgCache") == {}


# ── 導出 (phase 別の別名参照と選択集合) ──


def test_derived_statusarr_changedarr_switch_by_phase(st):
    assert js(st, "window.__st.statusArr() === window.__st.S.status2") is True
    assert js(st, "window.__st.changedArr() === window.__st.S.changed2") is True
    js(st, "window.__st.S.phase = 3")
    assert js(st, "window.__st.statusArr() === window.__st.S.status3") is True
    assert js(st, "window.__st.changedArr() === window.__st.S.changed3") is True


def test_derived_pkey_curelsel_key_by_current_page_fi_pi(st):
    js(st, "window.__st.S.page = 2")
    assert js(st, "window.__st.pkey()") == "1:0"
    js(st, "window.__st.curElSel().x = true")
    assert js(st, "window.__st.S.elSel['1:0']") == {"x": True}


def test_derived_selkeys_selcount_clearsel_scope_to_current_phase(st):
    js(st, "window.__st.selSet()[0] = true")
    js(st, "window.__st.selSet()[3] = true")
    js(st, "window.__st.S.selFor[3][1] = true")
    assert sorted(js(st, "window.__st.selKeys()")) == ["0", "3"]
    assert js(st, "window.__st.selCount()") == 2
    js(st, "window.__st.clearSel()")
    assert js(st, "window.__st.selCount()") == 0
    assert js(st, "window.__st.S.selFor[3][1]") is True


def test_derived_statusofcur_returns_status_of_current_page(st):
    js(st, "window.__st.S.page = 1")
    assert js(st, "window.__st.statusOfCur()") == "none"


# ── 遷移 ──


def test_transition_nextpending_prefers_ahead_and_wraps_to_start(st):
    js(st, "window.__st.S.page = 2")
    assert js(st, "window.__st.nextPending(window.__st.S.status2)") == 3
    js(st, "window.__st.S.status2[3] = 'reviewed'")
    assert js(st, "window.__st.nextPending(window.__st.S.status2)") == 0
    js(st, "window.__st.S.status2[0] = 'skipped'")
    js(st, "window.__st.S.status2[2] = 'reviewed'")
    assert js(st, "window.__st.nextPending(window.__st.S.status2)") == -1


def test_transition_firstpending_searches_from_start_default_zero(st):
    assert js(st, "window.__st.firstPending(window.__st.S.status2)") == 0
    js(st, "window.__st.S.status2 = ['reviewed', 'none', 'pending', 'none', 'none']")
    assert js(st, "window.__st.firstPending(window.__st.S.status2)") == 2
    assert js(st, "window.__st.firstPending(['none', 'none', 'none', 'none', 'none'])") == 0


def test_transition_advancephase_moves_2_to_3_to_4_and_clears_guard_and_target_selection(st):
    js(st, "window.__st.S.page = 4")
    js(st, "window.__st.S.guarding = true")
    js(st, "window.__st.S.selFor[3][1] = true")
    js(st, "window.__st.advancePhase()")
    assert js(st, "window.__st.S.phase") == 3
    assert js(st, "window.__st.S.page") == 0
    assert js(st, "window.__st.S.guarding") is False
    assert js(st, "Object.keys(window.__st.S.selFor[3]).filter(k => window.__st.S.selFor[3][k])") == []
    js(st, "window.__st.advancePhase()")
    assert js(st, "window.__st.S.phase") == 4


# ── 書き出し範囲 ──

_PARSE_SPEC_STUB = 'const parseSpecStub = (spec, max) => (spec === "1-2" ? [1, 2].filter((n) => n <= max) : []);'


def test_export_range_all_mode_is_all_pages(st):
    expr = f"""(() => {{
      {_PARSE_SPEC_STUB}
      return window.__st.exportPageList("", parseSpecStub).length;
    }})()"""
    assert js(st, expr) == 5


def test_export_range_noskip_excludes_pages_skipped_in_either_step(st):
    js(st, "window.__st.S.expMode = 'noskip'")
    js(st, "window.__st.S.status2[1] = 'skipped'")
    js(st, "window.__st.S.status3[4] = 'skipped'")
    expr = f"""(() => {{
      {_PARSE_SPEC_STUB}
      return window.__st.exportPageList("", parseSpecStub).length;
    }})()"""
    assert js(st, expr) == 3


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
        changed2: [false], changed3: [false] })""")
    assert js(st, "Object.keys(window.__st.S.figSel)") == []
    assert js(st, "Object.keys(window.__st.S.figCand)") == []
