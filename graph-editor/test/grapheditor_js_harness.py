# =============================================================================
# grapheditor_js_harness.py — JS 移植テストの共通ヘルパ（設計書 §4.2）
# =============================================================================
# pdf-to-svg/test/pdftosvg_js_harness.py からのコピー流用（設計書 §6 の道具複製枠。
# 改善はコピー元と相互反映する）に、graph-editor 固有の classic script 読込
# （UMD の leader_geom.cjs）を加えたもの。


def js(page, expr, *args):
    """`page.evaluate` の薄いラッパ。式 1 個 = 断言 1 個の形で使う。"""
    return page.evaluate(expr, *args)


def load_classic(page, url):
    """classic `<script src>` を挿入する（UMD が global を生やす読込経路。ui.html と同じ）。"""
    page.add_script_tag(url=url)
