# =============================================================================
# test_grapheditor_e2e_load_guards.py — 読込時の資源上限と中断時の状態(実 Chromium)
# =============================================================================
# 旧 `editor_load_guards.e2e.ts`(Playwright/TS)からの 1:1 移植。主張は 2 つで、
# どちらも**実ブラウザでしか確かめられない**もの:
#
# 1. **上限が効くこと**: ラベル数・ノード数が上限を超える入力は、途中まで読むのでは
#    なく読込ごと拒否し、件数を利用者へ通知する。速度そのものは端末依存で測っても脆いので、
#    「超過したら明示的に拒否する」ことをテストの主張にする。
# 2. **中断しても前のファイルが残らないこと**: 読込は `ed.name` を新ファイルへ
#    切り替えてから走るため、途中で止まるとキャンバスだけ旧ファイルのまま残り、そのまま
#    保存すると旧内容が新ファイル名で書き出される。中断経路は必ず空状態へ倒す。
import os
import re

import pytest

pytestmark = [pytest.mark.browser, pytest.mark.e2e]


def _constant_from(path, pattern):
    """上限値は**実装のソースから読む**(テスト側へ数値を写すと、実装だけ緩めても緑のままになる)。"""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.search(pattern, text)
    assert m, f"上限値を実装から読めませんでした: {pattern}"
    return int(m.group(1))


_CONSTANTS_JS = os.path.join(os.path.dirname(__file__), "..", "resources", "web", "js", "constants.js")
_UTILS_JS = os.path.join(os.path.dirname(__file__), "..", "resources", "web", "js", "utils.js")

MAX_LABELS = _constant_from(_CONSTANTS_JS, r"maxLabels:\s*(\d+)")
MAX_NODES = _constant_from(_UTILS_JS, r"MAX_SVG_NODES\s*=\s*(\d+)")

# ノード数の上限を確実に超える詰め物。
NODE_FLOOD = '<circle cx="1" cy="1" r="1"/>' * (MAX_NODES + 1000)


def svg_with_labels(count, extra=""):
    """ラベル `count` 個を持つ最小 SVG。`extra` はルート直下へ足す任意マークアップ。"""
    labels = "".join(
        f'<g class="label" data-name="L{i}" data-percent="1"><text x="10" y="{10 + i}" fill="#111111">'
        f'<tspan x="10">L{i}</tspan><tspan x="10" dy="1.1em">1%</tspan></text></g>'
        for i in range(count)
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 450" width="600" height="450">'
        '<g id="slices"><g class="slice" data-name="L0">'
        '<path d="M300,225 L300,90 A135,135 0 0 1 435,225 Z" fill="#4e79a7"/></g></g>'
        f'<g id="labels">{labels}</g>{extra}</svg>'
    )


def load_and_inspect(page, name, content):
    """読込後の観測点をまとめて取り出す(キャンバス実体 + エディタ状態 + 通知文言)。"""
    return page.evaluate(
        """
        async ({ name, content }) => {
            const ed = window.__editor;
            await ed.load({ name, id: Math.floor(Math.random() * 1e9), content });
            const canvas = document.querySelector("#canvas");
            return {
                name: ed.name,
                currentId: ed.currentId,
                labels: ed.labels.length,
                hasSvg: !!ed.svg,
                canvasSvgCount: canvas ? canvas.querySelectorAll("svg").length : -1,
                canvasLabelCount: canvas ? canvas.querySelectorAll("#labels > g.label").length : -1,
                saveDisabled: !!ed.dom.btnSave.disabled,
                status: document.querySelector("#status")?.textContent ?? "",
            };
        }
        """,
        {"name": name, "content": content},
    )


@pytest.fixture(autouse=True)
def _goto(e2e_page):
    page = e2e_page
    page.goto("/ui.html")
    page.wait_for_function("() => !!window.__editor")


