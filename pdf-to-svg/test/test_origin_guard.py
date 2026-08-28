"""同一オリジン検査 + セッショントークン認可 (`web/origin_guard.py`) の迂回耐性を外形から
固定する。

主張の形は「**迂回入力では 403 になり、かつ副作用が発生していない**」。ステータスだけを
見ると「実行してから 403 を返す」実装 (`quit_event` は立ってしまう) を見逃すため、
`quit_event` / `last_seen` / `store` / `docs` を毎回突き合わせる。

ヘッダ検査 (Host/Origin/Content-Type) を試す各ケースは**正しいトークンを添えて**送る。
添えないと「トークンが無いから 403」でも通ってしまい、検査したつもりの次元が実際には
効いていない退行を取りこぼすため。逆にトークンの検査は、ヘッダをすべて正規値に揃えた
うえでトークンだけを外す/壊すことで主張する。

ここのテストベクタ表は `graph-editor/test/test_app_guard.py` と**同一仕様の複製**である
(2 プロジェクトは並行実装で、片方を変えたら両方を変える)。`urllib` は URL から Host を
強制するので `Host: evil.example` を送れない。`http.client` の `putrequest(skip_host=True)`
で任意のリクエスト行・ヘッダを手組みする。
"""
from __future__ import annotations

import http.client
import http.server
import json
import threading
import time

import config
import pytest
from dictionary.store import DictionaryStore
from web import origin_guard
from web.rpc_methods import WebSession
from web.server import Handler, create_server
from web.undo_stack import UndoStack
import socket

# 「Host ヘッダを省略する」を `None` と区別するための番兵。
_DEFAULT = object()


@pytest.fixture
def server(tmp_path):
    """`create_server` で組んだ実サーバ (ガード設定済み) を空きポートで走らせる。"""
    session = WebSession(DictionaryStore(tmp_path / "dict.json"), UndoStack())
    srv = create_server(str(config.resource_path("web")), session)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield srv
    finally:
        srv.shutdown()
        srv.server_close()
        session.store.close()


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


def _rpc(port, method, args, *, origin=_DEFAULT, ctype="application/json", host=_DEFAULT,
         token=None):
    headers = []
    if origin is _DEFAULT:
        headers.append(("Origin", f"http://127.0.0.1:{port}"))
    elif origin is not None:
        headers.append(("Origin", origin))
    if ctype is not None:
        headers.append(("Content-Type", ctype))
    body = json.dumps({"method": method, "args": args}).encode()
    return _request(port, "POST", "/rpc", host=host, headers=headers, body=body, token=token)


def _dict_add(server, **kwargs):
    """`dictAdd` (辞書を書き換える副作用つき RPC) を撃つ。既定では**正しいトークン**を添える
    ので、403 になったならヘッダ検査のどれかが効いたことを意味する。"""
    kwargs.setdefault("token", getattr(server, "guard_token", None))
    return _rpc(server.server_address[1], "dictAdd",
                {"source": "Item No.", "target": "侵入"}, **kwargs)


# ── 正常系 (これが壊れると UI が動かない) ──


def test_legitimate_ui_request_passes(server):
    status, body, _ = _dict_add(server)
    assert status == 200 and json.loads(body)["ok"] is True
    assert [e.target for e in server.session.store.all()] == ["侵入"]


def test_localhost_host_and_case_and_padding_pass(server):
    """`localhost` 表記・大文字・前後空白は正規化して通す (許可リストの正常系)。"""
    port = server.server_address[1]
    for host in (f"  127.0.0.1:{port}  ", f"LOCALHOST:{port}"):
        status, _, _ = _request(port, "GET", "/", host=host)
        assert status == 200, host


def test_quit_beacon_with_origin_sets_quit_event(server):
    """`navigator.sendBeacon('/quit')` 相当 (Content-Type 無し・本文なし) は通る。"""
    port = server.server_address[1]
    status, _, _ = _request(port, "POST", "/quit", token=server.guard_token,
                            headers=[("Origin", f"http://127.0.0.1:{port}")])
    assert status == 204
    # `quit_event.set()` は 204 送信の**後**なので、応答受信直後はまだ立っていないことがある。
    # 拒否側の主張 (`is_set() is False`) は待たずに成立するが、こちらは待つ必要がある。
    assert server.quit_event.wait(5) is True


# ── 迂回入力: Origin ──


@pytest.mark.parametrize("origin", [
    None,                                   # Origin ヘッダ無し (非ブラウザ / 素の curl)
    "https://evil.example",                 # 別オリジン
    "http://127.0.0.1:65535",               # 同ホスト別ポート
    "null",                                 # sandbox iframe / file:// / data:
])
def test_rpc_rejected_and_dictionary_untouched(server, origin):
    status, body, _ = _dict_add(server, origin=origin)
    assert status == 403 and body == b"forbidden"
    assert server.session.store.all() == []


