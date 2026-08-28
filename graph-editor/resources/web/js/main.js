// =============================================================================
// main.js — SVG ラベル位置 ビジュアル編集クライアントのエントリポイント
// =============================================================================
// 役割: バニラ JS・依存ゼロのクライアント本体。ローカルの小さな HTTP サーバ (`app.py`) から
// http://127.0.0.1 で配信され、OS の Edge をアプリモードで開いて動作する。ファイル I/O は
// `<input>`(開く) / ダウンロード(保存) 固定。File System Access API は VDI 環境でネイティブ
// ダイアログが不安定なため使わない (`utils.js` の `hasFsAccess()` が常に false を返す設計)。
//
// 構成: 状態 + ライフサイクル + 描画は `editor.js` の `Editor` クラスに集約し、1 ラベル分の
// 状態と DOM 同期は `label-state.js` の `LabelState` クラスが持つ。描画はホットパス
// (ドラッグ中の `pointermove`) で個別の `renderX` を直呼びせず `markDirty` で dirty フラグを
// 立て、`requestAnimationFrame` で 1 フレーム最大 1 回へ合流させる (描画スケジューラ)。
// インスペクタ/オーバーレイは構造シグネチャが変わった時だけ作り直し、通常フレームは
// 読出し値/座標だけを更新する。
// =============================================================================

import { dom } from "./dom.js";
import { drawIcons } from "./icons.js";
import { hasFsAccess } from "./utils.js";
import { STATUS_READY } from "./constants.js";
import { Editor } from "./editor.js";

// ── 1. 起動 ──

// 静的マークアップ内のアイコンを描画
drawIcons(document);

const editor = new Editor(dom);
editor.bindEvents();
editor.updateToolbar();
editor.goPhase(1);   // 最初は「ファイルを開く」画面
// E2E テスト用フック (本番動作には無害)。Playwright から `editor` を操作するため公開。
window.__editor = editor;

// `hasFsAccess()` は VDI 方針で常に false (utils.js 参照)。分岐は将来の再有効化に備えて残す。
if (hasFsAccess()) {
  editor.setStatus(STATUS_READY);
} else {
  editor.setStatus("簡易モード: 選択=ファイル選択 / 保存=ダウンロード (Edge 推奨)");
}

// ── 2. サーバ通信 (終了ビーコン / 生存ハートビート) ──

// サーバは `/quit` `/ping` に**起動ごとのセッショントークン**を要求する (`app.py` の G6)。
// 値は `app.py` が `--app=` の URL クエリでこの窓にだけ渡す。攻撃者ページが本アプリを
// `<iframe>` に埋めても、その frame の URL にトークンは無いので下の `pagehide` ビーコンは
// 403 になる (Origin だけでは frame 経由の自撃ちを見分けられない)。
// クエリからは**消さない** (`history.replaceState` で除くと、窓の再読込でトークンを失う)。
const SESSION_TOKEN = new URLSearchParams(window.location.search).get("token") || "";

// `navigator.sendBeacon` はヘッダを付けられないので、そこだけクエリでトークンを送る
// (サーバはヘッダ・クエリのどちらでも受ける)。
const authUrl = (path) => `${path}?token=${encodeURIComponent(SESSION_TOKEN)}`;

// 窓/タブを閉じたらローカルサーバへ終了を通知 (`/quit` ビーコン。常駐プロセスを残さない)。
window.addEventListener("pagehide", () => {
  try { navigator.sendBeacon(authUrl("/quit")); } catch { /* 失敗してもプロセス監視側で終了する */ }
});

// 生存ハートビート。Edge アプリ窓ではプロセス監視で終了するが、既定ブラウザ(フォールバック)
// 経路にはプロセスハンドルが無く、終了契機が pagehide ビーコンのみになる。ビーコン不達/タブ
// クラッシュ時にサーバ側 watchdog が自動終了できるよう、定期的に生存を知らせる。
setInterval(() => {
  fetch("/ping", {
    method: "POST", keepalive: true, headers: { "X-Session-Token": SESSION_TOKEN },
  }).catch(() => { });
}, 10000);