def test_over_label_limit_svg_rejected_wholesale_with_count_notified(e2e_page):
    page = e2e_page
    r = load_and_inspect(page, "too_many.svg", svg_with_labels(MAX_LABELS + 1))

    # 部分的に読み込んで「一部だけ編集できる」状態にしない。
    assert r["hasSvg"] is False
    assert r["labels"] == 0
    assert r["canvasSvgCount"] == 0
    assert r["saveDisabled"] is True
    # 黙って消さず、実数と上限の両方を出す。
    assert str(MAX_LABELS + 1) in r["status"]
    assert str(MAX_LABELS) in r["status"]
    assert "上限" in r["status"]


def test_label_count_within_limit_loads_as_before(e2e_page):
    page = e2e_page
    n = min(100, MAX_LABELS)
    r = load_and_inspect(page, "ok.svg", svg_with_labels(n))

    assert r["hasSvg"] is True
    assert r["labels"] == n
    assert r["canvasLabelCount"] == n


def test_over_node_limit_svg_rejected_as_uninterpretable(e2e_page):
    # 入力長 8MiB の制限は「小さなノードを大量に詰める」形を止められないので、ノード数側の
    # 予算で切れることを見る (1 ノードあたり ~28 バイト = 数百 KB 程度の入力)。
    page = e2e_page
    r = load_and_inspect(page, "too_many_nodes.svg", svg_with_labels(2, NODE_FLOOD))

    assert r["hasSvg"] is False
    assert r["labels"] == 0
    assert r["canvasSvgCount"] == 0
    assert "解釈できませんでした" in r["status"]


def test_aborted_load_leaves_no_previous_file_state_on_canvas(e2e_page):
    page = e2e_page
    first = load_and_inspect(page, "first.svg", svg_with_labels(3))
    assert first["hasSvg"] is True
    assert first["canvasLabelCount"] == 3

    # 2 枚目は拒否される入力。名前だけ切り替わって図が残ると、保存時に 1 枚目の内容が
    # 2 枚目のファイル名で書き出される。
    second = load_and_inspect(page, "second.svg", svg_with_labels(2, NODE_FLOOD))
    # 表示上のアイデンティティ (ファイル名 / アイテム id) も空へ戻す。残すと「開いていない
    # のに編集中のファイルがある」状態になり、レールの編集中マークも取り残される。
    assert second["name"] is None
    assert second["currentId"] is None
    assert second["hasSvg"] is False
    assert second["canvasSvgCount"] == 0
    assert second["canvasLabelCount"] == 0
    assert second["labels"] == 0
    assert second["saveDisabled"] is True


def test_font_face_declaration_names_from_prototype_words_still_completes_load(e2e_page):
    # `constructor` / `__proto__` は素のオブジェクト表では継承値を返すため、自前キーだけを
    # 見ないと `re.test` が TypeError になり読込が無言で止まる (キャンバスは前のファイルのまま)。
    page = e2e_page
    style = "<style>@font-face{constructor:a;__proto__:b}</style>"
    load_and_inspect(page, "first.svg", svg_with_labels(3))
    r = load_and_inspect(page, "crafted.svg", svg_with_labels(2, style))

    assert r["name"] == "crafted.svg"
    assert r["hasSvg"] is True
    assert r["labels"] == 2
    assert r["canvasLabelCount"] == 2
    # 認識できない `<style>` は落ちるので、除去件数が利用者へ出る。
    assert "除去" in r["status"]


def test_aborted_load_leaves_no_editing_mark_on_the_rail(e2e_page):
    page = e2e_page
    marks = page.evaluate(
        """
        async ({ ok, bad }) => {
            const ed = window.__editor;
            ed.items = [
                { name: "first.svg", id: 1, content: ok, edited: false },
                { name: "second.svg", id: 2, content: bad, edited: false },
            ];
            ed._itemSeq = 2;
            await ed.load(ed.items[0]);
            const before = document.querySelectorAll("#fileList .fileitem .rdot").length;
            await ed.load(ed.items[1]);
            return { before, after: document.querySelectorAll("#fileList .fileitem .rdot").length };
        }
        """,
        {"ok": svg_with_labels(3), "bad": svg_with_labels(2, NODE_FLOOD)},
    )

    # 読めているうちは 1 件だけ「編集中」。中断後は開いているファイルが無いので 0 件。
    assert marks["before"] == 1
    assert marks["after"] == 0
