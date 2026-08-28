# =============================================================================
# test_grapheditor_e2e_sanitize.py — 未信頼 SVG 取り込みの迂回テスト(実 Edge)
# =============================================================================
# 旧 `editor_sanitize.e2e.ts`(Playwright/TS)からの 1:1 移植。読み込んだ SVG はアプリ origin の
# 生 DOM へインライン挿入される(`getBBox` の実測が要るため)。したがって「危険物が実行され
# ないこと」は実ブラウザでしか主張できない。
#
# 本ファイルは**denylist では止まらない迂回入力を並べ、それが失敗すること**を主張する。
# 個別の要素名・属性名を数える形にはしない(次の別名で無力化されるため)。代わりに
# 「出力ツリーに名前空間つき属性が 1 つも無い」「ELEMENT / TEXT 以外のノードが無い」
# のような**不変条件**を主張する。**セキュリティガードの中核** — 断言の弱体化・ケース
# 省略は絶対にしない。悪性 SVG ペイロード・evaluate 文字列は旧 TS から逐語で写す。
import os

import pytest

pytestmark = [pytest.mark.browser, pytest.mark.e2e]

_PIE_SAMPLE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "pie_sample.svg")
with open(_PIE_SAMPLE_PATH, "r", encoding="utf-8") as _f:
    PIE_SAMPLE = _f.read()


def svg_with(inner, root_attrs="", slice_fill="#4e79a7"):
    """slices / labels を備えた最小 SVG に、迂回用のマークアップ `inner` を足す。
    `root_attrs` は名前空間宣言(`xmlns:xl=…`)を根へ足すための逃げ道。"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 450" width="600" height="450" {root_attrs}>
  <g id="slices">
    <g class="slice" data-name="Alpha"><path d="M300,225 L300,90 A135,135 0 0 1 435,225 Z" fill="{slice_fill}"/></g>
    <g class="slice" data-name="Beta"><path d="M300,225 L435,225 A135,135 0 0 1 300,360 Z" fill="#f28e2b"/></g>
  </g>
  <g id="labels">
    <g class="label" data-name="Alpha" data-percent="50"><text x="500" y="60" fill="#111111"><tspan x="500">Alpha</tspan><tspan x="500" dy="1.1em">50%</tspan></text></g>
    <g class="label" data-name="Beta" data-percent="50"><text x="360" y="300" fill="#111111"><tspan x="360">Beta</tspan><tspan x="360" dy="1.1em">50%</tspan></text></g>
  </g>
  {inner}
</svg>"""


def inspect_canvas(page):
    """読み込んだ後の DOM を機械的に走査し、不変条件の判定材料をまとめて返す。"""
    return page.evaluate(
        """
        () => {
            const svg = document.querySelector("#canvas svg");
            if (!svg) return null;
            const nodeTypes = new Set();
            const elements = [];
            const nsAttrs = [];
            const walker = document.createTreeWalker(svg, NodeFilter.SHOW_ALL);
            const visit = (n) => {
                nodeTypes.add(n.nodeType);
                if (n.nodeType === Node.ELEMENT_NODE) {
                    const el = n;
                    elements.push(el.localName);
                    for (const a of Array.from(el.attributes)) {
                        if (a.namespaceURI !== null) nsAttrs.push(`${el.localName}@${a.name}`);
                    }
                }
            };
            visit(svg);
            let cur;
            while ((cur = walker.nextNode())) visit(cur);
            return {
                nodeTypes: [...nodeTypes],
                elements,
                nsAttrs,
                html: svg.outerHTML,
            };
        }
        """
    )


def sanitize_counts(page, svg):
    """`sanitizeSvg` を直接呼び、除去件数を取る(ページ内の ESM を動的 import)。"""
    return page.evaluate(
        """
        async (text) => {
            const specifier = "/js/utils.js";
            const m = await import(specifier);
            const res = m.sanitizeSvg(text);
            return res ? { ok: true, removed: m.removedCount(res.removed) } : { ok: false, removed: -1 };
        }
        """,
        svg,
    )


