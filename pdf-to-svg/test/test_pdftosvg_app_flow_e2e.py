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
import zipfile
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

    # グレーモード専用のペインは色モードでは描かれない (hidden が .editor/.segment の display に負けない)
    expect(page.locator("#fig-editor")).to_be_hidden()
    expect(page.locator("#exp-modes-gray")).to_be_hidden()
    expect(page.locator("#pagenav-4")).to_be_hidden()
    # ファイル名の案内は色モードの文言のまま (グレーモード専用の _fig1_gray. にならない)
    expect(page.locator("#exp-name-hint")).to_contain_text("_p1.svg")

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


FIG_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "stewardship_sample.pdf")


@pytest.fixture(scope="module")
def stewardship_pdf():
    """実 PDF を模した合成 2 ページ。1 ページ目は図の無い見出し・本文のみ、2 ページ目に
    図 (見出し・本文・帯・曲線・ラベル・QR 枠) を置く。全ページ検出→自動移動を検証するため、
    図が「最初のページではない」構成にする。外部著作物は使わない。"""
    import fitz

    doc = fitz.open()

    page1 = doc.new_page(width=595, height=842)
    page1.insert_text((43, 150), "（2）運用経過", fontname="japan", fontsize=11)
    page1.insert_text((43, 175), "当期のファンドは国内外の株式市場の上昇を背景に、基準価額は堅調に推移しました。", fontname="japan", fontsize=8)

    page2 = doc.new_page(width=595, height=842)
    page2.insert_text((43, 150), "（3）当社のスチュワードシップ活動", fontname="japan", fontsize=11)
    page2.insert_text((43, 175), "当社は「責任ある機関投資家」として、エンゲージメント、議決権行使、投資の意思決定におけるESGの考慮を3つの柱として", fontname="japan", fontsize=8)
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
    page2.insert_text((162, 574), "［フィデューシャリー・デューティーの実践］", fontname="japan", fontsize=9, color=(1, 1, 1))
    page2.draw_rect(fitz.Rect(113, 600, 483, 650), color=(0, 0, 0), width=0.8)
    page2.insert_text((190, 640), "https://www.smtam.jp/institutional/stewardship_initiatives/", fontsize=8)
    page2.insert_text((43, 700), "（4）自社ESGスコアについて", fontname="japan", fontsize=11)

    doc.save(FIG_FIXTURE)
    doc.close()
    return FIG_FIXTURE


def test_gray_figure_flow(e2e_page, stewardship_pdf):
    """手順 1 でチェック → 手順 4 直行 → 検出図が採用済み → 切り出しグレー SVG を書き出す。"""
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)

    page.check("#chk-gray")
    expect(page.locator("#gray-skipnote")).to_be_visible()
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(stewardship_pdf)
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル", timeout=30_000)

    page.click("#btn-next")
    expect(page.locator('[data-screen="4"]')).to_have_class(re.compile("on"))

    # 手順 4 に入ると全ページを検出し、最初に見つかったページ (2 ページ目) へ自動で移動する
    # (`#exp-num` が "1" になることで「検出済み・採用済み」を非空虚に確認する)
    expect(page.locator("#exp-num")).to_have_text("1", timeout=15_000)
    expect(page.locator("#pagenav-4 .pg-row2.current")).to_have_text(re.compile("2 ページ"))

    expect(page.locator('#stepbar .step[data-step="2"]')).to_be_hidden()
    expect(page.locator("#pagenav-4")).to_be_visible()
    # 検出できたページは最初から採用済み (実線 1 つ)
    expect(page.locator("#fig-stage .fig-cand.sel")).to_have_count(1)
    expect(page.locator("#pagenav-4 .pg-row2.done")).to_have_count(1)
    # 書き出しファイル名の案内はグレーモード専用の文言になる
    expect(page.locator("#exp-name-hint")).to_contain_text("_fig1_gray.svg")

    # × で外すと 0 件になり書き出せない。候補 (点線) をクリックすると戻る
    page.click("#fig-stage .fig-cand.sel .del")
    expect(page.locator("#exp-num")).to_have_text("0")
    expect(page.locator("#btn-export")).to_be_disabled()
    page.click("#fig-stage .fig-cand:not(.sel)")
    expect(page.locator("#exp-num")).to_have_text("1")

    # 採用済みを角ハンドルで伸縮しても元候補は再出現しない (二重書き出しの防止)
    handle = page.locator("#fig-stage .fig-cand.sel .h.se")
    box = handle.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + 30, box["y"] + 30, steps=5)
    page.mouse.up()
    expect(page.locator("#fig-stage .fig-cand:not(.sel)")).to_have_count(0)
    expect(page.locator("#exp-num")).to_have_text("1")

    with page.expect_download() as dl_info:
        page.click("#btn-export")
    download = dl_info.value
    assert download.suggested_filename == "stewardship_sample_p2_fig1_gray.svg"
    svg_text = Path(download.path()).read_text(encoding="utf8")
    assert 'clip-path="url(#clip-export)"' in svg_text
    assert not re.search(r'="#(?!([0-9a-f]{2})\1\1")[0-9a-f]{6}"', svg_text)  # 有彩色が残らない
    assert "投資リターンの最大化" in svg_text                                  # 文字は文字のまま
    assert "自社ESGスコア" not in svg_text                                      # 図の外は含まない

    # 空白部分からページの外へ大きくドラッグしても、追加される矩形はページ内へ収まる
    # (figure.js の clampToPage。サーバの clip 検証「ページ内・正の寸法」に落ちて
    # 書き出しごと失敗する退行を防ぐ)。
    svg_box = page.locator("#fig-stage svg").bounding_box()
    page.mouse.move(svg_box["x"] + 15, svg_box["y"] + 15)  # ページ左上のブランク余白
    page.mouse.down()
    page.mouse.move(svg_box["x"] + svg_box["width"] + 300, svg_box["y"] + svg_box["height"] + 300, steps=5)
    page.mouse.up()
    expect(page.locator("#exp-num")).to_have_text("2")
    expect(page.locator("#fig-stage .fig-cand.sel")).to_have_count(2)

    with page.expect_download() as dl_info2:
        page.click("#btn-export")
    zip_path = dl_info2.value.path()
    with zipfile.ZipFile(zip_path) as z:
        names = sorted(z.namelist())
        assert names == ["stewardship_sample_p2_fig1_gray.svg", "stewardship_sample_p2_fig2_gray.svg"]
        fig2_svg = z.read("stewardship_sample_p2_fig2_gray.svg").decode("utf8")
    m = re.search(r'viewBox="([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+)"', fig2_svg)
    assert m, "viewBox 属性が見つからない"
    vx, vy, vw, vh = (float(g) for g in m.groups())
    # サーバの clip 検証と同じ許容量 (+0.5pt) で、ページ (595 x 842pt) 内に収まっていることを確かめる
    assert vx >= 0 and vy >= 0
    assert vx + vw <= 595.5 and vy + vh <= 842.5

    # 戻るは手順 1 へ (手順 3 ではない)
    page.click("#btn-back")
    expect(page.locator('[data-screen="1"]')).to_have_class(re.compile("on"))
    page.uncheck("#chk-gray")
