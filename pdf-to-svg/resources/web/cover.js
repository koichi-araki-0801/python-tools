// =============================================================================
// cover.js — 手順 3「上書き」ツールのオーバーレイ (置換語の同期だけを持つ)
// =============================================================================
// 箱の描画・選択・移動・角ハンドル伸縮は `rect-overlay.js` と共有する。ここが持つのは
// 「上書き固有の部分」= どの一覧 RPC を引くか (`coverList`) と、選んだとき入力欄 (`#cover-text`) に
// 何を映すか、そして入力欄の確定 (`updateCover {text}`) だけ。
import { createRectOverlay } from "./rect-overlay.js";
import { S } from "./state.js";

let ui = null;      // { rpc, afterEdit, pageOf } を app.js が注入する
let overlay = null; // createRectOverlay の返り値

function initCover(deps) {
  ui = deps;
  overlay = createRectOverlay({
    ui: deps,
    boxClass: "cover-box",
    tool: "cover",
    listRpc: "coverList",
    listKey: "covers",
    updateRpc: "updateCover",
    getSel: function () { return S.coverSel; },
    setSel: function (id) { S.coverSel = id; },
    getDrag: function () { return S.coverDrag; },
    setDrag: function (d) { S.coverDrag = d; },
    onSelect: syncTextInput,
  });
}

/** 選んでいる上書きの語を入力欄へ。未選択 (`item === null`) なら「次に置く語」へ戻す */
function syncTextInput(item) {
  var input = document.getElementById("cover-text"); if (!input) return;
  input.value = item ? item.text : S.coverText;
}

function drawCoverOverlay(host) { return overlay.draw(host); }
function installCoverDrag(host) { return overlay.installDrag(host); }
function clearCoverSel() { overlay.clearSel(); }

/** 入力欄の確定 (Enter / change)。上書きを選んでいれば選択中の要素の語だけを変え、
 *  `S.coverText` (次に置く語) には触れない。未選択なら次に置く語を確定する。
 *  (選択中の編集で `S.coverText` を書き換えると、選択を解いたあとに置く上書きへ
 *  編集中の語が紛れ込む — `input` リスナーの選択有無ガードと対で守る) */
async function commitCoverText(text) {
  if (S.coverSel === null) { S.coverText = text; return; }
  var pg = ui.pageOf();
  var res = await ui.rpc("coverList", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
  var cur = (res.covers || []).find(function (c) { return c.elId === S.coverSel; });
  if (!cur || cur.text === text) return;
  await ui.rpc("updateCover", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elId: S.coverSel, text: text });
  await ui.afterEdit();
}

export { initCover, drawCoverOverlay, installCoverDrag, commitCoverText, clearCoverSel };
