# =============================================================================
# test_grapheditor_utils_js.py — resources/web/js/utils.js の単体移植
# =============================================================================
# 旧 3 ファイル (vitest) と 1:1:
# - editor_state_fields.test.ts (describe 1 本・it 6 件) — stateEquals
# - editor_shortcuts.test.ts (describe 1 本・it 4 件) — acceptsShortcut
# - editor_label_text.test.ts (describe 1 本・it 5 件) — extractPercentText
# 期待値・入力は旧テストから逐語で写す。
#
# state_fields はテスト側ヘルパ (`snapshot` / `legacyEquals` / `baseState` / `mutate` /
# `VARIANTS`) を旧コード逐語で JS 側に丸ごと再構築し、1 回の evaluate で
# 「ヘルパ定義 + 断言」を返す IIFE として評価する(`STATE_FIELDS` の値は `copy`/`equals`
# 関数を持ちシリアライズ不能なため)。

import pytest

from grapheditor_js_harness import js

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def utils(edge_page, web_root_url):
    edge_page.evaluate("import('/js/utils.js').then(m => { window.__u = m; })")
    return edge_page


def _iife(body):
    """`body` (JS 文の並び) を包んで即時実行関数式にする。"""
    return f"(() => {{\n{body}\n}})()"


# `LabelState.snapshot()` 相当 (`STATE_FIELDS` の `copy` を通した複製) と、置き換え前の
# 判定 (`JSON.stringify` 比較) を旧テストの逐語のまま JS 側で再構築する。
_STATE_HELPERS = """
function snapshot(state) {
  const snap = {};
  for (const [k, f] of Object.entries(window.__u.STATE_FIELDS)) snap[k] = f.copy(state[k]);
  return snap;
}
function legacyEquals(a, b) {
  return JSON.stringify(snapshot(a)) === JSON.stringify(b);
}
function baseState() {
  return {
    textTx: { x: 0, y: 0 },
    leaderPts: [{ x: 1, y: 2 }, { x: 3, y: 4 }],
    leaderVisible: true,
    fill: "#111111",
    lineCount: 1,
    nameScaleX: 1,
    _auto: false,
  };
}
function mutate(patch) {
  return { ...baseState(), ...patch };
}
const VARIANTS = [
  ["無変更", baseState()],
  ["textTx.x", mutate({ textTx: { x: 1, y: 0 } })],
  ["textTx.y", mutate({ textTx: { x: 0, y: -0.5 } })],
  ["leaderPts の座標", mutate({ leaderPts: [{ x: 1, y: 2 }, { x: 3, y: 5 }] })],
  ["leaderPts の点数 (増)", mutate({ leaderPts: [{ x: 1, y: 2 }, { x: 9, y: 9 }, { x: 3, y: 4 }] })],
  ["leaderPts の点数 (減)", mutate({ leaderPts: [{ x: 1, y: 2 }] })],
  ["leaderPts が空", mutate({ leaderPts: [] })],
  ["leaderVisible", mutate({ leaderVisible: false })],
  ["fill", mutate({ fill: "#ffffff" })],
  ["lineCount", mutate({ lineCount: 2 })],
  ["nameScaleX", mutate({ nameScaleX: 0.85 })],
  ["_auto (自動 leader か)", mutate({ _auto: true })],
];
"""


# ── stateEquals ──


def test_stateequals_matches_legacy_serialize_compare_against_initial_snapshot(utils):
    body = _STATE_HELPERS + """
const initial = snapshot(baseState());
return VARIANTS.map(([label, state]) => ({
  label,
  ok: window.__u.stateEquals(state, initial) === legacyEquals(state, initial),
}));
"""
    result = js(utils, _iife(body))
    for entry in result:
        assert entry["ok"], entry["label"]


def test_stateequals_equal_states_equal_any_single_field_diff_not_equal(utils):
    body = _STATE_HELPERS + """
const initial = snapshot(baseState());
return {
  baseEqualsInitial: window.__u.stateEquals(baseState(), initial),
  // 複製 (`copy`) を挟んでも同値のままであること (参照比較へ退化していない)。
  snapshotEqualsInitial: window.__u.stateEquals(snapshot(baseState()), initial),
  variants: VARIANTS.slice(1).map(([label, state]) => ({
    label,
    notEqual: window.__u.stateEquals(state, initial) === false,
  })),
};
"""
    result = js(utils, _iife(body))
    assert result["baseEqualsInitial"] is True
    assert result["snapshotEqualsInitial"] is True
    for entry in result["variants"]:
        assert entry["notEqual"], entry["label"]


