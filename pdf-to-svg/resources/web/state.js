// =============================================================================
// state.js — 4 ステップ状態機械の状態オブジェクトと遷移・導出ロジック
// =============================================================================
// フロントの可変変数を単一の状態オブジェクト `S` へ集約し、状態にしか触れない
// 導出・遷移関数を同居させる。
// DOM には一切触れない (書き出し範囲のテキスト入力値などは引数で受ける) ため、
// 実ブラウザの単体 (`test/test_pdftosvg_state_js.py`) が状態機械を検証できる。
// 描画 (`render`) は呼ばない — 遷移後の再描画は呼び出し側 `app.js` の責務。

// ── 1. 状態オブジェクト (唯一の可変状態) ──

var S = {
  FILES: [],            // [{name, pages, size}]
  PAGES: [],            // [{fileIndex, pageInFile}] (全ファイル通しの平坦列)
  FILE_START: [],       // fileIndex -> 通し先頭ページ index
  TOTAL: 0,
  scanned: [],           // ページごとの純スキャン判定 (`state` の `scanned[]`)。手順 2 の対象外の判定源
  matches2: [],          // ページごとの {applied, pending} (辞書に一致した箇所の 置換済み / 未置換 の件数)
  edits3: [],            // ページごとの {removed, borders, covers} (削除 / 枠線 / 上書き の件数)
  phase: 1,             // ウィザード手順 (1=取込 / 2=置換 / 3=削除 / 4=書き出し)
  page: 0,              // 現在ページ (通し index)
  filterFor: { 2: "matched", 3: "all" },   // レールの絞り込み (手順 2: matched|all / 手順 3: all|edited)
  collapsed: {},        // "step:fi" -> true (レールのファイル折り畳み)
  tool: null,           // 手順3 ツール (null=無選択 / crop / border / cover)。無選択でもクリックでの要素選択は効く
  cropDrag: null,       // 範囲ドラッグ中の状態 {origin,rubber,mode}
  dragMoved: false,     // 直前の mouseup がドラッグ由来か (続けて飛ぶ click を握り潰す)
  coverText: "",        // 上書きツールの置換語 (空なら矩形だけ)
  coverSel: null,       // 上書きツールで選んでいる要素 id (null = 未選択。入力欄は次に置く語)
  coverDrag: null,      // 上書きの移動・伸縮中の状態 (`cover.js` が使う)
  elSel: {},            // "fi:pi" -> {elId:true} (要素選択)
  svgCache: {},         // "fi:pi" -> {svg,width,height}
  zoomFor: { 2: 1, 3: 1, 4: 1 },        // 手順2/3/4 のキャンバス内ズーム倍率
  borderColor: "#000000",       // 枠線ツールの色 (未選択のとき = 次に置く枠線の色)
  borderWidth: 1,       // 枠線ツールの太さ (pt。未選択のとき = 次に置く枠線の太さ)
  borderSel: null,      // 枠線ツールで選んでいる要素 id (null = 未選択。入力欄は次に置く値)
  borderDrag: null,     // 枠線の移動・伸縮中の状態 (`border.js` が使う)
  expMode: "all",       // 書き出しモード: page/all/spec
  expFile: 0,           // spec モードの対象ファイル
  lastChanges: [],       // 直近の `planPage` 結果 (`renderConfirm` と SVG 差替え後の再描画で共有)
  // ── グレーモード (図だけをグレースケールで書き出す) ──
  gray: false,          // 手順 1 のチェック。ON で手順 2・3 を飛ばし、手順 4 が図の選択画面になる
  figCand: {},          // "fi:pi" -> [{x,y,w,h}] サーバが検出した候補 (取得済みページのみ)
  figSel: {},           // "fi:pi" -> [{x,y,w,h}] 採用した矩形 (検出結果はここへ複製され、以後は利用者のもの)
  figDrag: null,        // ハンドル伸縮・空白ドラッグ中の状態 (figure.js が使う)
};

// ── 2. 導出 (現在ページの別名参照) ──

