# =============================================================================
# test_pdftosvg_app_flow_e2e.py — 4 ステップ UI の通し E2E(旧 app_flow.e2e.ts の 1:1)
# =============================================================================
# 実 Python バックエンド(test/e2e_server.py)を子プロセスで起動し、Edge channel の
# 実ブラウザから叩く。ポートは OS に選ばせる（`e2e_server.py` の説明を参照）。
# page は module スコープ共有(旧 TS はテスト毎に新規 page)だが、全テストが冒頭で
# goto するため JS realm は毎回作り直され、サーバ状態は resetSession が戻す — 等価。
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest
from playwright.sync_api import expect

from .e2e_server import wait_for_port_file, wait_until_serving

pytestmark = [pytest.mark.browser, pytest.mark.e2e]

TOKEN = "e2e-fixed-session-token"
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.pdf")


@pytest.fixture(scope="module")
def e2e_server():
    # ポート 0 で起動して OS に選ばせ、子が bind した実ポートをファイルで受け取る。固定ポートだと
    # 2 本並走したときに混線する (Windows では SO_REUSEADDR で二重 bind が成功し、接続が
    # どちらへ届くか不定になる) ため、毎回違うポートにして衝突そのものを無くす
    with tempfile.TemporaryDirectory(prefix="pdftosvg-e2e-port-") as tmp:
        port_file = Path(tmp) / "port"
        env = dict(os.environ, PDFTOSVG_E2E_PORT="0", PDFTOSVG_E2E_PORT_FILE=str(port_file))
        proc = subprocess.Popen(
            [sys.executable, os.path.join(os.path.dirname(__file__), "e2e_server.py")],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            port = wait_for_port_file(port_file, proc)
            base = f"http://127.0.0.1:{port}"
            wait_until_serving(proc, base)
            yield base
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


# サーバのセッション(開いている文書・辞書・Undo)はテスト間で共有される。各テストは自分が
# 前提とする構成を作れるよう、先に文書と辞書を空にする。辞書をテスト末尾で消す形にすると、
# アサートが落ちたときに実行されず、次のテストへ語が漏れる。
def reset_session(page):
    page.evaluate("""async () => {
        const w = window;
        for (let i = 0; i < 20; i++) {
            const st = await w.rpc("state");
            if (!st.files.length) break;
            await w.rpc("removeFile", { fileIndex: 0 });
        }
        const dict = await w.rpc("dictList");
        for (const e of dict.entries) await w.rpc("dictDelete", { id: e.id });
    }""")


def _adopted_rect(page, index=0):
    """手順 4 で採用している矩形をモデル側から読む (表示の箱ではなく `S.figSel` が正)。"""
    return page.evaluate(
        """(i) => {
            const S = window.__state; const pg = S.PAGES[S.page]; if (!pg) return null;
            const sel = S.figSel[pg.fileIndex + ":" + pg.pageInFile];
            const r = sel && sel[i];
            return r ? { x: r.x, y: r.y, w: r.w, h: r.h } : null;
        }""",
        index,
    )


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
    expect(page.locator("#dict-count")).to_have_text("登録済みの用語（1）")
    # 辞書に語を足しただけで、その語に当たるページは「辞書に一致」に上がる(再適用の前でも)
    expect(page.locator("#nav-hint")).to_contain_text("辞書に一致 1 ページ")
    page.click("#btn-reapply")
    expect(page.locator("#nav-hint")).to_contain_text("置換 1 か所")
    expect(page.locator("#doc-master")).to_contain_text("売上高", timeout=15_000)

    # 箇所単位: 一覧の「戻す」で 1 件だけ置換前へ → 行は未置換(置換ボタン)になる → 「置換」で再び当たる
    page.click('[data-tab="confirm"]')
    rows = page.locator("#confirm-dyn .change-row")
    expect(rows.first.locator(".num")).to_have_text("1")
    # 番号マーカーは一覧の行数と同数だけページ上に描かれる
    expect(page.locator("#doc-master svg [data-editor-marks] > g")).to_have_count(rows.count())
    rows.first.locator(".act-revert").click()
    expect(page.locator("#doc-master")).to_contain_text("Revenue", timeout=15_000)
    expect(page.locator("#confirm-dyn .count-card .num")).to_have_text("0")
    expect(page.locator("#confirm-dyn .count-card")).to_contain_text("1 か所が未置換です")
    page.locator("#confirm-dyn .change-row").first.locator(".act-apply").click()
    expect(page.locator("#doc-master")).to_contain_text("売上高", timeout=15_000)
    expect(page.locator("#confirm-dyn .count-card")).to_contain_text("すべて置き換えました")

    # 入力欄でのショートカットは文書の Undo を撃たない。辞書の語を打ち直そうと Ctrl+Z した
    # だけで直前の置換が消えると、消えたことに気付けないため。
    page.click('[data-tab="dict"]')
    page.click("#dict-src")
    page.evaluate("() => { window.__rpcLog.length = 0; }")
    page.press("#dict-src", "Control+z")
    page.press("#dict-src", "Control+y")
    assert page.evaluate("() => window.__rpcLog") == []

    # ── 3. 不要範囲を削除: 要素クリック選択 → 削除 → Undo → 再削除 ──
    page.click("#btn-next")  # ページごとの確認は無いので「次へ」でそのまま手順 3 へ
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
    target = page.locator('#trim-stage svg [data-el]', has_text="DeleteMe")
    target.click()
    page.click("#btn-deletesel")
    expect(page.locator('#trim-dyn [data-kind="removed"]')).to_have_count(1)
    page.click("#btn-undo")  # 直近の削除を取り消す
    expect(page.locator('#trim-dyn [data-kind="removed"]')).to_have_count(0)
    page.locator('#trim-stage svg [data-el]', has_text="DeleteMe").click()
    page.click("#btn-deletesel")
    expect(page.locator('#trim-dyn [data-kind="removed"]')).to_have_count(1)

    # 行ごとの「戻す」は直近の undo ではなく、その要素だけを戻す
    page.locator("#trim-dyn [data-restore]").first.click()
    expect(page.locator('#trim-dyn [data-kind="removed"]')).to_have_count(0)
    page.locator('#trim-stage svg [data-el]', has_text="DeleteMe").click()
    page.click("#btn-deletesel")
    expect(page.locator('#trim-dyn [data-kind="removed"]')).to_have_count(1)

    # ── 4. SVG に書き出す(1 ページ → 単一 SVG ダウンロード) ──
    page.click("#btn-next")  # 「書き出しへ」
    expect(page.locator("#btn-export")).to_be_visible()
    # まとめは表 (置換の箇所数・編集したページ)
    expect(page.locator("#export-summary")).to_contain_text("置換 1 か所")
    expect(page.locator("#export-summary")).to_contain_text("編集したページ 1")
    # 書き出す範囲は 3 択 (「スキップを除く」は無い)
    expect(page.locator("#exp-modes [data-mode]")).to_have_count(3)

    # グレーモード専用のペインは色モードでは描かれない (hidden が .editor/.segment の display に負けない)
    expect(page.locator("#fig-editor")).to_be_hidden()
    expect(page.locator("#exp-modes-gray")).to_be_hidden()
    expect(page.locator("#pagenav-4")).to_be_hidden()
    expect(page.locator("#fig-selist-box")).to_be_hidden()
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
    page.click("#btn-next")
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

    page.click("#btn-next")
    expect(page.locator("#trim-dyn")).to_contain_text("このページに編集はありません")
    break_rpc("removedList")
    page.locator('#pagenav-3 .pg-row2[data-g="0"]').click()
    expect(page.locator("#trim-dyn")).to_contain_text("取得できませんでした")
    heal_rpc()
    page.click("#trim-dyn [data-retry]")
    expect(page.locator("#trim-dyn")).to_contain_text("このページに編集はありません")


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
    # 右ペインの「採用した図」一覧にもファイル名 (書き出し予定名) が出る
    expect(page.locator("#fig-selist .serow")).to_have_count(1)
    expect(page.locator("#fig-selist .serow")).to_contain_text("stewardship_sample_p2_fig1_gray.svg")

    # × で外すと 0 件になり書き出せない。候補 (点線) をクリックすると戻る
    page.click("#fig-stage .fig-cand.sel .del")
    expect(page.locator("#exp-num")).to_have_text("0")
    expect(page.locator("#btn-export")).to_be_disabled()
    expect(page.locator("#fig-selist .serow")).to_have_count(0)
    page.click("#fig-stage .fig-cand:not(.sel)")
    expect(page.locator("#exp-num")).to_have_text("1")
    expect(page.locator("#fig-selist .serow")).to_have_count(1)

    # 採用済みを角ハンドルで伸縮しても元候補は再出現しない (二重書き出しの防止)
    # 伸縮が実際に効いていることを確かめるため、矩形の寸法が変わったか検証する
    rect_before = _adopted_rect(page)
    handle = page.locator("#fig-stage .fig-cand.sel .h.se")
    box = handle.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + 30, box["y"] + 30, steps=5)
    page.mouse.up()
    rect_after = _adopted_rect(page)
    # 南東を 30px ずつ移動したら、幅と高さが増えているはず
    assert rect_before is not None and rect_after is not None
    assert rect_after["w"] > rect_before["w"], f"幅が増えていない: {rect_before['w']} → {rect_after['w']}"
    assert rect_after["h"] > rect_before["h"], f"高さが増えていない: {rect_before['h']} → {rect_after['h']}"
    expect(page.locator("#fig-stage .fig-cand:not(.sel)")).to_have_count(0)
    expect(page.locator("#exp-num")).to_have_text("1")

    with page.expect_download() as dl_info:
        page.click("#btn-export")
    download = dl_info.value
    assert download.suggested_filename == "stewardship_sample_p2_fig1_gray.svg"
    svg_text = Path(download.path()).read_text(encoding="utf8")
    # id は clip 矩形ごとの決定的な値 (`clip-export` 固定ではない。複数ページを 1 文書へ
    # inline しても id が衝突しないようにするための変更)
    assert re.search(r'clip-path="url\(#clip-[\w-]+\)"', svg_text)
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
    expect(page.locator("#fig-selist .serow")).to_have_count(2)

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


