# =============================================================================
# test_grapheditor_e2e_ops.py — Undo/Redo・保存 bake・インスペクタ操作の E2E
# =============================================================================
# 旧 `editor_ops.e2e.ts`(Playwright/TS)からの 1:1 移植。`editor.js` の責務分割 (リファクタ) に
# 先行して回帰網を敷く。ドラッグ系の不変条件は `test_grapheditor_e2e_drag.py` が担当し、
# 本ファイルは「状態遷移 (履歴)」「保存出力のクリーン性」「インスペクタの実クリック配線」を
# 実ブラウザで固定する。
import os
import re

import pytest

pytestmark = [pytest.mark.browser, pytest.mark.e2e]

_FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "editor_pie.svg")
with open(_FIXTURE_PATH, "r", encoding="utf-8") as _f:
    SVG = _f.read()


@pytest.fixture(autouse=True)
def _load_fixture(e2e_page):
    page = e2e_page
    page.goto("/ui.html")
    page.wait_for_function("() => !!window.__editor")
    page.evaluate(
        "async (svg) => { await window.__editor.load({ name: 'fixture', id: 1, content: svg }); }",
        SVG,
    )
    page.wait_for_function("() => window.__editor.labels && window.__editor.labels.length >= 2")


def test_undo_redo_round_trips_label_position_and_new_op_discards_redo_branch(e2e_page):
    page = e2e_page
    r = page.evaluate("""
        () => {
            const ed = window.__editor;
            const s = ed.labels.find((l) => l.name === "Alpha");
            ed.selectLabel(s);
            const at = () => ({ x: s.textTx.x, y: s.textTx.y });

            ed.nudge(30, 20);
            ed.nudge(10, 0);
            const afterMoves = at();
            ed.undo();
            const afterUndo1 = at();
            ed.undo();
            const afterUndo2 = at();
            ed.redo();
            const afterRedo = at();
            // 新規操作 (nudge) は redo 分岐を破棄する
            ed.nudge(0, 5);
            const redoLenAfterNewOp = ed.redoStack.length;
            return { afterMoves, afterUndo1, afterUndo2, afterRedo, redoLenAfterNewOp };
        }
    """)

    assert r["afterMoves"] == {"x": 40, "y": 20}
    assert r["afterUndo1"] == {"x": 30, "y": 20}
    assert r["afterUndo2"] == {"x": 0, "y": 0}
    assert r["afterRedo"] == {"x": 30, "y": 20}
    assert r["redoLenAfterNewOp"] == 0


def test_save_bake_burns_in_transform_removes_editor_elements_restores_original_size(e2e_page):
    page = e2e_page
    out = page.evaluate("""
        () => {
            const ed = window.__editor;
            const s = ed.labels.find((l) => l.name === "Alpha");
            ed.selectLabel(s);
            ed.nudge(30, 20);
            ed.flushNow(); // 選択を移す前に Alpha の DOM 反映を確定 (描画は選択中ラベルのみ)
            // 非表示 leader が bake で除去されることも見る: Beta に leader を付けて非表示化
            const b = ed.labels.find((l) => l.name === "Beta");
            ed.selectLabel(b);
            ed.inspectorAction("leaderAdd");
            ed.inspectorAction("leaderOff");
            ed.flushNow();
            ed.zoom = 2; // 表示ズーム中でも出力は元サイズであること
            ed.applyZoom();
            return ed.bakeSvg();
        }
    """)

    assert out.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    # 編集専用要素・クラスが残らない
    assert "data-editor" not in out
    assert "label-hit" not in out
    # Beta が選択状態のまま bake しても選択マーカー(予約 data-editor-sel)が残らない
    assert "data-editor-sel" not in out
    assert "editor-overlay" not in out
    # Alpha: x=529+30 / y=68+20 に焼き込まれ transform は残らない
    assert 'x="559"' in out
    assert 'y="88"' in out
    assert "translate(30" not in out
    # ズーム表示ではなく元サイズへ復元
    assert 'width="600px"' in out
    assert 'height="450px"' in out
    # Beta の非表示 leader は除去される (path は Alpha の leader と slices のみ)
    beta_group = (
        re.search(r'<g[^>]*data-name="Beta"[^>]*class="label"[\s\S]*?</g>', out) or
        re.search(r'<g[^>]*class="label"[^>]*data-name="Beta"[\s\S]*?</g>', out)
    )
    assert beta_group is not None
    assert "<path" not in beta_group.group(0)


def test_inspector_real_clicks_wire_leader_add_bend_lines_fill_reset(e2e_page):
    # Beta (leader なし・円内) を選択してインスペクタを開く
    page = e2e_page
    page.evaluate("""
        () => {
            const ed = window.__editor;
            ed.selectLabel(ed.labels.find((l) => l.name === "Beta"));
        }
    """)

    def state():
        return page.evaluate("""
            () => {
                const s = window.__editor.selected;
                return {
                    pts: s.leaderPts.length,
                    visible: s.leaderVisible,
                    fill: s.fill,
                    lineCount: s.lineCount,
                    tx: { ...s.textTx },
                };
            }
        """)

    # 引出線「表示」(leader 無し時は追加として動く)
    page.click('[data-act="leaderAdd"]')
    st = state()
    assert st["pts"] == 2
    assert st["visible"] is True

    # 曲げ点「あり」→ 3 点化
    page.click('[data-act="bendAdd"]')
    assert state()["pts"] == 3

    # 行数「2行」→ tspan が 2 行構成に組み直される
    page.click('[data-act="lines2"]')
    assert state()["lineCount"] == 2
    tspan_rows = page.evaluate("""
        () => {
            const s = window.__editor.selected;
            window.__editor.flushNow();
            return [...s.text.querySelectorAll("tspan")].filter((t) => t.hasAttribute("x")).length;
        }
    """)
    assert tspan_rows == 2

    # 文字色「白」
    page.click('[data-act="insideOn"]')
    assert state()["fill"] == "#ffffff"

    # このラベルをリセット → 初期状態 (leader なし・1 行・元色) へ戻る
    page.click('[data-act="resetOne"]')
    final = state()
    assert final["pts"] == 0
    assert final["visible"] is False
    assert final["lineCount"] == 1
    assert final["fill"] == "#111111"


