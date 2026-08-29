# -*- coding: utf-8 -*-
"""offline 重量物バンドル(`python-wheelhouse/` + `docs/_build/vendor/`)を GitHub Releases
(ローリングタグ `offline-bundle-v1`)へ公開する。署名は Ed25519(`cryptography`)で行い、
pin 生成用のソース取得は一時的な Public 化 + 無認証 HTTPS(`github.com/.../archive/` 経由。
実体は `codeload.github.com` への 302 リダイレクト)で行う(このリポは private で、配布先の
端末は gh 未認証を前提とするため。取得後は必ず元の可視性へ戻す)。

行うこと(概要。詳細は各関数の docstring):
  1. HEAD が origin へ push 済みであることを確認する(codeload は GitHub 上のコミットしか
     返さないため、push 前に固めても配布先は取得できない)。
  2. content-key(`bundle_common.compute_content_key`)を算出し、Release 側の `bundle.key`
     と比較して重量物を再生成するか判定する(`--force` は常に再生成、`--tag-only` は
     一致時のみタグ移動・不一致は何もせず終了)。
  3. 再生成が必要なら、まず vendor 前提(mermaid JS 2 件 + manifest.txt)を検査してから
     (`assert_vendor_assets_present`。I-6: 74MB の `pip download` より前に軽い検査を
     済ませ、揃っていない端末での無駄な download を避ける)requirements を検査
     (`check_requirements.assert_requirements_file`)し、`pip download` で wheelhouse を
     組み、`docs/_build/vendor` と合わせて tar.gz へ固め、Ed25519 で署名する
     (公開鍵が無ければ即失敗。署名の無い重量物は公開しない)。
  4. `--tag-only` でなければ pin(`offline/pinned-release.txt`)を更新する(I-4: Release
     反映より先に行う。pin 生成の失敗で「新バンドル(Release)× 旧 pin」の不整合を
     確定させないため)。ソース zip の sha256 を得るために一時的にリポジトリを Public 化し、
     無認証で codeload から取得する(取得後は必ず finally で元の可視性へ戻す)。
  5. Release が無ければ作成、あれば notes を更新。アセット(tar.gz / .sig / .sha256 /
     bundle.key)は「先に upload、最後にタグ移動」の順で反映し、中断しても旧の組が生きる
     ようにする。

gh/git を実際に呼ぶ関数はすべて `runner` を受け取り、既定は実 `subprocess.run` だが呼び出し側
から差し替えられる(単体テストは偽 runner を注入し、実 gh/git は一切起動しない)。
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable, Iterable

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))

import bundle_common  # noqa: E402
from check_requirements import assert_requirements_file  # noqa: E402

DEFAULT_TAG = "offline-bundle-v1"
BUNDLE_NAME = "offline-deps-bundle.tar.gz"
WHEELHOUSE_DIR_NAME = "python-wheelhouse"
VENDOR_DIR_POSIX = "docs/_build/vendor"
PYTHON_VERSION = "3.13"

DEFAULT_SIGNING_KEY_PATH = (
    Path(os.environ.get("USERPROFILE", str(Path.home())))
    / ".python-tools-signing"
    / "bundle-signing.key.pem"
)
PUBLIC_KEY_PATH = ROOT / "offline" / "bundle-signing.pub.pem"
PIN_PATH = ROOT / "offline" / "pinned-release.txt"

CompletedProcess = subprocess.CompletedProcess
Runner = Callable[..., CompletedProcess]


def default_runner(cmd: list[str], **kwargs) -> CompletedProcess:
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    # `encoding` を明示しないと Windows既定ロケール(cp932 等)で decode され、`git` が出す
    # UTF-8 出力(日本語を含む警告・メッセージ)で読み取りスレッド内 `UnicodeDecodeError` に
    # なり、キャプチャ結果が欠落する(`scripts/hooks/post_commit.py` から `--tag-only` を
    # 呼ぶ経路で実機再現)。呼び出し元が別の `encoding` を明示した場合はそちらを優先する。
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    return subprocess.run(cmd, **kwargs)


# ── git / gh の薄いラッパ(runner 注入でテスト可能に保つ) ──


def git(args: list[str], *, cwd: Path = ROOT, runner: Runner = default_runner) -> CompletedProcess:
    return runner(["git", "-C", str(cwd), *args])


def gh(args: list[str], *, runner: Runner = default_runner) -> CompletedProcess:
    return runner(["gh", *args])


def require_commands(names: Iterable[str]) -> None:
    for name in names:
        if shutil.which(name) is None:
            raise RuntimeError(f"'{name}' が見つかりません。インストール/認証を確認してください。")


def assert_head_pushed(*, cwd: Path = ROOT, runner: Runner = default_runner) -> str:
    """HEAD が origin の何らかの ref に存在することを確認し、その SHA を返す。

    codeload(GitHub のアーカイブ配信)は GitHub 上に存在するコミットしか返さないため、
    ローカルにしか無い HEAD で pin/公開を組んでも配布先は取得できない。
    """
    head = git(["rev-parse", "HEAD"], cwd=cwd, runner=runner)
    if head.returncode != 0:
        raise RuntimeError("git HEAD を取得できません。git リポジトリ内で実行してください。")
    head_sha = head.stdout.strip()

    remote = git(["ls-remote", "origin"], cwd=cwd, runner=runner)
    if remote.returncode != 0:
        raise RuntimeError("git ls-remote origin に失敗しました。")
    remote_shas = {line.split("\t", 1)[0] for line in remote.stdout.splitlines() if line.strip()}
    if head_sha not in remote_shas:
        raise RuntimeError(
            f"HEAD ({head_sha}) が origin へ push されていません。\n"
            "  publish は push 済みの HEAD を前提とする"
            "(codeload は GitHub 上のコミットしか返さない)。先に `git push` を実行してください。"
        )
    return head_sha


def release_exists(tag: str, *, runner: Runner = default_runner) -> bool:
    return gh(["release", "view", tag], runner=runner).returncode == 0


def fetch_published_key(tag: str, dest_dir: Path, *, runner: Runner = default_runner) -> str | None:
    """Release `tag` から `bundle.key` を取得して内容を返す。取得できなければ `None`。"""
    result = gh(
        ["release", "download", tag, "--pattern", "bundle.key", "--dir", str(dest_dir), "--clobber"],
        runner=runner,
    )
    if result.returncode != 0:
        return None
    key_file = dest_dir / "bundle.key"
    if not key_file.is_file():
        return None
    return bundle_common.read_bundle_key(key_file)


# ── 純粋な判定/構築部品(runner 不要。単体テストの主対象) ──


def bundle_changed(*, force: bool, release_exists: bool, published_key: str | None, current_key: str) -> bool:
    """重量物の再生成が必要かを判定する。強制 / Release 未作成(初回) / キー不一致のいずれか。"""
    return force or (not release_exists) or (published_key != current_key)


def should_skip_tag_only(*, tag_only: bool, changed: bool) -> bool:
    """`--tag-only` 経路で「タグも動かさず何もしない」べきかを判定する。

    `--tag-only` は依存解決器(pip download)を一切起動しない契約のため、重量物の更新が
    要ると判明した時点でタグも進めずに終了する。ここでタグだけ進めると「新ソース × 旧重量物」
    の不整合ペアを配ることになる。
    """
    return tag_only and changed


def build_pip_download_command(
    python_exe: list[str], wheelhouse_dir: Path, requirements_files: list[Path]
) -> list[str]:
    """`pip download` の引数列を組み立てる(実行はしない。呼び出し側が subprocess で叩く)。

    `--python-version 3.13 --only-binary=:all:` で wheel の ABI を cp313 に固定し(実行
    インタプリタ任せだと別 ABI が混入し content-key では検知できない)、sdist を排除する
    (sdist は取得しただけでビルド = setup.py 実行に至る経路を開くため)。
    """
    cmd = [
        *python_exe,
        "-m",
        "pip",
        "download",
        "--no-input",
        "--disable-pip-version-check",
        "--python-version",
        PYTHON_VERSION,
        "--index-url",
        "https://pypi.org/simple",
        "--only-binary=:all:",
        "-d",
        str(wheelhouse_dir),
    ]
    for req in requirements_files:
        cmd += ["-r", str(req)]
    return cmd


def build_tar_command(tar_exe: str, bundle_path: Path, repo_root: Path) -> list[str]:
    """重量物を固める `tar -czf` の引数列を組み立てる(実行はしない)。"""
    return [
        tar_exe,
        "-czf",
        str(bundle_path),
        "-C",
        str(repo_root),
        WHEELHOUSE_DIR_NAME,
        VENDOR_DIR_POSIX,
    ]


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


# GitHub Releases の 1 アセットあたりの上限。
_MAX_RELEASE_ASSET_BYTES = 2 * 1024 * 1024 * 1024


def assert_release_asset_size_ok(size_bytes: int, *, label: str = BUNDLE_NAME) -> None:
    """アセットが Release の 2GB 上限を超えていないか検査する。超えたら `RuntimeError`。"""
    if size_bytes >= _MAX_RELEASE_ASSET_BYTES:
        raise RuntimeError(
            f"{label} が {_MAX_RELEASE_ASSET_BYTES} bytes(Release の上限)を超えました"
            f"(実サイズ {size_bytes} bytes)。分割が必要です。"
        )


def resolve_tar_exe() -> str:
    """Windows 標準 tar(`System32\\tar.exe`)を優先解決する。

    Git Bash 同梱の MSYS tar が PATH 先頭にあると `-C <Windows パス>` を rsh の
    host:path と誤認して失敗するため。
    """
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = Path(system_root) / "System32" / "tar.exe"
    if candidate.is_file():
        return str(candidate)
    found = shutil.which("tar")
    if found:
        return found
    raise RuntimeError("'tar' が見つかりません(Windows 10/11 標準の tar.exe が必要)。")


# ── 重量物の生成 ──


def build_wheelhouse(
    repo_root: Path,
    wheelhouse_dir: Path,
    requirements_files: list[Path],
    *,
    python_exe: list[str],
) -> None:
    """`requirements_files` を検査してから `pip download` で `wheelhouse_dir` へ収集する。

    **検査(`assert_requirements_file`)は pip 実行の直前・全ファイルに対して行う。**
    pip 入口列挙ガード(`find_pip_call_files` / テスト側)はこの呼び出しの存在を検査する。
    """
    for req in requirements_files:
        assert_requirements_file(req)

    if wheelhouse_dir.exists():
        shutil.rmtree(wheelhouse_dir)
    wheelhouse_dir.mkdir(parents=True)

    cmd = build_pip_download_command(python_exe, wheelhouse_dir, requirements_files)
    result = subprocess.run(cmd, cwd=repo_root)
    if result.returncode != 0:
        raise RuntimeError("pip download(wheelhouse 収集)に失敗しました。")


# vendor 配下でバンドル由来(= `.gitignore` 対象・git 管理外)なのはこの JS 2 件だけ。
# `manifest.txt` は git 管理下(コミットされる)なので、setup 側の削除対象
# (`setup_offline.remove_extracted_bundle`)には含めない。1 箇所にまとめて両側から参照する
# ことで、片方だけ増減して drift する事故を防ぐ。
VENDOR_JS_ASSET_NAMES = ("mermaid.min.js", "mermaid-layout-elk.min.js")
VENDOR_REQUIRED_ASSET_NAMES = ("manifest.txt", *VENDOR_JS_ASSET_NAMES)


def assert_vendor_assets_present(repo_root: Path) -> None:
    vendor_dir = repo_root / "docs" / "_build" / "vendor"
    missing = [name for name in VENDOR_REQUIRED_ASSET_NAMES if not (vendor_dir / name).is_file()]
    if missing:
        raise RuntimeError(
            f"docs/_build/vendor に不足があります: {missing}\n"
            "  offline\\setup-offline.bat 等で vendor 一式を展開してから publish してください。"
        )


def build_bundle_tar(repo_root: Path, bundle_path: Path) -> None:
    tar_exe = resolve_tar_exe()
    if bundle_path.exists():
        bundle_path.unlink()
    cmd = build_tar_command(tar_exe, bundle_path, repo_root)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        raise RuntimeError("tar による重量物の梱包に失敗しました。")


# ── Release 操作 ──


def move_rolling_tag(tag: str, commit_sha: str, *, cwd: Path = ROOT, runner: Runner = default_runner) -> None:
    """ローリングタグを `commit_sha` へ強制移動する(force push)。"""
    result = git(["push", "origin", f"+{commit_sha}:refs/tags/{tag}"], cwd=cwd, runner=runner)
    if result.returncode != 0:
        raise RuntimeError(f"タグの移動(git push)に失敗しました: {result.stderr}")


def gh_release_create(tag: str, notes_path: Path, *, runner: Runner = default_runner) -> None:
    result = gh(
        ["release", "create", tag, "--title", f"Offline deps bundle ({tag})", "--notes-file", str(notes_path)],
        runner=runner,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh release create に失敗しました: {result.stderr}")


def gh_release_edit_notes(tag: str, notes_path: Path, *, runner: Runner = default_runner) -> None:
    result = gh(["release", "edit", tag, "--notes-file", str(notes_path)], runner=runner)
    if result.returncode != 0:
        raise RuntimeError(f"gh release edit に失敗しました: {result.stderr}")


def gh_release_upload(tag: str, assets: list[Path], *, runner: Runner = default_runner) -> None:
    result = gh(["release", "upload", tag, *[str(a) for a in assets], "--clobber"], runner=runner)
    if result.returncode != 0:
        raise RuntimeError(f"gh release upload に失敗しました: {result.stderr}")


def sync_release(
    *,
    tag: str,
    head_sha: str,
    release_exists_flag: bool,
    changed: bool,
    notes_path: Path,
    assets: list[Path],
    runner: Runner = default_runner,
) -> None:
    """Release の作成/更新とタグ移動を「中断しても旧の組が生きる」順序で行う。

    初回(Release 未作成): タグ作成 → Release 作成 → アセット upload(`changed` のときのみ)。
    既存: notes 更新 → アセット upload(`changed` のときのみ)→ タグ移動。
    既存側はアセットを出し切ってからタグを進める。これにより upload 途中で失敗しても
    タグは旧コミットのままとなり、配布先が取得するソース(タグ)と重量物(アセット)は
    常に整合した組み合わせになる。
    """
    if not release_exists_flag:
        move_rolling_tag(tag, head_sha, runner=runner)
        gh_release_create(tag, notes_path, runner=runner)
        if changed:
            gh_release_upload(tag, assets, runner=runner)
    else:
        gh_release_edit_notes(tag, notes_path, runner=runner)
        if changed:
            gh_release_upload(tag, assets, runner=runner)
        move_rolling_tag(tag, head_sha, runner=runner)


def build_release_notes(tag: str, content_key: str) -> str:
    return (
        "別端末(Windows x64)でネット不要に環境構築するための重量物バンドル。\n"
        f"タグ `{tag}` は公開のたびに最新コミットへ移動し、GitHub が自動添付する "
        "`Source code (zip/tar.gz)` は最新のソースコードと一致します。\n\n"
        "## 同梱\n"
        "- python-wheelhouse ... pdf-to-svg / graph-editor / docs ビルド依存の wheel(cp313)\n"
        "- docs/_build/vendor ... mermaid 描画用 JS(2 ファイル)+ manifest\n\n"
        "## 完全性・真正性\n"
        "重量物には分離署名(`.sig`。Ed25519 / base64)を添えています。検証鍵は "
        "`offline/bundle-signing.pub.pem`、取得すべきソースの不変コミット ID と各 sha256 は "
        "`offline/pinned-release.txt` にあります(いずれも offline/ ごと手渡しで運ぶ前提)。\n\n"
        f"content key: `{content_key}`\n"
    )


# ── pin 生成(一時的な Public 化 + 無認証 codeload) ──


def gh_repo_name_with_owner(*, runner: Runner = default_runner) -> str:
    result = gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], runner=runner)
    if result.returncode != 0:
        raise RuntimeError("gh repo view でリポジトリ名を取得できません。")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("gh repo view の出力が空です(リポジトリ名を取得できません)。")
    return lines[0]


def gh_repo_visibility(*, runner: Runner = default_runner) -> str:
    result = gh(["repo", "view", "--json", "visibility", "-q", ".visibility"], runner=runner)
    if result.returncode != 0:
        raise RuntimeError("gh repo view でリポジトリの visibility を取得できません。")
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("gh repo view の出力が空です(visibility を取得できません)。")
    return lines[0].lower()


def gh_set_repo_visibility(visibility: str, *, runner: Runner = default_runner) -> None:
    """`gh repo edit --visibility <visibility>` を実行する。

    `--accept-visibility-change-consequences` は public 化のときだけでなく、
    `--visibility` を使うすべての呼び出し(private への復帰を含む)で必須
    (gh 2.93.0 実測。無いとクライアント側検証でリポジトリ解決より前に exit 1 になる)。
    """
    result = gh(
        ["repo", "edit", "--visibility", visibility, "--accept-visibility-change-consequences"],
        runner=runner,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh repo edit --visibility {visibility} に失敗しました: {result.stderr}")


def _restore_repo_visibility(original: str, *, runner: Runner = default_runner) -> None:
    """`temporarily_public_repo` の復帰処理。戻したうえで再取得して検証する。

    復帰コマンド自体の失敗、または戻した後の visibility が `original` と一致しないことは
    どちらも「リポジトリが Public のまま気づかれない」実害に直結するため、例外を握り潰さず
    `RuntimeError` を送出する(fail closed)。呼び出し元(`publish_bundle.py` の `__main__`)は
    これを非ゼロ終了として扱う。
    """
    try:
        gh_set_repo_visibility(original, runner=runner)
        actual = gh_repo_visibility(runner=runner)
    except Exception as exc:
        raise RuntimeError(
            f"リポジトリを {original} へ戻せませんでした。手動で "
            f"`gh repo edit --visibility {original} --accept-visibility-change-consequences` "
            f"を実行し、可視性を確認してください: {exc}"
        ) from exc
    if actual != original:
        raise RuntimeError(
            f"リポジトリの可視性復帰を確認できません(期待={original} / 実際={actual})。手動で "
            f"`gh repo edit --visibility {original} --accept-visibility-change-consequences` "
            "を実行し、可視性を確認してください。"
        )


@contextlib.contextmanager
def temporarily_public_repo(*, runner: Runner = default_runner):
    """pin 生成のソース zip 取得のため、一時的にリポジトリを Public 化する。

    visibility を事前確認し、既に public ならそのまま(何もしない)。private から public へ
    変えた場合のみ、finally で元(private)へ必ず戻し、`_restore_repo_visibility` で戻った
    ことを再取得して検証する。本体(`yield` の中)が例外(`KeyboardInterrupt` 等の
    `BaseException` を含む)を送出しても `finally` は必ず実行され、復帰が試みられる。
    """
    original = gh_repo_visibility(runner=runner)
    made_public = original != "public"
    if made_public:
        gh_set_repo_visibility("public", runner=runner)
    try:
        yield
    finally:
        if made_public:
            _restore_repo_visibility(original, runner=runner)


# ソース zip はコード一式のみ(重量物は含まない)なので、これより大きければ想定外として
# 中断する。`temporarily_public_repo` の内側で待ち続けるとリポジトリが Public のまま無制限に
# 露出するため、タイムアウトとサイズ上限の両方で「必ず終わる」ことを保証する。
_SOURCE_ZIP_TIMEOUT_SECONDS = 60
_MAX_SOURCE_ZIP_BYTES = 200 * 1024 * 1024


def download_source_zip(owner_repo: str, commit_sha: str, dest: Path) -> None:
    """`owner_repo`(`owner/name`)の `commit_sha` アーカイブを無認証 HTTPS で取得する。

    URL は `github.com/<owner_repo>/archive/<sha>.zip`(**`codeload.github.com` を直接
    叩いているわけではない**)。実機確認では `codeload.github.com` への 302 リダイレクトを
    経由し、最終的に得られるバイト列は codeload 直叩きと一致する(setup 側の
    `default_gh_authenticated_source_zip_download` が使う URL 形とは綴りが異なる同一実体。
    README-offline.md「setup 側の gh 認証 vs 無認証」参照)。

    `temporarily_public_repo` の中でのみ呼ぶこと(private のままでは 404 になる)。
    """
    url = f"https://github.com/{owner_repo}/archive/{commit_sha}.zip"
    with urllib.request.urlopen(url, timeout=_SOURCE_ZIP_TIMEOUT_SECONDS) as response:  # noqa: S310
        total = 0
        with dest.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_SOURCE_ZIP_BYTES:
                    raise RuntimeError(
                        f"ソース zip のサイズが上限({_MAX_SOURCE_ZIP_BYTES} bytes)を超えました。"
                        "取得を中断します。"
                    )
                out.write(chunk)


def generate_pin(
    repo_root: Path, head_sha: str, bundle_sha256: str, *, runner: Runner = default_runner
) -> bundle_common.PublishPin:
    """pin(`<repo_root>/offline/pinned-release.txt`)を生成してファイルへ書き出す。

    ソース zip の sha256 を得るためだけに一時的な Public 化を挟む(codeload は private
    リポジトリへ未認証でアクセスできない)。取得後は必ず finally で元の可視性へ戻る
    (`temporarily_public_repo` 参照)。
    """
    owner_repo = gh_repo_name_with_owner(runner=runner)
    with tempfile.TemporaryDirectory(prefix="python-tools-pin-") as tmp_name:
        zip_path = Path(tmp_name) / "source.zip"
        with temporarily_public_repo(runner=runner):
            download_source_zip(owner_repo, head_sha, zip_path)
        zip_sha256 = sha256_file(zip_path)
    pin = bundle_common.PublishPin(
        source_commit=head_sha, source_zip_sha256=zip_sha256, bundle_sha256=bundle_sha256
    )
    bundle_common.write_pin(repo_root / "offline" / "pinned-release.txt", pin)
    return pin


# ── pip 入口列挙ガード ──

# 「入口」= リポ内で pip install/download を実行するファイル。`.py` / `.yml` / `.yaml` に
# 加えて `.bat` も走査する(`docs/_build/build_all.bat` のように `.bat` から直接 pip を
# 呼ぶ実例があるため、拡張子で機械的に対象外にはできない)。
KNOWN_PIP_ENTRYPOINTS = frozenset(
    {
        "scripts/setup_dev.py",
        "scripts/lib/build_venv.py",
        "offline/publish_bundle.py",
        "offline/setup_offline.py",
        "docs/_build/build_all.bat",
        ".github/workflows/ci.yml",
    }
)

# 除外は「ガード自身の定義・テストファイル」という構造的な 1 件だけ(このファイルは
# 「pip install」という語を含む説明コメントを持つため、自己参照的に誤検知する)。
# 個々の pip 呼び出しファイルを見つけてから除外リストへ足す、という運用はしない
# (それは `KNOWN_PIP_ENTRYPOINTS` へ登録する形で行う)。
_GUARD_SELF_EXCLUDE = frozenset({"scripts/test_python_tools_scripts.py"})

_PIP_SCAN_EXTENSIONS = (".py", ".yml", ".yaml", ".bat")

# check_requirements の呼び出しを示す語。Python 側は識別子 `check_requirements`
# (import / 関数名)、`.bat` 側は同ランチャのファイル名 `check-requirements`(ハイフン形。
# `scripts/check-requirements.bat`)を呼ぶため、どちらの表記でも「検査を経由している」と
# 判定できるようにする。
_CHECK_REQUIREMENTS_MARKERS = ("check_requirements", "check-requirements")


def has_check_requirements_marker(text: str) -> bool:
    return any(marker in text for marker in _CHECK_REQUIREMENTS_MARKERS)


# `pip`(または `pip3`)の直後、空白・引用符・バッククォート・カンマ・ハイフンだけを挟んで
# `install`/`download` が続く形を拾う。Python の list リテラル形式(`"pip",\n "install"`)と
# シェル形式(`pip install ...`)の両方を捉える一方、`pip は requirements ...` のような
# 日本語散文中の「pip」への言及(その後に install/download が来ない、または全角文字を挟む)は
# 拾わない拒否リストの逆(許可する形だけを書く)にしてある。
_PIP_CALL_RE = re.compile(r"(?<![A-Za-z0-9_])pip3?[\s\"'`,\-]{0,20}(install|download)\b")


def find_pip_call_files(repo_root: Path, *, runner: Runner = default_runner) -> set[str]:
    """`pip install` / `pip download` を呼ぶ(と読める)追跡ファイルの相対パス集合を返す。

    走査対象は `_PIP_SCAN_EXTENSIONS`(`.py` / `.yml` / `.yaml` / `.bat`)に絞る。
    ガード自身のテストファイルは除外する。

    列挙は `-z`(NUL 区切り)出力を使う。git は既定(`core.quotepath=true`)では非 ASCII
    パスを引用符 + 8 進エスケープした文字列で返し、`rel.endswith(_PIP_SCAN_EXTENSIONS)` が
    末尾の `"` に阻まれて一致しなくなる(検査対象から黙って落ちる。実証済み)。`-z` は
    `core.quotepath` の設定に関わらずエスケープなしの生バイト列を NUL 区切りで返すため、
    この問題が構造的に起きない。同型の修正が `scripts/check_comments.py`
    (`_staged_files`)・`offline/lib/bundle_common.py`(`list_requirements_files_via_git`)・
    `scripts/setup_dev.py`(`list_requirements`)の計 4 箇所にある。
    """
    result = runner(["git", "-C", str(repo_root), "ls-files", "-z"])
    if result.returncode != 0:
        raise RuntimeError("git ls-files に失敗しました(pip 入口ガードを実行できません)。")

    hits: set[str] = set()
    for rel in result.stdout.split("\0"):
        if not rel or rel in _GUARD_SELF_EXCLUDE:
            continue
        if not rel.endswith(_PIP_SCAN_EXTENSIONS):
            continue
        path = repo_root / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if _PIP_CALL_RE.search(text):
            hits.add(rel)
    return hits


# ── CLI ──


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=DEFAULT_TAG, help=f"公開先のローリングタグ(既定 {DEFAULT_TAG})")
    parser.add_argument("--force", action="store_true", help="変更検知を無視して常に重量物を再生成する")
    parser.add_argument(
        "--tag-only",
        action="store_true",
        help="タグ移動(ソース更新)だけを行う。重量物の更新が必要と判明した場合は何もせず終了する",
    )
    parser.add_argument(
        "--signing-key",
        type=Path,
        default=DEFAULT_SIGNING_KEY_PATH,
        help="Ed25519 秘密鍵(PEM)のパス",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    require_commands(["git", "gh"])

    head_sha = assert_head_pushed()
    requirements_files = bundle_common.list_requirements_files(ROOT)
    if not requirements_files:
        raise RuntimeError("requirements.txt が見つかりません(git ls-files の結果が空)。")
    current_key = bundle_common.compute_content_key(ROOT, requirements_files=requirements_files)
    print(f"[info] current content key: {current_key}")

    with tempfile.TemporaryDirectory(prefix="python-tools-publish-") as tmp_name:
        tmp_dir = Path(tmp_name)
        exists = release_exists(args.tag)
        published_key = fetch_published_key(args.tag, tmp_dir) if exists else None
        print(f"[info] published key: {published_key or '(none)'}")

        changed = bundle_changed(
            force=args.force, release_exists=exists, published_key=published_key, current_key=current_key
        )

        if should_skip_tag_only(tag_only=args.tag_only, changed=changed):
            print("[skip] 重量物の更新が必要ですが --tag-only のため何もしません(タグも動かしません)。")
            return 0

        bundle_path = ROOT / BUNDLE_NAME
        sha_path = ROOT / f"{BUNDLE_NAME}.sha256"
        sig_path = ROOT / f"{BUNDLE_NAME}.sig"
        key_path = ROOT / "bundle.key"
        bundle_hash: str | None = None

        if changed:
            if not args.signing_key.is_file():
                raise RuntimeError(
                    f"署名鍵がありません: {args.signing_key}\n"
                    "  offline\\new_signing_key.py を 1 回実行して鍵ペアを作成してください。"
                )
            if not PUBLIC_KEY_PATH.is_file():
                raise RuntimeError(
                    f"公開鍵が offline/ にありません: {PUBLIC_KEY_PATH}\n"
                    "  配布先はこのファイルだけを真正性の根拠にするため、コミットが必要です。"
                )

        if args.tag_only:
            move_rolling_tag(args.tag, head_sha)
            print(f"[OK] タグのみ更新: {args.tag} を {head_sha} へ移動しました。")
            return 0

        if changed:
            print("[info] 重量物を更新します(--force / 初回 / 変更検知)。")
            # I-6: vendor 前提(mermaid JS 2 件 + manifest.txt)の検査は `build_wheelhouse`
            # (74MB の pip download を伴う)より前に行う。検査を後段に置くと、vendor が
            # 揃っていない新規 publisher 端末で download を丸ごと無駄にしてから失敗する
            # (README-offline.md に publisher 側 bootstrap 手順を成文化済み)。
            assert_vendor_assets_present(ROOT)
            py_exe = [sys.executable]
            build_wheelhouse(ROOT, ROOT / WHEELHOUSE_DIR_NAME, requirements_files, python_exe=py_exe)
            build_bundle_tar(ROOT, bundle_path)
            assert_release_asset_size_ok(bundle_path.stat().st_size)

            # 署名の自己検証で同じ内容を 2 回全読みしないよう、バイト列を 1 回読んで使い回す。
            bundle_bytes = bundle_path.read_bytes()
            bundle_hash = hashlib.sha256(bundle_bytes).hexdigest()
            sha_path.write_text(f"{bundle_hash}  {BUNDLE_NAME}", encoding="ascii")
            bundle_common.write_bundle_key(key_path, current_key)

            private_pem = args.signing_key.read_bytes()
            sig_b64 = bundle_common.sign_bytes(bundle_bytes, private_pem)
            sig_path.write_text(sig_b64, encoding="ascii")

            public_pem = PUBLIC_KEY_PATH.read_bytes()
            if not bundle_common.verify_signature_bytes(bundle_bytes, sig_b64, public_pem):
                raise RuntimeError(
                    f"分離署名の検証に失敗しました: {bundle_path}\n"
                    "  改ざん・すり替え、または公開鍵と署名鍵の不一致。処理を中止する。"
                )
            print("[info] 署名 OK。")
        else:
            print("[info] 重量物は最新の Release と一致。ソース(タグ)のみ更新します。")

        if bundle_hash is None:
            # 重量物を更新していない回は既存 pin の bundle-sha256 を引き継ぐ。
            try:
                bundle_hash = bundle_common.read_pin(PIN_PATH).bundle_sha256
            except ValueError:
                if sha_path.is_file():
                    bundle_hash = sha_path.read_text(encoding="ascii").strip().split()[0]
                else:
                    raise RuntimeError(
                        "重量物を更新していないため既存 pin か手元の .sha256 が要りますが、"
                        "どちらも読めません。初回は --force を付けて重量物ごと公開してください。"
                    )

        # I-4: pin 生成(generate_pin)を Release 反映(sync_release)より先に行う。
        # pin 生成の失敗(visibility 復帰失敗・codeload 落ち・上限・タイムアウト等)は
        # 従来の順序(sync_release が先)だと「新バンドル(Release)× 旧 pin」の不整合を
        # 確定させ、以後の配布先が手順3(主アンカー)で必ず失敗する形になっていた
        # (--tag-only は pin を見ないため検知経路も無い)。ここで先に pin を確定させれば、
        # 失敗時は Release/タグとも旧のままで済み、不整合な組を配らない。
        # `assert_head_pushed` を main() 冒頭で通しているため、この時点で HEAD は既に
        # origin 上に存在する(generate_pin の前提を満たす)。
        pin = generate_pin(ROOT, head_sha, bundle_hash)
        print(f"[info] pin を更新: {ROOT / 'offline' / 'pinned-release.txt'}(source-commit={pin.source_commit})")
        print("       ※ この pin ファイルをコミットしてください(offline/ ごと配布先へ運ぶ前提)。")

        notes = build_release_notes(args.tag, current_key)
        notes_path = tmp_dir / "notes.md"
        notes_path.write_text(notes, encoding="utf-8")

        sync_release(
            tag=args.tag,
            head_sha=head_sha,
            release_exists_flag=exists,
            changed=changed,
            notes_path=notes_path,
            assets=[bundle_path, sha_path, key_path, sig_path],
        )

    print(f"[OK] 公開完了: {args.tag}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        sys.exit(1)
