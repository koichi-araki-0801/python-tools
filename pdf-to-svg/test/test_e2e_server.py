# =============================================================================
# test_e2e_server.py — E2E 用サーバの起動 (ポート 0 → 実ポートをファイルで受け渡す) と待ち合わせ
# =============================================================================
# E2E はテスト用サーバをポート 0 で起動し、OS が選んだ実ポートを子プロセスがファイルへ書き、
# fixture がその出現を待って読む。固定ポートだと 2 本並走したときに混線する (Windows では
# SO_REUSEADDR で二重 bind が成功し、接続がどちらへ届くか不定になる) ため、毎回違うポートに
# して衝突そのものを無くす。ここでは、ファイルに実ポートが書かれてそのポートで応答すること、
# 子が起動前に死んだら stderr 付きで止まることを確かめる。
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from .e2e_server import wait_for_port_file, wait_until_serving


def _spawn(port_file: Path, *, port: str = "0") -> subprocess.Popen:
    env = dict(os.environ, PDFTOSVG_E2E_PORT=port, PDFTOSVG_E2E_PORT_FILE=str(port_file))
    return subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(__file__), "e2e_server.py")],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def test_port_zero_writes_the_actual_port_to_the_file_and_serves_there():
    """ポート 0 で起動すると、OS が選んだ実ポートがファイルへ書かれ、そのポートで応答する。"""
    with tempfile.TemporaryDirectory() as tmp:
        port_file = Path(tmp) / "port"
        proc = _spawn(port_file)
        try:
            port = wait_for_port_file(port_file, proc)
            assert 1024 <= port <= 65535
            wait_until_serving(proc, f"http://127.0.0.1:{port}")  # 例外が出ないこと
            assert proc.poll() is None
        finally:
            proc.kill()
            proc.wait()


def test_two_servers_started_at_once_get_different_ports():
    """2 本同時に起動しても別のポートになる (並走で混線しない根拠)。"""
    with tempfile.TemporaryDirectory() as tmp:
        f1, f2 = Path(tmp) / "p1", Path(tmp) / "p2"
        p1, p2 = _spawn(f1), _spawn(f2)
        try:
            port1 = wait_for_port_file(f1, p1)
            port2 = wait_for_port_file(f2, p2)
            assert port1 != port2
        finally:
            for p in (p1, p2):
                p.kill()
                p.wait()


def test_wait_for_port_file_fails_when_the_child_dies_before_writing():
    """子が起動前に死んだら (ここでは不正なポート指定で bind に失敗させる)、待ち続けずに
    stderr を添えて RuntimeError になる。"""
    with tempfile.TemporaryDirectory() as tmp:
        port_file = Path(tmp) / "port"
        proc = _spawn(port_file, port="99999")  # 範囲外 → bind で OverflowError
        try:
            with pytest.raises(RuntimeError, match="起動前に終了"):
                wait_for_port_file(port_file, proc, timeout=15.0)
        finally:
            proc.kill()
            proc.wait()
