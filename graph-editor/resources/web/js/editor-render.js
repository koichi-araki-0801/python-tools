// =============================================================================
// editor-render.js — オーバーレイ / インスペクタ / レールの描画
// =============================================================================
// `editor.js` の `Editor` インスタンス (`ed`) を第 1 引数に取る描画関数群。状態は
// 一切持たず、`ed` のセッション状態 (selected / labels / zoom / dom / 各キャッシュ) を
// 読み書きする。描画の入口は `editor.js` の描画スケジューラ (`markDirty` → `_flush`) で、
// 「構造シグネチャが変わった時だけ再構築・通常フレームは座標/文言のみ更新」の方針は
// 本モジュール内の `signature → build/position` 対で実現する。

import { CONFIG, WHITE, EMPTY_LIST_HTML, INSPECTOR_EMPTY_HTML, LEGEND_HTML } from "./constants.js";
import { escapeHtml, createSvgEl } from "./utils.js";
import { safeCssColor } from "./svg-policy.js";
import { drawIcons } from "./icons.js";

// ── 1. オーバーレイ (ハンドル) — 構造変化時のみ再構築、通常は座標更新 ──

/** ズームに依らず一定の見かけサイズになるよう SVG 単位を補正したハンドル半径 */
function handleSize(ed) {
  return CONFIG.handleScreenRadius / ed.zoom;
}

/** ハンドル構成 (選択ラベル・表示状態・頂点数) を表すシグネチャ */
function overlaySignature(ed) {
  const s = ed.selected;
  if (!s || !ed.overlay || !s.leaderVisible || !s.leaderPts.length) return "none";
  return `${ed.labels.indexOf(s)}|${s.leaderPts.length}`;
}

function syncOverlay(ed) {
  const sig = overlaySignature(ed);
  if (sig !== ed._overlaySig) {
    buildOverlay(ed);
    ed._overlaySig = sig;
  } else {
    positionHandles(ed);
  }
}

/** ハンドル円を作り直す (頂点数・選択が変わった時だけ呼ばれる) */
function buildOverlay(ed) {
  if (ed.overlay) ed.overlay.replaceChildren();
  ed._handles = [];
  const s = ed.selected;
  if (!s || !ed.overlay) return;
  if (!(s.leaderVisible && s.leaderPts.length)) return;
  const r = handleSize(ed);
  const last = s.leaderPts.length - 1;
  s.leaderPts.forEach((p, i) => {
    // 先頭=アンカー: 橙, 末尾=端点: 緑, 中間: 青
    const color = i === 0 ? "#ffb84c" : i === last ? "#57c878" : "#4c9aff";
    const c = handleCircle(ed, p.x, p.y, r, color);
    // 円側アンカー (i===0) はスライス中心角に固定 → ドラッグ不可。端点/曲げ点のみ可動。
    if (i === 0) {
      c.style.cursor = "not-allowed";
    } else {
      c.style.cursor = "move";
      c.addEventListener("pointerdown", (e) => ed.startLeaderDrag(e, s, i));
    }
    ed.overlay.appendChild(c);
    ed._handles.push(c);
  });
}

/** 既存ハンドル円の cx/cy (+ズーム時の r/stroke) だけを更新 */
function positionHandles(ed) {
  const s = ed.selected;
  if (!s || !ed._handles.length) return;
  const r = handleSize(ed);
  const sw = 1 / ed.zoom;
  s.leaderPts.forEach((p, i) => {
    const c = ed._handles[i];
    if (!c) return;
    c.setAttribute("cx", p.x);
    c.setAttribute("cy", p.y);
    c.setAttribute("r", r);
    c.setAttribute("stroke-width", sw);
  });
}

function handleCircle(ed, x, y, r, color) {
  return createSvgEl("circle", {
    cx: x, cy: y, r, fill: color,
    stroke: "#1e1f22", "stroke-width": 1 / ed.zoom, "data-editor": "1",
  });
}

// ── 2. インスペクタ (右パネル) — 構造変化時のみ再構築、毎回 座標表示のみ更新 ──

