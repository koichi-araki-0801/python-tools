# =============================================================================
# pdftosvg_js_harness.py — JS 移植テストの共通ヘルパ（設計書 §4.2）
# =============================================================================
# conftest.py に置かないのは、テストコードから `from test.conftest import ...` する形が
# stdlib `test` パッケージの shadow と pytest の import mode に依存する壊れやすい経路のため。
# フェーズ 3(graph-editor)はこのファイルと conftest の fixtures をコピーして流用する。


def js(page, expr, *args):
    """`page.evaluate` の薄いラッパ。式 1 個 = 断言 1 個の形で使う。"""
    return page.evaluate(expr, *args)
