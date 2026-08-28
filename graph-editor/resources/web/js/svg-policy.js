// =============================================================================
// svg-policy.js — 未信頼 SVG の許可リスト (要素 / 属性 / 値文法) — DOM 非依存
// =============================================================================
// 未信頼 SVG を「何を落とすか」ではなく「何を通すか」で定義する方針の一元管理。
// `utils.js` の `sanitizeSvg` はここの述語だけを見て**出力ツリーを組み直す**ため、
// 本モジュールに載っていない要素・属性・値は構造的に出力へ現れない。
//
// なぜ denylist ではないか: 危険物の列挙 (`<script>` / `on*` / `javascript:`) は
// `<foreignObject>` の XHTML `<iframe srcdoc>`・`<animate attributeName="href">`・
// 別プレフィックスの `xl:href`・スキーム内の制御文字 (`java\tscript:`) のように
// 「別の言語機能」で必ず回避される。列挙漏れの向きを「危険物を見落とす」から
// 「便利機能を見落とす (= 表示が欠けるだけ)」へ反転させるのが本モジュールの目的。
//
// DOM に依存しない純粋関数のみを置く (`pie-rules.js` と同じ流儀)。node の vitest から
// そのまま import して迂回入力を単体で検証できるようにするため。
// 配布 exe は `resources/web/js` をディレクトリ丸ごと同梱する (`scripts/build.ps1`)
// ので、`lib/*.cjs` と違い本ファイルの追加でビルド定義を触る必要はない。

// ── 1. 名前空間 ──
// 判定は**名前空間 URI と `localName` の対**で行い、`nodeName` / `attr.name` のような
// プレフィックス付き修飾名は一切比較しない。プレフィックスは文書側が自由に宣言でき
// (`xmlns:xl="...xlink"` → `xl:href`)、文字列比較では無限に別名を作られるため。

const SVG_NS = "http://www.w3.org/2000/svg";
const XMLNS_NS = "http://www.w3.org/2000/xmlns/";

// ── 2. 要素の許可集合 ──
// 前半 8 種は pie-chart の実出力 (`out/_baseline` + `out/svg_js` の全 166 ファイル) を
// 機械走査して得た実測値そのもの。後半 7 種は「外部フェッチもスクリプトも持ちえない」
// 図形・注記要素の余白。
//
// 大小文字は畳まない: XML は case-sensitive で、畳むと `viewBox` / `textLength` /
// `lengthAdjust` のような綴りが崩れて正常系が壊れる。壊れたからと畳み直すと今度は
// `<SCRIPT>` のような別綴りが通る穴になる。比較は常に完全一致。
//
// 意図的に入れていないもの: `foreignObject` (XHTML の実要素を持ち込む窓)、`a` / `use` /
// `image` / `feImage` (URL 参照)、`animate` / `set` / `animateTransform` / `discard`
// (DOM 挿入後に属性値を差し替える)、`script` / `handler`。
// グラデーション (`linearGradient` 等) と `clipPath` は `fill="url(#id)"` の局所参照を
// 許す必要が出るため既定では入れない (paint 文法を `url()` 込みへ緩めない方針)。
const ALLOWED_ELEMENTS = new Set([
  "svg", "defs", "style", "g", "path", "text", "tspan", "rect",
  "circle", "ellipse", "line", "polyline", "polygon", "title", "desc",
]);

