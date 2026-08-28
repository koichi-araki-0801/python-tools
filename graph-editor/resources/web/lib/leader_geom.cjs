/**
 * 引出線(leader)まわりの純粋関数。DOM にも CONFIG にも依存しない部分だけをここへ集約し、
 * ブラウザ(ui.html)と node(vitest 単体テスト)の双方から同一実装を共有する。
 *
 * 配布形態の都合で UMD: ブラウザでは classic <script> として読み込まれ global `LeaderGeom`
 * を生やし、node では `module.exports` を返す。プロジェクトは "type":"module" のため拡張子は
 * .cjs (= CommonJS 扱い) とし、ブラウザの classic script でもそのまま実行できるようにする。
 */
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.LeaderGeom = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const WHITE = "#ffffff";
  const BLACK = "#000000";

  /** 点 p を矩形 box={left,top,right,bottom} へクランプ = 外枠上(矩形内なら点自身)の最近点。
   *  leader 端点を必ずラベル外枠上へ載せるための核となる演算。box は pie-chart src/svg_geom.ts の
   *  BBox 規約 (left/right/top/bottom) に合わせる。 */
  function clampPointToBox(p, box) {
    return {
      x: Math.max(box.left, Math.min(p.x, box.right)),
      y: Math.max(box.top, Math.min(p.y, box.bottom)),
    };
  }

  /** "M x,y L x,y ..." → [{x,y},...] */
  function parsePath(d) {
    const nums = String(d).match(/-?\d*\.?\d+(?:e[-+]?\d+)?/gi);
    if (!nums) return [];
    const pts = [];
    for (let i = 0; i + 1 < nums.length; i += 2) {
      pts.push({ x: parseFloat(nums[i]), y: parseFloat(nums[i + 1]) });
    }
    return pts;
  }

  /** [{x,y},...] → "M x,y L x,y ..." */
  function buildPath(pts) {
    return pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x},${p.y}`).join(" ");
  }

  /** transform 文字列から translate(dx,dy) を取り出す。無ければ {x:0,y:0}。 */
  function parseTranslate(transform) {
    if (!transform) return { x: 0, y: 0 };
    // 数値トークンは重なりのない形にする (`\d*\.?\d+` は省略可能な数字列と必須の数字列が
    // 重なり、閉じ括弧に至れない未信頼 SVG の transform で二次バックトラックする)。捕捉する
    // 座標は不変 ( `-?\d+(?:\.\d+)?|-?\.\d+` は `-?\d*\.?\d+` と同じ数値集合を採る)。
    const m = transform.match(
      /translate\(\s*(-?\d+(?:\.\d+)?|-?\.\d+)[ ,]+(-?\d+(?:\.\d+)?|-?\.\d+)\s*\)/,
    );
    return m ? { x: parseFloat(m[1]), y: parseFloat(m[2]) } : { x: 0, y: 0 };
  }

  /** 色文字列を比較用に正規化 (trim + 小文字化 + 短縮形/英名を6桁へ)。 */
  function normColor(c) {
    if (c == null) return c;
    const v = String(c).trim().toLowerCase();
    if (v === "white" || v === "#fff") return WHITE;
    if (v === "black" || v === "#000") return BLACK;
    return v;
  }

  return { clampPointToBox, parsePath, buildPath, parseTranslate, normColor };
});
