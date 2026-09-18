# =============================================================================
# test_pdftosvg_page_jump_js.py — resources/web/page-jump.js の純粋関数の単体
# =============================================================================
# `resolveJump` はファイル一覧と通し先頭 index を引数で受ける (S を読まない) ので、
# 共有ページの状態を汚さずに境界だけを固定できる。
import pytest

from .pdftosvg_js_harness import js

pytestmark = pytest.mark.browser

FILES = [{"name": "a.pdf", "pages": 2}, {"name": "b.pdf", "pages": 3}]
START = [0, 2]


@pytest.fixture(scope="module")
def pj(edge_page):
    edge_page.evaluate("import('/page-jump.js').then(m => { window.__pj = m; })")
    return edge_page


def _resolve(page, fi, value):
    return js(page, "(a) => window.__pj.resolveJump(a.files, a.start, a.fi, a.value)",
              {"files": FILES, "start": START, "fi": fi, "value": value})


def test_resolvejump_maps_file_and_number_to_global_index(pj):
    assert _resolve(pj, 0, "1") == 0
    assert _resolve(pj, 0, "2") == 1
    assert _resolve(pj, 1, "1") == 2
    assert _resolve(pj, 1, "3") == 4


def test_resolvejump_clamps_out_of_range_and_treats_non_numbers_as_first_page(pj):
    assert _resolve(pj, 1, "99") == 4
    assert _resolve(pj, 1, "0") == 2
    assert _resolve(pj, 1, "-3") == 2
    assert _resolve(pj, 1, "abc") == 2
    assert _resolve(pj, 1, "") == 2
    assert _resolve(pj, 0, "1.7") == 0   # 小数は切り捨て


def test_resolvejump_returns_minus_one_for_an_unknown_file(pj):
    assert _resolve(pj, 5, "1") == -1