@pytest.fixture(autouse=True)
def _goto(e2e_page):
    page = e2e_page
    page.goto("/ui.html")
    page.wait_for_function("() => !!window.__editor")


# ── 1. denylist では止まらない 4 経路 ──


def test_foreignobject_xhtml_iframe_not_taken_in_and_srcdoc_does_not_run(e2e_page):
    page = e2e_page
    svg = svg_with(
        '<foreignObject x="0" y="0" width="300" height="200">'
        '<iframe xmlns="http://www.w3.org/1999/xhtml" '
        'srcdoc="&lt;script&gt;parent.__pwned=1&lt;/script&gt;"></iframe>'
        "</foreignObject>"
    )
    page.evaluate(
        "(s) => window.__editor.load({ name: 'p002', id: 1, content: s })", svg
    )
    # srcdoc の実行は非同期なので少し待ってから判定する。
    page.wait_for_timeout(300)

    r = inspect_canvas(page)
    assert r is not None
    assert "foreignObject" not in r["elements"]
    assert "iframe" not in r["elements"]
    assert page.evaluate("() => window.__pwned") is None
    assert page.evaluate('() => document.querySelectorAll("#canvas iframe").length') == 0


def test_animate_href_swap_drops_the_whole_element(e2e_page):
    page = e2e_page
    svg = svg_with(
        '<a href="#safe"><rect id="bait" x="10" y="10" width="80" height="80" fill="#000000"/>'
        '<animate attributeName="href" values="javascript:window.__c3=1" fill="freeze" dur="0.1s"/></a>'
    )
    page.evaluate(
        "(s) => window.__editor.load({ name: 'p010', id: 1, content: s })", svg
    )
    page.wait_for_timeout(300)

    r = inspect_canvas(page)
    assert "animate" not in r["elements"]
    assert "a" not in r["elements"]
    # 餌の `<rect>` ごと(親の `<a>` が許可外なので部分木ごと)落ちる。
    assert page.evaluate('() => document.querySelector("#canvas #bait")') is None
    assert page.evaluate("() => window.__c3") is None


def test_alternate_prefix_xlink_and_control_char_scheme_drop_the_whole_namespaced_attr(e2e_page):
    page = e2e_page
    svg = svg_with(
        # (a) 任意プレフィックスでの xlink 宣言 — 文字列比較では無限に別名を作れる。
        '<g xl:href="javascript:window.__c3=1"><rect x="0" y="0" width="10" height="10" fill="#000000"/></g>'
        # (b) スキーム内部にタブを挟む形 — URL パーサはタブを除いてから解釈する。
        '<g href="java\tscript:window.__c3=1"><rect x="20" y="0" width="10" height="10" fill="#000000"/></g>'
        # (c) 見慣れない prefix でも同じ名前空間 URI なら同じ扱いになること。
        '<g ev:href="javascript:window.__c3=1"><rect x="40" y="0" width="10" height="10" fill="#000000"/></g>',
        'xmlns:xl="http://www.w3.org/1999/xlink" xmlns:ev="http://www.w3.org/1999/xlink"',
    )
    page.evaluate(
        "(s) => window.__editor.load({ name: 'p011', id: 1, content: s })", svg
    )

    r = inspect_canvas(page)
    # 個別の属性名ではなく「名前空間つき属性が 1 つも無い」ことを主張する。
    assert r["nsAttrs"] == []
    assert "href" not in r["html"]
    assert "script:" not in r["html"].lower()
    assert page.evaluate("() => window.__c3") is None