function pkey() { var pg = S.PAGES[S.page]; return pg.fileIndex + ":" + pg.pageInFile; }
function curElSel() { var k = pkey(); return (S.elSel[k] = S.elSel[k] || {}); }

function figKey(pg) { return pg.fileIndex + ":" + pg.pageInFile; }
/** ページ SVG キャッシュが取りうる 2 キー (カラー / グレー)。`invalidate` はモードを問わず
 *  両方消したいのでこちらを使い、`svgKey` は現在のモードに応じてどちらか片方を返す
 *  (キー生成の書式をここ 1 箇所にまとめ、2 箇所で手組みして食い違うのを防ぐ)。 */
function svgKeys(fi, pi) { return [fi + ":" + pi, fi + ":" + pi + ":g"]; }
/** ページ SVG キャッシュのキー。グレーは別の SVG なのでキーを分ける (モード切替で混ざらない) */
function svgKey(fi, pi) { return svgKeys(fi, pi)[S.gray ? 1 : 0]; }
/** 通しページ g の採用矩形配列 (無ければ作る)。呼ぶだけで `S.figSel` に空配列を作ってしまうため、
 *  「まだ候補を記録していない」を見分けたい側 (`seedFigSel`) からは使わない (`figSelPeek` を使う)。 */
function figSelOf(g) {
  var pg = S.PAGES[g]; if (!pg) return [];
  var k = figKey(pg);
  return (S.figSel[k] = S.figSel[k] || []);
}
/** 通しページ g の採用矩形配列を作らずに覗く (無ければ空配列を返すだけ) */
function figSelPeek(g) {
  var pg = S.PAGES[g]; if (!pg) return [];
  return S.figSel[figKey(pg)] || [];
}
function figCount() { var n = 0; S.PAGES.forEach(function (pg, g) { n += figSelPeek(g).length; }); return n; }
/** サーバの候補を記録し、まだ候補を記録していないページだけ採用へ複製する。
 *  採用を複製するのは候補を初めて記録するときだけ。以後の再取得は利用者の採用を触らない
 *  (判定は `S.figSel` の有無ではなく `S.figCand` の Array 判定で行う。取得中に置く `null` の
 *  途中経過も未記録として扱いたいため、`undefined` と `null` の両方を「初回」とみなす)。 */
function seedFigSel(g, rects) {
  var pg = S.PAGES[g]; if (!pg) return;
  var k = figKey(pg);
  var firstTime = !Array.isArray(S.figCand[k]);
  S.figCand[k] = rects.map(function (r) { return { x: r.x, y: r.y, w: r.w, h: r.h }; });
  if (firstTime) {
    S.figSel[k] = rects.map(function (r) { return { x: r.x, y: r.y, w: r.w, h: r.h }; });
  }
}

// ── 3. 状態遷移 ──

// 旧ページ列と新ページ列が同一かを判定する。箇所単位の戻す/置換は 1 要素だけ変えて
// `state` を取り直すため、ファイル追加・削除が絡まない限りページ列自体は変わらない。
// この判定を通ったときだけ折り畳み・図の候補・採用を引き継ぐ (`applyState` 参照)。
function samePageList(oldPages, newPages) {
  if (oldPages.length !== newPages.length) return false;
  return oldPages.every(function (pg, i) {
    return pg.fileIndex === newPages[i].fileIndex && pg.pageInFile === newPages[i].pageInFile;
  });
}

/** サーバの `state` RPC 結果を取り込み、派生列 (FILE_START) とキャッシュを組み直す。
 *
 * ページの確認状態は持たないので、件数 (`matches2` / `edits3`) とスキャン判定 (`scanned`) は
 * 毎回そのまま取り込む。旧形式 (列なし) や短い列は 0 件・非スキャン扱いへ倒す (例外にしない)。
 * ファイル追加・削除でページ列が変わったときだけ、通し index をキーに持つ折り畳み・図の
 * 候補・採用を捨てる (持ち越すと別のページ・別のファイルを指す)。
 */
