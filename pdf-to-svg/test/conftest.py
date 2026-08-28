"""pytest 共有フィクスチャ。テスト用 PDF を `fitz` で動的生成して `fixtures/` に置く。

ベクタ/バナー/擬似スキャンの 3 種を session スコープで提供し、`engine` や
`export` 層のテストへ渡す。
"""
import functools
import http.server
import os
import threading
from pathlib import Path

import fitz
import pytest

# GUI を伴うテストはオフスクリーンで実行 (`QT_QPA_PLATFORM=offscreen`)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def vector_pdf() -> Path:
    """テキスト・線・塗り矩形を含むベクタ PDF。`load_document` の基本経路を覆う。"""
    FIXTURES.mkdir(exist_ok=True)
    path = FIXTURES / "vector_sample.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((50, 50), "Header A", fontsize=14, color=(0, 0, 0))
    page.insert_text((50, 80), "Value 123", fontsize=11, color=(0.2, 0.2, 0.8))
    page.draw_line((40, 100), (260, 100), color=(0, 0, 0), width=1.5)
    page.draw_rect(fitz.Rect(40, 120, 260, 170), color=(0, 0, 0), fill=(0.9, 0.9, 0.9), width=1)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture(scope="session")
def banner_pdf() -> Path:
    """グレー帯 (塗り矩形) を先に描き、その上へ白文字を載せた報告書風 PDF。"""
    FIXTURES.mkdir(exist_ok=True)
    path = FIXTURES / "banner_sample.pdf"
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.draw_rect(fitz.Rect(50, 40, 250, 70), color=None, fill=(0.6, 0.6, 0.6))
    page.insert_text((90, 60), "WHITE TITLE", fontsize=14, color=(1, 1, 1))
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture(scope="session")
def scanned_pdf() -> Path:
    """テキストを持たず、ページ全面を画像が覆う擬似スキャン PDF。"""
    FIXTURES.mkdir(exist_ok=True)
    path = FIXTURES / "scanned_sample.pdf"

    # 背景画像を生成 (別ドキュメントを `get_pixmap` でラスタ化)
    tmp = fitz.open()
    tp = tmp.new_page(width=200, height=200)
    tp.insert_text((30, 60), "SCANNED", fontsize=20)
    pix = tp.get_pixmap(matrix=fitz.Matrix(2, 2))
    img_bytes = pix.tobytes("png")
    tmp.close()

    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    page.insert_image(fitz.Rect(0, 0, 200, 200), stream=img_bytes)
    doc.save(str(path))
    doc.close()
    return path


# ── JS 単体・E2E 移植用ハーネス（設計書 §4.2。graph-editor 側フェーズ 3 がコピーして流用）──

WEB_ROOT = os.path.join(os.path.dirname(__file__), "..", "resources", "web")


class _QuietStaticHandler(http.server.SimpleHTTPRequestHandler):
    """アクセスログを抑制する静的配信ハンドラ（テスト出力を汚さないため）。"""

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
def edge_page(web_root_url):
    """Edge channel（端末既存の Edge・追加ダウンロード無し）の共有ページ。

    blank ページ（存在しないパス = 404 応答）を開く: index.html を開くと app.js が
    静的 import した同一モジュールインスタンス（シングルトン `S`）を共有してしまい、
    稼働中 app の /rpc 失敗処理・/ping ハートビートがテスト状態を汚すため。
    404 の文書でも origin は静的サーバなので dynamic import は同じ URL 空間で解決する。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        page.goto(web_root_url + "/__pytest_blank__")
        yield page
        browser.close()
