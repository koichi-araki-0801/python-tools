// =============================================================================
// label-state.js — 1 ラベル分の状態モデルと実 DOM 同期 (`LabelState`)
// =============================================================================

import { CONFIG, WHITE } from "./constants.js";
import { parseTranslate, parsePath, buildPath, normColor } from "./geom.js";
import { createSvgEl, extractPercentText, safeGetBBox, STATE_FIELDS } from "./utils.js";

// ── 1. ラベル状態 (1 ラベル分の状態と実 DOM 同期) ──

class LabelState {
  constructor(g, editor) {
    this.editor = editor;
    const text = g.querySelector("text");
    const path = g.querySelector("path");
    const tx = parseTranslate(text.getAttribute("transform"));
    this.g = g;
    this.text = text;
    this.path = path;
    this.name = g.getAttribute("data-name") || "(no name)";
    this.textTx = { ...tx };
    this.leaderPts = path ? parsePath(path.getAttribute("d")) : [];
    // 読込時から円側端点をスライス中心角リム点へ固定 (`initial` スナップショットにも反映)
    if (this.leaderPts.length >= 2) {
      const a = editor.sliceMidAnchor(this.name);
      if (a) this.leaderPts[0] = { x: a.x, y: a.y };
    }
    this.leaderVisible = !!path;
    this.originalFill = text.getAttribute("fill");
    this.fill = this.originalFill;
    // 行数 / 長体 / 名前・パーセント文字列を SVG から復元 (1行化・2行化・長体の編集に使う)。
    // パーセントは**実際に表示されている文字列**を保持する (理由は `utils.js` の
    // `extractPercentText`)。行数や長体を変えると `rebuildTextContent` が `tspan` を組み直すが、
    // その時に使う文字列は読込時のこれで、`data-percent` から作り直さない。
    const tspans = [...text.querySelectorAll("tspan")];
    this.percentText = extractPercentText(
      tspans.map((t) => ({ hasX: t.hasAttribute("x"), text: t.textContent })),
      this.name,
      g.getAttribute("data-percent"),
    );
    const lc = parseInt(g.getAttribute("data-line-count"), 10);
    // `data-line-count` 優先。無ければ `x` 指定を持つ `tspan` 数 (=行頭の数) で推定。
    this.lineCount = lc === 2 ? 2 : lc === 1 ? 1
      : (tspans.filter((t) => t.hasAttribute("x")).length >= 2 ? 2 : 1);
    const sxAttr = parseFloat(g.getAttribute("data-name-scale-x"));
    this.nameScaleX = sxAttr > 0 && sxAttr < 1 ? sxAttr : 1;
    this.baselineRaw = text.getAttribute("dominant-baseline") || "middle";
    // 行間 (em): 既存 `tspan` の 0 でない `dy` から検出。無ければ既定。
    let ls = CONFIG.defaultLineSpacing;
    for (const t of tspans) {
      const dy = (t.getAttribute("dy") || "").trim();
      // 数値トークンは重なりのない形にする (`\d*\.?\d+` は省略可能な数字列と必須の数字列が
      // 重なり、`em` に至れない長い数字列で開始位置ごとに二次バックトラックする)。加えて
      // trim 済み値の先頭へアンカーして全開始位置での再試行も消す (入力は未信頼 SVG の dy)。
      const m = dy.match(/^(-?\d+(?:\.\d+)?|-?\.\d+)\s*em/);
      if (m) { const v = Math.abs(parseFloat(m[1])); if (v > 0.01) { ls = v; break; } }
    }
    this.lineSpacing = ls;
    // 現在 DOM に焼かれている `text` 内容のシグネチャ。これと state がずれた時だけ再構築する。
    this._renderedTextSig = `${this.lineCount}|${this.nameScaleX}`;
    // 白文字 (inside スライス) タイプか — 円外/円内で色を切替える判定に使う。
    // 生成出力は厳密に `#ffffff` だが、表記揺れに備え正規化して比較する。
    this.whiteType = normColor(this.originalFill) === WHITE;
    this._auto = false;    // leader が自動生成 (位置駆動) か手動かの識別
    this._hitRect = null;  // ドラッグ用の透明ヒット矩形
    // リセット用の初期スナップショット
    this.initial = this.snapshot();
  }

  snapshot() {
    const snap = {};
    for (const [k, f] of Object.entries(STATE_FIELDS)) snap[k] = f.copy(this[k]);
    return snap;
  }

  apply(snap) {
    for (const [k, f] of Object.entries(STATE_FIELDS)) this[k] = f.copy(snap[k]);
  }

  /** ヒット矩形を text と同じ transform へ追従させる */
  syncHit() {
    const rect = this._hitRect;
    if (!rect) return;
    if (this.textTx.x || this.textTx.y) rect.setAttribute("transform", `translate(${this.textTx.x},${this.textTx.y})`);
    else rect.removeAttribute("transform");
  }

  /** `this.path` が無ければ leader `<path>` を生成し `text` の背面へ挿入 */
  ensurePath() {
    if (this.path) return this.path;
    const path = createSvgEl("path", { fill: "none", ...this.editor.leaderStyleTemplate() });
    // text (とヒット矩形) の背面に置く
    this.g.insertBefore(path, this.text);
    this.path = path;
    return path;
  }

