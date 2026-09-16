// =============================================================================
// border.js — 手順 3「枠線」ツールのオーバーレイ (色・太さの同期だけを持つ)
// =============================================================================
// 箱の描画・選択・移動・角ハンドル伸縮は `rect-overlay.js` と共有する。ここが持つのは
// 「枠線固有の部分」= どの一覧 RPC を引くか (`borderList`) と、選んだとき色・太さの入力欄に
// 何を映すか、そして入力欄の確定 (`updateBorder {color|width}`) だけ。
import { createRectOverlay } from "./rect-overlay.js";
import { S } from "./state.js";

let ui = null;      // { rpc, afterEdit, pageOf } を app.js が注入する
let overlay = null; // createRectOverlay の返り値

function initBorder(deps) {
  ui = deps;
  overlay = createRectOverlay({
    ui: deps,
    boxClass: "border-box",
    tool: "border",
    listRpc: "borderList",
    listKey: "borders",
    updateRpc: "updateBorder",
    getSel: function () { return S.borderSel; },
    setSel: function (id) { S.borderSel = id; },
    getDrag: function () { return S.borderDrag; },
    setDrag: function (d) { S.borderDrag = d; },
    onSelect: syncStyleInputs,
  });
}

/** 選んでいる枠線の色・太さを入力欄へ。未選択 (`item === null`) なら「次に置く枠線」の値へ戻す */
function syncStyleInputs(item) {
  var color = document.getElementById("border-color");
  var width = document.getElementById("border-width");
  if (color) color.value = item ? item.color : S.borderColor;
  if (width) width.value = String(item ? item.width : S.borderWidth);
}

function drawBorderOverlay(host) { return overlay.draw(host); }
function installBorderDrag(host) { return overlay.installDrag(host); }
function clearBorderSel() { overlay.clearSel(); }

/** 色・太さの確定。枠線を選んでいれば選択中の枠線だけを変え、「次に置く枠線」の値
 *  (`S.borderColor` / `S.borderWidth`) には触れない。未選択なら次に置く値を確定する。
 *  (選択中の編集で次に置く値を書き換えると、選択を解いたあとに置く枠線へ編集中の値が
 *  紛れ込む — `cover.js` の置換語と同じ守り方) */
async function commitBorderStyle(patch) {
  if (S.borderSel === null) {
    if (patch.color !== undefined) S.borderColor = patch.color;
    if (patch.width !== undefined) S.borderWidth = patch.width;
    return;
  }
  var pg = ui.pageOf();
  var res = await ui.rpc("borderList", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
  var cur = (res.borders || []).find(function (b) { return b.elId === S.borderSel; });
  if (!cur) return;
  if (patch.color !== undefined && cur.color === patch.color) return;
  if (patch.width !== undefined && cur.width === patch.width) return;
  var args = { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elId: S.borderSel };
  if (patch.color !== undefined) args.color = patch.color;
  if (patch.width !== undefined) args.width = patch.width;
  await ui.rpc("updateBorder", args);
  await ui.afterEdit();
}

export { initBorder, drawBorderOverlay, installBorderDrag, commitBorderStyle, clearBorderSel };
