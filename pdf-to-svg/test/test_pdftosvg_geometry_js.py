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
