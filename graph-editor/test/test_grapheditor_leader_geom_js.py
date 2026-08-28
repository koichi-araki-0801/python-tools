# =============================================================================
# test_grapheditor_leader_geom_js.py — resources/web/lib/leader_geom.cjs の単体移植
# =============================================================================
# 旧 editor_leader_geom.test.ts (vitest) の describe 4 本・it 21 件と 1:1。
# 期待値・入力は旧テストから逐語で写す。
import pytest

from grapheditor_js_harness import js, load_classic

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def geom(edge_page, web_root_url):
    if not edge_page.evaluate("typeof window.LeaderGeom !== 'undefined'"):
        load_classic(edge_page, web_root_url + "/lib/leader_geom.cjs")
    return edge_page


# ── clampPointToBox ──
# box = { left: 0, top: 0, right: 10, bottom: 4 }


def test_clamp_left_outside_point_goes_to_left_edge(geom):
    assert js(geom, "window.LeaderGeom.clampPointToBox({x:-5,y:2},{left:0,top:0,right:10,bottom:4})") == {"x": 0, "y": 2}


def test_clamp_right_outside_point_goes_to_right_edge(geom):
    assert js(geom, "window.LeaderGeom.clampPointToBox({x:99,y:1},{left:0,top:0,right:10,bottom:4})") == {"x": 10, "y": 1}


def test_clamp_top_outside_point_goes_to_top_edge(geom):
    # SVG: 上が小さい y
    assert js(geom, "window.LeaderGeom.clampPointToBox({x:5,y:-3},{left:0,top:0,right:10,bottom:4})") == {"x": 5, "y": 0}


def test_clamp_bottom_outside_point_goes_to_bottom_edge(geom):
    assert js(geom, "window.LeaderGeom.clampPointToBox({x:5,y:50},{left:0,top:0,right:10,bottom:4})") == {"x": 5, "y": 4}


def test_clamp_diagonal_outside_point_clamps_to_corner(geom):
    assert js(geom, "window.LeaderGeom.clampPointToBox({x:-1,y:-1},{left:0,top:0,right:10,bottom:4})") == {"x": 0, "y": 0}
    assert js(geom, "window.LeaderGeom.clampPointToBox({x:100,y:100},{left:0,top:0,right:10,bottom:4})") == {"x": 10, "y": 4}


def test_clamp_point_inside_box_stays_as_is(geom):
    assert js(geom, "window.LeaderGeom.clampPointToBox({x:3,y:2},{left:0,top:0,right:10,bottom:4})") == {"x": 3, "y": 2}


# ── parsePath / buildPath ──


def test_parsepath_reads_m_l_into_points(geom):
    assert js(geom, "window.LeaderGeom.parsePath('M1,2 L3,4 L5,6')") == [
        {"x": 1, "y": 2},
        {"x": 3, "y": 4},
        {"x": 5, "y": 6},
    ]


def test_buildpath_writes_points_into_m_l(geom):
    assert js(geom, "window.LeaderGeom.buildPath([{x:1,y:2},{x:3,y:4}])") == "M1,2 L3,4"


def test_parsepath_buildpath_roundtrip(geom):
    d = "M10,20 L-3.5,4 L0,0"
    assert js(geom, f"window.LeaderGeom.buildPath(window.LeaderGeom.parsePath('{d}'))") == d


def test_parsepath_reads_negative_decimal_exponent(geom):
    assert js(geom, "window.LeaderGeom.parsePath('M-1.5,2e1')") == [{"x": -1.5, "y": 20}]


def test_parsepath_empty_or_no_numbers_is_empty_array(geom):
    assert js(geom, "window.LeaderGeom.parsePath('')") == []
    assert js(geom, "window.LeaderGeom.parsePath('Z')") == []


def test_parsepath_odd_count_coordinates_drops_remainder(geom):
    assert js(geom, "window.LeaderGeom.parsePath('M1,2 L3')") == [{"x": 1, "y": 2}]


# ── parseTranslate ──


def test_parsetranslate_reads_translate_dx_dy(geom):
    assert js(geom, "window.LeaderGeom.parseTranslate('translate(3,4)')") == {"x": 3, "y": 4}


def test_parsetranslate_allows_whitespace_negative_decimal(geom):
    assert js(geom, "window.LeaderGeom.parseTranslate('translate( -2.5 , 6 )')") == {"x": -2.5, "y": 6}


def test_parsetranslate_empty_or_invalid_is_origin(geom):
    assert js(geom, "window.LeaderGeom.parseTranslate('')") == {"x": 0, "y": 0}
    assert js(geom, "window.LeaderGeom.parseTranslate(null)") == {"x": 0, "y": 0}
    assert js(geom, "window.LeaderGeom.parseTranslate('rotate(10)')") == {"x": 0, "y": 0}


def test_parsetranslate_reads_leading_dot_numbers(geom):
    # 数値集合の不変: 先頭ドット数値も従来どおり読む
    assert js(geom, "window.LeaderGeom.parseTranslate('translate(.5,-.25)')") == {"x": 0.5, "y": -0.25}


def test_parsetranslate_redos_guard_returns_immediately(geom):
    # `\d*\.?\d+` の二段量化子は、区切りはあるが閉じ括弧に至れない 2 つの長い数字列で
    # 二次バックトラックした。重なりのない形なら入力長に比例して即返る。
    expr = """(() => {
      const run = "9".repeat(50000);
      const evil = `translate(${run} ${run}x`;
      const t0 = Date.now();
      const r = window.LeaderGeom.parseTranslate(evil);
      return { r, elapsed: Date.now() - t0 };
    })()"""
    result = js(geom, expr)
    assert result["r"] == {"x": 0, "y": 0}
    assert result["elapsed"] < 2000


# ── normColor ──


def test_normcolor_white_and_hex_shorthand(geom):
    assert js(geom, "window.LeaderGeom.normColor('white')") == "#ffffff"
    assert js(geom, "window.LeaderGeom.normColor('#FFF')") == "#ffffff"


def test_normcolor_black_and_hex_shorthand(geom):
    assert js(geom, "window.LeaderGeom.normColor('black')") == "#000000"
    assert js(geom, "window.LeaderGeom.normColor('#000')") == "#000000"


def test_normcolor_trims_whitespace_and_lowercases(geom):
    assert js(geom, "window.LeaderGeom.normColor('  #AB12Cd  ')") == "#ab12cd"


def test_normcolor_null_stays_null(geom):
    assert js(geom, "window.LeaderGeom.normColor(null)") is None
