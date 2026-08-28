# =============================================================================
# test_grapheditor_pie_rules_js.py — resources/web/js/pie-rules.js の単体移植
# =============================================================================
# 旧 editor_pie_rules.test.ts (vitest) の describe 6 本・it 14 件と 1:1。
# 期待値・入力は旧テストから逐語で写す。
import pytest

from grapheditor_js_harness import js

pytestmark = pytest.mark.browser

EPS = 1e-6


@pytest.fixture(scope="module")
def rules(edge_page, web_root_url):
    edge_page.evaluate("import('/js/pie-rules.js').then(m => { window.__rules = m; })")
    return edge_page


# ── parsePieGeometry ──


def test_parsepiegeometry_wedge_path_extracts_center_and_radius(rules):
    assert js(rules, "window.__rules.parsePieGeometry('M300,225 L300,90 A135,135 0 0 1 435,225 Z')") == {
        "cx": 300,
        "cy": 225,
        "r": 135,
    }


def test_parsepiegeometry_allows_whitespace_and_negative_coords(rules):
    assert js(rules, "window.__rules.parsePieGeometry('M -10.5 20 L0,0 A 7.25,7.25 0 0 1 3,4')") == {
        "cx": -10.5,
        "cy": 20,
        "r": 7.25,
    }


def test_parsepiegeometry_no_arc_is_null(rules):
    assert js(rules, "window.__rules.parsePieGeometry('M0,0 L10,10 Z')") is None
    assert js(rules, "window.__rules.parsePieGeometry('')") is None


def test_parsepiegeometry_full_circle_without_l_is_null(rules):
    # 全円は `M` が中心ではなく天頂のリム点なので、そのまま中心として読むと円が半径 1 つ
    # 分ずれる。`sliceMidAnchor` の楔形ガードと同じ判定で退避し、既定円へ倒す。
    d = "M300,67.49999999999994 A157.5,157.5 0 1 1 300,382.5 A157.5,157.5 0 1 1 300,67.49999999999994 Z"
    assert js(rules, f"window.__rules.parsePieGeometry('{d}')") is None


def test_parsepiegeometry_l_only_after_a_is_null(rules):
    assert js(rules, "window.__rules.parsePieGeometry('M300,67.5 A157.5,157.5 0 1 1 300,382.5 L300,225 Z')") is None


# ── fallbackPieGeometry ──


def test_fallbackpiegeometry_canvas_center_short_side_times_ratio(rules):
    assert js(rules, "window.__rules.fallbackPieGeometry(600, 450, 0.35)") == {"cx": 300, "cy": 225, "r": 450 * 0.35}


# ── labelBox / labelCenter ──
# bbox = { x: 10, y: 20, width: 100, height: 30 }


def test_labelbox_reflects_texttx_into_frame(rules):
    assert js(rules, "window.__rules.labelBox({x:10,y:20,width:100,height:30},{x:5,y:-5})") == {
        "left": 15,
        "top": 15,
        "right": 115,
        "bottom": 45,
    }


def test_labelcenter_is_bbox_center_plus_texttx(rules):
    assert js(rules, "window.__rules.labelCenter({x:10,y:20,width:100,height:30},{x:5,y:-5})") == {"x": 65, "y": 30}


# ── isOutsidePie ──
# pie = { cx: 0, cy: 0, r: 100 }


def test_isoutsidepie_inside_false_outside_true_boundary_is_inside(rules):
    pie = "{cx:0,cy:0,r:100}"
    assert js(rules, f"window.__rules.isOutsidePie({{x:50,y:50}},{pie})") is False
    assert js(rules, f"window.__rules.isOutsidePie({{x:100,y:0}},{pie})") is False
    assert js(rules, f"window.__rules.isOutsidePie({{x:101,y:0}},{pie})") is True


# ── computeDefaultLeaderPts ──
# pie = { cx: 0, cy: 0, r: 100 }


def test_computedefaultleaderpts_endpoint_is_closest_point_on_label_frame(rules):
    result = js(
        rules,
        f"window.__rules.computeDefaultLeaderPts({{cx:0,cy:0,r:100}},{{left:150,top:-20,right:250,bottom:20}},{{x:100,y:0}},{EPS})",
    )
    a, ep = result
    assert a == {"x": 100, "y": 0}  # アンカーは渡された中心角リム点をそのまま使う
    assert ep == {"x": 150, "y": 0}  # 左辺の中央 (中心へ最近)


def test_computedefaultleaderpts_null_anchor_falls_back_to_center_to_endpoint_direction(rules):
    result = js(
        rules,
        f"window.__rules.computeDefaultLeaderPts({{cx:0,cy:0,r:100}},{{left:150,top:-20,right:250,bottom:20}},null,{EPS})",
    )
    a, ep = result
    assert ep == {"x": 150, "y": 0}
    assert a["x"] == pytest.approx(100, abs=1e-6)  # 方向 (1,0) の r=100 リム点
    assert a["y"] == pytest.approx(0, abs=1e-6)


def test_computedefaultleaderpts_zero_vector_escape_defaults_to_rightward(rules):
    # 中心を含む箱 → 端点 = 中心 (零ベクトル防御)
    result = js(
        rules,
        f"window.__rules.computeDefaultLeaderPts({{cx:0,cy:0,r:100}},{{left:-10,top:-10,right:10,bottom:10}},null,{EPS})",
    )
    a, ep = result
    assert ep == {"x": 0, "y": 0}
    assert a == {"x": 100, "y": 0}


# ── parsePieGeometry は入力長に対して線形 (計算量の上限・ReDoS) ──
# `d` は `sanitizeAttrValue` が 1 MiB まで意図的に通すため、数値パターンが曖昧だと
# 長い数字列 1 本で最初のラベル操作が固まる(読込は「除去 0 件」で正常に終わるので、
# 利用者には何が起きたか分からない)。


def test_parsepiegeometry_valid_d_still_parses_as_before(rules):
    assert js(rules, "window.__rules.parsePieGeometry('M 10,20 L0,0 A 5,5 0 0 1 1,2')") == {"cx": 10, "cy": 20, "r": 5}
    assert js(rules, "window.__rules.parsePieGeometry('M-1.5,.5L0,0A2,2 0 0 1 1,2')") == {"cx": -1.5, "cy": 0.5, "r": 2}


def test_parsepiegeometry_long_digit_run_does_not_grow_quadratically(rules):
    expr = """(() => {
      const measure = (n) => {
        const d = `M${"1".repeat(n)} L0,0 A2,2 0 0 1 1,2`;
        const t0 = performance.now();
        window.__rules.parsePieGeometry(d);
        return performance.now() - t0;
      };
      measure(50000);
      const small = measure(50000);
      const large = measure(800000);
      return { small, large };
    })()"""
    result = js(rules, expr)
    # 二次だと 16 倍の入力で 256 倍。線形なら 16 倍程度に収まる。
    assert result["large"] < max(50, result["small"] * 100)
    assert result["large"] < 1000
