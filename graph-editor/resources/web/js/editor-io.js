// =============================================================================
// editor-io.js — SVG 読込 / 保存 (bake) / ファイル選択・ドロップ
// =============================================================================
// `editor.js` の `Editor` インスタンス (`ed`) を第 1 引数に取るファイル I/O 群。
// 開く = `<input type=file>` + D&D / 保存 = ダウンロード固定 (VDI 方針。`hasFsAccess()`
// は常に false — utils.js 参照) という入出力の関所を本モジュールに集める。

import { CONFIG } from "./constants.js";
import { parseTranslate } from "./geom.js";
import { round, createSvgEl, safeGetBBox, sanitizeSvg, removedCount, hasFsAccess, SVG_PICKER_TYPES } from "./utils.js";
import { LabelState } from "./label-state.js";

// ── 1. SVG 読込 & セットアップ (メモリ上の `content` を直接インライン挿入) ──

/** 読込を中止し「何も開いていない」状態へ倒す (理由は利用者へ表示する)。
 *
 *  `load` は先頭で `ed.name` / `ed.history` 等を新しいファイルへ切り替えるため、中断した場合に
 *  キャンバスと `ed.labels` を残すと**前のファイルの図を新しいファイル名のまま保存できる**
 *  状態になる。中断経路は必ずここを通し、表示・状態・履歴をまとめて空へ揃える。
 *
 *  表示上のアイデンティティ (`name` / `currentId`) も戻す。残すと「何も開いていないのに
 *  編集中のファイルがある」表示になり、レールの編集中マークとトップバーのファイル名が
 *  読めなかったファイルを指し続ける。 */
function abortLoad(ed, message) {
  ed.dom.canvas.replaceChildren();
  ed.name = null;
  ed.currentId = null;
  ed.svg = null;
  ed.labels = [];
  ed.overlay = null;
  ed.selected = null;
  ed.setStatus(message, "err");
  ed.updateToolbar();
  ed.renderList();
}

/** ファイル切替 (レール / ファイルカード) の関所。切替先が別ファイルで、未保存の調整が
 *  残っていれば確認を挟む。`load` は `history` / `redoStack` ごと作り直すため、切替えた後は
 *  Undo でも調整を取り戻せない。文言と作法は `editor-events.js` の全体リセットに合わせる。
 *
 *  @returns {Promise<boolean>} 実際に読み込んだか (キャンセルなら false) */
async function switchTo(ed, item) {
  if (!item) return false;
  if (item.id !== ed.currentId && ed.labels.some((s) => ed.isLabelEdited(s))) {
    const ok = window.confirm(
      `「${ed.name}」の調整は保存されていません。破棄して「${item.name}」を開きます。よろしいですか？`,
    );
    if (!ok) return false;
  }
  await load(ed, item);
  return true;
}

