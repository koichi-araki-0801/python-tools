// =============================================================================
// utils.js — 状態を持たない純粋ユーティリティ群 (DOM/SVG/文字列ヘルパ)
// =============================================================================

import { SVG_NS, CONFIG } from "./constants.js";
import {
  XMLNS_NS,
  isAllowedAttr,
  isAllowedElement,
  sanitizeAttrValue,
  sanitizeFontFaceCss,
} from "./svg-policy.js";

// ── 1. 純粋ユーティリティ (状態を持たない) ──

// `parsePath` / `buildPath` / `parseTranslate` は `leader_geom.cjs` が実装し `geom.js` が
// 再エクスポートする。

/** 文字列を HTML 属性/テキストへ埋める際のエスケープ。
 *  新しく動的な値を画面へ出す時は、まず `textContent` / `setAttribute` を検討すること。
 *  文字列連結 + `innerHTML` は「1 箇所だけエスケープを忘れる」形で必ず破られる
 *  (インスペクタの色が素通しだった事例)。本関数は既存の一覧表示のためだけに残す。
 *  pdf-to-svg `dom.js` の `esc` と置換表を逐語一致させる(並行実装。片方を変えたら両方)。
 *  一致は `test_parallel_impl_drift.py` が機械検証する。 */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function round(n) {
  return Math.round(n * CONFIG.roundPrecision) / CONFIG.roundPrecision;
}

/** SVG 要素を生成し属性をまとめて設定する (値は `setAttribute` へ渡り文字列化される)。 */
function createSvgEl(tag, attrs = {}) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

/** `getBBox` は detached/未レイアウト時に例外を投げる。失敗時は `fallback` を返す。 */
function safeGetBBox(el, fallback = { x: 0, y: 0, width: 0, height: 0 }) {
  try {
    return el.getBBox();
  } catch {
    return fallback;
  }
}

// `normColor` は `leader_geom.cjs` が実装し `geom.js` が再エクスポートする。

// ── 2. 未信頼 SVG の取り込み (構成的 allowlist) ──
// 読み込んだ SVG は `<img>` でも sandbox iframe でもなく**アプリ origin の生 DOM へ
// インライン挿入**される (`getBBox` / `getComputedTextLength` の実測が要るため)。
// したがって取り込み時点で能動コンテンツが 1 つも残っていないことが前提条件になる。

// `DOMParser` へ渡す前の入力長の上限。XML の実体展開 (billion laughs) はパーサの
// 内側で起きるので、展開前に効かせられるのはこの 1 箇所だけ。
const MAX_SVG_INPUT_CHARS = 8 << 20;

// 再帰の深さ上限。深い入れ子でスタックを溢れさせる入力を安全側で切り落とす。
const MAX_SVG_DEPTH = 128;

// 出力ツリーへ組み立てるノード数 (要素 + テキスト) の上限。入力長 8MiB の制限だけでは
// 「小さなノードを大量に詰める」形 (`<g/>` の 10 万個並び) を止められず、そのまま
// アプリ origin の DOM へ挿すとレイアウトと以降の全描画が実用外の重さになる。
// pie-chart の実出力は数百ノード規模なので、2 桁以上の余裕を見てもここで切れる。
// 超過したら**部分的に読み込まず** `sanitizeSvg` ごと `null` を返す (呼び出し側が
// 「解釈できませんでした」として利用者へ通知する) — 途中まで表示して編集させると、
// 保存時に欠けたノードごと書き出してしまうため。
const MAX_SVG_NODES = 20000;

/** 許可された属性だけを**新しい要素へ書き写す**。
 *  `setAttributeNS` は使わない = 出力に名前空間つき属性を 1 つも作らない。
 *  `xmlns` 宣言 (xmlns 名前空間) は数えずに捨てる — 出力は `createElementNS` で組み
 *  `XMLSerializer` が宣言を再生成するので、これは除去ではなく再構築だから。 */
