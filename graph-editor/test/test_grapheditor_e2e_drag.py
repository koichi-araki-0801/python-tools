# =============================================================================
# test_grapheditor_e2e_drag.py — ラベル移動時の leader 端点不変条件を検証する E2E
# =============================================================================
# 旧 `editor_drag.e2e.ts`（Playwright/TS）からの 1:1 移植。`ui.html` を実ブラウザ
# (Edge channel) へロードし、実 `getBBox` を使ってラベルを移動したとき引出線(leader)の
# 端点が「必ずラベル外枠上」に来る不変条件を検証する。
import os
import re

import pytest

pytestmark = [pytest.mark.browser, pytest.mark.e2e]

_FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "editor_pie.svg")
with open(_FIXTURE_PATH, "r", encoding="utf-8") as _f:
    SVG = _f.read()

EPS = 0.5  # 実 `getBBox` とパス文字列の丸めを吸収する許容誤差(px)


def on_frame(p, box):
    """点 `p` が外枠 `box` の辺/角上(=境界距離≈0 かつ矩形範囲内)にあるか。"""
    within = (p["x"] >= box["left"] - EPS and p["x"] <= box["right"] + EPS and
              p["y"] >= box["top"] - EPS and p["y"] <= box["bottom"] + EPS)
    on_edge = (abs(p["x"] - box["left"]) < EPS or abs(p["x"] - box["right"]) < EPS or
               abs(p["y"] - box["top"]) < EPS or abs(p["y"] - box["bottom"]) < EPS)
    return within and on_edge


def clamp(p, box):
    """`clampPointToBox` の Python 側参照実装(端点の期待値算出用)。"""
    return {
        "x": max(box["left"], min(p["x"], box["right"])),
        "y": max(box["top"], min(p["y"], box["bottom"])),
    }


@pytest.fixture(autouse=True)
def _load_fixture(e2e_page):
    page = e2e_page
    page.goto("/ui.html")
    page.wait_for_function("() => !!window.__editor")
    page.evaluate(
        "async (svg) => { await window.__editor.load({ name: 'fixture', id: 1, content: svg }); }",
        SVG,
    )
    # ラベル (`labels`) が構築されるまで待つ
    page.wait_for_function("() => window.__editor.labels && window.__editor.labels.length >= 2")


def test_move_label_around_pie_endpoint_always_on_frame_manual_leader(e2e_page):
    page = e2e_page
    samples = page.evaluate("""
        () => {
            const ed = window.__editor;
            const s = ed.labels.find((l) => l.name === "Alpha");
            ed.selectLabel(s);
            const moves = [[120, 0], [0, 160], [-120, 0], [0, -160], [200, 80]];
            const out = [];
            for (const [dx, dy] of moves) {
                ed.nudge(dx, dy);
                ed.flushNow();
                const b = s.text.getBBox();
                const box = {
                    left: b.x + s.textTx.x,
                    top: b.y + s.textTx.y,
                    right: b.x + s.textTx.x + b.width,
                    bottom: b.y + s.textTx.y + b.height,
                };
                out.push({
                    box,
                    pts: s.leaderPts.map((p) => ({ x: p.x, y: p.y })),
                    leaderVisible: s.leaderVisible,
                    dAttr: s.path ? s.path.getAttribute("d") : null,
                });
            }
            return out;
        }
    """)

    assert len(samples) == 5
    for smp in samples:
        assert len(smp["pts"]) >= 2
        assert smp["leaderVisible"] is True
        endpoint = smp["pts"][-1]
        prev = smp["pts"][-2]
        # 端点は外枠上にある
        assert on_frame(endpoint, smp["box"]), f"endpoint {endpoint} not on frame {smp['box']}"
        # 端点 = 手前の点を外枠へクランプした点
        expected = clamp(prev, smp["box"])
        assert endpoint["x"] == pytest.approx(expected["x"], abs=0.05)
        assert endpoint["y"] == pytest.approx(expected["y"], abs=0.05)
        # DOM のパス末尾も同じ端点 (描画まで結線されている)
        assert smp["dAttr"] is not None
        nums = [float(n) for n in re.findall(r"-?\d*\.?\d+(?:e[-+]?\d+)?", smp["dAttr"], re.IGNORECASE)]
        dom_end = {"x": nums[-2], "y": nums[-1]}
        assert dom_end["x"] == pytest.approx(endpoint["x"], abs=0.05)
        assert dom_end["y"] == pytest.approx(endpoint["y"], abs=0.05)


