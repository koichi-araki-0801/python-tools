// =============================================================================
// rail.js — 左ページレール (一覧・フィルタ・一括操作) の描画と配線
// =============================================================================
// 状態は `state.js` の `S` を直接読み書きし、状態変更後の再描画と「次へ」判定だけは
// `initRail` で注入された `render` / `tryNext` (app.js の関数) へ委譲する。
// レールは手順2 (`#pagenav`) と手順3 (`#pagenav-3`) で同一実装を共有する。

import { esc, svg } from "./dom.js";
import { S, counts, pass, statusArr, selSet, selKeys, selCount, clearSel } from "./state.js";
import { fileIcon, chevD, checkD, ckMark, checkDot, skipDot } from "./icons.js";

var FILTERS = [
  { v: "pending", t: "要確認" }, { v: "all", t: "すべて" },
  { v: "reviewed", t: "確認済み" }, { v: "skipped", t: "スキップ" }, { v: "none", t: "変更なし" },
];
var STAT = { reviewed: "確認済み", skipped: "スキップ", pending: "要確認", none: "変更なし" };

// app.js から注入される再描画/遷移フック ({ render, tryNext })
var ui = { render: function () {}, tryNext: function () {} };
function initRail(deps) { ui = deps; }

function buildRail(navId) {
  var arr = statusArr(); var filt = S.filterFor[S.phase]; var sel = selSet(); var c = counts(arr);
  var html = "";
  html += '<div class="pl-head">';
  html += '<div class="pl-title">全 <b>' + S.TOTAL + "</b> ページ　要確認 <b>" + c.pend + "</b></div>";
  html += '<select class="pl-filter">' + FILTERS.map(function (f) {
    return '<option value="' + f.v + '"' + (f.v === filt ? " selected" : "") + ">" + f.t + "</option>"; }).join("") + "</select>";
  var visSelectable = [];
  S.PAGES.forEach(function (pg, g) { if (pass(arr[g], filt) && arr[g] !== "none") visSelectable.push(g); });
  var allSel = visSelectable.length > 0 && visSelectable.every(function (g) { return sel[g]; });
  html += '<label class="pl-all"><span class="ck' + (allSel ? " on" : "") + '" data-all="1">' + (allSel ? ckMark : "") + "</span>表示中をすべて選択</label>";
  html += '<button class="pl-skipall" data-skipall="1">' + svg('<path d="M9 8l4 4-4 4M15 8v8"/>', 15, 1.9) + "未確認をまとめてスキップ</button>";
  if (S.PAGES.length) {
    var curFile = S.FILES[S.PAGES[S.page].fileIndex];
    html += '<div class="pl-range"><div class="rg-lab">範囲で指定（' + esc(curFile.name) + "）</div>" +
      '<div class="rg-row"><input class="rg-from" type="number" min="1" max="' + curFile.pages + '" placeholder="1"> 〜 ' +
      '<input class="rg-to" type="number" min="1" max="' + curFile.pages + '" placeholder="' + curFile.pages + '"> ページを</div>' +
      '<div class="rg-row"><select class="rg-act"><option value="skipped">スキップ</option><option value="reviewed">確認済みに</option></select>' +
      '<button class="rg-go" data-rg="1">適用</button></div></div>';
  }
  html += "</div>";
  if (selCount() > 0) {
    html += '<div class="pl-selbar"><span><b>' + selCount() + "</b> 件を選択中</span><div class=\"selrow\">" +
      '<button data-bulk="done">確認済み</button><button data-bulk="skip">スキップ</button><button data-bulk="clear">解除</button></div></div>';
  }
  html += '<div class="pl-body">';
  var g = 0, anyRow = false;
  S.FILES.forEach(function (f, fi) {
    var idxs = [];
    for (var p = 0; p < f.pages; p++) { var gg = g + p; if (pass(arr[gg], filt)) idxs.push(gg); }
    if (idxs.length === 0) { g += f.pages; return; }
    anyRow = true;
    var key = S.phase + ":" + fi; var isColl = !!S.collapsed[key];
    var selectable = idxs.filter(function (i) { return arr[i] !== "none"; });
    var fileSel = selectable.length > 0 && selectable.every(function (i) { return sel[i]; });
    html += '<div class="pl-file' + (isColl ? " collapsed" : "") + '">' +
      '<span class="ck' + (fileSel ? " on" : "") + '" data-fileck="' + fi + '">' + (fileSel ? ckMark : "") + "</span>" +
      '<span class="fname" data-fcoll="' + fi + '">' + svg(fileIcon, 13, undefined, "fic") + esc(f.name) + "</span>" +
      '<span class="fcount">' + idxs.length + "</span>" +
      '<span class="fchev" data-fcoll="' + fi + '">' + svg(chevD, 15) + "</span></div>";
    if (!isColl) {
      idxs.forEach(function (gg) {
        var off = gg - g; var st = arr[gg];
        var cls = st === "reviewed" ? "done" : (st === "skipped" ? "skipped" : (st === "pending" ? "pending" : "none"));
        var dot = st === "reviewed" ? checkDot : (st === "skipped" ? skipDot : (off + 1));
        var ckbox = st !== "none"
          ? '<span class="ck row-ck' + (sel[gg] ? " on" : "") + '" data-ck="' + gg + '">' + (sel[gg] ? ckMark : "") + "</span>"
          : '<span style="width:17px;flex:none"></span>';
        html += '<div class="pg-row2 ' + cls + (gg === S.page ? " current" : "") + '" data-g="' + gg + '">' +
          ckbox + '<span class="dot">' + dot + '</span><span class="lbl">' + (off + 1) + " ページ</span>" +
          '<span class="tg t-' + cls + '">' + STAT[st] + "</span></div>";
      });
    }
    g += f.pages;
  });
  if (!anyRow) html += '<div class="empty-note" style="padding:48px 16px"><div class="ei">' + svg('<path d="' + checkD + '"/>', 24, 2) + '</div><div class="et">このフィルタに該当するページはありません</div></div>';
  html += "</div>";
  document.getElementById(navId).innerHTML = html;
  wireRail(navId, visSelectable);
}

