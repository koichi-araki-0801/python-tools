# -*- coding: utf-8 -*-
"""offline 重量物バンドルの取得・整合検査・展開(配布先のセットアップ)。

重量物(`python-wheelhouse/` + `docs/_build/vendor/` の mermaid JS)は git に入れず GitHub
Releases(タグ `offline-bundle-v1`)に置いてある。ソースコードは `git clone` で手元にある前提。

手順:
  1. リポジトリ直下(または `bk\\`)に `offline-deps-bundle.tar.gz` と `bundle.key` があれば
     それを使う。無ければ Release から HTTPS で直取得し(`gh` 不要。リポジトリは Public)、
     Release に並ぶ `.sha256` と突き合わせて転送破損を検知する。
  2. **展開の前に**、手元のソース(git 管理下の requirements.txt / manifest.txt)が重量物と
     対の組であることを `bundle.key`(content-key)で確認する。展開の後に測ると、バンドル
     同梱の manifest.txt が git 管理下の実体を上書きし、以後の照合が「バンドル自身との
     堂々巡り」になって manifest の差分を検知できなくなる。
  3. 展開する。

バンドルの真正性は検証しない。Release を更新できるのはリポジトリ所有者だけで、配布先は同じ
所有者の Public リポジトリを clone している前提で受け入れる。content-key の不一致は改ざんではなく
「依存を変えたのに publish していない」状態で、配布担当に
`local-only\\offline-publish\\publish-bundle.bat` の実行を依頼する。

HTTP 取得を行う関数は呼び出し側から差し替え可能にしている(単体テストは偽ダウンローダを注入し、
実ネットワークへはアクセスしない)。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(_HERE / "lib"))

import bundle_common  # noqa: E402

DEFAULT_OWNER = "koichi-araki-0801"
DEFAULT_REPO = "python-tools"

Downloader = Callable[[str, Path], None]

# GitHub Releases の 1 アセット上限(2GB)と同じ値で天井を切り、想定外の巨大応答を受け続けない。
_DOWNLOAD_TIMEOUT_SECONDS = 300
_MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024


# ── 手順1a: 手元のバンドル探索 ──


def find_local_bundle(repo_root: Path) -> tuple[Path, Path] | None:
    """直下、無ければ `bk\\` から `(バンドル, bundle.key)` を探す。両方揃った場所だけを返す。"""
    for directory in (repo_root, repo_root / "bk"):
        bundle = directory / bundle_common.BUNDLE_NAME
        key = directory / bundle_common.BUNDLE_KEY_NAME
        if bundle.is_file() and key.is_file():
            return bundle, key
    return None


# ── 手順1b: Release からの HTTPS 取得 ──


def _http_download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response:  # noqa: S310
        total = 0
        with dest.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_DOWNLOAD_BYTES:
                    raise RuntimeError(f"ダウンロードが上限({_MAX_DOWNLOAD_BYTES} bytes)を超えました: {url}")
                out.write(chunk)


def download_release_assets(
    tag: str,
    dest_dir: Path,
    *,
    owner: str = DEFAULT_OWNER,
    repo: str = DEFAULT_REPO,
    http_download: Downloader = _http_download,
) -> tuple[Path, Path, Path]:
    """Release からバンドル本体・`.sha256`・`bundle.key` を取得し `(bundle, sha256, key)` を返す。"""
    base = f"https://github.com/{owner}/{repo}/releases/download/{tag}"
    bundle_path = dest_dir / bundle_common.BUNDLE_NAME
    sha_path = dest_dir / f"{bundle_common.BUNDLE_NAME}.sha256"
    key_path = dest_dir / bundle_common.BUNDLE_KEY_NAME
    try:
        http_download(f"{base}/{bundle_common.BUNDLE_NAME}", bundle_path)
        http_download(f"{base}/{bundle_common.BUNDLE_NAME}.sha256", sha_path)
        http_download(f"{base}/{bundle_common.BUNDLE_KEY_NAME}", key_path)
    except Exception as exc:
        raise RuntimeError(
            f"重量物バンドルの取得に失敗しました(タグ {tag} / ネットワーク / リポジトリの公開状態を"
            f"確認してください)。詳細: {exc}"
        ) from exc
    if not (bundle_path.is_file() and sha_path.is_file() and key_path.is_file()):
        raise RuntimeError("重量物バンドルの取得に失敗しました(ファイルが作成されませんでした)。")
    return bundle_path, sha_path, key_path


def verify_bundle_sha256_sidecar(bundle_path: Path, sha_path: Path) -> None:
    """Release に並ぶ `.sha256`(形式 `<hex>  <name>`)と実ファイルを照合する(転送破損の検知)。"""
    expected = sha_path.read_text(encoding="ascii").strip().split()[0].lower()
    actual = bundle_common.sha256_file(bundle_path)
    if actual != expected:
        raise RuntimeError(
            f"バンドルの sha256 が Release の .sha256 と一致しません(期待={expected} / 実際={actual})。\n"
            "  転送中の破損の可能性があります。取得し直してください。"
        )


# ── 手順2: 手元のソースが重量物と対の組であることの確認(展開の前に行う) ──


def verify_local_checkout_matches_bundle_key(key_path: Path, repo_root: Path = ROOT) -> None:
    """手元の checkout が、取得した重量物と対の組であることを content-key で確かめる。

    **必ず `extract_bundle` の前に呼ぶこと。** `docs/_build/vendor/manifest.txt` は git 追跡下で
    clean clone に必ず存在するため展開前でも算出できる。展開後に測ると、バンドル同梱の
    manifest.txt が git 管理下の実体を上書きし、manifest だけの差分を検知できなくなる。

    不一致時は例外を送出するだけで、既存の展開物(python-wheelhouse / vendor の JS)には
    手を触れない。展開の前に呼ぶ検査なので、ここで削除すると前回までの完全な展開結果を
    失うだけで、対の組を取り戻す助けにはならない。
    """
    bundle_key = bundle_common.read_bundle_key(key_path)
    local_key = bundle_common.compute_content_key(repo_root)
    if local_key != bundle_key:
        raise RuntimeError(
            "手元のソースと重量物が対の組ではありません"
            f"(ローカル content-key={local_key} / bundle.key={bundle_key})。\n"
            "  requirements.txt や docs/_build/vendor/manifest.txt を変えたのに Release を更新していない"
            "可能性があります。配布担当に local-only\\offline-publish\\publish-bundle.bat の実行を"
            "依頼するか、bundle.key に対応するコミットへ checkout し直してください。"
        )


# ── 手順3: 展開 ──


def extract_bundle(bundle_path: Path, repo_root: Path = ROOT) -> None:
    """バンドルを repo_root 直下へ展開する(python-wheelhouse / docs/_build/vendor)。"""
    tar_exe = bundle_common.resolve_tar_exe()
    result = subprocess.run([tar_exe, "-xzf", str(bundle_path), "-C", str(repo_root)])
    if result.returncode != 0:
        raise RuntimeError("重量物の展開(tar)に失敗しました。")
    wheelhouse_dir = repo_root / bundle_common.WHEELHOUSE_DIR_NAME
    if not wheelhouse_dir.is_dir():
        raise RuntimeError(f"展開後に {wheelhouse_dir} が見つかりません(バンドルが不完全です)。")
    bundle_common.assert_vendor_assets_present(repo_root)


# ── CLI ──


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default=DEFAULT_OWNER, help=f"GitHub オーナー名(既定 {DEFAULT_OWNER})")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"リポジトリ名(既定 {DEFAULT_REPO})")
    parser.add_argument(
        "--tag", default=bundle_common.DEFAULT_TAG, help=f"取得元タグ(既定 {bundle_common.DEFAULT_TAG})"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="python-tools-setup-") as tmp_name:
        tmp_dir = Path(tmp_name)
        local = find_local_bundle(ROOT)
        if local is not None:
            bundle_path, key_path = local
            print(f"[1/3] 手元のバンドルを使います: {bundle_path}")
        else:
            print(f"[1/3] Release {args.tag} からバンドルを HTTPS で取得します...")
            bundle_path, sha_path, key_path = download_release_assets(
                args.tag, tmp_dir, owner=args.owner, repo=args.repo
            )
            verify_bundle_sha256_sidecar(bundle_path, sha_path)
            print("[info] sha256 OK(転送破損なし)。")

        print("[2/3] 手元のソースが重量物と対の組であることを bundle.key で確認します...")
        verify_local_checkout_matches_bundle_key(key_path)
        print("[info] content key 一致。")

        print("[3/3] バンドルを展開します(python-wheelhouse / docs/_build/vendor)...")
        extract_bundle(bundle_path)

    print()
    print("=" * 60)
    print(" offline セットアップ完了")
    print("=" * 60)
    print(f"  wheelhouse : {ROOT / bundle_common.WHEELHOUSE_DIR_NAME}")
    print(f"  vendor     : {ROOT / 'docs' / '_build' / 'vendor'}")
    print()
    print("次は setup-dev.bat を実行して開発依存を導入してください。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
