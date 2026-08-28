# =============================================================================
# test_grapheditor_svg_policy_js.py — resources/web/js/svg-policy.js の単体移植
# =============================================================================
# 旧 editor_svg_policy.test.ts (vitest) の describe 6 本・it 25 件と 1:1。
# 期待値・入力(悪性ペイロード含む)は旧テストから逐語で写す。
#
# `ALLOWED_ELEMENTS` 等の Set はシリアライズ不能なので、membership は
# `.has(...)` を JS 側で評価して bool を受け取る形にする(冪等断言・タイミング計測も
# 同様に JS 側で完結させ、Python の壁時計や再構築した比較値で代用しない)。
from pathlib import Path

import pytest

from grapheditor_js_harness import js

pytestmark = pytest.mark.browser

XHTML_NS = "http://www.w3.org/1999/xhtml"
XLINK_NS = "http://www.w3.org/1999/xlink"
XML_NS = "http://www.w3.org/XML/1998/namespace"


@pytest.fixture(scope="module")
def policy(edge_page, web_root_url):
    edge_page.evaluate("import('/js/svg-policy.js').then(m => { window.__pol = m; })")
    return edge_page


# ── isAllowedElement ──


def test_isallowedelement_active_content_capable_elements_never_allowed_even_in_svg_ns(policy):
    names = [
        "script", "foreignObject", "animate", "set", "animateTransform", "animateMotion",
        "discard", "a", "image", "use", "feImage", "handler", "iframe", "audio", "video",
        "switch", "filter", "pattern", "marker", "mask", "clipPath", "linearGradient",
    ]
    result = js(policy, "names => names.map(n => window.__pol.isAllowedElement(n, window.__pol.SVG_NS))", names)
    assert result == [False] * len(names)


def test_isallowedelement_allowed_spelling_wrong_namespace_not_allowed(policy):
    cases = [
        ["iframe", XHTML_NS],
        ["g", XHTML_NS],
        ["g", "urn:x-evil"],
        ["g", None],
        ["svg", XHTML_NS],
    ]
    result = js(policy, "cases => cases.map(([n, ns]) => window.__pol.isAllowedElement(n, ns))", cases)
    assert result == [False] * len(cases)


def test_isallowedelement_does_not_fold_case(policy):
    names = ["G", "SVG", "Path"]
    result = js(policy, "names => names.map(n => window.__pol.isAllowedElement(n, window.__pol.SVG_NS))", names)
    assert result == [False] * len(names)


def test_isallowedelement_pie_chart_output_8_elements_allowed(policy):
    names = ["svg", "defs", "style", "g", "path", "text", "tspan", "rect"]
    result = js(
        policy,
        "names => names.map(n => "
        "[window.__pol.isAllowedElement(n, window.__pol.SVG_NS), window.__pol.ALLOWED_ELEMENTS.has(n)])",
        names,
    )
    assert result == [[True, True] for _ in names]


# ── isAllowedAttr ──


def test_isallowedattr_namespaced_attrs_dropped_by_uri_only_no_prefix_compare(policy):
    cases = [
        ["href", XLINK_NS, "path"],
        ["href", "urn:x-evil", "path"],
        ["space", XML_NS, "text"],
        ["xlink:href", None, "path"],
    ]
    result = js(policy, "cases => cases.map(([n, ns, el]) => window.__pol.isAllowedAttr(n, ns, el))", cases)
    assert result == [False] * len(cases)


def test_isallowedattr_url_and_event_attrs_not_in_allowed_set(policy):
    names = ["href", "src", "xlink:href", "onload", "onLoad", "ONLOAD", "onclick", "style"]
    result = js(policy, "names => names.map(n => window.__pol.isAllowedAttr(n, null, 'path'))", names)
    assert result == [False] * len(names)


def test_isallowedattr_exact_spelling_match(policy):
    cases = [
        ["viewBox", None, "svg"],
        ["viewbox", None, "svg"],
        ["textLength", None, "tspan"],
        ["textlength", None, "tspan"],
    ]
    result = js(policy, "cases => cases.map(([n, ns, el]) => window.__pol.isAllowedAttr(n, ns, el))", cases)
    assert result == [True, False, True, False]


