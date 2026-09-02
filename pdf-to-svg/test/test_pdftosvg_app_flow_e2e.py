# =============================================================================
# test_pdftosvg_app_flow_e2e.py — 4 ステップ UI の通し E2E(旧 app_flow.e2e.ts の 1:1)
# =============================================================================
# 実 Python バックエンド(test/e2e_server.py)を子プロセスで起動し、Edge channel の
# 実ブラウザから叩く。旧 TS E2E(:5180)と並走できるよう別ポート(:5181)を使う。
# page は module スコープ共有(旧 TS はテスト毎に新規 page)だが、全テストが冒頭で
# goto するため JS realm は毎回作り直され、サーバ状態は resetSession が戻す — 等価。
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import expect

pytestmark = [pytest.mark.browser, pytest.mark.e2e]

PORT = 5181
TOKEN = "e2e-fixed-session-token"
BASE = f"http://127.0.0.1:{PORT}"
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.pdf")


@pytest.fixture(scope="module")
def e2e_server():
    env = dict(os.environ, PDFTOSVG_E2E_PORT=str(PORT))
    proc = subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(__file__), "e2e_server.py")],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(BASE + "/", timeout=1)
                break
            except urllib.error.HTTPError:
                break  # 4xx/5xx でも「サーバが応答した」= 起動完了
            except OSError:
                if proc.poll() is not None:
                    raise RuntimeError(proc.stderr.read().decode("utf-8", "replace"))
                time.sleep(0.2)
        else:
            raise RuntimeError("e2e server が起動しない")
        yield BASE
    finally:
        proc.kill()
        proc.wait()


@pytest.fixture(scope="module")
def e2e_page(e2e_server):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(base_url=e2e_server)
        yield page
        browser.close()


# サーバのセッション(開いている文書・Undo)はテスト間で共有される。各テストは自分が
# 前提とするファイル構成を作れるよう、先に読み込み済みの文書を空にする。
def reset_session(page):
    page.evaluate("""async () => {
        const w = window;
        for (let i = 0; i < 20; i++) {
            const st = await w.rpc("state");
            if (!st.files.length) return;
            await w.rpc("removeFile", { fileIndex: 0 });
        }
    }""")


