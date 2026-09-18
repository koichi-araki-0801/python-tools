// =============================================================================
// app.js — PdfToSvg フロントエンド (4 ステップ状態機械の本体)
// =============================================================================
// 役割: 4 ステップ状態機械として、データ・ページ描画・編集・書き出しを
// Python バックエンド (`window.rpc`) に接続する。状態に依存しない純粋ヘルパは
// `dom.js` / `geometry.js` が持つ (type="module" で読込)。
import { esc, svg } from "./dom.js";
import { clientToPage, parseSpec, rectFromDrag, pageSizeOf } from "./geometry.js";
import {
  S, curElSel,
  applyState, resetPhaseUi, advancePhase,
  exportPageList, expCount, zipName, chunkBySize,
  figKey, svgKey, svgKeys, figSelOf, figSelPeek, figCount, seedFigSel, exportFigureList, adoptedFigures,
  phaseAfterLoad, phaseBeforeExport, phaseBeforeTrim, stepAllowed, skipsPhase2, firstEditablePage2, landOnPhase2,
  matchCount, nextMatched, scannedCountOf, scannedTotal, matchTotals, editTotals,
} from "./state.js";
import { fileIcon, xIcon, ckMark } from "./icons.js";
import { initRail, buildRail } from "./rail.js";
import { initPageJump, buildPageJump } from "./page-jump.js";
import { initFigure, buildFigRail, buildFigSelist, drawFigOverlay, installFigDrag } from "./figure.js";
import { initCover, drawCoverOverlay, installCoverDrag, commitCoverText, clearCoverSel } from "./cover.js";
import { initBorder, drawBorderOverlay, installBorderDrag, commitBorderStyle, clearBorderSel } from "./border.js";