def test_isallowedattr_data_star_allowed_except_editor_reserved_names(policy):
    cases = [
        ["data-name", None, "g"],
        ["data-inside-slice", None, "g"],
        ["data-editor", None, "g"],
        ["data-editor-hit", None, "rect"],
    ]
    result = js(policy, "cases => cases.map(([n, ns, el]) => window.__pol.isAllowedAttr(n, ns, el))", cases)
    assert result == [True, True, False, False]


def test_isallowedattr_type_only_on_style(policy):
    assert js(policy, "window.__pol.isAllowedAttr('type', null, 'style')") is True
    assert js(policy, "window.__pol.isAllowedAttr('type', null, 'path')") is False


# ── sanitizeAttrValue ──


def test_sanitizeattrvalue_paint_rejects_schemed_values_and_url_refs(policy):
    cases = [
        ["path", "fill", "javascript:alert(1)"],
        ["path", "fill", "java\tscript:alert(1)"],
        ["path", "fill", "url(https://example.invalid/x)"],
        ["path", "fill", "url(#grad)"],
        ["path", "stroke", 'red" onload="alert(1)'],
    ]
    result = js(policy, "cases => cases.map(([el, attr, v]) => window.__pol.sanitizeAttrValue(el, attr, v))", cases)
    assert result == [None] * len(cases)


def test_sanitizeattrvalue_pie_chart_output_paint_values_accepted(policy):
    values = ["#d1d2d4", "#ffffff", "#111111", "none", "currentColor"]
    result = js(policy, "vs => vs.map(v => window.__pol.sanitizeAttrValue('path', 'fill', v))", values)
    assert result == values


def test_sanitizeattrvalue_style_type_only_text_css(policy):
    assert js(policy, "window.__pol.sanitizeAttrValue('style', 'type', 'text/css')") == "text/css"
    assert js(policy, "v => window.__pol.sanitizeAttrValue('style', 'type', v)", " TEXT/CSS ") == "text/css"
    assert js(policy, "window.__pol.sanitizeAttrValue('style', 'type', 'text/javascript')") is None


def test_sanitizeattrvalue_control_chars_and_too_long_values_dropped(policy):
    assert js(policy, "v => window.__pol.sanitizeAttrValue('text', 'font-family', v)", "sans\x00serif") is None
    assert js(policy, "v => window.__pol.sanitizeAttrValue('text', 'font-family', v)", "x" * 5000) is None
    # 座標列 (`d` / `points`) だけは長さの別枠を持つ。
    d_value = "M0,0 " + ("L1,1 " * 2000)
    assert js(policy, "v => window.__pol.sanitizeAttrValue('path', 'd', v)", d_value) is not None


def test_sanitizeattrvalue_other_attrs_pass_through(policy):
    # URL 属性が 1 つも残らないため、それ以外の属性値は素通しする。
    assert (
        js(policy, "v => window.__pol.sanitizeAttrValue('text', 'font-family', v)", '"BIZ UDPGothic", sans-serif')
        == '"BIZ UDPGothic", sans-serif'
    )
    assert js(policy, "v => window.__pol.sanitizeAttrValue('g', 'data-name', v)", "A & B") == "A & B"
    assert js(policy, "window.__pol.sanitizeAttrValue('g', 'data-name', 42)") is None


# ── safeCssColor ──


def test_safecsscolor_drops_declaration_splice_markup_escape_and_function_calls(policy):
    values = [
        "red;background-image:url(https://example.invalid/x)",
        '#fff"><img src=x onerror="alert(1)">',
        "expression(alert(1))",
        "url(#x)",
        "rgb(0,0,0);x:y",
        "var(--sunk, url(https://example.invalid/x))",
        "#ff\x00f",
        "a" * 200,
        "",
    ]
    result = js(policy, "vs => vs.map(v => window.__pol.safeCssColor(v))", values)
    assert result == [None] * len(values)
    assert js(policy, "window.__pol.safeCssColor(null)") is None