async function load(ed, item) {
  if (!item || typeof item.content !== "string") return;
  const seq = ++ed._loadSeq; // この呼び出しの世代 (後勝ち判定用)
  ed.name = item.name;
  ed.currentId = item.id;
  ed.history = [];
  ed.redoStack = [];
  ed.selected = null;
  ed.zoom = 1;
  ed._pie = null;
  ed._leaderStyle = null;
  ed._sliceByName = null;
  ed._sliceAnchor = null;
  // 別ファイルへ切替えるので構造シグネチャ / 参照キャッシュをリセット
  ed._inspSig = null;
  ed._overlaySig = null;
  ed._handles = [];

  // 許可リストに沿って組み直した `<svg>` をインライン挿入 (フォント込みで描画)。
  // `sanitizeSvg` は本文書の `createElementNS` で組んだ木を返すので `importNode` は不要。
  //
  // **例外もここで受ける**: サニタイザ内部の想定外エラー (細工入力で踏ませられる) がここを
  // 抜けると、`ed.name` を新ファイルへ切り替えた後・キャンバス差し替え前で停止し、旧ファイルの
  // 内容が新ファイル名のまま残る。`load` は `async` なので投げても unhandled rejection として
  // 握り潰され、利用者には「何も起きていない」ようにしか見えない。判定不能は解釈不能へ倒す。
  let res = null;
  try {
    res = sanitizeSvg(item.content);
  } catch {
    res = null;
  }
  if (!res) {
    abortLoad(ed, `${item.name}: SVG を解釈できませんでした (壊れているか、上限を超えています)`);
    return;
  }
  // ラベル数の上限。以降の処理 (ヒット領域の生成・オーバーレイ・レール描画・履歴の
  // スナップショット) はいずれもラベル数に比例するため、ここで拒否しないと細工 SVG 1 枚で
  // アプリが操作不能になる。黙って切り捨てず件数を出して読込ごと中止する — 一部だけ編集
  // できる状態にすると、保存時に残りを含めて書き出してしまうため。
  const labelCount = res.root.querySelectorAll("#labels > g.label").length;
  if (labelCount > CONFIG.maxLabels) {
    abortLoad(ed, `${item.name}: ラベルが多すぎます (${labelCount} 個 / 上限 ${CONFIG.maxLabels} 個)。読み込みを中止しました`);
    return;
  }
  ed.dom.canvas.replaceChildren(res.root);
  const svg = res.root;
  ed.svg = svg;

  // ベースサイズを `viewBox` から取得
  const vb = (svg.getAttribute("viewBox") || `0 0 ${CONFIG.defaultViewBox.w} ${CONFIG.defaultViewBox.h}`).split(/\s+/).map(Number);
  ed.baseW = vb[2] || CONFIG.defaultViewBox.w;
  ed.baseH = vb[3] || CONFIG.defaultViewBox.h;
  ed.applyZoom();

  // 編集画面(手順2)を表示してから `getBBox` を測る。非表示(`display:none`)のままだと
  // `getBBox` が 0 を返し、ヒット領域や引出線の既定座標が崩れるため必ず先に表示する。
  ed.goPhase(2);

  // 埋め込みフォントの読込を待ってから `getBBox` (正確なヒット領域のため)
  try {
    await document.fonts.ready;
  } catch {
    /* fonts API 非対応でも続行 */
  }
  // await 中に別ファイルが読み込まれていたら後勝ち。古い継続は中断する。
  if (seq !== ed._loadSeq) return;

  // 各ラベルにヒット領域を付与 + 状態構築。
  // **測定 (`getBBox`) と DOM 変更を交互にしない**: ヒット矩形を 1 個挿しては次のラベルを
  // 測る形だと、挿入のたびにレイアウトが無効化されてラベル数ぶんの強制同期レイアウトが
  // 直列に走る。「全部測る (読み) → 全部挿す (書き)」の 2 相に分けると、レイアウトは
  // 最初の 1 回で済む。
  ed.labels = [];
  const labelGroups = svg.querySelectorAll("#labels > g.label");
  labelGroups.forEach((g) => {
    // `<text>` を持たない `g.label` は `LabelState` が組み立てられない (以降の描画も
    // 成立しない)。細工 SVG で確実に踏めるので、例外で読込全体を落とさず読み飛ばす。
    if (!g.querySelector("text")) return;
    ed.labels.push(new LabelState(g, ed));
  });
  // 読み相: DOM を 1 バイトも変更しない (ここで書くと次の `getBBox` が再レイアウトを強いる)。
  const boxes = ed.labels.map((s) => safeGetBBox(s.text));
  // 書き相: 測定済みの bbox から矩形を組んで挿す (この相では計測しない)。
  ed.labels.forEach((s, i) => attachHitArea(ed, s, boxes[i]));

  // ハンドル用オーバーレイ `<g>` (最前面)
  const overlay = createSvgEl("g", { id: "editor-overlay", "data-editor": "1" });
  svg.appendChild(overlay);
  ed.overlay = overlay;

  // 背景クリックで選択解除
  svg.addEventListener("pointerdown", (e) => {
    if (e.target === svg || e.target.closest("#slices")) ed.selectLabel(null);
  });

  ed.markDirty({ overlay: true, inspector: true });
  ed.flushNow();
  ed.updateToolbar();
  ed.highlightActiveInList();
  // 落とした分は黙って消さずに件数で知らせる。「開いたのに一部が出ない」理由が
  // 利用者に見えないと、サニタイザの誤検知にも気づけないため。`err` は
  // `.skip-note.err` (警告色) + トーストで、注意を引く経路として流用する。
  const dropped = removedCount(res.removed);
  if (dropped > 0) {
    ed.setStatus(`${item.name}  (ラベル ${ed.labels.length} 個 / 許可外の要素・属性 ${dropped} 件を除去)`, "err");
  } else {
    ed.setStatus(`${item.name}  (ラベル ${ed.labels.length} 個)`);
  }
}

