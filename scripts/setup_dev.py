#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""python-tools の開発環境セットアップ (`setup-dev.bat` から起動)。

行うこと:
  1. `py -3.13` と Microsoft Edge の存在確認 (どちらもこのリポの前提)。
  2. `python-wheelhouse/` の存在確認。既定は fail-closed — 無ければ
     「先に offline\\setup-offline.bat を実行してください」と表示して失敗する
     (配布ストーリーの証明性を守る)。オンライン導入は `--online` を明示指定した時のみ。
  3. requirements の形式検査 (`check_requirements`)。
  4. requirements を `pip install --no-index --find-links python-wheelhouse` で導入する。
     列挙は `git ls-files -- '*requirements.txt'`(ハードコードしない。ファイルが増減しても
     追随する)。
  5. `git config core.hooksPath scripts/hooks` (コメント規約検査の pre-commit フックを有効化)。
  6. 実行内容のサマリを表示する。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WHEELHOUSE = ROOT / "python-wheelhouse"
PYTHON_VERSION = "3.13"
HOOKS_PATH = "scripts/hooks"

# `setup-dev.bat` はスクリプト直接起動 (`py -3.13 "%~dp0scripts\setup_dev.py"`) のため
# `sys.path[0]` は既に `scripts/` になっているが、`pytest` 等の別経路からの import でも
# 同様に解決できるよう明示しておく。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_requirements import check_requirements_file  # noqa: E402


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"[setup] $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run(cmd, check=True, cwd=ROOT, **kwargs)


# ── 1. 前提ツールの確認 ──
def resolve_python() -> list[str]:
    """`py -3.13` を解決する。無ければ中止する (このリポは Python 3.13 固定が前提)。"""
    launcher = shutil.which("py")
    if launcher is None:
        print(
            "[error] Python ランチャ `py` が見つかりません。Python 3.13 を導入し PATH を通してください。",
            file=sys.stderr,
        )
        sys.exit(1)
    probe = subprocess.run(
        [launcher, f"-{PYTHON_VERSION}", "--version"],
        capture_output=True,
        text=True,
        # `py --version` の出力は ASCII のみだが、`text=True` かつ `encoding` 未指定は
        # Windows既定ロケール依存で decode されるため、他の subprocess 呼び出しと同じ
        # 規約(UTF-8 固定)へ揃えておく(同一クラスの不具合の再発防止)。
        encoding="utf-8",
        errors="replace",
    )
    if probe.returncode != 0:
        print(
            f"[error] `py -{PYTHON_VERSION}` が起動しません。Python {PYTHON_VERSION} を導入してください。",
            file=sys.stderr,
        )
        sys.exit(1)
    version = (probe.stdout or probe.stderr).strip()
    print(f"[setup] Python: {version}")
    return [launcher, f"-{PYTHON_VERSION}"]


def check_edge() -> None:
    """pdf-to-svg / graph-editor は Edge シェル UI 前提のため、起動可否を先に確認する。"""
    program_files = [
        os.environ.get("PROGRAMFILES", r"C:\Program Files"),
        os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
    ]
    candidates = [Path(pf) / "Microsoft" / "Edge" / "Application" / "msedge.exe" for pf in program_files]
    found = any(c.is_file() for c in candidates) or shutil.which("msedge") is not None
    if not found:
        print(
            "[error] Microsoft Edge (msedge.exe) が見つかりません。pdf-to-svg / graph-editor は "
            "Edge シェル UI 前提のため、先に Edge を導入してください。",
            file=sys.stderr,
        )
        sys.exit(1)
    print("[setup] Edge: 検出しました")


# ── 2. wheelhouse / requirements ──
def check_wheelhouse(online: bool) -> None:
    if online:
        print("[setup] --online 指定: wheelhouse チェックを省略しオンラインで導入します")
        return
    if not WHEELHOUSE.is_dir():
        print(
            "[error] python-wheelhouse/ がありません。先に offline\\setup-offline.bat を"
            "実行してください。\n"
            "        (ネットワーク接続がある端末でオンライン導入したい場合のみ、"
            "本コマンドへ --online を明示指定してください)",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[setup] wheelhouse: {WHEELHOUSE}")


def list_requirements() -> list[Path]:
    """`*requirements.txt` を git 管理対象から動的に列挙する (ハードコードしない)。

    content-key 算出 (将来のオフラインバンドル構築) と同一集合を保つため、パス列は
    ここ 1 箇所からしか作らない。
    """
    out = subprocess.run(
        ["git", "ls-files", "--", "*requirements.txt"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        # `encoding` を明示しないと Windows既定ロケール(cp932 等)で decode され、`git` が
        # 出す UTF-8 出力で読み取りスレッド内 `UnicodeDecodeError` になりうる
        # (`offline/lib/bundle_common.py` の `list_requirements_files_via_git` と同一クラス)。
        encoding="utf-8",
        errors="replace",
    )
    files = [ROOT / line for line in out.stdout.splitlines() if line.strip()]
    return sorted(files, key=lambda p: p.relative_to(ROOT).as_posix())


def check_requirements(requirements: list[Path]) -> None:
    """requirements ファイルが「名前 + バージョン指定子」だけで書かれているかを検査する。

    `--find-links` / 直 URL 参照 / ローカルパス等のオプション行が 1 行でも混入すると、
    pip の解決先そのものを差し替えられる。検査本体は `check_requirements.py` の
    `check_requirements_file` に集約する (venv ビルド (`scripts/lib/build_venv.py`) と
    実装を共有し、入口ごとに検査ロジックが drift するのを防ぐ)。
    """
    ok = True
    for req in requirements:
        violations = check_requirements_file(req)
        if violations:
            ok = False
            for v in violations:
                print(f"[error] [requirements] {v}", file=sys.stderr)
    if not ok:
        print("[error] requirements の形式検査に失敗しました。上記を修正してください。", file=sys.stderr)
        sys.exit(1)


# ── 3. セットアップ本体 ──
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--online",
        action="store_true",
        help="wheelhouse を使わずオンラインで pip install する (明示 opt-in。既定は fail-closed)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    py = resolve_python()
    check_edge()
    check_wheelhouse(args.online)

    requirements = list_requirements()
    if not requirements:
        print("[error] requirements.txt が 1 件も見つかりません (git ls-files の結果が空)。", file=sys.stderr)
        return 1

    check_requirements(requirements)

    pip_cmd = [*py, "-m", "pip", "install"]
    if not args.online:
        pip_cmd += ["--no-index", "--find-links", str(WHEELHOUSE)]
    for req in requirements:
        pip_cmd += ["-r", str(req)]
    _run(pip_cmd)

    _run(["git", "config", "core.hooksPath", HOOKS_PATH])

    print()
    print("=" * 60)
    print(" python-tools 開発環境セットアップ完了")
    print("=" * 60)
    print(f"  Python       : {' '.join(py)}")
    print(f"  導入元       : {'オンライン (--online)' if args.online else WHEELHOUSE}")
    print(f"  requirements : {len(requirements)} 件")
    for req in requirements:
        print(f"    - {req.relative_to(ROOT).as_posix()}")
    print(f"  git hooksPath: {HOOKS_PATH} (pre-commit でコメント規約を検査)")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
