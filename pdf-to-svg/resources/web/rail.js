// =============================================================================
// rail.js — 左ページレール (一覧・絞り込み・件数タグ) の描画と配線
// =============================================================================
// 状態は `state.js` の `S` を読み、状態変更後の再描画だけは `initRail` で注入された
// `render` (app.js) へ委譲する。レールは手順 2 (`#pagenav`) と手順 3 (`#pagenav-3`) で
// 同一実装を共有する。ページの確認状態は持たず、行のタグは件数 (`S.matches2` / `S.edits3`)
// から毎回描く。

import { esc, svg } from "./dom.js";
import { S, railPages, matchTotals, editTotals } from "./state.js";
import { fileIcon, chevD } from "./icons.js";

var FILTERS = {
  2: [{ v: "matched", t: "辞書に一致したページだけ" }, { v: "all", t: "すべてのページ" }],
  3: [{ v: "all", t: "すべてのページ" }, { v: "edited", t: "編集したページだけ" }],
};
var EMPTY = { 2: "辞書に一致したページはありません", 3: "編集したページはありません" };

// app.js から注入される再描画フック ({ render })
var ui = { render: function () {} };
function initRail(deps) { ui = deps; }

/** 行の右端のタグ。0 の項目は省き、すべて 0 なら出さない */
function rowTag(g) {
  var parts = [];
  if (S.phase === 2) {
    var m = S.matches2[g] || { applied: 0, pending: 0 };
    if (m.applied) parts.push("置換 " + m.applied);
    if (m.pending) parts.push("未置換 " + m.pending);
  } else {
    var e = S.edits3[g] || { removed: 0, borders: 0, covers: 0 };
    if (e.removed) parts.push("削除 " + e.removed);
    if (e.borders) parts.push("枠線 " + e.borders);
    if (e.covers) parts.push("上書き " + e.covers);
  }
  return parts.length ? '<span class="tg t-count">' + parts.join(" ・ ") + "</span>" : "";
}

function railTitle() {
  if (S.phase === 2) {
    var t = matchTotals();
    return "全 <b>" + S.TOTAL + "</b> ページ　辞書に一致 <b>" + t.pages + "</b> ページ" +
      (t.scanned ? "　対象外 <b>" + t.scanned + "</b>" : "");
  }
  return "全 <b>" + S.TOTAL + "</b> ページ　編集したページ <b>" + editTotals().pages + "</b>";
}

function buildRail(navId) {
  var filt = S.filterFor[S.phase];
  var visible = railPages(S.phase);
  var html = '<div class="pl-head"><div class="pl-title">' + railTitle() + "</div>";
  html += '<select class="pl-filter">' + FILTERS[S.phase].map(function (f) {
    return '<option value="' + f.v + '"' + (f.v === filt ? " selected" : "") + ">" + f.t + "</option>";
  }).join("") + "</select></div>";
  html += '<div class="pl-body">';
  var anyRow = false;
  S.FILES.forEach(function (f, fi) {
    var start = S.FILE_START[fi] || 0;
    var idxs = visible.filter(function (g) { return g >= start && g < start + f.pages; });
    if (idxs.length === 0) return;
    anyRow = true;
    var key = S.phase + ":" + fi; var isColl = !!S.collapsed[key];
    html += '<div class="pl-file' + (isColl ? " collapsed" : "") + '">' +
      '<span class="fname" data-fcoll="' + fi + '">' + svg(fileIcon, 13, undefined, "fic") + esc(f.name) + "</span>" +
      '<span class="fcount">' + idxs.length + "</span>" +
      '<span class="fchev" data-fcoll="' + fi + '">' + svg(chevD, 15) + "</span></div>";
    if (!isColl) {
      idxs.forEach(function (g) {
        var n = g - start + 1;
        html += '<div class="pg-row2' + (g === S.page ? " current" : "") + '" data-g="' + g + '">' +
          '<span class="dot">' + n + '</span><span class="lbl">' + n + " ページ</span>" + rowTag(g) + "</div>";
      });
    }
  });
  if (!anyRow) html += '<div class="empty-note" style="padding:48px 16px"><div class="et">' + EMPTY[S.phase] + "</div></div>";
  html += "</div>";
  var nav = document.getElementById(navId);
  nav.innerHTML = html;
  nav.querySelector(".pl-filter").addEventListener("change", function () { S.filterFor[S.phase] = this.value; ui.render(); });
  nav.querySelectorAll("[data-fcoll]").forEach(function (el) {
    el.addEventListener("click", function (e) {
      e.stopPropagation(); var k = S.phase + ":" + el.dataset.fcoll; S.collapsed[k] = !S.collapsed[k]; ui.render();
    });
  });
  nav.querySelectorAll(".pg-row2").forEach(function (r) {
    r.addEventListener("click", function () { S.page = +r.dataset.g; ui.render(); });
  });
}

export { initRail, buildRail };
