# =============================================================================
# test_zzz_grapheditor_coverage_gate.py — svg-policy / leader_geom のカバレッジゲート
# =============================================================================
# ファイル名の zzz は意図的: pytest の同一ディレクトリ収集はファイル名順のため、
# 単体移植テスト群の実行後にカバレッジを判定する（設計書 §4.3。旧 vitest 85% ゲートの
# 後継。閾値は新実装の実測値の直下へ校正して固定する）。
# ⚠ 部分実行（-k で単体を除外した場合等）では母数に対して実行が欠け偽赤になる。
# このゲートは全単体実行（既定収集）でのみ意味を持つ。
# 閾値は実測値 − 5 ポイント(小数切り捨て)で固定している(実測記録はマスター計画
# `docs/superpowers/plans/2026-08-28-phase3-graph-editor-tests.md` 末尾参照)。マージンの
# 射程は Edge 版差等のゆらぎ吸収であり、~10 行未満の小さな未実行追加は検出できない
# （旧 85% 固定も同等の粒度） — ゲートの主眼は denylist 化・大ブロック退行の検出で、
# 細粒度の網は単体 75 件そのものが担う。
import os

import pytest

from grapheditor_v8_coverage import (
    assert_bmp_only,
    assert_no_block_comment_in_literals,
    line_and_function_coverage,
)

pytestmark = pytest.mark.browser

TARGETS = {
    "/js/svg-policy.js": ("svg-policy.js", 92.0, 95.0),
    "/lib/leader_geom.cjs": ("leader_geom.cjs", 87.0, 95.0),
}


def test_editor_js_coverage_gate(coverage_collector):
    result = coverage_collector.take()
    for suffix, (name, line_min, func_min) in TARGETS.items():
        matches = [sc for sc in result if sc["url"].endswith(suffix)]
        assert matches, f"{name} のカバレッジが無い(URL 経由で読込まれていない?)"
        assert len(matches) == 1, f"{name} が複数回読込まれている(母数が壊れる — 読込ガードの退行)"
        src_path = os.path.join(
            os.path.dirname(__file__), "..", "resources", "web",
            suffix.lstrip("/").replace("/", os.sep))
        source = open(src_path, encoding="utf-8").read()
        assert_bmp_only(source, name)
        assert_no_block_comment_in_literals(source, name)
        line_pct, func_pct = line_and_function_coverage(source, matches[0]["functions"])
        assert line_pct >= line_min, f"{name} 行カバレッジ {line_pct:.1f}% < {line_min}%"
        assert func_pct >= func_min, f"{name} 関数カバレッジ {func_pct:.1f}% < {func_min}%"
