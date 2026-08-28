// =============================================================================
// dom.js — PdfToSvg の純粋な DOM/文字列ヘルパ (アプリ状態に依存しない)
// =============================================================================

// インライン SVG アイコン生成。`p`=path 群, `w`=一辺px(任意), `sw`=stroke幅(既定1.7)、
// `cls`=付与する class 属性(任意)。
export function svg(p, w, sw, cls) {
  return (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="' +
    (sw || 1.7) +
    '" stroke-linecap="round" stroke-linejoin="round"' +
    (cls ? ' class="' + cls + '"' : "") +
    (w ? ' style="width:' + w + "px;height:" + w + 'px"' : "") +
    ">" +
    p +
    "</svg>"
  );
}

// HTML 属性/本文へ埋め込む際の最小エスケープ。graph-editor `utils.js` の `escapeHtml`
// と置換表を逐語一致させる(並行実装。片方を変えたら両方)。一致は
// `test_parallel_impl_drift.py` が機械検証する。
export function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}