  /** 行数(1/2) と 長体率 に基づき `<text>` 内の `tspan` を組み直す。生成側 `textFragment` と同じ
   *  構造: 1行目=名前 (長体なら `textLength`+`lengthAdjust`)、続いて パーセント。
   *  - 2行: 名前と % を別行 (各行 `x` 指定 + `dy` で改行)
   *  - 1行: 名前 `tspan` の後ろに " %" を `x`/`dy` 無しで同チャンク流し込み (text-anchor 維持)
   *  長体の `textLength` は実フォントでの素の送り幅 (`getComputedTextLength`) × 率 で算出する。 */
  rebuildTextContent() {
    const text = this.text;
    const x = text.getAttribute("x") || "0";
    const L = this.lineSpacing;
    const two = this.lineCount >= 2;
    const sx = this.nameScaleX;
    // baseline ごとの 1 行目 `dy` (生成側と一致)
    let firstDy;
    if (this.baselineRaw === "text-before-edge") firstDy = "0em";
    else if (this.baselineRaw === "text-after-edge") firstDy = two ? `${-(this.lineCount - 1) * L}em` : "0em";
    else firstDy = two ? `${(-(this.lineCount - 1) * L) / 2}em` : "0em";

    const nameT = createSvgEl("tspan", { x, dy: firstDy });
    // 2行+長体: 横圧縮(`textLength`)は行位置(`dy`)を持つ `tspan` に同居させると Chromium で
    // 後続行の行送りが壊れ重なる/消える。圧縮を内側 `tspan` へ隔離して行送りを守る。
    let nameTarget = nameT;
    if (two && sx < 1) {
      const inner = createSvgEl("tspan");
      nameT.appendChild(inner);
      nameTarget = inner;
    }
    nameTarget.textContent = this.name;

    const pctT = createSvgEl("tspan");
    if (two) {
      pctT.setAttribute("x", x);
      pctT.setAttribute("dy", `${L}em`);
      pctT.textContent = this.percentText;
    } else {
      // 同一チャンクに流す (`x`/`dy` 無し)。先頭スペースで名前と数値を区切る。
      pctT.textContent = ` ${this.percentText}`;
    }
    text.replaceChildren(nameT, pctT);

    // 長体: 素の送り幅を測ってから `textLength` を与える (測定は `textLength` 無しの状態で)
    if (sx < 1) {
      let natural = 0;
      try { natural = nameTarget.getComputedTextLength(); } catch { natural = 0; }
      if (natural > 0) {
        nameTarget.setAttribute("textLength", (natural * sx).toFixed(2));
        nameTarget.setAttribute("lengthAdjust", "spacingAndGlyphs");
      }
    }

    // `<g>` の `data-*` 属性も実態に合わせる (保存後に再読込しても状態が残るように)
    this.g.setAttribute("data-line-count", two ? "2" : "1");
    if (sx < 1) this.g.setAttribute("data-name-scale-x", String(sx));
    else this.g.removeAttribute("data-name-scale-x");

    this.refreshHitRect();
  }

  /** `text` の現 bbox からヒット矩形を再計測 (行数/長体で寸法が変わった後に呼ぶ) */
  refreshHitRect() {
    const rect = this._hitRect;
    if (!rect) return;
    const bbox = safeGetBBox(this.text, null);
    if (!bbox) return;
    const pad = CONFIG.hitPadding;
    rect.setAttribute("x", bbox.x - pad);
    rect.setAttribute("y", bbox.y - pad);
    rect.setAttribute("width", bbox.width + pad * 2);
    rect.setAttribute("height", bbox.height + pad * 2);
    this.syncHit();
  }

  /** JS 状態を実 DOM へ反映 */
  renderToDom() {
    // 行数/長体が変わっていれば `tspan` を組み直す (位置・色より先に確定させる)
    const textSig = `${this.lineCount}|${this.nameScaleX}`;
    if (textSig !== this._renderedTextSig) {
      this.rebuildTextContent();
      this._renderedTextSig = textSig;
    }
    if (this.textTx.x === 0 && this.textTx.y === 0) {
      this.text.removeAttribute("transform");
    } else {
      this.text.setAttribute("transform", `translate(${this.textTx.x},${this.textTx.y})`);
    }
    // `fill` が無い `text` (`originalFill=null`) は属性を触らない ("null" 焼き込み防止)
    if (this.fill != null && this.fill !== "") this.text.setAttribute("fill", this.fill);
    if (this.leaderPts.length >= 2) {
      // 円側端点は常にスライス中心角リム点へロック (生成/編集経路を問わず固定)
      const a = this.editor.sliceMidAnchor(this.name);
      if (a) this.leaderPts[0] = { x: a.x, y: a.y };
      this.ensurePath();
      this.path.setAttribute("d", buildPath(this.leaderPts));
      this.path.style.display = this.leaderVisible ? "" : "none";
    } else if (this.path) {
      // リーダー無し状態: DOM から `path` を除去 (Undo/削除で再導出される)
      this.path.remove();
      this.path = null;
    }
    this.syncHit();
  }
}

export { LabelState };