function wireRail(navId, visSelectable) {
  var nav = document.getElementById(navId);
  var arr = statusArr(); var sel = selSet();
  nav.querySelector(".pl-filter").addEventListener("change", function () { S.filterFor[S.phase] = this.value; ui.render(); });
  nav.querySelector("[data-all]").addEventListener("click", function () {
    var allSel = visSelectable.length > 0 && visSelectable.every(function (g) { return sel[g]; });
    visSelectable.forEach(function (g) { if (allSel) delete sel[g]; else sel[g] = true; });
    ui.render();
  });
  nav.querySelector("[data-skipall]").addEventListener("click", function () {
    for (var g = 0; g < S.TOTAL; g++) if (arr[g] === "pending") arr[g] = "skipped";
    ui.tryNext(); // 全スキップ後はそのまま次のステップへ進む
  });
  var rg = nav.querySelector("[data-rg]");
  if (rg) rg.addEventListener("click", function () {
    var fi = S.PAGES[S.page].fileIndex; var start = S.FILE_START[fi]; var fp = S.FILES[fi].pages;
    var from = parseInt(nav.querySelector(".rg-from").value, 10) || 1;
    var to = parseInt(nav.querySelector(".rg-to").value, 10) || fp;
    if (from > to) { var t = from; from = to; to = t; }
    from = Math.max(1, Math.min(fp, from)); to = Math.max(1, Math.min(fp, to));
    var act = nav.querySelector(".rg-act").value;
    for (var pp = from; pp <= to; pp++) { var gg = start + (pp - 1); if (arr[gg] !== "none") arr[gg] = act; }
    ui.render();
  });
  var selbar = nav.querySelector(".pl-selbar");
  if (selbar) selbar.querySelectorAll("[data-bulk]").forEach(function (b) {
    b.addEventListener("click", function () {
      var k = b.dataset.bulk;
      if (k === "clear") clearSel();
      else { selKeys().forEach(function (g) { arr[+g] = k === "done" ? "reviewed" : "skipped"; }); clearSel(); }
      ui.render();
    });
  });
  nav.querySelectorAll("[data-fileck]").forEach(function (el) {
    el.addEventListener("click", function (e) {
      e.stopPropagation();
      var fi = +el.dataset.fileck; var start = S.FILE_START[fi]; var idxs = [];
      for (var p = 0; p < S.FILES[fi].pages; p++) { var gg = start + p; if (pass(arr[gg], S.filterFor[S.phase]) && arr[gg] !== "none") idxs.push(gg); }
      var allSel = idxs.length > 0 && idxs.every(function (g) { return sel[g]; });
      idxs.forEach(function (g) { if (allSel) delete sel[g]; else sel[g] = true; });
      ui.render();
    });
  });
  nav.querySelectorAll("[data-fcoll]").forEach(function (el) {
    el.addEventListener("click", function (e) {
      e.stopPropagation(); S.collapsed[S.phase + ":" + el.dataset.fcoll] = !S.collapsed[S.phase + ":" + el.dataset.fcoll]; ui.render();
    });
  });
  nav.querySelectorAll(".row-ck").forEach(function (el) {
    el.addEventListener("click", function (e) {
      e.stopPropagation(); var g = +el.dataset.ck; if (sel[g]) delete sel[g]; else sel[g] = true; ui.render();
    });
  });
  nav.querySelectorAll(".pg-row2").forEach(function (r) {
    r.addEventListener("click", function () { S.page = +r.dataset.g; ui.render(); });
  });
}

export { initRail, buildRail };