def _goto_step3(page, pdf_path):
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(str(pdf_path))
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル", timeout=30_000)
    page.click("#btn-next")
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))
    page.click("#btn-next")  # 辞書が空なので未確認ガードは出ない
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
    expect(page.locator("#trim-stage svg")).to_be_visible()


def test_ocr_layer_upload_notifies(e2e_page, ocr_layer_pdf):
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(str(ocr_layer_pdf))
    expect(page.locator("#toast")).to_contain_text("OCR 文字のページを 1 ページ検出", timeout=30_000)


def test_click_transparent_ocr_text_collects_into_dictionary(e2e_page, ocr_layer_pdf):
    """手順 2 の透明 (未置換の不可視 OCR) 文字をクリックすると `dictSuggest` が発火し、
    「元の語」欄へ取り込まれる (`wireConfirmPick`)。当たり判定は `fill-opacity="0"` でも
    `fill` を残しているため効く (`fill="none"` だと SVG 既定の `pointer-events` が外れる)。
    """
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(str(ocr_layer_pdf))
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル", timeout=30_000)
    page.click("#btn-next")
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))

    target = page.locator('#doc-master svg [data-el]', has_text="Header Text")
    expect(target).to_have_count(1)
    target.click()
    expect(page.locator("#dict-src")).to_have_value("Header Text")


def test_confirm_marker_is_drawn_over_replaced_invisible_text_group(e2e_page, ocr_layer_pdf):
    """辞書置換後の確認マーカーは、不可視 OCR 文字の置換結果 `<g><rect/><text/></g>` の
    上に描かれる (`drawChangeMarkers` は対象要素の `getBBox()` を使い、`<g>` は子要素の
    bbox を合併するので `<text>` 単体のときと同じ位置に置ける)。マーカーの中心 (`cx`/`cy`)
    が置換矩形 (`<rect>`) の左上と一致することで、`<g>` へのラップ後も位置がずれて
    いないと確かめる。
    """
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(str(ocr_layer_pdf))
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル", timeout=30_000)
    page.click("#btn-next")
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))
    page.click('[data-tab="dict"]')
    page.fill("#dict-src", "Header Text")
    page.fill("#dict-tgt", "見出し")
    page.click("#dict-add")
    page.click("#btn-reapply")
    expect(page.locator("#doc-master")).to_contain_text("見出し", timeout=15_000)

    page.click('[data-tab="confirm"]')
    expect(page.locator("#confirm-dyn .change-row")).to_have_count(1)
    expect(page.locator("#doc-master svg [data-editor-marks] > g")).to_have_count(1)

    pos = page.evaluate("""() => {
        var svgEl = document.querySelector("#doc-master svg");
        var textEl = svgEl.querySelector('g[data-el] text');
        var groupEl = textEl.closest('[data-el]');
        var rectEl = groupEl.querySelector('rect');
        var circleEl = svgEl.querySelector('[data-editor-marks] circle');
        return {
            markCx: +circleEl.getAttribute('cx'), markCy: +circleEl.getAttribute('cy'),
            rectX: +rectEl.getAttribute('x'), rectY: +rectEl.getAttribute('y'),
        };
    }""")
    assert abs(pos["markCx"] - pos["rectX"]) < 1
    assert abs(pos["markCy"] - pos["rectY"]) < 1


