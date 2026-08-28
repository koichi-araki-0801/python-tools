// =============================================================================
// editor-events.js — 静的 UI 要素へのイベント配線
// =============================================================================
// `editor.js` の `Editor` インスタンス (`ed`) を受け取り、起動時に 1 回だけ静的な
// UI 要素 (ドロップゾーン / ツールバー / ステップバー / キーボード) を配線する。
// 動的要素 (ハンドル / インスペクタ / レール行) の配線は各描画時に editor-render.js が行う。

import { CONFIG } from "./constants.js";
import { acceptsShortcut } from "./utils.js";

/** 起動時の一括配線の入口 (`main.js` → `Editor.bindEvents` から呼ばれる) */
function bindEvents(ed) {
  wireOpen(ed);
  wireToolbar(ed);
  wireWizard(ed);
  wireKeyboard(ed);
}

// ── 1. 開く (手順1 ドロップゾーン / レールのボタン) ──

function wireOpen(ed) {
  if (ed.dom.dropzone) {
    ed.dom.dropzone.addEventListener("click", () => ed.openFiles());
    // `tabindex=0` の div のため Enter/Space のキーボード起動を自前で足す (ui.html 参照)。
    ed.dom.dropzone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); ed.openFiles(); }
    });
    ed.dom.dropzone.addEventListener("dragover", (e) => { e.preventDefault(); ed.dom.dropzone.classList.add("dragover"); });
    ed.dom.dropzone.addEventListener("dragleave", () => ed.dom.dropzone.classList.remove("dragover"));
    ed.dom.dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      ed.dom.dropzone.classList.remove("dragover");
      ed.handleDrop(e.dataTransfer);
    });
  }
  if (ed.dom.btnOpenRail) ed.dom.btnOpenRail.addEventListener("click", () => ed.openFiles());
}

// ── 2. ツールバー (保存 / Undo / Redo / 全体リセット / ズーム) ──

function wireToolbar(ed) {
  ed.dom.btnSave.addEventListener("click", () => ed.save());
  ed.dom.btnUndo.addEventListener("click", () => ed.undo());
  if (ed.dom.btnRedo) ed.dom.btnRedo.addEventListener("click", () => ed.redo());
  ed.dom.btnReset.addEventListener("click", () => {
    const it = ed.items.find((i) => i.id === ed.currentId);
    if (!it) return;
    // 表示中ファイルの調整を全破棄する破壊的操作のため確認を挟む (Undo でも戻れない
    // `load` による再構築)。フレームワーク無しのため `window.confirm` で足りる。
    const ok = window.confirm(`「${it.name}」の調整をすべて破棄して、開いた時の状態に戻します。よろしいですか？`);
    if (ok) ed.load(it);
  });
  ed.dom.btnZoomIn.addEventListener("click", () => ed.setZoom(ed.zoom * CONFIG.zoomStep));
  ed.dom.btnZoomOut.addEventListener("click", () => ed.setZoom(ed.zoom / CONFIG.zoomStep));
}

// ── 3. ウィザード遷移 (フッター / ステップバー) ──

function wireWizard(ed) {
  if (ed.dom.btnBack) ed.dom.btnBack.addEventListener("click", () => ed.goPhase(ed.phase - 1));
  if (ed.dom.btnNext) ed.dom.btnNext.addEventListener("click", () => ed.goPhase(ed.phase + 1));
  if (ed.dom.stepbar) {
    ed.dom.stepbar.querySelectorAll(".step").forEach((st) => {
      st.addEventListener("click", () => ed.goPhase(+st.dataset.step));
    });
  }
}

// ── 4. キーボード (ショートカット / 矢印ナッジ) ──

function wireKeyboard(ed) {
  window.addEventListener("keydown", (e) => {
    // 受理条件は `utils.js` の `acceptsShortcut` に集約する。判定を各ショートカットの中へ
    // 散らすと、足すたびにガードを書き忘れる (現に矢印だけがフォーカスを見ていた)。
    const active = document.activeElement;
    const ctrl = e.ctrlKey || e.metaKey;
    const k = e.key.toLowerCase();

    if (ctrl && k === "o") {
      if (!acceptsShortcut(active, ed.phase, "open")) return;
      e.preventDefault();
      ed.openFiles();
      return;
    }
    if (ctrl && k === "s") {
      if (!acceptsShortcut(active, ed.phase, "save")) return;
      e.preventDefault();
      ed.save();
      return;
    }

    // ここから下は文書に紐づく操作。
    if (!acceptsShortcut(active, ed.phase, "document")) return;

    // Redo: Ctrl+Y / Ctrl+Shift+Z
    if (ctrl && (k === "y" || (e.shiftKey && k === "z"))) {
      e.preventDefault();
      ed.redo();
      return;
    }
    if (ctrl && k === "z") {
      e.preventDefault();
      ed.undo();
      return;
    }
    if (e.key === "Escape") {
      ed.selectLabel(null);
      return;
    }
    if (!ed.selected) return;
    const step = e.shiftKey ? CONFIG.nudgeStepFast : CONFIG.nudgeStep;
    const map = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (map[e.key]) {
      e.preventDefault();
      // 押しっぱなし (`repeat`) の分は履歴を積まない。1 発ごとに積むと `historyLimit` を
      // 数秒で使い切り、それ以前の操作が戻せなくなる。
      ed.nudge(map[e.key][0], map[e.key][1], e.repeat);
    }
  });
}

export { bindEvents };