def test_four_step_flow(e2e_page):
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)

    # ショートカットの発火を数えるため `rpc` を包む。押下ハンドラは同期に `rpc` を呼ぶので、
    # 押した直後に記録を見れば発火の有無が確定する。
    page.evaluate("""() => {
        const w = window;
        w.__rpcLog = [];
        const orig = w.rpc;
        w.rpc = function (method, args) { w.__rpcLog.push(method); return orig(method, args); };
    }""")
    # ファイルを 1 つも読み込んでいない間は文書のショートカットを撃たない
    page.keyboard.press("Control+z")
    assert page.evaluate("() => window.__rpcLog") == []

    # ── 1. PDF を選ぶ(動的 `<input type=file>` は filechooser イベントで受ける) ──
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(FIXTURE)
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル", timeout=30_000)

    # ── 2. 用語を置換(辞書タブ → 追加 → 再適用。ヘッダ・本文を問わず全文が対象) ──
    page.click("#btn-next")
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))
    page.click('[data-tab="dict"]')
    page.fill("#dict-src", "Revenue")
    page.fill("#dict-tgt", "売上高")
    page.click("#dict-add")
    expect(page.locator("#dict-count")).to_contain_text("1")
    # 辞書に語を足しただけで、その語に当たるページは「要確認」に上がる(再適用の前でも)
    expect(page.locator("#nav-hint")).to_contain_text("要確認 1")
    page.click("#btn-reapply")
    # 「N 件置換」ヒントは直後の render() が状態行で上書きするため文言では見ない。
    # 置換の成立は「要確認 1(changed 化)」とページ表示(書き出しと同一経路)で確認する。
    expect(page.locator("#nav-hint")).to_contain_text("要確認 1")
    expect(page.locator("#doc-master")).to_contain_text("売上高", timeout=15_000)

    # 箇所単位: 一覧の「戻す」で 1 件だけ置換前へ → 行は未置換(置換ボタン)になる → 「置換」で再び当たる
    page.click('[data-tab="confirm"]')
    rows = page.locator("#confirm-dyn .change-row")
    expect(rows.first.locator(".num")).to_have_text("1")
    # 番号マーカーは一覧の行数と同数だけページ上に描かれる
    expect(page.locator("#doc-master svg [data-editor-marks] > g")).to_have_count(rows.count())
    rows.first.locator(".act-revert").click()
    expect(page.locator("#doc-master")).to_contain_text("Revenue", timeout=15_000)
    expect(page.locator("#confirm-dyn")).to_contain_text("未置換 1 件")
    page.locator("#confirm-dyn .change-row").first.locator(".act-apply").click()
    expect(page.locator("#doc-master")).to_contain_text("売上高", timeout=15_000)
    expect(page.locator("#confirm-dyn")).not_to_contain_text("未置換")

    # 入力欄でのショートカットは文書の Undo を撃たない。辞書の語を打ち直そうと Ctrl+Z した
    # だけで直前の置換が消えると、消えたことに気付けないため。
    page.click('[data-tab="dict"]')
    page.click("#dict-src")
    page.evaluate("() => { window.__rpcLog.length = 0; }")
    page.press("#dict-src", "Control+z")
    page.press("#dict-src", "Control+y")
    assert page.evaluate("() => window.__rpcLog") == []

    # ── 3. 不要範囲を削除: 要素クリック選択 → 削除 → Undo → 再削除 ──
    page.click('[data-screen="2"] [data-skipall]')  # 未確認をまとめてスキップ → 手順3 へ
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
    target = page.locator('#trim-stage svg [data-el]', has_text="DeleteMe")
    target.click()
    page.click("#btn-deletesel")
    expect(page.locator("#trim-dyn")).to_contain_text("削除した要素（1）")
    page.click("#btn-undo")  # 直近の削除を取り消す
    expect(page.locator("#trim-dyn")).to_contain_text("削除した要素（0）")
    page.locator('#trim-stage svg [data-el]', has_text="DeleteMe").click()
    page.click("#btn-deletesel")
    expect(page.locator("#trim-dyn")).to_contain_text("削除した要素（1）")

    # 行ごとの「戻す」は直近の undo ではなく、その要素だけを戻す
    page.locator("#trim-dyn [data-restore]").first.click()
    expect(page.locator("#trim-dyn")).to_contain_text("削除した要素（0）")
    page.locator('#trim-stage svg [data-el]', has_text="DeleteMe").click()
    page.click("#btn-deletesel")
    expect(page.locator("#trim-dyn")).to_contain_text("削除した要素（1）")

    # ── 4. SVG に書き出す(1 ページ → 単一 SVG ダウンロード) ──
    page.click('[data-screen="3"] [data-skipall]')
    expect(page.locator("#btn-export")).to_be_visible()

    # 書き出しの失敗は握り潰さず通知し、ボタンを押せる状態へ戻す
    page.evaluate("""() => {
        const w = window;
        w.__origRpc = w.rpc;
        w.rpc = function (method, args) {
            if (method === "exportSvg") return Promise.reject(new Error("書き出し失敗テスト"));
            return w.__origRpc(method, args);
        };
    }""")
    page.click("#btn-export")
    expect(page.locator("#toast")).to_contain_text("書き出し失敗テスト")
    expect(page.locator("#btn-export")).to_be_enabled()
    page.evaluate("() => { window.rpc = window.__origRpc; }")

    with page.expect_download() as dl_info:
        page.click("#btn-export")
    download = dl_info.value
    assert re.search(r"\.svg$", download.suggested_filename, re.IGNORECASE)
    saved = download.path()
    svg_text = Path(saved).read_text(encoding="utf8")
    assert "売上高" in svg_text   # 置換が成果物へ反映されている
    assert "DeleteMe" not in svg_text  # 削除が成果物へ反映されている


