"""同一オリジン検査 + セッショントークン認可 (`app.py` の同名セクション) の迂回耐性を外形から
固定する。

主張の形は「**迂回入力では 403 になり、かつ副作用が発生していない**」。ステータスだけを見ると
「実行してから 403 を返す」実装 (`quit_event` は立ってしまう) を見逃すため、`quit_event` と
`last_seen` を毎回突き合わせる。`/quit` は `main()` の `finally` で `msedge.exe` へ
`proc.terminate()` を撃つ = 外部から撃たれると編集内容が消えるうえ他の Edge 窓を巻き添えに
しうるので、ここが緩むと実害が出る。

ヘッダ検査 (Host/Origin/Content-Type) を試す各ケースは**正しいトークンを添えて**送る。
添えないと「トークンが無いから 403」でも通ってしまい、検査したつもりの次元が実際には
効いていない退行を取りこぼすため。逆にトークンの検査は、ヘッダをすべて正規値に揃えた
うえでトークンだけを外す/壊すことで主張する。

ここのテストベクタ表は `pdf-to-svg/test/test_origin_guard.py` と**同一仕様の複製**である
(2 プロジェクトは並行実装で、片方を変えたら両方を変える)。`urllib` は URL から Host を
強制するので `Host: evil.example` を送れない。`http.client` の `putrequest(skip_host=True)`
で任意のリクエスト行・ヘッダを手組みする。

`import app` に副作用は無く Edge も起動しない (同梱資産の読み込みは `main()`/初回 GET の
遅延読込。`main()` を呼ばない)。
"""
from __future__ import annotations

import http.client
import http.server
import threading
import time

import app
import pytest
import socket

# 「Host ヘッダを省略する」を `None` と区別するための番兵。
_DEFAULT = object()


@pytest.fixture
def server():
    """`create_server` で組んだ実サーバ (ガード設定済み) を空きポートで走らせる。"""
    srv = app.create_server()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()


def _request(port, method, target, *, host=_DEFAULT, headers=(), body=None, raw_tail=None,
             token=None):
    """リクエスト行とヘッダを手組みして 1 往復する。`(status, body, headers)` を返す。
    `token` を渡すと `X-Session-Token` ヘッダを載せる (`None` は無しで送る)。"""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
        if host is _DEFAULT:
            conn.putheader("Host", f"127.0.0.1:{port}")
        elif host is not None:
            conn.putheader("Host", host)
        if token is not None:
            conn.putheader("X-Session-Token", token)
        for name, value in headers:
            conn.putheader(name, value)
        if body is not None and not any(n.lower() == "transfer-encoding" for n, _ in headers):
            conn.putheader("Content-Length", str(len(body)))
        conn.endheaders()
        if body is not None:
            conn.send(body)
        if raw_tail is not None:
            conn.send(raw_tail)
        res = conn.getresponse()
        return res.status, res.read(), res.headers
    finally:
        conn.close()


def _beacon(server, target, *, origin=_DEFAULT, host=_DEFAULT, extra=(), token=_DEFAULT):
    """`navigator.sendBeacon(target)` / `fetch(target, {method:'POST'})` 相当
    (本文なし・Content-Type なし) を送る。既定では**正しいトークン**を添えるので、
    403 になったならヘッダ検査のどれかが効いたことを意味する。"""
    port = server.server_address[1]
    headers = []
    if origin is _DEFAULT:
        headers.append(("Origin", f"http://127.0.0.1:{port}"))
    elif origin is not None:
        headers.append(("Origin", origin))
    headers.extend(extra)
    if token is _DEFAULT:
        token = getattr(server, "guard_token", None)
    return _request(port, "POST", target, host=host, headers=headers, token=token)


# ── 正常系 (これが壊れると UI が動かない / 窓を閉じてもプロセスが残る) ──


def test_ui_html_is_served(server):
    port = server.server_address[1]
    status, body, _ = _request(port, "GET", "/")
    assert status == 200 and b"<html" in body.lower()


