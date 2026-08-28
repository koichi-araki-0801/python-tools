// =============================================================================
// editor.js — エディタ本体 (セッション状態 + ライフサイクル + 描画統括)
// =============================================================================

import { CONFIG, WHITE, BLACK, DEFAULT_LEADER_STYLE, INSPECTOR_ACTIONS } from "./constants.js";
import { clampPointToBox } from "./geom.js";
import { parsePieGeometry, fallbackPieGeometry, labelBox, labelCenter, isOutsidePie, computeDefaultLeaderPts } from "./pie-rules.js";
import { safeGetBBox, stateEquals } from "./utils.js";
import { showToast } from "./icons.js";
// 描画 (オーバーレイ / インスペクタ / レール) は editor-render.js、ファイル I/O (読込 /
// 保存 bake / 開く) は editor-io.js が担う。名前空間 import で衝突回避。
import * as render from "./editor-render.js";
import * as io from "./editor-io.js";
import { bindEvents as bindEditorEvents } from "./editor-events.js";

// ── 1. エディタ本体 (セッション状態 + ライフサイクル + 描画オーケストレーション) ──

class Editor {
  constructor(dom) {
    this.dom = dom;

    // 現在の編集セッション状態
    this.name = null;        // 読込中のファイル名 (表示用。同定には使わない)
    this.currentId = null;   // 読込中アイテムの id (同名ファイルを取り違えないため)
    this.svg = null;         // インライン SVG ルート要素
    this.overlay = null;     // ハンドル等を入れる <g> (保存時に除去)
    this.labels = [];        // LabelState の配列
    this.selected = null;    // 選択中ラベル状態
    this.history = [];       // Undo 用スナップショット
    this.redoStack = [];     // Redo 用スナップショット (新規操作で破棄)
    this.phase = 1;          // ウィザード手順 (1=開く / 2=調整 / 3=保存)
    this.zoom = 1;
    this.baseW = 0;
    this.baseH = 0;
    this._pie = null;        // パイ中心・半径のキャッシュ {cx,cy,r}
    this._leaderStyle = null;// 新規 leader 用 stroke 属性のキャッシュ
    this._sliceByName = null;// data-name → スライス<path> の Map (遅延構築)
    this._sliceAnchor = null;// data-name → 中心角リム点 {x,y}|null のキャッシュ
    this.items = [];         // 読み込んだファイル群 (メモリ保持) … {id, name, content, edited?}
    this._itemSeq = 0;       // items に振る一意 id の採番 (同名でも区別する)
    this._loadSeq = 0;       // load() 再入の後勝ち判定 (fonts.ready 待ちのレース回避)

    // 描画スケジューラ (rAF + dirty フラグ)
    this._dirty = { dom: false, overlay: false, inspector: false };
    this._frame = 0;         // rAF ハンドル (0=未予約)
    // インスペクタの構造再構築判定
    this._inspSig = null;
    // オーバーレイのハンドル要素キャッシュ + 構造再構築判定
    this._handles = [];
    this._overlaySig = null;
  }

  // ── 2. 共通 ──

  setStatus(msg, kind = "") {
    if (this.dom.status) {
      this.dom.status.textContent = msg;
      this.dom.status.className = "skip-note" + (kind ? " " + kind : "");
    }
    // 完了/失敗はトーストでも通知
    if (kind === "ok" || kind === "err") showToast(msg);
  }

  // ── 3. ウィザード (手順の切替) ──