def test_rpc_rejects_prefix_match_origin(server):
    """`http://127.0.0.1:<port>.evil.com` — 前方一致で判定していれば通ってしまう値。"""
    port = server.server_address[1]
    status, _, _ = _dict_add(server, origin=f"http://127.0.0.1:{port}.evil.com")
    assert status == 403
    assert server.session.store.all() == []


def test_rpc_rejects_duplicate_origin_headers(server):
    """正規 Origin を 2 本目に潜ませる。`get()` は先頭しか返さないので個数を見る必要がある。"""
    port = server.server_address[1]
    headers = [("Origin", "https://evil.example"),
               ("Origin", f"http://127.0.0.1:{port}"),
               ("Content-Type", "application/json")]
    body = json.dumps({"method": "dictAdd", "args": {"source": "a", "target": "b"}}).encode()
    status, _, _ = _request(port, "POST", "/rpc", headers=headers, body=body,
                            token=server.guard_token)
    assert status == 403
    assert server.session.store.all() == []


# ── 迂回入力: Content-Type (プリフライトを起こさない simple request) ──


@pytest.mark.parametrize("ctype", [
    "text/plain;charset=UTF-8",             # プリフライト無しで送れる simple request
    "application/x-www-form-urlencoded",    # <form> 送信
    "multipart/form-data; boundary=x",      # <form enctype>
    "application/json+evil",                # 許可値の前方一致狙い
    "x/application/json",                   # 許可値の部分一致狙い
])
def test_rpc_rejects_simple_request_content_types(server, ctype):
    status, _, _ = _dict_add(server, ctype=ctype)
    assert status == 403
    assert server.session.store.all() == []


def test_rpc_accepts_content_type_parameters(server):
    """許可値にパラメータが付いていても `;` の前で完全一致するなら通す。"""
    status, _, _ = _dict_add(server, ctype="Application/JSON ; charset=utf-8")
    assert status == 200
    assert len(server.session.store.all()) == 1


def test_post_without_content_type_but_with_body_is_rejected(server):
    """Content-Type 無しで通してよいのは本文の無いビーコンだけ。"""
    port = server.server_address[1]
    status, _, _ = _request(port, "POST", "/quit", token=server.guard_token,
                            headers=[("Origin", f"http://127.0.0.1:{port}")],
                            body=b"{}")
    assert status == 403
    assert server.quit_event.is_set() is False


# ── 認可: セッショントークン (同一マシンの別プロセス) ──
#
# ここの各ケースは Host・Origin・Content-Type をすべて正規値に揃えて送る。つまり
# 「ローカルの非ブラウザプロセスが**ヘッダを完璧に詐称した**」状況そのもので、
# トークンだけが拒否理由になっている。


@pytest.mark.parametrize("token", [
    None,                                   # トークン無し (ヘッダもクエリも付けない)
    "",                                     # 空文字
    "wrong-token",                          # 別の値
])
def test_rpc_without_valid_token_is_rejected_and_dictionary_untouched(server, token):
    status, body, _ = _dict_add(server, token=token)
    assert status == 403 and body == b"forbidden"
    assert server.session.store.all() == []


def test_rpc_rejects_token_prefix(server):
    """正解の先頭 N 文字。前方一致や `startswith` で比べていれば通ってしまう値。"""
    status, _, _ = _dict_add(server, token=server.guard_token[:8])
    assert status == 403
    assert server.session.store.all() == []


def test_quit_without_token_does_not_set_quit_event(server):
    """ローカルの別プロセスがアプリを落とせないこと (「実行してから 403」でもないこと)。"""
    port = server.server_address[1]
    status, _, _ = _request(port, "POST", "/quit",
                            headers=[("Origin", f"http://127.0.0.1:{port}")])
    assert status == 403
    assert server.quit_event.is_set() is False


def test_ping_without_token_does_not_refresh_last_seen(server):
    """トークン無しの `/ping` で idle watchdog を延命できないこと。"""
    port = server.server_address[1]
    server.last_seen = -1.0
    status, _, _ = _request(port, "POST", "/ping",
                            headers=[("Origin", f"http://127.0.0.1:{port}")])
    assert status == 403
    assert server.last_seen == -1.0


def test_upload_without_token_is_rejected_before_parsing(server):
    """未認可の本文は読まずに落とす (解析させない)。"""
    port = server.server_address[1]
    status, _, _ = _request(port, "POST", "/upload?name=x.pdf",
                            headers=[("Origin", f"http://127.0.0.1:{port}"),
                                     ("Content-Type", "application/octet-stream")],
                            body=b"%PDF-1.4\n" + b"A" * (512 * 1024))
    assert status == 403
    assert server.session.docs == []