def test_manual_cover_tool_places_cover(e2e_page, ocr_layer_pdf):
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="cover"]')
    expect(page.locator("#cover-opts")).to_be_visible()
    page.fill("#cover-text", "手動語")
    box = page.locator("#trim-stage svg").bounding_box()
    # ページ座標 (20,120)-(120,140) 付近 (白地の不可視文字の上) をドラッグする
    sx, sy = box["width"] / 300, box["height"] / 200
    page.mouse.move(box["x"] + 20 * sx, box["y"] + 110 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 120 * sx, box["y"] + 135 * sy, steps=5)
    page.mouse.up()
    expect(page.locator('#trim-stage svg g[data-el] text', has_text="手動語")).to_have_count(1)
    covers = page.evaluate(
        """async () => (await window.rpc("coverList", { fileIndex: 0, pageInFile: 0 })).covers"""
    )
    assert len(covers) == 1 and covers[0]["text"] == "手動語"


def test_manual_cover_drag_past_the_page_edge_still_places_a_cover(e2e_page, ocr_layer_pdf):
    """ページの端をまたいでドラッグしても上書きが置かれる (ページ内へ収める)。

    収めずにサーバへ送ると `addCover` がページ外として拒否し、受け止めが無いため利用者には
    成功も失敗も見えないまま何も起きない。
    """
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="cover"]')
    page.fill("#cover-text", "端")
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200
    # ページ右下の外までドラッグする
    page.mouse.move(box["x"] + 250 * sx, box["y"] + 150 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] + 120, box["y"] + box["height"] + 120, steps=5)
    page.mouse.up()
    # オーバーレイの描画を待ってから RPC を読む。addCover → 再描画の連鎖が終わる前に
    # 評価すると、次のテストの遷移がこの連鎖を途中で断ち切ってしまう。
    expect(page.locator("#trim-stage .cover-box")).to_have_count(1)
    covers = page.evaluate(
        """async () => (await window.rpc("coverList", { fileIndex: 0, pageInFile: 0 })).covers"""
    )
    assert len(covers) == 1
    r = covers[0]["rect"]
    assert r["x"] + r["w"] <= 300.5 and r["y"] + r["h"] <= 200.5


def test_manual_cover_jitter_click_does_not_push_noop_undo(e2e_page, ocr_layer_pdf):
    """1px 程度のジッター付きクリックは `updateCover` の no-op を送らない。

    送ると矩形が変わらない 1 段が Undo スタックへ積まれ、次の Ctrl+Z が「何も起きない」
    ように見える (`cover.js` の `rectsNearlyEqual`)。Undo 1 回で「置いた」こと自体が
    取り消されることを確かめれば、ジッターの `updateCover` が積まれていないと分かる。
    """
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="cover"]')
    page.fill("#cover-text", "上書き語")
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200
    page.mouse.move(box["x"] + 20 * sx, box["y"] + 110 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 120 * sx, box["y"] + 135 * sy, steps=5)
    page.mouse.up()
    overlay = page.locator("#trim-stage .cover-box")
    expect(overlay).to_have_count(1)

    # 本体をクリック。ページ座標で 0.5pt (しきい値 1pt 未満) だけずらし、実クリックの
    # 手ブレを再現する。
    ob = overlay.bounding_box()
    cx, cy = ob["x"] + ob["width"] / 2, ob["y"] + ob["height"] / 2
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx + sx * 0.5, cy, steps=1)
    page.mouse.up()

    # Ctrl+Z の時点で入力欄にフォーカスが残っていないこと (残っていると Ctrl+Z はブラウザ標準の
    # 取り消しへ譲られ、アプリの Undo に届かない)。上書きを置いた時点でアプリが外している前提を
    # ここで明示し、テストの結果が実行順に依存しないようにする。
    expect(page.locator("#cover-text")).not_to_be_focused()
    page.keyboard.press("Control+z")
    expect(page.locator("#trim-stage .cover-box")).to_have_count(0)


def test_undo_after_typing_a_word_then_placing_a_cover_undoes_the_cover(e2e_page, ocr_layer_pdf):
    """入力欄に語を打ってから範囲を引いて上書きを置き、そのまま Ctrl+Z を押すと上書きが戻る。

    範囲を引いた時点でアプリが入力欄のフォーカスを外すので、Ctrl+Z がアプリの Undo に届く。
    外さないと Ctrl+Z はブラウザ標準の取り消しへ譲られ、上書きは戻らず入力欄の語が消える。
    """
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="cover"]')
    page.fill("#cover-text", "打った語")
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200
    page.mouse.move(box["x"] + 20 * sx, box["y"] + 110 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 120 * sx, box["y"] + 135 * sy, steps=5)
    page.mouse.up()
    expect(page.locator("#trim-stage .cover-box")).to_have_count(1)
    expect(page.locator("#cover-text")).not_to_be_focused()
    page.keyboard.press("Control+z")
    expect(page.locator("#trim-stage .cover-box")).to_have_count(0)
    # 入力欄の語は消えていない (ブラウザ標準の取り消しに取られていない)
    expect(page.locator("#cover-text")).to_have_value("打った語")


