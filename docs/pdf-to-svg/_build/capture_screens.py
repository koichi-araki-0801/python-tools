# -*- coding: utf-8 -*-
"""PdfToSvg 操作手順書向けの実機スクリーンショット自動取得ハーネス。

`pdf-to-svg/src/web/server.py` の `create_server()` を直接起動し（`app.py` の Edge 起動・
60 秒アイドル watchdog を経由しないので撮影中にサーバが落ちない）、Playwright(chromium) で
4 ステップの実画面を撮影して `docs/pdf-to-svg/images/` に PNG 出力する。

- 入力 PDF (色モード): `test/fixtures/vector_sample.pdf`（"Header A" / "Value 123"）。
  無ければ `test/conftest.py::vector_pdf` と同じ fitz コードでその場で生成する
  （pytest を先に走らせる前提を作らないため）。
- 入力 PDF (グレーモード): `test/test_pdftosvg_app_flow_e2e.py::stewardship_pdf` と同じ
  fitz コードで一時ディレクトリへその場で生成する（コミットしない）。
- 辞書は一時ファイルに作り「Header A → 見出し A」を投入（本番 data/dictionary.json は汚さない）
- ファイル選択は File System Access API を無効化し、隠し <input type=file> 経由で set_files
- 出力 PNG: 色モード = step1_select / step2_replace / step2b_dict / step2c_dict_share /
  step2d_guard / step3_edit / step3c_region / step3b_border / step4_export。
  グレーモード = step1b_gray_check（チェック ON + 手順 2・3 省略の注記）/
  step4b_gray_figure（3 ペインの図の選択画面）/ step4c_gray_panel（右ペインの拡大）。
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

import fitz  # noqa: E402

import shot as shot_helper  # noqa: E402
from dictionary.store import DictionaryStore  # noqa: E402
from web.rpc_methods import WebSession  # noqa: E402
from web.server import create_server  # noqa: E402
from web.undo_stack import UndoStack  # noqa: E402

OUT = REPO / "docs" / "pdf-to-svg" / "images"
OUT.mkdir(parents=True, exist_ok=True)
# 実体は pdf-to-svg/test/fixtures/ (tests/ ではない)。pytest 未実行の環境でも撮影できるよう
# 無ければ ensure_vector_sample() がその場で作る。
SAMPLE = ROOT / "test" / "fixtures" / "vector_sample.pdf"


def ensure_vector_sample() -> None:
    """`SAMPLE` が無ければ `test/conftest.py::vector_pdf` と同じ fitz コードで生成する。
    既に pytest 実行済みで存在する場合はそのまま使い回す（session フィクスチャの内容と
    同一なので撮影結果に差は出ない）。"""
    if SAMPLE.exists():
        return
    SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=300, height=200)
    page.insert_text((50, 50), "Header A", fontsize=14, color=(0, 0, 0))
    page.insert_text((50, 80), "Value 123", fontsize=11, color=(0.2, 0.2, 0.8))
    page.draw_line((40, 100), (260, 100), color=(0, 0, 0), width=1.5)
    page.draw_rect(fitz.Rect(40, 120, 260, 170), color=(0, 0, 0), fill=(0.9, 0.9, 0.9), width=1)
    doc.save(str(SAMPLE))
    doc.close()


def build_stewardship_pdf(tmpdir: str) -> pathlib.Path:
    """`test_pdftosvg_app_flow_e2e.py::stewardship_pdf` と同じ fitz コードで、実 PDF を
    模した合成 2 ページを一時ディレクトリへ生成する（コミットしない）。1 ページ目は図の
    無い見出し・本文のみ、2 ページ目に図（見出し・本文・帯・曲線・ラベル・QR 枠）を置き、
    グレーモードの全ページ検出→自動移動を見せる（図が最初のページではない構成）。"""
    path = pathlib.Path(tmpdir) / "stewardship_sample.pdf"
    doc = fitz.open()

    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((43, 150), "（2）運用経過", fontname="japan", fontsize=11)
    page1.insert_text(
        (43, 175),
        "当期のファンドは国内外の株式市場の上昇を背景に、基準価額は堅調に推移しました。",
        fontname="japan", fontsize=8,
    )

    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((43, 150), "（3）当社のスチュワードシップ活動", fontname="japan", fontsize=11)
    page2.insert_text(
        (43, 175),
        "当社は「責任ある機関投資家」として、エンゲージメント、議決権行使、投資の意思決定における"
        "ESGの考慮を3つの柱として",
        fontname="japan", fontsize=8,
    )
    page2.draw_rect(fitz.Rect(113, 249, 483, 284), color=None, fill=(0, 0.62, 0.71))
    page2.insert_text((224, 275), "投資リターンの最大化", fontname="japan", fontsize=13, color=(1, 1, 1))
    shape = page2.new_shape()
    shape.draw_bezier((220, 330), (300, 300), (330, 480), (400, 490))
    shape.finish(color=(0.8, 0.2, 0.3), width=6)
    shape.commit()
    page2.insert_text((85, 478), "エンゲージメント", fontname="japan", fontsize=9, color=(0.85, 0.55, 0.1))
    page2.insert_text((430, 354), "議決権行使", fontname="japan", fontsize=9, color=(0.2, 0.6, 0.3))
    page2.insert_text((104, 366), "におけるESGの考慮", fontname="japan", fontsize=9, color=(0.8, 0.2, 0.3))
    page2.draw_rect(fitz.Rect(113, 526, 483, 596), color=None, fill=(0, 0.62, 0.71))
    page2.insert_text(
        (162, 574), "［フィデューシャリー・デューティーの実践］", fontname="japan", fontsize=9, color=(1, 1, 1),
    )
    page2.draw_rect(fitz.Rect(113, 600, 483, 650), color=(0, 0, 0), width=0.8)
    page2.insert_text((190, 640), "https://www.smtam.jp/institutional/stewardship_initiatives/", fontsize=8)
    page2.insert_text((43, 700), "（4）自社ESGスコアについて", fontname="japan", fontsize=11)

    doc.save(str(path))
    doc.close()
    return path


def start_server():
    """一時辞書を仕込んだ WebSession でローカルサーバを起動し (server, url) を返す。
    `url` には起動時発行のセッショントークンを `?token=` で載せる（`rpc.js` が
    `window.location.search` から読むのはここだけなので、無いと非安全メソッドが
    origin_guard に全拒否される）。"""
    tmpdir = tempfile.mkdtemp(prefix="pdftosvg-shots-")
    store = DictionaryStore(pathlib.Path(tmpdir) / "dictionary.json")
    store.add("Header A", "見出し A")  # ステップ2で実際の置換を見せるための種
    session = WebSession(store, UndoStack())
    server = create_server(str(ROOT / "resources" / "web"), session)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{port}/?token={server.guard_token}"


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


def clear_session_files(page):
    """サーバ側セッションに残っているファイルを rpc で 1 件ずつ外す。サーバは色モード撮影
    (main) と共有しており `vector_sample.pdf` が読み込まれたままなので、グレーモード撮影の
    前に空へ戻す（E2E `test_pdftosvg_app_flow_e2e.py::reset_session` と同じ手当て）。"""
    page.evaluate("""async () => {
        const w = window;
        for (let i = 0; i < 20; i++) {
            const st = await w.rpc("state");
            if (!st.files.length) return;
            await w.rpc("removeFile", { fileIndex: 0 });
        }
    }""")


def capture_gray(browser, url, sample_pdf):
    """グレーモード（「図だけをグレースケールで書き出す」）の撮影。色モードと同じサーバを
    使い回すブラウザ新規ページで、チェック ON → ファイル選択 → 手順 4 の図の選択画面まで
    進めて撮る。"""
    with shot_helper.page_context(browser, 1280, 880, allowed_schemes=None) as page:
        page.add_init_script(
            "delete window.showOpenFilePicker;"
            "delete window.showSaveFilePicker;"
            "delete window.showDirectoryPicker;"
        )
        page.goto(url)
        page.wait_for_selector("#btn-pick")
        clear_session_files(page)

        # ---- ステップ1: グレーモードのチェックを ON にしてから PDF を選ぶ ----
        page.check("#chk-gray")
        page.wait_for_selector("#gray-skipnote")  # 「手順 2・3 は省略されます」の注記
        with page.expect_file_chooser() as fc:
            page.click("#btn-pick")
        fc.value.set_files(str(sample_pdf))
        page.wait_for_selector("#file-cards .file-card", timeout=15000)
        time.sleep(0.6)
        shot(page, "step1b_gray_check.png")

        # ---- ステップ4: 図の選択画面 (ON のため 2・3 は自動で飛ばされる) ----
        page.click("#btn-next")
        page.wait_for_selector('.screen[data-screen="4"].on', timeout=10000)
        # 全ページ自動検出 + 最初に見つかったページへの自動移動が終わるのを、
        # 非空虚な条件 (#exp-num が "1") と採用済み候補の出現で確認する。CSP
        # (`default-src 'self'`) が `unsafe-eval` を禁じるため `wait_for_function` は
        # 使えず、Playwright 自前のセレクタエンジンで完結する `:text-is()` で待つ。
        page.wait_for_selector('#exp-num:text-is("1")', timeout=15000)
        page.wait_for_selector("#fig-stage .fig-cand.sel", timeout=15000)
        time.sleep(0.8)
        shot(page, "step4b_gray_figure.png")

        # ---- 右ペイン (採用した図の一覧・書き出し) の拡大 ----
        page.locator("#export-center").screenshot(path=str(OUT / "step4c_gray_panel.png"))
        print("  saved step4c_gray_panel.png")


def main():
    ensure_vector_sample()
    server, url = start_server()
    print("server:", url)
    gray_tmpdir = tempfile.mkdtemp(prefix="pdftosvg-shots-gray-")
    stewardship_pdf = build_stewardship_pdf(gray_tmpdir)
    try:
        # ローカル HTTP サーバ（start_server）の実画面を撮影するため http: の取得が要る。
        # allowed_schemes=None を明示し、意図的な素通しであることを示す。
        with shot_helper.chromium() as browser:
            with shot_helper.page_context(browser, 1280, 880, allowed_schemes=None) as page:
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

            # ---- グレーモード (別ページで同じサーバ・ブラウザを使い回す) ----
            capture_gray(browser, url, stewardship_pdf)
    finally:
        server.shutdown()
        server.server_close()
    print("done.")


if __name__ == "__main__":
    main()
