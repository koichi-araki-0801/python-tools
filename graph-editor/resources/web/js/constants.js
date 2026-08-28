// =============================================================================
// constants.js — 調整用定数・既定スタイル・UI 文言・操作表の一元管理
// =============================================================================

const SVG_NS = "http://www.w3.org/2000/svg";

// 純粋関数 (`parsePath` 等) は `geom.js` が持ち、各モジュールが import する。

// 文字色の正規値 (生成側: 通常=`#111111` / inside=`#ffffff`)。比較・既定値に使う。
const WHITE = "#ffffff";
const BLACK = "#111111";

// 調整用の定数 (見かけサイズ・閾値・既定値を一元管理)
const CONFIG = {
  handleScreenRadius: 5,   // ハンドルの見かけ半径 (ズームで割って一定化)
  pieRadiusRatio: 0.35,    // slice から半径を推定できない時のフォールバック係数
  historyLimit: 100,       // Undo 履歴の保持上限
  // 1 ファイルで扱うラベル数の上限。超過は読み込みごと拒否する (`editor-io.js` の `load`)。
  // ヒット領域の生成・オーバーレイ・レール描画・履歴スナップショットがどれもラベル数に
  // 比例するため、上限が無いと細工 SVG 1 枚で操作不能になる。pie-chart の実出力は数十個
  // 規模なので、2 桁の余裕を見てもここで切れる。
  maxLabels: 500,
  hitPadding: 3,           // ヒット矩形の bbox からの余白
  zoomMin: 0.4,
  zoomMax: 3,
  zoomStep: 1.2,           // ＋/− ボタン 1 回あたりの倍率
  nudgeStep: 1,            // 矢印キーの移動量 (px)
  nudgeStepFast: 10,       // Shift+矢印の移動量 (px)
  vecEpsilon: 1e-6,        // ベクトル長がこの値未満なら方向を既定化
  roundPrecision: 1e6,     // 座標焼き込み時の丸め精度
  defaultViewBox: { w: 600, h: 450 }, // viewBox 取得失敗時の既定サイズ
  condenseMin: 0.7,        // 長体 (横圧縮) の下限率
  condenseStep: 0.01,      // 長体スライダの刻み
  defaultLineSpacing: 1.1, // 行間 (em)。SVG から検出できない時の既定
};

// 新規 leader の既定 `stroke` 系属性 (既存 leader が無い場合に使用)
const DEFAULT_LEADER_STYLE = {
  stroke: "#6a6a6a", "stroke-width": "1.008",
  "stroke-linecap": "round", "stroke-linejoin": "round",
};

// UI 文言 (HTML マークアップと重複する箇所は同一文字列を保つこと)
const EMPTY_LIST_HTML = '<div class="empty-note" style="height:auto;padding:18px 8px"><div class="et" style="font-weight:500">まだファイルがありません</div></div>';
const STATUS_READY = "「ファイルを選択…」で SVG を開いてください";

// インスペクタ未選択時の表示（右パネル）
const INSPECTOR_EMPTY_HTML = '<div class="empty-note"><div class="ei"><i data-ic="cursor"></i></div><div class="et">ラベルをクリックして選択</div></div>';

// 凡例（引出線ハンドルの色: 端点=緑 / 曲点=青 / アンカー=橙）
const LEGEND_HTML = `
<div class="leg">
  <div class="lh">引出線のハンドル</div>
  <div class="lr"><i class="g"></i>端点<small>文字側・可動</small></div>
  <div class="lr"><i class="b"></i>曲点<small>折れ目・可動</small></div>
  <div class="lr"><i class="o"></i>アンカー<small>起点・固定</small></div>
</div>`;

// インスペクタのボタン操作表。`{ guard(s):状態が操作可能か, run(editor, s):状態変更 }`。
// 共通の `pushHistory` / `markDirty` は `editor.js` の `inspectorAction` 側で 1 度だけ行う。
// `_auto=false` は「明示操作したら以後のドラッグで位置駆動の自動上書きをしない」印。
const INSPECTOR_ACTIONS = {
  leaderOn:     { guard: (s) => s.leaderPts.length && !s.leaderVisible,
                  run: (e, s) => { s.leaderVisible = true; s._auto = false; } },
  leaderOff:    { guard: (s) => s.leaderVisible,
                  run: (e, s) => { s.leaderVisible = false; s._auto = false; } },
  leaderAdd:    { guard: (s) => s.leaderPts.length === 0,
                  run: (e, s) => { s.leaderPts = e.defaultLeaderPts(s); s.leaderVisible = true; s._auto = false; } },
  bendAdd:      { guard: (s) => s.leaderPts.length === 2,
                  run: (e, s) => {
                    const [a, b] = s.leaderPts;
                    s.leaderPts = [a, { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, b];
                    s._auto = false;
                  } },
  bendRemove:   { guard: (s) => s.leaderPts.length >= 3,
                  run: (e, s) => { s.leaderPts = [s.leaderPts[0], s.leaderPts[s.leaderPts.length - 1]]; s._auto = false; } },
  // `resnapLeader`: 実行後にラベルの外枠が変わる操作の印。`inspectorAction` が `flushNow`
  // で寸法を確定させてから leader 末尾端点を外枠上へ引き戻す。
  lines1:       { guard: (s) => s.lineCount !== 1, run: (e, s) => { s.lineCount = 1; }, resnapLeader: true },
  lines2:       { guard: (s) => s.lineCount !== 2, run: (e, s) => { s.lineCount = 2; }, resnapLeader: true },
  insideOn:     { guard: (s) => s.fill !== WHITE, run: (e, s) => { s.fill = WHITE; } },
  insideOff:    { guard: (s) => s.fill === WHITE,
                  // 元が白文字なら黒へ、それ以外は元の色へ戻す (元色が無ければ黒)
                  run: (e, s) => { s.fill = s.whiteType ? BLACK : (s.originalFill != null ? s.originalFill : BLACK); } },
  resetOne:     { guard: (s) => true, run: (e, s) => { s.apply(s.initial); } },
};

export { SVG_NS, WHITE, BLACK, CONFIG, DEFAULT_LEADER_STYLE, EMPTY_LIST_HTML, STATUS_READY, INSPECTOR_EMPTY_HTML, LEGEND_HTML, INSPECTOR_ACTIONS };