// ── 3. 属性の許可集合 ──
// pie-chart 実測の 29 種を核に、エディタが保存時に書き戻す属性 (`transform` /
// `textLength` / `lengthAdjust` / `data-line-count` / `data-name-scale-x` / `stroke-*`)
// と、上記図形要素の幾何・表示属性を足したもの。往復 (保存 → 再読込) が成立する範囲を
// 常に含めること。漏れると「自分の出力を自分で開けない」。
//
// `style` 属性 (インライン CSS) は入れない: 実出力に 0 件で、通すと `background-image:
// url(...)` 等の外部参照が復活する。URL を値に取る属性 (`href` / `xlink:href` / `src`)
// も一切入れない — この結果「生き残った属性値が URL として解釈されることはない」ので、
// スキーム文字列を正規表現で弾く処理そのものが不要になる (制御文字迂回の再来防止)。
const ALLOWED_ATTRS = new Set([
  // 文書・レイアウト
  "viewBox", "width", "height", "preserveAspectRatio", "transform",
  // 識別・分類
  "id", "class",
  // paint / 線
  "fill", "fill-opacity", "fill-rule", "clip-rule", "opacity",
  "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-opacity",
  "stroke-dasharray", "stroke-dashoffset", "stroke-miterlimit", "paint-order",
  // 幾何
  "d", "points", "x", "y", "dx", "dy", "rx", "ry", "cx", "cy", "r",
  "x1", "y1", "x2", "y2",
  // テキスト
  "text-anchor", "dominant-baseline", "alignment-baseline", "font-size",
  "font-family", "font-weight", "font-style", "letter-spacing", "word-spacing",
  "textLength", "lengthAdjust",
  // 表示ヒント
  "shape-rendering", "text-rendering", "visibility", "display",
  // `<style type="text/css">` の 1 箇所だけで使う (下の要素条件つき)
  "type",
]);

// `data-` 接頭辞は原則許可するが、この 3 つはエディタ専有名。入力から持ち込まれると
// `bakeSvg` が保存時に無条件削除するため「開けたのに保存すると消える」不整合になる。
// `data-editor-sel`(選択マーカー) を予約に含めるのは列挙漏れ対策でもある: `class` は
// 値無検査で通す許可属性のため、`is-selected` のような素のクラス名では出口
// `sanitizeSvg` の検知網に掛からない。予約 `data-*` にしておけば、`bakeSvg` の除去列挙が
// 将来漏れても出口検査が `removedCount>0` で必ず保存を止める。
const RESERVED_DATA_ATTRS = new Set(["data-editor", "data-editor-hit", "data-editor-sel"]);

/** 要素を出力へ通してよいか。名前空間と綴りの**両方**が一致した時だけ true。
 *  仮に `foreignObject` を許可集合へ足しても、その中の XHTML `<iframe>` は名前空間が
 *  SVG でないためここで落ちる (二重に閉じている)。 */
function isAllowedElement(localName, namespaceURI) {
  return namespaceURI === SVG_NS && ALLOWED_ELEMENTS.has(localName);
}

/** 属性を出力へ通してよいか。
 *  名前空間つき属性 (`xlink:href` / 任意プレフィックス / `xml:space`) は**一律で落とす**。
 *  `utils.js` 側は `setAttribute` しか使わない = 出力に名前空間つき属性を 1 つも作らない、
 *  という不変条件を保つため (テストはこの不変条件そのものを主張する)。 */
function isAllowedAttr(localName, namespaceURI, elementLocalName) {
  if (namespaceURI !== null) return false;
  if (localName === "type") return elementLocalName === "style";
  if (ALLOWED_ATTRS.has(localName)) return true;
  return localName.startsWith("data-") && !RESERVED_DATA_ATTRS.has(localName);
}

// ── 4. 値の文法 ──

// 素通しする属性値の上限。`d` / `points` は座標列で長くなるため別枠にする。
const MAX_ATTR_VALUE = 4096;
const MAX_PATH_VALUE = 1 << 20;
const LONG_VALUE_ATTRS = new Set(["d", "points"]);

// C0 制御文字 (タブ・改行・復帰を除く) と DEL。`java\tscript:` のような
// 「スキーム内に制御文字を挟む」細工の温床なので、URL 属性を通さない今も値から排除する。
const CONTROL_CHARS = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;

