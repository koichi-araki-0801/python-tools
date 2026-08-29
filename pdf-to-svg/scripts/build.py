#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PdfToSvg の配布 exe を隔離 venv 内でビルドする。

共通ライブラリ `scripts/lib/build_venv.py` で隔離 venv (`.venv-build`) を用意し、
wheelhouse から (オフライン専用・fail-closed) 依存を install した後、PyInstaller で
`dist/PdfToSvg/PdfToSvg.exe` を生成する。venv 準備ロジックは graph-editor の同名スクリプトと
共通化してある。ビルド引数の実体は `packaging/pdftosvg.spec` 側が持ち、本スクリプトは
spec ファイルを渡すだけ。

作業ディレクトリはプロジェクトルート (`pdf-to-svg/`) へ固定して PyInstaller を呼ぶ
(`--distpath dist` / `--workpath build` の相対前提を保つため)。

使い方: `py -3.13 pdf-to-svg/scripts/build.py [clean] [--no-pause]`
(`build.bat` から `pdf-to-svg\\scripts\\build.bat [clean]` で呼ぶのが通常の入口)。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
WORKSPACE = PROJECT_DIR.parent
WHEELHOUSE = WORKSPACE / "python-wheelhouse"
REQUIREMENTS = PROJECT_DIR / "requirements.txt"

sys.path.insert(0, str(WORKSPACE / "scripts" / "lib"))
from build_venv import build_venv  # noqa: E402


def _pause(message: str = "続行するには Enter キーを押してください . . . ") -> None:
    # 旧 `build.bat` の `cmd /c pause` に相当。ダブルクリック起動でウィンドウが
    # 即閉じしないよう待つ。
    try:
        input(message)
    except EOFError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default=None, help="`clean` を渡すと venv を作り直す")
    parser.add_argument(
        "--no-pause", action="store_true", help="完了/失敗時の一時停止を抑止する (CI・自動実行用)"
    )
    args = parser.parse_args(argv)

    try:
        venv_python = build_venv(
            PROJECT_DIR, REQUIREMENTS, WHEELHOUSE, clean=(args.action == "clean")
        )

        print()
        print("=" * 44)
        print(" [2/2] exe をビルド (PyInstaller)")
        print("=" * 44)
        result = subprocess.run(
            [
                str(venv_python),
                "-m",
                "PyInstaller",
                "packaging/pdftosvg.spec",
                "--clean",
                "--noconfirm",
                "--distpath",
                "dist",
                "--workpath",
                "build",
            ],
            cwd=PROJECT_DIR,
        )
        if result.returncode != 0:
            raise RuntimeError("ビルドに失敗しました。")

        print()
        print("=" * 44)
        print(" 完成: dist/PdfToSvg/PdfToSvg.exe")
        print("=" * 44)
    except Exception as exc:  # noqa: BLE001 - ダブルクリック起動時にエラーを画面へ出す
        print()
        print(f"[エラー] {exc}")
        if not args.no_pause:
            _pause()
        return 1

    if not args.no_pause:
        _pause()
    return 0


if __name__ == "__main__":
    sys.exit(main())
