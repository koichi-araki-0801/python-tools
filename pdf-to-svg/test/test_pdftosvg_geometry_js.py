# =============================================================================
# test_pdftosvg_geometry_js.py — resources/web/geometry.js の単体移植
# =============================================================================
# 旧 vitest ファイルからの移植テストと、geometry.js へ統合された矩形ヘルパの単体テスト。
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


def test_resizebycorner_moves_the_grabbed_corner(geo):
    """南東を掴んで動かすと、北西は固定されたまま幅と高さが変わる。"""
    assert js(geo, """window.__geo.resizeByCorner(
        {x: 10, y: 10, w: 20, h: 20}, "se", {x: 40, y: 50})""") == {
        "x": 10, "y": 10, "w": 30, "h": 40,
    }


def test_resizebycorner_moves_the_opposite_corner(geo):
    """北西を掴んで動かすと、南東が固定される。"""
    assert js(geo, """window.__geo.resizeByCorner(
        {x: 10, y: 10, w: 20, h: 20}, "nw", {x: 5, y: 5})""") == {
        "x": 5, "y": 5, "w": 25, "h": 25,
    }


def test_resizebycorner_handles_dragging_past_the_opposite_edge(geo):
    """反対の辺を越えて引いても矩形は正の寸法で返る (左右・上下が入れ替わる)。"""
    assert js(geo, """window.__geo.resizeByCorner(
        {x: 10, y: 10, w: 20, h: 20}, "se", {x: 0, y: 0})""") == {
        "x": 0, "y": 0, "w": 10, "h": 10,
    }


def test_resizebycorner_clamps_to_the_minimum_size(geo):
    """掴んだ角を反対の角へ寄せきっても `MIN_SIZE_PT` より小さくしない。"""
    assert js(geo, """window.__geo.resizeByCorner(
        {x: 10, y: 10, w: 20, h: 20}, "se", {x: 10, y: 10})""") == {
        "x": 10, "y": 10, "w": 4, "h": 4,
    }


def test_rectfromdrag_clamps_to_the_page(geo):
    """ページの外まで引いた矩形はページ内へ収まる。"""
    assert js(geo, """window.__geo.rectFromDrag(
        {x: 250, y: 150}, {x: 400, y: 300}, {w: 300, h: 200})""") == {
        "x": 250, "y": 150, "w": 50, "h": 50,
    }


def test_rectfromdrag_normalizes_the_direction(geo):
    """右下から左上へ引いても同じ矩形になる。"""
    a = js(geo, "window.__geo.rectFromDrag({x: 10, y: 10}, {x: 60, y: 40}, {w: 300, h: 200})")
    b = js(geo, "window.__geo.rectFromDrag({x: 60, y: 40}, {x: 10, y: 10}, {w: 300, h: 200})")
    assert a == b == {"x": 10, "y": 10, "w": 50, "h": 30}


def test_rectfromdrag_rejects_a_rect_below_the_minimum(geo):
    """`MIN_SIZE_PT` 未満は誤クリックとみなして `null` を返す。"""
    assert js(geo, "window.__geo.rectFromDrag({x: 10, y: 10}, {x: 12, y: 12}, {w: 300, h: 200})") is None


def test_rectfromdrag_rejects_a_rect_clamped_below_the_minimum(geo):
    """ページ外だけを引いた結果、収めると潰れる矩形も `null`。"""
    assert js(geo, "window.__geo.rectFromDrag({x: 310, y: 10}, {x: 400, y: 40}, {w: 300, h: 200})") is None


def test_corner_handles_html_has_four_corners(geo):
    assert js(geo, """(() => {
        const d = document.createElement("div");
        d.innerHTML = window.__geo.CORNER_HANDLES_HTML;
        return Array.from(d.querySelectorAll(".h")).map(e => ({
            corner: e.dataset.corner,
            classes: Array.from(e.classList).sort().join(" ")
        }));
    })()""") == [
        {"corner": "nw", "classes": "h nw"},
        {"corner": "ne", "classes": "h ne"},
        {"corner": "sw", "classes": "h sw"},
        {"corner": "se", "classes": "h se"},
    ]
