#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pre-push フック本体。push 対象がタグのみなら pytest 一式をスキップする。

`scripts/hooks/pre-push`(sh シム。`git config core.hooksPath scripts/hooks` で有効化する)
から `py -3.13` で起動される。git は push 対象 ref を stdin へ
`<local ref> <local sha> <remote ref> <remote sha>` の行で渡す(`githooks(5)` の pre-push 節)。

判定ロジックは monorepo `scripts/pre-push.mjs` の `decidePrePushAction` /
`countAheadOfUpstream` と同型: `offline/publish_bundle.py --tag-only` はローリングタグ
(`offline-bundle-v1`)を `post_commit.py` からコミットのたび呼ぶため、タグのみの push まで
フルテストを発火させると、コミットごとに数分ブロックされる(monorepo で実害済みの障害と
同型)。stdin に ref が 1 行も無いとき(空 stdin 等)は「対象なし」と決め打たず、
upstream との実差分(`git rev-list --count @{u}..HEAD`)で安全側に判定する。

ブランチ push(タグ以外を 1 つでも含む push)では次を順に実行し、1 つでも失敗したら
以降を走らせず終了コードをそのまま返す。`pdf-to-svg` と `graph-editor` の `test/` は
同名モジュール(`test_edge_launch.py` 等)を含むため、1 回の `pytest` 呼び出しへ
まとめない(import file mismatch。README の検証コマンドと同じ個別実行)。
  1. `pytest scripts`
  2. `pytest docs/_build`
  3. `pytest pdf-to-svg`
  4. `pytest graph-editor`
  5. `pytest pdf-to-svg -m e2e`
  6. `pytest graph-editor -m e2e`
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# 実行順(README の個別検証コマンドと同じ並び)。要素は `python -m pytest` へ渡す追加引数。
PYTEST_STEPS: tuple[tuple[str, ...], ...] = (
    ("scripts",),
    ("docs/_build",),
    ("pdf-to-svg",),
    ("graph-editor",),
    ("pdf-to-svg", "-m", "e2e"),
    ("graph-editor", "-m", "e2e"),
)


def parse_remote_refs(stdin_text: str) -> list[str]:
    """stdin のペイロードから push 先(3 列目 = remote ref)の一覧を取り出す。"""
    refs: list[str] = []
    for line in stdin_text.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            refs.append(parts[2])
    return refs


def count_ahead_of_upstream(*, cwd: Path = ROOT) -> int | None:
    """`@{u}` に対する HEAD の先行コミット数。upstream 未設定や git 失敗は `None`
    (呼び出し側が安全側 = 実行へ倒す)。"""
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "@{u}..HEAD"],
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            # `git` の出力は decimal 数値のみで実害は無いが、`default_runner`
            # (`post_commit.py`)と同じ規約(Windows既定ロケールでの誤 decode を避ける)へ
            # 一貫させておく。
            encoding="utf-8",
            errors="replace",
        )
    except (subprocess.CalledProcessError, OSError):
        return None
    try:
        n = int(result.stdout.strip())
    except ValueError:
        return None
    return n if n >= 0 else None


def decide_pre_push_action(remote_refs: list[str], ahead: int | None) -> str:
    """push 内容から pytest 一式の要否を決める。'run' = 実行 / 'skip' = 実行しない。

    - ref を 1 つでも含む push はタグのみのときだけ 'skip'(ブランチ ref が 1 つでも
      混じっていれば 'run')。
    - ref が空のとき(空 stdin 等)は `ahead` で判定する。`ahead` が取れない場合は
      安全側で 'run'。
    """
    if remote_refs:
        tag_only = all(ref.startswith("refs/tags/") for ref in remote_refs)
        return "skip" if tag_only else "run"
    if ahead is None:
        return "run"
    return "run" if ahead > 0 else "skip"


def run_pytest_suite(*, cwd: Path = ROOT) -> int:
    """`PYTEST_STEPS` を順に実行する。各ステップの所要を出力し、失敗したら即座に返す。"""
    for extra in PYTEST_STEPS:
        cmd = [sys.executable, "-m", "pytest", *extra]
        print(f"[pre-push] $ {' '.join(cmd)}")
        started = time.monotonic()
        result = subprocess.run(cmd, cwd=cwd)
        elapsed = time.monotonic() - started
        print(f"[pre-push]   -> {elapsed:.1f}s (exit {result.returncode})")
        if result.returncode != 0:
            return result.returncode
    return 0


def main() -> int:
    # Windows既定コンソール (cp932 等) では Japanese メッセージが UnicodeEncodeError で
    # 出力を落としうる。フック失敗時の案内を確実に出すため UTF-8 へ固定する。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    stdin_text = sys.stdin.read()
    remote_refs = parse_remote_refs(stdin_text)
    ahead = None if remote_refs else count_ahead_of_upstream()
    action = decide_pre_push_action(remote_refs, ahead)

    if action == "skip":
        why = f"タグのみ ({', '.join(remote_refs)})" if remote_refs else "push 対象なし(upstream と差分なし)"
        print(f"[pre-push] {why} -> pytest をスキップします")
        return 0

    if not remote_refs:
        detail = "upstream 先行数が取れない" if ahead is None else f"upstream より {ahead} コミット先行"
        print(f"[pre-push] stdin に ref が無いが{detail} -> 安全側で pytest を実行します")

    started = time.monotonic()
    code = run_pytest_suite()
    elapsed = time.monotonic() - started
    print(f"[pre-push] pytest 一式 合計 {elapsed:.1f}s (exit {code})")
    if code != 0:
        print(
            "[pre-push] pytest が失敗しました。上記を修正してから push してください。",
            file=sys.stderr,
        )
    return code


if __name__ == "__main__":
    sys.exit(main())
