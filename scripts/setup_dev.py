#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""python-tools の開発環境セットアップ (`setup-dev.bat` から起動)。

行うこと:
  1. `py -3.13` と Microsoft Edge の存在確認 (どちらもこのリポの前提)。
  2. requirements の形式検査 (`check_requirements`)。
  3. requirements を PyPI から `pip` で導入する。列挙は
     `git ls-files -- '*requirements.txt'`(ハードコードしない。ファイルが増減しても追随する)。
  4. docs の mermaid ランタイムを GitHub Releases から取得する (`fetch_docs_vendor`)。
     取得できなくても警告に留めて続行する — docs の HTML ビルドだけが要る依存で、
     未配置時は整形コード表示へフォールバックするため。
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
PYTHON_VERSION = "3.13"
HOOKS_PATH = "scripts/hooks"

# `setup-dev.bat` はスクリプト直接起動 (`py -3.13 "%~dp0scripts\setup_dev.py"`) のため
# `sys.path[0]` は既に `scripts/` になっているが、`pytest` 等の別経路からの import でも
# 同様に解決できるよう明示しておく。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_docs_vendor  # noqa: E402
from check_requirements import assert_requirements_file  # noqa: E402


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


# ── 2. requirements ──
def list_requirements() -> list[Path]:
    """`*requirements.txt` を git 管理対象から動的に列挙する (ハードコードしない)。

    列挙は `-z` (NUL 区切り) 出力を使う。git は既定 (`core.quotepath=true`) では非 ASCII
    パスを引用符 + 8 進エスケープした文字列で返し、`ROOT / line` が実在しないパスになって
    黙って install 対象から落ちる (実証済み)。`-z` は `core.quotepath` の設定に関わらず
    エスケープなしの生バイト列を NUL 区切りで返すため、この問題が構造的に起きない。
    同型の修正が `scripts/check_comments.py` (`_staged_files`)・
    `scripts/check_requirements.py` (`find_pip_call_files`) の計 3 箇所にある。
    """
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", "*requirements.txt"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        # `encoding` を明示しないと Windows既定ロケール(cp932 等)で decode され、`git` が
        # 出す UTF-8 出力で読み取りスレッド内 `UnicodeDecodeError` になりうる。
        encoding="utf-8",
        errors="replace",
    )
    files = [ROOT / p for p in out.stdout.split("\0") if p]
    return sorted(files, key=lambda p: p.relative_to(ROOT).as_posix())


def check_requirements(requirements: list[Path]) -> None:
    """requirements ファイルが「名前 + バージョン指定子」だけで書かれているかを検査する。

    `--find-links` / 直 URL 参照 / ローカルパス等のオプション行が 1 行でも混入すると、
    pip の解決先そのものを差し替えられる。検査本体は `check_requirements.py` の
    `assert_requirements_file` に集約する(venv ビルド (`scripts/lib/build_venv.py`) 等の
    他の pip 入口と**同じ契約**(検査に落ちたら `RuntimeError` を送出する。`SystemExit` に
    しない理由は `assert_requirements_file` の docstring 参照)。呼び出し側 (`main`) が
    `RuntimeError` を捕捉して終了コード化する。
    """
    for req in requirements:
        assert_requirements_file(req)


# ── 3. セットアップ本体 ──
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    return parser.parse_args(argv)


def build_pip_command(py: list[str], requirements: list[Path]) -> list[str]:
    """requirements を PyPI から導入する pip 呼び出しを組み立てる。

    索引を塞ぐ引数は付けない。解決先を差し替える形の混入は、呼び出しの前に通す
    `check_requirements` (`assert_requirements_file`) が requirements 側で止める。
    """
    cmd = [*py, "-m", "pip", "install"]
    for req in requirements:
        cmd += ["-r", str(req)]
    return cmd


def main() -> int:
    parse_args()

    py = resolve_python()
    check_edge()

    requirements = list_requirements()
    if not requirements:
        print("[error] requirements.txt が 1 件も見つかりません (git ls-files の結果が空)。", file=sys.stderr)
        return 1

    check_requirements(requirements)
    _run(build_pip_command(py, requirements))

    # docs の mermaid ランタイム。取得できなくてもセットアップは成功で終える。
    vendor_ok = fetch_docs_vendor.fetch()

    _run(["git", "config", "core.hooksPath", HOOKS_PATH])

    print()
    print("=" * 60)
    print(" python-tools 開発環境セットアップ完了")
    print("=" * 60)
    print(f"  Python       : {' '.join(py)}")
    print("  導入元       : PyPI (オンライン)")
    print(f"  requirements : {len(requirements)} 件")
    for req in requirements:
        print(f"    - {req.relative_to(ROOT).as_posix()}")
    print(f"  docs vendor  : {'配置済み' if vendor_ok else '未取得 (mermaid 図は整形コード表示)'}")
    print(f"  git hooksPath: {HOOKS_PATH} (pre-commit でコメント規約を検査)")
    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