/** 選択中ラベルの右パネル本体 HTML (モック「案A」準拠のセグメント UI)。
 *  **補間を 1 箇所も含まない静的スケルトン**であること。値は `fillInspector` が
 *  `textContent` / `setAttribute` / `style` プロパティ代入で流し込む。
 *  ここへ `${...}` を戻すと「1 箇所だけエスケープを忘れる」形が復活する
 *  (スライス色だけが素通しで、選択しただけで任意 JS が走った事例)。
 *  クラス名・要素構造・並びは docs のスクリーンショット (`panel_right.png`) の
 *  基準でもあるので、見た目に出る変更は再撮影とセットで行うこと。 */
const INSPECTOR_BODY_HTML = `
<div class="selname"><span class="sw"></span><span class="nm"></span></div>

<div class="ctl">
  <div class="clab"><i data-ic="leader"></i>引出線</div>
  <div class="segment" data-ctl="leader">
    <button data-act="leaderAdd" aria-pressed="false">表示</button>
    <button data-act="leaderOff" aria-pressed="false">非表示</button>
  </div>
</div>

<div class="ctl" data-dep="leader">
  <div class="clab"><i data-ic="bend"></i>曲げ点</div>
  <div class="segment" data-ctl="bent">
    <button data-act="bendAdd" aria-pressed="false">あり</button>
    <button data-act="bendRemove" aria-pressed="false">なし</button>
  </div>
</div>

<div class="ctl">
  <div class="clab"><i data-ic="droplet"></i>文字色</div>
  <div class="segment" data-ctl="color">
    <button data-act="insideOff" aria-pressed="false"><span class="swdot" style="background:#111"></span>黒</button>
    <button data-act="insideOn" aria-pressed="false"><span class="swdot" style="background:#fff;box-shadow:0 0 0 1px var(--border-strong)"></span>白</button>
  </div>
</div>

<div class="ctl">
  <div class="clab"><i data-ic="rows"></i>行数</div>
  <div class="segment" data-ctl="lines">
    <button data-act="lines1" aria-pressed="false">1行</button>
    <button data-act="lines2" aria-pressed="false">2行</button>
  </div>
</div>

<div class="ctl">
  <div class="clab"><i data-ic="width"></i>長体 <span class="tech">（横圧縮）</span></div>
  <div class="rng">
    <input type="range" id="scaleRange" min="0" max="1" step="0.01" value="1">
    <span class="v" id="scaleVal"></span>
  </div>
</div>

${LEGEND_HTML}

<div class="panel-reset">
  <button class="btn outline" data-act="resetOne" style="width:100%;justify-content:center"><i data-ic="reset"></i>このラベルをリセット</button>
</div>`;

/** 選択ラベル `s` の値を静的スケルトン `box` へ流し込む (文字列連結を経由しない)。
 *  スライス色は入力 SVG 由来なので `safeCssColor` で文法検証したうえで
 *  `style.backgroundColor` へ**プロパティ代入**する。`setAttribute("style", ...)` は
 *  不可 — markup 脱出は防げても `red;background-image:url(https://…)` で宣言を継ぎ足され
 *  外部フェッチが立つ (CSSOM のプロパティ代入なら不正値が黙って無視される)。 */
function fillInspector(ed, box, s) {
  const hasLeader = s.leaderPts.length >= 2;
  const hasBend = s.leaderPts.length >= 3;

  const sw = box.querySelector(".selname .sw");
  if (sw) sw.style.backgroundColor = safeCssColor(ed.sliceColor(s.name)) ?? "var(--sunk)";
  const nm = box.querySelector(".selname .nm");
  if (nm) nm.textContent = s.percentText ? `${s.name} ${s.percentText}` : s.name;

  // 引出線の「表示」は leader が無ければ追加(`leaderAdd`)、有れば表示(`leaderOn`)。
  const pressed = {
    leaderAdd: [hasLeader ? "leaderOn" : "leaderAdd", s.leaderVisible],
    leaderOff: ["leaderOff", !s.leaderVisible],
    bendAdd: ["bendAdd", hasBend],
    bendRemove: ["bendRemove", !hasBend],
    insideOff: ["insideOff", s.fill !== WHITE],
    insideOn: ["insideOn", s.fill === WHITE],
    lines1: ["lines1", s.lineCount < 2],
    lines2: ["lines2", s.lineCount >= 2],
  };
  for (const [key, [act, on]] of Object.entries(pressed)) {
    const btn = box.querySelector(`button[data-act="${key}"]`);
    if (!btn) continue;
    btn.setAttribute("data-act", act);
    btn.setAttribute("aria-pressed", String(on));
  }

  const dep = box.querySelector('.ctl[data-dep="leader"]');
  if (dep) dep.classList.toggle("off", !hasLeader);

  const range = box.querySelector("#scaleRange");
  if (range) {
    range.min = String(CONFIG.condenseMin);
    range.step = String(CONFIG.condenseStep);
    range.value = String(s.nameScaleX);
  }
  const valEl = box.querySelector("#scaleVal");
  if (valEl) valEl.textContent = `${Math.round(s.nameScaleX * 100)}%`;
}