def test_undo_after_typing_a_width_then_placing_a_border_undoes_the_border(e2e_page, ocr_layer_pdf):
    """太さを打ってから枠線を引き、そのまま Ctrl+Z を押すと枠線が戻る (枠線ツールでも同じ)。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    _place_border(page, width="3")
    expect(page.locator("#border-width")).not_to_be_focused()
    page.keyboard.press("Control+z")
    expect(page.locator("#trim-stage .border-box")).to_have_count(0)
    expect(page.locator("#border-width")).to_have_value("3")


def test_border_width_outside_the_html_range_is_rejected_and_the_input_is_restored(e2e_page, ocr_layer_pdf):
    """入力欄の max (20) を越える太さを打って確定すると、サーバへ送らず入力欄を直前の妥当な値へ戻す。

    HTML の `min` / `max` はブラウザの number 入力で強制力が弱く、25 と打てば JS はその値を読める。
    JS が HTML の属性を正典として検査しないと、サーバが拒否した値が入力欄に残ったままになる。
    """
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="border"]')
    page.fill("#border-width", "3")
    page.press("#border-width", "Enter")  # 次に置く太さを 3 に確定
    page.fill("#border-width", "25")
    page.press("#border-width", "Enter")
    expect(page.locator("#border-width")).to_have_value("3")  # 弾かれて 3 に戻る
    assert page.evaluate("() => window.__state.borderWidth") == 3
    page.fill("#border-width", "0.2")
    page.press("#border-width", "Enter")
    expect(page.locator("#border-width")).to_have_value("3")


def test_manual_cover_resize_and_retext(e2e_page, ocr_layer_pdf):
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="cover"]')
    page.fill("#cover-text", "初期")
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200
    page.mouse.move(box["x"] + 20 * sx, box["y"] + 110 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 120 * sx, box["y"] + 135 * sy, steps=5)
    page.mouse.up()
    overlay = page.locator("#trim-stage .cover-box")
    expect(overlay).to_have_count(1)

    # 右下ハンドルで伸縮 → updateCover(rect)
    h = overlay.locator(".h.se").bounding_box()
    page.mouse.move(h["x"] + h["width"] / 2, h["y"] + h["height"] / 2)
    page.mouse.down()
    page.mouse.move(h["x"] + 40 * sx, h["y"] + 20 * sy, steps=5)
    page.mouse.up()
    rect = page.evaluate("""async () => (await window.rpc("coverList", { fileIndex: 0, pageInFile: 0 })).covers[0].rect""")
    assert rect["w"] > 100 and rect["h"] > 25

    # オーバーレイをクリックして選び、入力欄で語を変える → updateCover(text)
    page.locator("#trim-stage .cover-box").click()
    expect(page.locator("#cover-text")).to_have_value("初期")
    page.fill("#cover-text", "変更後")
    page.press("#cover-text", "Enter")
    expect(page.locator('#trim-stage svg g[data-el] text', has_text="変更後")).to_have_count(1)
    text = page.evaluate("""async () => (await window.rpc("coverList", { fileIndex: 0, pageInFile: 0 })).covers[0].text""")
    assert text == "変更後"

    # Undo で語が戻る
    page.keyboard.press("Control+z")
    expect(page.locator('#trim-stage svg g[data-el] text', has_text="初期")).to_have_count(1)


def test_manual_cover_selected_edit_does_not_leak_into_next_word(e2e_page, ocr_layer_pdf):
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="cover"]')
    page.fill("#cover-text", "次語")
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200

    # 1 個目の上書きを「次語」で置く
    page.mouse.move(box["x"] + 20 * sx, box["y"] + 110 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 120 * sx, box["y"] + 135 * sy, steps=5)
    page.mouse.up()
    expect(page.locator("#trim-stage .cover-box")).to_have_count(1)

    # クリックで選び、選択中の語だけを別の語へ編集して確定する
    page.locator("#trim-stage .cover-box").click()
    expect(page.locator("#cover-text")).to_have_value("次語")
    page.fill("#cover-text", "選択中に編集した語")
    page.press("#cover-text", "Enter")
    expect(page.locator('#trim-stage svg g[data-el] text', has_text="選択中に編集した語")).to_have_count(1)

    # 空白をクリックして選択解除 → 入力欄は「次に置く語」(選択中の編集に汚されていない) へ戻る
    page.mouse.click(box["x"] + 250 * sx, box["y"] + 20 * sy)
    expect(page.locator("#cover-text")).to_have_value("次語")

    # 2 個目の上書きをドラッグで置く → 選択中に編集した語ではなく最初の「次語」が使われる
    page.mouse.move(box["x"] + 20 * sx, box["y"] + 150 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 120 * sx, box["y"] + 170 * sy, steps=5)
    page.mouse.up()
    expect(page.locator("#trim-stage .cover-box")).to_have_count(2)
    texts = page.evaluate("""async () => (await window.rpc("coverList", { fileIndex: 0, pageInFile: 0 })).covers.map(c => c.text)""")
    assert sorted(texts) == sorted(["選択中に編集した語", "次語"])


def _place_cover(page, word):
    """上書きツールでページ座標 (20,110)-(120,135) へ上書きを 1 つ置く。"""
    page.click('[data-tool="cover"]')
    page.fill("#cover-text", word)
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200
    page.mouse.move(box["x"] + 20 * sx, box["y"] + 110 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 120 * sx, box["y"] + 135 * sy, steps=5)
    page.mouse.up()
    expect(page.locator("#trim-stage .cover-box")).to_have_count(1)


def _select_visible_text(page):
    """ツールを選ばないまま可視文字を 1 つクリックで選び、青枠 (`.sel-box`) が付くまで待つ。"""
    page.locator("#trim-stage svg [data-el]", has_text="visible text").first.click()
    expect(page.locator("#trim-stage .sel-box")).to_have_count(1)


def _open_second_page_in_step3(page, pdf_path):
    """手順 3 で 2 ページ目を開く。絞り込みの既定は「すべてのページ」なので、行をクリックするだけ。"""
    _goto_step3(page, pdf_path)
    page.click('#pagenav-3 .pg-row2[data-g="1"]')
    expect(page.locator("#pgnav-3 .pj-num")).to_have_value("2")


def _advance_step3_to_step4(page):
    """手順 3 から 4 へ進む。ページごとの確認は無いので「書き出しへ」でそのまま進む。"""
    page.click("#btn-next")
    expect(page.locator('[data-screen="4"]')).to_have_class(re.compile("on"))


def _place_border(page, width="2"):
    """枠線ツールでページ座標 (20,110)-(120,135) へ枠線を 1 つ置く。"""
    page.click('[data-tool="border"]')
    expect(page.locator("#border-opts")).to_be_visible()
    page.fill("#border-width", width)
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200
    page.mouse.move(box["x"] + 20 * sx, box["y"] + 110 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 120 * sx, box["y"] + 135 * sy, steps=5)
    page.mouse.up()
    expect(page.locator("#trim-stage .border-box")).to_have_count(1)


def _poll_borders(page, predicate_js, timeout_ms=3000):
    """`borderList` の結果が `predicate_js`（JS の関数式。引数は borders 配列）を満たすまで待ち、
    満たした時点の borders を返す。Playwright の `wait_for_function` に任せる（以前は文字列を
    `eval` で関数に戻して自前でポーリングしていた）。

    2 つの制約を踏まえた形にしてある。
    ① `wait_for_function` の predicate は async 関数を渡しても 1 回しか呼ばれない（呼び出し直後の
    戻り値は Promise で、Promise は常に truthy なのでポーリング側はその場で「満たした」とみなし、
    その後 Promise を await した中身をそのまま返す。中身が false でも再ポーリングされない。実測でも
    `polling="raf"` / 数値ポーリングいずれも同じ挙動だった）。そのため `borderList` の RPC 往復
    （本質的に非同期）は predicate の外に出し、裏で定期取得するタイマーの最新値を、predicate 自身は
    同期関数として読むだけにする（同期 predicate なら `wait_for_function` が正しく再ポーリングする）。
    ② このアプリの応答は CSP（`default-src 'self'`。`unsafe-eval` を許可しない）を持ち、
    `wait_for_function` の predicate 内で `eval` を呼ぶとそこで CSP 違反になる（通常の `evaluate` は
    CDP 経由で CSP の対象にならず通るが、`wait_for_function` のポーリング機構は対象になる。実測で
    確認済み）。そのため `predicate_js`（関数式の文字列）の実体化（`eval` 相当）は通常の `evaluate`
    側で 1 回だけ行い、`wait_for_function` へは実体化済みの関数への参照（JSHandle）を渡す。"""
    # `pred_handle`（evaluate_handle が返す JSHandle）はページ側にリソースを持つので、
    # 成功・タイムアウト・例外のどの経路でも dispose() する。evaluate_handle 自体が例外を投げる
    # 経路もあるため None で初期化してから try に入り、setInterval の起動も try の中（先頭）へ
    # 置いて、以降のどの行が例外を投げても finally の clearInterval / dispose に必ず到達させる。
    pred_handle = None
    try:
        page.evaluate(
            """() => {
                if (window.__bordersPollTimer) return;
                window.__bordersSnapshot = null;
                var tick = function () {
                    window.rpc("borderList", { fileIndex: 0, pageInFile: 0 }).then(function (r) {
                        window.__bordersSnapshot = r.borders;
                    });
                };
                tick();
                window.__bordersPollTimer = setInterval(tick, 100);
            }"""
        )
        # 式がそのまま関数として渡ると Playwright は「呼び出す関数」とみなして即実行してしまうため
        # (evaluate 系 API の標準の解釈)、オブジェクトで包んで関数そのものへの参照だけを取り出す。
        pred_handle = page.evaluate_handle("({fn: " + predicate_js + "})")
        handle = page.wait_for_function(
            """(predObj) => {
                var bs = window.__bordersSnapshot;
                return bs && predObj.fn(bs) ? bs : false;
            }""",
            arg=pred_handle,
            timeout=timeout_ms,
            polling=100,
        )
        return handle.json_value()
    finally:
        page.evaluate(
            """() => {
                if (window.__bordersPollTimer) { clearInterval(window.__bordersPollTimer); window.__bordersPollTimer = null; }
            }"""
        )
        if pred_handle is not None:
            pred_handle.dispose()


def test_border_overlay_resize_and_width_change(e2e_page, ocr_layer_pdf):
    """置いた枠線を角ハンドルで伸縮でき、選んでから太さを変えられる (どちらも Undo 可)。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    _place_border(page, width="2")
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200

    # 右下ハンドルで伸縮 → updateBorder(rect)
    overlay = page.locator("#trim-stage .border-box")
    h = overlay.locator(".h.se").bounding_box()
    page.mouse.move(h["x"] + h["width"] / 2, h["y"] + h["height"] / 2)
    page.mouse.down()
    page.mouse.move(h["x"] + 40 * sx, h["y"] + 20 * sy, steps=5)
    page.mouse.up()
    borders = _poll_borders(page, "function (bs) { return bs[0] && bs[0].rect.w > 100 && bs[0].rect.h > 25; }")
    rect = borders[0]["rect"]
    assert rect["w"] > 100 and rect["h"] > 25

    # オーバーレイをクリックして選び、太さを変える → updateBorder(width)
    page.locator("#trim-stage .border-box").click()
    expect(page.locator("#border-width")).to_have_value("2")
    page.fill("#border-width", "5")
    page.press("#border-width", "Enter")
    borders = _poll_borders(page, "function (bs) { return bs[0] && bs[0].width === 5; }")
    assert borders[0]["width"] == 5

    # Undo で太さが戻る
    page.keyboard.press("Control+z")
    borders = _poll_borders(page, "function (bs) { return bs[0] && bs[0].width === 2; }")
    assert borders[0]["width"] == 2

    # 置いた枠線は右パネル「このページの編集」にも行として出る
    expect(page.locator('#trim-dyn [data-kind="border"]')).to_have_count(1)
    expect(page.locator("#trim-dyn")).to_contain_text("枠線")


