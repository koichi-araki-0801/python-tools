// =============================================================================
// geometry.js — PdfToSvg のページ座標・範囲指定の純粋ヘルパ (状態非依存)
// =============================================================================

// クライアント座標 → SVG `viewBox` 座標 (ページ pt)。
export function clientToPage(svgEl, clientX, clientY) {
  var r = svgEl.getBoundingClientRect();
  var vb = svgEl.viewBox.baseVal;
  return {
    x: vb.x + ((clientX - r.left) / r.width) * vb.width,
    y: vb.y + ((clientY - r.top) / r.height) * vb.height,
  };
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
