# =============================================================================
# test_pdftosvg_geometry_js.py — resources/web/geometry.js の単体移植
# =============================================================================
# 旧 geometry.test.js (vitest) の it 7 件と 1:1。期待値は旧テストから逐語で写す。
import pytest

from .pdftosvg_js_harness import js

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def geo(edge_page):
    edge_page.evaluate("import('/geometry.js').then(m => { window.__geo = m; })")
    return edge_page


def test_parsespec_expands_ranges_and_singles(geo):
    assert js(geo, "window.__geo.parseSpec('1-5, 8', 100)") == [1, 2, 3, 4, 5, 8]


def test_parsespec_normalizes_reversed_range(geo):
    assert js(geo, "window.__geo.parseSpec('5-3', 100)") == [3, 4, 5]


def test_parsespec_dedupes(geo):
    assert js(geo, "window.__geo.parseSpec('1, 1, 2-3, 3', 100)") == [1, 2, 3]


def test_parsespec_clamps_to_1_maxpages(geo):
    assert js(geo, "window.__geo.parseSpec('0-3', 2)") == [1, 2]
    assert js(geo, "window.__geo.parseSpec('8-12', 10)") == [8, 9, 10]


def test_parsespec_ignores_empty_and_invalid_tokens(geo):
    assert js(geo, "window.__geo.parseSpec('', 10)") == []
    assert js(geo, "window.__geo.parseSpec(' , abc, 2', 10)") == [2]
    assert js(geo, "window.__geo.parseSpec(null, 10)") == []


# `viewBox` と要素矩形をスタブした最小の `svgEl` でアフィン変換だけを検証する。
# メソッド持ちオブジェクトは evaluate の引数として serialize できないため、
# JS 式内で構築して評価する。
_SVG_EL_EXPR = """
(() => ({
  getBoundingClientRect: () => ({ left: 100, top: 50, width: 200, height: 400 }),
  viewBox: { baseVal: { x: 0, y: 0, width: 400, height: 800 } },
}))()
"""


def test_clienttopage_top_left_maps_to_viewbox_origin(geo):
    expr = f"window.__geo.clientToPage({_SVG_EL_EXPR}, 100, 50)"
    assert js(geo, expr) == {"x": 0, "y": 0}


def test_clienttopage_center_maps_to_viewbox_center_scale_2x(geo):
    expr = f"window.__geo.clientToPage({_SVG_EL_EXPR}, 200, 250)"
    assert js(geo, expr) == {"x": 200, "y": 400}


def test_rectiou_identical_rects_is_1(geo):
    r = "{x:0,y:0,w:100,h:100}"
    assert js(geo, f"window.__geo.rectIoU({r}, {r})") == 1


def test_rectiou_disjoint_rects_is_0(geo):
    a = "{x:0,y:0,w:10,h:10}"
    b = "{x:100,y:100,w:10,h:10}"
    assert js(geo, f"window.__geo.rectIoU({a}, {b})") == 0


def test_rectiou_partial_overlap(geo):
    a = "{x:0,y:0,w:100,h:100}"
    b = "{x:10,y:0,w:100,h:100}"
    got = js(geo, f"window.__geo.rectIoU({a}, {b})")
    assert got == pytest.approx((90 * 100) / (100 * 100 * 2 - 90 * 100))


def test_rectiou_zero_area_rect_is_0(geo):
    a = "{x:0,y:0,w:0,h:0}"
    b = "{x:0,y:0,w:10,h:10}"
    assert js(geo, f"window.__geo.rectIoU({a}, {b})") == 0


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