def test_border_selected_edit_does_not_leak_into_the_next_border(e2e_page, ocr_layer_pdf):
    """選択中に変えた太さが、選択を解いたあとに置く枠線へ紛れ込まない。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    _place_border(page, width="2")
    page.locator("#trim-stage .border-box").click()
    page.fill("#border-width", "7")
    page.press("#border-width", "Enter")
    # 太さの確定 (`commitBorderStyle`) は `updateBorder` → `afterEdit` の RPC 往復を挟み、
    # ページ SVG の再取得・再マウントを伴う (枠線の太さそのものが SVG の `stroke-width`
    # なので、変更を反映するには描き直しが要る)。この再マウントが終わる前に 2 本目を
    # 置き始めると、2 本目の追加 (`addBorder` → `afterEdit`) の再描画と競合し、
    # `rect-overlay.js` の `draw` が古い一覧の結果で新しい描画を上書きしてしまう
    # (どちらの HTTP 応答が先に返るかは保証されない)。反映後の SVG (`stroke-width="7"`)
    # を待ってから次へ進み、2 つの再描画が重ならないようにする。
    expect(page.locator("#trim-stage svg rect[data-el]").first).to_have_attribute("stroke-width", "7")

    # 空白をドラッグすると選択が解け、2 本目は「次に置く枠線」の太さ 2 で置かれる
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200
    page.mouse.move(box["x"] + 150 * sx, box["y"] + 40 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 250 * sx, box["y"] + 80 * sy, steps=5)
    page.mouse.up()
    expect(page.locator("#trim-stage .border-box")).to_have_count(2)
    widths = page.evaluate("""async () => (await window.rpc("borderList", { fileIndex: 0, pageInFile: 0 })).borders.map(b => b.width)""")
    assert sorted(widths) == [2, 7]


def test_border_delete_button_removes_border_selected_with_border_tool(e2e_page, ocr_layer_pdf):
    """枠線ツールのままクリックで選んだ枠線を、「削除」ボタンで消せる。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    _place_border(page)
    page.locator("#trim-stage .border-box").click()
    expect(page.locator("#trim-stage .border-box.sel")).to_have_count(1)
    page.click("#btn-deletesel")
    expect(page.locator("#trim-stage .border-box")).to_have_count(0)
    borders = page.evaluate("""async () => (await window.rpc("borderList", { fileIndex: 0, pageInFile: 0 })).borders""")
    assert borders == []