  /** 手順 `n` (1=開く / 2=調整 / 3=保存) へ切替え、ステップバー/画面/フッターを更新 */
  goPhase(n) {
    n = Math.max(1, Math.min(3, n));
    // ファイル未読込なら 2・3 へは進めない
    if (n >= 2 && !this.svg) { showToast("先に SVG を開いてください"); n = 1; }
    this.phase = n;
    const screens = { 1: this.dom.scOpen, 2: this.dom.scEdit, 3: this.dom.scSave };
    for (const [k, el] of Object.entries(screens)) { if (el) el.classList.toggle("on", +k === n); }
    // ステップバー
    if (this.dom.stepbar) {
      this.dom.stepbar.querySelectorAll(".step").forEach((st) => {
        const sn = +st.dataset.step;
        st.classList.toggle("active", sn === n);
        st.classList.toggle("done", sn < n);
      });
    }
    // フッターのボタン
    if (this.dom.btnBack) this.dom.btnBack.disabled = n === 1;
    if (this.dom.btnNext) {
      const last = n === 3;
      this.dom.btnNext.style.display = last ? "none" : "";
      this.dom.btnNext.disabled = n === 1 && !this.svg;
    }
    if (this.dom.navHint) this.dom.navHint.style.display = n === 2 ? "" : "none";
    this.updateChrome();
  }

  /** マウスイベント client 座標 → SVG ユーザー単位。
   *  `inv` (逆 CTM) を渡すと `getScreenCTM` 呼び出しを省ける (ドラッグ中の reflow 回避)。 */
  toSvgPoint(evt, inv) {
    const pt = this.svg.createSVGPoint();
    pt.x = evt.clientX;
    pt.y = evt.clientY;
    return pt.matrixTransform(inv || this.svg.getScreenCTM().inverse());
  }

  // ── 4. 円幾何 / leader スタイル (セッション状態に依存) ──

  /** 円(パイ)の中心・半径を slice パスから推定 (リーダー後付けの既定座標に使用) */
  getPieGeometry() {
    if (this._pie) return this._pie;
    const slicePath = this.svg && this.svg.querySelector("#slices .slice path, #slices path");
    const geom =
      (slicePath && parsePieGeometry(slicePath.getAttribute("d"))) ||
      fallbackPieGeometry(this.baseW, this.baseH, CONFIG.pieRadiusRatio);
    this._pie = geom;
    return geom;
  }

  /** `data-name` → スライス `<path>` の `Map` を一度だけ構築 (属性エスケープ回避のため走査) */
  _sliceMap() {
    if (this._sliceByName) return this._sliceByName;
    const map = new Map();
    const slices = this.svg ? this.svg.querySelectorAll("#slices g.slice") : [];
    slices.forEach((g) => {
      const name = g.getAttribute("data-name");
      const path = g.querySelector("path");
      if (name != null && path && !map.has(name)) map.set(name, path);
    });
    this._sliceByName = map;
    return map;
  }

  /** 指定ラベル名のスライスの「中心角リム点」を返す。leader 円側アンカーの固定先。
   *  楔形パス (M中心 L始点 A終点 Z) は両直線脚が半径 r で等長のため、円弧中点 =
   *  パス全長の中央 = 中心角リム点になる (`getPointAtLength(total/2)`)。
   *  スライス未発見/楔形でない (例: 100% 単一スライスは L 無し+2連 A) 場合は `null`。 */
  sliceMidAnchor(name) {
    if (!this._sliceAnchor) this._sliceAnchor = new Map();
    if (this._sliceAnchor.has(name)) return this._sliceAnchor.get(name);
    let anchor = null;
    const path = this._sliceMap().get(name);
    const d = path && (path.getAttribute("d") || "");
    // 楔形 (M…L…A…) のみ対象。それ以外は中心角が定義できないので退避。
    if (path && /M[^A-Za-z]*L[^A-Za-z]*A/.test(d)) {
      try {
        const total = path.getTotalLength();
        if (total > 0) {
          const p = path.getPointAtLength(total / 2);
          anchor = { x: p.x, y: p.y };
        }
      } catch { anchor = null; }
    }
    this._sliceAnchor.set(name, anchor);
    return anchor;
  }

  /** 既存 leader から stroke 系属性を借用 (無ければ既定値) */
  leaderStyleTemplate() {
    if (this._leaderStyle) return this._leaderStyle;
    const style = { ...DEFAULT_LEADER_STYLE };
    const existing = this.svg && this.svg.querySelector('#labels path[fill="none"]');
    if (existing) {
      for (const k of Object.keys(style)) {
        const v = existing.getAttribute(k);
        if (v != null) style[k] = v;
      }
    }
    this._leaderStyle = style;
    return style;
  }

