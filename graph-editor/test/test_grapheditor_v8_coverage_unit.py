"""grapheditor_v8_coverage.line_and_function_coverage の変換器単体テスト。

実ブラウザを要しない純粋関数のテストなので `pytest.mark.browser` は付けない
（V8 precise coverage の `functions` 配列を手組みして与える）。
`assert_bmp_only` / `assert_no_block_comment_in_literals`（ゲートの前提を機械検証する
2 関数）の単体テストも本ファイルに同居させる。
"""
import pytest

from grapheditor_v8_coverage import (
    assert_bmp_only,
    assert_no_block_comment_in_literals,
    line_and_function_coverage,
)


def test_basic_covered_and_uncovered_line_and_function_ratio():
    source = "\n".join([
        "function covered() {",
        "  return 1;",
        "}",
        "",
        "function uncovered() {",
        "  return 2;",
        "}",
    ])
    covered_start = source.index("function covered")
    covered_end = source.index("function uncovered")
    uncovered_start = covered_end
    functions = [
        {"functionName": "", "ranges": [{"startOffset": 0, "endOffset": len(source), "count": 1}]},
        {"functionName": "covered", "ranges": [{"startOffset": covered_start, "endOffset": covered_end, "count": 5}]},
        {"functionName": "uncovered", "ranges": [{"startOffset": uncovered_start, "endOffset": len(source), "count": 0}]},
    ]
    line_pct, func_pct = line_and_function_coverage(source, functions)
    # 母数は空行を除く 6 行(covered 3 行 + uncovered 3 行)。covered 側 3 行のみ被覆。
    assert line_pct == 50.0
    # 無名(スクリプト全体)の range は母数から除外され、named 2 関数のうち covered の 1 件のみ被覆。
    assert func_pct == 50.0


def test_comment_and_blank_lines_excluded_from_denominator():
    source = "\n".join([
        "function covered() {",
        "  return 1;",
        "}",
        "",
        "// comment before uncovered",
        "/* block",
        "   comment */",
        "function uncovered() {",
        "  return 2;",
        "}",
    ])
    covered_start = source.index("function covered")
    comment_start = source.index("// comment before uncovered")
    uncovered_start = source.index("function uncovered")
    functions = [
        {"functionName": "", "ranges": [{"startOffset": 0, "endOffset": len(source), "count": 1}]},
        {"functionName": "covered", "ranges": [{"startOffset": covered_start, "endOffset": comment_start, "count": 5}]},
        {"functionName": "uncovered", "ranges": [{"startOffset": uncovered_start, "endOffset": len(source), "count": 0}]},
    ]
    line_pct, func_pct = line_and_function_coverage(source, functions)
    # `//` 行コメント・複数行 `/* */` ブロックコメント・空行の 4 行が母数から落ちていれば
    # 6 行(covered 3 + uncovered 3)中 3 行被覆 = 50.0%。誤って母数へ混入すると
    # コメント区間は無名 range(count=1)しか被らないため被覆扱いになり値がズレる。
    assert line_pct == 50.0
    assert func_pct == 50.0


def test_mid_line_slash_slash_in_string_is_not_mistaken_for_a_comment():
    source = "\n".join([
        'const SVG_NS = "http://www.w3.org/2000/svg";',
        "function use() {",
        "  return SVG_NS;",
        "}",
    ])
    use_start = source.index("function use")
    functions = [
        {"functionName": "", "ranges": [{"startOffset": 0, "endOffset": len(source), "count": 1}]},
        {"functionName": "use", "ranges": [{"startOffset": use_start, "endOffset": len(source), "count": 0}]},
    ]
    line_pct, func_pct = line_and_function_coverage(source, functions)
    # 1 行目は非空白先頭が `const` であり `//` は行頭ではないのでコメント扱いされず、
    # 無名 range(count=1)によって被覆済みとして母数(4 行)に数えられる。
    assert line_pct == 25.0
    assert func_pct == 0.0