function copyAllowedAttrs(srcEl, dstEl, removed) {
  for (const attr of srcEl.attributes) {
    if (attr.namespaceURI === XMLNS_NS) continue;
    if (!isAllowedAttr(attr.localName, attr.namespaceURI, srcEl.localName)) {
      removed.attrs++;
      continue;
    }
    const value = sanitizeAttrValue(srcEl.localName, attr.localName, attr.value);
    if (value === null) {
      removed.attrs++;
      continue;
    }
    dstEl.setAttribute(attr.localName, value);
  }
}

/** ソースツリーを読み取り、許可されたものだけで出力ツリーを組み立てる (入力ノードは
 *  1 つも再利用しない)。コメント / 処理命令 / DOCTYPE は無害だが持ち込まない —
 *  「出力は ELEMENT と TEXT だけ」という単純な不変条件をテストで主張できるようにする。
 *  `budget.remaining` を使い切ったら `false` を返して打ち切る (呼び出し側は全体を捨てる)。 */
function buildAllowedChildren(srcEl, dstEl, removed, depth, budget) {
  for (const node of srcEl.childNodes) {
    if (budget.remaining <= 0) return false;
    if (node.nodeType === Node.TEXT_NODE || node.nodeType === Node.CDATA_SECTION_NODE) {
      budget.remaining--;
      dstEl.appendChild(document.createTextNode(node.data));
      continue;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) continue;
    if (!isAllowedElement(node.localName, node.namespaceURI) || depth >= MAX_SVG_DEPTH) {
      removed.elements++;
      continue;
    }
    budget.remaining--;
    if (node.localName === "style") {
      const css = sanitizeFontFaceCss(node.textContent);
      if (!css) {
        if ((node.textContent || "").trim()) removed.styles++;
        continue;
      }
      const styleEl = document.createElementNS(SVG_NS, "style");
      copyAllowedAttrs(node, styleEl, removed);
      styleEl.textContent = css;
      dstEl.appendChild(styleEl);
      continue;
    }
    const out = document.createElementNS(SVG_NS, node.localName);
    copyAllowedAttrs(node, out, removed);
    if (!buildAllowedChildren(node, out, removed, depth + 1, budget)) return false;
    dstEl.appendChild(out);
  }
  return true;
}

/** 未信頼 SVG を許可リストに沿って**組み直して**返す。
 *  戻り値は `{ root, removed }` で、`root` は本文書の `createElementNS` で組んだ
 *  `<svg>` 要素 (そのまま挿入でき `importNode` は不要)。`removed` は落とした件数で、
 *  利用者への警告表示と、保存直前の自己検証 (`editor-io.js` の `save`) に使う。
 *  解釈不能・非 SVG・上限超過なら `null`。
 *
 *  在庫を削る (`removeAttribute` / `remove`) 方式へ戻さないこと: 消し忘れた属性や
 *  ノード種 (コメント・CDATA・処理命令・実体参照) がそのまま残り、`<foreignObject>` の
 *  XHTML `<iframe>` や `<animate attributeName="href">` のように「危険物リストに
 *  載っていなかっただけ」の経路が復活する。許可集合は `svg-policy.js` が正典。 */
function sanitizeSvg(svgText) {
  if (typeof svgText !== "string" || !svgText || svgText.length > MAX_SVG_INPUT_CHARS) return null;
  const doc = new DOMParser().parseFromString(svgText, "image/svg+xml");
  const src = doc.documentElement;
  if (!src || src.nodeName === "parsererror" || src.querySelector("parsererror")) return null;
  // ルートも名前空間つきで判定する (`nodeName.toLowerCase()` はプレフィックス付き
  // 別名前空間の `<x:svg>` を取りこぼす)。
  if (!isAllowedElement(src.localName, src.namespaceURI) || src.localName !== "svg") return null;
  const removed = { elements: 0, attrs: 0, styles: 0 };
  const root = document.createElementNS(SVG_NS, "svg");
  copyAllowedAttrs(src, root, removed);
  // ノード数の予算。使い切ったら組み立てを打ち切り、途中の木は返さない (`null`)。
  const budget = { remaining: MAX_SVG_NODES };
  if (!buildAllowedChildren(src, root, removed, 1, budget)) return null;
  return { root, removed };
}