  /** リーダー後付け時の既定 2 点 [リム上アンカー, ラベル端点] を算出。
   *  `bbox` 省略時は `getBBox`。ドラッグ中は開始時 `bbox` を渡し reflow を避ける。
   *  算出本体は `pie-rules.js` の `computeDefaultLeaderPts` (純粋関数)。 */
  defaultLeaderPts(s, bbox) {
    const pie = this.getPieGeometry();
    if (!bbox) bbox = safeGetBBox(s.text, { x: pie.cx, y: pie.cy, width: 0, height: 0 });
    return computeDefaultLeaderPts(pie, labelBox(bbox, s.textTx), this.sliceMidAnchor(s.name), CONFIG.vecEpsilon);
  }

  /** leader 末尾(端点)を必ずラベル外枠上へ置く。アンカー/曲げ点は保持。
   *  手前の点をラベル矩形へクランプ = 外枠上の最近点。`bbox` は素の `getBBox` 値。 */
  snapEndpointToFrame(s, bbox) {
    const n = s.leaderPts.length;
    if (n < 2) return;
    s.leaderPts[n - 1] = clampPointToBox(s.leaderPts[n - 2], labelBox(bbox, s.textTx));
  }

  /** ラベル移動後の leader 追従。既存 leader を持ち円外なら端点を外枠上へ
   *  再スナップ(アンカー/曲げ点は保持)、それ以外は位置駆動ルール。
   *  `basePts` 指定時はそれを基準に復元 (ドラッグ中の連続適用用)。 */
  followLeaderAfterMove(s, bbox, basePts) {
    const pts = basePts || s.leaderPts;
    if (pts.length >= 2 && this.isOutsideRim(s, bbox)) {
      s.leaderPts = pts.map((q) => ({ ...q })); // アンカー/曲げ点を保持
      this.snapEndpointToFrame(s, bbox);
      if (s.whiteType) s.fill = BLACK;
    } else {
      this.applyRimLeaderRule(s, bbox);
    }
  }

  /** ラベル(`text` bbox)の中心点 (`textTx` 反映)。`bbox` 省略時は `getBBox`。 */
  labelCenterPoint(s, bbox) {
    let b = bbox;
    if (!b) {
      b = safeGetBBox(s.text, null);
      if (!b) return null;
    }
    return labelCenter(b, s.textTx);
  }

  /** ラベル中心が円周の外にあるか。`bbox` 省略時は `getBBox`。 */
  isOutsideRim(s, bbox) {
    const c = this.labelCenterPoint(s, bbox);
    if (!c) return false;
    return isOutsidePie(c, this.getPieGeometry());
  }

  // leader 状態モデル:
  //   `_auto=true`  … 位置駆動で生成された leader。円外で生成/端点追従し、円内で除去する。
  //   `_auto=false` … ユーザー管理の leader (ファイル由来 / 手動追加 / 頂点や曲げ点を手動編集)。
  //                   位置ルールは削除も可視性の強制もしない (ユーザーの意思を保持)。
  /** 位置駆動の leader ルール: 円外なら自動 leader を確保・円内なら自動分のみ除去。
   *  白文字タイプは円外で黒・円内で白に切替 (視認性)。`bbox` 省略時は `getBBox`。 */
  applyRimLeaderRule(s, bbox) {
    if (this.isOutsideRim(s, bbox)) {
      if (s.leaderPts.length === 0 || s._auto) {
        // 自動 leader を (再)生成。生成分だけ可視を強制する。
        s.leaderPts = this.defaultLeaderPts(s, bbox);
        s._auto = true;
        s.leaderVisible = true;
      }
      // 手動 leader (_auto=false) は pts も可視性も触れない。
      if (s.whiteType) s.fill = BLACK;
    } else {
      if (s._auto) {
        // 自動生成分のみ除去。手動 leader は保持する。
        s.leaderPts = [];
        s.leaderVisible = false;
        s._auto = false;
      }
      if (s.whiteType) s.fill = WHITE;
    }
  }

  // ── 5. 描画スケジューラ ──

