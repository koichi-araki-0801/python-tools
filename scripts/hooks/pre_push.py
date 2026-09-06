#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pre-push フック本体。check_comments と pytest 一式を順に実行する。

`scripts/hooks/pre-push`(sh シム。`git config core.hooksPath scripts/hooks` で有効化する)
から `py -3.13` で起動される。

次を順に実行し、1 つでも失敗したら以降を走らせず終了コードをそのまま返す。`pdf-to-svg` と
`graph-editor` の `test/` は
同名モジュール(`test_edge_launch.py` 等)を含むため、1 回の `pytest` 呼び出しへ
まとめない(import file mismatch。README の検証コマンドと同じ個別実行)。
  0. `python scripts/check_comments.py`(フルツリー。I-5: pre-commit フックは `--staged`
     でステージ済みファイルだけを見るため、`--no-verify`・`core.hooksPath` 未設定 clone・
     非 ASCII パスの quotepath 問題(I-1)のいずれでも素通りしうる。push 前に全ツリーを
     検査し直し、失敗したら pytest 一式は走らせない)
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
CHECK_COMMENTS_SCRIPT = ROOT / "scripts" / "check_comments.py"

# 実行順(README の個別検証コマンドと同じ並び)。要素は `python -m pytest` へ渡す追加引数。
PYTEST_STEPS: tuple[tuple[str, ...], ...] = (
    ("scripts",),
    ("docs/_build",),
    ("pdf-to-svg",),
    ("graph-editor",),
    ("pdf-to-svg", "-m", "e2e"),
    ("graph-editor", "-m", "e2e"),
)


def run_check_comments(*, cwd: Path = ROOT) -> int:
    """`scripts/check_comments.py` をフルツリー(`--staged` 無し)で実行する(I-5)。

    pre-commit フック(`pre_commit.py`)は `--staged` でステージ済みファイルだけを見るため、
    `--no-verify`・`core.hooksPath` 未設定 clone・非 ASCII パスの quotepath 問題(I-1)の
    いずれでも素通りしうる。push 前に全ツリーを検査し直すことで、pre-commit 1 箇所だけが
    強制点という「常に緑のガード」化を避ける。
    """
    cmd = [sys.executable, str(CHECK_COMMENTS_SCRIPT)]
    print(f"[pre-push] $ {' '.join(cmd)}")
    started = time.monotonic()
    result = subprocess.run(cmd, cwd=cwd)
    elapsed = time.monotonic() - started
    print(f"[pre-push]   -> {elapsed:.1f}s (exit {result.returncode})")
    return result.returncode


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
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    started = time.monotonic()
    code = run_check_comments()
    if code == 0:
        code = run_pytest_suite()
    elapsed = time.monotonic() - started
    print(f"[pre-push] 検証一式 合計 {elapsed:.1f}s (exit {code})")
    if code != 0:
        print("[pre-push] 検証が失敗しました。上記を修正してから push してください。", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
