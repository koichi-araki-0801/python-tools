# =============================================================================
# test_grapheditor_e2e_capture_docs.py — 操作手順書向けスクリーンショット取得の移植(実 Edge)
# =============================================================================
# 旧 `capture_docs.e2e.ts`(Playwright/TS)からの 1:1 移植。旧は pie-chart のサンプル SVG
# (`pie-chart/out/svg_js/asset_balanced_8.svg` — git 非追跡の生成物)を読み `docs/graph-editor/images`
# へ 6 枚を直接上書きしていたが、フェーズ 4 のクリーンなリポジトリにはその生成物が存在しない。
#
# 本ファイルでは:
# - 入力 SVG は `test/fixtures/capture_asset_balanced_8.svg`(上記生成物のコミット複製。
#   byte 同一を fc.exe で確認済み)を読む。旧 TS はこの複製を参照しない(変更していない)。
# - 出力は **`tmp_path`(pytest 標準の一時ディレクトリ)へ撮る**。`docs/graph-editor/images` へは
#   書かない — 旧 TS の capture(実運用の再撮影経路)とこの新テストが同じ画像ファイルへ交互に
#   上書きすると、CI 実行順序によって片方の出力が握り潰される事故になる。docs への出力先切替は
#   フェーズ 5(旧 TS 撤去)で行う。
# - 断言は「6 ファイルが生成され各サイズ > 0」+ 旧テストが個別に持っていた断言(clip 済みの
#   panel_right ロケータスクリーンショット等)を逐語で踏襲する。
import os

import pytest

pytestmark = [pytest.mark.browser, pytest.mark.e2e]

_SVG_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "capture_asset_balanced_8.svg")
with open(_SVG_PATH, "r", encoding="utf-8") as _f:
    SVG = _f.read()


@pytest.fixture
def capture_page(edge_browser, e2e_server):
    """旧 `test.use({ viewport: { width: 1280, height: 820 } })` をこのファイル専用 fixture で写す。"""
    context = edge_browser.new_context(base_url=e2e_server, viewport={"width": 1280, "height": 820})
    page = context.new_page()
    yield page
    context.close()


def load_and_select(page):
    """サンプル SVG を読み込み、引出線を持つラベルを 1 つ選択した状態にする。"""
    page.goto("/ui.html")
    page.wait_for_function("() => !!window.__editor")
    # サンプル SVG を読み込ませる(実ファイル選択ダイアログを使わない)。
    page.evaluate(
        """
        (svg) => window.__editor.load({ name: "資産配分", id: 1, content: svg })
        """,
        SVG,
    )
    page.wait_for_function("() => window.__editor.labels?.length >= 2")
    # 引出線(曲点を含む点列)を持つラベルを優先して選択し、ハンドル 3 種を見せる。
    page.evaluate(
        """
        () => {
            const ed = window.__editor;
            const withLeader = ed.labels.find((l) => (l.leaderPts?.length ?? 0) >= 3);
            ed.selectLabel(withLeader ?? ed.labels[0]);
        }
        """
    )
    page.wait_for_timeout(400)


def selected_clip(page):
    """選択中ラベル(ハンドル込み)の周囲を切り出す clip 矩形を求める。"""
    box = page.evaluate(
        """
        () => {
            const g = document.querySelector("g.label[data-editor-sel]");
            const r = g.getBoundingClientRect();
            return { x: r.x, y: r.y, width: r.width, height: r.height };
        }
        """
    )
    pad = 90
    return {
        "x": max(0, box["x"] - pad),
        "y": max(0, box["y"] - pad),
        "width": box["width"] + pad * 2,
        "height": box["height"] + pad * 2,
    }


def _assert_nonempty(path):
    assert os.path.isfile(path)
    assert os.path.getsize(path) > 0


def test_capture_open_screen(capture_page, tmp_path):
    page = capture_page
    page.goto("/ui.html")
    page.wait_for_function("() => !!window.__editor")
    page.wait_for_timeout(300)
    out = tmp_path / "open_screen.png"
    page.screenshot(path=str(out))
    _assert_nonempty(out)


def test_capture_editor_main(capture_page, tmp_path):
    page = capture_page
    load_and_select(page)
    out = tmp_path / "editor_main.png"
    page.screenshot(path=str(out))
    _assert_nonempty(out)


def test_capture_handles_zoom_condense_zoom(capture_page, tmp_path):
    page = capture_page
    load_and_select(page)
    clip = selected_clip(page)
    handles_out = tmp_path / "handles_zoom.png"
    page.screenshot(path=str(handles_out), clip=clip)
    _assert_nonempty(handles_out)

    # 長体スライダを 70% へ(ユーザー操作と同じ input イベント経由で反映)。
    page.evaluate(
        """
        () => {
            const r = document.getElementById("scaleRange");
            r.value = "0.7";
            r.dispatchEvent(new Event("input", { bubbles: true }));
        }
        """
    )
    page.wait_for_timeout(400)
    condense_out = tmp_path / "condense_zoom.png"
    page.screenshot(path=str(condense_out), clip=clip)
    _assert_nonempty(condense_out)


def test_capture_panel_right(capture_page, tmp_path):
    page = capture_page
    load_and_select(page)
    out = tmp_path / "panel_right.png"
    page.locator(".panel").screenshot(path=str(out))
    _assert_nonempty(out)


def test_capture_save_screen(capture_page, tmp_path):
    page = capture_page
    load_and_select(page)
    page.evaluate("() => window.__editor.goPhase(3)")
    page.wait_for_timeout(300)
    out = tmp_path / "save_screen.png"
    page.screenshot(path=str(out))
    _assert_nonempty(out)