  /** 描画要求を dirty フラグへ立て、1 フレーム最大 1 回の flush を予約する */
  markDirty(flags) {
    Object.assign(this._dirty, flags);
    if (!this._frame) this._frame = requestAnimationFrame(() => this._flush());
  }

  _flush() {
    this._frame = 0;
    const d = this._dirty;
    this._dirty = { dom: false, overlay: false, inspector: false };
    if (d.dom && this.selected) this.selected.renderToDom();
    if (d.overlay) render.syncOverlay(this);
    if (d.inspector) render.renderInspector(this);
  }

  /** 保留中の描画を同期的に確定させる (保存前の DOM 読出しや、即時反映が要る操作で使用) */
  flushNow() {
    if (this._frame) { cancelAnimationFrame(this._frame); this._frame = 0; }
    this._flush();
  }

  /** 全ラベルの状態を実 DOM へ反映 (Undo/読込時の一括同期) */
  renderAllToDom() {
    for (const s of this.labels) s.renderToDom();
  }

  // ── 6. Undo 履歴 (全ラベルのスナップショット) ──

  pushHistory() {
    this.history.push(this.labels.map((s) => s.snapshot()));
    if (this.history.length > CONFIG.historyLimit) this.history.shift();
    // 新規操作は redo の分岐履歴を破棄 (一般的な Undo/Redo の挙動)
    this.redoStack = [];
    this.updateToolbar();
  }

  undo() {
    if (!this.history.length) return;
    // 復元前の現在状態を redo へ退避
    this.redoStack.push(this.labels.map((s) => s.snapshot()));
    const snap = this.history.pop();
    this.labels.forEach((s, i) => s.apply(snap[i]));
    this.renderAllToDom();
    this.markDirty({ overlay: true, inspector: true });
    this.flushNow();
    this.updateToolbar();
  }

  redo() {
    if (!this.redoStack.length) return;
    // 復元前の現在状態を undo へ積み戻す (undo と対称)
    this.history.push(this.labels.map((s) => s.snapshot()));
    if (this.history.length > CONFIG.historyLimit) this.history.shift();
    const snap = this.redoStack.pop();
    this.labels.forEach((s, i) => s.apply(snap[i]));
    this.renderAllToDom();
    this.markDirty({ overlay: true, inspector: true });
    this.flushNow();
    this.updateToolbar();
  }

  updateToolbar() {
    this.dom.btnUndo.disabled = this.history.length === 0;
    if (this.dom.btnRedo) this.dom.btnRedo.disabled = this.redoStack.length === 0;
    this.dom.btnReset.disabled = !this.svg;
    this.dom.btnSave.disabled = !this.svg;
  }

  // ── 7. オーバーレイ (ハンドル) 描画 — editor-render.js の `syncOverlay` が担う ──

  // ── 8. ドラッグ操作 ──