const HEX_COLOR = /^#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i;
// `rgb()` / `hsl()` の引数 3〜4 個。数値・パーセント・角度単位のみを許し、
// 入れ子の関数 (`url()` / `var()` / `expression()`) は文法上入れない。
const COLOR_ARG = "[+-]?(?:\\d+\\.?\\d*|\\.\\d+)(?:%|deg|grad|rad|turn)?";
const COLOR_FN = new RegExp(
  `^(?:rgb|rgba|hsl|hsla)\\(\\s*${COLOR_ARG}(?:\\s*,\\s*|\\s+)${COLOR_ARG}` +
    `(?:\\s*,\\s*|\\s+)${COLOR_ARG}(?:\\s*[,/]\\s*${COLOR_ARG})?\\s*\\)$`,
  "i",
);
// カスタムプロパティ参照。フォールバック引数は取らない (`var(--x, url(...))` を作らせない)。
const CSS_VAR = /^var\(\s*--[a-z0-9-]+\s*\)$/i;

// CSS の名前色 (CSS Color Level 4 の 148 色) + `transparent` / `currentcolor`。
const NAMED_COLORS = new Set(
  ("aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue " +
    "blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk " +
    "crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki " +
    "darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen " +
    "darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue " +
    "dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite " +
    "gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki " +
    "lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan " +
    "lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen " +
    "lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen " +
    "magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen " +
    "mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream " +
    "mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid " +
    "palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum " +
    "powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown " +
    "seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen " +
    "steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke yellow " +
    "yellowgreen transparent currentcolor").split(" "),
);

/** CSS の色として安全に使える値か。受理なら trim 済みの文字列、拒否なら `null`。
 *  `element.style.backgroundColor` への**プロパティ代入**と併用する前提の二重検証で、
 *  `red;background-image:url(https://…)` のような宣言の継ぎ足しと
 *  `#fff"><img src=x onerror=…>` のような markup 脱出の双方をここで落とす。 */