def test_switching_files_from_rail_with_unsaved_edits_confirms_and_cancel_keeps_edits(e2e_page):
    # レール (手順2 の左一覧) に 2 ファイルを載せ、1 つ目を開いた状態にする。
    page = e2e_page
    page.evaluate(
        """
        async (svg) => {
            const ed = window.__editor;
            ed.items = [
                { name: "first.svg", id: 1, content: svg, edited: false },
                { name: "second.svg", id: 2, content: svg, edited: false },
            ];
            ed._itemSeq = 2;
            await ed.load(ed.items[0]);
            ed.renderList();
        }
        """,
        SVG,
    )

    # 1 つ目を編集する (`load` は履歴ごと作り直すので、切替えると Undo でも戻せない)。
    page.evaluate("""
        () => {
            const ed = window.__editor;
            ed.selectLabel(ed.labels.find((l) => l.name === "Alpha"));
            ed.nudge(25, 15);
        }
    """)

    def alpha_tx():
        return page.evaluate("""
            () => {
                const s = window.__editor.labels.find((l) => l.name === "Alpha");
                return { ...s.textTx, id: window.__editor.currentId };
            }
        """)

    assert alpha_tx() == {"x": 25, "y": 15, "id": 1}

    # キャンセル: 確認ダイアログが出て、切替は起きず編集も残る。
    seen = {"message": ""}

    def _on_dialog_dismiss(dialog):
        seen["message"] = dialog.message
        dialog.dismiss()

    page.once("dialog", _on_dialog_dismiss)
    page.click('.fileitem[data-id="2"]')
    assert "second.svg" in seen["message"]
    assert alpha_tx() == {"x": 25, "y": 15, "id": 1}

    # 承諾: 切替が起きて、新しいファイルは未編集の状態で開く。
    page.once("dialog", lambda dialog: dialog.accept())
    page.click('.fileitem[data-id="2"]')
    page.wait_for_function("() => window.__editor.currentId === 2")
    assert alpha_tx() == {"x": 0, "y": 0, "id": 2}


def test_switching_files_without_unsaved_edits_does_not_prompt(e2e_page):
    page = e2e_page
    page.evaluate(
        """
        async (svg) => {
            const ed = window.__editor;
            ed.items = [
                { name: "first.svg", id: 1, content: svg, edited: false },
                { name: "second.svg", id: 2, content: svg, edited: false },
            ];
            ed._itemSeq = 2;
            await ed.load(ed.items[0]);
            ed.renderList();
        }
        """,
        SVG,
    )

    dialogs = {"count": 0}

    def _on_dialog(dialog):
        dialogs["count"] += 1
        dialog.dismiss()

    page.on("dialog", _on_dialog)
    page.click('.fileitem[data-id="2"]')
    page.wait_for_function("() => window.__editor.currentId === 2")
    assert dialogs["count"] == 0


def test_shortcuts_gate_by_step_and_focus_and_arrow_repeat_does_not_pile_up_history(e2e_page):
    page = e2e_page

    def hist():
        return page.evaluate("() => window.__editor.history.length")

    def tx():
        return page.evaluate("""
            () => {
                const s = window.__editor.labels.find((l) => l.name === "Alpha");
                return { ...s.textTx };
            }
        """)

    page.evaluate("""
        () => {
            const ed = window.__editor;
            ed.selectLabel(ed.labels.find((l) => l.name === "Alpha"));
            ed.nudge(30, 20);
        }
    """)
    assert tx() == {"x": 30, "y": 20}

    # 手順 1 (開く画面) では文書の Undo を受け付けない。キャンバスが見えないまま
    # 状態だけ動くのを防ぐため。
    page.evaluate("() => window.__editor.goPhase(1)")
    page.keyboard.press("Control+z")
    assert tx() == {"x": 30, "y": 20}

    # 手順 2 へ戻せば効く。
    page.evaluate("() => window.__editor.goPhase(2)")
    page.keyboard.press("Control+z")
    assert tx() == {"x": 0, "y": 0}

    # 矢印キーのリピート: 1 回目だけ履歴へ積み、押しっぱなしの分はまとめて 1 回で戻る。
    before = hist()
    page.evaluate("""
        () => {
            const fire = (repeat) =>
                window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", repeat, bubbles: true }));
            fire(false);
            fire(true);
            fire(true);
            fire(true);
        }
    """)
    assert tx() == {"x": 4, "y": 0}
    assert hist() == before + 1
    page.keyboard.press("Control+z")
    assert tx() == {"x": 0, "y": 0}