def test_external_url_image_import_font_face_do_not_fire_external_requests(e2e_page):
    page = e2e_page
    external = []

    def _on_request(req):
        u = req.url
        if not u.startswith("http://127.0.0.1:") and not u.startswith("data:") and not u.startswith("blob:"):
            external.append(u)

    page.on("request", _on_request)

    svg = svg_with(
        '<image href="https://example.invalid/x.png" x="0" y="0" width="10" height="10"/>'
        "<style>@import url(https://example.invalid/x.css);"
        '@font-face{font-family:"Evil";src:url(https://example.invalid/f.woff2) format("woff2");}</style>'
    )
    page.evaluate(
        "(s) => window.__editor.load({ name: 'p025', id: 1, content: s })", svg
    )
    page.wait_for_timeout(500)

    r = inspect_canvas(page)
    assert "image" not in r["elements"]
    # `<style>` は文法に一致しないので丸ごと落ちる(`@import` を消す denylist ではない)。
    assert "style" not in r["elements"]
    assert "example.invalid" not in r["html"]
    assert external == []


# ── 2. インスペクタ ──


def test_fill_closing_the_attribute_cannot_inject_an_element_into_the_inspector(e2e_page):
    page = e2e_page
    evil_fill = '#fff&quot;&gt;&lt;img src=x onerror=&quot;window.__x1=1&quot;&gt;'
    svg = svg_with("", "", evil_fill)
    page.evaluate(
        "(s) => window.__editor.load({ name: 'p001', id: 1, content: s })", svg
    )
    page.wait_for_function("() => window.__editor.labels && window.__editor.labels.length >= 1")
    page.evaluate(
        """
        () => {
            const ed = window.__editor;
            ed.selectLabel(ed.labels.find((l) => l.name === "Alpha"));
            ed.flushNow();
        }
        """
    )
    page.wait_for_timeout(200)

    r = page.evaluate(
        """
        () => {
            const body = document.querySelector("#inspectorBody");
            const sw = body.querySelector(".selname .sw");
            return {
                imgCount: body.querySelectorAll("img").length,
                html: body.innerHTML,
                bg: getComputedStyle(sw).backgroundColor,
                inline: sw.getAttribute("style"),
                name: body.querySelector(".selname .nm").textContent,
            };
        }
        """
    )
    assert r["imgCount"] == 0
    assert "onerror" not in r["html"]
    assert page.evaluate("() => window.__x1") is None
    # 不正な色は CSSOM が黙って無視するので、フォールバックのまま(背景が塗られない)。
    assert "onerror" not in (r["inline"] or "")
    assert r["bg"] != "rgb(255, 255, 255)"
    assert r["name"] == "Alpha 50%"


def test_legit_fill_is_reflected_in_the_swatch_as_before(e2e_page):
    page = e2e_page
    page.evaluate(
        "(s) => window.__editor.load({ name: 'ok', id: 1, content: s })",
        svg_with("", "", "#4e79a7"),
    )
    page.wait_for_function("() => window.__editor.labels && window.__editor.labels.length >= 1")
    page.evaluate(
        """
        () => {
            const ed = window.__editor;
            ed.selectLabel(ed.labels.find((l) => l.name === "Alpha"));
            ed.flushNow();
        }
        """
    )
    bg = page.evaluate(
        '() => getComputedStyle(document.querySelector("#inspectorBody .selname .sw")).backgroundColor'
    )
    assert bg == "rgb(78, 121, 167)"


# ── 3. 出力ツリーの不変条件 ──


def test_ingested_dom_has_no_nodes_other_than_element_and_text(e2e_page):
    page = e2e_page
    svg = svg_with(
        '<!-- comment --><?xml-stylesheet href="https://example.invalid/x.css"?>'
        '<g><![CDATA[raw]]><rect x="0" y="0" width="5" height="5" fill="#000000"/></g>'
    )
    page.evaluate(
        "(s) => window.__editor.load({ name: 'nodes', id: 1, content: s })", svg
    )

    r = inspect_canvas(page)
    # 1=ELEMENT / 3=TEXT のみ。コメント(8)・処理命令(7)・CDATA(4) は持ち込まない。
    assert sorted(r["nodeTypes"]) == [1, 3]
    assert "example.invalid" not in r["html"]


