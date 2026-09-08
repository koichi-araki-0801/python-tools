"""接続の資源上限 (`app.py` の `REQUEST_TIMEOUT` / `MAX_CONNECTIONS`) の退行ガード。

「正しい入力を正しく処理する」ではなく**「迂回入力で破綻しない」**を主張する形で書く。
所要時間ではなく**上限が効くこと**を見る (実時間はマシン依存で脆い): 上限に当たったら
拒否して**必ず返る**こと、そして上限が正常系を壊していないこと。

同一オリジン検査 (`parse_request`) はリクエスト行とヘッダが届いて初めて走るので、
**何も送らない接続はガードの手前でブロックし続ける**。ここを閉じられるのはハンドラ側の
期限と受け入れ枠だけで、認可のテスト (`test_app_guard.py`) では捕まえられない。

pdf-to-svg の `test/test_resource_limits.py`「接続の資源上限」節と**同一仕様の複製**
である (並行実装)。2 実装の値が揃っていることは `test_parallel_impl_drift.py` が検証する。
"""
from __future__ import annotations

import concurrent.futures
import socket
import socketserver
import threading
import time
import urllib.error
import urllib.request

import app


def _serve(**kwargs):
    """`create_server` でサーバを起動して返す (呼び出し側で shutdown)。"""
    server = app.create_server(**kwargs)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _wait_until(pred, msg: str, timeout: float = 10.0, interval: float = 0.02):
    """`pred()` が真になるまで待つ (固定 sleep の置き換え)。

    接続を張っただけでは枠は取られていない (listen キューに積まれるだけで、accept して
    初めて `process_request` が走る)。固定 sleep で待つと遅い端末では枠が埋まる前に次の
    接続を張ってしまい、上限の主張が黙って崩れる。条件で待てば、速い端末では即座に進む。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(interval)
    raise AssertionError(msg)


def _get_ok(port: int) -> int:
    """`GET /` を 1 回投げてステータスを返す (正常系が壊れていないことの確認用)。"""
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as res:
        res.read()
        return res.status


def test_silent_connection_is_closed_by_the_handler_timeout(monkeypatch):
    """何も送らない接続はスレッドを恒久占有できない (`parse_request` は届かない)。"""
    monkeypatch.setattr(app.Handler, "timeout", 0.5)
    server = _serve()
    try:
        sock = socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=10)
        sock.settimeout(10)
        # 1 バイトも送らない。期限が効いていれば向こうから閉じる (recv が EOF を返す)。
        assert sock.recv(1) == b""
        sock.close()
    finally:
        server.shutdown()
        server.server_close()


def test_dripping_connection_is_closed_by_the_request_deadline(monkeypatch):
    """改行を送らずに少しずつ送り続ける接続も、**要求単位の絶対期限**で閉じられる。

    per-recv の `timeout` は recv ごとに再武装されるので、per-recv より短い間隔で 1 バイトずつ
    送り続ければ `readline` を無限に引き延ばして 1 スレッドを恒久占有できた。`MAX_REQUEST_SECONDS`
    はこれを閉じる。per-recv を十分長く (5s)、期限を短く (1s) して、閉じているのが期限であること
    を主張する (pdf-to-svg 側と同一挙動)。
    """
    monkeypatch.setattr(app.Handler, "timeout", 5.0)
    monkeypatch.setattr(app, "MAX_REQUEST_SECONDS", 1.0)
    server = _serve()
    try:
        sock = socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=10)
        sock.settimeout(0.3)
        start = time.monotonic()
        closed_by_server = False
        wall = start + 6.0  # 安全弁 (期限が効かなければここまで回り続けて False で落ちる)
        while time.monotonic() < wall:
            try:
                sock.sendall(b"a")  # 改行なし = リクエスト行は完成しない
            except OSError:
                closed_by_server = True
                break
            try:
                if sock.recv(1) == b"":  # 向こう (サーバ) が閉じた
                    closed_by_server = True
                    break
            except socket.timeout:
                pass  # まだ開いている。次のドリップへ。
            time.sleep(0.15)  # per-recv (5s) には遠く及ばない間隔
        sock.close()
        assert closed_by_server, "ドリップ接続が期限で閉じられていない"
        # 期限 (1s) + 余裕。per-recv (5s) にはまだ達していないので、閉じたのは期限である。
        assert time.monotonic() - start < 4.0
    finally:
        server.shutdown()
        server.server_close()


def test_connection_cap_accepts_exactly_the_cap_and_refuses_the_next(monkeypatch):
    """上限ちょうどまでは受理し、超えた接続は受け付けず即切断する (スレッドを積み上げない)。

    受理を 1 本ずつ `available_slots` で主張するのが要点。まとめて張って最後の 1 本だけを
    見る形だと、上限が過小へ退行して (例: 2 → 1) 2 本目が即切断されていても、3 本目の
    切断は同じように観測できてしまい、テストは通り抜ける。
    """
    monkeypatch.setattr(app.Handler, "timeout", 5.0)
    cap = 2
    server = _serve(max_connections=cap)
    port = server.server_address[1]
    assert server.available_slots == cap
    hogs = []
    try:
        for taken in range(1, cap + 1):  # 無言接続で枠を 1 つずつ埋める
            hogs.append(socket.create_connection(("127.0.0.1", port), timeout=10))
            _wait_until(lambda taken=taken: server.available_slots == cap - taken,
                        f"{taken} 本目の接続が受理されていない (上限が過小)")

        extra = socket.create_connection(("127.0.0.1", port), timeout=10)
        extra.settimeout(10)
        assert extra.recv(1) == b""  # 枠が無いので応答せず切断される
        extra.close()
        # 拒否は枠を消費しない (`process_request` が acquire に失敗した側で return する)。
        assert server.available_slots == 0

        for sock in hogs:  # 枠を返せば通常のリクエストがまた通る
            sock.close()
        hogs = []
        _wait_until(lambda: server.available_slots == cap, "枠が返っていない")
        assert _get_ok(port) == 200
    finally:
        for sock in hogs:
            sock.close()
        server.shutdown()
        server.server_close()


def test_connection_slots_are_released_after_each_request(monkeypatch):
    """処理し終えた接続は枠を返す (上限を超える回数を捌いても詰まらない)。

    枠の解放を落とすと上限が**片道で減り続け**、やがて全接続を拒否する。上限そのものを
    見るテストは 1 巡しか回さないのでこの形を捕まえられない。上限より多い回数を逐次に
    投げて、最後まで通り切ることと枠が満杯へ戻ることの両方を見る。
    """
    monkeypatch.setattr(app.Handler, "timeout", 5.0)
    cap = 2
    server = _serve(max_connections=cap)
    port = server.server_address[1]
    try:
        for i in range(cap + 3):  # 上限より多い回数を逐次に (枠が片道で減れば途中で詰まる)
            assert _get_ok(port) == 200, f"{i + 1} 回目のリクエストが通らない"
        _wait_until(lambda: server.available_slots == cap, "処理後に枠が返っていない")
    finally:
        server.shutdown()
        server.server_close()


def test_concurrent_requests_within_the_cap_all_succeed(monkeypatch):
    """上限内の同時リクエストは全部成功する (上限が正常系を壊していない)。

    逐次のテストは枠の取得と解放が 1 本ずつ交代する形しか通らない。ここは上限ぴったりの
    多重度で上限の数倍を捌かせ、**取得と解放が競合する下でも**拒否が混ざらないことを見る。
    """
    monkeypatch.setattr(app.Handler, "timeout", 5.0)
    cap = 4
    rounds = 3
    server = _serve(max_connections=cap)
    port = server.server_address[1]
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=cap) as pool:
            results = list(pool.map(lambda _: _get_ok(port), range(cap * rounds)))
        assert results == [200] * (cap * rounds)
        _wait_until(lambda: server.available_slots == cap, "処理後に枠が返っていない")
    finally:
        server.shutdown()
        server.server_close()


def test_connection_slot_is_released_when_the_handler_thread_cannot_start(monkeypatch):
    """ハンドラスレッドの起動に失敗しても枠は返る。

    取った枠を例外経路で漏らすと、上限が片道で減って最後には全接続を拒否する
    (`process_request` の `except BaseException: release`)。
    """
    monkeypatch.setattr(app.Handler, "timeout", 5.0)
    cap = 2
    server = _serve(max_connections=cap)
    port = server.server_address[1]

    def _boom(self, request, client_address):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(socketserver.ThreadingMixIn, "process_request", _boom)
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        sock.settimeout(10)
        assert sock.recv(1) == b""  # 起動できないので応答せず閉じられる
        sock.close()
        _wait_until(lambda: server.available_slots == cap, "例外経路で枠が漏れている")
    finally:
        server.shutdown()
        server.server_close()
