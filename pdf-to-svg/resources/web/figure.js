// =============================================================================
// figure.js — グレーモード (手順 4) のレール・候補矩形オーバーレイ・ハンドル操作
// =============================================================================
// 状態は `state.js` の `S.figCand` / `S.figSel` を直接読み書きし、再描画だけは
// `initFigure` で注入された `render` (app.js) へ委譲する。
// オーバーレイは SVG の外 (host 直下の div) に置くので、`bakeSvg` 相当の書き出しには
// 混ざらない (書き出しはサーバの `exportSvg` が clip を受けて別生成する)。
// 矩形操作のヘルパ (`copyRect` / `pageSizeOf` / `clampToPage` / `placeRect` / `MIN_SIZE_PT`) は
// 手順 3 の上書きオーバーレイ (`cover.js`) と共有するため `geometry.js` にある。
import { esc } from "./dom.js";
import { clientToPage, rectIoU, copyRect, pageSizeOf, clampToPage, placeRect, MIN_SIZE_PT, resizeByCorner, CORNER_HANDLES_HTML } from "./geometry.js";
import { S, figKey, figSelOf, figSelPeek, figCount, adoptedFigures } from "./state.js";

var ui = { render: function () {} };
function initFigure(deps) { ui = deps; }

// 採用済みと大きく重なる候補は隠す。伸縮しても隠れたまま、採用を外せば戻る
// (等値比較だと伸縮で採用側の座標がずれた瞬間に元候補が再出現し、二重書き出しにつながるため)。
var CAND_HIDE_IOU = 0.5;

/** 左レール: ページ一覧 + 候補/採用のバッジ。クリックでページ移動 */
function buildFigRail(navId) {
  var html = '<div class="pl-head"><div class="pl-title">全 <b>' + S.TOTAL + "</b> ページ　採用 <b>" + figCount() + "</b> 図</div></div>";
  html += '<div class="pl-body">';
  var g = 0;
  S.FILES.forEach(function (f) {
    html += '<div class="pl-file"><span class="fname">' + esc(f.name) + "</span></div>";
    for (var p = 0; p < f.pages; p++) {
      var gg = g + p;
      var pg = S.PAGES[gg]; if (!pg) continue; // ページ列を再取得中などで一時的に欠けることがある (figSelPeek と同じ流儀)
      var n = figSelPeek(gg).length;
      var cand = (S.figCand[figKey(pg)] || []).length;
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

/** 右ペイン「採用した図」一覧: ファイル名 (書き出し予定名) と pt 寸法。クリックでそのページへ移動する。
 *  `adoptedFigures()` は `S.expMode` に関係なく全ページ分を返すので、一覧は書き出し範囲の
 *  設定を変えても変わらない (範囲はあくまで書き出し対象を絞るだけ)。 */
function buildFigSelist(elId) {
  var el = document.getElementById(elId); if (!el) return;
  var list = adoptedFigures();
  if (!list.length) {
    el.innerHTML = '<div class="empty">まだ図を採用していません。ページ上の候補をクリックしてください。</div>';
    return;
  }
  el.innerHTML = list.map(function (it) {
    var f = S.FILES[it.fileIndex];
    var stem = f ? f.name.replace(/\.pdf$/i, "") : "";
    var name = stem + "_p" + (it.pageInFile + 1) + "_fig" + it.figIndex + "_gray.svg";
    var g = (S.FILE_START[it.fileIndex] || 0) + it.pageInFile;
    return '<div class="serow" data-g="' + g + '"><span class="sw"></span><span class="fn">' + esc(name) +
      '</span><span class="dim">' + Math.round(it.rect.w) + " × " + Math.round(it.rect.h) + "</span></div>";
  }).join("");
  el.querySelectorAll("[data-g]").forEach(function (row) {
    row.addEventListener("click", function () { S.page = +row.dataset.g; ui.render(); });
  });
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
    // `tabindex=0` の div のため Enter/Space のキーボード起動を自前で足す (dropzone と同じ流儀。app.js 参照)。
    box.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.stopPropagation(); sel.push(copyRect(r)); ui.render(); }
    });
    host.appendChild(box);
  });
  sel.forEach(function (r, i) {
    var box = document.createElement("div");
    box.className = "fig-cand sel"; box.dataset.sel = i;
    box.innerHTML = '<span class="tag">採用 ' + (i + 1) + " ・ " + Math.round(r.w) + " × " + Math.round(r.h) + " pt</span>" +
      '<button type="button" class="del" title="採用を外す">×</button>' + CORNER_HANDLES_HTML;
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
    // resize: 掴んだ角を動かし、反対の角は固定する。動かす側の点はページ内へクランプする
    // (clientToPage はページの外へも線形に外挿するため、そのままだとサーバの clip 検証に落ちる)。
    var p = clientToPage(svgEl, e.clientX, e.clientY);
    var sz = pageSizeOf(svgEl);
    p.x = Math.max(0, Math.min(p.x, sz.w));
    p.y = Math.max(0, Math.min(p.y, sz.h));
    // `d.rect` は採用矩形そのもの (`figSelPeek` が同一性で箱を引く) なので、置き換えず中身を書く。
    Object.assign(d.rect, resizeByCorner(d.orig, d.corner, p));
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
    var raw = { x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(a.x - b.x), h: Math.abs(a.y - b.y) };
    var sz = pageSizeOf(svgEl);
    var r = clampToPage(raw, sz.w, sz.h); // ページ外までドラッグしても採用矩形はページ内に収める
    if (r.w < MIN_SIZE_PT || r.h < MIN_SIZE_PT) return;
    figSelOf(S.page).push(r);
    ui.render();
  });
}

export { initFigure, buildFigRail, buildFigSelist, drawFigOverlay, installFigDrag };