def test_saved_output_carries_no_active_content_and_reload_removes_nothing(e2e_page):
    page = e2e_page
    svg = svg_with(
        '<foreignObject width="10" height="10"><iframe xmlns="http://www.w3.org/1999/xhtml" srcdoc="&lt;script&gt;1&lt;/script&gt;"></iframe></foreignObject>'
        '<a href="#x"><animate attributeName="href" values="javascript:1" fill="freeze"/></a>'
        '<image href="https://example.invalid/x.png" width="10" height="10"/>'
        '<g onload="window.__c3=1"><rect x="0" y="0" width="5" height="5" fill="#000000"/></g>',
        'xmlns:xl="http://www.w3.org/1999/xlink"',
    )
    page.evaluate(
        "(s) => window.__editor.load({ name: 'bake', id: 1, content: s })", svg
    )
    page.wait_for_function("() => window.__editor.labels && window.__editor.labels.length >= 1")

    out = page.evaluate("() => window.__editor.bakeSvg()")
    for bad in ["foreignObject", "iframe", "animate", "javascript", "onerror", "onload", "https://"]:
        assert bad not in out, bad
    # 出口が入口を通る(自己一貫性)。ここが 0 でないと `save` は保存を中止する。
    assert sanitize_counts(page, out) == {"ok": True, "removed": 0}


def test_input_with_disallowed_content_never_reports_zero_removed_and_user_is_told(e2e_page):
    page = e2e_page
    svg = svg_with("<script>window.__c3=1</script>")
    counts = sanitize_counts(page, svg)
    assert counts["ok"] is True
    assert counts["removed"] > 0

    page.evaluate(
        "(s) => window.__editor.load({ name: 'warn', id: 1, content: s })", svg
    )
    status = page.evaluate('() => document.querySelector(".footer .skip-note")?.textContent')
    assert "除去" in status


def test_input_that_cannot_be_parsed_as_svg_is_null_load_aborts(e2e_page):
    page = e2e_page
    assert sanitize_counts(page, "<html><body>x</body></html>") == {"ok": False, "removed": -1}
    assert sanitize_counts(page, "not xml at all <<<") == {"ok": False, "removed": -1}


# ── 4. 実用が壊れていないことの主張 ──


def test_real_pie_chart_output_nothing_removed_font_data_star_textlength_preserved(e2e_page):
    page = e2e_page
    assert sanitize_counts(page, PIE_SAMPLE) == {"ok": True, "removed": 0}

    page.evaluate(
        "(s) => window.__editor.load({ name: 'pie', id: 1, content: s })", PIE_SAMPLE
    )
    page.wait_for_function("() => window.__editor.labels && window.__editor.labels.length >= 4")

    r = page.evaluate(
        """
        () => {
            const svg = document.querySelector("#canvas svg");
            const style = svg.querySelector("style");
            return {
                labels: window.__editor.labels.length,
                styleCount: svg.querySelectorAll("style").length,
                css: style ? style.textContent || "" : "",
                hasDefs: !!svg.querySelector("defs"),
                hasRect: !!svg.querySelector("rect:not([data-editor-hit])"),
                hasTspan: !!svg.querySelector("tspan"),
                dataNames: [...svg.querySelectorAll("#labels > g.label")].map((g) => g.getAttribute("data-name")),
                slicePathFill: svg.querySelector("#slices g.slice path")?.getAttribute("fill"),
                leaderPaths: svg.querySelectorAll("#labels path").length,
            };
        }
        """
    )
    assert r["labels"] == 4
    assert r["styleCount"] == 1
    assert "@font-face" in r["css"]
    assert "data:font/woff2" in r["css"]
    assert r["hasDefs"] is True
    assert r["hasRect"] is True
    assert r["hasTspan"] is True
    assert all(n for n in r["dataNames"])
    assert r["slicePathFill"] is not None
    import re

    assert re.match(r"^#[0-9a-f]{6}$", r["slicePathFill"], re.IGNORECASE)
    assert r["leaderPaths"] > 0