/** ラベルにドラッグ用の透明ヒット矩形 (`<rect>`) を追加。
 *  `bbox` は**呼び出し側が測って渡す** — ここで `getBBox` を呼ぶと DOM 変更と計測が交互に
 *  なり、ラベル数ぶんの強制同期レイアウトになる (`load` の読み相/書き相の分離を参照)。 */
function attachHitArea(ed, s, bbox) {
  const pad = CONFIG.hitPadding;
  const rect = createSvgEl("rect", {
    class: "label-hit", "data-editor-hit": "1",
    x: bbox.x - pad, y: bbox.y - pad,
    width: bbox.width + pad * 2, height: bbox.height + pad * 2,
  });
  s._hitRect = rect;
  // `text` と同じ transform を適用して追従させる
  s.syncHit();
  rect.addEventListener("pointerdown", (e) => ed.startTextDrag(e, s));
  // 最前面 (glyph の隙間も含めて bbox 全体を掴めるよう `text` の上に重ねる)
  s.g.appendChild(rect);
}

// ── 2. 保存 (baking → ダウンロード) ──

async function save(ed) {
  if (!ed.svg) return;
  // 保留中の描画を確定させてから DOM を読む
  ed.flushNow();
  const out = bakeSvg(ed);
  // 出口の自己検証: 書き出す文字列を入口と**同じ** `sanitizeSvg` に通し、1 件でも
  // 落ちるなら保存を中止する。取り込み時に許可外が残っていない限り除去件数は 0 に
  // なるはずで、0 でなければ入口の実装が壊れた合図 (下流の閲覧者へ能動コンテンツを
  // 持ち出す事故を、入口の穴に依存せず出口で止める)。
  // 例外は `null` 扱いにする (入口側の読込中断 `abortLoad` と同じ倒し方) — try/catch を
  // 欠くと例外は unhandled rejection になり、保存ボタンを押しても何も起きない無言失敗になる。
  let check = null;
  try {
    check = sanitizeSvg(out);
  } catch {
    check = null;
  }
  if (!check || removedCount(check.removed) > 0) {
    ed.setStatus("保存を中止しました: 出力に許可されていない内容が含まれています", "err");
    return;
  }
  const markSaved = () => {
    const it = ed.items.find((i) => i.id === ed.currentId);
    if (it) it.edited = true;
    ed.renderList();
    ed.highlightActiveInList();
  };
  if (hasFsAccess()) {
    ed.setStatus("保存先を選択してください…");
    try {
      const handle = await window.showSaveFilePicker({
        suggestedName: ed.name || "edited.svg",
        types: SVG_PICKER_TYPES,
      });
      const w = await handle.createWritable();
      await w.write(out);
      await w.close();
      ed.setStatus(`保存しました → ${handle.name}`, "ok");
      markSaved();
    } catch (e) {
      if (e && e.name === "AbortError") ed.setStatus("保存をキャンセルしました");
      else ed.setStatus(`保存に失敗しました: ${e}`, "err");
    }
  } else {
    // 非対応ブラウザ: `Blob` をダウンロード (ブラウザの保存先へ)
    downloadSvg(out, ed.name || "edited.svg");
    ed.setStatus("ダウンロードフォルダに保存しました", "ok");
    markSaved();
  }
}

