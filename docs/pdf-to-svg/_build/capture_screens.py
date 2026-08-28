# -*- coding: utf-8 -*-
"""PdfToSvg 操作手順書向けの実機スクリーンショット自動取得ハーネス。

`pdf-to-svg/src/web/server.py` の `create_server()` を直接起動し（`app.py` の Edge 起動・
60 秒アイドル watchdog を経由しないので撮影中にサーバが落ちない）、Playwright(chromium) で
4 ステップの実画面を撮影して `docs/pdf-to-svg/images/` に PNG 出力する。

- 入力 PDF: `tests/fixtures/vector_sample.pdf`（"Header A" / "Value 123"）
- 辞書は一時ファイルに作り「Header A → 見出し A」を投入（本番 data/dictionary.json は汚さない）
- ファイル選択は File System Access API を無効化し、隠し <input type=file> 経由で set_files
"""
from __future__ import annotations

import pathlib
import sys
import tempfile
import threading
import time

# リポジトリルートからの相対解決 (このファイルは <repo>/docs/pdf-to-svg/_build/ にある)。
REPO = pathlib.Path(__file__).resolve().parents[3]
ROOT = REPO / "pdf-to-svg"
sys.path.insert(0, str(ROOT / "src"))
# 共通撮影ヘルパ (docs/_build/shot.py)。launch/コンテキスト/解像度規約を集約。
sys.path.insert(0, str(REPO / "docs" / "_build"))

import shot as shot_helper  # noqa: E402
from dictionary.store import DictionaryStore  # noqa: E402
from web.rpc_methods import WebSession  # noqa: E402
from web.server import create_server  # noqa: E402
from web.undo_stack import UndoStack  # noqa: E402

OUT = REPO / "docs" / "pdf-to-svg" / "images"
OUT.mkdir(parents=True, exist_ok=True)
SAMPLE = ROOT / "tests" / "fixtures" / "vector_sample.pdf"


def start_server():
    """一時辞書を仕込んだ WebSession でローカルサーバを起動し (server, url) を返す。"""
    tmpdir = tempfile.mkdtemp(prefix="pdftosvg-shots-")
    store = DictionaryStore(pathlib.Path(tmpdir) / "dictionary.json")
    store.add("Header A", "見出し A")  # ステップ2で実際の置換を見せるための種
    session = WebSession(store, UndoStack())
    server = create_server(str(ROOT / "resources" / "web"), session)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{port}/"


def shot(page, name):
    path = OUT / name
    page.screenshot(path=str(path))
    print("  saved", path.name)


def skip_guard_if_present(page):
    """未確認ガードバーが出ていたら「未確認をすべてスキップして進む」を押す。"""
    try:
        if page.is_visible("#guard"):
            page.click("#guard-skip")
            return True
    except Exception:
        pass
    return False


def main():
    server, url = start_server()
    print("server:", url)
    try:
        # ローカル HTTP サーバ（start_server）の実画面を撮影するため http: の取得が要る。
        # allowed_schemes=None を明示し、意図的な素通しであることを示す。
        with shot_helper.chromium() as browser, \
                shot_helper.page_context(browser, 1280, 880, allowed_schemes=None) as page:
            # File System Access API を消し、隠し <input type=file> フォールバックへ。
            page.add_init_script(
                "delete window.showOpenFilePicker;"
                "delete window.showSaveFilePicker;"
                "delete window.showDirectoryPicker;"
            )
            page.goto(url)
            page.wait_for_selector("#btn-pick")

            # ---- ステップ1: PDF を選ぶ ----
            with page.expect_file_chooser() as fc:
                page.click("#btn-pick")
            fc.value.set_files(str(SAMPLE))
            page.wait_for_selector("#file-cards .file-card", timeout=15000)
            time.sleep(0.6)
            shot(page, "step1_select.png")

            # ---- ステップ2: 用語を置換（確認タブ）----
            page.click("#btn-next")
            page.wait_for_selector('.screen[data-screen="2"].on', timeout=10000)
            page.wait_for_selector("#doc-master svg", timeout=15000)
            time.sleep(1.0)
            shot(page, "step2_replace.png")

            # ---- ステップ2(辞書タブ) ----
            page.click('[data-tab="dict"]')
            page.wait_for_selector('[data-pane="dict"].on', timeout=5000)
            time.sleep(0.5)
            shot(page, "step2b_dict.png")
            # 辞書共有ボタン (JSON書き出し/読み込み) の拡大。8章「辞書の共有」用。
            page.locator('[data-pane="dict"] .panel-foot').screenshot(
                path=str(OUT / "step2c_dict_share.png")
            )
            print("  saved step2c_dict_share.png")
            page.click('[data-tab="confirm"]')  # 確認タブに戻す

            # ---- 未確認ガードバー (ステップ2で未確認のまま「次へ」) ----
            page.click("#btn-next")
            if page.is_visible("#guard"):
                time.sleep(0.4)
                shot(page, "step2d_guard.png")
            skip_guard_if_present(page)

            # ---- ステップ3: 削除・枠線の編集 ----
            page.wait_for_selector('.screen[data-screen="3"].on', timeout=10000)
            page.wait_for_selector("#trim-stage svg", timeout=15000)
            time.sleep(1.0)
            shot(page, "step3_edit.png")

            # ---- ステップ3: 範囲削除 (ドラッグ中のラバーバンド) ----
            # 先に範囲削除を撮る (枠線を先に撮って Ctrl+Z すると、取り消した枠線が
            # 「削除した要素」一覧に残骸として写り込むため)。
            stage = page.locator("#trim-stage svg").bounding_box()
            page.click('[data-tool="crop"]')
            page.mouse.move(stage["x"] + stage["width"] * 0.2, stage["y"] + stage["height"] * 0.15)
            page.mouse.down()
            page.mouse.move(stage["x"] + stage["width"] * 0.7, stage["y"] + stage["height"] * 0.5, steps=8)
            time.sleep(0.3)
            shot(page, "step3c_region.png")
            page.mouse.up()
            time.sleep(0.5)
            page.keyboard.press("Control+z")  # 範囲削除を取り消す (要素が全て戻る)
            time.sleep(0.5)

            # ---- ステップ3: 枠線の追加 (ドラッグで矩形を引いた直後) ----
            page.click('[data-tool="border"]')
            page.mouse.move(stage["x"] + stage["width"] * 0.25, stage["y"] + stage["height"] * 0.2)
            page.mouse.down()
            page.mouse.move(stage["x"] + stage["width"] * 0.75, stage["y"] + stage["height"] * 0.45, steps=8)
            page.mouse.up()
            time.sleep(0.8)
            shot(page, "step3b_border.png")
            page.keyboard.press("Control+z")  # 枠線を取り消す
            time.sleep(0.5)
            page.click('[data-tool="select"]')

            # ---- ステップ4: SVG に書き出す ----
            page.click("#btn-next")
            skip_guard_if_present(page)
            page.wait_for_selector('.screen[data-screen="4"].on', timeout=10000)
            time.sleep(0.6)
            shot(page, "step4_export.png")
    finally:
        server.shutdown()
        server.server_close()
    print("done.")


if __name__ == "__main__":
    main()