function applyState(st) {
  var samePages = samePageList(S.PAGES, st.pages);
  S.FILES = st.files; S.PAGES = st.pages; S.TOTAL = st.total;
  S.scanned = S.PAGES.map(function (_pg, g) { return !!(st.scanned && st.scanned[g]); });
  S.matches2 = S.PAGES.map(function (_pg, g) {
    var m = st.matches2 && st.matches2[g];
    return { applied: m ? (m[0] | 0) : 0, pending: m ? (m[1] | 0) : 0 };
  });
  S.edits3 = S.PAGES.map(function (_pg, g) {
    var e = st.edits3 && st.edits3[g];
    return { removed: e ? (e[0] | 0) : 0, borders: e ? (e[1] | 0) : 0, covers: e ? (e[2] | 0) : 0 };
  });
  if (!samePages) { S.collapsed = {}; S.figCand = {}; S.figSel = {}; }
  S.FILE_START = []; var s = 0;
  S.FILES.forEach(function (f, i) { S.FILE_START[i] = s; s += f.pages; });
  S.svgCache = {}; S.elSel = {};
  if (S.page >= S.TOTAL) S.page = 0;
}

/** ページ SVG のキャッシュを全ページ分捨てる。
 *
 * Undo/Redo は現在ページ以外への編集も巻き戻すため、現在ページだけ作り直すと
 * 他ページが古い SVG のまま残る。
 */
function invalidateAll() { S.svgCache = {}; }

/** 通しページ g の辞書一致の件数 (置換済み + 未置換)。0 なら「辞書に一致しないページ」 */
function matchCount(g) { var m = S.matches2[g]; return m ? m.applied + m.pending : 0; }
/** 通しページ g の編集の件数 (削除 + 枠線 + 上書き)。0 なら「編集していないページ」 */
function editCount(g) { var e = S.edits3[g]; return e ? e.removed + e.borders + e.covers : 0; }

/** レールに出す通しページ index の配列。絞り込み (`S.filterFor`) を通した結果で、
 *  手順 2 はスキャンページを絞り込みに関わらず出さない (辞書が構造的に当たらないため)。
 *  手順 3 はスキャンページも出す (上書きの対象になる)。レールの行・ファイル行の件数はここを通す。 */
function railPages(phase) {
  var filt = S.filterFor[phase]; var out = [];
  S.PAGES.forEach(function (_pg, g) {
    if (phase === 2) {
      if (S.scanned[g]) return;
      if (filt === "matched" && !matchCount(g)) return;
    } else if (filt === "edited" && !editCount(g)) return;
    out.push(g);
  });
  return out;
}
/** 手順 2 の「次の一致ページ」。from より後ろで辞書に一致 (スキャン以外) のページ、無ければ先頭から。
 *  無ければ -1 */
function nextMatched(from) {
  for (var i = from + 1; i < S.TOTAL; i++) if (!S.scanned[i] && matchCount(i)) return i;
  for (var j = 0; j < from; j++) if (!S.scanned[j] && matchCount(j)) return j;
  return -1;
}
/** ファイル fi のスキャンページ数 (手順 1 のカードのバッジ) */
function scannedCountOf(fi) {
  var f = S.FILES[fi]; if (!f) return 0;
  var start = S.FILE_START[fi] || 0; var n = 0;
  for (var p = 0; p < f.pages; p++) if (S.scanned[start + p]) n++;
  return n;
}
/** スキャンページの総数 (手順 1 のバナー・手順 2 の見出し) */
function scannedTotal() { return S.scanned.filter(Boolean).length; }
/** 手順 2 のまとめ: 置換済み・未置換の箇所数、一致のあるページ数、スキャンページ数 */
function matchTotals() {
  var t = { applied: 0, pending: 0, pages: 0, scanned: scannedTotal() };
  S.matches2.forEach(function (m, g) {
    if (S.scanned[g]) return;
    t.applied += m.applied; t.pending += m.pending;
    if (m.applied + m.pending) t.pages++;
  });
  return t;
}
/** 手順 3 のまとめ: 編集したページ数と、削除・枠線・上書きの件数 */
function editTotals() {
  var t = { pages: 0, removed: 0, borders: 0, covers: 0 };
  S.edits3.forEach(function (e) {
    t.removed += e.removed; t.borders += e.borders; t.covers += e.covers;
    if (e.removed + e.borders + e.covers) t.pages++;
  });
  return t;
}

