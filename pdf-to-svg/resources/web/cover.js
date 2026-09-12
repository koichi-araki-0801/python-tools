// =============================================================================
// cover.js — 手順 3「上書き」ツールのオーバーレイ (移動・角ハンドル伸縮・置換語の変更)
// =============================================================================
// 置いた上書きは `coverList` RPC が返す矩形をモデルの正として HTML の箱で重ね、ドラッグ中は
// 箱だけを動かし、mouseup の 1 回だけ `updateCover` を送る (`figure.js` の採用矩形と同じ流儀)。
// 矩形操作の純粋ヘルパ (`copyRect` / `pageSizeOf` / `clampToPage` / `placeRect` / `MIN_SIZE_PT`)
// は `figure.js` の採用矩形の実装とロジックが同一なので、複製せずそちらから読む。
import { clientToPage } from "./geometry.js";
import { S } from "./state.js";
import { copyRect, pageSizeOf, clampToPage, placeRect, MIN_SIZE_PT } from "./figure.js";

let ui = null; // { rpc, afterEdit, pageOf } を app.js が注入する

function initCover(deps) { ui = deps; }

/** 手順 3 で上書きツールが選ばれている間だけ、ページ上の上書きを箱で重ねる。呼ぶたびに描き直す */
async function drawCoverOverlay(host) {
  host.querySelectorAll(".cover-box").forEach(function (b) { b.remove(); });
  if (S.phase !== 3 || S.tool !== "cover") { S.coverSel = null; return; }
  var svgEl = host.querySelector("svg"); if (!svgEl) return;
  var pg = ui.pageOf();
  var res = await ui.rpc("coverList", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
  if (host.querySelector("svg") !== svgEl) return; // 取得中にページが変わった
  var covers = res.covers || [];
  if (S.coverSel !== null && !covers.some(function (c) { return c.elId === S.coverSel; })) S.coverSel = null;
  covers.forEach(function (c) {
    var box = document.createElement("div");
    box.className = "cover-box" + (c.elId === S.coverSel ? " sel" : "");
    box.dataset.elId = c.elId;
    box.innerHTML =
      '<span class="h nw" data-corner="nw"></span><span class="h ne" data-corner="ne"></span>' +
      '<span class="h sw" data-corner="sw"></span><span class="h se" data-corner="se"></span>';
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

/** 入力欄の確定 (Enter / change)。上書きを選んでいれば語を変え、未選択なら次に置く語にする */
async function commitCoverText(text) {
  S.coverText = text;
  if (S.coverSel === null) return;
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
      var p = clientToPage(svgEl, e.clientX, e.clientY);
      p.x = Math.max(0, Math.min(p.x, sz.w)); p.y = Math.max(0, Math.min(p.y, sz.h));
      var o = d.orig, c = d.corner;
      var left = c.indexOf("w") >= 0 ? p.x : o.x, right = c.indexOf("e") >= 0 ? p.x : o.x + o.w;
      var top = c.indexOf("n") >= 0 ? p.y : o.y, bottom = c.indexOf("s") >= 0 ? p.y : o.y + o.h;
      d.rect = { x: Math.min(left, right), y: Math.min(top, bottom), w: Math.max(MIN_SIZE_PT, Math.abs(right - left)), h: Math.max(MIN_SIZE_PT, Math.abs(bottom - top)) };
    }
    placeRect(d.box, d.rect, svgEl, host);
  });
  window.addEventListener("mouseup", async function () {
    var d = S.coverDrag; if (!d) return;
    S.coverDrag = null;
    S.coverSel = d.elId;
    if (!d.moved) {
      // クリック = 選択だけ。coverList の再取得 (RPC 往復) を待って反映すると、その間に
      // 利用者が入力欄へ打ち始めた語を syncTextInput が巻き戻してしまう (往復の完了が
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
    var pg = ui.pageOf();
    await ui.rpc("updateCover", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elId: d.elId, rect: r });
    await ui.afterEdit();
  });
}

export { initCover, drawCoverOverlay, installCoverDrag, commitCoverText };
