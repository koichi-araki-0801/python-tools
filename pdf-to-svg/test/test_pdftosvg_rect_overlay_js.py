# =============================================================================
# test_pdftosvg_rect_overlay_js.py — resources/web/rect-overlay.js の単体（実ブラウザ）
# =============================================================================
# `createRectOverlay` の `draw()` は一覧 RPC を待ってから箱を作る。同じページで `draw()` が
# 重なったとき、後から出した要求の応答が先に届き、遅れて届いた古い一覧で箱を作り直さない
# こと（`mountPage` と同じ世代トークン）を、`ui.rpc` を外から resolve できる Promise に
# 差し替えて確かめる。DOM（`placeRect` の `getBoundingClientRect`）を読むので実ブラウザで回す。
import json

import pytest

from .pdftosvg_js_harness import js

pytestmark = pytest.mark.browser

SETUP = """
window.__roSetup = async () => {
  const st = await import('/state.js');
  const ro = await import('/rect-overlay.js');
  const saved = { phase: st.S.phase, tool: st.S.tool };
  st.S.phase = 3; st.S.tool = "cover";
  const host = document.createElement("div");
  host.style.cssText = "position:relative;width:300px;height:200px";
  host.innerHTML = '<svg viewBox="0 0 300 200" width="300" height="200"></svg>';
  document.body.appendChild(host);
  const pending = [];  // draw() ごとの一覧 RPC の resolve。テストが届く順を決める
  const ui = {
    rpc: () => new Promise((resolve) => { pending.push(resolve); }),
    afterEdit: async () => {},
    pageOf: () => ({ fileIndex: 0, pageInFile: 0 }),
    syncCalls: 0,
    syncDeleteButton() { this.syncCalls++; },
  };
  let sel = null, drag = null;
  const ov = ro.createRectOverlay({
    ui, boxClass: "t-box", tool: "cover", listRpc: "coverList", listKey: "covers", updateRpc: "updateCover",
    getSel: () => sel, setSel: (v) => { sel = v; }, getDrag: () => drag, setDrag: (v) => { drag = v; },
    onSelect: () => {},
  });
  window.__ro = { host, pending, ov, promises: [], saved, st, ui };
};
window.__roTeardown = () => {
  const c = window.__ro; if (!c) return;
  c.st.S.phase = c.saved.phase; c.st.S.tool = c.saved.tool;
  c.host.remove();
  delete window.__ro;
};
"""

RECT = {"x": 10, "y": 10, "w": 50, "h": 30}


@pytest.fixture(scope="module")
def ro(edge_page):
    edge_page.evaluate(SETUP)
    edge_page.evaluate("window.__roSetup()")
    yield edge_page
    # 共有ページ (session スコープの edge_page) を汚さない。`S` はモジュールシングルトンで、
    # 書き換えたまま残すと後に走る browser テストが `phase=3 / tool="cover"` を黙って継承する
    edge_page.evaluate("window.__roTeardown()")


def _box_ids(page):
    return js(page, "[...window.__ro.host.querySelectorAll('.t-box')].map(b => b.dataset.elId)")


def test_draw_discards_a_stale_list_that_arrives_after_a_newer_one(ro):
    """同じページで draw() が 2 回重なり、先に出した要求の応答が後から届いても、
    古い一覧で箱を作り直さない。"""
    # 2 回続けて draw() を始める。どちらも一覧 RPC の応答待ちで止まる
    n = js(ro, "(() => { const c = window.__ro; c.promises.push(c.ov.draw(c.host)); c.promises.push(c.ov.draw(c.host)); return c.pending.length; })()")
    assert n == 2
    # 2 回目 (新しい方) の応答を先に届ける → 箱は elId 2
    js(ro, "(() => { window.__ro.pending[1]({ covers: [{ elId: 2, rect: %s, text: 'b' }] }); return 0; })()" % json.dumps(RECT))
    js(ro, "window.__ro.promises[1]")  # 2 回目の draw() の完了を待つ
    assert _box_ids(ro) == ["2"]
    # 1 回目 (古い方) の応答を後から届ける → 世代が古いので捨てられ、箱は elId 2 のまま
    js(ro, "(() => { window.__ro.pending[0]({ covers: [{ elId: 1, rect: %s, text: 'a' }] }); return 0; })()" % json.dumps(RECT))
    js(ro, "window.__ro.promises[0]")  # 1 回目の draw() の完了を待つ
    assert _box_ids(ro) == ["2"]


def test_draw_syncs_the_delete_button_even_when_the_svg_is_missing(ro):
    """host に svg が無いとき draw() は早期 return するが、押下可否の同期は飛ばさない
    (「選択が変わる全経路から呼ぶ」に穴を作らない)。"""
    before = js(ro, "window.__ro.ui.syncCalls")
    js(ro, "(() => { const c = window.__ro; c.host.querySelector('svg').remove(); return 0; })()")
    js(ro, "window.__ro.ov.draw(window.__ro.host)")
    after = js(ro, "window.__ro.ui.syncCalls")
    assert after == before + 1
    # svg を戻す (後続のテストのため)
    js(ro, "(() => { window.__ro.host.innerHTML = '<svg viewBox=\"0 0 300 200\" width=\"300\" height=\"200\"></svg>'; return 0; })()")
