# =============================================================================
# conftest.py — graph-editor pytest の共有 fixtures
# =============================================================================
# 静的サーバは pdf-to-svg/test/conftest.py のコピー流用（設計書 §6 の道具複製枠。改善は
# コピー元と相互反映する）。graph-editor 固有:
# - playwright は単一の session Browser（edge_browser）へ括り出す。単体（edge_page）と
#   E2E（e2e_page）が同じ Browser を共有し、sync_playwright の二重起動を作らない。
# - CDP precise coverage は「goto 完了後・モジュール読込前」に開始する（設計書 §4.3。
#   goto より前に張ると renderer の process swap で Profiler 状態を失うことがあり、
#   読込後に張ると読込済みスクリプトを取りこぼす）。
import functools
import http.server
import os
import threading

import pytest

WEB_ROOT = os.path.join(os.path.dirname(__file__), "..", "resources", "web")


class _QuietStaticHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        # 既定の guess_type は .cjs を知らず octet-stream になる(editor_server.py と同じ理由。
        # 本ハンドラは nosniff を出していないため今のところ動いているだけで、
        # 送出ヘッダを変えても壊れないよう対称に揃えておく)。
        ".cjs": "text/javascript",
        ".js": "text/javascript",
        ".mjs": "text/javascript",
    }

    def log_message(self, *args):
        pass


@pytest.fixture(scope="session")
def web_root_url():
    """`resources/web` を配信する静的サーバ。ES module は URL 経由で読み込む
    （インライン埋込だと CDP カバレッジの scriptCoverage.url が空になるため）。

    ポート 0 を `ThreadingHTTPServer` へ直接束縛し OS に選定させる（空きポートを
    先に probe してから同じ番号で再バインドする方式は、probe のクローズと実バインドの
    間に他プロセスが同じポートを奪える TOCTOU を持つ）。"""
    handler = functools.partial(_QuietStaticHandler, directory=os.path.abspath(WEB_ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()


@pytest.fixture(scope="session")
def edge_browser():
    """Edge channel（端末既存の Edge・追加ダウンロード無し）の共有 Browser。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        yield browser
        browser.close()


@pytest.fixture(scope="session")
def edge_page(edge_browser, web_root_url):
    """単体移植用の共有ページ。

    blank ページ（存在しないパス = 404 応答）を開く: index.html を開くと app.js が
    静的 import した同一モジュールインスタンス（シングルトン `S`）を共有してしまい、
    稼働中 app の /rpc 失敗処理・/ping ハートビートがテスト状態を汚すため。
    404 の文書でも origin は静的サーバなので dynamic import は同じ URL 空間で解決する
    （pdf-to-svg 側 conftest と同じ理由）。"""
    page = edge_browser.new_page()
    page.goto(web_root_url + "/__pytest_blank__")
    cdp = page.context.new_cdp_session(page)
    cdp.send("Profiler.enable")
    cdp.send("Profiler.startPreciseCoverage", {"callCount": True, "detailed": True})
    page._grapheditor_cdp = cdp
    yield page
    page.close()


class _CoverageCollector:
    """CDP precise coverage の取り出し口。ゲートテスト（カバレッジ判定）が消費する。"""

    def __init__(self, cdp):
        self._cdp = cdp

    def take(self):
        return self._cdp.send("Profiler.takePreciseCoverage")["result"]


@pytest.fixture(scope="session")
def coverage_collector(edge_page):
    return _CoverageCollector(edge_page._grapheditor_cdp)


# ── E2E fixtures（editor_server.py を子プロセスで起動。単体の web_root_url とは別サーバ）──


@pytest.fixture(scope="session")
def e2e_server():
    """editor_server.py を子プロセスで起動し、stdout の 1 行目から実ポートを得る。
    readline は起動失敗時に無限待ちになるため、番犬タイマーでプロセスを落として抜ける。
    stderr はパイプで拾い(黙って捨てない)、起動行が読めなかった場合の assert メッセージへ
    先頭を添える。try/finally は fixture 本体全体を覆い、いずれの assert 失敗時も
    子プロセスを確実に kill する。"""
    import re
    import subprocess
    import sys
    import urllib.request

    proc = subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(__file__), "editor_server.py")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        watchdog = threading.Timer(15, proc.kill)
        watchdog.start()
        try:
            line = proc.stdout.readline()
        finally:
            watchdog.cancel()
        m = re.search(r"http://127\.0\.0\.1:(\d+)/", line or "")
        if not m:
            proc.kill()
            stderr_head = (proc.stderr.read() or "")[:2000]
            assert m, f"サーバの起動行が読めない: {line!r} / stderr 先頭: {stderr_head!r}"
        base = f"http://127.0.0.1:{m.group(1)}"
        with urllib.request.urlopen(base + "/ui.html", timeout=5) as res:
            assert res.headers.get("Content-Security-Policy"), "防御ヘッダが載っていない"
            assert res.headers.get("X-Content-Type-Options") == "nosniff"
        yield base
    finally:
        proc.kill()
        proc.wait()


@pytest.fixture
def e2e_page(edge_browser, e2e_server):
    """E2E 用のページ。**テストごとに context から作り直す**（旧 TS の per-test page と
    同型。page.route のパッチ・dialog リスナ・viewport 変更をテスト間に持ち越さない）。"""
    context = edge_browser.new_context(base_url=e2e_server)
    page = context.new_page()
    yield page
    context.close()