def test_localhost_host_and_case_and_padding_pass(server):
    """`localhost` 表記・大文字・前後空白は正規化して通す (許可リストの正常系)。"""
    port = server.server_address[1]
    for host in (f"  127.0.0.1:{port}  ", f"LOCALHOST:{port}"):
        assert _request(port, "GET", "/", host=host)[0] == 200, host


def test_quit_beacon_with_origin_sets_quit_event(server):
    """`main.js` の `navigator.sendBeacon('/quit')` がそのまま通ること (無改修の裏取り)。"""
    port = server.server_address[1]
    status, _, _ = _beacon(server, "/quit")
    assert status == 204
    # `quit_event.set()` は 204 送信の**後**なので、応答受信直後はまだ立っていないことがある。
    # 拒否側の主張 (`is_set() is False`) は待たずに成立するが、こちらは待つ必要がある。
    assert server.quit_event.wait(5) is True


def test_ping_beacon_with_origin_refreshes_last_seen(server):
    """`main.js` の 10 秒毎 `fetch('/ping', {method:'POST', keepalive:true})` が通ること。"""
    port = server.server_address[1]
    server.last_seen = -1.0
    status, _, _ = _beacon(server, "/ping")
    assert status == 204
    assert server.last_seen > 0.0


# ── 迂回入力: Origin ──


@pytest.mark.parametrize("origin", [
    None,                                   # Origin ヘッダ無し (非ブラウザ / 素の curl)
    "https://evil.example",                 # 別オリジン
    "http://127.0.0.1:65535",               # 同ホスト別ポート
    "null",                                 # sandbox iframe / file:// / data:
])
def test_quit_rejected_without_valid_origin(server, origin):
    """「実行してから 403」ではないこと。ここが緩むとアプリを外部ページから落とせる。"""
    port = server.server_address[1]
    status, body, _ = _beacon(server, "/quit", origin=origin)
    assert status == 403 and body == b"forbidden"
    assert server.quit_event.is_set() is False


def test_quit_rejects_prefix_match_origin(server):
    """`http://127.0.0.1:<port>.evil.com` — 前方一致で判定していれば通ってしまう値。"""
    port = server.server_address[1]
    status, _, _ = _beacon(server, "/quit", origin=f"http://127.0.0.1:{port}.evil.com")
    assert status == 403
    assert server.quit_event.is_set() is False


def test_quit_rejects_duplicate_origin_headers(server):
    """正規 Origin を 2 本目に潜ませる。`get()` は先頭しか返さないので個数を見る必要がある。"""
    port = server.server_address[1]
    status, _, _ = _beacon(server, "/quit", origin="https://evil.example",
                           extra=[("Origin", f"http://127.0.0.1:{port}")])
    assert status == 403
    assert server.quit_event.is_set() is False


def test_ping_from_foreign_origin_does_not_refresh_last_seen(server):
    """外部から `/ping` を打ち続けて idle watchdog を無効化し、ゾンビサーバを維持できないこと。"""
    port = server.server_address[1]
    server.last_seen = -1.0
    status, _, _ = _beacon(server, "/ping", origin="https://evil.example")
    assert status == 403
    assert server.last_seen == -1.0


@pytest.mark.parametrize("target", ["/", "/favicon.ico", "/styles.css", "/does-not-exist"])
def test_get_without_origin_does_not_refresh_last_seen(server, target):
    """Origin 無しの GET (`<img src>` / no-cors fetch) は 200/204/404 を返すが延命はしない。

    Host は攻撃者ページからの取得でも `127.0.0.1:<port>` になり G1 を通り、Origin が無い以上
    G3/G4 のどちらにも掛からない。ここで `last_seen` が進むと、数十秒間隔で叩き続けるだけで
    `IDLE_TIMEOUT` が永久に発火しなくなる (= watchdog の無効化)。
    """
    port = server.server_address[1]
    server.last_seen = -1.0
    for _ in range(3):
        status, _, _ = _request(port, "GET", target)
        assert status in (200, 204, 404)
    assert server.last_seen == -1.0


# ── 迂回入力: Content-Type (プリフライトを起こさない simple request) ──