def test_manual_cover_delete_button_removes_cover_selected_with_cover_tool(e2e_page, ocr_layer_pdf):
    """上書きツールのままクリックで選んだ上書きを、「削除」ボタンで消せる。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    _place_cover(page, "消す語")
    page.locator("#trim-stage .cover-box").click()
    expect(page.locator("#trim-stage .cover-box.sel")).to_have_count(1)
    page.click("#btn-deletesel")
    expect(page.locator("#trim-stage .cover-box")).to_have_count(0)
    covers = page.evaluate("""async () => (await window.rpc("coverList", { fileIndex: 0, pageInFile: 0 })).covers""")
    assert covers == []


def test_delete_button_is_disabled_until_something_is_selected(e2e_page, ocr_layer_pdf):
    """何も選んでいない間は「削除」ボタンを押せない (押しても何も起きない状態を見た目で示す)。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    expect(page.locator("#btn-deletesel")).to_be_disabled()
    _select_visible_text(page)
    expect(page.locator("#btn-deletesel")).to_be_enabled()
    page.click("#btn-deletesel")
    expect(page.locator("#trim-stage .sel-box")).to_have_count(0)
    expect(page.locator("#btn-deletesel")).to_be_disabled()


def test_delete_button_is_enabled_by_a_border_selection_and_disabled_right_after_deleting(e2e_page, ocr_layer_pdf):
    """枠線を選んだときに「削除」ボタンが有効になり、削除した直後には (一覧の再取得を待たず) 無効に戻る。

    削除の直後は `S.borderSel` に削除済みの id が残ったまま `render()` が走るため、以前は非同期の
    一覧再取得が届くまで一瞬ボタンが有効のままだった。削除のハンドラで選択を即座に解く。
    """
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    _place_border(page)
    page.locator("#trim-stage .border-box").click()
    expect(page.locator("#btn-deletesel")).to_be_enabled()
    page.click("#btn-deletesel")
    # 削除の RPC 往復を待たずに、クリック直後の同期処理で無効になっていること
    assert page.evaluate("() => window.__state.borderSel") is None
    assert page.evaluate("() => document.getElementById('btn-deletesel').disabled") is True
    expect(page.locator("#btn-deletesel")).to_be_disabled()
    expect(page.locator("#trim-stage .border-box")).to_have_count(0)


def test_deleting_a_selected_border_restores_the_width_input_to_the_next_value(e2e_page, ocr_layer_pdf):
    """選択中の枠線の太さを変えてから削除すると、入力欄は「次に置く太さ」へ戻る。

    削除ボタンのハンドラは選択を `clearBorderSel` 経由で解く（`S.borderSel = null` の直接代入だと
    `clearOverlaySel` の `onSelect(null)` が呼ばれず、入力欄に削除済みの枠線の値が残る。次に置く枠線は
    `S.borderWidth` で置かれるため、表示と実際が食い違っていた）。
    """
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    _place_border(page, width="3")
    page.locator("#trim-stage .border-box").click()
    expect(page.locator("#border-width")).to_have_value("3")
    page.fill("#border-width", "7")
    page.press("#border-width", "Enter")
    _poll_borders(page, "function (bs) { return bs[0] && bs[0].width === 7; }")
    page.click("#btn-deletesel")
    expect(page.locator("#trim-stage .border-box")).to_have_count(0)
    # 入力欄は選択中の値 (7) ではなく「次に置く太さ」(3) へ戻る
    expect(page.locator("#border-width")).to_have_value("3")
    assert page.evaluate("() => window.__state.borderWidth") == 3


def test_switching_tool_clears_element_selection(e2e_page, ocr_layer_pdf):
    """ツールを切り替えると青枠の選択が解け、上書きの緑枠と同時に残らない。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    _select_visible_text(page)
    page.click('[data-tool="cover"]')
    expect(page.locator("#trim-stage .sel-box")).to_have_count(0)
    assert page.evaluate("() => Object.keys(window.__state.elSel['0:0'] || {}).length") == 0


def test_element_click_selection_works_while_a_tool_is_active(e2e_page, ocr_layer_pdf):
    """「選択」タブが無くなっても、どのツール中でもクリックで要素を選んで削除できる。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="crop"]')
    page.locator("#trim-stage svg [data-el]", has_text="visible text").first.click()
    expect(page.locator("#trim-stage .sel-box")).to_have_count(1)
    page.click("#btn-deletesel")
    expect(page.locator("#trim-stage .sel-box")).to_have_count(0)
    expect(page.locator('#trim-stage svg [data-el]', has_text="visible text")).to_have_count(0)


def test_pressing_the_active_tool_again_returns_to_no_tool(e2e_page, ocr_layer_pdf):
    """押下中のタブをもう一度押すと無選択へ戻り、ツール固有の入力欄が消える。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="border"]')
    expect(page.locator("#border-opts")).to_be_visible()
    page.click('[data-tool="border"]')
    expect(page.locator("#border-opts")).to_be_hidden()
    expect(page.locator('.float-tools [data-tool][aria-pressed="true"]')).to_have_count(0)


def test_click_after_offpage_drag_and_tool_toggle_off_selects_in_one_click(e2e_page, ocr_layer_pdf):
    """ページ外へはみ出すドラッグの直後にツールを無選択へ戻しても、次の要素クリックが
    握り潰されない (`S.dragMoved` がツール切替のたびにリセットされることの回帰確認)。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="crop"]')
    box = page.locator("#trim-stage svg").bounding_box()
    # ページ内から始めて、ページ (svg) の外まで大きくはみ出した位置で離す。
    # mouseup の target は svg の子孫ではなくなるため、後続の click は svg の
    # click リスナー (S.dragMoved を消費する側) へ届かない。
    page.mouse.move(box["x"] + 10, box["y"] + 10)
    page.mouse.down()
    page.mouse.move(5, 5, steps=5)
    page.mouse.up()
    page.click('[data-tool="crop"]')  # 押下中のタブの再クリックで無選択へ戻す
    page.locator("#trim-stage svg [data-el]", has_text="visible text").first.click()
    expect(page.locator("#trim-stage .sel-box")).to_have_count(1)


