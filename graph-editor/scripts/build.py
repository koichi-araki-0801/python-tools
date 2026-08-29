#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LabelEditor (SVG ラベル位置エディタ) の配布 exe を隔離 venv 内でビルドする。

共通ライブラリ `scripts/lib/build_venv.py` で隔離 venv (`.venv-build`) を用意し、
wheelhouse から (オフライン専用・fail-closed) 依存を install した後、PyInstaller の
`--onefile` で `dist/LabelEditor.exe` (単一ファイル、実行に Python 不要) を生成する。
venv 準備ロジックは pdf-to-svg の同名スクリプトと共通化してある。

設計: ブラウザエンジンは同梱しない。exe は小さなローカル HTTP サーバを起動し、OS の Edge を
アプリモードで開く。ファイル入出力は `<input>` (開く) / ダウンロード (保存) 固定
(File System Access API は VDI で不安定なため不使用)。WebView2 ランタイムを同梱しないため
小さい (~10MB)。

作業ディレクトリはプロジェクトルート (`graph-editor/`) へ固定して PyInstaller を呼ぶ
(`--add-data` の相対元 `resources/web/*`、`app.py`、出力 `dist/` の相対前提を保つため)。

使い方: `py -3.13 graph-editor/scripts/build.py [clean] [--no-pause]`
(`build.bat` から `graph-editor\\scripts\\build.bat [clean]` で呼ぶのが通常の入口)。
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
        print(" [2/2] exe をビルド (PyInstaller, 単一ファイル)")
        print("=" * 44)
        result = subprocess.run(
            [
                str(venv_python),
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onefile",
                "--windowed",
                "--name",
                "LabelEditor",
                "--add-data",
                "resources/web/ui.html;.",
                "--add-data",
                "resources/web/styles.css;.",
                "--add-data",
                "resources/web/js;js",
                "--add-data",
                "resources/web/lib/leader_geom.cjs;lib",
                "app.py",
            ],
            cwd=PROJECT_DIR,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "ビルドに失敗しました。LabelEditor.exe 実行中なら閉じて再実行してください"
                "(上書き不可)。"
            )

        print()
        print("完成: dist/LabelEditor.exe (単一ファイル, ~10MB)")
        print("  配布: このファイルを渡すだけ。受け取り側はダブルクリックで Microsoft Edge の")
        print("        アプリウィンドウが開きます (Windows 10/11 標準の Edge を使用, 追加導入不要)。")
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
