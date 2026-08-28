"""ローカル HTTP サーバ (127.0.0.1 のみ・標準ライブラリ)。

QtWebEngine / QWebChannel を廃し、graph-editor と同じ「小さなローカルサーバ +
ブラウザ (Edge アプリモード)」方式へ。本ハンドラは以下を担う:

- `GET /` ほか: `resources/web/` の静的配信 (拡張子ホワイトリスト + パストラバーサル防止)
- `POST /rpc`: `{method, args}` を受け `rpc_methods.py` の `dispatch` へ流し `{ok, data}` を返す
- `POST /upload?name=...`: PDF バイト列を受け `loader.py` の `load_document_bytes` で読み込む
- `POST /quit` / `POST /ping`: ウィンドウ閉鎖ビーコン / 生存ハートビート (`app.py` のライフサイクル管理用)

ファイル入出力 (PDF を開く / SVG を保存) はブラウザ側の File System Access API が担い、
本サーバはバイト列の受け渡しと純粋な状態操作だけを行う (graph-editor と同じ思想)。
`ThreadingHTTPServer` のため、セッション状態の変更は `server.lock` で直列化する。
"""
from __future__ import annotations

import http.server
import json
import os
import threading
import time
from urllib.parse import parse_qs, unquote, urlsplit

from web import loader, origin_guard, rpc_methods
from web.rpc_methods import WebSession

# 受け付けるリクエスト本文の上限。同時接続数 (`MAX_CONNECTIONS`) と無通信上限
# (`REQUEST_TIMEOUT`) を入れてもなお、巨大な Content-Length を申告してゆっくり送れば
# 1 接続でメモリを積み上げられる (時間ではなく量の上限が要る)。
# 申告値がこれを超えたら**本文を読まずに** 413 を返す (読んでから捨てるのは DoS を防がない)。
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_RPC_BYTES = 8 * 1024 * 1024

# 1 接続あたりのソケット無通信上限 (秒)。これが無いと `handle_one_request` の
# `rfile.readline()` が**永久にブロック**し、`parse_request()` のガードにすら到達しない
# (ガードはリクエスト行とヘッダが届いて初めて走る)。何も送らない接続を並べるだけで
# ハンドラスレッドを恒久的に占有できてしまうので、期限を切って閉じる。
# ローカル UI との往復は数ミリ秒なので、10 秒は正常系に十分な余裕がある。
REQUEST_TIMEOUT = 10.0

# 同時に処理する接続数の上限。`ThreadingHTTPServer` は接続ごとに無制限にスレッドを
# 起こすため、上限が無いとスレッドとスタックメモリを食い潰せる。超過分は**受け付けずに
# 即切断**する (キューに積むと結局その接続を抱えることになる)。UI は 1 つで、
# 同時接続は静的資産の並列取得ぶん程度しか要らない。
MAX_CONNECTIONS = 32

# 静的配信を許す拡張子と MIME。
_MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
}