@pytest.mark.parametrize("ctype", [
    "text/plain;charset=UTF-8",             # `fetch(..., {mode:'no-cors'})` の抜け道
    "application/x-www-form-urlencoded",    # <form> 送信
    "multipart/form-data; boundary=x",      # <form enctype>
    "application/json+evil",                # 許可値の前方一致狙い
    "x/application/json",                   # 許可値の部分一致狙い
])
def test_quit_rejects_simple_request_content_types(server, ctype):
    port = server.server_address[1]
    status, _, _ = _request(port, "POST", "/quit", token=server.guard_token,
                            headers=[("Origin", f"http://127.0.0.1:{port}"),
                                     ("Content-Type", ctype)],
                            body=b"x")
    assert status == 403
    assert server.quit_event.is_set() is False


def test_post_without_content_type_but_with_body_is_rejected(server):
    """Content-Type 無しで通してよいのは本文の無いビーコンだけ。"""
    port = server.server_address[1]
    status, _, _ = _request(port, "POST", "/quit", token=server.guard_token,
                            headers=[("Origin", f"http://127.0.0.1:{port}")],
                            body=b"{}")
    assert status == 403
    assert server.quit_event.is_set() is False


# ── 認可: セッショントークン (frame 埋め込み / 同一マシンの別プロセス) ──
#
# ここの各ケースは Host・Origin・Content-Type をすべて正規値に揃えて送る。つまり
# 「攻撃者ページに `<iframe>` されたアプリ自身が自分の Origin で撃った `/quit`」と
# 「ローカルの非ブラウザプロセスがヘッダを完璧に詐称した要求」そのもので、
# トークンだけが拒否理由になっている。


@pytest.mark.parametrize("token", [
    None,                                   # トークン無し (ヘッダもクエリも付けない)
    "",                                     # 空文字
    "wrong-token",                          # 別の値
])
def test_quit_without_valid_token_does_not_set_quit_event(server, token):
    """frame に埋め込まれた本アプリの `pagehide` ビーコンを止める。Origin は完全一致するので
    同一オリジン検査だけでは通ってしまう経路で、ここが最後の関所になる。"""
    status, body, _ = _beacon(server, "/quit", token=token)
    assert status == 403 and body == b"forbidden"
    assert server.quit_event.is_set() is False


def test_quit_rejects_token_prefix(server):
    """正解の先頭 N 文字。前方一致や `startswith` で比べていれば通ってしまう値。"""
    status, _, _ = _beacon(server, "/quit", token=server.guard_token[:8])
    assert status == 403
    assert server.quit_event.is_set() is False


def test_ping_without_token_does_not_refresh_last_seen(server):
    """トークン無しの `/ping` で idle watchdog を延命できないこと (ゾンビサーバの維持を断つ)。"""
    server.last_seen = -1.0
    status, _, _ = _beacon(server, "/ping", token=None)
    assert status == 403
    assert server.last_seen == -1.0


def test_token_is_accepted_from_query_for_sendbeacon(server):
    """`navigator.sendBeacon('/quit?token=...')` 相当。ヘッダを付けられない API のための経路。"""
    status, _, _ = _beacon(server, f"/quit?token={server.guard_token}", token=None)
    assert status == 204
    assert server.quit_event.wait(5) is True


def test_duplicate_token_query_values_are_rejected(server):
    """正解を 2 本目に潜ませる (どちらが真か決められない値は通さない)。"""
    status, _, _ = _beacon(server, f"/quit?token=wrong&token={server.guard_token}", token=None)
    assert status == 403
    assert server.quit_event.is_set() is False


def test_get_does_not_require_a_token(server):
    """静的配信はトークンを要求しない。下位資産の取得にトークンは載らないうえ、GET には
    副作用も機微データも無いという前提 (`GuardedHandler` のクラス doc) の裏取り。"""
    port = server.server_address[1]
    assert _request(port, "GET", "/")[0] == 200
    assert _request(port, "GET", "/js/main.js")[0] == 200
    # トークン付き URL (`--app=` の入口そのもの) でも `/` として配信されること。
    assert _request(port, "GET", f"/?token={server.guard_token}")[0] == 200