def test_token_is_accepted_from_query_for_sendbeacon(server):
    """`navigator.sendBeacon('/quit?token=...')` 相当。ヘッダを付けられない API のための経路。"""
    port = server.server_address[1]
    status, _, _ = _request(port, "POST", f"/quit?token={server.guard_token}",
                            headers=[("Origin", f"http://127.0.0.1:{port}")])
    assert status == 204
    assert server.quit_event.wait(5) is True


def test_duplicate_token_query_values_are_rejected(server):
    """正解を 2 本目に潜ませる (どちらが真か決められない値は通さない)。"""
    port = server.server_address[1]
    status, _, _ = _request(port, "POST", f"/quit?token=wrong&token={server.guard_token}",
                            headers=[("Origin", f"http://127.0.0.1:{port}")])
    assert status == 403
    assert server.quit_event.is_set() is False


def test_get_does_not_require_a_token(server):
    """静的配信はトークンを要求しない。下位資産の取得にトークンは載らないうえ、GET には
    副作用も機微データも無いという前提 (`GuardedHTTPRequestHandler` のクラス doc) の裏取り。"""
    port = server.server_address[1]
    assert _request(port, "GET", "/")[0] == 200
    assert _request(port, "GET", "/app.js")[0] == 200
    # トークン付き URL (`--app=` の入口そのもの) でも `/` として配信されること。
    assert _request(port, "GET", f"/?token={server.guard_token}")[0] == 200


def test_token_is_never_served_to_unauthorized_clients(server):
    """**トークンを配信物へ埋めない**こと。埋めた瞬間に `GET /` を撃てる任意のローカル
    プロセスが読み出せ、同一マシンの別ユーザーという脅威がそのまま復活する。
    受け渡しは `--app=` の URL クエリ 1 本だけ (`app.py`)。"""
    port = server.server_address[1]
    token = server.guard_token.encode()
    for target in ("/", "/app.js", "/rpc.js", "/styles.css"):
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
    `<script src="http://127.0.0.1:<port>/app.js">` の `Host` は許可値そのものなので、Host 検査は
    通る。その経路を鈍らせるのは `Cross-Origin-Resource-Policy: same-origin`
    (`test_security_headers_are_sent_on_every_response`) であり、Host 検査が担うのは
    「攻撃者ドメイン名のまま 127.0.0.1 へ解決される」DNS リバインディングの遮断だけである。
    """
    port = server.server_address[1]
    assert _request(port, "GET", "/app.js", host="evil.example")[0] == 403
    assert _request(port, "GET", "/app.js")[0] == 200


# ── 迂回入力: リクエスト行 / フレーミング ──


def test_absolute_form_request_target_is_rejected(server):
    """`POST http://127.0.0.1:p/quit` + `Host: evil.example`。経路分岐は通るが Host は攻撃者値。"""
    port = server.server_address[1]
    status, _, _ = _request(port, "POST", f"http://127.0.0.1:{port}/quit",
                            host="evil.example", token=server.guard_token,
                            headers=[("Origin", f"http://127.0.0.1:{port}")])
    assert status == 403
    assert server.quit_event.is_set() is False


def test_transfer_encoding_is_rejected(server):
    """Content-Length しか読まない `_read_body` とチャンク本文の食い違い (デシンク) を封じる。"""
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
    status, _, _ = _request(port, "POST", "/ping", token=server.guard_token,
                            headers=[("Origin", f"http://127.0.0.1:{port}"),
                                     ("Content-Length", "0"),
                                     ("Content-Length", "0")])
    assert status == 403


# ── 迂回入力: ライフサイクル (副作用の不発を確認する) ──


def test_quit_without_origin_does_not_set_quit_event(server):
    """「実行してから 403」ではないこと。ここが緩むとアプリを外部から落とせる。"""
    port = server.server_address[1]
    status, _, _ = _request(port, "POST", "/quit", headers=[], token=server.guard_token)
    assert status == 403
    assert server.quit_event.is_set() is False


def test_ping_from_foreign_origin_does_not_refresh_last_seen(server):
    """外部から `/ping` を打ち続けて idle watchdog を無効化できないこと。"""
    port = server.server_address[1]
    server.last_seen = -1.0
    status, _, _ = _request(port, "POST", "/ping", token=server.guard_token,
                            headers=[("Origin", "https://evil.example")])
    assert status == 403
    assert server.last_seen == -1.0


@pytest.mark.parametrize("target", ["/", "/favicon.ico", "/does-not-exist"])
def test_get_without_origin_does_not_refresh_last_seen(server, target):
    """Origin 無しの GET (`<img src>` / no-cors fetch) は応答するが延命はしないこと。

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