def test_click_after_offpage_drag_and_overlay_select_selects_in_one_click(e2e_page, ocr_layer_pdf):
    """ページ外へはみ出すドラッグで枠線を置いた直後に、その箱をクリックして選んでも
    `S.dragMoved` が消費されずに残らない。続けて要素をクリックすれば 1 回で選択される。

    箱の mousedown はキャンバスの mousedown ハンドラへ届かない (箱側が stopPropagation する) ため、
    そこにリセットを置く形では `S.dragMoved` が消費されずに残る。window の capture フェーズで
    「次の mousedown が来たら用済み」と 1 箇所で持つことで、経路を個別に塞がずに済む。

    箱をクリックした直後の値は `window.__state`(E2E 用の読み取り窓)で直接確かめる。箱は
    `background: transparent` でも div 全面が pointer-events を奪うため、箱が覆う位置で
    「続けて要素をクリック」しても実ブラウザではその要素へ届かず (クリックは箱を再選択する
    だけになり)、`.sel-box` の有無では箱の mousedown が漏れをそのまま検出できない。次の
    要素クリックは箱と重ならない位置で行い、1 回で選べることの回帰確認として添える。
    """
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="border"]')
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200
    # ページの右下の外までドラッグして枠線を置く (S.dragMoved が true のまま残る操作)。
    # x=200 起点にして、後で使う「visible text」(x=20, y=150) を箱が覆わないようにする
    # (`.border-box` は `background: transparent` でも div 全面が pointer-events を奪うため、
    # 重なると次のクリックが箱に取られてしまい要素を選べない)。
    page.mouse.move(box["x"] + 200 * sx, box["y"] + 20 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] + 80, box["y"] + box["height"] + 80, steps=5)
    page.mouse.up()
    expect(page.locator("#trim-stage .border-box")).to_have_count(1)
    assert page.evaluate("() => window.__state.dragMoved") is True
    # 置いた箱をクリックして選ぶ (箱側が stopPropagation するのでキャンバスの mousedown は走らない)
    page.locator("#trim-stage .border-box").click()
    expect(page.locator("#trim-stage .border-box.sel")).to_have_count(1)
    # 本題: 箱の mousedown だけでも `S.dragMoved` が用済みになっていること
    # (修正前は true のまま残り、次に svg 側で拾う click を誤って握り潰す)
    assert page.evaluate("() => window.__state.dragMoved") is False
    # 続けて要素をクリック → 1 回で選ばれること (箱と重ならない要素なので実クリックが届く)
    page.locator("#trim-stage svg [data-el]", has_text="visible text").first.click()
    expect(page.locator("#trim-stage .sel-box")).to_have_count(1)


def test_back_from_step4_keeps_page_and_clears_selection(e2e_page, ocr_layer_two_page_pdf):
    """「戻る」で手順 4 から 3 へ戻ると、見ていたページのまま選択が解けている。"""
    page = e2e_page
    _open_second_page_in_step3(page, ocr_layer_two_page_pdf)
    _select_visible_text(page)
    _advance_step3_to_step4(page)
    page.click("#btn-back")
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
    expect(page.locator("#pgnav-3 .pj-num")).to_have_value("2")
    expect(page.locator("#trim-stage svg")).to_be_visible()
    expect(page.locator("#trim-stage .sel-box")).to_have_count(0)


def test_stepbar_back_to_step3_keeps_page_and_resets_tool(e2e_page, ocr_layer_two_page_pdf):
    """ステップバーで手順 4 から 3 へ戻ると、見ていたページのままツールが無選択に戻る。"""
    page = e2e_page
    _open_second_page_in_step3(page, ocr_layer_two_page_pdf)
    page.click('[data-tool="cover"]')
    expect(page.locator("#cover-opts")).to_be_visible()
    _advance_step3_to_step4(page)
    page.click('#stepbar .step[data-step="3"]')
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
    expect(page.locator("#pgnav-3 .pj-num")).to_have_value("2")
    expect(page.locator('.float-tools [data-tool][aria-pressed="true"]')).to_have_count(0)
    expect(page.locator("#cover-opts")).to_be_hidden()


def test_back_from_step3_to_step2_keeps_page(e2e_page, ocr_layer_two_page_pdf):
    """「戻る」で手順 3 から 2 へ戻っても、見ていたページのまま。"""
    page = e2e_page
    _open_second_page_in_step3(page, ocr_layer_two_page_pdf)
    page.click("#btn-back")
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))
    expect(page.locator("#pgnav-2 .pj-num")).to_have_value("2")


def test_all_scanned_pdf_skips_step2_via_dialog(e2e_page, scanned_pdf):
    """全ページが純スキャンなら、手順 1 の「次へ」でモーダルが出て手順 3 へ直行する。

    手順 2 はステップバーから消え、「戻る」は 3→1 になる。手順 4 のまとめには「対象外」が出る。
    """
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(str(scanned_pdf))
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル", timeout=30_000)
    # 読み込み直後のトースト (混在時にも出る通知)
    expect(page.locator("#toast")).to_contain_text("1 ページはスキャン画像のため", timeout=30_000)
    # 読み込んだ時点でステップバーの 2 が消え、注記が出る (グレーモードと同じ見せ方)
    expect(page.locator('#stepbar .step[data-step="2"]')).to_be_hidden()
    expect(page.locator("#scan-skipnote")).to_be_visible()

    page.click("#btn-next")
    dialog = page.locator("#skip2-dialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("上書き")
    expect(page.locator("#skip2-n")).to_have_text("1")
    # 省略した PDF の一覧 (ファイル名とページ数) を本文に出す
    expect(page.locator("#skip2-list li")).to_have_count(1)
    expect(page.locator("#skip2-list li")).to_contain_text("scanned_sample.pdf")
    expect(page.locator("#skip2-list li")).to_contain_text("1 ページ")
    # モーダルの間は手順 1 のまま
    expect(page.locator('[data-screen="1"]')).to_have_class(re.compile("on"))
    # OK 専用: Esc (2 回押しても) では閉じず、手順 1 に留まる
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")
    expect(dialog).to_be_visible()
    expect(page.locator('[data-screen="1"]')).to_have_class(re.compile("on"))
    # 背景クリック (backdrop) でも閉じない
    page.mouse.click(5, 5)
    expect(dialog).to_be_visible()
    page.click("#skip2-go")
    expect(dialog).to_be_hidden()
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
    expect(page.locator('#stepbar .step[data-step="2"]')).to_be_hidden()

    # 「戻る」は手順 1 へ (手順 2 を飛ばしたので)
    page.click("#btn-back")
    expect(page.locator('[data-screen="1"]')).to_have_class(re.compile("on"))
    # もう一度「次へ」でも案内は出る (OK を押すまで進めないのは同じ)
    page.click("#btn-next")
    expect(dialog).to_be_visible()
    page.click("#skip2-go")
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))

    # 手順 3 から「書き出しへ」で手順 4
    page.click("#btn-next")
    expect(page.locator('[data-screen="4"]')).to_have_class(re.compile("on"))
    expect(page.locator("#export-summary")).to_contain_text("対象外 1")
    # ステップバーの 2 は表示されない（クリック不可そのものは state.js 単体の stepAllowed(2) で固定）
    expect(page.locator('#stepbar .step[data-step="2"]')).to_be_hidden()
    # 手順 4 の「戻る」は手順 3 のまま (手順 2 の省略は 3→1 だけに効く)
    page.click("#btn-back")
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))