def test_token_is_never_served_to_unauthorized_clients(server):
    """**トークンを `ui.html` へ埋めない**こと。埋めると frame に埋め込まれた本アプリ自身が
    それを受け取り、`pagehide` の `/quit` が通ってしまう (frame 埋め込みの経路がそのまま復活する)。
    受け渡しは `--app=` の URL クエリ 1 本だけ (`main()`)。"""
    port = server.server_address[1]
    token = server.guard_token.encode()
    for target in ("/", "/ui.html", "/js/main.js", "/styles.css", "/lib/leader_geom.cjs"):
        status, body, headers = _request(port, "GET", target)
        assert status == 200, target
        assert token not in body, target
        assert token not in str(headers).encode(), target


# ── 迂回入力: Host (DNS リバインディング) ──


@pytest.mark.parametrize("host", [
    "evil.example",                         # リバインディング時に実際に届く値
    "127.0.0.1.evil.com:{port}",            # 前方一致狙い
    "evil.com:{port}",                      # 部分一致狙い
    "127.0.0.1.:{port}",                    # 末尾ドット付き FQDN
    "[::1]:{port}",                         # 別ループバック表記
    None,                                   # Host ヘッダ無し
])
def test_get_rejected_on_host_mismatch(server, host):
    port = server.server_address[1]
    status, _, _ = _request(port, "GET", "/",
                            host=None if host is None else host.format(port=port))
    assert status == 403


def test_rejects_duplicate_host_headers(server):
    port = server.server_address[1]
    status, _, _ = _request(port, "GET", "/", host="evil.example",
                            headers=[("Host", f"127.0.0.1:{port}")])
    assert status == 403


def test_static_asset_rejected_on_host_mismatch(server):
    """名前ベースで届いた取得 (`Host: evil.example`) は静的資産でも 403 になること。

    ⚠ これは**ポート探索オラクルを塞ぐ主張ではない**: 攻撃者ページが IP リテラルを直に書いた
    `<script src="http://127.0.0.1:<port>/js/main.js">` の `Host` は許可値そのものなので、Host
    検査は通る。その経路を鈍らせるのは `Cross-Origin-Resource-Policy: same-origin`
    (`test_security_headers_are_sent_on_every_response`) であり、Host 検査が担うのは
    「攻撃者ドメイン名のまま 127.0.0.1 へ解決される」DNS リバインディングの遮断だけである。
    """
    port = server.server_address[1]
    assert _request(port, "GET", "/js/main.js", host="evil.example")[0] == 403
    assert _request(port, "GET", "/js/main.js")[0] == 200


# ── 迂回入力: リクエスト行 / フレーミング ──


def test_absolute_form_request_target_is_rejected(server):
    """`POST http://127.0.0.1:p/quit` + `Host: evil.example`。経路分岐は通るが Host は攻撃者値。"""
    port = server.server_address[1]
    status, _, _ = _beacon(server, f"http://127.0.0.1:{port}/quit", host="evil.example")
    assert status == 403
    assert server.quit_event.is_set() is False


def test_transfer_encoding_is_rejected(server):
    """チャンク本文が未読のまま keep-alive 接続に残る食い違い (デシンク) を封じる。"""
    port = server.server_address[1]
    status, _, _ = _request(port, "POST", "/quit", token=server.guard_token,
                            headers=[("Origin", f"http://127.0.0.1:{port}"),
                                     ("Transfer-Encoding", "chunked")],
                            raw_tail=b"0\r\n\r\n")
    assert status == 403
    assert server.quit_event.is_set() is False