/** FS Access API 非対応時のフォールバック保存 (`Blob` ダウンロード) */
function downloadSvg(text, name) {
  const blob = new Blob([text], { type: "image/svg+xml" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = /\.svg$/i.test(name) ? name : `${name}.svg`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** 編集を恒久座標へ焼き込み、エディタ専用要素を除去したクリーン SVG 文字列を返す */
function bakeSvg(ed) {
  const clone = ed.svg.cloneNode(true);

  // エディタ専用要素を除去
  clone.querySelectorAll("[data-editor], [data-editor-hit]").forEach((el) => el.remove());
  // 選択マーカー(予約 `data-editor-sel`)を除去。この除去列挙が漏れても、予約 `data-*`
  // である以上は出口 `sanitizeSvg` の `removedCount>0` が必ず保存を止める(svg-policy.js
  // 参照)ので、ここでの除去は性能上の先回りに過ぎない。
  clone.querySelectorAll("[data-editor-sel]").forEach((el) => el.removeAttribute("data-editor-sel"));

  // 表示用に付けた width/height (ズーム) を元サイズへ戻す
  clone.setAttribute("width", `${ed.baseW}px`);
  clone.setAttribute("height", `${ed.baseH}px`);

  // 各ラベル: `text` の transform を `x`/`y` へ焼き込み、非表示 leader を除去
  clone.querySelectorAll("#labels > g.label").forEach((g) => {
    const text = g.querySelector("text");
    if (text) {
      const t = parseTranslate(text.getAttribute("transform"));
      if (t.x || t.y) {
        const x = parseFloat(text.getAttribute("x") || "0") + t.x;
        const y = parseFloat(text.getAttribute("y") || "0") + t.y;
        text.setAttribute("x", round(x));
        text.setAttribute("y", round(y));
        text.querySelectorAll("tspan").forEach((ts) => {
          if (ts.hasAttribute("x")) ts.setAttribute("x", round(parseFloat(ts.getAttribute("x")) + t.x));
          // `dy` は相対値なので不変
        });
        text.removeAttribute("transform");
      }
    }
    const path = g.querySelector("path");
    if (path) {
      if (path.style.display === "none") {
        path.remove();
      } else {
        // 表示用に付けた `display` だけ消す。入力由来の inline `style` 属性は
        // サニタイザが通さないので、ここに残るのはエディタが書いたものだけ。
        path.style.removeProperty("display");
        if (!path.getAttribute("style")) path.removeAttribute("style");
      }
    }
  });

  const xml = new XMLSerializer().serializeToString(clone);
  return `<?xml version="1.0" encoding="UTF-8"?>\n${xml}`;
}

// ── 3. ファイル選択 / ドロップ (開く) ──

async function openFiles(ed) {
  ed.setStatus("ファイルを選択してください…");
  let files = [];
  if (hasFsAccess()) {
    let handles;
    try {
      handles = await window.showOpenFilePicker({ multiple: true, types: SVG_PICKER_TYPES });
    } catch (e) {
      if (e && e.name === "AbortError") { ed.setStatus("ファイルが選択されませんでした"); return; }
      ed.setStatus(`読込に失敗しました: ${e}`, "err");
      return;
    }
    for (const h of handles) {
      try {
        const file = await h.getFile();
        files.push({ name: file.name, content: await file.text() });
      } catch (e) {
        files.push({ name: h.name || "(no name)", content: "", error: String(e) });
      }
    }
  } else {
    files = await pickFilesFallback();
  }
  if (!files || !files.length) {
    ed.setStatus("ファイルが選択されませんでした");
    return;
  }
  await addAndOpen(ed, files);
}

/** ドラッグ＆ドロップされた .svg ファイルを取り込む (手順1 のドロップゾーン) */
async function handleDrop(ed, dt) {
  if (!dt) return;
  const dropped = [...(dt.files || [])].filter((f) => /\.svg$/i.test(f.name) || f.type === "image/svg+xml");
  if (!dropped.length) { ed.setStatus("SVG ファイルをドロップしてください"); return; }
  const files = [];
  for (const file of dropped) {
    try { files.push({ name: file.name, content: await file.text() }); }
    catch (e) { files.push({ name: file.name, content: "", error: String(e) }); }
  }
  await addAndOpen(ed, files);
}

/** 取得済みファイル群を items へ登録し、先頭を開いて手順2 へ進む (openFiles / D&D 共通) */
async function addAndOpen(ed, files) {
  // 同名でも別ファイルとして区別したいので `name` で重複排除せず、各々へ一意 `id` を振る。
  const added = files.map((f) => {
    const it = { ...f, id: ++ed._itemSeq, edited: false };
    ed.items.push(it);
    return it;
  });
  ed.renderList();
  await load(ed, added[0]);
  ed.goPhase(2);
}

/** FS Access API 非対応時のフォールバック: `<input type=file>` で複数選択 */
function pickFilesFallback() {
  return new Promise((resolve) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".svg,image/svg+xml";
    input.multiple = true;
    input.style.display = "none";
    let done = false;
    const finish = async () => {
      if (done) return;
      done = true;
      const out = [];
      for (const file of [...(input.files || [])]) {
        out.push({ name: file.name, content: await file.text() });
      }
      input.remove();
      resolve(out);
    };
    input.addEventListener("change", finish);
    // キャンセル検知 (`focus` が戻り `files` が空なら空配列で解決)
    window.addEventListener("focus", () => setTimeout(() => {
      if (!done && (!input.files || !input.files.length)) { done = true; input.remove(); resolve([]); }
    }, 500), { once: true });
    document.body.appendChild(input);
    input.click();
  });
}

export { load, switchTo, save, bakeSvg, openFiles, handleDrop };
