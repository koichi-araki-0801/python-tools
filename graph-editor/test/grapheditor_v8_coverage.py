"""CDP `Profiler.takePreciseCoverage` の byte-offset range 列 → 行/関数被覆率の変換器。

V8 precise coverage は 1 スクリプトにつき「関数(トップレベルの無名関数含む)ごとの
range 列」を返す。各 range は `startOffset`/`endOffset`(byte-offset。対象 2 ファイルは
BMP 文字のみで構成されるため Python の文字オフセットと一致する)/`count` を持つ。
本モジュールはこれを純 Python で行 % ・関数 % へ変換する（ブラウザ非依存）。

変換仕様(詳細設計書 / 実装計画 Task 4 準拠):

- 行分割は `\\n`。各行の [開始, 終了) offset を求める(改行文字自体は含めない)。
- 母数 = いずれかの関数 range と交差し、かつ空白のみ・コメント行でない行。
  コメント判定は素朴なスキャナ(`//` 行・`/* */` ブロックのみ)で、文字列リテラルは
  一切考慮しない。文字列リテラル内の `//` は誤検知しうるが、判定式が「行の非空白先頭が
  コメント内か」であるため行頭以外の `//` は無害。危険なのは文字列内の `/*`(複数行ぶん
  コメント扱いへ誤って倒れる) — 対象ファイルに存在しないことは呼び出し側(ゲート)の
  前提として別途機械確認する。
- 行カバー済み = その行と交差する range のうち**最内(区間が最小)の range** の
  `count > 0`。
- 関数カバレッジ = `functionName != ""` の関数のうち、トップ range(`ranges[0]`)の
  `count > 0` である割合。スクリプト全体を表す無名 range(`functionName == ""`)は
  母数から除外する。
- ~10 行未満の小さな未実行追加は検出できない粒度の割り切り(呼び出し側ゲートの閾値
  マージンが吸収する)。ゲートの主眼は denylist 化・大ブロック退行の検出で、細粒度の
  網は単体テストそのものが担う。
"""


def _line_spans(source):
    """各行の `(開始offset, 終了offset)` のリスト(`\\n` 自体は含めない)。"""
    spans = []
    start = 0
    for line in source.split("\n"):
        end = start + len(line)
        spans.append((start, end))
        start = end + 1
    return spans


def _comment_mask(source):
    """位置ごとに「`//` 行コメント or `/* */` ブロックコメントの内側」かを表す bool 列。

    文字列リテラルは考慮しない素朴なスキャナ(モジュール docstring の仕様どおり)。
    """
    n = len(source)
    mask = [False] * n
    i = 0
    while i < n:
        two = source[i : i + 2]
        if two == "//":
            j = i
            while j < n and source[j] != "\n":
                mask[j] = True
                j += 1
            i = j
        elif two == "/*":
            end = source.find("*/", i + 2)
            stop = n if end == -1 else end + 2
            for k in range(i, stop):
                mask[k] = True
            i = stop
        else:
            i += 1
    return mask


def _first_non_blank_offset(line_text):
    """行内で最初の非空白文字の offset(行頭からの相対位置)。空白のみなら `None`。"""
    for offset, ch in enumerate(line_text):
        if not ch.isspace():
            return offset
    return None


def _is_blank_or_comment_line(line_text, span, mask):
    """行が「空白のみ」または「非空白先頭がコメント内」なら `True`。"""
    offset = _first_non_blank_offset(line_text)
    if offset is None:
        return True
    pos = span[0] + offset
    return mask[pos]


def _ranges_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


def assert_bmp_only(source, name):
    """`source` が基本多言語面(BMP)の文字のみで構成されていることを assert する。

    非 BMP 文字(絵文字等)は UTF-16 では 2 code unit(サロゲートペア)を消費するが、
    Python の文字列は 1 文字を 1 offset として数える。V8 precise coverage の
    `startOffset`/`endOffset` は UTF-16 code-unit 単位なので、対象ソースに非 BMP 文字が
    混じると本モジュールの offset 計算(行 span・range 交差判定)が V8 側とずれる。
    このゲートは対象 2 ファイルが BMP のみであることを前提にしており、その前提が
    崩れていないことをここで機械的に固定する。
    """
    utf16_units = len(source.encode("utf-16-le")) // 2
    assert utf16_units == len(source), (
        f"{name}: 非 BMP 文字を検出した(UTF-16 code units={utf16_units} "
        f"!= 文字数={len(source)})。V8 coverage の byte-offset と本モジュールの文字 offset "
        "がずれるため、この前提が崩れた状態でゲートを走らせてはならない。"
    )