/** 全ページが純スキャンか。ページが無ければ false (手順 1 の「次へ」は別途無効) */
function skipsPhase2() { return S.TOTAL > 0 && S.scanned.every(Boolean); }
/** 手順 2 に入ったとき表示するページ: 辞書に一致 (スキャン以外) の最初、無ければスキャン以外の最初、
 *  無ければ 0 */
function firstEditablePage2() {
  for (var i = 0; i < S.TOTAL; i++) if (!S.scanned[i] && matchCount(i)) return i;
  for (var j = 0; j < S.TOTAL; j++) if (!S.scanned[j]) return j;
  return 0;
}
/** 手順 2 に入る直前に呼ぶ。表示中のページがスキャンならレールに出ているページへ差し替える
 *  (レールに無いページに立つと、キャンバスに画像だけが出て何の画面か分からない)。スキャン以外に
 *  居るときは動かさない (「戻る」で見ていたページを保つ)。 */
function landOnPhase2() { if (S.scanned[S.page]) S.page = firstEditablePage2(); }
/** 手順 1 の「次へ」の行き先。グレーモードが最優先、次に手順 2 の省略 */
function phaseAfterLoad() { return S.gray ? 4 : (skipsPhase2() ? 3 : 2); }
/** 手順 3 の「戻る」の行き先。手順 2 を省略していれば手順 1 へ */
function phaseBeforeTrim() { return skipsPhase2() ? 1 : 2; }
/** 手順 4 の「戻る」の行き先 */
function phaseBeforeExport() { return S.gray ? 1 : 3; }
/** ステップバーのクリックで移ってよい手順か */
function stepAllowed(n) {
  if (S.gray) return n === 1 || n === 4;
  if (skipsPhase2() && n === 2) return false;
  return true;
}

/** 手順を移るときに、手順 3 の編集で使う一時状態を既定へ戻す。再描画は呼び出し側。
 *
 * 対象は要素の選択 (青枠)・上書きの選択 (緑枠)・枠線の選択・ツール・`dragMoved` の 5 つ。手順を
 * またいで選択・ツールを残すと、戻った直後のクリックが残っていた選択を外して「削除」が効かなく
 * なり、ツールも「上書き」や「範囲削除」のまま始まってしまう。`dragMoved` も一時状態の一つで、
 * ページ外の余白で mouseup したドラッグの直後は `wireEditTools` を経由せずここでツールが
 * `null` に戻ることがあり (「次へ」「戻る」・ステップバー)、そのときにフラグを残すと手順 3 へ
 * 戻ってからの最初の要素クリックが握り潰される。手順を移る経路 (「次へ」・「戻る」・ステップバー)
 * はすべてここを通す。表示中のページ (`S.page`) はここでは触らない (戻ったときに
 * 見ていたページを保つため)。
 */
function resetPhaseUi() {
  S.elSel = {};
  S.coverSel = null;
  S.borderSel = null;
  S.tool = null;
  S.dragMoved = false;
}

/** 手順を 1 つ進める (2→3 / 3→4)。手順 3 の一時状態も戻す。再描画は呼び出し側 */
function advancePhase() {
  resetPhaseUi();
  if (S.phase === 2) { S.phase = 3; S.page = 0; } else if (S.phase === 3) S.phase = 4;
}

// ── 4. 書き出し範囲の算出 (spec 入力値は引数で受ける — DOM 非依存) ──

/** 現在のモードで書き出す [{fileIndex, pageInFile}] を返す (page モードは対象外) */
function exportPageList(specValue, parseSpecFn) {
  if (S.expMode === "all") return S.PAGES.slice();
  if (S.expMode === "spec") {
    var fi = S.expFile; if (!S.FILES[fi]) return [];
    return parseSpecFn(specValue, S.FILES[fi].pages)
      .map(function (n) { return { fileIndex: fi, pageInFile: n - 1 }; });
  }
  return []; // page モードは exportPage を使うため対象外
}