def test_innermost_range_wins_for_line_coverage():
    source = "\n".join([
        "function branchy(x) {",
        "  if (x) {",
        "    return 1;",
        "  } else {",
        "    return 2;",
        "  }",
        "}",
    ])
    fn_start = source.index("function branchy")
    else_line_start = source.index("    return 2;")
    else_line_end = else_line_start + len("    return 2;")
    functions = [
        {"functionName": "", "ranges": [{"startOffset": 0, "endOffset": len(source), "count": 1}]},
        {
            "functionName": "branchy",
            "ranges": [
                {"startOffset": fn_start, "endOffset": len(source), "count": 1},
                {"startOffset": else_line_start, "endOffset": else_line_end, "count": 0},
            ],
        },
    ]
    line_pct, func_pct = line_and_function_coverage(source, functions)
    # 7 行中、else 分岐の 1 行だけが最内 range(count=0)で未被覆。外側の関数 range(count=1)
    # だけを見ると誤って全被覆になってしまうため、最内 range を優先する仕様の検証。
    assert line_pct == (6 / 7) * 100.0
    assert func_pct == 100.0


def test_no_named_functions_yields_full_function_coverage():
    source = "const x = 1;\nconst y = 2;\n"
    functions = [
        {"functionName": "", "ranges": [{"startOffset": 0, "endOffset": len(source), "count": 1}]},
    ]
    line_pct, func_pct = line_and_function_coverage(source, functions)
    assert line_pct == 100.0
    # 母数(named 関数)が 0 件のときは「全て満たす」扱いで 100.0(ゼロ除算にしない)。
    assert func_pct == 100.0


def test_line_not_intersecting_any_function_range_excluded_from_denominator():
    source = "\n".join([
        "function inRange() {",
        "  return 1;",
        "}",
        "",
        "const orphan = 1;",
    ])
    in_range_start = source.index("function inRange")
    in_range_end = source.index("const orphan")
    functions = [
        {
            "functionName": "inRange",
            "ranges": [{"startOffset": in_range_start, "endOffset": in_range_end, "count": 1}],
        },
    ]
    line_pct, func_pct = line_and_function_coverage(source, functions)
    # 最終行(`const orphan = 1;`)はどの関数 range とも交差しないため母数から除外される。
    # 母数は inRange の 3 行のみで全て被覆 -> 100%(orphan 行が母数に紛れ込むと 4 分の 3 = 75% になる)。
    assert line_pct == 100.0
    assert func_pct == 100.0


def test_assert_bmp_only_raises_on_non_bmp_character():
    # サロゲートペア(絵文字)は UTF-16 で 2 code unit を消費し、Python の文字 offset とずれる。
    source = 'const emoji = "\U0001f600";\n'
    with pytest.raises(AssertionError):
        assert_bmp_only(source, "dummy.js")


def test_assert_bmp_only_green_for_bmp_only_source():
    source = "const s = \"日本語も BMP 内なので OK\";\n"
    assert_bmp_only(source, "dummy.js")  # 例外を投げなければ green


def test_assert_no_block_comment_in_literals_detects_slash_star_in_string():
    source = 'const s = "prefix /* not a real comment */ suffix";\n'
    with pytest.raises(AssertionError):
        assert_no_block_comment_in_literals(source, "dummy.js")


def test_assert_no_block_comment_in_literals_detects_slash_star_in_regex():
    # `\/` はエスケープされたスラッシュ(正規表現リテラルを終端させない)で、直後の `*` と
    # 連続して literal 内に `/*` を作る。
    source = "const re = /prefix\\/*suffix/;\n"
    with pytest.raises(AssertionError):
        assert_no_block_comment_in_literals(source, "dummy.js")


def test_assert_no_block_comment_in_literals_green_for_slash_star_inside_line_comment():
    # `//` 行コメント内の `/*` は無害(スキャナが `//` を先に食い、リテラルとして再走査しない)。
    source = "// see `lib/*.cjs` for details\nconst x = 1;\n"
    assert_no_block_comment_in_literals(source, "dummy.js")  # 例外を投げなければ green