# ── 5. bakeSvg の覆いの穴 2 つ(選択マーカーの予約 data-* 化 / 出口検査の try/catch) ──


def test_selection_marker_missed_by_removal_list_is_still_caught_by_reserved_data_editor_sel(e2e_page):
    page = e2e_page
    # `bakeSvg` の除去列挙(`[data-editor-sel]` の属性除去)が将来漏れても、選択マーカーが
    # 予約 `data-*` である限り出口検査は必ず `removed>0` に倒れて保存を止める、という
    # 安全網そのものを主張する(`class="is-selected"` のような素のクラス名は `class` が
    # 値無検査の許可属性なので、この網に掛からなかった)。
    svg = svg_with("").replace(
        '<g class="label" data-name="Alpha" data-percent="50">',
        '<g class="label" data-name="Alpha" data-percent="50" data-editor-sel="1">',
    )
    counts = sanitize_counts(page, svg)
    assert counts["ok"] is True
    assert counts["removed"] > 0


def test_sanitizesvg_throwing_makes_save_abort_and_not_trigger_a_download(e2e_page):
    page = e2e_page
    # 入口は既に明示 try/catch 済みだが、出口 `sanitizeSvg(out)` は未対応だと例外が
    # unhandled rejection になり「保存ボタンを押しても何も起きない」無言失敗になる。
    # `/js/utils.js` の `sanitizeSvg` を例外を投げる版へ差し替え、save がステータス表示の
    # うえ return し、ダウンロードが起きないことを確かめる。例外は `window.__throwSanitize`
    # フラグが立っている時だけ投げる — `load` も同じ `sanitizeSvg` を通るため、無条件に
    # 投げると読込自体が(これも中断 = 意図どおり)落ちてしまい、保存経路だけを狙って
    # 検証できない。

    def _handler(route):
        res = route.fetch()
        body = res.text()
        patched = body.replace(
            "function sanitizeSvg(svgText) {",
            'function sanitizeSvg(svgText) { if (window.__throwSanitize) throw new Error("boom-test");',
        )
        assert patched != body  # 置換が実際に効いたことの前提(壊れたら誤検証を防ぐ)
        route.fulfill(response=res, body=patched)

    page.route("**/js/utils.js", _handler)
    page.goto("/ui.html")
    page.wait_for_function("() => !!window.__editor")
    page.evaluate(
        "(s) => window.__editor.load({ name: 'throwtest', id: 1, content: s })", PIE_SAMPLE
    )
    page.wait_for_function("() => window.__editor.labels && window.__editor.labels.length >= 4")

    download_fired = {"value": False}

    def _on_download(_download):
        download_fired["value"] = True

    page.once("download", _on_download)
    page.evaluate("() => { window.__throwSanitize = true; }")
    page.evaluate("() => window.__editor.save()")
    page.wait_for_timeout(200)

    status = page.evaluate('() => document.querySelector(".footer .skip-note")?.textContent')
    assert "保存を中止しました" in status
    assert download_fired["value"] is False


def test_round_trip_reopening_saved_output_zero_removed_same_label_count_transform_baked_in(e2e_page):
    page = e2e_page
    page.evaluate(
        "(s) => window.__editor.load({ name: 'pie', id: 1, content: s })", PIE_SAMPLE
    )
    page.wait_for_function("() => window.__editor.labels && window.__editor.labels.length >= 4")

    out = page.evaluate(
        """
        () => {
            const ed = window.__editor;
            ed.selectLabel(ed.labels[0]);
            ed.nudge(12, -7);
            ed.flushNow();
            return ed.bakeSvg();
        }
        """
    )
    assert "translate(" not in out
    assert sanitize_counts(page, out) == {"ok": True, "removed": 0}

    labels = page.evaluate(
        """
        async (s) => {
            await window.__editor.load({ name: "pie2", id: 2, content: s });
            return window.__editor.labels.length;
        }
        """,
        out,
    )
    assert labels == 4