def test_unread_body_does_not_reset_the_connection(server):
    """拒否時に未読本文を残したまま閉じると OS が RST を送り、**送信済みの 403 ごと**
    クライアントの受信バッファが捨てられる (拒否はできているのに接続エラーしか見えない)。
    `_drain_body` は `Transfer-Encoding` を読めないのでこの経路へ落ちる。

    上の `test_transfer_encoding_is_rejected` は本文の続きが届くのとサーバが閉じるのの
    競争になっていて、この退行を取りこぼしうる。ここでは 403 を送り終えた頃合いに続きを
    送りつけ、確定的に踏ませる。
    """
    port = server.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.putrequest("POST", "/quit", skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", f"127.0.0.1:{port}")
        conn.putheader("Origin", f"http://127.0.0.1:{port}")
        conn.putheader("X-Session-Token", server.guard_token)
        conn.putheader("Transfer-Encoding", "chunked")
        conn.endheaders()
        time.sleep(0.1)  # 拒否は即座なので、これで「閉じるなら閉じ終えた」状態になる
        conn.send(b"0\r\n\r\n")
        res = conn.getresponse()
        assert res.status == 403
        assert res.read() == b"forbidden"
    finally:
        conn.close()
    assert server.quit_event.is_set() is False


def test_duplicate_content_length_is_rejected(server):
    port = server.server_address[1]
    status, _, _ = _beacon(server, "/ping", extra=[("Content-Length", "0"),
                                                   ("Content-Length", "0")])
    assert status == 403


# ── fail closed / CORS ヘッダを出さない ──


def test_unconfigured_server_rejects_everything():
    """`ThreadingHTTPServer` を素で組んで `configure_guard` を忘れた場合は全拒否 (fail open しない)。"""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    srv.quit_event = threading.Event()
    srv.last_seen = 0.0
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        assert _request(port, "GET", "/")[0] == 403
        assert _beacon(srv, "/quit")[0] == 403
        assert srv.quit_event.is_set() is False
    finally:
        srv.shutdown()
        srv.server_close()


def test_no_cors_headers_are_ever_emitted(server):
    """ACAO を出さないこと自体が防御 (許可外オリジンのプリフライトを必ず失敗させる)。"""
    port = server.server_address[1]
    responses = [
        _request(port, "GET", "/"),
        _request(port, "GET", "/", host="evil.example"),
        _beacon(server, "/ping"),
        _beacon(server, "/ping", origin="https://evil.example"),
        _request(port, "OPTIONS", "/quit", headers=[("Origin", f"http://127.0.0.1:{port}")]),
    ]
    for _, _, headers in responses:
        assert not [k for k in headers.keys() if k.lower().startswith("access-control-")]


def test_security_headers_are_sent_on_every_response(server):
    """成功・404・403・204 の**すべて**に防御ヘッダが載ること。

    `frame-ancestors 'none'` / `X-Frame-Options: DENY` が 1 応答でも欠けると、その URL を
    `<iframe>` の足がかりにでき、frame 内のアプリ自身が撃つ `/quit` の入口が開く。
    とくに拒否応答 (`GuardedHandler._reject`) は成功応答と別経路なので忘れられやすい。
    """
    port = server.server_address[1]
    responses = [
        _request(port, "GET", "/"),                              # 200 (成功 `_send`)
        _request(port, "GET", "/does-not-exist"),                # 404 (成功経路の別コード)
        _request(port, "GET", "/", host="evil.example"),         # 403 (`_reject`)
        _beacon(server, "/ping"),                                # 204 (本文なし)
    ]
    for status, _, headers in responses:
        assert headers.get("X-Frame-Options") == "DENY", status
        assert headers.get("X-Content-Type-Options") == "nosniff", status
        assert headers.get("Cross-Origin-Resource-Policy") == "same-origin", status
        csp = headers.get("Content-Security-Policy") or ""
        assert "frame-ancestors 'none'" in csp, status
        assert "default-src 'self'" in csp, status


def test_csp_opens_only_the_exceptions_the_ui_actually_needs(server):
    """CSP の例外は「実際に要るものだけ」。`unsafe-inline` はスタイルのみ (読み込んだ SVG の
    `<style>` に入る `@font-face`)、`data:` は画像とフォントのみ。**script へは一切開けない**
    ことをここで固定する。**pdf-to-svg の同名テストと逐語で揃えること** (並行実装)。"""
    port = server.server_address[1]
    csp = (_request(port, "GET", "/")[2].get("Content-Security-Policy") or "")
    directives = {}
    for part in csp.split(";"):
        tokens = part.split()
        if tokens:
            directives[tokens[0]] = tokens[1:]
    assert "'unsafe-inline'" not in directives.get("default-src", [])
    assert "'unsafe-eval'" not in directives.get("default-src", [])
    assert "script-src" not in directives  # default-src 'self' へ落ちる = inline script 不可
    assert directives["style-src"] == ["'self'", "'unsafe-inline'"]
    assert directives["img-src"] == ["'self'", "data:"]
    assert directives["font-src"] == ["'self'", "data:"]
    assert directives["object-src"] == ["'none'"]
    assert directives["base-uri"] == ["'none'"]


# pdf-to-svg との drift 検出 (`SECURITY_HEADERS` / `TOKEN_*` / 資源上限 / Edge 起動引数の
# 突き合わせ) は `test_parallel_impl_drift.py` に集約した。ここは graph-editor 単体の外形を見る。


def test_reject_logging_is_capped_per_reason(server, caplog):
    """403 の理由コードごとに先頭 N 件だけログへ出す (ログを膨らませられないこと)。"""
    port = server.server_address[1]
    with caplog.at_level("WARNING", logger="labeleditor"):
        for _ in range(app.REJECT_LOG_LIMIT + 3):
            _request(port, "GET", "/", host="evil.example")
    lines = [r for r in caplog.records if "host-mismatch" in r.getMessage()]
    assert len(lines) == app.REJECT_LOG_LIMIT
    # 攻撃者の入れた値をそのままログへ出さない (制御文字での行偽装を防ぐ整形が効いている)。
    assert all("\n" not in r.getMessage() for r in lines)

def _raw_head(port, request_bytes):
    """生ソケットで 1 往復し、応答ヘッダ部だけを小文字で返す。

    `http.client` はリクエスト行の長さを自前で検証してしまうため、414 を出させるには
    生で送る必要がある。
    """
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(request_bytes)
        chunks = []
        while b"\r\n\r\n" not in b"".join(chunks):
            got = sock.recv(4096)
            if not got:
                break
            chunks.append(got)
    return b"".join(chunks).split(b"\r\n\r\n", 1)[0].decode("latin-1")


def test_security_headers_are_sent_on_base_class_responses(server):
    """基底クラスが直接返す応答にも防御ヘッダが載ること。

    `_send` / `_reject` を明示的に通らない応答が 2 種ある:
      - `HEAD` に `do_HEAD` が無いときの **501**
      - リクエスト行が長すぎるときの **414** (`parse_request()` より前で返るので
        同一オリジン検査すら通らない)
    どちらも `send_error()` 経由で、明示呼び出し方式では防御ヘッダ無しで出ていた。
    ヘッダが欠けると `Cross-Origin-Resource-Policy` が効かず、クロスオリジンの
    `fetch(..., {method:'HEAD', mode:'no-cors'})` が resolve する = 「このポートでこの
    アプリが動いている」を確定できる (ポート探索オラクル)。付与は `end_headers()` の
    override 1 箇所へ集約してあるので、送信経路を足しても付け忘れは起きない。
    """
    port = server.server_address[1]

    status, _, headers = _request(port, "HEAD", "/")
    assert status == 501
    assert headers.get("X-Frame-Options") == "DENY"
    assert headers.get("X-Content-Type-Options") == "nosniff"
    assert headers.get("Cross-Origin-Resource-Policy") == "same-origin"
    assert "frame-ancestors 'none'" in (headers.get("Content-Security-Policy") or "")

    head = _raw_head(port, b"GET /" + b"a" * 70000 + b" HTTP/1.1\r\n\r\n").lower()
    assert " 414 " in head.split("\r\n", 1)[0]
    assert "x-frame-options: deny" in head
    assert "cross-origin-resource-policy: same-origin" in head
    assert "frame-ancestors 'none'" in head


def test_security_headers_are_not_duplicated(server):
    """1 応答につき 1 回だけ載ること (`end_headers()` の二重付与ガード)。"""
    port = server.server_address[1]
    head = _raw_head(
        port,
        b"GET / HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nConnection: close\r\n\r\n" % port,
    ).lower()
    assert head.count("x-frame-options:") == 1
    assert head.count("cross-origin-resource-policy:") == 1