function expCount(specValue, parseSpecFn) {
  return S.expMode === "page" ? (S.TOTAL ? 1 : 0) : exportPageList(specValue, parseSpecFn).length;
}

/** グレーモードの書き出し対象: 採用矩形を 1 図 = 1 SVG に展開する (page モードは表示中のページだけ) */
function exportFigureList() {
  var pages = S.expMode === "page" ? [S.page] : S.PAGES.map(function (_pg, g) { return g; });
  var out = [];
  pages.forEach(function (g) {
    var pg = S.PAGES[g]; if (!pg) return;
    figSelPeek(g).forEach(function (r, i) {
      out.push({ fileIndex: pg.fileIndex, pageInFile: pg.pageInFile,
        clip: { x: r.x, y: r.y, w: r.w, h: r.h }, figIndex: i + 1, grayscale: true });
    });
  });
  return out;
}

/** 手順 4 右ペイン「採用した図」一覧: 採用矩形を `{fileIndex, pageInFile, figIndex, rect}` に
 *  展開する (DOM 非依存。`figSelPeek` 経由で読むだけなので非破壊)。`exportFigureList` は
 *  書き出し範囲 (`S.expMode`) で対象を絞るのに対し、一覧は「今なにを採用済みか」を見せる
 *  ものなので `S.expMode` に関係なく常に全ページ分を返す。 */
function adoptedFigures() {
  var out = [];
  S.PAGES.forEach(function (pg, g) {
    figSelPeek(g).forEach(function (r, i) {
      out.push({ fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, figIndex: i + 1,
        rect: { x: r.x, y: r.y, w: r.w, h: r.h } });
    });
  });
  return out;
}

/** 項目列を送信サイズ予算で塊へ分ける。`sizeOf` は 1 件のバイト数を返す関数。
 *
 * ZIP 集約 (`zipEntries`) は SVG 本文をまるごと 1 リクエストで送るため、サーバの
 * RPC 本文上限を超えると書き出しごと失敗する。予算に収まる塊へ分けて ZIP を複数本に
 * する。1 件だけで予算を超える項目はその 1 件だけの塊にする (黙って落とすより、
 * 上限超過の失敗として利用者へ返すほうが取りこぼしに気付ける)。
 */
function chunkBySize(items, sizeOf, budget) {
  var chunks = [];
  var cur = [];
  var sum = 0;
  items.forEach(function (it) {
    var n = sizeOf(it);
    if (cur.length && sum + n > budget) { chunks.push(cur); cur = []; sum = 0; }
    cur.push(it); sum += n;
  });
  if (cur.length) chunks.push(cur);
  return chunks;
}

/** ZIP のファイル名。対象が 1 PDF ならその名前を継ぎ、複数ファイル混在なら汎用名にする。
 *  グレーモードは `_gray` を挟み、Downloads でカラー版と衝突させない */
function zipName(list) {
  var fis = {};
  list.forEach(function (it) { fis[it.fileIndex] = 1; });
  var keys = Object.keys(fis);
  var suffix = S.gray ? "_gray_svg.zip" : "_svg.zip";
  if (keys.length === 1 && S.FILES[+keys[0]]) {
    return S.FILES[+keys[0]].name.replace(/\.pdf$/i, "") + suffix;
  }
  return S.gray ? "svg_export_gray.zip" : "svg_export.zip";
}

export {
  S, pkey, curElSel,
  figKey, svgKey, svgKeys, figSelOf, figSelPeek, figCount, seedFigSel, exportFigureList, adoptedFigures,
  matchCount, editCount, railPages, nextMatched, scannedCountOf, scannedTotal, matchTotals, editTotals,
  phaseAfterLoad, phaseBeforeExport, phaseBeforeTrim, stepAllowed, skipsPhase2, firstEditablePage2, landOnPhase2,
  applyState, invalidateAll, resetPhaseUi, advancePhase,
  exportPageList, expCount, zipName, chunkBySize,
};
