# -*- coding: utf-8 -*-
"""offline 重量物バンドルの取得・検証・展開(配布先の Python 版セットアップ)。

`offline/publish_bundle.py` が GitHub Releases(ローリングタグ `offline-bundle-v1`)へ
公開した重量物バンドル(`python-wheelhouse/` + `docs/_build/vendor/`)を取得し、
`offline/pinned-release.txt`(pin)と `offline/bundle-signing.pub.pem`(公開鍵)だけを
配信元と独立した真正性の根拠として検証したうえで展開する。ソースコード自体は
`git clone` 等の別経路で既に手元にある前提(このリポの重量物は wheel と JS の 2 種類
だけで、monorepo 版のようにソース ZIP そのものを展開して環境を構築する設計は採らない)。

ブートストラップ順序(Ed25519 検証の鶏卵回避。詳細は各手順の docstring):
  1. pin 読込・公開鍵存在確認(どちらも無ければ即死)
  2. Release からバンドル本体(.tar.gz)と分離署名(.sig)を取得
     (gh CLI が認証済みなら private のまま取得できる。未認証なら無認証 HTTPS へ
     フォールバックし、その場合はリポジトリの一時 Public 化が前提 — README-offline.md 参照)
  3. **pin の bundle-sha256 と実ファイルを標準ライブラリ hashlib だけで照合**
     (主アンカー。まだ `cryptography` が無い段階でも判定できる経路を先に置く)
  4. 展開(python-wheelhouse / docs/_build/vendor)
  5. wheelhouse から `cryptography` を `--no-index` で導入
     (`check_requirements` でのファイル検査を経てから pip を呼ぶ)
  6. **Ed25519 分離署名を検証**(多層防御。失敗したら手順4で展開した内容を削除して
     非ゼロ終了する)
  7. pin の source-zip-sha256 を、pin の source-commit のアーカイブ(codeload)を取得して
     照合する(手元の git checkout とは独立の経路で「公開時に生成された pin」と
     整合することを確かめる追加確認。展開・書き込みは行わない)

手順3までは `cryptography` に一切依存しない(`bundle_common.py` は署名系の 3 関数だけが
個別に遅延 import する設計になっている。モジュール冒頭で import すると、`cryptography` が
まだ無い配布先での手順1-4の実行自体が import エラーで止まってしまうため)。

gh を呼ぶ関数・HTTP 取得を行う関数はすべて呼び出し側から差し替え可能にしている(単体テストは
偽 runner・偽ダウンロード関数を注入し、実ネットワークへは一切アクセスしない)。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import bundle_common  # noqa: E402
import publish_bundle  # noqa: E402
from check_requirements import assert_requirements_file  # noqa: E402

DEFAULT_OWNER = "koichi-araki-0801"
DEFAULT_REPO = "python-tools"

CompletedProcess = subprocess.CompletedProcess
Runner = Callable[..., CompletedProcess]
Downloader = Callable[[str, Path], None]

default_runner = publish_bundle.default_runner


# ── 手順1: pin + 公開鍵の読込 ──


def load_pin_and_public_key(
    *,
    pin_path: Path = publish_bundle.PIN_PATH,
    public_key_path: Path = publish_bundle.PUBLIC_KEY_PATH,
) -> tuple[bundle_common.PublishPin, bytes]:
    """pin と公開鍵を読み込む(手順1)。

    どちらか欠落・形式不正なら例外(fail closed)。取得する重量物を配信元と独立に真正と
    判定するための唯一の根拠であるため、これが揃わない限り以降の手順へ進まない。
    `read_pin` は形式不正を `ValueError` で拒否する(bundle_common.py 参照)。
    """
    pin = bundle_common.read_pin(pin_path)
    if not public_key_path.is_file():
        raise RuntimeError(
            f"公開鍵がありません: {public_key_path}\n"
            "  offline/ フォルダを丸ごと(pin ファイルと公開鍵ごと)持ち込んでください。"
        )
    return pin, public_key_path.read_bytes()


# ── 手順2: Release からバンドルを取得 ──

# python-wheelhouse を含むためバンドルはソース ZIP よりずっと大きくなりうる。GitHub
# Releases のアセット上限(2GB)と同じ値で天井を切り、想定外の巨大応答を無限に受け続けない。
_BUNDLE_DOWNLOAD_TIMEOUT_SECONDS = 300
_MAX_BUNDLE_DOWNLOAD_BYTES = 2 * 1024 * 1024 * 1024

# ソース ZIP はコード一式のみ(重量物は含まない)なので、こちらは小さい上限で足りる。
_SOURCE_ZIP_DOWNLOAD_TIMEOUT_SECONDS = 60
_MAX_SOURCE_ZIP_DOWNLOAD_BYTES = 200 * 1024 * 1024


def _http_download(url: str, dest: Path, *, timeout: int, max_bytes: int) -> None:
    """無認証 HTTPS で `url` を `dest` へ取得する(タイムアウト・サイズ上限つき)。"""
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        total = 0
        with dest.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError(f"ダウンロードが上限({max_bytes} bytes)を超えました: {url}")
                out.write(chunk)


def default_bundle_http_download(url: str, dest: Path) -> None:
    """バンドル用の既定ダウンローダ(gh が使えないときの無認証 HTTPS フォールバック)。"""
    _http_download(
        url, dest, timeout=_BUNDLE_DOWNLOAD_TIMEOUT_SECONDS, max_bytes=_MAX_BUNDLE_DOWNLOAD_BYTES
    )


def default_source_zip_http_download(url: str, dest: Path) -> None:
    """ソース ZIP 用の既定ダウンローダ(gh が使えないときの無認証 HTTPS フォールバック)。"""
    _http_download(
        url,
        dest,
        timeout=_SOURCE_ZIP_DOWNLOAD_TIMEOUT_SECONDS,
        max_bytes=_MAX_SOURCE_ZIP_DOWNLOAD_BYTES,
    )


def gh_download_bundle_assets(tag: str, dest_dir: Path, *, runner: Runner = default_runner) -> bool:
    """`gh release download` でバンドル本体と分離署名を取得する。成功したら True。

    gh が認証済みならリポジトリを Public 化せずに(private のまま)取得できる。
    """
    result = publish_bundle.gh(
        [
            "release",
            "download",
            tag,
            "--dir",
            str(dest_dir),
            "--clobber",
            "--pattern",
            publish_bundle.BUNDLE_NAME,
            "--pattern",
            f"{publish_bundle.BUNDLE_NAME}.sig",
        ],
        runner=runner,
    )
    bundle_path = dest_dir / publish_bundle.BUNDLE_NAME
    sig_path = dest_dir / f"{publish_bundle.BUNDLE_NAME}.sig"
    return result.returncode == 0 and bundle_path.is_file() and sig_path.is_file()


def fetch_bundle_assets(
    tag: str,
    dest_dir: Path,
    *,
    owner: str = DEFAULT_OWNER,
    repo: str = DEFAULT_REPO,
    runner: Runner = default_runner,
    http_download: Downloader = default_bundle_http_download,
) -> tuple[Path, Path]:
    """Release からバンドル本体(.tar.gz)と分離署名(.sig)を dest_dir へ取得する(手順2)。

    gh CLI を先に試し(認証済みなら private のまま取得できる)、失敗したら無認証 HTTPS の
    Release アセット直 URL へフォールバックする。後者はリポジトリが一時的に Public 公開
    されていることが前提(README-offline.md の手順)。取得元アセットに同梱される
    `.sha256` は使わない(取得物を差し替えられる攻撃者は同じ場所へ `.sha256` も置けるため。
    判定は手渡しで運ばれた pin(手順3)だけで行う)。
    """
    bundle_path = dest_dir / publish_bundle.BUNDLE_NAME
    sig_path = dest_dir / f"{publish_bundle.BUNDLE_NAME}.sig"

    if gh_download_bundle_assets(tag, dest_dir, runner=runner):
        print("[info] gh CLI でバンドルを取得しました。")
        return bundle_path, sig_path

    print("[info] gh CLI での取得ができません(未認証等)。無認証 HTTPS へフォールバックします。")
    base = f"https://github.com/{owner}/{repo}/releases/download/{tag}"
    try:
        http_download(f"{base}/{publish_bundle.BUNDLE_NAME}", bundle_path)
        http_download(f"{base}/{publish_bundle.BUNDLE_NAME}.sig", sig_path)
    except Exception as exc:
        raise RuntimeError(
            "重量物バンドルの取得に失敗しました。gh CLI が未認証なら、リポジトリ管理者へ"
            "一時的な Public 化を依頼してから再実行してください(README-offline.md 参照)。"
            f"詳細: {exc}"
        ) from exc
    if not (bundle_path.is_file() and sig_path.is_file()):
        raise RuntimeError("重量物バンドルの取得に失敗しました(ファイルが作成されませんでした)。")
    return bundle_path, sig_path


# ── 手順3: sha256 照合(主アンカー) ──


def verify_bundle_sha256(bundle_path: Path, pin: bundle_common.PublishPin) -> None:
    """pin の bundle-sha256 と実ファイルを hashlib だけで照合する(手順3)。

    まだ展開していない段階で行う(不一致のバンドルを万一にもリポジトリ直下へ展開しない
    ため)。`cryptography`(手順5で導入)を使わずに判定できる唯一の照合であり、これが
    ブートストラップの主アンカーになる。
    """
    actual = publish_bundle.sha256_file(bundle_path)
    if actual != pin.bundle_sha256:
        raise RuntimeError(
            f"バンドルの sha256 が pin と一致しません(期待={pin.bundle_sha256} / 実際={actual})。\n"
            "  改ざん・取得ミス・pin とバンドルの組み合わせ違いの可能性があります。処理を中止します。"
        )


# ── 手順4: 展開 ──


def extract_bundle(bundle_path: Path, repo_root: Path = ROOT) -> None:
    """バンドルを repo_root 直下へ展開する(python-wheelhouse / docs/_build/vendor)。"""
    tar_exe = publish_bundle.resolve_tar_exe()
    result = subprocess.run([tar_exe, "-xzf", str(bundle_path), "-C", str(repo_root)])
    if result.returncode != 0:
        raise RuntimeError("重量物の展開(tar)に失敗しました。")
    wheelhouse_dir = repo_root / publish_bundle.WHEELHOUSE_DIR_NAME
    if not wheelhouse_dir.is_dir():
        raise RuntimeError(f"展開後に {wheelhouse_dir} が見つかりません(バンドルが不完全です)。")
    publish_bundle.assert_vendor_assets_present(repo_root)


def remove_extracted_bundle(repo_root: Path = ROOT) -> None:
    """展開済みの重量物(python-wheelhouse / docs/_build/vendor の JS 2 件)を削除する。

    手順6の署名検証に失敗したときの後始末(多層防御。展開物を残さない)。
    `docs/_build/vendor/manifest.txt` は git 管理下のファイル(バンドルにも同梱されるが
    リポジトリのコミット内容が正)なので消さない。JS 2 ファイルだけがバンドル由来で
    `.gitignore` 対象になっている。
    """
    wheelhouse_dir = repo_root / publish_bundle.WHEELHOUSE_DIR_NAME
    if wheelhouse_dir.is_dir():
        shutil.rmtree(wheelhouse_dir, ignore_errors=True)
    vendor_dir = repo_root / "docs" / "_build" / "vendor"
    for name in ("mermaid.min.js", "mermaid-layout-elk.min.js"):
        p = vendor_dir / name
        if p.is_file():
            p.unlink(missing_ok=True)


# ── 手順5: wheelhouse から cryptography を導入 ──


def build_pip_install_command(
    python_exe: list[str], wheelhouse_dir: Path, req_path: Path
) -> list[str]:
    """`pip install --no-index --find-links <wheelhouse> -r <req>` の引数列を組み立てる。

    実行はしない(呼び出し側が subprocess で叩く)。`--no-index` は wheelhouse 以外からの
    解決を禁じる(オフライン成立性を守る)。
    """
    return [
        *python_exe,
        "-m",
        "pip",
        "install",
        "--no-index",
        "--find-links",
        str(wheelhouse_dir),
        "-r",
        str(req_path),
    ]


def install_cryptography_from_wheelhouse(
    repo_root: Path = ROOT, *, python_exe: list[str] | None = None
) -> None:
    """wheelhouse から `cryptography` を `--no-index` で導入する(手順5)。

    手順6(Ed25519 署名検証)は `cryptography` に依存するが、その `cryptography` 自体は
    このバンドル(手順4で展開した wheelhouse)にしか無い。requirements の形式検査
    (`check_requirements`)は pip へ渡すすべての入口で必須のため、ここでも pip を呼ぶ前に
    必ず通す。
    """
    req_path = repo_root / "offline" / "dev-requirements.txt"
    assert_requirements_file(req_path)

    wheelhouse_dir = repo_root / publish_bundle.WHEELHOUSE_DIR_NAME
    py_exe = python_exe if python_exe is not None else [sys.executable]
    cmd = build_pip_install_command(py_exe, wheelhouse_dir, req_path)
    result = subprocess.run(cmd, cwd=repo_root)
    if result.returncode != 0:
        raise RuntimeError("cryptography の導入(pip install --no-index)に失敗しました。")


# ── 手順6: Ed25519 署名検証(失敗したら展開物を削除) ──


def verify_bundle_signature_or_cleanup(
    bundle_path: Path, sig_path: Path, public_key_pem: bytes, *, repo_root: Path = ROOT
) -> None:
    """Ed25519 分離署名を検証する(手順6・多層防御)。

    手順3(sha256)は転送破損・単純な取得ミスを弾く一方、hashlib だけの照合は「秘密鍵の
    所持」までは要求しない。署名検証はそれより一段強い根拠になる。失敗したら、たとえ
    手順3を通っていても手順4で展開済みの内容を信用せず削除してから処理を中止する。
    """
    sig_b64 = sig_path.read_text(encoding="ascii").strip()
    if not bundle_common.verify_signature(bundle_path, sig_b64, public_key_pem):
        remove_extracted_bundle(repo_root)
        raise RuntimeError(
            "分離署名の検証に失敗しました。改ざん・すり替え、または公開鍵と署名鍵の不一致の"
            "可能性があります。展開済みの重量物を削除し、処理を中止します。"
        )


# ── 手順7: source zip の sha256 照合(追加確認。展開はしない) ──


def gh_download_source_zip(
    owner: str, repo: str, commit_sha: str, dest: Path, *, runner: Runner = default_runner
) -> bool:
    """`gh api` で pin の source-commit のアーカイブを取得する。成功したら True。

    gh が認証済みならリポジトリを Public 化せずに(private のまま)取得できる。
    """
    result = publish_bundle.gh(
        ["api", f"repos/{owner}/{repo}/zipball/{commit_sha}", "--output", str(dest)],
        runner=runner,
    )
    return result.returncode == 0 and dest.is_file()


def verify_source_zip_sha256(
    pin: bundle_common.PublishPin,
    *,
    owner: str = DEFAULT_OWNER,
    repo: str = DEFAULT_REPO,
    runner: Runner = default_runner,
    http_download: Downloader = default_source_zip_http_download,
) -> None:
    """pin の source-commit のアーカイブを取得し、source-zip-sha256 と照合する(手順7)。

    ソースコード自体は既に手元にある前提(git clone 等の別経路)なので、取得したアーカイブを
    展開はしない。「公開時に `publish_bundle.py` が生成した pin」と「今 GitHub 上にある
    同一コミットのアーカイブ」を独立な経路で突き合わせる追加確認であり、この照合結果は
    手順3-6で確定したバンドルの正当性そのものには影響しない(源が異なる問題の切り分けの
    ため、失敗時は展開済みの重量物を削除せずに処理を中止する)。
    """
    with tempfile.TemporaryDirectory(prefix="python-tools-setup-src-") as tmp_name:
        zip_path = Path(tmp_name) / "source.zip"
        ok = gh_download_source_zip(owner, repo, pin.source_commit, zip_path, runner=runner)
        if not ok:
            print(
                "[info] gh CLI での取得ができません(未認証等)。無認証 HTTPS へフォールバックします。"
            )
            url = f"https://github.com/{owner}/{repo}/archive/{pin.source_commit}.zip"
            try:
                http_download(url, zip_path)
            except Exception as exc:
                raise RuntimeError(
                    "ソース ZIP の取得(追加確認)に失敗しました。gh CLI が未認証なら、"
                    "リポジトリ管理者へ一時的な Public 化を依頼してから再実行してください"
                    f"(README-offline.md 参照)。詳細: {exc}"
                ) from exc
        actual = publish_bundle.sha256_file(zip_path)

    if actual != pin.source_zip_sha256:
        raise RuntimeError(
            "ソース ZIP の sha256 が pin と一致しません"
            f"(期待={pin.source_zip_sha256} / 実際={actual})。\n"
            "  pin が指すコミットと現在 GitHub 上にあるコミットが食い違っています。"
        )


# ── CLI ──


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default=DEFAULT_OWNER, help=f"GitHub オーナー名(既定 {DEFAULT_OWNER})")
    parser.add_argument("--repo", default=DEFAULT_REPO, help=f"リポジトリ名(既定 {DEFAULT_REPO})")
    parser.add_argument(
        "--tag", default=publish_bundle.DEFAULT_TAG, help=f"取得元ローリングタグ(既定 {publish_bundle.DEFAULT_TAG})"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    print("[1/7] pin と公開鍵を読み込みます...")
    pin, public_key_pem = load_pin_and_public_key()
    print(f"[info] pinned source commit: {pin.source_commit}")

    with tempfile.TemporaryDirectory(prefix="python-tools-setup-") as tmp_name:
        tmp_dir = Path(tmp_name)

        print(f"[2/7] Release {args.tag} からバンドルを取得します...")
        bundle_path, sig_path = fetch_bundle_assets(args.tag, tmp_dir, owner=args.owner, repo=args.repo)

        print("[3/7] バンドルの sha256 を pin と照合します(主アンカー)...")
        verify_bundle_sha256(bundle_path, pin)
        print("[info] sha256 OK。")

        print("[4/7] バンドルを展開します(python-wheelhouse / docs/_build/vendor)...")
        extract_bundle(bundle_path)

        print("[5/7] wheelhouse から cryptography を導入します...")
        install_cryptography_from_wheelhouse()

        print("[6/7] Ed25519 分離署名を検証します(多層防御)...")
        verify_bundle_signature_or_cleanup(bundle_path, sig_path, public_key_pem)
        print("[info] 署名 OK。")

        print("[7/7] ソース ZIP の sha256 を pin と照合します(追加確認)...")
        verify_source_zip_sha256(pin, owner=args.owner, repo=args.repo)
        print("[info] ソース ZIP の sha256 OK。")

    print()
    print("=" * 60)
    print(" offline セットアップ完了")
    print("=" * 60)
    print(f"  pinned source commit : {pin.source_commit}")
    print(f"  wheelhouse            : {ROOT / publish_bundle.WHEELHOUSE_DIR_NAME}")
    print(f"  vendor                : {ROOT / 'docs' / '_build' / 'vendor'}")
    print()
    print("次は setup-dev.bat を実行して開発依存を導入してください。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