def test_safecsscolor_accepts_only_valid_color_syntax(policy):
    values = [
        "#4e79a7", "#fff", "#ffff", "#4e79a7cc", "rgb(1,2,3)", "rgba(1, 2, 3, 0.5)",
        "hsl(120deg 50% 50%)", "var(--sunk)", "currentColor", "rebeccapurple", " #fff ",
    ]
    result = js(policy, "vs => vs.map(v => window.__pol.safeCssColor(v))", values)
    assert all(v is not None for v in result)
    assert js(policy, "v => window.__pol.safeCssColor(v)", " #fff ") == "#fff"


# ── sanitizeFontFaceCss ──


def test_sanitizefontfacecss_rejects_all_css_that_sets_up_external_fetch(policy):
    inputs = [
        "@import url(https://example.invalid/x.css);",
        "@font-face{src:url(https://example.invalid/f.woff2)}",
        "@font-face{src:url(data:text/html;base64,AAAA)}",
        "@font-face{src:url('/local.woff2')}",
    ]
    result = js(policy, "vs => vs.map(v => window.__pol.sanitizeFontFaceCss(v))", inputs)
    assert result == [""] * len(inputs)


def test_sanitizefontfacecss_full_consume_match_catches_what_denylist_would_miss(policy):
    inputs = [
        # CSS エスケープでの綴り替え。バックスラッシュを含む入力は入口で捨てる。
        "@\\69mport url(https://example.invalid/x.css);",
        # 大小混在・前後の空白でも `@font-face` 以外は受理しない。
        "  @IMPORT url(https://example.invalid/x.css);  ",
        # アプリ UI のセレクタを乗っ取る CSS (インライン SVG の CSS は文書全体に効く)。
        ".btn{display:none}",
        "@font-face{font-weight:400}.btn{display:none}",
    ]
    result = js(policy, "vs => vs.map(v => window.__pol.sanitizeFontFaceCss(v))", inputs)
    assert result == [""] * len(inputs)


def test_sanitizefontfacecss_discards_whole_input_if_even_one_byte_remains(policy):
    ok = '@font-face{src:url(data:font/woff2;base64,AAAA) format("woff2");}'
    assert js(policy, "v => window.__pol.sanitizeFontFaceCss(v)", ok) != ""
    assert js(policy, "v => window.__pol.sanitizeFontFaceCss(v)", f"{ok}]]><script>x</script>") == ""
    assert js(policy, "v => window.__pol.sanitizeFontFaceCss(v)", f"{ok}x") == ""
    assert js(policy, "v => window.__pol.sanitizeFontFaceCss(v)", "@font-face{src:url(data:font/woff2;base64,AAAA)") == ""


def test_sanitizefontfacecss_constrains_base64_charset_blocks_early_close_via_paren(policy):
    inputs = [
        "@font-face{src:url(data:font/woff2;base64,AA)AA)}",
        "@font-face{src:url(data:font/woff2;base64,AA<AA)}",
    ]
    result = js(policy, "vs => vs.map(v => window.__pol.sanitizeFontFaceCss(v))", inputs)
    assert result == [""] * len(inputs)


def test_sanitizefontfacecss_discards_whole_block_if_any_declaration_unrecognized(policy):
    inputs = [
        "@font-face{font-weight:400;behavior:url(x.htc)}",
        "@font-face{font-weight:heavy}",
        "@font-face{@media{}}",
    ]
    result = js(policy, "vs => vs.map(v => window.__pol.sanitizeFontFaceCss(v))", inputs)
    assert result == [""] * len(inputs)


def test_sanitizefontfacecss_declaration_names_from_prototype_words_rejected_not_thrown(policy):
    # 宣言名は攻撃者が綴れる文字列で、そのまま許可表のキーになる。素のオブジェクト表だと
    # `constructor` / `__proto__` が継承値を返し「未知プロパティ = 拒否」ではなく
    # `re.test` の TypeError になっていた。ここでは**投げないこと**まで主張する
    # (page.evaluate 中に JS が例外を投げれば、この呼び出し自体が Python 側の例外になる)。
    props = [
        "constructor", "__proto__", "toString", "hasOwnProperty", "valueOf",
        "isPrototypeOf", "propertyIsEnumerable", "toLocaleString",
    ]
    for prop in props:
        solo = f"@font-face{{{prop}:a}}"
        mixed = f"@font-face{{src:url(data:font/woff2;base64,AAAA);{prop}:a}}"
        result = js(policy, "vs => vs.map(v => window.__pol.sanitizeFontFaceCss(v))", [solo, mixed])
        assert result == ["", ""], prop


