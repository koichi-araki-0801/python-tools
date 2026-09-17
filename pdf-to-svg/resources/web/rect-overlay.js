// =============================================================================
// rect-overlay.js — ページ上の矩形を HTML の箱で重ね、移動・角ハンドル伸縮させる共通部分
// =============================================================================
// 手順 3 の「上書き」(`cover.js`) と「枠線」(`border.js`) は、置いた矩形を後から選び・動かし・
// 大きさを変える点で同じ振る舞いをする。モデルを正とし (表示 SVG から座標を拾わない)、ドラッグ中は
// 箱だけを動かし、mouseup の 1 回だけ更新 RPC を送る、という流儀もそろえる。両者で違うのは
// 「どの一覧 RPC を引くか」「選択したとき入力欄に何を映すか」「いまこのオーバーレイを描くべきか」
// (`isActive`) だけなので、それを `opts` で受け取る。複製して 2 本持つと、片方だけ直した不具合が
// もう片方に残る。このファイルは `S` を読まない。手順やツールの状態は `opts.isActive()` で受け取る。
// 単体テストが共有ページの `S` を書き換えずに済み、部品として本当に `opts` だけで動く。
// 矩形操作のヘルパ (`copyRect` / `pageSizeOf` / `clampToPage` / `placeRect` / `MIN_SIZE_PT` /
// `resizeFromPointer` / `CORNER_HANDLES_HTML`) は手順 4 の採用矩形と共通なので `geometry.js` から読む。
import { clientToPage, copyRect, pageSizeOf, clampToPage, placeRect, MIN_SIZE_PT, resizeFromPointer, CORNER_HANDLES_HTML } from "./geometry.js";

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

/** 1 種類の矩形オーバーレイを作る。返り値の `draw` / `installDrag` / `clearSel` を呼び出し側が使う。 */
function createRectOverlay(opts) {
  var ui = opts.ui;
  // draw() の世代。同じページで draw() が重なったとき、後から出した要求の応答が先に届くと、
  // 遅れて届いた古い一覧で箱を作り直してしまう (draw() は冒頭で箱を全部消すので、古い応答は
  // 箱を重複させる)。`mountPage` の token と同じ考え方で、応答が届いた時点で最新の呼び出しで
  // なければ描かない。
  var drawSeq = 0;

  /** 選択を解き、入力欄を「次に置く値」へ戻す。選択解除の経路 (ツール切替・空白クリック・
   *  ページ移動・選んでいた要素が消えた等) をここへ一元化し、選択中に編集した値が
   *  「次に置く値」へ紛れ込んだまま入力欄に残らないようにする。
   *  `state.js` が export する `clearSel`（ページレールの選択を解く）と同名にならないよう、
   *  内部名はこれにする。公開名は呼び出し側（`cover.js` / `border.js`）を変えないため `clearSel` のまま。 */
  function clearOverlaySel() {
    opts.setSel(null);
    opts.onSelect(null);
    if (ui.syncDeleteButton) ui.syncDeleteButton();
  }

  /** 手順 3 で対象のツールが選ばれている間だけ、ページ上の矩形を箱で重ねる。呼ぶたびに描き直す */
  async function draw(host) {
    var seq = ++drawSeq;
    host.querySelectorAll("." + opts.boxClass).forEach(function (b) { b.remove(); });
    if (!opts.isActive()) { clearOverlaySel(); return; }
    var svgEl = host.querySelector("svg"); if (!svgEl) { if (ui.syncDeleteButton) ui.syncDeleteButton(); return; }
    var pg = ui.pageOf();
    var res = await ui.rpc(opts.listRpc, { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
    if (seq !== drawSeq) return;                     // 取得中に新しい draw() が始まった (追い越された)
    if (host.querySelector("svg") !== svgEl) return; // 取得中にページが変わった
    var items = res[opts.listKey] || [];
    var sel = opts.getSel();
    if (sel !== null && !items.some(function (c) { return c.elId === sel; })) clearOverlaySel();
    items.forEach(function (c) {
      var box = document.createElement("div");
      box.className = opts.boxClass + (c.elId === opts.getSel() ? " sel" : "");
      box.dataset.elId = c.elId;
      box.innerHTML = CORNER_HANDLES_HTML;
      placeRect(box, c.rect, svgEl, host);
      box.querySelectorAll(".h").forEach(function (h) {
        h.addEventListener("mousedown", function (e) {
          e.stopPropagation(); e.preventDefault();
          opts.setDrag({ mode: "resize", elId: c.elId, rect: copyRect(c.rect), orig: copyRect(c.rect), corner: h.dataset.corner, box: box, moved: false, item: c });
        });
      });
      box.addEventListener("mousedown", function (e) {
        e.stopPropagation(); e.preventDefault();
        opts.setDrag({ mode: "move", elId: c.elId, rect: copyRect(c.rect), orig: copyRect(c.rect), origin: { x: e.clientX, y: e.clientY }, box: box, moved: false, item: c });
      });
      box.addEventListener("click", function (e) { e.stopPropagation(); });
      host.appendChild(box);
    });
    var cur = items.find(function (c) { return c.elId === opts.getSel(); });
    if (cur) opts.onSelect(cur);
    if (ui.syncDeleteButton) ui.syncDeleteButton();
  }

  /** 移動・伸縮のドラッグ。起動時に一度だけ張る (多重登録防止) */
  function installDrag(host) {
    window.addEventListener("mousemove", function (e) {
      var d = opts.getDrag(); if (!d) return;
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
      var d = opts.getDrag(); if (!d) return;
      opts.setDrag(null);
      opts.setSel(d.elId);
      if (!d.moved) {
        // クリック = 選択だけ。一覧の再取得 (RPC 往復) を待って反映すると、その間に利用者が
        // 入力欄へ打ち始めた値を巻き戻してしまう (往復の完了が入力より遅れて着く競合)。
        // 選ぶだけなら mousedown 時点で拾った値で足りるので、待たずに即時反映する
        // (矩形・見た目は据え置きのままなので再取得も不要)。
        host.querySelectorAll("." + opts.boxClass).forEach(function (b) { b.classList.toggle("sel", b.dataset.elId === String(d.elId)); });
        opts.onSelect(d.item);
        if (ui.syncDeleteButton) ui.syncDeleteButton();
        return;
      }
      var svgEl = host.querySelector("svg"); if (!svgEl) { if (ui.syncDeleteButton) ui.syncDeleteButton(); return; }
      var sz = pageSizeOf(svgEl);
      var r = clampToPage(d.rect, sz.w, sz.h);
      if (r.w < MIN_SIZE_PT || r.h < MIN_SIZE_PT) { await draw(host); return; }
      if (rectsNearlyEqual(r, d.orig)) {
        // `mousemove` は 1px のジッターでも `d.moved` を立てるため、結果の矩形が元と実質同じなら
        // クリック扱いにして更新 RPC を送らない。送ると変化の無い 1 段が Undo スタックへ積まれ、
        // 次の Ctrl+Z が「何も起きない」ように見える。
        await draw(host);
        return;
      }
      var pg = ui.pageOf();
      await ui.rpc(opts.updateRpc, { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elId: d.elId, rect: r });
      await ui.afterEdit();
    });
  }

  return { draw: draw, installDrag: installDrag, clearSel: clearOverlaySel };
}

export { createRectOverlay };