def test_stateequals_either_side_missing_is_not_equal(utils):
    body = """
return [
  window.__u.stateEquals(
    { textTx: { x: 0, y: 0 }, leaderPts: [], leaderVisible: true, fill: "#111111",
      lineCount: 1, nameScaleX: 1, _auto: false },
    null,
  ),
  window.__u.stateEquals(null, { textTx: { x: 0, y: 0 } }),
  window.__u.stateEquals(null, null),
];
"""
    result = js(utils, _iife(body))
    assert result == [False, False, False]


def test_stateequals_fill_null_on_both_sides_equal_one_side_only_not_equal(utils):
    # `fill` は `originalFill=null` の `<text>` がありうる (`label-state.js`)。
    body = _STATE_HELPERS + """
const a = mutate({ fill: null });
const b = mutate({ fill: null });
return [
  window.__u.stateEquals(a, snapshot(b)),
  window.__u.stateEquals(a, snapshot(baseState())),
  window.__u.stateEquals(baseState(), snapshot(a)),
];
"""
    result = js(utils, _iife(body))
    assert result == [True, False, False]


def test_stateequals_auto_field_is_in_state_fields_and_roundtrips_via_snapshot(utils):
    body = _STATE_HELPERS + """
return {
  hasAuto: Object.keys(window.__u.STATE_FIELDS).includes("_auto"),
  snapAuto: snapshot(mutate({ _auto: true }))._auto,
  eq: window.__u.stateEquals(mutate({ _auto: true }), snapshot(baseState())),
};
"""
    result = js(utils, _iife(body))
    assert result["hasAuto"] is True
    assert result["snapAuto"] is True
    assert result["eq"] is False


def test_stateequals_every_field_has_copy_and_equals(utils):
    body = """
return Object.entries(window.__u.STATE_FIELDS).map(([k, f]) => ({
  k,
  copyIsFn: typeof f.copy === "function",
  equalsIsFn: typeof f.equals === "function",
}));
"""
    result = js(utils, _iife(body))
    for entry in result:
        assert entry["copyIsFn"], entry["k"]
        assert entry["equalsIsFn"], entry["k"]


# ── acceptsShortcut ──


def test_acceptsshortcut_no_scope_accepted_while_input_focused(utils):
    scopes = ["document", "save", "open"]
    cases = []
    for scope in scopes:
        cases.append([{"tagName": "INPUT", "isContentEditable": False}, 2, scope])
        cases.append([{"tagName": "TEXTAREA", "isContentEditable": False}, 2, scope])
        cases.append([{"tagName": "SELECT", "isContentEditable": False}, 2, scope])
        cases.append([{"tagName": "DIV", "isContentEditable": True}, 2, scope])
    # 小文字の `tagName` (XHTML 等) でも同じ判定になる。
    cases.append([{"tagName": "input", "isContentEditable": False}, 2, "document"])
    result = js(
        utils,
        "cases => cases.map(([el, phase, scope]) => window.__u.acceptsShortcut(el, phase, scope))",
        cases,
    )
    assert result == [False] * len(cases)


def test_acceptsshortcut_document_scope_accepted_only_at_phase2(utils):
    body_el = {"tagName": "BODY", "isContentEditable": False}
    cases = [[body_el, 1, "document"], [body_el, 2, "document"], [body_el, 3, "document"]]
    result = js(
        utils,
        "cases => cases.map(([el, phase, scope]) => window.__u.acceptsShortcut(el, phase, scope))",
        cases,
    )
    assert result == [False, True, False]


def test_acceptsshortcut_save_at_phase2_and_3_open_at_any_phase(utils):
    body_el = {"tagName": "BODY", "isContentEditable": False}
    save_cases = [[body_el, 1, "save"], [body_el, 2, "save"], [body_el, 3, "save"]]
    save_result = js(
        utils,
        "cases => cases.map(([el, phase, scope]) => window.__u.acceptsShortcut(el, phase, scope))",
        save_cases,
    )
    assert save_result == [False, True, True]
    open_cases = [[body_el, 1, "open"], [body_el, 2, "open"], [body_el, 3, "open"]]
    open_result = js(
        utils,
        "cases => cases.map(([el, phase, scope]) => window.__u.acceptsShortcut(el, phase, scope))",
        open_cases,
    )
    assert open_result == [True, True, True]