def test_sanitizefontfacecss_pie_chart_output_accepted_byte_for_byte_and_idempotent(policy):
    # 出典: `pie-chart/out/svg_js/asset_4slice_simple.svg` の `<style>` 内容
    # (base64 のみ先頭 64 文字へ短縮)。`out/` は git 未追跡なのでフィクスチャに固定する。
    css_path = Path(__file__).parent / "fixtures" / "pie_font_face.css"
    css = css_path.read_text(encoding="utf-8")
    # 冪等断言は JS 側の `===` で行う(Python 側で再構築した文字列同士の比較で代用しない)。
    assert js(policy, "css => window.__pol.sanitizeFontFaceCss(css) === css", css) is True
    out = js(policy, "css => window.__pol.sanitizeFontFaceCss(css)", css)
    assert js(policy, "out => window.__pol.sanitizeFontFaceCss(out) === out", out) is True
    assert "data:font/woff2;base64," in out
    assert "@import" not in out


# ── 計算量の上限(ReDoS) ──
# 資源上限は「入力の大きさ」と「処理の計算量」の 2 軸で持つ必要がある。入力長
# (`MAX_SVG_INPUT_CHARS` 8MiB)・ノード数・ラベル数の上限はどれも大きさの上限で、
# 100 バイト未満の入力で刺さる指数バックトラックは止められない。しかもサニタイザが
# メインスレッドで固まると、規定の失敗の仕方(読込ごと拒否 + 件数通知)にすらならず、
# `/ping` 途絶で 60 秒後にサーバが自ら終了する = 守るためのコードが守る対象を殺す。


def test_sanitizefontfacecss_valid_font_family_still_passes(policy):
    src = 'src:url(data:font/woff2;base64,AAAA) format("woff2")'
    oks = [
        "Arial",
        "sans-serif",
        '"BIZ UDPGothic"',
        "'Noto Serif JP'",
        "Times New Roman",
        'Arial, "BIZ UDPGothic", sans-serif',
        "Helvetica Neue, Arial, sans-serif",
    ]
    inputs = [f"@font-face{{font-family:{ok};{src}}}" for ok in oks]
    result = js(policy, "vs => vs.map(v => window.__pol.sanitizeFontFaceCss(v))", inputs)
    assert all(v != "" for v in result), list(zip(oks, result))


def test_sanitizefontfacecss_16x_delimiters_time_does_not_spike(policy):
    # 実行時間を測るため、`performance.now()` を JS 内(ブラウザ内)で計測する
    # (Python 側の壁時計で代用しない)。区切りごとに解析の分岐が増える非マッチ確定の
    # 最悪形 `evil(n)` を使う。指数バックトラックだと 28 → 448 で天文学的に伸びる
    # (修正前は 85 バイトで 6.5 秒)。
    expr = """(() => {
      const SRC = 'src:url(data:font/woff2;base64,AAAA) format("woff2")';
      const evil = (n) => `${Array(n).fill("a ").join(",")},!`;
      const measure = (n) => {
        const css = `@font-face{font-family:${evil(n)};${SRC}}`;
        const t0 = performance.now();
        window.__pol.sanitizeFontFaceCss(css);
        return performance.now() - t0;
      };
      measure(28); // ウォームアップ(JIT の初回コストを測らない)
      const small = measure(28);
      const large = measure(448);
      return { small, large };
    })()"""
    result = js(policy, expr)
    # 線形なら概ね 16 倍。定数項に埋もれるので上限は緩く取り、桁が変わらないことを見る。
    assert result["large"] < max(50, result["small"] * 200)
    assert result["large"] < 1000