/** `sanitizeSvg` の除去件数の合計 (0 なら 1 バイトも削っていない)。 */
function removedCount(removed) {
  return removed.elements + removed.attrs + removed.styles;
}

// ── 3. 入出力の方針と編集状態フィールド ──

// File System Access API のネイティブピッカー (`showOpenFilePicker` / `showSaveFilePicker`) を
// 使うか。VDI/リモートデスクトップの管理された Edge ではこのピッカーがレンダラごとクラッシュ
// するため、常に `false` にして従来型 `<input type=file>` / `<a download>` のフォールバック経路
// へ流す (`editor.js` の `openFiles` / `save` 参照)。本ツールは開いたハンドルを使わず内容だけ
// 扱うので機能差は実質「保存先がダウンロードフォルダ固定」になる点のみ。安定性を優先する判断。
function hasFsAccess() {
  return false;
}

// 開く/保存ダイアログのファイル種別フィルタ。
const SVG_PICKER_TYPES = [{ description: "SVG ファイル", accept: { "image/svg+xml": [".svg"] } }];

// 編集で変化し Undo/リセット対象となるフィールドと、その複製方法・等値判定を一元定義。
// `label-state.js` の `LabelState` の `snapshot` / `apply` と、下の `stateEquals` が
// すべてこれを参照するため、項目追加はここ 1 箇所で済む。
//
// `equals` を持つ理由: 「編集済みか」の判定 (`editor.js` の `isLabelEdited`) は
// レール描画から**ドラッグ中の毎フレーム・全ラベル分**呼ばれる。
// `JSON.stringify(snapshot()) !== JSON.stringify(initial)` で比べると 1 フレームあたり
// ラベル数 × 2 回の直列化と、その分のスナップショット複製が要る。等値判定を
// フィールドごとに持てば、複製も文字列化もせずに比較だけで済む。
const STATE_FIELDS = {
  textTx: { copy: (v) => ({ ...v }), equals: (a, b) => a.x === b.x && a.y === b.y },
  leaderPts: {
    copy: (v) => v.map((p) => ({ ...p })),
    equals: (a, b) => a.length === b.length && a.every((p, i) => p.x === b[i].x && p.y === b[i].y),
  },
  leaderVisible: { copy: (v) => v, equals: (a, b) => a === b },
  fill: { copy: (v) => v, equals: (a, b) => a === b },
  lineCount: { copy: (v) => v, equals: (a, b) => a === b },    // 1 | 2 (1行化/2行化)
  nameScaleX: { copy: (v) => v, equals: (a, b) => a === b },   // 名前の横圧縮率 (長体)。1=圧縮なし
  // 自動 leader (位置駆動で生成・円内で除去) か手動 leader かの区別。`leaderPts` と対で
  // 復元しないと、Undo 後に自動分が消せなくなる / 手動分が位置ルールに上書きされる。
  _auto: { copy: (v) => v, equals: (a, b) => a === b },
};

/** 状態を持つ側 (`LabelState` 実体でも `snapshot()` の結果でもよい) 同士を
 *  `STATE_FIELDS` の等値判定で比べる。片方が欠けていれば「等しくない」。 */
function stateEquals(a, b) {
  if (!a || !b) return false;
  for (const [k, f] of Object.entries(STATE_FIELDS)) {
    const va = a[k];
    const vb = b[k];
    // 未設定 (読込直後に片方だけ欠ける等) は同値判定へ持ち込まず素の比較へ落とす。
    if (va == null || vb == null) {
      if (va !== vb) return false;
      continue;
    }
    if (!f.equals(va, vb)) return false;
  }
  return true;
}

