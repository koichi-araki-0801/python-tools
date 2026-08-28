# =============================================================================
# test_pdftosvg_js_smoke.py — JS 移植ハーネス自体の煙テスト
# =============================================================================
# 静的サーバから ES module を実ブラウザへ読み込んで evaluate できることを固定する。
# ここが緑でなければ後続の state/geometry 移植は全部成立しない。
import pytest

from .pdftosvg_js_harness import js

pytestmark = pytest.mark.browser


def test_module_import_and_evaluate(edge_page):
    mod = "import('/geometry.js').then(m => { window.__smoke = m; return typeof m.parseSpec; })"
    assert edge_page.evaluate(mod) == "function"
    assert js(edge_page, "window.__smoke.parseSpec('1-3', 10)") == [1, 2, 3]
