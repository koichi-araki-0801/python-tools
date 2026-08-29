#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""共通ライブラリ: Python exe ビルド用の隔離 venv 準備。

`graph-editor/scripts/build.py` / `pdf-to-svg/scripts/build.py` から import して使う
(両者でほぼ同一だった venv 作成〜wheel install ロジックを 1 か所へ集約。monorepo
`scripts/lib/build-python-venv.ps1` の移植)。

**wheelhouse は必須 (fail-closed)。** monorepo 版はオンライン `pip install` へのフォール
バックを持っていたが、本リポでは意図的に落とす。フォールバックを残すと「オフラインで
組み立てられる」という前提を検証しないまま実行が通ってしまい、依存が知らぬ間にネット
ワーク上のパッケージへ差し替わりうる (requirements の形式検査は `--find-links` 等の混入を
防ぐが、wheelhouse 自体が無ければ検査の意味が無い)。ビルドできない状態は「ビルドできない」
と明示して止めることを選ぶ。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from check_requirements import assert_requirements_file  # noqa: E402


def resolve_python_launcher() -> list[str] | None:
    """`py -3` (Windows ランチャ) を優先し、無ければ `python`。

    双方とも起動しなければ `None` を返す (呼び出し側でビルドを中断させる)。
    """
    for exe, base_args in (("py", ["-3"]), ("python", [])):
        launcher = shutil.which(exe)
        if launcher is None:
            continue
        probe = subprocess.run([launcher, *base_args, "--version"], capture_output=True)
        if probe.returncode == 0:
            return [launcher, *base_args]
    return None


def require_wheelhouse(wheelhouse_dir: Path) -> None:
    """`wheelhouse_dir` が無ければ `RuntimeError`。**fail-closed の唯一の入口。**"""
    if not wheelhouse_dir.is_dir():
        raise RuntimeError(
            f"wheelhouse がありません: {wheelhouse_dir}\n"
            "  本リポは wheelhouse 必須(fail-closed)。オンライン fallback は行わない"
            "(オフラインで組み立てられることを隠さないため)。先に offline\\setup-offline.bat"
            " 等で wheelhouse を用意すること。"
        )


def build_venv(
    project_dir: Path,
    requirements_path: Path,
    wheelhouse_dir: Path,
    *,
    clean: bool = False,
) -> Path:
    """ビルド専用の隔離 venv (`.venv-build`) を用意し、依存を install して venv の
    `python.exe` を返す。

    端末のグローバル Python には無関係なライブラリが多数入っており、そのままビルドすると
    PyInstaller が拾って exe に余計な依存が混入する。専用 venv は既定でシステムの
    site-packages を参照しないため、必要な依存だけのクリーンな環境でビルドでき肥大化を防ぐ。
    """
    launcher = resolve_python_launcher()
    if launcher is None:
        raise RuntimeError("Python が見つかりません。Python を導入し PATH を通して再実行してください。")

    venv_dir = project_dir / ".venv-build"
    venv_python = venv_dir / "Scripts" / "python.exe"

    if clean and venv_dir.is_dir():
        print("[setup] ビルド venv を作り直します (clean)...")
        shutil.rmtree(venv_dir)

    # 既存 venv の健全性チェック。python.exe が無い/実際に起動しない場合は壊れているとみなす
    # (存在チェックだけだと不完全/破損 venv の上に `-m venv` を実行して失敗するため)。
    venv_ok = False
    if venv_python.is_file():
        probe = subprocess.run([str(venv_python), "--version"], capture_output=True)
        venv_ok = probe.returncode == 0
    if not venv_ok:
        if venv_dir.is_dir():
            print("[setup] 既存ビルド venv が不完全なため作り直します...")
            shutil.rmtree(venv_dir)
        print("[setup] 隔離ビルド venv (.venv-build) を作成中...")
        result = subprocess.run([*launcher, "-m", "venv", str(venv_dir)])
        if result.returncode != 0:
            raise RuntimeError("ビルド venv の作成に失敗しました。")

    # requirements の形式検査。**pip へ渡すすべての入口で行う** (検査が一部の入口にしか
    # 無いと、そこを迂回する経路が素通りする)。`--no-index` は requirements 内の
    # `--find-links <URL>` や直 URL 参照を止めないので、オフラインでも省略できない。
    assert_requirements_file(requirements_path)

    print("=" * 44)
    print(" [1/2] 依存ライブラリをインストール (隔離 venv 内)")
    print("=" * 44)
    require_wheelhouse(wheelhouse_dir)
    print(f"[setup] オフライン wheelhouse から install: {wheelhouse_dir}")
    result = subprocess.run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(wheelhouse_dir),
            "-r",
            str(requirements_path),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError("依存のインストールに失敗しました。")

    return venv_python
