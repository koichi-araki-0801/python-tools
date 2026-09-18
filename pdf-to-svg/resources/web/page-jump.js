// =============================================================================
// page-jump.js — 「ページへ移動」(ファイル選択 + ページ番号 + 前後) の描画と配線
// =============================================================================
// 手順 2 (`#pgnav-2`) と手順 3 (`#pgnav-3`) が同じ関数から 1 つずつ生成する。レールの絞り込みに
// 出ていないページへも番号で直接移動できる。状態は `state.js` の `S.page` を書き、再描画は
// `initPageJump` で注入された `render` (app.js) へ委譲する。`resolveJump` は S を読まない
// 純粋関数で、単体テスト (`test/test_pdftosvg_page_jump_js.py`) が境界を固定する。

import { esc, svg } from "./dom.js";
import { S } from "./state.js";
import { chevL, chevD } from "./icons.js";

var ui = { render: function () {} };
function initPageJump(deps) { ui = deps; }

/** ファイル fileIndex のページ番号 value (1 始まりの文字列) を通し index にする。
 *  番号は 1〜そのファイルのページ数へ丸め、数字でなければ 1 とみなす。ファイルが無ければ -1 */
function resolveJump(files, fileStart, fileIndex, value) {
  var f = files[fileIndex]; if (!f) return -1;
  var n = parseInt(value, 10);
  if (!isFinite(n)) n = 1;
  n = Math.max(1, Math.min(f.pages, n));
  return (fileStart[fileIndex] || 0) + (n - 1);
}

function buildPageJump(hostId) {
  var host = document.getElementById(hostId); if (!host) return;
  var pg = S.PAGES[S.page]; if (!pg) { host.innerHTML = ""; return; }
  var f = S.FILES[pg.fileIndex];
  host.innerHTML =
    '<button type="button" class="pj-btn" data-pj="prev" title="前のページ"' + (S.page === 0 ? " disabled" : "") + ">" + svg(chevL, 16) + "</button>" +
    '<select class="pj-file" aria-label="ファイル">' + S.FILES.map(function (x, i) {
      return '<option value="' + i + '"' + (i === pg.fileIndex ? " selected" : "") + ">" + esc(x.name) + "</option>";
    }).join("") + "</select>" +
    '<input class="pj-num" type="number" min="1" max="' + f.pages + '" value="' + (pg.pageInFile + 1) + '" aria-label="ページ番号">' +
    '<span class="pj-of">/ ' + f.pages + " ページ</span>" +
    '<button type="button" class="btn primary pj-go" data-pj="go">移動</button>' +
    '<button type="button" class="pj-btn" data-pj="next" title="次のページ"' + (S.page >= S.TOTAL - 1 ? " disabled" : "") + ">" + svg(chevD, 16) + "</button>";
  var sel = host.querySelector(".pj-file"), num = host.querySelector(".pj-num");
  function go() {
    var g = resolveJump(S.FILES, S.FILE_START, +sel.value, num.value);
    if (g < 0) return;
    S.page = g; ui.render();
  }
  host.querySelector('[data-pj="go"]').addEventListener("click", go);
  num.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); go(); } });
  // ファイルを切り替えたら番号入力の上限をそのファイルに合わせ、1 ページ目へ (移動は「移動」で確定)
  sel.addEventListener("change", function () { var x = S.FILES[+sel.value]; if (x) { num.max = x.pages; num.value = 1; } });
  host.querySelector('[data-pj="prev"]').addEventListener("click", function () { if (S.page > 0) { S.page--; ui.render(); } });
  host.querySelector('[data-pj="next"]').addEventListener("click", function () { if (S.page < S.TOTAL - 1) { S.page++; ui.render(); } });
}

export { initPageJump, buildPageJump, resolveJump };