def test_mixed_scanned_and_vector_pdfs_hide_scanned_rows_without_a_dialog(e2e_page, scanned_pdf, vector_pdf):
    """スキャン PDF とベクター PDF が混在するときはモーダルを出さず手順 2 へ進む。

    スキャンページはレールに出ず、手順 2 に入った時点の表示ページはベクター側になる
    (スキャンを先に読み込んで通し index 0 がスキャンページになる構成で確かめる)。
    """
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files([str(scanned_pdf), str(vector_pdf)])
    expect(page.locator("#filelist-count")).to_contain_text("2 ファイル", timeout=30_000)
    expect(page.locator("#toast")).to_contain_text("1 ページはスキャン画像のため", timeout=30_000)
    # 混在ならステップバーの 2 は残る
    expect(page.locator('#stepbar .step[data-step="2"]')).to_be_visible()
    expect(page.locator("#scan-skipnote")).to_be_hidden()

    page.click("#btn-next")
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))
    expect(page.locator("#skip2-dialog")).to_be_hidden()
    # レールにはベクター PDF の 1 行だけ。スキャン PDF はファイル行ごと出ない
    expect(page.locator("#pagenav .pg-row2")).to_have_count(1)
    expect(page.locator("#pagenav .pl-file")).to_have_count(1)
    expect(page.locator("#pagenav .pl-file")).to_contain_text("vector_sample.pdf")
    # 表示中のページはスキャンページ (通し 0) ではなくベクター側
    expect(page.locator("#pgnav-2 .pj-file")).to_have_value("1")
    assert page.evaluate("() => window.__state.page") == 1
    assert page.evaluate("() => window.__state.status2") == ["na", "none"]
    # 手順 2 上部のまとめにも「対象外 1」
    expect(page.locator("#pagenav .pl-title")).to_contain_text("対象外 1")

    # 手順 3 へ進み、戻ると手順 2 のベクターページに戻る (3→2 のまま)
    page.click("#btn-next")
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
    page.click("#btn-back")
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))
    assert page.evaluate("() => window.__state.page") == 1


def test_dialog_closed_after_a_vector_pdf_was_added_lands_on_step2(e2e_page, scanned_pdf, vector_pdf):
    """案内モーダルの表示中に文字を持つ PDF が加わったら、閉じたときは手順 2 へ進む。

    モーダルは手順 1 を離れる前に出すだけで、進行中の読み込み (`addFiles`) は止めない。
    行き先を開いた時点の状態で決め打ちすると、混在になったのに手順 2 を飛ばしてしまう。
    """
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(str(scanned_pdf))
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル", timeout=30_000)

    page.click("#btn-next")
    dialog = page.locator("#skip2-dialog")
    expect(dialog).to_be_visible()

    # モーダル表示中にベクター PDF を足す。モーダルは背景を inert にするため実クリックは
    # 届かないが、スクリプトからの `click()` は inert でも通る (hit-test とフォーカスだけが
    # 止まる)。これで実際の `addFiles` → `reloadState` の経路がモーダルの裏で走る。
    with page.expect_file_chooser() as fc2_info:
        page.evaluate("() => document.getElementById('btn-pick').click()")
    fc2_info.value.set_files(str(vector_pdf))
    expect(page.locator("#filelist-count")).to_contain_text("2 ファイル", timeout=30_000)
    # 読み込みが済んでもモーダルは開いたまま (閉じるのは利用者の OK だけ)
    expect(dialog).to_be_visible()
    # 一覧は開いた時点のもの (足したベクター PDF は載らない)
    expect(page.locator("#skip2-list li")).to_have_count(1)

    page.click("#skip2-go")
    expect(dialog).to_be_hidden()
    # 混在になっているので手順 3 ではなく手順 2 へ進む
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))
    # 表示ページは対象外 (通し 0 のスキャンページ) を避けてベクター側へ寄る
    assert page.evaluate("() => window.__state.page") == 1


def test_page_jump_moves_by_number_and_arrows_including_pages_hidden_from_the_rail(e2e_page, ocr_layer_two_page_pdf):
    """画面下の「ページへ移動」: 番号 + 移動 / Enter / 前後ボタンで表示ページが変わる。
    手順 2 のレールは辞書に一致したページだけを出すが、移動はどのページへも効く。"""
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(str(ocr_layer_two_page_pdf))
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル", timeout=30_000)
    page.click("#btn-next")
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))
    # 辞書が空なのでレールに行は無いが、番号で 2 ページ目へ行ける
    expect(page.locator("#pagenav .pg-row2")).to_have_count(0)
    page.fill("#pgnav-2 .pj-num", "2")
    page.click("#pgnav-2 .pj-go")
    assert page.evaluate("() => window.__state.page") == 1
    expect(page.locator("#pgnav-2 .pj-num")).to_have_value("2")
    # 前へ
    page.click('#pgnav-2 [data-pj="prev"]')
    assert page.evaluate("() => window.__state.page") == 0
    # Enter でも移動。範囲外は端に丸める
    page.fill("#pgnav-2 .pj-num", "9")
    page.press("#pgnav-2 .pj-num", "Enter")
    assert page.evaluate("() => window.__state.page") == 1
    expect(page.locator('#pgnav-2 [data-pj="next"]')).to_be_disabled()
    # 手順 3 でも同じ部品
    page.click("#btn-next")
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
    expect(page.locator("#pgnav-3 .pj-num")).to_have_value("1")
    page.click('#pgnav-3 [data-pj="next"]')
    expect(page.locator("#pgnav-3 .pj-num")).to_have_value("2")