def test_auto_leader_outside_pie_endpoint_on_frame_and_removed_when_back_inside(e2e_page):
    page = e2e_page
    result = page.evaluate("""
        () => {
            const ed = window.__editor;
            const s = ed.labels.find((l) => l.name === "Beta");
            ed.selectLabel(s);

            // 初期: 円内・leader なし
            const initial = { len: s.leaderPts.length, visible: s.leaderVisible };

            // 円外へ大きく移動 → 自動 leader が生成されるはず
            ed.nudge(-220, 160);
            ed.flushNow();
            const b = s.text.getBBox();
            const box = {
                left: b.x + s.textTx.x,
                top: b.y + s.textTx.y,
                right: b.x + s.textTx.x + b.width,
                bottom: b.y + s.textTx.y + b.height,
            };
            const outside = {
                pts: s.leaderPts.map((p) => ({ x: p.x, y: p.y })),
                visible: s.leaderVisible,
                box,
            };

            // 円内へ戻す → 自動分は削除されるはず
            ed.nudge(220, -160);
            ed.flushNow();
            const back = { len: s.leaderPts.length, visible: s.leaderVisible };

            return { initial, outside, back };
        }
    """)

    # 初期は leader なし
    assert result["initial"]["len"] == 0
    assert result["initial"]["visible"] is False

    # 円外: 自動生成され端点が外枠上
    assert len(result["outside"]["pts"]) >= 2
    assert result["outside"]["visible"] is True
    ep = result["outside"]["pts"][-1]
    assert on_frame(ep, result["outside"]["box"]), \
        f"auto endpoint {ep} not on frame {result['outside']['box']}"

    # 円内へ戻すと自動 leader は除去
    assert result["back"]["len"] == 0
    assert result["back"]["visible"] is False


def test_label_frame_change_by_line_count_and_condense_endpoint_returns_to_frame(e2e_page):
    # Alpha は円外・leader 付きのラベル。行数 (1⇄2) と長体はラベルの外枠を変えるので、
    # 端点をそのままにすると外枠から外れる (枠の内側に浮く / 遠くへ取り残される)。
    page = e2e_page
    samples = page.evaluate("""
        () => {
            const ed = window.__editor;
            const s = ed.labels.find((l) => l.name === "Alpha");
            ed.selectLabel(s);
            const sample = () => {
                ed.flushNow();
                const b = s.text.getBBox();
                const box = {
                    left: b.x + s.textTx.x,
                    top: b.y + s.textTx.y,
                    right: b.x + s.textTx.x + b.width,
                    bottom: b.y + s.textTx.y + b.height,
                };
                return {
                    box,
                    pts: s.leaderPts.map((p) => ({ x: p.x, y: p.y })),
                    leaderVisible: s.leaderVisible,
                    dAttr: s.path ? s.path.getAttribute("d") : null,
                };
            };
            const out = [];
            ed.inspectorAction("lines2");
            out.push(sample());
            ed.setNameScaleX(s, 0.6);
            out.push(sample());
            ed.inspectorAction("lines1");
            out.push(sample());
            return out;
        }
    """)

    assert len(samples) == 3
    for smp in samples:
        assert len(smp["pts"]) >= 2
        endpoint = smp["pts"][-1]
        prev = smp["pts"][-2]
        assert on_frame(endpoint, smp["box"]), f"endpoint {endpoint} not on frame {smp['box']}"
        expected = clamp(prev, smp["box"])
        assert endpoint["x"] == pytest.approx(expected["x"], abs=0.05)
        assert endpoint["y"] == pytest.approx(expected["y"], abs=0.05)
        # DOM のパス末尾も同じ端点 (描画まで結線されている)
        nums = [float(n) for n in re.findall(r"-?\d*\.?\d+(?:e[-+]?\d+)?", smp["dAttr"], re.IGNORECASE)]
        assert nums[-2] == pytest.approx(endpoint["x"], abs=0.05)
        assert nums[-1] == pytest.approx(endpoint["y"], abs=0.05)
