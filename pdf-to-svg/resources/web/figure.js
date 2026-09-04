// =============================================================================
// figure.js — グレーモード (手順 4) のレール・候補矩形オーバーレイ・ハンドル操作
// =============================================================================
// 状態は `state.js` の `S.figCand` / `S.figSel` を直接読み書きし、再描画だけは
// `initFigure` で注入された `render` (app.js) へ委譲する。
// オーバーレイは SVG の外 (host 直下の div) に置くので、`bakeSvg` 相当の書き出しには
// 混ざらない (書き出しはサーバの `exportSvg` が clip を受けて別生成する)。
import { esc } from "./dom.js";
import { clientToPage, rectIoU } from "./geometry.js";
import { S, figKey, figSelOf, figSelPeek, figCount } from "./state.js";

var ui = { render: function () {} };
function initFigure(deps) { ui = deps; }

var MIN_SIZE_PT = 4; // これ未満の矩形は誤クリックとみなして作らない
// 採用済みと大きく重なる候補は隠す。伸縮しても隠れたまま、採用を外せば戻る
// (等値比較だと伸縮で採用側の座標がずれた瞬間に元候補が再出現し、二重書き出しにつながるため)。
var CAND_HIDE_IOU = 0.5;

function copyRect(r) { return { x: r.x, y: r.y, w: r.w, h: r.h }; }

/** 左レール: ページ一覧 + 候補/採用のバッジ。クリックでページ移動 */
function buildFigRail(navId) {
  var html = '<div class="pl-head"><div class="pl-title">全 <b>' + S.TOTAL + "</b> ページ　採用 <b>" + figCount() + "</b> 図</div></div>";
  html += '<div class="pl-body">';
  var g = 0;
  S.FILES.forEach(function (f) {
    html += '<div class="pl-file"><span class="fname">' + esc(f.name) + "</span></div>";
    for (var p = 0; p < f.pages; p++) {
      var gg = g + p;
      var n = figSelPeek(gg).length;
      var cand = (S.figCand[figKey(S.PAGES[gg])] || []).length;
      var cls = n ? "done" : (cand ? "pending" : "none");
      var tag = n ? '<span class="tg t-done">採用 ' + n + "</span>" : (cand ? '<span class="tg t-pending">候補</span>' : "");
      html += '<div class="pg-row2 ' + cls + (gg === S.page ? " current" : "") + '" data-g="' + gg + '">' +
        '<span style="width:17px;flex:none"></span><span class="dot">' + (p + 1) + '</span><span class="lbl">' + (p + 1) + " ページ</span>" + tag + "</div>";
    }
    g += f.pages;
  });
  html += "</div>";
  var nav = document.getElementById(navId);
  nav.innerHTML = html;
  nav.querySelectorAll("[data-g]").forEach(function (row) {
    row.addEventListener("click", function () { S.page = +row.dataset.g; ui.render(); });
  });
}

/** ページ座標 (pt) の矩形を host 相対の px に置く */
function placeRect(box, r, svgEl, host) {
  var sr = svgEl.getBoundingClientRect(), hb = host.getBoundingClientRect(), vb = svgEl.viewBox.baseVal;
  var sx = sr.width / vb.width, sy = sr.height / vb.height;
  box.style.left = ((r.x - vb.x) * sx + sr.left - hb.left) + "px";
  box.style.top = ((r.y - vb.y) * sy + sr.top - hb.top) + "px";
  box.style.width = (r.w * sx) + "px";
  box.style.height = (r.h * sy) + "px";
}

