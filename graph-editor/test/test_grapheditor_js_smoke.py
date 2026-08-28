# =============================================================================
# test_grapheditor_js_smoke.py — JS 移植ハーネス自体の煙テスト
# =============================================================================
# ES module（svg-policy.js）と UMD classic script（leader_geom.cjs → global LeaderGeom）の
# 両読込経路が成立することを固定する。後続の 75 件はこの 2 経路の上に建つ。
import pytest

from grapheditor_js_harness import js, load_classic

pytestmark = pytest.mark.browser


def test_module_and_classic_script_loading(edge_page, web_root_url):
    assert edge_page.evaluate(
        "import('/js/svg-policy.js').then(m => { window.__smoke = m; return typeof m.isAllowedElement; })"
    ) == "function"
    load_classic(edge_page, web_root_url + "/lib/leader_geom.cjs")
    assert js(edge_page, "typeof window.LeaderGeom.clampPointToBox") == "function"
    assert js(edge_page, "window.LeaderGeom.clampPointToBox({x:-5,y:2},{left:0,top:0,right:10,bottom:4})") == {"x": 0, "y": 2}