/** インスペクタの構造を表すシグネチャ (座標 `dx`/`dy` は含めない = 構造再構築の対象外) */
function inspectorSignature(ed) {
  const s = ed.selected;
  if (!s) return "none";
  return [ed.labels.indexOf(s), s.leaderPts.length, s.leaderVisible, s.fill === WHITE, s.lineCount, s.nameScaleX].join("|");
}

/** 構造シグネチャが変わった時だけパネルを作り直す */
function renderInspector(ed) {
  const sig = inspectorSignature(ed);
  if (sig !== ed._inspSig) {
    ed._inspSig = sig;
    buildInspector(ed);
  }
  syncRail(ed);
}

function buildInspector(ed) {
  const s = ed.selected;
  if (!s) {
    ed.dom.inspectorBody.innerHTML = INSPECTOR_EMPTY_HTML;
    drawIcons(ed.dom.inspectorBody);
    return;
  }
  const box = document.createElement("div");
  // 定数スケルトンなので `innerHTML` で良い。動的な値は `fillInspector` が DOM API で入れる。
  box.innerHTML = INSPECTOR_BODY_HTML;
  fillInspector(ed, box, s);
  box.querySelectorAll("button[data-act]").forEach((btn) => {
    btn.addEventListener("click", () => ed.inspectorAction(btn.getAttribute("data-act")));
  });
  // 長体スライダ: ドラッグ中はライブ反映し、操作開始時に 1 度だけ履歴へ積む。
  // インスペクタは再構築しない (`markDirty` の inspector を立てない) のでドラッグが途切れない。
  const range = box.querySelector("#scaleRange");
  if (range) {
    const valEl = box.querySelector("#scaleVal");
    let pushed = false;
    const begin = () => { pushed = false; };
    range.addEventListener("pointerdown", begin);
    range.addEventListener("keydown", begin);
    range.addEventListener("input", () => {
      if (!ed.selected) return;
      if (!pushed) { ed.pushHistory(); pushed = true; }
      const v = parseFloat(range.value);
      ed.selected.nameScaleX = v;
      if (valEl) valEl.textContent = `${Math.round(v * 100)}%`;
      ed.markDirty({ dom: true });
    });
    // 確定 (`change`) で外枠の変化を leader 端点へ反映する。ドラッグ中の毎 `input` で
    // 測ると 1 操作あたり数十回の強制同期レイアウトになるので、終わりに 1 度だけ。
    range.addEventListener("change", () => {
      if (ed.selected) ed.setNameScaleX(ed.selected, parseFloat(range.value));
    });
  }
  ed.dom.inspectorBody.replaceChildren(box);
  drawIcons(ed.dom.inspectorBody);
}

// ── 3. レール (左) / トップバー等のクローム ──

