#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""docs の mermaid ランタイムを GitHub Releases から取得し `docs/_build/vendor/` へ置く。

`setup-dev.bat`(`scripts/setup_dev.py`)から呼ばれるのが通常の入口で、単独実行もできる
(`py -3.13 scripts\\fetch_docs_vendor.py`)。

取得先はソース内の定数で固定する。`git remote` から組み立てると、fork やミラーから clone した
端末が別の配布物を掴む。

正典は `docs/_build/vendor/manifest.txt`(git 管理下)で、そこに書かれた sha256 と突き合わせて
初めて配置する。Release に併置するハッシュのサイドカーはアセットと同じ場所にあるため転送破損の
検知にしかならず、置かない。

配置は「全件が manifest と一致したときだけ」行う。1 件でも不一致・不足・想定外があれば既存の
配置物に触れずに失敗を返す。不一致で古い配置を消すと、それまで揃っていた vendor を失うだけで
何も得られない。

vendor は docs の HTML ビルドだけが要る依存で、`md2html.py` は未配置時に整形コード表示へ
フォールバックする。そのため `setup_dev.py` からの経路では失敗を警告に留める(戻り値 `False`)。
単独実行のときだけ終了コード 1 とする。
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = ROOT / "docs" / "_build" / "vendor"
MANIFEST = VENDOR_DIR / "manifest.txt"

OWNER = "koichi-araki-0801"
REPO = "python-tools"
TAG = "docs-vendor-v1"
ASSET_NAME = "docs-vendor.tar.gz"

DOWNLOAD_TIMEOUT_SECONDS = 120
_CHUNK = 1024 * 1024


def asset_url(owner: str = OWNER, repo: str = REPO, tag: str = TAG, asset: str = ASSET_NAME) -> str:
    return f"https://github.com/{owner}/{repo}/releases/download/{tag}/{asset}"


def parse_manifest(text: str) -> dict[str, str]:
    """manifest.txt から `{ファイル名: sha256}` を読む。

    有意行は空白区切りで、先頭トークンがファイル名、`sha256=` で始まるトークンが期待値。
    `version=` / `source=` のような他のトークンは無視する(トークンが増えても壊れない)。
    """
    entries: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens = line.split()
        digest = None
        for token in tokens[1:]:
            if token.startswith("sha256="):
                digest = token[len("sha256=") :].strip().lower()
        if digest:
            entries[tokens[0]] = digest
    return entries


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def vendor_is_current(vendor_dir: Path, expected: dict[str, str]) -> bool:
    """配置済みの実体が manifest と全件一致していれば True(取得を省略できる)。"""
    for name, digest in expected.items():
        path = vendor_dir / name
        if not path.is_file() or sha256_file(path) != digest:
            return False
    return True


def http_download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
        with dest.open("wb") as fh:
            shutil.copyfileobj(response, fh)


def _extract_expected_members(tar_path: Path, dest_dir: Path, expected: dict[str, str]) -> None:
    """manifest に載る通常ファイルだけを `dest_dir` へ展開する。

    メンバ名を許可リストと**完全一致**で照合するため、絶対パスや `..` を含む名前はそもそも
    一致せず落ちる(展開先を外へ逃がす経路が構造的に生じない)。`filter="data"` も併用する。
    """
    allowed = set(expected)
    with tarfile.open(tar_path, "r:gz") as tf:
        members = tf.getmembers()
        for member in members:
            if member.name not in allowed:
                raise RuntimeError(f"想定外のメンバを含みます: {member.name!r}")
            if not member.isfile():
                raise RuntimeError(f"通常ファイルでないメンバを含みます: {member.name!r}")
        missing = allowed - {member.name for member in members}
        if missing:
            raise RuntimeError(f"必要なファイルが足りません: {sorted(missing)}")
        tf.extractall(dest_dir, members=members, filter="data")


def _verify_extracted(dest_dir: Path, expected: dict[str, str]) -> None:
    for name, digest in expected.items():
        path = dest_dir / name
        if not path.is_file():
            raise RuntimeError(f"展開後に見つかりません: {name}")
        actual = sha256_file(path)
        if actual != digest:
            raise RuntimeError(f"sha256 が一致しません: {name} (期待 {digest} / 実際 {actual})")


def _place(stage_dir: Path, vendor_dir: Path, expected: dict[str, str]) -> None:
    """検証済みの実体を `vendor_dir` へ移す。

    いったん同一ディレクトリ内の `.new` へ全件を写してから `os.replace` で名前を差し替える。
    同一ディレクトリなので差し替えはアトミックで、途中で失敗しても既存の配置物は壊れない。
    """
    vendor_dir.mkdir(parents=True, exist_ok=True)
    staged: list[tuple[Path, Path]] = []
    try:
        for name in expected:
            temp_dest = vendor_dir / f"{name}.new"
            shutil.copyfile(stage_dir / name, temp_dest)
            staged.append((temp_dest, vendor_dir / name))
        for temp_dest, final_dest in staged:
            os.replace(temp_dest, final_dest)
    finally:
        for temp_dest, _final in staged:
            if temp_dest.exists():
                temp_dest.unlink()


def fetch(
    vendor_dir: Path = VENDOR_DIR,
    manifest_path: Path = MANIFEST,
    *,
    url: str | None = None,
    downloader: Callable[[str, Path], None] = http_download,
) -> bool:
    """Release から取得して配置する。成功なら True、失敗は理由を表示して False。"""
    try:
        expected = parse_manifest(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"[vendor] manifest を読めません: {exc}", file=sys.stderr)
        return False
    if not expected:
        print(f"[vendor] manifest に有効な行がありません: {manifest_path}", file=sys.stderr)
        return False

    if vendor_is_current(vendor_dir, expected):
        print(f"[vendor] 配置済み ({len(expected)} 件が manifest と一致) のため取得を省略します")
        return True

    try:
        with tempfile.TemporaryDirectory() as temp:
            temp_dir = Path(temp)
            archive = temp_dir / ASSET_NAME
            stage = temp_dir / "stage"
            stage.mkdir()
            downloader(url or asset_url(), archive)
            _extract_expected_members(archive, stage, expected)
            _verify_extracted(stage, expected)
            _place(stage, vendor_dir, expected)
    except Exception as exc:  # 取得経路の失敗はすべて警告へ倒す(セットアップは止めない)
        print(f"[vendor] 取得できませんでした: {exc}", file=sys.stderr)
        print(
            "[vendor] docs の HTML ビルドでは mermaid 図が整形コード表示になります"
            "(他の作業には影響しません)。",
            file=sys.stderr,
        )
        return False

    print(f"[vendor] {len(expected)} 件を配置しました: {vendor_dir}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    return 0 if fetch() else 1


if __name__ == "__main__":
    sys.exit(main())
