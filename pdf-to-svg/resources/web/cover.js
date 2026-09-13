// =============================================================================
// cover.js — 手順 3「上書き」ツールのオーバーレイ (移動・角ハンドル伸縮・置換語の変更)
// =============================================================================
// 置いた上書きは `coverList` RPC が返す矩形をモデルの正として HTML の箱で重ね、ドラッグ中は
// 箱だけを動かし、mouseup の 1 回だけ `updateCover` を送る (`figure.js` の採用矩形と同じ流儀)。
// 矩形操作のヘルパ (`copyRect` / `pageSizeOf` / `clampToPage` / `placeRect` / `MIN_SIZE_PT` /
// `resizeFromPointer` / `CORNER_HANDLES_HTML`) は手順 4 の採用矩形と同じ流儀なので `geometry.js`
// から共有して読む。
import { clientToPage, copyRect, pageSizeOf, clampToPage, placeRect, MIN_SIZE_PT, resizeFromPointer, CORNER_HANDLES_HTML } from "./geometry.js";
import { S } from "./state.js";

let ui = null; // { rpc, afterEdit, pageOf } を app.js が注入する

function initCover(deps) { ui = deps; }

/** 上書きの選択を解く。入力欄を「次に置く語」(`S.coverText`) へ戻す。選択解除の経路
 *  (ツール切替・空白クリック・ページ移動・選択中の要素が消えた等) をここへ一元化し、
 *  選択中に編集した語が `S.coverText` へ紛れ込んだまま入力欄に残らないようにする。 */
function clearCoverSel() {
  S.coverSel = null;
  var input = document.getElementById("cover-text");
  if (input) input.value = S.coverText;
}

/** 手順 3 で上書きツールが選ばれている間だけ、ページ上の上書きを箱で重ねる。呼ぶたびに描き直す */
async function drawCoverOverlay(host) {
  host.querySelectorAll(".cover-box").forEach(function (b) { b.remove(); });
  if (S.phase !== 3 || S.tool !== "cover") { clearCoverSel(); return; }
  var svgEl = host.querySelector("svg"); if (!svgEl) return;
  var pg = ui.pageOf();
  var res = await ui.rpc("coverList", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
  if (host.querySelector("svg") !== svgEl) return; // 取得中にページが変わった
  var covers = res.covers || [];
  if (S.coverSel !== null && !covers.some(function (c) { return c.elId === S.coverSel; })) clearCoverSel();
  covers.forEach(function (c) {
    var box = document.createElement("div");
    box.className = "cover-box" + (c.elId === S.coverSel ? " sel" : "");
    box.dataset.elId = c.elId;
    box.innerHTML = CORNER_HANDLES_HTML;
    placeRect(box, c.rect, svgEl, host);
    box.querySelectorAll(".h").forEach(function (h) {
      h.addEventListener("mousedown", function (e) {
        e.stopPropagation(); e.preventDefault();
        S.coverDrag = { mode: "resize", elId: c.elId, rect: copyRect(c.rect), orig: copyRect(c.rect), corner: h.dataset.corner, box: box, moved: false, text: c.text };
      });
    });
    box.addEventListener("mousedown", function (e) {
      e.stopPropagation(); e.preventDefault();
      S.coverDrag = { mode: "move", elId: c.elId, rect: copyRect(c.rect), orig: copyRect(c.rect), origin: { x: e.clientX, y: e.clientY }, box: box, moved: false, text: c.text };
    });
    box.addEventListener("click", function (e) { e.stopPropagation(); });
    host.appendChild(box);
  });
  syncTextInput(covers);
}

/** 選んでいる上書きの語を入力欄へ (未選択なら利用者の入力をそのまま残す) */
function syncTextInput(covers) {
  var input = document.getElementById("cover-text"); if (!input) return;
  var sel = covers.find(function (c) { return c.elId === S.coverSel; });
  if (sel) { input.value = sel.text; }
}

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

/** 移動・伸縮のドラッグ。起動時に一度だけ張る (多重登録防止) */
function installCoverDrag(host) {
  window.addEventListener("mousemove", function (e) {
    var d = S.coverDrag; if (!d) return;
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    var sz = pageSizeOf(svgEl);
    d.moved = true;
    if (d.mode === "move") {
      var a = clientToPage(svgEl, d.origin.x, d.origin.y);
      var b = clientToPage(svgEl, e.clientX, e.clientY);
      var moved = { x: d.orig.x + (b.x - a.x), y: d.orig.y + (b.y - a.y), w: d.orig.w, h: d.orig.h };
      // 大きさを保ったままページ内へ収める
      moved.x = Math.max(0, Math.min(moved.x, sz.w - moved.w));
      moved.y = Math.max(0, Math.min(moved.y, sz.h - moved.h));
      d.rect = moved;
    } else {
      d.rect = resizeFromPointer(svgEl, d, e.clientX, e.clientY);
    }
    placeRect(d.box, d.rect, svgEl, host);
  });
  window.addEventListener("mouseup", async function () {
    var d = S.coverDrag; if (!d) return;
    S.coverDrag = null;
    S.coverSel = d.elId;
    if (!d.moved) {
      // クリック = 選択だけ。`coverList` の再取得 (RPC 往復) を待って反映すると、その間に
      // 利用者が入力欄へ打ち始めた語を `syncTextInput` が巻き戻してしまう (往復の完了が
      // 入力より遅れて着く競合)。選ぶだけなら mousedown 時点で拾った値で足りるので、
      // 待たずに即時反映する (矩形・見た目は据え置きのままなので再取得も不要)。
      host.querySelectorAll(".cover-box").forEach(function (b) { b.classList.toggle("sel", b.dataset.elId === String(d.elId)); });
      var input = document.getElementById("cover-text");
      if (input) input.value = d.text;
      return;
    }
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    var sz = pageSizeOf(svgEl);
    var r = clampToPage(d.rect, sz.w, sz.h);
    if (r.w < MIN_SIZE_PT || r.h < MIN_SIZE_PT) { await drawCoverOverlay(host); return; }
    if (rectsNearlyEqual(r, d.orig)) {
      // `mousemove` は 1px のジッターでも `d.moved` を立てるため、結果の矩形が元と
      // 実質同じならクリック扱いにして `updateCover` を送らない。送ると変化の無い
      // 1 段が Undo スタックへ積まれ、次の Ctrl+Z が「何も起きない」ように見える。
      await drawCoverOverlay(host);
      return;
    }
    var pg = ui.pageOf();
    await ui.rpc("updateCover", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elId: d.elId, rect: r });
    await ui.afterEdit();
  });
}

// ジッター判定のしきい値 (ページ座標 pt)。通常の表示倍率ではおおむね画面 1px 相当で、
// 意図した伸縮・移動 (数 pt 以上動く) までは無視しない。
var JITTER_EPS_PT = 1;

/** 2 矩形が `JITTER_EPS_PT` 未満の差しか無いか (クリックの手ブレとみなせるか) */
function rectsNearlyEqual(a, b) {
  return (
    Math.abs(a.x - b.x) < JITTER_EPS_PT && Math.abs(a.y - b.y) < JITTER_EPS_PT &&
    Math.abs(a.w - b.w) < JITTER_EPS_PT && Math.abs(a.h - b.h) < JITTER_EPS_PT
  );
}

export { initCover, drawCoverOverlay, installCoverDrag, commitCoverText, clearCoverSel };
