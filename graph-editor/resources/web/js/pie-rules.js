// =============================================================================
// pie-rules.js — 円幾何と leader 既定配置の純粋関数 (DOM 非依存)
// =============================================================================
// `editor.js` から抽出した判定・算出ロジック。DOM (`getBBox` / querySelector) には
// 触れず、呼び出し側が測った bbox / スライス d 文字列を入力に取る。vitest
// (`test/editor_pie_rules.test.ts`) が node 単体で同一実装を検証する。

/** slice パスの d ("M cx,cy L… A r,…") から円中心・半径を推定する。楔形でなければ null。
 *
 *  楔形 (`M` 中心 → `L` 始点 → `A` 終点) に限るのは、`M` の座標を円中心として読むため。
 *  100% 単一スライスは `L` を持たない全円 (`M` 天頂 + `A` 2 連) で、`M` はリム上の点だから
 *  そのまま中心にすると円が半径 1 つ分ずれる。判定は `editor.js` の `sliceMidAnchor` と同形。 */
function parsePieGeometry(d) {
  // 数値は `\d*` と `\d+` が重なる形 (`-?\d*\.?\d+`) にしない。重なると 1 つの数字列に
  // 対して複数の分割が同じ位置へ到達し、非マッチ時に長さの二乗で試行が増える。`d` は
  // `sanitizeAttrValue` が 1 MiB まで意図的に通すので、そこへ長い数字列を 1 本置くだけで
  // 最初のラベル操作が固まる。整数部ありと小数点始まりを**排他**に書けば線形になる。
  const NUM = /-?(?:\d+(?:\.\d+)?|\.\d+)/.source;
  const src = d || "";
  // `[^A-Za-z]*` は `L` / `A` と文字集合が交わらないので、貪欲に取っても候補は 1 通りに
  // 決まる (下の NUM と同じく、非マッチ時の試行が長さの二乗へ膨らまない形)。
  if (!/M[^A-Za-z]*L[^A-Za-z]*A/.test(src)) return null;
  const m = src.match(new RegExp(`M\\s*(${NUM})[ ,]+(${NUM})`));
  const a = src.match(new RegExp(`A\\s*(${NUM})[ ,]+(${NUM})`));
  if (!m || !a) return null;
  return { cx: parseFloat(m[1]), cy: parseFloat(m[2]), r: parseFloat(a[1]) };
}

/** slice から推定できない時の既定円 (キャンバス中央・短辺 × ratio) */
function fallbackPieGeometry(w, h, ratio) {
  return { cx: w / 2, cy: h / 2, r: Math.min(w, h) * ratio };
}

/** 素の bbox + `textTx` から ラベル外枠 {left,top,right,bottom} を組む */
function labelBox(bbox, tx) {
  const left = bbox.x + tx.x;
  const top = bbox.y + tx.y;
  return { left, top, right: left + bbox.width, bottom: top + bbox.height };
}

/** 素の bbox + `textTx` から ラベル中心点を返す */
function labelCenter(bbox, tx) {
  return { x: bbox.x + bbox.width / 2 + tx.x, y: bbox.y + bbox.height / 2 + tx.y };
}

/** 点 `c` が円周の外にあるか */
function isOutsidePie(c, pie) {
  return Math.hypot(c.x - pie.cx, c.y - pie.cy) > pie.r;
}

/** リーダー後付け時の既定 2 点 [リム上アンカー, ラベル端点] を算出する。
 *  端点 = ラベル外枠上で円中心に最も近い点。`anchor` (スライス中心角リム点) が
 *  null なら 中心→端点 方向のリム点へ退避する (`eps` 未満の零ベクトルは右向きに既定化)。 */
function computeDefaultLeaderPts(pie, box, anchor, eps) {
  const { cx, cy, r } = pie;
  const endpoint = {
    x: Math.max(box.left, Math.min(cx, box.right)),
    y: Math.max(box.top, Math.min(cy, box.bottom)),
  };
  if (!anchor) {
    let dx = endpoint.x - cx;
    let dy = endpoint.y - cy;
    const len = Math.hypot(dx, dy);
    if (len < eps) { dx = 1; dy = 0; }
    const ux = dx / (len || 1);
    const uy = dy / (len || 1);
    anchor = { x: cx + ux * r, y: cy + uy * r };
  }
  return [anchor, endpoint];
}

export { parsePieGeometry, fallbackPieGeometry, labelBox, labelCenter, isOutsidePie, computeDefaultLeaderPts };