def assert_no_block_comment_in_literals(source, name):
    """文字列/テンプレート/正規表現リテラルの内側に `/*` が紛れていないことを assert する。

    `_comment_mask` は文字列リテラルを一切考慮しない素朴なスキャナで、リテラル内に
    `/*` があると次の `*/` までの実コード行を丸ごとコメント扱いへ誤って倒し、母数から
    落として検出できなくする(ゲートが緩む方向の壊れ方)。本関数はコメントスキャナと
    同水準の素朴さで文字列(`"..."`/`'...'`/`` `...` ``)と正規表現リテラルだけを
    読み飛ばし、その内側に `/*` が 0 件であることを確認する。正規表現リテラルの開始判定
    (除算演算子との区別)は「直前の非空白文字が識別子/`)`/`]`/`}` でなければ正規表現」
    という簡易ヒューリスティック(素朴なスキャナの割り切り)。
    """
    n = len(source)
    i = 0
    prev_significant = ""
    violations = []
    while i < n:
        two = source[i : i + 2]
        ch = source[i]
        if two == "//":
            j = i
            while j < n and source[j] != "\n":
                j += 1
            i = j
            continue
        if two == "/*":
            end = source.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if ch in ("'", '"', "`"):
            quote = ch
            start = i
            j = i + 1
            while j < n and source[j] != quote:
                if source[j] == "\\":
                    j += 2
                    continue
                j += 1
            end = min(j + 1, n)
            literal = source[start:end]
            if "/*" in literal:
                violations.append((start, literal[:20]))
            prev_significant = quote
            i = end
            continue
        if ch == "/" and _looks_like_regex_start(prev_significant):
            start = i
            j = i + 1
            in_class = False
            while j < n:
                c = source[j]
                if c == "\\":
                    j += 2
                    continue
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    j += 1
                    break
                elif c == "\n":
                    break
                j += 1
            end = j
            literal = source[start:end]
            if "/*" in literal:
                violations.append((start, literal[:20]))
            prev_significant = "/"
            i = end
            continue
        if not ch.isspace():
            prev_significant = ch
        i += 1
    assert not violations, (
        f"{name}: 文字列/正規表現リテラルの内側に `/*` を検出した(offset・先頭断片): "
        f"{violations}。この検出は _comment_mask がリテラルを考慮しないため、行カバレッジの"
        "母数が誤って狭まるのを防ぐための前提チェックである。"
    )


def _looks_like_regex_start(prev_significant):
    """直前の非空白文字から見て `/` が正規表現リテラルの開始らしいかの簡易判定。"""
    if prev_significant == "":
        return True
    if prev_significant.isalnum() or prev_significant in ")]}":
        return False
    return True


def line_and_function_coverage(script_source, functions):
    """V8 precise coverage の `functions` 配列(1 スクリプト分)を `(行 %, 関数 %)` へ変換する。

    `functions` は CDP `Profiler.takePreciseCoverage` の `result[i].functions` 形式
    (各要素が `functionName` / `ranges`(`startOffset`/`endOffset`/`count` の列))。
    母数が 0 件の軸は「全て満たす」扱いで `100.0` を返す(ゼロ除算にしない)。
    """
    spans = _line_spans(script_source)
    lines = script_source.split("\n")
    mask = _comment_mask(script_source)

    all_ranges = [
        (r["startOffset"], r["endOffset"], r["count"])
        for fn in functions
        for r in fn.get("ranges", [])
    ]

    total_lines = 0
    covered_lines = 0
    for line_text, span in zip(lines, spans):
        if _is_blank_or_comment_line(line_text, span, mask):
            continue
        overlapping = [r for r in all_ranges if _ranges_overlap(span[0], span[1], r[0], r[1])]
        if not overlapping:
            continue
        total_lines += 1
        innermost = min(overlapping, key=lambda r: r[1] - r[0])
        if innermost[2] > 0:
            covered_lines += 1
    line_pct = 100.0 if total_lines == 0 else covered_lines / total_lines * 100.0

    named = [fn for fn in functions if fn.get("functionName", "") != ""]
    covered_fns = sum(
        1 for fn in named if fn.get("ranges") and fn["ranges"][0]["count"] > 0
    )
    func_pct = 100.0 if not named else covered_fns / len(named) * 100.0

    return line_pct, func_pct
