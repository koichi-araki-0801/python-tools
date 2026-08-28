// =============================================================================
// dom.js — UI 要素の id 参照を一元化する DOM ハンドル集
// =============================================================================
// **解決はモジュール読み込み時の 1 回だけ**にすること。読み込んだ SVG はアプリ origin の
// 生 DOM へインライン挿入され、その `id` は入力側が自由に付けられる (サニタイザは `id` を
// 通す)。参照を遅延解決 (毎回 `getElementById`) に変えると、`id="canvas"` 等を持つ細工 SVG が
// UI のハンドルを乗っ取れるようになる。

const $ = (id) => document.getElementById(id);
const dom = {
  // 一覧 / キャンバス / パネル
  list: $("fileList"),
  canvas: $("canvas"),
  inspectorBody: $("inspectorBody"),
  // トップバー / ステータス
  status: $("status"),
  fileChip: $("fileChip"),
  btnUndo: $("btnUndo"),
  btnRedo: $("btnRedo"),
  // 操作ボタン
  btnSave: $("btnSave"),
  btnReset: $("btnResetAll"),
  btnZoomIn: $("btnZoomIn"),
  btnZoomOut: $("btnZoomOut"),
  // ウィザード
  stepbar: $("stepbar"),
  scOpen: $("scOpen"),
  scEdit: $("scEdit"),
  scSave: $("scSave"),
  dropzone: $("dropzone"),
  btnOpenRail: $("btnOpenRail"),
  btnBack: $("btnBack"),
  btnNext: $("btnNext"),
  navHint: $("navHint"),
  toast: $("toast"),
  // 表示まわり
  openList: $("openList"),
  openCount: $("openCount"),
  pgInfo: $("pgInfo"),
  zoomLvl: $("zoomLvl"),
  saveName: $("saveName"),
  saveSub: $("saveSub"),
};

export { dom };