  /** ドラッグの定型処理: `pointermove`/`up` を配線し、初回の実移動時に一度だけ
   *  `pushHistory` する。`onMove(dx, dy)` には開始点からの累積移動量を渡す。 */
  onDrag(evt, onMove) {
    // 逆 CTM はドラッグ中ほぼ不変 (ズーム/スクロールしない) なので開始時に 1 回だけ取得
    const inv = this.svg.getScreenCTM().inverse();
    const start = this.toSvgPoint(evt, inv);
    let pushed = false;
    const move = (e) => {
      const p = this.toSvgPoint(e, inv);
      const dx = p.x - start.x;
      const dy = p.y - start.y;
      if (!pushed && (dx || dy)) { this.pushHistory(); pushed = true; }
      onMove(dx, dy);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", up);
  }

  startTextDrag(evt, s) {
    evt.preventDefault();
    evt.stopPropagation();
    this.selectLabel(s);
    const txStart = { ...s.textTx };
    // ドラッグ開始時の leader 状態 (円外で元から leader を持つ場合の追従/復元に使用)
    const startPts = s.leaderPts.map((p) => ({ ...p }));
    // bbox は transform 非依存 (= ドラッグ中不変) なので開始時に 1 回だけ取得し reflow を避ける
    const bbox = safeGetBBox(s.text, null);

    this.onDrag(evt, (dx, dy) => {
      s.textTx = { x: txStart.x + dx, y: txStart.y + dy };
      // `startPts` 基準でアンカー/曲げ点を保持しつつ端点を毎フレーム外枠へ再スナップ
      this.followLeaderAfterMove(s, bbox, startPts);
      this.markDirty({ dom: true, overlay: true, inspector: true });
    });
  }

  startLeaderDrag(evt, s, index) {
    evt.preventDefault();
    evt.stopPropagation();
    this.selectLabel(s);
    const ptStart = { ...s.leaderPts[index] };

    this.onDrag(evt, (dx, dy) => {
      // 手動で頂点を動かしたら以後は位置駆動で上書きしない。実際に動いてから印を付けるのは、
      // `onDrag` が初回移動で `pushHistory` するため (pointerdown だけで確定すると、触れた
      // だけの自動 leader が無履歴で手動へ落ち、Undo でも戻せず位置ルールから外れる)。
      s._auto = false;
      s.leaderPts[index] = { x: ptStart.x + dx, y: ptStart.y + dy };
      this.markDirty({ dom: true, overlay: true });
    });
  }

  // ── 9. 選択 & インスペクタ ──

  selectLabel(s) {
    if (this.selected === s) return;
    // 予約 `data-editor-sel`(class ではなく)を使う: `class` は出口 `sanitizeSvg` が
    // 値無検査で通す許可属性なので、素のクラス名だと列挙漏れが検知網の外へ出る。
    if (this.selected) this.selected.g.removeAttribute("data-editor-sel");
    this.selected = s;
    if (s) s.g.setAttribute("data-editor-sel", "1");
    this.markDirty({ overlay: true, inspector: true });
    this.flushNow();
  }

  /** スライス(扇形)の塗り色を `data-name` から引く。見つからなければ既定。
   *  戻り値は**未検証の文字列**で、入力 SVG の `fill` 属性そのまま。画面へ出す側が
   *  `safeCssColor` で文法検証する (検証済み専用にすると他用途で使いにくいため、
   *  検証は使う側に置く)。`path.style.fill` の分岐は、インライン `style` 属性を
   *  サニタイザが通さないので実質エディタ内部由来の値しか拾わない。 */
  sliceColor(name) {
    const path = this._sliceMap().get(name);
    const c = path && (path.getAttribute("fill") || (path.style && path.style.fill));
    return c && c !== "none" ? c : "var(--sunk)";
  }

  // インスペクタ本体の描画/配線は editor-render.js の `renderInspector` が担う。

  inspectorAction(act) {
    const s = this.selected;
    const a = INSPECTOR_ACTIONS[act];
    if (!s || !a || !a.guard(s)) return;
    this.pushHistory();
    a.run(this, s);
    this.markDirty({ dom: true, overlay: true, inspector: true });
    if (a.resnapLeader) this.resnapLeaderToFrame(s);
  }

  /** ラベルの外枠が変わった後に leader 末尾端点を外枠上へ引き戻す。
   *  端点が外枠上にある不変条件は行数・長体の変更でも保たれなければならない (放っておくと
   *  枠の内側へ浮く / 縮んだ枠から取り残される)。`flushNow` を先に呼ぶのは、`tspan` の
   *  組み直しが保留のままだと旧寸法を測ってしまうため。 */
  resnapLeaderToFrame(s) {
    if (!s || s.leaderPts.length < 2) return;
    this.flushNow();
    const bbox = safeGetBBox(s.text, null);
    if (!bbox) return;
    this.snapEndpointToFrame(s, bbox);
    this.markDirty({ dom: true, overlay: true });
  }

  /** 名前の長体率 (横圧縮) を確定し、変わった外枠へ leader 端点を引き戻す。
   *  スライダのドラッグ中 (`input`) はライブ反映だけにして、確定 (`change`) でここを通す。 */
  setNameScaleX(s, v) {
    if (!s) return;
    s.nameScaleX = v;
    this.markDirty({ dom: true });
    this.resnapLeaderToFrame(s);
  }

  /** 選択ラベルを微少移動する。`coalesceHistory` が真なら履歴を積まず直前の 1 手へまとめる
   *  (矢印キーの押しっぱなし用。リピート 1 発ごとに積むと `historyLimit` を数秒で使い切り、
   *  それ以前の操作が戻せなくなる)。 */
  nudge(dx, dy, coalesceHistory = false) {
    const s = this.selected;
    if (!s) return;
    if (!coalesceHistory) this.pushHistory();
    s.textTx = { x: s.textTx.x + dx, y: s.textTx.y + dy };
    // 端点を外枠へ再スナップ。円周を跨いだ場合の自動生成/削除も内包。
    this.followLeaderAfterMove(s, safeGetBBox(s.text, null));
    this.markDirty({ dom: true, overlay: true, inspector: true });
  }

  // ── 10. SVG 読込 & セットアップ — editor-io.js へ委譲 ──

  async load(item) { return io.load(this, item); }
  /** レール / ファイルカードからの切替 (未保存の調整があれば確認する)。実装は
   *  `editor-io.js` の `switchTo`。戻り値は実際に読み込んだか。 */
  async switchTo(item) { return io.switchTo(this, item); }

  // ── 11. ズーム ──

  applyZoom() {
    if (!this.svg) return;
    this.svg.setAttribute("width", this.baseW * this.zoom);
    this.svg.setAttribute("height", this.baseH * this.zoom);
  }

  setZoom(z) {
    const prev = this.zoom;
    z = Math.max(CONFIG.zoomMin, Math.min(CONFIG.zoomMax, z));
    if (z === prev) return;
    // 表示中心を保ったまま拡縮 (左上基準だと中心がずれて見づらいため)
    const pane = this.dom.canvas.parentElement; // `#canvasPane` (スクロール容器)
    const r = z / prev;
    const cx = pane.scrollLeft + pane.clientWidth / 2;
    const cy = pane.scrollTop + pane.clientHeight / 2;
    this.zoom = z;
    this.applyZoom();
    pane.scrollLeft = cx * r - pane.clientWidth / 2;
    pane.scrollTop = cy * r - pane.clientHeight / 2;
    // ハンドルの見かけサイズをズームに追従 (構造不変なので座標/サイズ更新で済む)
    this.markDirty({ overlay: true });
    this.flushNow();
  }

  // ── 12. 保存 (bake → ダウンロード) — editor-io.js へ委譲 ──

  async save() { return io.save(this); }
  // E2E 検証用フック (`window.__editor` 経由で bake 結果を検査する)。本番の保存経路は
  // `io.save` がモジュール内の bakeSvg を直接呼ぶため、このラッパを通らない。
  bakeSvg() { return io.bakeSvg(this); }

  // ── 13. ファイル選択 / ドロップ (開く) — editor-io.js へ委譲 ──

  async openFiles() { return io.openFiles(this); }
  async handleDrop(dt) { return io.handleDrop(this, dt); }

  /** ラベルが初期状態から変更されているか (編集済みドット用)。
   *  レール更新 (`syncRail`) 経由でドラッグ中の**毎フレーム・全ラベル分**呼ばれる経路なので、
   *  スナップショットの複製も `JSON.stringify` も挟まず `STATE_FIELDS` の等値判定だけで比べる
   *  (直列化で比べると 1 フレームにつきラベル数 × 2 回の直列化になる)。 */
  isLabelEdited(s) {
    if (!s) return false;
    return !stateEquals(s, s.initial);
  }

  // レール / 開いたファイル一覧 / クロームの描画は editor-render.js が担う。
  // 呼び出し元 (load / save / openFiles / goPhase) 向けの薄い委譲のみ置く。
  updateChrome() { render.updateChrome(this); }
  renderList() { render.buildRail(this); render.renderOpenList(this); render.updateChrome(this); }
  highlightActiveInList() { render.buildRail(this); render.updateChrome(this); }

  // ── 14. イベント配線 — editor-events.js へ委譲 ──

  bindEvents() { bindEditorEvents(this); }
}

export { Editor };
