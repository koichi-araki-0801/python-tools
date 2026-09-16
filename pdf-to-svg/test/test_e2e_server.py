# =============================================================================
# test_e2e_server.py — E2E 用サーバの起動待ち合わせ (`e2e_server` の
# `ensure_port_is_free` / `wait_until_serving`)
# =============================================================================
# E2E はテスト用サーバを固定ポートで起動する。既に別のサーバが同じポートで動いていると、
# 2 つのテスト実行が 1 つのサーバを黙って共有して互いの文書を消し合う。起動後に子プロセスの
# 応答や生死だけを見ても検知できない: Windows では `ThreadingHTTPServer` の既定
# `allow_reuse_address` (`SO_REUSEADDR`) により LISTEN 中のポートへの二重 bind が成功するため、
# 後発の子は死なずに起動してしまう。そこで起動する**前**に応答の有無で見る。
import http.server
import os
import subprocess
import sys
import threading

import pytest

from .e2e_server import ensure_port_is_free, wait_until_serving


class _Occupier(http.server.BaseHTTPRequestHandler):
    """ポートを先に取って 200 を返すだけのサーバ (別の E2E が走っている状況の代わり)。"""

    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_ensure_port_is_free_fails_when_another_server_already_holds_the_port():
    """先にポートを占有するサーバがいると、起動前の確認で RuntimeError になる。

    Windows では SO_REUSEADDR により二重 bind が成功して子が死なないため、起動後に子の生死を見る
    方法では検知できない。起動前に応答の有無で見る。
    """
    occupier = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Occupier)
    port = occupier.server_address[1]
    threading.Thread(target=occupier.serve_forever, daemon=True).start()
    try:
        with pytest.raises(RuntimeError, match="別のサーバが既に応答している"):
            ensure_port_is_free(f"http://127.0.0.1:{port}")
    finally:
        occupier.shutdown()
        occupier.server_close()


def test_wait_until_serving_returns_when_the_child_itself_is_serving():
    """ポートが空いていれば子が起動し、応答した時点で戻る (子は生きている)。"""
    # 空きポートを OS から借りて、閉じた直後に子へ渡す (probe と bind の間に他プロセスが奪う
    # 可能性は残るが、テストとしては十分低い)
    probe = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Occupier)
    port = probe.server_address[1]
    probe.server_close()
    env = dict(os.environ, PDFTOSVG_E2E_PORT=str(port))
    proc = subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(__file__), "e2e_server.py")],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        wait_until_serving(proc, f"http://127.0.0.1:{port}")  # 例外が出ないこと
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()
