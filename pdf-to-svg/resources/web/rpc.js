// =============================================================================
// rpc.js — ローカル HTTP サーバ (`app.py` / `server.py`) の /rpc を叩くクライアント
// =============================================================================
// 役割: QtWebChannel を廃し fetch ベースへ。`window.rpc(method, args)` -> Promise を
// 公開する。
//
// 後方互換: `app.js` は起動時に `window.__rpcReady` を await し、`window.onProgress(cb)`
// で進捗コールバックを登録する。HTTP 化で接続ハンドシェイクは不要になったため
// `__rpcReady` は即解決済み。進捗はフロント側がループの i/N を直接 `setHint` するため
// `onProgress` は no-op。
//
// 認可: サーバは非安全メソッド (`/rpc` `/upload` `/quit` `/ping`) に**起動ごとの
// セッショントークン**を要求する (`web/origin_guard.py` の G6)。値は `app.py` が
// `--app=` の URL クエリでこの窓にだけ渡すので、ここで一度だけ読み取って公開する。
// `rpc.js` は `index.html` の最初の `<script>` なので、`app.js` から必ず参照できる。
(function () {
  "use strict";

  // URL からトークンを取る。**クエリから消さない** (`history.replaceState` で除くと、
  // 利用者が窓を再読込した瞬間にトークンを失いアプリが動かなくなる)。
  var TOKEN = new URLSearchParams(window.location.search).get("token") || "";

  // トークンを載せた fetch ヘッダを組む。`extra` は Content-Type 等の追加分。
  window.__authHeaders = function (extra) {
    var h = { "X-Session-Token": TOKEN };
    if (extra) { Object.keys(extra).forEach(function (k) { h[k] = extra[k]; }); }
    return h;
  };

  // `navigator.sendBeacon` はヘッダを付けられないので、そこだけクエリでトークンを送る
  // (サーバはヘッダ・クエリのどちらでも受ける)。
  window.__authUrl = function (path) {
    return path + (path.indexOf("?") < 0 ? "?" : "&") + "token=" + encodeURIComponent(TOKEN);
  };

  window.__rpcReady = Promise.resolve();
  window.onProgress = function () {}; // 進捗はフロントがローカル表示 (サーバからの push は無い)。

  window.rpc = async function (method, args) {
    var res = await fetch("/rpc", {
      method: "POST",
      headers: window.__authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ method: method, args: args || {} }),
    });
    var j = await res.json();
    if (j.ok) return j.data;
    throw new Error(j.error || "RPC error");
  };
})();