/** 左レール: ファイル一覧 + 選択中ファイルのラベル一覧 */
function buildRail(ed) {
  const list = ed.dom.list;
  if (!list) return;
  list.replaceChildren();
  if (!ed.items.length) {
    list.innerHTML = EMPTY_LIST_HTML;
    drawIcons(list);
    return;
  }
  for (const it of ed.items) {
    const isCur = it.id === ed.currentId;
    const item = document.createElement("div");
    item.className = "fileitem" + (isCur ? " cur" : "");
    item.dataset.id = it.id;
    let status = "";
    if (it.edited) status = '<span class="rok"><i data-ic="check"></i></span>';
    else if (isCur) status = '<span class="rdot" title="編集中"></span>';
    item.innerHTML = `<span class="rp"></span><span class="rn">${escapeHtml(it.name.replace(/\.svg$/i, ""))}</span>${status}`;
    item.addEventListener("click", (e) => {
      if (e.target.closest(".lblrow")) return;
      if (it.id !== ed.currentId) ed.switchTo(it);
    });
    list.appendChild(item);
    // 選択中ファイルの直下にラベル一覧 (`.lblsub`)
    if (isCur && ed.labels.length) {
      const sub = document.createElement("div");
      sub.className = "lblsub";
      sub.innerHTML = ed.labels.map((s, i) =>
        `<div class="lblrow${s === ed.selected ? " on" : ""}" data-idx="${i}">` +
        `<span class="ld${ed.isLabelEdited(s) ? " ed" : ""}"></span>` +
        `<span class="nm">${escapeHtml(s.name)}</span>` +
        (s.percentText ? `<span class="pc">${escapeHtml(s.percentText)}</span>` : "") +
        `</div>`
      ).join("");
      list.appendChild(sub);
      sub.querySelectorAll(".lblrow").forEach((r) =>
        r.addEventListener("click", () => ed.selectLabel(ed.labels[+r.dataset.idx]))
      );
    }
  }
  drawIcons(list);
}

/** 手順1 の「開いたファイル」一覧 */
function renderOpenList(ed) {
  const el = ed.dom.openList;
  if (!el) return;
  if (ed.dom.openCount) ed.dom.openCount.textContent = ed.items.length ? `${ed.items.length} 件` : "";
  el.replaceChildren();
  for (const it of ed.items) {
    const card = document.createElement("div");
    card.className = "file-card clickable";
    card.innerHTML =
      `<div class="fic"><i data-ic="file"></i></div>` +
      `<div class="fmeta"><div class="fname">${escapeHtml(it.name)}</div><div class="fsub">${it.edited ? "保存済み" : "未保存"}</div></div>` +
      (it.edited ? '<span class="rok"><i data-ic="check"></i></span>' : "");
    card.addEventListener("click", async () => { if (await ed.switchTo(it)) ed.goPhase(2); });
    el.appendChild(card);
  }
  drawIcons(el);
}

/** トップバー / ページナビ / ズーム% / 保存画面 の文言を最新化 */
function updateChrome(ed) {
  if (ed.dom.fileChip) ed.dom.fileChip.textContent = ed.name || "ファイル未選択";
  if (ed.dom.pgInfo) {
    if (!ed.svg) ed.dom.pgInfo.textContent = "ファイル未選択";
    else if (ed.selected) ed.dom.pgInfo.innerHTML = `選択中：<b>${escapeHtml(ed.selected.name)}</b>（ラベル ${ed.labels.length} 個）`;
    else ed.dom.pgInfo.innerHTML = `ラベル <b>${ed.labels.length}</b> 個（クリックで選択）`;
  }
  if (ed.dom.zoomLvl) ed.dom.zoomLvl.textContent = `${Math.round(ed.zoom * 100)}%`;
  if (ed.dom.saveName) ed.dom.saveName.textContent = ed.name || "ファイル未選択";
  if (ed.dom.saveSub) ed.dom.saveSub.textContent = ed.svg ? `ラベル ${ed.labels.length} 個` : "—";
}

/** レールのラベル行の選択/編集済み表示だけを軽量更新 (毎フレーム可) */
function syncRail(ed) {
  const list = ed.dom.list;
  if (!list) return;
  list.querySelectorAll(".lblrow").forEach((r) => {
    const s = ed.labels[+r.dataset.idx];
    r.classList.toggle("on", s === ed.selected);
    const ld = r.querySelector(".ld");
    if (ld) ld.classList.toggle("ed", ed.isLabelEdited(s));
  });
  updateChrome(ed);
}

export { syncOverlay, renderInspector, buildRail, renderOpenList, updateChrome };
