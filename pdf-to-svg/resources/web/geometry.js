// =============================================================================
// geometry.js — PdfToSvg のページ座標・矩形操作・ページ範囲指定のヘルパ
// =============================================================================
// 画面の状態 (`state.js` の `S`) には依存しない。DOM は読む (`clientToPage` /
// `pageSizeOf` が `viewBox` と要素の実寸を見る) し、`placeRect` は箱の `style` を書くが、
// どれも「渡された引数だけで決まる」ので手順 3 のオーバーレイ (`cover.js`) と手順 4 の
// 採用矩形 (`figure.js`) が同じ実装を共有できる。

// クライアント座標 → SVG `viewBox` 座標 (ページ pt)。
export function clientToPage(svgEl, clientX, clientY) {
  var r = svgEl.getBoundingClientRect();
  var vb = svgEl.viewBox.baseVal;
  return {
    x: vb.x + ((clientX - r.left) / r.width) * vb.width,
    y: vb.y + ((clientY - r.top) / r.height) * vb.height,
  };
}

/** ページ座標 (pt) の矩形を host 相対の px に置く */
export function placeRect(box, r, svgEl, host) {
  var sr = svgEl.getBoundingClientRect(), hb = host.getBoundingClientRect(), vb = svgEl.viewBox.baseVal;
  var sx = sr.width / vb.width, sy = sr.height / vb.height;
  box.style.left = ((r.x - vb.x) * sx + sr.left - hb.left) + "px";
  box.style.top = ((r.y - vb.y) * sy + sr.top - hb.top) + "px";
  box.style.width = (r.w * sx) + "px";
  box.style.height = (r.h * sy) + "px";
}

export var MIN_SIZE_PT = 4; // これ未満の矩形は誤クリックとみなして作らない

export function copyRect(r) { return { x: r.x, y: r.y, w: r.w, h: r.h }; }

// ページ外へはみ出した矩形をページ内へ収める (サーバの clip 検証は「ページ内・正の寸法」を要求する)
export function clampToPage(r, w, h) {
  var x0 = Math.max(0, Math.min(r.x, w)), y0 = Math.max(0, Math.min(r.y, h));
  var x1 = Math.max(0, Math.min(r.x + r.w, w)), y1 = Math.max(0, Math.min(r.y + r.h, h));
  return { x: x0, y: y0, w: Math.max(0, x1 - x0), h: Math.max(0, y1 - y0) };
}

// ページ幅・高さ (pt)。viewBox の原点は常に 0,0 (書き出し矩形はページ全体) なので width/height だけ見る
export function pageSizeOf(svgEl) {
  var vb = svgEl.viewBox.baseVal;
  return { w: vb.width, h: vb.height };
}

/** 掴んだ角 `corner` を点 `p` へ動かしたときの矩形。反対の角は固定し、`MIN_SIZE_PT` より小さくしない。
 *  新しい矩形を返す純粋関数にしてあるのは、呼び出し側で同一性を保ちたい場合 (`figure.js` は
 *  採用矩形の箱を配列の同一性で引く) に `Object.assign` で受けられるようにするため。 */
export function resizeByCorner(orig, corner, p) {
  var left = corner.indexOf("w") >= 0 ? p.x : orig.x;
  var right = corner.indexOf("e") >= 0 ? p.x : orig.x + orig.w;
  var top = corner.indexOf("n") >= 0 ? p.y : orig.y;
  var bottom = corner.indexOf("s") >= 0 ? p.y : orig.y + orig.h;
  return {
    x: Math.min(left, right),
    y: Math.min(top, bottom),
    w: Math.max(MIN_SIZE_PT, Math.abs(right - left)),
    h: Math.max(MIN_SIZE_PT, Math.abs(bottom - top)),
  };
}

// 角ハンドル 4 つのマークアップ。伸縮の当たり判定は `.h` の `data-corner` で拾う。
export var CORNER_HANDLES_HTML =
  '<span class="h nw" data-corner="nw"></span><span class="h ne" data-corner="ne"></span>' +
  '<span class="h sw" data-corner="sw"></span><span class="h se" data-corner="se"></span>';

/** 2 つの矩形 {x,y,w,h} の IoU (重なり面積 / 合併面積)。重ならなければ 0 */
export function rectIoU(a, b) {
  var ix = Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x));
  var iy = Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
  var inter = ix * iy;
  var union = a.w * a.h + b.w * b.h - inter;
  return union > 0 ? inter / union : 0;
}

// "1-5, 8" → [1,2,3,4,5,8] (1始まり・昇順ユニーク・1..max にクランプ)。
export function parseSpec(text, maxPages) {
  var got = {};
  String(text || "")
    .split(",")
    .forEach(function (tok) {
      tok = tok.trim();
      if (!tok) return;
      var m = tok.match(/^(\d+)\s*-\s*(\d+)$/);
      var a, b;
      if (m) {
        a = +m[1];
        b = +m[2];
      } else if (/^\d+$/.test(tok)) {
        a = b = +tok;
      } else return;
      if (a > b) {
        var t = a;
        a = b;
        b = t;
      }
      a = Math.max(1, a);
      b = Math.min(maxPages, b);
      for (var n = a; n <= b; n++) got[n] = true;
    });
  return Object.keys(got)
    .map(Number)
    .sort(function (x, y) {
      return x - y;
    });
}
