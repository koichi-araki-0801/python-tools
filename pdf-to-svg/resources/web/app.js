// =============================================================================
// app.js — PdfToSvg フロントエンド (4 ステップ状態機械の本体)
// =============================================================================
// 役割: 4 ステップ状態機械として、データ・ページ描画・編集・書き出しを
// Python バックエンド (`window.rpc`) に接続する。状態に依存しない純粋ヘルパは
// `dom.js` / `geometry.js` が持つ (type="module" で読込)。
import { esc, svg } from "./dom.js";
import { clientToPage, parseSpec } from "./geometry.js";
import {
  S, counts, pass, initStatus,
  statusArr, changedArr, selSet, pkey, curElSel, statusOfCur, selKeys, selCount, clearSel,
  applyState, invalidateAll, nextPending, firstPending, advancePhase,
  exportPageList, expCount, zipName, chunkBySize,
} from "./state.js";
import { fileIcon, xIcon, checkD, ckMark } from "./icons.js";
import { initRail, buildRail } from "./rail.js";

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
  var degradedNoticed = { truncated: 0, noBackground: 0 };
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
    degradedNoticed.truncated = st.truncated || 0;
    degradedNoticed.noBackground = st.noBackground || 0;
    if (msgs.length) toast(msgs.join(" / "));
  }

  // File 配列を順にアップロードして状態を更新する (クリック選択・D&D 共用)。
  // 途中で失敗しても、そこまでに取り込めた分は必ず画面へ反映する。失敗を投げっぱなしに
  // すると読み込み中の表示のまま止まり、成功した分も一覧に出ず理由も届かない。
  async function addFiles(files) {
    if (!files || !files.length) { render(); return; }
    var failed = null;
    try {
      for (var i = 0; i < files.length; i++) {
        setHint("読み込み中 " + (i + 1) + "/" + files.length + ": " + esc(files[i].name));
        var buf = await files[i].arrayBuffer();
        failed = files[i].name;
        await uploadPdf(files[i].name, buf);
        failed = null;
      }
    } catch (e) {
      toast("「" + failed + "」を読み込めませんでした: " + String((e && e.message) || e));
    }
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
      return '<div class="file-card"><div class="fic">' + svg(fileIcon, 20) +
        '</div><div class="fmeta"><div class="fname">' + esc(f.name) + '</div><div class="fsub">' +
        f.pages + " ページ" + (f.size ? " ・ " + f.size : "") + "</div></div>" +
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
  }
  // ── 6. ページ SVG ──
  async function ensureSvg(fi, pi) {
    var k = fi + ":" + pi;
    if (!S.svgCache[k]) S.svgCache[k] = await rpc("pageSvg", { fileIndex: fi, pageInFile: pi });
    return S.svgCache[k];
  }
  function invalidate(fi, pi) { delete S.svgCache[fi + ":" + pi]; }

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
    var host = document.getElementById(S.phase === 2 ? "doc-master" : "trim-stage");
    if (!host) return;
    var svgEl = host.querySelector("svg");
    var data = S.svgCache[pkey()];
    if (svgEl && data) {
      scalePage(svgEl, data.width, data.height, app.querySelector('[data-screen="' + S.phase + '"] .editor'));
      if (S.phase === 3) drawSelBoxes(host); // sel-box は host 相対なので再計算
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
    if (!S.svgCache[pg.fileIndex + ":" + pg.pageInFile]) {
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

  // ── 8. 左: ページ一覧 — rail.js の buildRail/wireRail が担う (initRail で render/tryNext を注入) ──

    function renderSummary(id, arr) {
    var c = counts(arr);
    document.getElementById(id).innerHTML =
      '<span class="si"><span class="d pend"></span>要確認 <b>' + c.pend + "</b></span>" +
      '<span class="si"><span class="d done"></span>確認済み <b>' + c.done + "</b></span>" +
      '<span class="si"><span class="d skip"></span>スキップ <b>' + c.skip + "</b></span>" +
      '<span class="si"><span class="d pend" style="background:var(--border-strong)"></span>変更なし <b>' + c.none + "</b></span>";
  }

  // ── 9. 確認ペイン (手順2) ──
  async function renderConfirm() {
    var el = document.getElementById("confirm-dyn");
    var ed2 = app.querySelector('[data-screen="2"] .editor');
    if (!S.changed2[S.page]) {
      ed2.classList.add("nochange");
      el.innerHTML = noChangeNote("このページに置換はありません");
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
    el.innerHTML =
      '<div class="confirm-banner"><span class="ic">' + svg('<path d="' + checkD + '"/>', 22, 2.2) + '</span><div><div class="t">このページで ' +
      applied + ' 件を置換</div>' + (pending ? '<div class="t sub">未置換 ' + pending + ' 件</div>' : "") +
      '<div class="s">番号はページ上のマーカーと対応します</div></div></div>' +
      '<div style="display:flex;flex-direction:column;min-height:0;flex:1;"><div class="field-label">変更の一覧（行に乗せると該当箇所を強調）</div><div class="change-list">' +
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

  // ── 10. 削除ペイン (手順3) ──
  async function renderTrim() {
    var el = document.getElementById("trim-dyn");
    var ed3 = app.querySelector('[data-screen="3"] .editor');
    ed3.classList.remove("nochange");
    var pg = S.PAGES[S.page];
    var token = pg.fileIndex + ":" + pg.pageInFile;
    var data;
    try {
      data = await rpc("removedList", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
    } catch (e) {
      if (token !== S.PAGES[S.page].fileIndex + ":" + S.PAGES[S.page].pageInFile) return; // ページが変わった
      renderPaneError(el, "削除した要素の一覧を取得できませんでした: " + String((e && e.message) || e));
      return;
    }
    if (token !== S.PAGES[S.page].fileIndex + ":" + S.PAGES[S.page].pageInFile) return; // ページが変わった
    var n = data.removed.length;
    var head = '<div class="field-label">このページで削除した要素（' + n + "）</div>";
    if (n === 0) {
      el.innerHTML = head + '<div class="empty-note" style="flex:1"><div class="et" style="color:var(--faint)">要素を選んで「削除」、または「範囲削除」でドラッグした領域内の要素をまとめて削除します。</div></div>';
      return;
    }
    var rows = data.removed.map(function (r) {
      return '<div class="removed-row"><span class="ric">' + svg('<path d="M4 7h16M6 7v12.5A1.5 1.5 0 0 0 7.5 21h9a1.5 1.5 0 0 0 1.5-1.5V7"/>', 15) +
        '</span><span class="rlabel">' + esc(r.label) + '</span><button class="pa-link" data-restore="' + r.elId + '">戻す</button></div>';
    }).join("");
    el.innerHTML = head + '<div class="change-list">' + rows + "</div>";
    el.querySelectorAll("[data-restore]").forEach(function (b) {
      b.addEventListener("click", async function () {
        // 行の要素だけを戻す。全体の undo は直近 1 件しか戻せず、複数回に分けて削除した
        // 後や別ページで削除した後に押すと無関係な操作を取り消してしまう。
        await rpc("restoreElements", {
          fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elIds: [+b.dataset.restore],
        });
        await afterEdit();
      });
    });
  }

  // ── 11. 手順3 エディタ操作 ──
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

  // 選択モードのクリック結線のみ。SVG は mountPage で毎回差し替わるため漏れない。
  // crop ドラッグのリスナーは wireStatic で一度だけ張る (多重登録防止)。
  function wireTrimStage() {
    if (S.tool !== "select") return;
    var host = document.getElementById("trim-stage");
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    svgEl.addEventListener("click", function (e) {
      var t = e.target.closest("[data-el]"); if (!t) return;
      var id = t.getAttribute("data-el"); var sel = curElSel();
      if (sel[id]) delete sel[id]; else sel[id] = true;
      drawSelBoxes(host);
    });
  }

  // crop/border ツール: ドラッグした矩形で範囲削除 (crop) または枠線追加 (border)。
  // リスナーは起動時に一度だけ設置し、イベント時に S.phase/S.tool を判定する。
  function installCropDrag() {
    var host = document.getElementById("trim-stage");
    host.addEventListener("mousedown", function (e) {
      if (S.phase !== 3 || (S.tool !== "crop" && S.tool !== "border")) return;
      if (!host.querySelector("svg")) return;
      var rubber = document.createElement("div");
      rubber.className = S.tool === "border" ? "border-rubber" : "crop-rubber";
      host.appendChild(rubber);
      S.cropDrag = { origin: { x: e.clientX, y: e.clientY }, rubber: rubber, mode: S.tool };
      e.preventDefault();
    });
    window.addEventListener("mousemove", function (e) {
      if (!S.cropDrag) return;
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
      var x = Math.min(a.x, b.x), y = Math.min(a.y, b.y);
      var w = Math.abs(a.x - b.x), h = Math.abs(a.y - b.y);
      if (w < 4 || h < 4) return;
      var pg = S.PAGES[S.page]; var rect = { x: x, y: y, w: w, h: h };
      if (d.mode === "border") {
        await rpc("addBorder", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, rect: rect, color: S.borderColor, width: S.borderWidth });
      } else {
        await rpc("deleteRegion", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, rect: rect });
      }
      await afterEdit();
    });
  }

  async function afterEdit() {
    var pg = S.PAGES[S.page];
    invalidate(pg.fileIndex, pg.pageInFile);
    curElSel(); S.elSel[pkey()] = {};
    render();
  }

  // Undo/Redo は現在ページ以外の編集も巻き戻す (別ページで削除してからページを移った後など)。
  // 現在ページだけ作り直す `afterEdit` では他ページが古い SVG のまま残り、置換の有無が
  // 変わった分も案内バーに反映されないので、キャッシュを全ページ分捨てて state も取り直す。
  async function afterUndoRedo() {
    invalidateAll();
    await reloadState();
    render();
  }

  // ── 12. ページ単位アクション ──
  function pageActHTML() {
    var st = statusOfCur();
    if (st === "none") return '<div class="pa-prompt" style="margin:0">このページは変更がないため操作は不要です</div>';
    if (st === "reviewed") return '<div class="pa-badge good">' + svg('<path d="' + checkD + '"/>', 17) + 'このページは確認済み</div><button class="pa-link" data-pa="reset">取り消す</button>';
    if (st === "skipped") return '<div class="pa-badge warn">' + svg('<path d="M9 8l4 4-4 4M15 8v8"/>', 17) + 'このページはスキップ</div><button class="pa-link" data-pa="review">確認する</button>';
    return '<div class="pa-prompt">' + (S.phase === 2 ? "このページの置換を確認、または不要ならスキップ" : "このページを確認、または不要ならスキップ") + "</div>" +
      '<div class="pa-btns"><button class="btn ghost" data-pa="skip">スキップ</button><button class="btn primary" data-pa="done">' + (S.phase === 2 ? "確認しました" : "確認しました") + "</button></div>";
  }
  function onPageAct(actv) {
    var arr = statusArr();
    if (actv === "done") { arr[S.page] = "reviewed"; var n1 = nextPending(arr); if (n1 >= 0) S.page = n1; }
    else if (actv === "skip") { arr[S.page] = "skipped"; var n2 = nextPending(arr); if (n2 >= 0) S.page = n2; }
    else { arr[S.page] = "pending"; }
    render();
  }
  function renderPageAct() {
    var el = document.getElementById(S.phase === 2 ? "pageact-2" : "pageact-3");
    el.innerHTML = pageActHTML();
    el.querySelectorAll("[data-pa]").forEach(function (b) { b.addEventListener("click", function () { onPageAct(b.dataset.pa); }); });
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
        // 削除した語に当たっていたページは「要確認」から降りる。state を取り直さないと
        // 案内バーが消えた語の件数を数え続ける。
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

  function render() {
    var steps = [].slice.call(app.querySelectorAll("#stepbar .step"));
    var screens = [].slice.call(app.querySelectorAll(".screen"));
    var btnBack = document.getElementById("btn-back");
    var btnNext = document.getElementById("btn-next");
    var btnExport = document.getElementById("btn-export");
    var ctxText = document.getElementById("ctx-text");
    var guard = document.getElementById("guard");

    screens.forEach(function (s) { s.classList.toggle("on", +s.dataset.screen === S.phase); });
    steps.forEach(function (st) {
      var n = +st.dataset.step; var done = n < S.phase, active = n === S.phase;
      st.classList.toggle("done", done); st.classList.toggle("active", active);
      st.classList.toggle("future", !done && !active); st.classList.toggle("clickable", n <= S.phase);
      st.querySelector(".n").innerHTML = done ? ckMark : n;
    });
    if (S.guarding && (S.phase === 2 || S.phase === 3)) {
      var gpend = counts(statusArr()).pend;
      if (gpend === 0) S.guarding = false;            // 未確認0 → ガードを閉じる
      else document.getElementById("guard-n").textContent = gpend; // 件数を最新に
    }
    guard.hidden = !S.guarding;
    btnBack.style.visibility = S.phase === 1 ? "hidden" : "visible";
    btnNext.style.display = S.phase < 4 ? "" : "none";
    btnExport.style.display = S.phase === 4 ? "" : "none";
    btnNext.childNodes[0].nodeValue = S.phase === 3 ? "書き出しへ" : "次へ";
    btnNext.disabled = (S.phase === 1 && S.TOTAL === 0);
    btnNext.style.opacity = btnNext.disabled ? ".5" : "";

    if (S.phase === 1) {
      setHint(S.TOTAL ? "「次へ」で用語の置換に進みます" : "変換するPDFを選びます");
      ctxText.textContent = S.TOTAL ? S.FILES.length + " ファイル・" + S.TOTAL + " ページ" : "ファイル未選択";
    } else if (S.phase === 4) {
      setHint("内容を確認して書き出します。");
      ctxText.textContent = S.FILES.length + " ファイル・" + S.TOTAL + " ページ";
      refreshExport();
      var s2 = counts(S.status2), s3 = counts(S.status3);
      document.getElementById("export-summary").innerHTML =
        S.FILES.length + "ファイル・全" + S.TOTAL + "ページ<br/>用語：確認 " + s2.done + " / スキップ " + s2.skip +
        "　削除：確認 " + s3.done + " / スキップ " + s3.skip;
    } else {
      var task = S.phase === 2 ? "用語の置換" : "削除・枠線の編集";
      var c = counts(statusArr());
      setHint(task + " — 要確認 <b>" + c.pend + "</b> / 確認済み <b>" + c.done + "</b> / スキップ <b>" + c.skip + "</b>");
      var pg = S.PAGES[S.page];
      ctxText.textContent = S.FILES[pg.fileIndex].name + " ・ " + (pg.pageInFile + 1) + "/" + S.FILES[pg.fileIndex].pages + " ページ";
    }

    if (S.phase === 2 && S.TOTAL) {
      buildRail("pagenav"); renderSummary("sum-2", S.status2); renderPageAct();
      document.getElementById("pgnav-2").innerHTML = pageLabel();
      mountPage(document.getElementById("doc-master"), app.querySelector('[data-screen="2"] .editor'), false, function () {
        wireConfirmPick();
        drawChangeMarkers(S.lastChanges || []);
      });
      renderConfirm();
      updateZoomLabel();
    }
    if (S.phase === 3 && S.TOTAL) {
      buildRail("pagenav-3"); renderSummary("sum-3", S.status3); renderPageAct();
      document.getElementById("pgnav-3").innerHTML = pageLabel();
      var ed3 = app.querySelector('[data-screen="3"] .editor');
      ed3.classList.toggle("tool-crop", S.tool === "crop");
      ed3.classList.toggle("tool-select", S.tool === "select");
      ed3.classList.toggle("tool-border", S.tool === "border");
      var bo = document.getElementById("border-opts");
      if (bo) bo.hidden = S.tool !== "border";
      mountPage(document.getElementById("trim-stage"), ed3, true, wireTrimStage);
      renderTrim();
      updateZoomLabel();
    }
  }

  // ── 15. ナビゲーション ──
  function tryNext() {
    if (S.phase === 1) { if (!S.TOTAL) return; S.phase = 2; S.page = 0; S.guarding = false; render(); return; }
    if (S.phase === 2 || S.phase === 3) {
      var pend = counts(statusArr()).pend;
      if (pend > 0) { S.guarding = true; document.getElementById("guard-n").textContent = pend; render(); return; }
      advancePhase(); render();
    }
  }
  function back() {
    S.guarding = false;
    if (S.phase === 2) S.phase = 1; else if (S.phase === 3) { S.phase = 2; S.page = 0; } else if (S.phase === 4) { S.phase = 3; S.page = 0; }
    render();
  }

  function wireStatic() {
    installCropDrag();
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
    app.querySelectorAll('[data-screen="2"] .editor, [data-screen="3"] .editor').forEach(function (ed) {
      ed.addEventListener("wheel", function (e) {
        if (!e.ctrlKey || (S.phase !== 2 && S.phase !== 3)) return;
        e.preventDefault();
        setZoom(curZoom() * (e.deltaY < 0 ? 1.1 : 1 / 1.1));
      }, { passive: false });
    });
  }

  /** フッター/ステップバー/ガード/Undo・Redo のナビゲーション */
  function wireNav() {
    document.getElementById("btn-back").addEventListener("click", back);
    document.getElementById("btn-next").addEventListener("click", tryNext);
    document.getElementById("btn-undo").addEventListener("click", async function () { await rpc("undo"); await afterUndoRedo(); });
    document.getElementById("btn-redo").addEventListener("click", async function () { await rpc("redo"); await afterUndoRedo(); });
    document.getElementById("guard-back").addEventListener("click", function () { S.guarding = false; S.page = firstPending(statusArr()); render(); });
    document.getElementById("guard-skip").addEventListener("click", function () {
      var arr = statusArr(); for (var i = 0; i < S.TOTAL; i++) if (arr[i] === "pending") arr[i] = "skipped"; advancePhase(); render();
    });
    app.querySelectorAll("#stepbar .step").forEach(function (st) {
      st.addEventListener("click", function () {
        var n = +st.dataset.step; if (n > S.phase || !S.TOTAL) return;
        S.guarding = false; S.phase = n; if (n === 2 || n === 3) S.page = 0; clearSel(); render();
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
        S.tool = b.dataset.tool;
        app.querySelectorAll(".float-tools [data-tool]").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
        render();
      });
    });
    // 枠線ツールの色・太さ
    document.getElementById("border-color").addEventListener("input", function () { S.borderColor = this.value; });
    document.getElementById("border-width").addEventListener("input", function () {
      var v = parseFloat(this.value); if (!isNaN(v) && v > 0) S.borderWidth = v;
    });
    document.getElementById("btn-deletesel").addEventListener("click", async function () {
      var pg = S.PAGES[S.page]; if (!pg) return;
      var ids = Object.keys(curElSel()); if (!ids.length) return;
      await rpc("applyDelete", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elIds: ids }); await afterEdit();
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
      // 登録した語に当たるページは「要確認」へ上がる。他の辞書操作 (再適用・戻す) と同じく
      // state を取り直さないと、確認済みのページに新語が当たっても案内バーが気付かない。
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
      rpc(key === "z" ? "undo" : "redo").then(afterUndoRedo);
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
    document.getElementById("exp-num").textContent = expCount(expSpecValue(), parseSpec);
  }

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
      if (S.expMode === "page") {
        var pg = S.PAGES[S.page] || { fileIndex: 0, pageInFile: 0 };
        var one = await rpc("exportSvg", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
        var ok = await saveTextFile(one.name, one.svg, "SVG", "image/svg+xml", ".svg");
        if (!ok) return;
        setHint('<b style="color:var(--good-ink)">1個のSVGを書き出しました。</b>');
        toast("1個のSVGを書き出しました");
        return;
      }
      var list = exportPageList(expSpecValue(), parseSpec);
      if (!list.length) { setHint("書き出す対象のページがありません。"); return; }
      // 変換中はボタンを止め、総数が既知の i/N を進捗バーでも示す (フッター文字だけでは
      // 固まったように見える)。SVG 変換はページごとに `exportSvg` を呼んで進捗を刻む。
      if (btn) btn.disabled = true;
      if (prog) { prog.hidden = false; prog.max = list.length; prog.value = 0; }
      var entries = [];
      for (var i = 0; i < list.length; i++) {
        setHint("書き出し中 " + (i + 1) + "/" + list.length);
        var item = await rpc("exportSvg", list[i]);
        entries.push({ name: item.name, text: item.svg });
        if (prog) prog.value = i + 1;
      }
      if (entries.length === 1) {
        downloadBlob(entries[0].name, entries[0].text, "image/svg+xml");
        setHint('<b style="color:var(--good-ink)">1個のSVGを書き出しました。</b>');
        toast("1個のSVGを書き出しました");
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
      var suffix = chunks.length === 1 ? " ZIP で書き出しました。" : " ZIP " + chunks.length + " 本に分けて書き出しました。";
      setHint('<b style="color:var(--good-ink)">' + total + "個のSVGを" + suffix + "</b>");
      toast(total + "個のSVGを" + (chunks.length === 1 ? " ZIP 1 ファイルで" : " ZIP " + chunks.length + " ファイルに分けて") + "書き出しました");
    } catch (e) {
      // 失敗を握り潰すと「押しても何も起きない」になる。理由を出して再試行できる状態へ戻す。
      toast(String((e && e.message) || "書き出しに失敗しました"));
      setHint("書き出しに失敗しました。内容を確認して、もう一度お試しください。");
    } finally {
      if (btn) btn.disabled = false;
      if (prog) prog.hidden = true;
    }
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
    initRail({ render: render, tryNext: tryNext });
    wireStatic();
    render();
    startLifecycle();
  });
})();