(function () {
  "use strict";

  var app = document.getElementById("app");

  // ── 1. アイコン ── (icons.js が担う)

  // ── 2. 状態 ──
  // 可変状態は state.js の `S` に集約 (導出・遷移関数も同居)。ここは表示定数のみ。
  // ── 3. ファイル入出力 ──
  // File System Access API のネイティブピッカー (`showOpenFilePicker` / `showSaveFilePicker` /
  // `showDirectoryPicker`) は VDI/リモートデスクトップの管理された Edge でレンダラごとクラッシュ
  // するため一切使わない。開く = 従来型 `<input type=file>`、保存 = `<a download>` に統一する。
  // 本 UI は開いて得たハンドルを使わず内容だけ扱うので、機能差は「保存先がダウンロード
  // フォルダ固定」になる点のみ。安定性を優先する判断。`hasFsSave` は常に false を返す。
  function hasFsSave() { return false; }

  // `<input type=file>` でファイルを開く小ヘルパ (multiple/accept を指定可)。
  function pickViaInput(accept, multiple) {
    return new Promise(function (resolve) {
      var inp = document.createElement("input");
      inp.type = "file"; inp.accept = accept; inp.multiple = !!multiple;
      inp.addEventListener("change", function () { resolve([].slice.call(inp.files)); });
      inp.click();
    });
  }

  async function pickPdfFiles() {
    return await pickViaInput(".pdf,application/pdf", true);
  }

  async function uploadPdf(name, buf) {
    // セッショントークンは `rpc.js` の `__authHeaders` が載せる (`/upload` も非安全メソッド
    // なのでサーバが要求する)。
    var res = await fetch("/upload?name=" + encodeURIComponent(name), {
      method: "POST",
      headers: window.__authHeaders({ "Content-Type": "application/octet-stream" }),
      body: buf,
    });
    var j = await res.json();
    if (!j.ok) throw new Error(j.error || "アップロードに失敗しました");
    return j.data;
  }

  function downloadBlob(name, text, mime) {
    var url = URL.createObjectURL(new Blob([text], { type: mime || "application/octet-stream" }));
    var a = document.createElement("a");
    a.href = url; a.download = name; document.body.appendChild(a); a.click();
    setTimeout(function () { a.remove(); URL.revokeObjectURL(url); }, 1000);
  }

  // 1 ファイルを保存。成功で true、ユーザーがキャンセルしたら false。FSA 非対応は download。
  async function saveTextFile(suggestedName, text, descr, mime, ext) {
    if (hasFsSave()) {
      try {
        var accept = {}; accept[mime] = [ext];
        var h = await window.showSaveFilePicker({ suggestedName: suggestedName, types: [{ description: descr, accept: accept }] });
        var w = await h.createWritable(); await w.write(text); await w.close();
        return true;
      } catch (e) { if (e && e.name === "AbortError") return false; throw e; }
    }
    downloadBlob(suggestedName, text, mime); return true;
  }

  // 1 ファイルを開いて File を返す。キャンセルで null。FSA は使わず `<input type=file>`。
  // (`descr` は呼出側の互換のため受けるが未使用)
  async function pickOneFile(descr, mime, ext) {
    var files = await pickViaInput(ext + "," + mime, false);
    return files[0] || null;
  }

  // base64 → Uint8Array。ZIP 等のバイナリを `downloadBlob` (BlobPart) へ渡すための小ヘルパ。
  function b64ToBytes(b64) {
    var bin = atob(b64);
    var out = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  // 画面下部の一時通知 (graph-editor と同型)。フッター文字 (`setHint`) は視線が届きにくい
  // ため、完了などの重要イベントはこちらでも知らせる。`aria-live` は index.html 側に付与。
  var _toastTimer = null;
  function toast(msg) {
    var t = document.getElementById("toast");
    if (!t) return;
    t.textContent = msg;
    t.classList.add("on");
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(function () { t.classList.remove("on"); }, 3200);
  }

  // ── 4. 読み込み ──
  // 資源上限による劣化の直前値 (要素の切り捨て / 背景の欠落)。同じ状態で何度も通知しない。
  var degradedNoticed = { truncated: 0, noBackground: 0, ocrPages: 0 };
  async function reloadState() {
    var st = await rpc("state");
    applyState(st);
    // 上限で劣化したページは要素が欠ける・背景が白紙になる。黙って欠落させず必ず伝える。
    // toast は 1 つしか出せないので、同時に起きた分は連結する (片方を捨てない)。
    var msgs = [];
    if (st.truncated && st.truncated !== degradedNoticed.truncated) {
      msgs.push(st.truncated + " ページが要素数の上限を超えたため、一部の要素を読み飛ばしました");
    }
    if (st.noBackground && st.noBackground !== degradedNoticed.noBackground) {
      msgs.push(st.noBackground + " ページは大きすぎて背景画像を生成できませんでした");
    }
    if (st.ocrPages && st.ocrPages !== degradedNoticed.ocrPages) {
      msgs.push("画像 + OCR 文字のページを " + st.ocrPages + " ページ検出しました。置換箇所は画像の上に矩形で上書きします");
    }
    degradedNoticed.truncated = st.truncated || 0;
    degradedNoticed.noBackground = st.noBackground || 0;
    degradedNoticed.ocrPages = st.ocrPages || 0;
    if (msgs.length) toast(msgs.join(" / "));
  }

  // File 配列を順にアップロードして状態を更新する (クリック選択・D&D 共用)。
  // 1 件が失敗しても残りは続けて取り込み、失敗分だけまとめて通知する。失敗で
  // ループを抜けると後続のファイルが黙って捨てられ、利用者は「選んだのに増えない」
  // 理由を受け取れない (パスワード保護 PDF が混ざる場合に実際に起きた)。
  async function addFiles(files) {
    if (!files || !files.length) { render(); return; }
    var failures = [];
    for (var i = 0; i < files.length; i++) {
      setHint("読み込み中 " + (i + 1) + "/" + files.length + ": " + esc(files[i].name));
      try {
        var buf = await files[i].arrayBuffer();
        await uploadPdf(files[i].name, buf);
      } catch (e) {
        failures.push("「" + files[i].name + "」を読み込めませんでした: " + String((e && e.message) || e));
      }
    }
    if (failures.length) toast(failures.join(" / "));
    await reloadState();
    renderFileCards();
    render();
  }

  async function doLoad() { await addFiles(await pickPdfFiles()); }

  // ── 5. (1) ファイルカード ──
  function renderFileCards() {
    document.getElementById("filelist-count").textContent =
      S.FILES.length + " ファイル・" + S.TOTAL + " ページ";
    document.getElementById("file-cards").innerHTML = S.FILES.map(function (f, i) {
      var sc = scannedCountOf(i);
      var chip = sc ? '<span class="chip">スキャン画像 ' + sc + " / " + f.pages + " ページ</span>" : "";
      return '<div class="file-card"><div class="fic">' + svg(fileIcon, 20) +
        '</div><div class="fmeta"><div class="fname">' + esc(f.name) + '</div><div class="fsub"><span>' +
        f.pages + " ページ" + (f.size ? " ・ " + f.size : "") + "</span>" + chip + "</div></div>" +
        '<button class="iconbtn" data-removefile="' + i + '" title="一覧から削除">' + svg(xIcon, 16) + "</button></div>";
    }).join("");
    document.getElementById("file-cards").querySelectorAll("[data-removefile]").forEach(function (b) {
      b.addEventListener("click", async function () {
        await rpc("removeFile", { fileIndex: +b.dataset.removefile });
        await reloadState();
        renderFileCards();
        render();
      });
    });
    renderScanBanner();
  }

  /** 手順 1 のスキャン画像のバナー。スキャンページが 1 ページ以上あるときだけ出す。
   *  グレーモードのときは出さない (手順 2 を通らないため)。文言は全ページ用と混在用の 2 系統。 */
  function renderScanBanner() {
    var el = document.getElementById("scan-banner"), text = document.getElementById("scan-banner-text");
    var n = scannedTotal();
    if (!n || S.gray) { el.hidden = true; return; }
    var all = skipsPhase2();
    var lines = all
      ? ["<b>選んだ PDF はすべてスキャン画像です（" + n + " ページ）。</b>",
         "文字を持たないため、用語の置換はできません。",
         "手順 2「用語を置換」は省略し、「次へ」で手順 3「削除・枠線の編集」に進みます。",
         "文字を置き換えたいときは、手順 3 の「上書き」で矩形と語を置きます。"]
      : ["<b>スキャン画像のページが " + n + " ページあります。</b>",
         "文字を持たないため、用語の置換はできません（手順 2 の一覧には出ません）。",
         "文字を置き換えたいときは、手順 3 の「上書き」で矩形と語を置きます。"];
    text.innerHTML = lines.map(function (s) { return "<span>" + s + "</span>"; }).join("");
    el.hidden = false;
  }
  // ── 6. ページ SVG ──
  async function ensureSvg(fi, pi) {
    var k = svgKey(fi, pi);
    if (!S.svgCache[k]) {
      S.svgCache[k] = await rpc("pageSvg", { fileIndex: fi, pageInFile: pi, grayscale: S.gray });
      if (S.svgCache[k].coverFallback) toast("背景色を採れなかった " + S.svgCache[k].coverFallback + " 箇所は白で上書きしました");
    }
    return S.svgCache[k];
  }
  function invalidate(fi, pi) { svgKeys(fi, pi).forEach(function (k) { delete S.svgCache[k]; }); }

  // フィット率 (現行どおりクランプ 0.05〜3) にズーム倍率を掛けた最終スケールを当てる。
  // zoom=1 なら従来表示と一致。
  function scalePage(svgEl, w, h, editorEl) {
    var avW = Math.max(120, editorEl.clientWidth - 90);
    var avH = Math.max(120, editorEl.clientHeight - 96);
    var fit = Math.min(avW / w, avH / h);
    fit = Math.max(0.05, Math.min(fit, 3));
    var sc = fit * curZoom();
    svgEl.style.width = (w * sc) + "px";
    svgEl.style.height = (h * sc) + "px";
  }

  // ── 7. キャンバス内ズーム (手順2・3、キャンバスのみ拡大縮小) ──
  function curZoom() { return S.zoomFor[S.phase] || 1; }
  function updateZoomLabel() {
    var el = app.querySelector('[data-screen="' + S.phase + '"] .zoom-ctrl .zpct');
    if (el) el.textContent = Math.round(curZoom() * 100) + "%";
  }
  function setZoom(z) {
    S.zoomFor[S.phase] = Math.max(0.25, Math.min(6, z));
    rescaleCurrent();
  }
  // 再フェッチせず現在表示中の SVG にスケールだけ当て直す。
  function rescaleCurrent() {
    var host = document.getElementById(S.phase === 2 ? "doc-master" : (S.phase === 3 ? "trim-stage" : "fig-stage"));
    if (!host) return;
    var svgEl = host.querySelector("svg");
    var pg = S.PAGES[S.page];
    var data = pg && S.svgCache[svgKey(pg.fileIndex, pg.pageInFile)];
    if (svgEl && data) {
      scalePage(svgEl, data.width, data.height, app.querySelector('[data-screen="' + S.phase + '"] .editor'));
      if (S.phase === 3) drawSelBoxes(host); // sel-box は host 相対なので再計算
      if (S.phase === 4) drawFigOverlay(host);
    }
    updateZoomLabel();
  }

  // mountPage の呼び出し通番。同じページを続けて開くと時刻だけでは token が衝突しうるため、
  // 呼び出しごとに必ず変わる値で「最後の呼び出しだけが描く」を保証する。
  var mountSeq = 0;

  // host に現在ページの SVG を載せる。token で古い await を破棄。
  // SVG 取得は失敗・遅延し得るため、無言でプレースホルダのまま固まらせず
  // エラーを画面に出す (この描画が唯一ページを表示する経路のため)。
  // `onMounted` は描いた時だけ呼ぶ (クリック配線の注入点)。破棄した呼び出しから呼ぶと、
  // 現ページの SVG へ同じリスナーが二重に付き、クリックが往復して選択できなくなる。
  async function mountPage(host, editorEl, withSelect, onMounted) {
    var pg = S.PAGES[S.page];
    var token = pg.fileIndex + ":" + pg.pageInFile + ":" + (++mountSeq);
    host.dataset.token = token;
    var data;
    if (!S.svgCache[svgKey(pg.fileIndex, pg.pageInFile)]) {
      // 取得中に旧ページの SVG を残すと、その上でクリック選択や範囲削除ができてしまう。
      host.classList.add("empty");
      host.innerHTML = '<span class="page-loading">ページを読み込んでいます…</span>';
    }
    try {
      data = await ensureSvg(pg.fileIndex, pg.pageInFile);
    } catch (e) {
      if (host.dataset.token !== token) return; // ページが変わった
      host.classList.remove("empty");
      host.innerHTML = '<div class="page-loading" style="padding:24px">ページの表示に失敗しました<br>' + esc(e && e.message || e) + "</div>";
      return;
    }
    if (host.dataset.token !== token) return; // ページが変わった
    host.classList.remove("empty");
    host.innerHTML = data.svg;
    var svgEl = host.querySelector("svg");
    if (svgEl) scalePage(svgEl, data.width, data.height, editorEl);
    if (withSelect) { drawSelBoxes(host); }
    if (onMounted) onMounted();
  }

  // ── 8. 左: ページ一覧 — rail.js の buildRail が担う (initRail で render を注入) ──

  // ── 9. 確認ペイン (手順2) ──
  async function renderConfirm() {
    var el = document.getElementById("confirm-dyn");
    var ed2 = app.querySelector('[data-screen="2"] .editor');
    if (!matchCount(S.page)) {
      ed2.classList.add("nochange");
      el.innerHTML = noChangeNote(S.scanned[S.page]
        ? "このページはスキャン画像のため、用語の置換の対象外です"
        : "このページに辞書と一致する語はありません");
      S.lastChanges = [];
      drawChangeMarkers([]);
      return;
    }
    ed2.classList.remove("nochange");
    var pg = S.PAGES[S.page];
    var token = pg.fileIndex + ":" + pg.pageInFile;
    var data;
    try {
      data = await rpc("planPage", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
    } catch (e) {
      if (token !== S.PAGES[S.page].fileIndex + ":" + S.PAGES[S.page].pageInFile) return; // ページが変わった
      S.lastChanges = [];
      drawChangeMarkers([]);
      renderPaneError(el, "変更の一覧を取得できませんでした: " + String((e && e.message) || e));
      return;
    }
    if (token !== S.PAGES[S.page].fileIndex + ":" + S.PAGES[S.page].pageInFile) return; // ページが変わった
    var applied = data.changes.filter(function (c) { return c.state === "applied"; }).length;
    var pending = data.changes.length - applied;
    var rows = data.changes.map(function (ch, i) {
      var isApplied = ch.state === "applied";
      var warn = ch.warning ? '<span class="warn" title="置換語が元の幅より長く、圧縮表示される可能性があります">幅超過</span>' : "";
      var badge = isApplied ? "" : '<span class="state">未置換</span>';
      // 置換済み行は「戻す」、未置換行 (戻した箇所・まだ当てていない箇所) は「置換」。
      var act = isApplied
        ? '<button type="button" class="row-btn act-revert" title="この箇所だけ置換前に戻す">戻す</button>'
        : '<button type="button" class="row-btn act-apply" title="この箇所だけ置換する">置換</button>';
      return '<div class="change-row' + (isApplied ? "" : " pending") + '" data-el="' + ch.elId + '">' +
        '<span class="num">' + (i + 1) + '</span><span class="loc">' + esc(ch.loc) +
        '</span><span class="pair"><span class="from">' + esc(ch.source) + "</span>" +
        svg('<path d="M4 12h15M13 6l6 6-6 6"/>', 15) + '<span class="to">' + esc(ch.target) + "</span></span>" +
        warn + badge + act + "</div>";
    }).join("");
    var total = data.changes.length;
    var desc = total === 0 ? "このページに辞書と一致する語はありません。"
      : pending === 0 ? "辞書に一致した " + total + " か所をすべて置き換えました。"
      : "一致 " + total + " か所のうち " + pending + " か所が未置換です。";
    el.innerHTML =
      '<div class="count-card"><div class="num">' + applied + '</div><div><div class="t">このページで置き換えた語</div>' +
      '<div class="lines s"><span>' + desc + "</span>" + (pending ? "<span>「置換」で当てられます。</span>" : "") + "</div></div></div>" +
      '<div style="display:flex;flex-direction:column;min-height:0;flex:1;"><div class="field-label">辞書に一致した箇所（番号はページ上のマーカー）</div><div class="change-list">' +
      rows + "</div></div>";
    S.lastChanges = data.changes;
    drawChangeMarkers(S.lastChanges);
    el.querySelectorAll(".change-row[data-el]").forEach(function (row) {
      var elId = row.dataset.el;
      row.addEventListener("click", function () { flashElement("doc-master", elId); });
      row.addEventListener("mouseenter", function () { highlightElement("doc-master", elId, true); });
      row.addEventListener("mouseleave", function () { highlightElement("doc-master", elId, false); });
      var args = { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elId: elId };
      // 置換の有無が変わると SVG も一覧も変わるので、再適用ボタンと同じく再生成→再描画する。
      async function after() {
        highlightElement("doc-master", elId, false);
        invalidate(pg.fileIndex, pg.pageInFile);
        await reloadState();
        render();
      }
      var revert = row.querySelector(".act-revert");
      if (revert) revert.addEventListener("click", async function (e) {
        e.stopPropagation(); await rpc("revertDictMatch", args); await after();
      });
      var apply = row.querySelector(".act-apply");
      if (apply) apply.addEventListener("click", async function (e) {
        e.stopPropagation(); await rpc("applyDictMatch", args); await after();
      });
    });
  }
  // ペインの取得が失敗したときの表示。旧ページの行 (とそのクリック結線) を残すと、
  // 今見ているページと無関係な要素を操作できてしまうため、必ず中身ごと置き換える。
  function renderPaneError(el, msg) {
    el.innerHTML = '<div class="empty-note" style="flex:1"><div class="et">' + esc(msg) +
      '</div><button type="button" class="btn ghost" data-retry="1">再試行</button></div>';
    var btn = el.querySelector("[data-retry]");
    if (btn) btn.addEventListener("click", function () { render(); });
  }

  function noChangeNote(msg) {
    return '<div class="empty-note"><div class="ei">' + svg('<circle cx="12" cy="12" r="9"/><path d="M8 12h8"/>', 24) +
      '</div><div class="et">' + esc(msg) + "</div></div>";
  }

  function flashElement(hostId, elId) {
    var host = document.getElementById(hostId);
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    var target = svgEl.querySelector('[data-el="' + elId + '"]'); if (!target) return;
    var hb = host.getBoundingClientRect(); var tb = target.getBoundingClientRect();
    var box = document.createElement("div");
    box.className = "sel-box";
    box.style.left = (tb.left - hb.left - 3) + "px"; box.style.top = (tb.top - hb.top - 3) + "px";
    box.style.width = (tb.width + 6) + "px"; box.style.height = (tb.height + 6) + "px";
    box.style.transition = "opacity .9s ease"; host.appendChild(box);
    setTimeout(function () { box.style.opacity = "0"; }, 350);
    setTimeout(function () { box.remove(); }, 1300);
  }

  // 一覧の行に乗せている間だけ該当要素を枠で示す (`flashElement` の持続版)。
  function highlightElement(hostId, elId, on) {
    var host = document.getElementById(hostId);
    if (!host) return;
    var old = host.querySelector('.sel-box[data-hl="' + elId + '"]');
    if (old) old.remove();
    if (!on) return;
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    var target = svgEl.querySelector('[data-el="' + elId + '"]'); if (!target) return;
    var hb = host.getBoundingClientRect(); var tb = target.getBoundingClientRect();
    var box = document.createElement("div");
    box.className = "sel-box"; box.dataset.hl = elId;
    box.style.left = (tb.left - hb.left - 3) + "px"; box.style.top = (tb.top - hb.top - 3) + "px";
    box.style.width = (tb.width + 6) + "px"; box.style.height = (tb.height + 6) + "px";
    host.appendChild(box);
  }

  // 一覧の通し番号をページ上の該当要素の左上へ描く。SVG 座標系 (getBBox) に置くので
  // ズームに追随し、表示用 DOM にだけ入る (書き出しはサーバ側 exportSvg で別生成)。
  var SVG_NS = "http://www.w3.org/2000/svg";
  function drawChangeMarkers(changes) {
    var host = document.getElementById("doc-master");
    var svgEl = host && host.querySelector("svg");
    if (!svgEl) return;
    var old = svgEl.querySelector("[data-editor-marks]");
    if (old) old.remove();
    if (!changes.length) return;
    var vb = svgEl.viewBox.baseVal;
    var r = Math.max(4, Math.min(vb.width, vb.height) * 0.012); // ページ寸法に対する相対サイズ
    var g = document.createElementNS(SVG_NS, "g");
    g.setAttribute("data-editor-marks", "");
    g.setAttribute("font-family", "BIZ UDPGothic, Yu Gothic UI, sans-serif");
    g.setAttribute("font-weight", "700");
    g.setAttribute("font-size", String(r * 1.3));
    g.setAttribute("pointer-events", "none");
    changes.forEach(function (ch, i) {
      var t = svgEl.querySelector('[data-el="' + ch.elId + '"]'); if (!t) return;
      var bb = t.getBBox();
      var m = document.createElementNS(SVG_NS, "g");
      var c = document.createElementNS(SVG_NS, "circle");
      c.setAttribute("cx", bb.x); c.setAttribute("cy", bb.y); c.setAttribute("r", r);
      c.setAttribute("fill", ch.state === "applied" ? "oklch(0.585 0.105 240)" : "oklch(0.68 0.010 262)");
      var tx = document.createElementNS(SVG_NS, "text");
      tx.setAttribute("x", bb.x); tx.setAttribute("y", bb.y + r * 0.45);
      tx.setAttribute("text-anchor", "middle"); tx.setAttribute("fill", "#fff");
      tx.textContent = String(i + 1);
      m.appendChild(c); m.appendChild(tx); g.appendChild(m);
    });
    svgEl.appendChild(g);
  }

  // ── 10. 編集ペイン (手順3): このページの編集 (削除・枠線・上書き) と使い方 ──
  var HOWTO = {
    normal: ["要素をクリックして「削除」。", "「範囲削除」はドラッグ範囲をまとめて削除。", "「枠線」「上書き」はドラッグで置きます。", "置いた後も動かせます。"],
    scanned: ["画像の文字は辞書で置き換えられません。", "「上書き」を選び、置く所をドラッグします。", "上のボックスに置換語を入れます。", "画像の上に矩形と語が乗ります。", "置いた上書きは後から動かせます。"],
  };
  function howtoHTML() {
    var scanned = !!S.scanned[S.page];
    return '<div class="howto"><b>' + (scanned ? "スキャン画像のページの使い方" : "使い方") + "</b><ul>" +
      HOWTO[scanned ? "scanned" : "normal"].map(function (s) { return "<li>" + s + "</li>"; }).join("") + "</ul></div>";
  }
  async function renderTrim() {
    var el = document.getElementById("trim-dyn");
    var ed3 = app.querySelector('[data-screen="3"] .editor');
    ed3.classList.remove("nochange");
    var pg = S.PAGES[S.page];
    var token = pg.fileIndex + ":" + pg.pageInFile;
    var args = { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile };
    var lists;
    try {
      lists = await Promise.all([rpc("removedList", args), rpc("borderList", args), rpc("coverList", args)]);
    } catch (e) {
      if (token !== S.PAGES[S.page].fileIndex + ":" + S.PAGES[S.page].pageInFile) return; // ページが変わった
      renderPaneError(el, "このページの編集の一覧を取得できませんでした: " + String((e && e.message) || e));
      return;
    }
    if (token !== S.PAGES[S.page].fileIndex + ":" + S.PAGES[S.page].pageInFile) return; // ページが変わった
    var removed = lists[0].removed, borders = lists[1].borders, covers = lists[2].covers;
    var rows = removed.map(function (r) {
      return '<div class="edit-row" data-kind="removed"><span class="k">削除</span><span class="rlabel">' + esc(r.label) + '</span><button class="row-btn" data-restore="' + r.elId + '">戻す</button></div>';
    }).concat(borders.map(function (b) {
      return '<div class="edit-row" data-kind="border"><span class="k">枠線</span><span class="rlabel">' + esc(b.color) + " ・ " + b.width + ' pt</span><button class="row-btn" data-del="' + b.elId + '">削除</button></div>';
    })).concat(covers.map(function (c) {
      return '<div class="edit-row" data-kind="cover"><span class="k">上書き</span><span class="rlabel">' + (c.text ? "「" + esc(c.text) + "」" : "（矩形だけ）") + '</span><button class="row-btn" data-del="' + c.elId + '">削除</button></div>';
    })).join("");
    el.innerHTML = '<div class="field-label">このページの編集</div>' +
      (rows ? '<div class="change-list">' + rows + "</div>" : '<div class="edit-empty">このページに編集はありません</div>') +
      howtoHTML();
    el.querySelectorAll("[data-restore]").forEach(function (b) {
      b.addEventListener("click", async function () {
        // 行の要素だけを戻す。全体の undo は直近 1 件しか戻せず、複数回に分けて削除した
        // 後や別ページで削除した後に押すと無関係な操作を取り消してしまう。
        await rpc("restoreElements", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elIds: [+b.dataset.restore] });
        await afterEdit();
      });
    });
    el.querySelectorAll("[data-del]").forEach(function (b) {
      b.addEventListener("click", async function () {
        await rpc("applyDelete", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elIds: [+b.dataset.del] });
        await afterEdit();
      });
    });
  }

  // ── 11. 手順3 エディタ操作 ──
  /** 「削除」ボタンの押下可否を今の選択から決める。要素 (青枠)・上書き (緑枠)・枠線のどれかを
   *  選んでいれば押せる。何も選んでいない間は押しても何も起きないので無効にする (押下可否で
   *  「いま何を選んでいるか」が分かる)。位置は動かさない — 出し入れすると隣のボタンの位置が
   *  ずれて目が迷う。選択が変わる 3 経路 (`render()`・クリック選択・オーバーレイの選択) から呼ぶ。 */
  function syncDeleteButton() {
    var del = document.getElementById("btn-deletesel");
    if (del) del.disabled = !Object.keys(curElSel()).length && S.coverSel === null && S.borderSel === null;
  }

  function drawSelBoxes(host) {
    host.querySelectorAll(".sel-box").forEach(function (b) { b.remove(); });
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    var sel = curElSel(); var hb = host.getBoundingClientRect();
    Object.keys(sel).forEach(function (id) {
      var t = svgEl.querySelector('[data-el="' + id + '"]'); if (!t) return;
      var tb = t.getBoundingClientRect();
      var box = document.createElement("div"); box.className = "sel-box";
      box.style.left = (tb.left - hb.left - 2) + "px"; box.style.top = (tb.top - hb.top - 2) + "px";
      box.style.width = (tb.width + 4) + "px"; box.style.height = (tb.height + 4) + "px";
      host.appendChild(box);
    });
  }

  // 要素のクリック選択の結線。SVG は mountPage で毎回差し替わるため漏れない。
  // ツールを選んでいてもクリックは要素の選択に使う (ドラッグだけがツール固有の操作)。
  // crop/border/cover ドラッグのリスナーは wireStatic で一度だけ張る (多重登録防止)。
  function wireTrimStage() {
    var host = document.getElementById("trim-stage");
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    svgEl.addEventListener("click", function (e) {
      // ドラッグで矩形を引いた直後にも click は飛ぶ。そのまま拾うと、引き終わった位置の
      // 要素が意図せず選択される (範囲削除の直後に無関係な要素が青枠になる)。
      if (S.dragMoved) { S.dragMoved = false; return; }
      var t = e.target.closest("[data-el]"); if (!t) return;
      var id = t.getAttribute("data-el"); var sel = curElSel();
      if (sel[id]) delete sel[id]; else sel[id] = true;
      drawSelBoxes(host);
      syncDeleteButton();
    });
  }

  // crop/border ツール: ドラッグした矩形で範囲削除 (crop) または枠線追加 (border)。
  // リスナーは起動時に一度だけ設置し、イベント時に S.phase/S.tool を判定する。
  function installCropDrag() {
    var host = document.getElementById("trim-stage");
    host.addEventListener("mousedown", function (e) {
      if (S.phase !== 3 || (S.tool !== "crop" && S.tool !== "border" && S.tool !== "cover")) return;
      if (e.target.closest(".cover-box") || e.target.closest(".border-box")) return; // オーバーレイ上の移動・伸縮・選択は cover.js / border.js が扱う
      if (!host.querySelector("svg")) return;
      if (S.tool === "cover") clearCoverSel(); // 上書きの空白クリックは選択解除 (新規追加のラバーバンドへ進む)
      if (S.tool === "border") clearBorderSel(); // 枠線も同様
      blurTextEntry(); // 選択を解いたあとで外す (順序を入れ替えると確定 RPC が飛ぶ)
      var rubber = document.createElement("div");
      rubber.className = S.tool === "border" ? "border-rubber" : S.tool === "cover" ? "cover-rubber" : "crop-rubber";
      host.appendChild(rubber);
      S.cropDrag = { origin: { x: e.clientX, y: e.clientY }, rubber: rubber, mode: S.tool };
      e.preventDefault();
    });
    window.addEventListener("mousemove", function (e) {
      if (!S.cropDrag) return;
      S.dragMoved = true;
      var hb = host.getBoundingClientRect();
      var x1 = Math.min(S.cropDrag.origin.x, e.clientX), y1 = Math.min(S.cropDrag.origin.y, e.clientY);
      var x2 = Math.max(S.cropDrag.origin.x, e.clientX), y2 = Math.max(S.cropDrag.origin.y, e.clientY);
      S.cropDrag.rubber.style.left = (x1 - hb.left) + "px"; S.cropDrag.rubber.style.top = (y1 - hb.top) + "px";
      S.cropDrag.rubber.style.width = (x2 - x1) + "px"; S.cropDrag.rubber.style.height = (y2 - y1) + "px";
    });
    window.addEventListener("mouseup", async function (e) {
      if (!S.cropDrag) return;
      var d = S.cropDrag; S.cropDrag = null; d.rubber.remove();
      var svgEl = host.querySelector("svg"); if (!svgEl) return;
      var a = clientToPage(svgEl, d.origin.x, d.origin.y);
      var b = clientToPage(svgEl, e.clientX, e.clientY);
      var rect = rectFromDrag(a, b, pageSizeOf(svgEl));
      if (!rect) return;
      var pg = S.PAGES[S.page];
      // `rectFromDrag` は 3 ツールとも同じ「ページ内へクランプした矩形」を渡す。crop
      // (範囲削除) はページ外の矩形でも要素との交差判定にしか使わないので無害、border は
      // 矩形自体が SVG に残るのでページ内へ収まっている方が正しい (cover は元々ページ内が
      // サーバ検証の前提)。
      try {
        if (d.mode === "border") {
          await rpc("addBorder", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, rect: rect, color: S.borderColor, width: S.borderWidth });
        } else if (d.mode === "cover") {
          await rpc("addCover", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, rect: rect, text: S.coverText });
        } else {
          await rpc("deleteRegion", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, rect: rect });
        }
      } catch (err) {
        toast(String((err && err.message) || "操作に失敗しました"));
        return;
      }
      await afterEdit();
    });
  }

  /** 手順 3 の編集・Undo・Redo のあとの後始末。編集が成立しうる経路 (ツールのドラッグ・
   *  一覧の行ボタン・オーバーレイの移動と伸縮・Undo/Redo) はすべてここを通す。
   *
   *  どの経路でも `state` を丸ごと取り直す。ページごとの件数 (`S.matches2` / `S.edits3`) は
   *  サーバの `state` にしか無いので、取り直さないと削除・枠線・上書きを置いてもレールの
   *  件数タグ・フッターの件数・手順 4 のまとめが 0 のまま残る。Undo/Redo は現在ページ以外の
   *  編集も巻き戻す (別ページで削除してからページを移った後など) ので、そもそも全ページ分を
   *  見直す必要がある。
   *  ページ SVG のキャッシュと要素の選択は `applyState` が捨てるため、ここでは触らない。 */
  async function afterEdit() {
    blurTextEntry(); // 編集が成功した時点で入力欄のフォーカスを外し、続く Ctrl+Z をアプリの Undo へ通す
    // 取り直しに失敗しても理由を出してから必ず描き直す。黙って抜けると、編集は通っているのに
    // 画面が更新されず、利用者には何も起きていないように見える。
    try {
      await reloadState();
    } catch (e) {
      toast("状態を取り直せませんでした: " + String((e && e.message) || e));
    } finally {
      render();
    }
  }

  // ── 12. ページ送り (右パネル下部) ──
  function wirePageFoot2() {
    var prev = document.getElementById("prev-page-2"), next = document.getElementById("next-match-2");
    prev.disabled = S.page === 0;
    var nm = nextMatched(S.page);
    next.disabled = nm < 0;
    prev.onclick = function () { if (S.page > 0) { S.page--; render(); } };
    next.onclick = function () { var n = nextMatched(S.page); if (n >= 0) { S.page = n; render(); } };
  }
  function wirePageFoot3() {
    var prev = document.getElementById("prev-page-3"), next = document.getElementById("next-page-3");
    prev.disabled = S.page === 0;
    next.disabled = S.page >= S.TOTAL - 1;
    prev.onclick = function () { if (S.page > 0) { S.page--; render(); } };
    next.onclick = function () { if (S.page < S.TOTAL - 1) { S.page++; render(); } };
  }
  function pageLabel() { var pg = S.PAGES[S.page]; return "<b>" + esc(S.FILES[pg.fileIndex].name) + "</b> ・ " + (pg.pageInFile + 1) + " ページ"; }

  // ── 13. 辞書ペイン ──
  var dictState = { entries: [], suggestJoin: false };
  // クリック取り込みが折返し連結した候補かの記憶。登録時にエントリの連結由来
  // (joined) として送り、一括適用の連結照合の対象を決める。#dict-src を手編集
  // したら連結由来は外す (連結文字列でなくなるため)。
  var pendingJoined = false;
  // 辞書ファイルの読み込み異常を通知したかの記憶。起動後 1 度だけ出す
  // (`loadDict` は辞書ペインを開くたびに走るので、毎回出すと邪魔になる)。
  var dictLoadNoticeShown = false;
  async function loadDict() {
    dictState = await rpc("dictList");
    // 壊れた要素は黙って消さない: 起動時に捨てた件数・読めなかった事実を利用者へ返す。
    if (!dictLoadNoticeShown) {
      dictLoadNoticeShown = true;
      if (dictState.loadFailed) toast("辞書ファイルを読み込めませんでした。空の辞書で開始します");
      else if (dictState.loadSkipped) toast("辞書ファイルの " + dictState.loadSkipped + " 件を読み飛ばしました（形式が不正）");
    }
    renderDict();
  }
  function renderDict() {
    document.getElementById("dict-count").textContent = "登録済みの用語（" + dictState.entries.length + "）";
    document.getElementById("dict-rows").innerHTML = dictState.entries.map(function (m) {
      var joinBadge = m.joined ? '<span class="join-badge" title="折返し連結の取り込み由来。再適用時に 2 行を連結して照合します">連結</span>' : "";
      return '<div class="dict-row" data-id="' + m.id + '"><span class="src">' + esc(m.source) + joinBadge + '</span><span class="arr">' +
        svg('<path d="M4 12h15"/><path d="m13 6 6 6-6 6"/>', 14) + '</span><span class="tgt">' + esc(m.target) + "</span>" +
        '<button class="iconbtn" data-del="' + m.id + '" title="削除" style="width:26px;height:26px">' + svg(xIcon, 15) + "</button></div>";
    }).join("");
    document.getElementById("dict-rows").querySelectorAll("[data-del]").forEach(function (b) {
      b.addEventListener("click", async function () {
        dictState = await rpc("dictDelete", { id: +b.dataset.del }); renderDict();
        // 削除した語に当たっていたページは一致件数 (`S.matches2`) が変わるため、state を取り直す。
        // 取り直さないとレールの件数タグとフッターの件数が消えた語を数え続ける。
        await reloadState(); render();
      });
    });
    var chkJoin = document.getElementById("chk-suggest-join");
    chkJoin.querySelector(".box").classList.toggle("on", !!dictState.suggestJoin);
  }

  // 手順2 のパネルタブ切替 (タブクリック・機能1 の双方から使う)
  function activateTab(name) {
    app.querySelectorAll(".panel-tab").forEach(function (t) {
      t.setAttribute("aria-selected", t.dataset.tab === name ? "true" : "false");
    });
    app.querySelectorAll('[data-screen="2"] .tabpane').forEach(function (p) {
      p.classList.toggle("on", p.dataset.pane === name);
    });
    if (name === "dict") loadDict();
  }

  // 機能1: 手順2 のページ上の文字クリック → 「元の語」に取り込む。
  // 「クリック取り込みで折返しを連結」チェックが ON のとき、折返しで複数行に分かれた
  // 1 文 (セル) はサーバの dictSuggest がマッチャと同じ束ね方で連結した文字列を返す
  // (連結したかは pendingJoined に記録し、登録エントリの連結由来になる)。取得に
  // 失敗したときはクリック行の textContent をそのまま使う。
  function wireConfirmPick() {
    var host = document.getElementById("doc-master");
    var svgEl = host.querySelector("svg");
    if (!svgEl) return;
    svgEl.addEventListener("click", async function (e) {
      var t = e.target.closest("[data-el]");
      if (!t || t.tagName.toLowerCase() !== "text") return;
      var txt = (t.textContent || "").trim();
      if (!txt) return;
      activateTab("dict");
      var pg = S.PAGES[S.page];
      var joined = false;
      if (pg) {
        try {
          var r = await rpc("dictSuggest", {
            fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elId: t.getAttribute("data-el"),
          });
          if (r && r.source) { txt = r.source; joined = !!r.joined; }
        } catch (_) { /* 折返し連結の取得失敗時はクリック行の文字列を使う */ }
      }
      pendingJoined = joined;
      document.getElementById("dict-src").value = txt;
      document.getElementById("dict-tgt").focus();
      flashElement("doc-master", t.getAttribute("data-el"));
    });
  }

  // ── 14. 描画 ──
  function setHint(html) { document.getElementById("nav-hint").innerHTML = html; }

  /** 手順 4 のまとめの表 (PDF / 用語の置換 / 削除・枠線)。0 の項目は省く */
  function exportSummaryRows() {
    var mt = matchTotals(), et = editTotals();
    var terms = [];
    if (mt.applied) terms.push("置換 <b>" + mt.applied + "</b> か所（<b>" + mt.pages + "</b> ページ）");
    if (mt.pending) terms.push("未置換 <b>" + mt.pending + "</b> か所");
    if (mt.scanned) terms.push("対象外（スキャン画像） <b>" + mt.scanned + "</b> ページ");
    if (!terms.length) terms.push("辞書に一致した語はありません");
    var edits = [];
    if (et.pages) {
      edits.push("編集したページ <b>" + et.pages + "</b>");
      if (et.removed) edits.push("削除 <b>" + et.removed + "</b>");
      if (et.borders) edits.push("枠線 <b>" + et.borders + "</b>");
      if (et.covers) edits.push("上書き <b>" + et.covers + "</b>");
    } else edits.push("編集したページはありません");
    function row(th, items) { return "<tr><th>" + th + "</th><td>" + items.map(function (x) { return "<span>" + x + "</span>"; }).join("") + "</td></tr>"; }
    return row("PDF", ["<b>" + S.FILES.length + "</b> ファイル・全 <b>" + S.TOTAL + "</b> ページ"]) +
      row("用語の置換", terms) + row("削除・枠線", edits);
  }

  // RPC で通しページ g の候補を取得し `S.figCand`/`S.figSel` へ記録する下位ヘルパ。
  // 「未取得か」の判定と二重要求ガードは呼び出し側 (`ensureFigCand`/`prefetchFigCand`) が持つ
  // (ここでは無条件に取得しに行く)。取得中は `null` を立てる (`seedFigSel` の初回判定にも使う印)。
  async function fetchFigCand(g) {
    var pg = S.PAGES[g]; if (!pg) return;
    var k = figKey(pg);
    S.figCand[k] = null;
    try {
      var res = await rpc("figureCandidates", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
      seedFigSel(g, res.rects || []);
    } catch (e) {
      delete S.figCand[k];
      throw e;
    }
  }

  // 候補を未取得のページだけ取りに行き、届いたら 1 回だけ再描画する (取得済みなら何もしないので再帰しない)。
  async function ensureFigCand(g) {
    var pg = S.PAGES[g]; if (!pg) return;
    if (S.figCand[figKey(pg)] !== undefined) return;
    try {
      await fetchFigCand(g);
    } catch (e) {
      toast("図の検出に失敗しました: " + String((e && e.message) || e));
      return;
    }
    if (S.phase === 4 && S.gray) render();
  }

  // 手順 4 (グレーモード) に入った直後、全ページの候補をまとめて取りに行き、最初に検出できた
  // ページへ自動で移動する。ページを訪れるまで取得しない従来方式だと、利用者が図を手探りで
  // 探すことになり自動化の趣旨に反する (spec §2.4/§8.2)。
  var figPrefetching = false;
  async function prefetchFigCand() {
    if (figPrefetching) return;
    figPrefetching = true;
    var startPage = S.page;
    var toastedFailure = false; // 複数ページが失敗しても通知は 1 回に抑える (連打しない)
    try {
      for (var g = 0; g < S.TOTAL; g++) {
        if (!S.gray || S.phase !== 4) break; // 途中でグレーモードを抜けたら追跡をやめる
        var pg = S.PAGES[g]; if (!pg) continue;
        if (Array.isArray(S.figCand[figKey(pg)])) continue; // 取得済みはスキップ
        setHint("図を探しています " + (g + 1) + "/" + S.TOTAL);
        try {
          await fetchFigCand(g);
        } catch (e) {
          if (!toastedFailure) {
            toastedFailure = true;
            toast("図の検出に失敗しました: " + String((e && e.message) || e));
          }
        }
      }
    } finally {
      figPrefetching = false;
    }
    if (!S.gray || S.phase !== 4) return;
    if (S.page === startPage) {
      // 利用者がまだページを動かしていなければ、最初に検出できたページへ連れて行く。
      var found = -1;
      for (var i = 0; i < S.TOTAL; i++) { if (figSelPeek(i).length) { found = i; break; } }
      if (found >= 0) S.page = found;
      render();
      if (found < 0) setHint("図が見つかりませんでした。ページを選び、範囲をドラッグで指定してください");
    } else {
      render(); // 利用者が既に動かしていたら位置は変えず、レールの件数表示だけ最新化する
    }
  }

  function render() {
    var steps = [].slice.call(app.querySelectorAll("#stepbar .step"));
    var screens = [].slice.call(app.querySelectorAll(".screen"));
    var btnBack = document.getElementById("btn-back");
    var btnNext = document.getElementById("btn-next");
    var btnExport = document.getElementById("btn-export");
    var ctxText = document.getElementById("ctx-text");

    screens.forEach(function (s) { s.classList.toggle("on", +s.dataset.screen === S.phase); });
    var stepbar = document.getElementById("stepbar");
    stepbar.classList.toggle("gray-mode", S.gray);
    document.getElementById("gray-skipnote").hidden = !S.gray;
    // 手順 2 の省略 (全ページが純スキャン)。グレーモード中はそちらの注記だけ出す
    var skip2 = !S.gray && skipsPhase2();
    stepbar.classList.toggle("skip2", skip2);
    document.getElementById("scan-skipnote").hidden = !skip2;
    document.getElementById("step4-label").textContent = S.gray ? "図をグレーで書き出す" : "SVGに書き出す";
    var screen4 = app.querySelector('[data-screen="4"]');
    screen4.classList.toggle("gray", S.gray);
    document.getElementById("pagenav-4").hidden = !S.gray;
    document.getElementById("fig-editor").hidden = !S.gray;
    document.getElementById("exp-modes-gray").hidden = !S.gray;
    document.getElementById("fig-selist-box").hidden = !S.gray;
    document.getElementById("export-title").textContent = S.gray ? "図をグレーで書き出す" : "SVG に書き出す";
    document.getElementById("exp-name-hint").textContent = S.gray
      ? "元ファイル名_p8_fig1_gray.svg …（複数は元ファイル名_gray_svg.zip）"
      : "元ファイル名_p1.svg, _p2.svg …（複数は元ファイル名_svg.zip にまとめます）";
    document.getElementById("mode-normal-box").classList.toggle("on", !S.gray);
    document.getElementById("mode-gray-box").classList.toggle("on", S.gray);
    document.getElementById("flow-step2").classList.toggle("skip", skip2);
    renderScanBanner();
    steps.forEach(function (st) {
      var n = +st.dataset.step; var done = n < S.phase, active = n === S.phase;
      st.classList.toggle("done", done); st.classList.toggle("active", active);
      st.classList.toggle("future", !done && !active); st.classList.toggle("clickable", n <= S.phase);
      st.querySelector(".n").innerHTML = done ? ckMark : n;
    });
    btnBack.style.visibility = S.phase === 1 ? "hidden" : "visible";
    btnNext.style.display = S.phase < 4 ? "" : "none";
    btnExport.style.display = S.phase === 4 ? "" : "none";
    btnNext.childNodes[0].nodeValue = S.phase === 3 ? "書き出しへ" : "次へ";
    btnNext.disabled = (S.phase === 1 && S.TOTAL === 0);
    btnNext.style.opacity = btnNext.disabled ? ".5" : "";

    if (S.phase === 1) {
      var sc = scannedTotal();
      setHint(!S.TOTAL ? "変換するPDFを選びます"
        : S.gray ? "「次へ」で図の選択に進みます（手順 2・3 は省略）"
        : skip2 ? "「次へ」で削除・枠線の編集に進みます（スキャン画像のみのため用語の置換は省略）"
        : "「次へ」で用語の置換に進みます" + (sc ? "（スキャン画像の " + sc + " ページは対象外）" : ""));
      ctxText.textContent = S.TOTAL ? S.FILES.length + " ファイル・" + S.TOTAL + " ページ" : "ファイル未選択";
    } else if (S.phase === 4 && S.gray) {
      var pg4 = S.PAGES[S.page];
      setHint("図を確認して書き出します。採用 <b>" + figCount() + "</b> 図");
      // pg4 はページ列の再取得中などで一時的に欠けうる (figSelPeek と同じ流儀。無ければ表示だけ諦める)
      if (pg4) ctxText.textContent = S.FILES[pg4.fileIndex].name + " ・ " + (pg4.pageInFile + 1) + "/" + S.FILES[pg4.fileIndex].pages + " ページ";
      refreshExport();
      document.getElementById("export-summary").innerHTML =
        S.FILES.length + "ファイル・全" + S.TOTAL + "ページ<br/>採用 " + figCount() + " 図・グレースケール";
    } else if (S.phase === 4) {
      ctxText.textContent = S.FILES.length + " ファイル・" + S.TOTAL + " ページ";
      refreshExport(); // フッターの案内 (何個書き出すか) も refreshExport が出す
      document.getElementById("export-summary").innerHTML = exportSummaryRows();
    } else {
      var pg = S.PAGES[S.page];
      if (S.phase === 2) {
        var mt = matchTotals();
        setHint("用語の置換 — 辞書に一致 <b>" + mt.pages + "</b> ページ ・ 置換 <b>" + mt.applied + "</b> か所 / 未置換 <b>" + mt.pending + "</b> か所");
      } else {
        setHint("削除・枠線の編集 — 編集したページ <b>" + editTotals().pages + "</b> / " + S.TOTAL);
      }
      ctxText.textContent = S.FILES[pg.fileIndex].name + " ・ " + (pg.pageInFile + 1) + "/" + S.FILES[pg.fileIndex].pages + " ページ";
    }

    if (S.phase === 2 && S.TOTAL) {
      buildRail("pagenav");
      wirePageFoot2();
      buildPageJump("pgnav-2");
      mountPage(document.getElementById("doc-master"), app.querySelector('[data-screen="2"] .editor'), false, function () {
        wireConfirmPick();
        drawChangeMarkers(S.lastChanges || []);
      });
      renderConfirm();
      updateZoomLabel();
    }
    if (S.phase === 3 && S.TOTAL) {
      buildRail("pagenav-3");
      wirePageFoot3();
      buildPageJump("pgnav-3");
      var ed3 = app.querySelector('[data-screen="3"] .editor');
      ed3.classList.toggle("tool-crop", S.tool === "crop");
      ed3.classList.toggle("tool-border", S.tool === "border");
      ed3.classList.toggle("tool-cover", S.tool === "cover");
      // 押下表示は `S.tool` から毎回付け直す (手順の移動で `resetPhaseUi` がツールを戻す経路もあるため)
      app.querySelectorAll(".float-tools [data-tool]").forEach(function (x) { x.setAttribute("aria-pressed", x.dataset.tool === S.tool ? "true" : "false"); });
      var bo = document.getElementById("border-opts");
      if (bo) bo.hidden = S.tool !== "border";
      var co = document.getElementById("cover-opts");
      if (co) co.hidden = S.tool !== "cover";
      syncDeleteButton();
      mountPage(document.getElementById("trim-stage"), ed3, true, function () {
        wireTrimStage();
        drawCoverOverlay(document.getElementById("trim-stage"));
        drawBorderOverlay(document.getElementById("trim-stage"));
      });
      renderTrim();
      updateZoomLabel();
    }
    if (S.phase === 4 && S.gray && S.TOTAL) {
      buildFigRail("pagenav-4");
      buildFigSelist("fig-selist");
      document.getElementById("pgnav-4").innerHTML = pageLabel();
      var host4 = document.getElementById("fig-stage");
      ensureFigCand(S.page);
      // 検出ゼロ (取得済みで候補も採用も無い) のページは手動へ誘導する (spec 2 節 4.)
      var candCur = pg4 && S.figCand[figKey(pg4)];
      document.getElementById("fig-hint").innerHTML =
        (Array.isArray(candCur) && !candCur.length && !figSelPeek(S.page).length)
          ? "このページに図は見つかりませんでした。範囲を<b>ドラッグ</b>で指定してください"
          : "<b>クリック</b>で採用 / 解除 ・ 何もない場所を<b>ドラッグ</b>で範囲を追加";
      mountPage(host4, app.querySelector('[data-screen="4"] .editor'), false, function () { drawFigOverlay(host4); });
      updateZoomLabel();
    }
  }

  // ── 15. ナビゲーション ──
  function tryNext() {
    if (S.phase === 1) {
      if (!S.TOTAL) return;
      S.phase = phaseAfterLoad(); S.page = 0; resetPhaseUi();
      if (S.phase === 2) S.page = firstEditablePage2();
      render();
      if (S.gray) prefetchFigCand();
      return;
    }
    if (S.phase === 2 || S.phase === 3) { advancePhase(); render(); }
  }
  // 戻るときは表示中のページ (`S.page`) を保つ。手順 4 で気付いた直しへそのページのまま戻れるようにするため
  // (ページ番号は全手順で共通の通し index なので、そのまま引き継げる)。
  function back() {
    resetPhaseUi();
    if (S.phase === 2) S.phase = 1;
    else if (S.phase === 3) S.phase = phaseBeforeTrim();
    else if (S.phase === 4) S.phase = phaseBeforeExport();
    if (S.phase === 2) landOnPhase2();
    render();
  }

  function wireStatic() {
    // ドラッグ直後に飛ぶ click を 1 回だけ握り潰すためのフラグ (`S.dragMoved`) は、次の mousedown が
    // 来た時点で必ず用済みになる (DOM のイベント順序は mousedown → mouseup → click なので、この
    // capture リスナは次の click より前に走る)。個別の経路 (ツール切替・手順移動・オーバーレイ上の
    // mousedown 等) でリセットを足す形だと、経路を 1 つ見落とすたびにクリック 1 回が空振りする
    // 不具合が再発する。ここ 1 箇所で不変条件として持つ。
    window.addEventListener("mousedown", function () { S.dragMoved = false; }, true);
    installCropDrag();
    installCoverDrag(document.getElementById("trim-stage"));
    installBorderDrag(document.getElementById("trim-stage"));
    installFigDrag(document.getElementById("fig-stage"));
    wireLoadUi();
    wireZoom();
    wireNav();
    wireEditTools();
    wireDictPane();
    wireExportPane();
  }

  /** 手順1: ファイル選択・ドロップゾーン (D&D と誤ドロップ時のバックストップ含む) */
  function wireLoadUi() {
    document.getElementById("btn-pick").addEventListener("click", doLoad);
    var dz = document.getElementById("dropzone");
    dz.addEventListener("click", function (e) {
      if (e.target.closest("#btn-pick")) return; doLoad();
    });
    // `tabindex=0` の div のため Enter/Space のキーボード起動を自前で足す (index.html 参照)。
    dz.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); doLoad(); }
    });
    // ドラッグ&ドロップで PDF 追加
    ["dragenter", "dragover"].forEach(function (ev) {
      dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.add("dragover"); });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      dz.addEventListener(ev, function (e) { e.preventDefault(); dz.classList.remove("dragover"); });
    });
    dz.addEventListener("drop", function (e) {
      var fl = (e.dataTransfer && e.dataTransfer.files) ? [].slice.call(e.dataTransfer.files) : [];
      var pdfs = fl.filter(function (f) { return f.type === "application/pdf" || /\.pdf$/i.test(f.name); });
      if (pdfs.length) addFiles(pdfs);
    });
    // ゾーン外に落としてもブラウザが PDF を開いて遷移しないようにする (バックストップ)
    ["dragover", "drop"].forEach(function (ev) {
      document.addEventListener(ev, function (e) { e.preventDefault(); });
    });
    function setGray(on) {
      S.gray = on;
      S.expMode = "all";  // グレーモードに spec は無い (手順 2・3 を通らない)
      S.svgCache = {};    // カラー/グレーで SVG が違う (キーも違うが、古い方を持ち続けない)
      render();
    }
    document.getElementById("mode-gray").addEventListener("change", function () { if (this.checked) setGray(true); });
    document.getElementById("mode-normal").addEventListener("change", function () { if (this.checked) setGray(false); });
  }

  /** 手順2/3: キャンバス内ズーム (＋/−/リセット・Ctrl+ホイール) */
  function wireZoom() {
    app.querySelectorAll(".zoom-ctrl [data-zoomact]").forEach(function (b) {
      b.addEventListener("click", function () {
        var act = b.dataset.zoomact;
        if (act === "reset") setZoom(1);
        else setZoom(curZoom() * (act === "in" ? 1.25 : 0.8));
      });
    });
    app.querySelectorAll('[data-screen="2"] .editor, [data-screen="3"] .editor, [data-screen="4"] .editor').forEach(function (ed) {
      ed.addEventListener("wheel", function (e) {
        if (!e.ctrlKey || (S.phase !== 2 && S.phase !== 3 && S.phase !== 4)) return;
        e.preventDefault();
        setZoom(curZoom() * (e.deltaY < 0 ? 1.1 : 1 / 1.1));
      }, { passive: false });
    });
  }

  /** フッター/ステップバー/Undo・Redo のナビゲーション */
  function wireNav() {
    document.getElementById("btn-back").addEventListener("click", back);
    document.getElementById("btn-next").addEventListener("click", tryNext);
    document.getElementById("btn-undo").addEventListener("click", async function () { await rpc("undo"); await afterEdit(); });
    document.getElementById("btn-redo").addEventListener("click", async function () { await rpc("redo"); await afterEdit(); });
    app.querySelectorAll("#stepbar .step").forEach(function (st) {
      st.addEventListener("click", function () {
        var n = +st.dataset.step; if (n > S.phase || !S.TOTAL || !stepAllowed(n)) return;
        // `back` と同じく表示中のページを保つ。今いる手順を押しただけなら編集中の選択・ツールは残す
        if (n !== S.phase) resetPhaseUi();
        S.phase = n;
        if (n === 2) landOnPhase2();
        render();
      });
    });
  }

  /** 手順2 パネルタブ・手順3 ツール切替・選択削除 */
  function wireEditTools() {
    app.querySelectorAll("[data-tab]").forEach(function (el) {
      el.addEventListener("click", function () { activateTab(el.dataset.tab); });
    });
    // 手順3 ツール
    app.querySelectorAll(".float-tools [data-tool]").forEach(function (b) {
      b.addEventListener("click", function () {
        // 押下中のタブをもう一度押したら無選択へ戻す (ドラッグ操作を止めてクリック選択だけにする)
        S.tool = S.tool === b.dataset.tool ? null : b.dataset.tool;
        // ツールを離れたら要素の選択 (青枠)・上書きの選択 (緑枠)・枠線の選択を解く。残すと複数の枠が
        // 同時に出て、「削除」が画面で選んだつもりの無い側まで消す
        S.elSel = {};
        clearCoverSel();
        clearBorderSel();
        render();
      });
    });
    // 枠線ツールの色・太さ。枠線を選んでいる間、入力欄は選択中の枠線の編集に使う。
    // `input` は未選択のときだけ「次に置く枠線」の値を直接更新する (選択中は触れない —
    // 触れると、選択を解いたあとに置く枠線へ編集中の値が紛れ込む)。確定 (`change`/Enter) は
    // `border.js` の `commitBorderStyle` へ渡し、選択の有無での書き分けもそちら 1 箇所に持たせる。
    var colorInput = document.getElementById("border-color");
    colorInput.addEventListener("input", function () { if (S.borderSel === null) S.borderColor = this.value; });
    colorInput.addEventListener("change", function () { commitBorderStyle({ color: this.value }); });
    var widthInput = document.getElementById("border-width");
    widthInput.addEventListener("input", function () {
      var v = parseFloat(this.value);
      var lo = parseFloat(this.min), hi = parseFloat(this.max);
      if (!isNaN(v) && v >= lo && v <= hi && S.borderSel === null) S.borderWidth = v;
    });
    widthInput.addEventListener("change", function () {
      // 範囲の正典は HTML の min / max (index.html の #border-width)。ここで数字を書かず属性から
      // 読むのは、範囲を HTML・JS・サーバの 3 箇所に書くとどれかがずれるため (サーバ側の
      // BORDER_WIDTH_MIN/MAX は HTML と揃える旨をコメントで結んである)。number 入力の min / max は
      // ブラウザが強制しないので、JS で検査しないと範囲外の値がサーバへ届き、拒否された値が
      // 入力欄に残る。
      var v = parseFloat(this.value);
      var lo = parseFloat(this.min), hi = parseFloat(this.max);
      if (!isNaN(v) && v >= lo && v <= hi) { commitBorderStyle({ width: v }); return; }
      // 弾いた値を表示に残すと、`change` は値が変わらない限り再発火しないので「表示だけ嘘」の状態で
      // 次の操作へ進める。直前の妥当な値 (次に置く太さ) へ戻す
      this.value = String(S.borderWidth);
    });
    widthInput.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); this.blur(); } });
    // 上書きツールの置換語。上書きを選んでいる間、入力欄は選択中の要素の語の編集に使う。
    // `input` は未選択のときだけ次に置く語 (`S.coverText`) を直接更新する (選択中は
    // `S.coverText` に触れない — 触れると、選択を解いたあとに置く上書きへ編集中の語が
    // 紛れ込む)。確定 (`change`/Enter) は `cover.js` の `commitCoverText` へ渡し、
    // 選択の有無での書き分けもそちら 1 箇所に持たせる。
    var coverInput = document.getElementById("cover-text");
    coverInput.addEventListener("input", function () { if (S.coverSel === null) S.coverText = this.value; });
    coverInput.addEventListener("change", function () { commitCoverText(this.value); });
    coverInput.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); this.blur(); } });
    document.getElementById("btn-deletesel").addEventListener("click", async function () {
      var pg = S.PAGES[S.page]; if (!pg) return;
      var ids = Object.keys(curElSel());
      // 上書きツールで選んだ上書き (緑枠) も同じ削除経路へ載せる。ツールを切り替えると要素の選択は解けるため、
      // 実際に入るのはどちらか片方だけ
      if (S.coverSel !== null && ids.indexOf(String(S.coverSel)) < 0) ids.push(String(S.coverSel));
      if (S.borderSel !== null && ids.indexOf(String(S.borderSel)) < 0) ids.push(String(S.borderSel));
      if (!ids.length) return;
      // 削除する要素の選択を即座に解く (elIds はここまでに ids へ確定済みなので、この後 RPC 往復を
      // 待たずに消しても削除自体には影響しない)。`await rpc` の後まで残すと、`afterEdit` →
      // `render()` → `syncDeleteButton()` が削除予定の id をまだ選択中と見て有効のままにし、
      // 非同期の一覧再取得 (オーバーレイの `draw()`) が届くまでボタンが一瞬ずれる。
      // 選択解除は `rect-overlay.js` の `clearOverlaySel` 経由に一元化されているため、
      // ここも `S.coverSel` / `S.borderSel` への直接代入ではなく `clearCoverSel` / `clearBorderSel`
      // を呼ぶ。直接代入だと `clearOverlaySel` の `onSelect(null)` を通らず、入力欄が削除済み要素の
      // 値のまま残る (`syncDeleteButton()` の呼び出しも一緒に素通りする)。
      clearCoverSel();
      clearBorderSel();
      await rpc("applyDelete", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elIds: ids });
      await afterEdit();
    });
  }

  /** 辞書ペイン (追加・折返し連結・再適用・入出力) */
  function wireDictPane() {
    document.getElementById("dict-add").addEventListener("click", async function () {
      var src = document.getElementById("dict-src"); var tgt = document.getElementById("dict-tgt");
      if (!src.value.trim()) return;
      try {
        dictState = await rpc("dictAdd", { source: src.value, target: tgt.value, joined: pendingJoined });
      } catch (e) {
        // 件数上限に達した等。握り潰すと「押しても増えない」になるので理由を出す。
        toast(String((e && e.message) || "用語を追加できませんでした"));
        return;
      }
      pendingJoined = false;
      src.value = ""; tgt.value = ""; renderDict();
      // 登録した語に当たるページは一致件数 (`S.matches2`) が変わるため、他の辞書操作
      // (再適用・戻す) と同じく state を取り直す。
      await reloadState(); render();
    });
    // 元の語を手編集したら連結由来を外す (取り込んだ連結文字列ではなくなるため)
    document.getElementById("dict-src").addEventListener("input", function () {
      pendingJoined = false;
    });
    document.getElementById("chk-suggest-join").addEventListener("click", async function () {
      dictState.suggestJoin = !dictState.suggestJoin;
      await rpc("setSuggestJoin", { value: dictState.suggestJoin }); renderDict();
    });
    document.getElementById("btn-reapply").addEventListener("click", async function () {
      var r = await rpc("reapplyDict");
      await reloadState();
      var msg = "辞書を再適用しました（" + r.count + " 件置換";
      if (r.warnings) msg += ", うち " + r.warnings + " 件 幅超過";
      setHint(msg + "）");
      render();
    });
    document.getElementById("btn-reapply-page").addEventListener("click", async function () {
      if (S.page >= S.TOTAL) return;
      var pg = S.PAGES[S.page];
      var r = await rpc("reapplyDictPage", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
      invalidate(pg.fileIndex, pg.pageInFile);  // 置換で SVG が変わるため当該ページを再生成
      await reloadState();
      var msg = "このページに再適用しました（" + r.count + " 件置換";
      if (r.warnings) msg += ", うち " + r.warnings + " 件 幅超過";
      setHint(msg + "）");
      render();
    });
    document.getElementById("btn-dict-export").addEventListener("click", async function () {
      var r = await rpc("dictJson");
      var ok = await saveTextFile("dictionary.json", r.json, "JSON", "application/json", ".json");
      if (!ok) return;
      setHint("辞書を書き出しました（" + (r.count || 0) + " 件）");
    });
    document.getElementById("btn-dict-import").addEventListener("click", async function () {
      var f = await pickOneFile("JSON", "application/json", ".json");
      if (!f) return;
      var text = await f.text();
      var r;
      try {
        r = await rpc("dictImportJson", { json: text });
      } catch (e) {
        // 件数上限超過・読み込み失敗はサーバが理由付きで拒否する。握り潰すと
        // 「押しても何も起きない」になるので、必ず理由を出す。
        toast(String((e && e.message) || "辞書を読み込めませんでした"));
        return;
      }
      dictState = r; renderDict();
      // 捨てた件数も必ず出す (取り込み件数だけ見せると、壊れた要素が黙って消える)。
      var msg = "辞書を読み込みました（" + (r.imported || 0) + " 件";
      if (r.skipped) msg += "、" + r.skipped + " 件は形式が不正のため読み飛ばし";
      setHint(msg + "）");
    });
  }

  // 文字入力中の要素か。入力欄では Ctrl+Z が「打った文字を戻す」意味になるため、
  // 文書側のショートカットはそちらへ譲る。
  function isTextEntry(target) {
    if (!target || !target.tagName) return false;
    var tag = target.tagName.toLowerCase();
    return tag === "input" || tag === "textarea" || !!target.isContentEditable;
  }

  /** 入力欄にフォーカスが残っていれば外す。キャンバスの操作 (ラバーバンドの開始・編集の成功) の
   *  あとに呼ぶ。入力欄にフォーカスがある間の Ctrl+Z は「ブラウザ標準の取り消しへ譲る」
   *  (`isTextEntry` のガード) ため、外さないと「語を打つ → 範囲を引く → Ctrl+Z」で上書きが戻らず、
   *  代わりに入力欄の語が消える。キャンバスの mousedown はテキスト選択を防ぐため
   *  `preventDefault()` しており、それだけではフォーカスが移らない。
   *  blur で `change` が発火し確定処理 (`commitCoverText` / `commitBorderStyle`) が走るが、
   *  ラバーバンド開始時は直前に選択を解いているので「次に置く値」を書くだけで RPC は飛ばず、
   *  編集成功後は RPC 済みで入力欄は同期済みなので差分が無い。箱を掴んだ瞬間には呼ばない
   *  (選択中の要素があると確定 RPC → 再マウント → ドラッグ中の箱が消えるため)。 */
  function blurTextEntry() {
    var el = document.activeElement;
    if (isTextEntry(el)) el.blur();
  }

  /** 書き出し範囲・実行・ショートカット・進捗 */
  function wireExportPane() {
    app.querySelectorAll(".segment [data-mode]").forEach(function (b) {
      b.addEventListener("click", function () { S.expMode = b.dataset.mode; refreshExport(); });
    });
    document.getElementById("exp-file").addEventListener("change", function () { S.expFile = +this.value; refreshExport(); });
    document.getElementById("exp-spec").addEventListener("input", refreshExport);
    document.getElementById("btn-export").addEventListener("click", doExport);
    // ショートカット。ページが 1 つも無い間は後処理が現在ページを前提にできないので撃たず、
    // 入力欄でのキー操作はブラウザ標準の取り消しへ譲る。押さえた時だけ既定動作を止める。
    window.addEventListener("keydown", function (e) {
      if (!e.ctrlKey) return;
      var key = e.key.toLowerCase();
      if (key !== "z" && key !== "y") return;
      if (isTextEntry(e.target)) return;
      if (!S.TOTAL || !S.PAGES[S.page]) return;
      e.preventDefault();
      rpc(key === "z" ? "undo" : "redo").then(afterEdit);
    });
    // 進捗
    window.onProgress(function (msg) { setHint(esc(msg)); });
  }

  // 書き出し範囲テキスト入力の現在値 (state.js は DOM 非依存のため引数で渡す)
  function expSpecValue() { var el = document.getElementById("exp-spec"); return el ? el.value : ""; }

  function refreshExport() {
    app.querySelectorAll(".segment [data-mode]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.dataset.mode === S.expMode ? "true" : "false");
    });
    var specRow = document.getElementById("exp-spec-row");
    if (specRow) specRow.style.display = S.expMode === "spec" ? "flex" : "none";
    var sel = document.getElementById("exp-file");
    if (sel) {
      sel.innerHTML = S.FILES.map(function (f, i) {
        return '<option value="' + i + '">' + esc(f.name) + "（" + f.pages + "ページ）</option>";
      }).join("");
      if (S.expFile >= S.FILES.length) S.expFile = 0;
      sel.value = String(S.expFile);
    }
    var num = S.gray ? (S.expMode === "page" ? figSelOf(S.page).length : figCount()) : expCount(expSpecValue(), parseSpec);
    document.getElementById("exp-num").textContent = num;
    // 書き出す個数はフッターの案内にも出す。範囲のボタン・ファイル選択・ページ指定の
    // 入力は `render()` を通らずここだけを呼ぶため、案内の文言もここで作らないと古い件数が残る。
    // グレーモードの案内は採用した図の数を出す別の文言なので、`render()` 側に置いたままにする。
    if (S.phase === 4 && !S.gray) {
      setHint(num === 0 ? "書き出すページがありません"
        : num === 1 ? "1 個の SVG を保存します"
        : num + " 個の SVG を zip にまとめて保存します");
    }
    var btn = document.getElementById("btn-export");
    if (btn) btn.disabled = S.gray && num === 0;
  }

  // 書き出し完了トーストへ連結する「背景色を採れなかった箇所」の追記。件数が 0 なら
  // 空文字列 (既存の完了トーストの文言は変えないため、足さない)。
  function coverSuffix(n) { return n ? " / 背景色を採れなかった " + n + " 箇所は白で上書きしました" : ""; }

  // ZIP 集約 1 リクエストの送信バイト予算。サーバの RPC 本文上限 (8 MiB) の 9 割を使い、
  // 残りは JSON の外枠 (メソッド名・引数キー) の余白に充てる。
  var ZIP_REQUEST_BUDGET = Math.floor(8 * 1024 * 1024 * 0.9);
  var _utf8 = new TextEncoder();
  // 1 entry が JSON 本文に占めるバイト数。SVG は引用符が多くエスケープで膨らむので、
  // 文字数ではなく直列化後の実バイト数で数える (区切りのカンマ分を 1 足す)。
  function entryRequestBytes(e) { return _utf8.encode(JSON.stringify(e)).length + 1; }

  // 複数 ZIP に分かれたときの各本の名前 (`sample_svg.zip` → `sample_svg_1.zip`)。
  function zipPartName(base, index) { return base.replace(/\.zip$/i, "") + "_" + index + ".zip"; }

  async function doExport() {
    var btn = document.getElementById("btn-export");
    var prog = document.getElementById("exp-progress");
    try {
      if (S.gray) {
        var figs = exportFigureList();
        if (!figs.length) { setHint("採用した図がありません。ページ上の候補をクリックしてください。"); return; }
        await exportEntries(figs, btn, prog);
        return;
      }
      if (S.expMode === "page") {
        var pg = S.PAGES[S.page] || { fileIndex: 0, pageInFile: 0 };
        var one = await rpc("exportSvg", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
        var ok = await saveTextFile(one.name, one.svg, "SVG", "image/svg+xml", ".svg");
        if (!ok) return;
        setHint('<b style="color:var(--good-ink)">1個のSVGを書き出しました。</b>');
        toast("1個のSVGを書き出しました" + coverSuffix(one.coverFallback));
        return;
      }
      var list = exportPageList(expSpecValue(), parseSpec);
      if (!list.length) { setHint("書き出す対象のページがありません。"); return; }
      await exportEntries(list, btn, prog);
    } catch (e) {
      // 失敗を握り潰すと「押しても何も起きない」になる。理由を出して再試行できる状態へ戻す。
      toast(String((e && e.message) || "書き出しに失敗しました"));
      setHint("書き出しに失敗しました。内容を確認して、もう一度お試しください。");
    } finally {
      if (btn) btn.disabled = false;
      if (prog) prog.hidden = true;
    }
  }

  // `exportSvg` をページ (または図) ごとに呼び、1 件なら直接ダウンロード、複数は ZIP へ集約する。
  // 既存の全ページ書き出しと図の書き出しで同じ経路を使う (進捗・ZIP 分割・文言を二重に持たない)。
  async function exportEntries(list, btn, prog) {
    // 変換中はボタンを止め、総数が既知の i/N を進捗バーでも示す (フッター文字だけでは
    // 固まったように見える)。SVG 変換はページごとに `exportSvg` を呼んで進捗を刻む。
    if (btn) btn.disabled = true;
    if (prog) { prog.hidden = false; prog.max = list.length; prog.value = 0; }
    var entries = [];
    var coverFallbackTotal = 0;
    for (var i = 0; i < list.length; i++) {
      setHint("書き出し中 " + (i + 1) + "/" + list.length);
      var item;
      if (list[i].clip) {
        // グレーモード (図の切り出し) はどのページ・どの図で失敗したかが分からないと
        // 探し直せない。カラー側 (clip 無し) は従来どおりの文言のまま変えない。
        try {
          item = await rpc("exportSvg", list[i]);
        } catch (e) {
          throw new Error((list[i].pageInFile + 1) + " ページ目の図 " + (list[i].figIndex || "") + ": " + String((e && e.message) || e));
        }
      } else {
        item = await rpc("exportSvg", list[i]);
      }
      coverFallbackTotal += item.coverFallback || 0;
      entries.push({ name: item.name, text: item.svg });
      if (prog) prog.value = i + 1;
    }
    if (entries.length === 1) {
      // `downloadBlob` はブラウザ任せの保存で、ブロックされたかを Web API から検知できない。
      // 保存先を選ぶ FSA 経路 (上の `saveTextFile`) と違い、完了を断定しない文言にする。
      downloadBlob(entries[0].name, entries[0].text, "image/svg+xml");
      setHint('<b style="color:var(--good-ink)">1個のSVGのダウンロードを開始しました。</b>');
      toast("1個のSVGのダウンロードを開始しました" + coverSuffix(coverFallbackTotal));
      return;
    }
    // 複数ページは ZIP へ集約する — N 個の個別ダウンロード (Edge の連続 DL 確認に
    // 阻まれ、ダウンロードフォルダも散らかる) を避ける。集約はサーバ側 `zipEntries`。
    // 1 リクエストの本文上限を超える量は複数本へ分ける (1 本に詰めると書き出しごと失敗する)。
    var chunks = chunkBySize(entries, entryRequestBytes, ZIP_REQUEST_BUDGET);
    var base = zipName(list);
    var total = 0;
    for (var c = 0; c < chunks.length; c++) {
      setHint(chunks.length === 1 ? "ZIP にまとめています…"
        : "ZIP にまとめています… " + (c + 1) + "/" + chunks.length);
      var z = await rpc("zipEntries", { entries: chunks[c] });
      downloadBlob(chunks.length === 1 ? base : zipPartName(base, c + 1),
        b64ToBytes(z.zipBase64), "application/zip");
      total += z.count;
    }
    var suffix = chunks.length === 1 ? " ZIP でダウンロード開始しました。" : " ZIP " + chunks.length + " 本に分けてダウンロード開始しました。";
    setHint('<b style="color:var(--good-ink)">' + total + "個のSVGを" + suffix + "</b>");
    toast(total + "個のSVGを" + (chunks.length === 1 ? " ZIP 1 ファイルで" : " ZIP " + chunks.length + " ファイルに分けて") + "ダウンロード開始しました" + coverSuffix(coverFallbackTotal));
  }

  // ── 16. ライフサイクル (サーバ常駐管理) ──
  // `app.py` は「窓を閉じた時の /quit ビーコン」＋「/ping ハートビート途絶を見張る
  // watchdog」でサーバを終了する設計。クライアントがこれらを送らないと、Edge の
  // コールド再起動で起動プロセスが早期終了した際にサーバが落ちて初回起動が空白になる。
  function startLifecycle() {
    // 生存ハートビート: last_seen を定期更新し、開いている間は watchdog に殺させない。
    setInterval(function () {
      fetch("/ping", {
        method: "POST", keepalive: true, headers: window.__authHeaders(),
      }).catch(function () {});
    }, 10000);
    // 窓を閉じる時の終了ビーコン。beforeunload ではなく pagehide + sendBeacon が確実。
    // 最小化でも hidden になる visibilitychange は使わない (最小化でサーバを殺さないため)。
    // ビーコン不達でもハートビート途絶 watchdog がバックストップになる。
    // `sendBeacon` はヘッダを付けられないため、トークンだけはクエリで送る (`__authUrl`)。
    window.addEventListener("pagehide", function () {
      try { navigator.sendBeacon(window.__authUrl("/quit")); } catch (e) {}
    });
  }

  // ── 17. 起動 ──
  window.__rpcReady.then(function () {
    window.__state = S; // E2E/デバッグ用の読み取り窓
    initRail({ render: render });
    initPageJump({ render: render });
    initFigure({ render: render });
    initCover({ rpc: rpc, afterEdit: afterEdit, pageOf: function () { return S.PAGES[S.page]; }, syncDeleteButton: syncDeleteButton });
    initBorder({ rpc: rpc, afterEdit: afterEdit, pageOf: function () { return S.PAGES[S.page]; }, syncDeleteButton: syncDeleteButton });
    wireStatic();
    render();
    startLifecycle();
  });
})();