/** 候補 (点線) と採用 (実線) を host に重ねる。呼ぶたびに全部描き直す */
function drawFigOverlay(host) {
  host.querySelectorAll(".fig-cand").forEach(function (b) { b.remove(); });
  var svgEl = host.querySelector("svg"); if (!svgEl || !S.PAGES[S.page]) return;
  var sel = figSelOf(S.page);
  var cands = S.figCand[figKey(S.PAGES[S.page])] || [];
  cands.forEach(function (r, i) {
    if (sel.some(function (s) { return rectIoU(s, r) >= CAND_HIDE_IOU; })) return; // 採用済みは実線側で描く
    var box = document.createElement("div");
    box.className = "fig-cand"; box.setAttribute("role", "button"); box.tabIndex = 0;
    box.innerHTML = '<span class="tag">候補 ' + (i + 1) + "</span>";
    placeRect(box, r, svgEl, host);
    box.addEventListener("click", function (e) { e.stopPropagation(); sel.push(copyRect(r)); ui.render(); });
    host.appendChild(box);
  });
  sel.forEach(function (r, i) {
    var box = document.createElement("div");
    box.className = "fig-cand sel"; box.dataset.sel = i;
    box.innerHTML = '<span class="tag">採用 ' + (i + 1) + " ・ " + Math.round(r.w) + " × " + Math.round(r.h) + " pt</span>" +
      '<button type="button" class="del" title="採用を外す">×</button>' +
      '<span class="h nw" data-corner="nw"></span><span class="h ne" data-corner="ne"></span>' +
      '<span class="h sw" data-corner="sw"></span><span class="h se" data-corner="se"></span>';
    placeRect(box, r, svgEl, host);
    box.querySelector(".del").addEventListener("click", function (e) { e.stopPropagation(); sel.splice(i, 1); ui.render(); });
    box.querySelectorAll(".h").forEach(function (h) {
      h.addEventListener("mousedown", function (e) {
        e.stopPropagation(); e.preventDefault();
        S.figDrag = { mode: "resize", rect: r, corner: h.dataset.corner, orig: copyRect(r) };
      });
    });
    box.addEventListener("click", function (e) { e.stopPropagation(); });
    host.appendChild(box);
  });
}

/** 空白ドラッグで矩形追加、角ハンドルで伸縮。起動時に一度だけ張る (多重登録防止) */
function installFigDrag(host) {
  host.addEventListener("mousedown", function (e) {
    if (S.phase !== 4 || !S.gray) return;
    if (e.target.closest(".fig-cand")) return;
    if (!host.querySelector("svg")) return;
    var rubber = document.createElement("div");
    rubber.className = "crop-rubber";
    host.appendChild(rubber);
    S.figDrag = { mode: "add", origin: { x: e.clientX, y: e.clientY }, rubber: rubber };
    e.preventDefault();
  });
  window.addEventListener("mousemove", function (e) {
    var d = S.figDrag; if (!d) return;
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    if (d.mode === "add") {
      var hb = host.getBoundingClientRect();
      var x1 = Math.min(d.origin.x, e.clientX), y1 = Math.min(d.origin.y, e.clientY);
      var x2 = Math.max(d.origin.x, e.clientX), y2 = Math.max(d.origin.y, e.clientY);
      d.rubber.style.left = (x1 - hb.left) + "px"; d.rubber.style.top = (y1 - hb.top) + "px";
      d.rubber.style.width = (x2 - x1) + "px"; d.rubber.style.height = (y2 - y1) + "px";
      return;
    }
    // resize: 掴んだ角を動かし、反対の角は固定する
    var p = clientToPage(svgEl, e.clientX, e.clientY);
    var o = d.orig, c = d.corner;
    var left = c.indexOf("w") >= 0 ? p.x : o.x, right = c.indexOf("e") >= 0 ? p.x : o.x + o.w;
    var top = c.indexOf("n") >= 0 ? p.y : o.y, bottom = c.indexOf("s") >= 0 ? p.y : o.y + o.h;
    d.rect.x = Math.min(left, right); d.rect.y = Math.min(top, bottom);
    d.rect.w = Math.max(MIN_SIZE_PT, Math.abs(right - left)); d.rect.h = Math.max(MIN_SIZE_PT, Math.abs(bottom - top));
    var box = host.querySelector('.fig-cand.sel[data-sel="' + figSelPeek(S.page).indexOf(d.rect) + '"]');
    if (box) placeRect(box, d.rect, svgEl, host);
  });
  window.addEventListener("mouseup", function (e) {
    var d = S.figDrag; if (!d) return;
    S.figDrag = null;
    if (d.mode === "resize") { ui.render(); return; }
    d.rubber.remove();
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    var a = clientToPage(svgEl, d.origin.x, d.origin.y);
    var b = clientToPage(svgEl, e.clientX, e.clientY);
    var w = Math.abs(a.x - b.x), h = Math.abs(a.y - b.y);
    if (w < MIN_SIZE_PT || h < MIN_SIZE_PT) return;
    figSelOf(S.page).push({ x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: w, h: h });
    ui.render();
  });
}

export { initFigure, buildFigRail, drawFigOverlay, installFigDrag };