function safeCssColor(value) {
  if (typeof value !== "string") return null;
  const v = value.trim();
  if (!v || v.length > 64) return null;
  if (CONTROL_CHARS.test(v)) return null;
  // 宣言・マークアップ・エスケープの区切り文字が 1 つでもあれば色ではない。
  if (/[;<>"'\\{}]/.test(v)) return null;
  if (HEX_COLOR.test(v)) return v;
  if (COLOR_FN.test(v)) return v;
  if (CSS_VAR.test(v)) return v;
  if (NAMED_COLORS.has(v.toLowerCase())) return v;
  return null;
}

/** paint 属性 (`fill` / `stroke`) の値。色に加えて `none` を許す。
 *  `url(#id)` は許さない — 参照先の `<linearGradient>` / `<clipPath>` を許可集合へ
 *  入れていないため、通しても解決できない参照が残るだけになる。 */
function safePaint(value) {
  const v = String(value).trim();
  if (v.toLowerCase() === "none") return v;
  return safeCssColor(v);
}

/** 属性値の受理判定。受理なら (必要なら正規化した) 文字列、拒否なら `null`。
 *  URL を値に取る属性は `ALLOWED_ATTRS` に 1 つも無いので、ここでスキームを検査する
 *  必要は無い (逆に正規表現でスキームを弾く実装へ戻すと制御文字迂回が復活する)。
 *  残っているのは「値そのものに意味がある」paint と `<style type>` の 2 つだけ。 */
function sanitizeAttrValue(elementLocalName, attrLocalName, value) {
  if (typeof value !== "string") return null;
  const limit = LONG_VALUE_ATTRS.has(attrLocalName) ? MAX_PATH_VALUE : MAX_ATTR_VALUE;
  if (value.length > limit) return null;
  if (CONTROL_CHARS.test(value)) return null;
  if (attrLocalName === "fill" || attrLocalName === "stroke") return safePaint(value);
  if (attrLocalName === "type") return value.trim().toLowerCase() === "text/css" ? "text/css" : null;
  return value;
}

// ── 5. `<style>` の CSS — 認識できた宣言から組み立て直す ──
// 原文を通すと `@import url(https://…)` と `@font-face { src: url(https://…) }` で
// 外部フェッチが立ち、さらにインライン SVG の CSS はアプリ UI のセレクタにも効く
// (`.btn{display:none}` で操作不能にできる)。かといって `<style>` ごと落とすと
// 埋め込みフォントが失われ `getBBox` / `getComputedTextLength` の実測値が変わって
// ヒット領域と長体計算がずれる。
//
// そこで **`(@font-face{...})*` に完全一致する場合のみ受理し、受理した宣言から
// CSS を組み立て直す**。「`@import` を消す」のような denylist にしないこと —
// `@\69mport` (CSS エスケープ) や `/**/` の分断で必ず抜けられる。
// 全消費でない (末尾にゴミが残る) 入力は 1 バイトでも残れば丸ごと捨てる。

const MAX_CSS_INPUT = 4 << 20;

// `@font-face` 内で認識する宣言と、その値の文法。ここに無いプロパティが 1 つでも
// あればブロックごと不受理 (= CSS 全体を捨てる)。
//
// **プロトタイプを持たせない** (`__proto__: null`): 素のオブジェクトリテラルだと
// `Object.prototype` を継承するため、攻撃者が書いた宣言名がそのままキーになる本表では
// `constructor:a` / `__proto__:a` が「未知プロパティ = 拒否」ではなく `Object` や
// `Object.prototype` を返してしまい、続く `re.test(value)` が TypeError になる。
// 例外は `sanitizeSvg` を貫いて `editor-io.js` の `load` まで飛び、キャンバス差し替え前に
// 読込を中断する = 前のファイルの図が新しいファイル名のまま残る (そのまま保存すると
// 旧内容が新ファイル名で書き出される)。参照側の `Object.hasOwn` と二重で閉じる。
const FONT_FACE_VALUE = {
  __proto__: null,
  // 引用符なしのファミリ名は**語の連なり**として書く。`[\w -]` のように文字クラスへ空白を
  // 含めると、区切りの `\s*` と同じ空白に一致して 1 区切りあたり 2 通りの解析が生まれ、
  // 非マッチ入力で 2^n の指数バックトラックになる (85 バイトで 6.5 秒を実測)。
  // 空白の直後に必ず語を要求すれば、区切り直前の空白を名前側が食えないので曖昧さが消える。
  // 入力長ではなく**計算量**の上限であり、`MAX_SVG_INPUT_CHARS` などの大きさの上限では
  // 代替できない (100 バイト未満の入力で刺さる)。
  "font-family":
    /^(?:"[\w .-]{1,64}"|'[\w .-]{1,64}'|[a-z][\w-]{0,63}(?: {1,4}[\w-]{1,64}){0,7})(?:\s*,\s*(?:"[\w .-]{1,64}"|'[\w .-]{1,64}'|[a-z][\w-]{0,63}(?: {1,4}[\w-]{1,64}){0,7}))*$/i,
  "font-weight": /^(?:normal|bold|bolder|lighter|[1-9][0-9]{0,2})$/i,
  "font-style": /^(?:normal|italic|oblique)$/i,
  "font-display": /^(?:auto|block|swap|fallback|optional)$/i,
  "font-stretch": /^(?:normal|(?:ultra|extra|semi)-(?:condensed|expanded)|condensed|expanded|\d{1,3}%)$/i,
  "unicode-range": /^u\+[0-9a-f?]{1,6}(?:-[0-9a-f]{1,6})?(?:\s*,\s*u\+[0-9a-f?]{1,6}(?:-[0-9a-f]{1,6})?)*$/i,
};

// `src` の 1 項目。**`data:` の font 系だけ**を許し、base64 部分の charset を
// `[A-Za-z0-9+/=]` に縛る。charset を縛るのが要点で、`)` を含ませて `url()` を
// 早期に閉じる細工がここで入らなくなる。`http(s):` は文法上どこにも書けない。
const FONT_SRC_ITEM =
  /^url\(\s*data:(?:font\/(?:woff2|woff|ttf|otf|sfnt)|application\/(?:font-woff2|font-woff|x-font-ttf|x-font-otf))\s*;\s*base64\s*,\s*[A-Za-z0-9+/=]+\s*\)(?:\s+format\(\s*"(?:woff2|woff|truetype|opentype|embedded-opentype)"\s*\))?$/i;

/** 括弧の深さと引用符を見ながら区切る (base64 の `data:...;base64,` を壊さないため)。 */
function splitTopLevel(text, sep) {
  const out = [];
  let depth = 0;
  let quote = "";
  let cur = "";
  for (const ch of text) {
    if (quote) {
      cur += ch;
      if (ch === quote) quote = "";
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      cur += ch;
      continue;
    }
    if (ch === "(") depth++;
    else if (ch === ")") depth--;
    if (ch === sep && depth === 0) {
      out.push(cur);
      cur = "";
      continue;
    }
    cur += ch;
  }
  out.push(cur);
  return out;
}

/** `@font-face` ブロック本体の宣言列を検証する。受理なら `prop:value;` 列、拒否なら `null`。 */
function parseFontFaceBody(body) {
  const decls = [];
  for (const raw of splitTopLevel(body, ";")) {
    const part = raw.trim();
    if (!part) continue;
    const colon = part.indexOf(":");
    if (colon < 0) return null;
    const prop = part.slice(0, colon).trim().toLowerCase();
    const value = part.slice(colon + 1).trim().replace(/\s+/g, " ");
    if (!value) return null;
    if (prop === "src") {
      const items = splitTopLevel(value, ",").map((s) => s.trim());
      if (!items.length || items.some((s) => !FONT_SRC_ITEM.test(s))) return null;
      decls.push(`src:${items.join(",")};`);
      continue;
    }
    // `prop` は攻撃者が綴れる文字列なので、表の**自前キーだけ**を引く。`Object.hasOwn` を
    // 挟まないと `constructor` / `__proto__` が継承値を返し、`re.test` が関数でなくなる。
    if (!Object.hasOwn(FONT_FACE_VALUE, prop)) return null;
    const re = FONT_FACE_VALUE[prop];
    if (!re || !re.test(value)) return null;
    decls.push(`${prop}:${value};`);
  }
  return decls;
}

/** `<style>` の CSS を `@font-face` ブロックだけへ縮退させる。
 *  受理した宣言から**新しい文字列を組み立てて**返すので、原文の切り貼りが 1 箇所も
 *  無い (= `]]>` や `</style>` の混入が文法上ありえない)。全体が文法に一致しない場合は
 *  空文字列を返し、呼び出し側は `<style>` ごと出力から外して除去件数へ数える。 */
function sanitizeFontFaceCss(cssText) {
  if (typeof cssText !== "string") return "";
  const s = cssText;
  if (!s.trim() || s.length > MAX_CSS_INPUT) return "";
  // バックスラッシュは CSS のエスケープ表記 (`@\69mport`) の入口。文法側でも弾けるが、
  // 「識別子を綴り替えて allowlist を素通りさせる」道を入口で閉じておく。
  if (s.includes("\\") || CONTROL_CHARS.test(s)) return "";
  const blocks = [];
  let i = 0;
  const skipWs = () => {
    while (i < s.length && /\s/.test(s[i])) i++;
  };
  skipWs();
  while (i < s.length) {
    if (s.slice(i, i + 10).toLowerCase() !== "@font-face") return "";
    i += 10;
    skipWs();
    if (s[i] !== "{") return "";
    i++;
    const end = s.indexOf("}", i);
    if (end < 0) return "";
    const body = s.slice(i, end);
    // 本体に `{` があれば入れ子の規則。文法外なので全体を捨てる。
    if (body.includes("{")) return "";
    i = end + 1;
    const decls = parseFontFaceBody(body);
    if (!decls) return "";
    if (decls.length) blocks.push(`@font-face{${decls.join("")}}`);
    skipWs();
  }
  return blocks.join("");
}

export {
  SVG_NS,
  XMLNS_NS,
  ALLOWED_ELEMENTS,
  ALLOWED_ATTRS,
  isAllowedElement,
  isAllowedAttr,
  sanitizeAttrValue,
  safeCssColor,
  sanitizeFontFaceCss,
};