def test_same_origin_get_refreshes_last_seen(server):
    """正規ページからの取得 (Origin 完全一致) は延命する = 判定と副作用が同じ 1 箇所にある。"""
    port = server.server_address[1]
    server.last_seen = -1.0
    status, _, _ = _request(port, "GET", "/",
                            headers=[("Origin", f"http://127.0.0.1:{port}")])
    assert status == 200
    assert server.last_seen > 0.0


def test_upload_without_origin_is_rejected_before_parsing(server):
    """本文を読む前に落ちる (未認可の巨大 body を解析させない)。"""
    port = server.server_address[1]
    status, _, _ = _request(port, "POST", "/upload?name=x.pdf", token=server.guard_token,
                            headers=[("Content-Type", "application/octet-stream")],
                            body=b"%PDF-1.4\n" + b"A" * (512 * 1024))
    assert status == 403
    assert server.session.docs == []


# ── fail closed / CORS ヘッダを出さない ──


def test_unconfigured_server_rejects_everything(tmp_path):
    """`ThreadingHTTPServer` を素で組んで `configure_guard` を忘れた場合は全拒否 (fail open しない)。
    テスト用の使い捨てサーバで生まれやすい形なので、回帰として固定する。"""
    session = WebSession(DictionaryStore(tmp_path / "dict.json"), UndoStack())
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.web_root = str(config.resource_path("web"))
    srv.session = session
    srv.lock = threading.Lock()
    srv.quit_event = threading.Event()
    srv.last_seen = 0.0
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    try:
        assert _request(port, "GET", "/")[0] == 403
        assert _dict_add(srv)[0] == 403
        assert session.store.all() == []
    finally:
        srv.shutdown()
        srv.server_close()
        session.store.close()


def test_no_cors_headers_are_ever_emitted(server):
    """ACAO を出さないこと自体が防御 (許可外オリジンのプリフライトを必ず失敗させる)。"""
    port = server.server_address[1]
    responses = [
        _request(port, "GET", "/"),
        _request(port, "GET", "/", host="evil.example"),
        _dict_add(server),
        _dict_add(server, origin="https://evil.example"),
        _request(port, "OPTIONS", "/rpc", headers=[("Origin", f"http://127.0.0.1:{port}")]),
    ]
    for _, _, headers in responses:
        assert not [k for k in headers.keys() if k.lower().startswith("access-control-")]


def test_security_headers_are_sent_on_every_response(server):
    """成功・404・403・204 の**すべて**に防御ヘッダが載ること。

    1 本でも欠けた応答があれば、その URL だけを frame の足がかりや他オリジンからの
    no-cors 読み出し (既知パスの 200/404 差によるポート探索) に使える。とくに拒否応答
    (`origin_guard._reject`) は成功応答と別経路なので、忘れられやすい。
    """
    port = server.server_address[1]
    responses = [
        _request(port, "GET", "/"),                              # 200 (成功 `_send`)
        _request(port, "GET", "/does-not-exist"),                # 404 (成功経路の別コード)
        _request(port, "GET", "/", host="evil.example"),         # 403 (`_reject`)
        _dict_add(server),                                       # 200 (JSON 応答)
        _request(port, "POST", "/ping", token=server.guard_token,
                 headers=[("Origin", f"http://127.0.0.1:{port}")]),  # 204 (本文なし)
    ]
    for status, _, headers in responses:
        assert headers.get("X-Frame-Options") == "DENY", status
        assert headers.get("X-Content-Type-Options") == "nosniff", status
        assert headers.get("Cross-Origin-Resource-Policy") == "same-origin", status
        csp = headers.get("Content-Security-Policy") or ""
        assert "frame-ancestors 'none'" in csp, status
        assert "default-src 'self'" in csp, status


def test_csp_opens_only_the_exceptions_the_ui_actually_needs(server):
    """CSP の例外は「実際に要るものだけ」。`unsafe-inline` はスタイルのみ (`index.html` の
    inline `<style>` と `style=` 属性)、`data:` は画像とフォントのみ (SVG に埋め込む PDF 由来
    画像とサブセットフォント)。**script へは一切開けない**ことをここで固定する。"""
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


def test_reject_logging_is_capped_per_reason(server, caplog):
    """403 の理由コードごとに先頭 N 件だけログへ出す (`startup.log` はローテーション無し)。"""
    port = server.server_address[1]
    with caplog.at_level("WARNING", logger="pdftosvg"):
        for _ in range(origin_guard.REJECT_LOG_LIMIT + 3):
            _request(port, "GET", "/", host="evil.example")
    lines = [r for r in caplog.records if "host-mismatch" in r.getMessage()]
    assert len(lines) == origin_guard.REJECT_LOG_LIMIT
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