def test_acceptsshortcut_works_without_focus_element(utils):
    assert js(utils, "window.__u.acceptsShortcut(null, 2, 'document')") is True
    assert js(utils, "window.__u.acceptsShortcut(undefined, 1, 'document')") is False
    assert js(utils, "window.__u.acceptsShortcut(null, 1, 'open')") is True


# ── extractPercentText ──

# `label-state.js` の `rebuildTextContent` が組む `tspan` 構成を旧テストの逐語のまま
# JS 側で再現する。2 行構成は名前行と % 行がそれぞれ `x` を持ち、1 行構成は % を同一
# チャンクへ流し込む。`longBody` (長体) は名前行の内側へ `x` なしの `tspan` を 1 枚挟む。
_REBUILT_HELPER = """
function rebuilt(name, percentText, two, longBody = false) {
  const rows = [{ hasX: true, text: longBody && two ? "" : name }];
  if (longBody && two) rows.push({ hasX: false, text: name });
  rows.push(two ? { hasX: true, text: percentText } : { hasX: false, text: ` ${percentText}` });
  return rows;
}
"""


def test_extractpercenttext_two_row_uses_displayed_percent_row_verbatim(utils):
    # 実サンプル (pdf_510037_06_gold_asset.svg): 表示は 100.8% / △0.8% で data-percent と乖離する。
    r1 = js(
        utils,
        "window.__u.extractPercentText("
        "[{hasX:true,text:'外国投資信託証券'},{hasX:true,text:'100.8%'}], '外国投資信託証券', '99.2')",
    )
    assert r1 == "100.8%"
    r2 = js(
        utils,
        "window.__u.extractPercentText([{hasX:true,text:'その他'},{hasX:true,text:'△0.8%'}], 'その他', '0.8')",
    )
    assert r2 == "△0.8%"


def test_extractpercenttext_one_row_drops_name_prefix_and_keeps_percent(utils):
    body = _REBUILT_HELPER + """
return [
  window.__u.extractPercentText([{hasX:true,text:'その他 4.0%'}], 'その他', '4.0'),
  window.__u.extractPercentText(rebuilt('その他', '4.0%', false), 'その他', '4.0'),
];
"""
    result = js(utils, _iife(body))
    assert result == ["4.0%", "4.0%"]


def test_extractpercenttext_stable_across_1_and_2_row_roundtrip(utils):
    body = _REBUILT_HELPER + """
const name = "外国投資信託証券";
const source = [{ hasX: true, text: name }, { hasX: true, text: "100.8%" }];
let pct = window.__u.extractPercentText(source, name, "99.2");
const steps = [[false, false], [true, false], [true, true], [false, false]];
const results = [];
for (const [two, longBody] of steps) {
  pct = window.__u.extractPercentText(rebuilt(name, pct, two, longBody), name, "99.2");
  results.push(pct);
}
return results;
"""
    result = js(utils, _iife(body))
    assert result == ["100.8%"] * 4


def test_extractpercenttext_no_percent_displayed_returns_empty(utils):
    # 引出線なし・円内のラベルは名前だけを出すことがある。ここで `50%` を生やすと、
    # 行数を変えただけで画面に無かった数値が現れる。
    result = js(utils, "window.__u.extractPercentText([{hasX:true,text:'Beta'}], 'Beta', '50')")
    assert result == ""


def test_extractpercenttext_falls_back_to_data_percent_only_when_unreadable(utils):
    # `data-name` と表示テキストが食い違う SVG (生成側以外の入力) 向けの退避経路。
    assert js(utils, "window.__u.extractPercentText([{hasX:true,text:'Gamma 12%'}], 'Delta', '12')") == "12%"
    assert js(utils, "window.__u.extractPercentText([], 'Delta', '12')") == "12%"
    assert js(utils, "window.__u.extractPercentText([], 'Delta', null)") == ""
    assert js(utils, "window.__u.extractPercentText([], 'Delta', '')") == ""