def test_stale_page_fetch_does_not_break_current_page(e2e_page):
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)

    # 同じ PDF を 2 つ読み込み、ページ切替のある状態を作る
    for i in range(2):
        with page.expect_file_chooser() as fc_info:
            page.click("#btn-pick")
        fc_info.value.set_files(FIXTURE)
        expect(page.locator("#filelist-count")).to_contain_text(f"{i + 1} ファイル", timeout=30_000)

    page.click("#btn-next")
    page.click('[data-screen="2"] [data-skipall]')
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
    expect(page.locator("#trim-stage svg")).to_be_visible(timeout=30_000)

    # 2 ページ目の取得をわざと遅らせ、届く前に 1 ページ目へ戻る
    page.evaluate("""() => {
        const w = window;
        const orig = w.rpc;
        w.rpc = async function (method, args) {
            const r = await orig(method, args);
            if (method === "pageSvg") await new Promise((done) => setTimeout(done, 1500));
            return r;
        };
    }""")
    page.locator('#pagenav-3 .pg-row2[data-g="1"]').click()
    page.locator('#pagenav-3 .pg-row2[data-g="0"]').click()
    page.wait_for_timeout(2500)  # 遅らせた 2 ページ目の応答が届くまで待つ

    # 遅れて届いた分でクリック配線が二重にならない(1 回のクリックで 1 件だけ選択される)
    page.locator('#trim-stage svg [data-el]', has_text="DeleteMe").click()
    expect(page.locator("#trim-stage .sel-box")).to_have_count(1)


def test_partial_load_failure_keeps_succeeded_files(e2e_page):
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)

    # 2 つ目が壊れた PDF。握り潰すと「選んだのに増えない」になるので理由を出す。
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files([
        {"name": "sample.pdf", "mimeType": "application/pdf", "buffer": Path(FIXTURE).read_bytes()},
        {"name": "broken.pdf", "mimeType": "application/pdf", "buffer": b"not a pdf"},
    ])
    expect(page.locator("#toast")).to_contain_text("broken.pdf", timeout=30_000)
    # 成功した分は取り込まれている
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル")


def test_load_failure_in_the_middle_does_not_skip_later_files(e2e_page):
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)

    # 真ん中が壊れた PDF。1 件の失敗で後続まで止めると、利用者は「後ろのファイルは
    # 選んだのに増えない」理由を受け取れない。失敗分だけ通知し、残りは取り込む。
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files([
        {"name": "first.pdf", "mimeType": "application/pdf", "buffer": Path(FIXTURE).read_bytes()},
        {"name": "broken.pdf", "mimeType": "application/pdf", "buffer": b"not a pdf"},
        {"name": "last.pdf", "mimeType": "application/pdf", "buffer": Path(FIXTURE).read_bytes()},
    ])
    expect(page.locator("#toast")).to_contain_text("broken.pdf", timeout=30_000)
    expect(page.locator("#filelist-count")).to_contain_text("2 ファイル")
    expect(page.locator("#file-cards")).to_contain_text("last.pdf")


def test_list_fetch_failure_clears_rows_and_offers_retry(e2e_page):
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)

    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(FIXTURE)
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル", timeout=30_000)

    # 変更の一覧を出すために辞書へ 1 語入れる
    page.click("#btn-next")
    page.click('[data-tab="dict"]')
    page.fill("#dict-src", "Revenue")
    page.fill("#dict-tgt", "売上高")
    page.click("#dict-add")
    page.click('[data-tab="confirm"]')
    expect(page.locator("#confirm-dyn .change-row")).to_have_count(1)

    # 指定した RPC だけを失敗させる差し替え
    def break_rpc(method):
        page.evaluate("""(m) => {
            const w = window;
            w.__origRpc = w.__origRpc || w.rpc;
            w.rpc = function (name, args) {
                if (name === m) return Promise.reject(new Error("取得テスト失敗"));
                return w.__origRpc(name, args);
            };
        }""", method)

    def heal_rpc():
        page.evaluate("() => { window.rpc = window.__origRpc; }")

    break_rpc("planPage")
    page.locator('#pagenav .pg-row2[data-g="0"]').click()
    expect(page.locator("#confirm-dyn")).to_contain_text("取得できませんでした")
    expect(page.locator("#confirm-dyn .change-row")).to_have_count(0)
    heal_rpc()
    page.click("#confirm-dyn [data-retry]")
    expect(page.locator("#confirm-dyn .change-row")).to_have_count(1)

    page.click('[data-screen="2"] [data-skipall]')
    expect(page.locator("#trim-dyn")).to_contain_text("削除した要素（0）")
    break_rpc("removedList")
    page.locator('#pagenav-3 .pg-row2[data-g="0"]').click()
    expect(page.locator("#trim-dyn")).to_contain_text("取得できませんでした")
    heal_rpc()
    page.click("#trim-dyn [data-retry]")
    expect(page.locator("#trim-dyn")).to_contain_text("削除した要素（0）")