class Handler(origin_guard.GuardedHTTPRequestHandler):
    """静的配信 + RPC + アップロード + ライフサイクルビーコンの最小ハンドラ。

    同一オリジン検査とセッショントークン認可は基底の `parse_request()` が一手に引き受ける
    ので、以下の `do_*` / `_handle_*` に検査は書かない (`web/origin_guard.py` 参照)。
    `/rpc` `/upload` `/quit` `/ping` はすべて非安全メソッドなので、この 1 箇所でまとめて
    トークンを要求できている。ここへ `do_GET` の副作用や機微データの読み出しを足すと、
    Origin もトークンも要求しない安全メソッドの経路が穴になる点にだけ注意する。
    """

    # ソケットの無通信上限 (`socketserver.StreamRequestHandler.setup` が `settimeout` する)。
    # 基底の `handle_one_request` は `socket.timeout` を捕まえて接続を閉じるので、
    # ここに値を置くだけで「何も送らない接続」がスレッドを抱え続ける形が閉じる。
    timeout = REQUEST_TIMEOUT

    # ローカル単一ユーザ用途。アクセスログは出さない。
    def log_message(self, *args):
        pass

    # ── 送信ヘルパ ──
    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # frame 化・他オリジン読み出し・MIME 誤解釈を断つ防御ヘッダ。成功応答も 404 も
        # ここを通るので、`_send` 以外の送信経路を足すときは基底の `_reject` と同じく
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False),
                   "application/json; charset=utf-8")

    # `last_seen` の更新は基底 `GuardedHTTPRequestHandler._touch_if_same_origin` が
    # Origin 完全一致時にだけ行う。ここへ書き戻すと Origin 無し GET で watchdog を
    # 無期限に延命できるようになる (`origin_guard.py` の同名メソッドの doc を見よ)。

    # ── GET (静的配信) ──
    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            self._serve_file("index.html")
        elif path == "/favicon.ico":
            self._send(204)
        else:
            self._serve_file(path.lstrip("/"))

    def _serve_file(self, rel: str):
        """`resources/web` 配下のファイルを配信する。拡張子ホワイトリスト一致かつ
        解決後パスがルート配下のものだけを返す (パストラバーサル防止)。それ以外は 404。"""
        root = self.server.web_root
        ctype = _MIME.get(os.path.splitext(rel)[1].lower())
        if not rel or ctype is None:
            self._send(404, b"not found")
            return
        full = os.path.normpath(os.path.join(root, rel))
        if full != root and not full.startswith(root + os.sep):
            self._send(404, b"not found")
            return
        try:
            with open(full, "rb") as f:
                body = f.read()
        except OSError:
            self._send(404, b"not found")
            return
        self._send(200, body, ctype)

    # ── POST ──
    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/rpc":
            self._handle_rpc()
        elif path == "/upload":
            self._handle_upload()
        elif path == "/quit":
            self._send(204)
            self.server.quit_event.set()
        elif path == "/ping":
            self._send(204)
        else:
            self._send(404, b"not found")

    def _read_body(self, limit: int) -> "bytes | None":
        """Content-Length 分を確実に読み切る (大きな PDF での短絡読み防止)。

        申告値が `limit` を超えていたら**本文を読まずに** None を返す。読んでから捨てる
        のは DoS を防がない (受け取らないのが最も安い)。呼び出し側は 413 を返して
        `close_connection` を立てること — 読み切らずに応答すると keep-alive が壊れる。
        """
        raw = self.headers.get("Content-Length")
        if raw is None:
            return b""
        try:
            n = int(raw)
        except ValueError:
            return None
        if n < 0 or n > limit:
            return None
        buf = bytearray()
        while len(buf) < n:
            chunk = self.rfile.read(n - len(buf))
            if not chunk:
                break
            buf.extend(chunk)
        return bytes(buf)

    def _too_large(self, limit: int) -> None:
        self.close_connection = True
        self._send_json({"ok": False, "error": f"request body too large (limit {limit} bytes)"},
                        413)

    def _handle_rpc(self):
        body = self._read_body(MAX_RPC_BYTES)
        if body is None:
            self._too_large(MAX_RPC_BYTES)
            return
        try:
            req = json.loads(body or b"{}")
            method = req.get("method")
            args = req.get("args") or {}
        except (json.JSONDecodeError, AttributeError) as exc:
            self._send_json({"ok": False, "error": f"bad request: {exc}"}, 400)
            return
        try:
            with self.server.lock:
                data = rpc_methods.dispatch(self.server.session, method, args)
        except KeyError:
            self._send_json({"ok": False, "error": f"unknown method: {method}"})
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": str(exc)})
        else:
            self._send_json({"ok": True, "data": data})

    def _handle_upload(self):
        qs = parse_qs(urlsplit(self.path).query)
        name = unquote((qs.get("name") or ["document.pdf"])[0])
        data = self._read_body(MAX_UPLOAD_BYTES)
        if data is None:
            self._too_large(MAX_UPLOAD_BYTES)
            return
        try:
            session = self.server.session
            # 解析は**ロックの外**で行う。構築中の Document はまだ誰からも見えない純ローカル
            # 値なので共有状態を触らず、その間 `/rpc` が応答できる (ロック内で解析すると
            # その間アプリ全体が無反応になる)。アップロード同士は `upload_lock` で直列化する。
            with self.server.upload_lock:
                doc = loader.load_document_bytes(name, data)
                with self.server.lock:
                    # 履歴のリセットは解析が成功してから。解析の**前**にクリアすると、
                    # 読み込みに失敗したとき「読めなかったのに Undo 履歴だけ消えている」
                    # 状態になる。
                    session.undo.clear()
                    session.docs.append(doc)
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": str(exc)})
        else:
            self._send_json({"ok": True, "data": {"total": len(session.docs)}})


class BoundedThreadingHTTPServer(http.server.ThreadingHTTPServer):
    """同時処理数に上限を持つ `ThreadingHTTPServer`。

    標準の `ThreadingMixIn` は接続ごとに無条件でスレッドを起こす。ローカル待受とはいえ
    同一マシンの別プロセスは自由に繋げるので、上限が無いとスレッド数で押し潰せる。
    空きが無ければ**キューへ積まず即切断**する: 積んでも接続とメモリは抱えたままで、
    上限の意味が消えるためである。
    """

    def __init__(self, *args, max_connections: "int | None" = None, **kwargs):
        # 既定値は呼び出し時に読む (定義時に束縛するとテストから上限を差し替えられない)。
        self._slots = threading.BoundedSemaphore(max_connections or MAX_CONNECTIONS)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            # スレッド生成に失敗した場合。取った枠は必ず返す (漏らすと上限が
            # 片道で減り続け、やがて全接続を拒否する)。
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def create_server(web_root: str, session: WebSession, port: int = 0,
                  token: str | None = None,
                  max_connections: int | None = None) -> http.server.ThreadingHTTPServer:
    """127.0.0.1 で待ち受けるサーバを構築する (まだ serve はしない)。既定の `port=0` は
    空きポート。固定ポートが要る E2E も**この関数を通す**こと: `ThreadingHTTPServer` を
    手組みすると `configure_guard` を忘れて `unconfigured` の全拒否になり (かつては
    `test/e2e_server.py` が実際にその形だった)、同時接続の上限
    (`BoundedThreadingHTTPServer`) も落ちる。許可リストは bind 後の実ポートから作る。

    `token` はセッショントークン。既定 (`None`) では起動ごとに新しい値を作る。固定値を
    渡してよいのはテスト・E2E の使い捨てサーバだけで、本番経路 (`app.py`) は既定に任せる。
    発行後の値は `server.guard_token` から読める (`--app=` の URL へ載せる用)。
    `max_connections` の既定 (`None`) は `MAX_CONNECTIONS`。差し替えるのは上限が効くことを
    見るテストだけで、本番経路は既定に任せる。"""
    server = BoundedThreadingHTTPServer(("127.0.0.1", port), Handler,
                                        max_connections=max_connections)
    server.web_root = os.path.abspath(web_root)
    server.session = session
    server.lock = threading.Lock()
    # アップロードの直列化用。`lock`(共有状態の保護)とは別に持つことで、巨大 PDF の
    # 解析中も `/rpc` が応答しつつ、アップロードだけは並列に積み上がらない。
    server.upload_lock = threading.Lock()
    server.quit_event = threading.Event()
    server.last_seen = time.monotonic()
    origin_guard.configure_guard(server, server.server_address[1],
                                 token or origin_guard.new_session_token())
    return server