// ── 4. ラベルの表示文字列 ──

/** `<text>` の `tspan` 列から「パーセント行として実際に表示されている文字列」を取り出す。
 *
 *  `data-percent` の値から `${v}%` を組み直さないのは、生成側のこの属性が総和比の絶対値で、
 *  表示文字列と一致しないため (符号付きの `△0.8%`、丸めの結果 総和が 100 を超える `100.8%`)。
 *  行数や長体を変えると `label-state.js` の `rebuildTextContent` が `tspan` を組み直すので、
 *  そこで属性から作り直すと画面の数値が別物へ書き換わる。`data-percent` は表示文字列を
 *  読み取れなかった時の保険としてのみ使う。
 *
 *  @param {Array<{hasX: boolean, text: string}>} tspans 描画順の `tspan` (行頭が `hasX`)
 *  @param {string} name ラベル名 (`data-name`)。1 行構成では表示文字列の接頭辞になる
 *  @param {string|null|undefined} percentAttr `data-percent` の生値
 *  @returns {string} パーセント行の表示文字列 (前後の空白は落とす)
 */
function extractPercentText(tspans, name, percentAttr) {
  // 行頭 (`x` 指定) が 2 つ以上あれば 2 行構成。最後の行頭以降がパーセント行で、長体で挟まる
  // 内側 `tspan` は `x` を持たないので同じ行に属する。
  let lastRow = -1;
  let rowCount = 0;
  for (let i = 0; i < tspans.length; i++) {
    if (tspans[i].hasX) { lastRow = i; rowCount++; }
  }
  if (rowCount >= 2) return tspans.slice(lastRow).map((t) => t.text).join("").trim();

  // 1 行構成は名前とパーセントが同一チャンクに流し込まれているので、名前の分を落とす。
  const whole = tspans.map((t) => t.text).join("").trim();
  if (name && whole.startsWith(name)) return whole.slice(name.length).trim();
  const attr = percentAttr == null ? "" : String(percentAttr).trim();
  return attr === "" ? "" : `${attr}%`;
}

// ── 5. キーボードショートカットの受理判定 ──

/** ショートカットを受け付けてよい状況か。`editor-events.js` の配線の**先頭**で使う関門で、
 *  DOM から切り離して検証できるよう純粋関数にしてある。
 *
 *  - 入力欄 (`input` / `textarea` / `select` / contenteditable) にフォーカスがある間は
 *    どの範囲も受理しない。そのコントロール自身の取り消しや文字入力を横取りするため。
 *  - 文書に紐づく操作 (Undo/Redo・選択解除・矢印ナッジ) は編集画面 (手順 2) だけで受理する。
 *    他の手順ではキャンバスが見えないので、効いたかどうか分からないまま状態が動く。
 *  - 保存は保存画面 (手順 3) でも、開くはどの手順でも受理する。その手順の主目的そのもの。
 *
 *  @param {{tagName?: string, isContentEditable?: boolean}|null|undefined} active フォーカス要素
 *  @param {number} phase ウィザードの手順 (1=開く / 2=調整 / 3=保存)
 *  @param {"document"|"save"|"open"} scope ショートカットの適用範囲
 *  @returns {boolean} 受理してよいか
 */
function acceptsShortcut(active, phase, scope) {
  const tag = active && active.tagName ? String(active.tagName).toUpperCase() : "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return false;
  if (active && active.isContentEditable) return false;
  if (scope === "open") return true;
  if (scope === "save") return phase >= 2;
  return phase === 2;
}

export {
  escapeHtml, round, createSvgEl, safeGetBBox, sanitizeSvg, removedCount, hasFsAccess,
  SVG_PICKER_TYPES, STATE_FIELDS, stateEquals, extractPercentText, acceptsShortcut, MAX_SVG_NODES,
};
