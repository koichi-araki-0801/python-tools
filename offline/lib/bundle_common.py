# -*- coding: utf-8 -*-
"""共通ライブラリ: offline 重量物バンドルの content-key 算出・bundle.key の読み書き・バンドル共通定数。

`offline/publish_bundle.py` / `offline/setup_offline.py` から import して使う。
content-key はファイル内容の連結を基本とし、
行末(CR)だけは正規化する(`_read_normalized_bytes` 参照)。Windows worktree(既定
`core.autocrlf=true`)は CRLF、GitHub の archive zip(codeload)は LF になるため、正規化
しないと同じ内容でも worktree ごとに異なる key を生み、配布先での bundle.key 突き合わせが
恒久的に不一致になる。対象が少数の `requirements.txt` と 1 つの manifest.txt だけであることから、
行コメント・空行の除去までは行わない(内容そのものを比較する方が変更検知として素直なため)。

content-key = 追跡中の全 `*requirements.txt` の内容 + `docs/_build/vendor/manifest.txt` の
内容(いずれも CR 除去後)を列挙順に連結したバイト列の SHA256。列挙は git 経路
(`git ls-files -- '*requirements.txt'`)を既定とし、git が使えない/管理外なら FS フォールバック
(`name.endswith('requirements.txt')` のグロブ相当)へ切り替える。2 経路は除外ディレクトリの
数え合わせで一致させるのではなく、「追跡されないディレクトリ(`.git` / `python-wheelhouse` /
`.venv*`)は最初から両経路とも候補に入らない」形で構造的に同一集合になるよう作る。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable

# ── requirements.txt の列挙 ──

# FS フォールバックが除外するディレクトリ(M-6)。`.git`(git 管理領域)・`python-wheelhouse`
# (重量物置き場)・`dist`/`build`/`out`/`coverage`/`test-results`/`__pycache__`/
# `.pytest_cache` は git 追跡外の生成物置き場(`.pytest_cache` 以外は `.gitignore` に列挙、
# `.pytest_cache` は pytest が生成する未追跡キャッシュ)で、git 経路(`git ls-files`)では
# 最初から候補に入らない。FS フォールバックだけがこの集合を持たないと、
# 「git が使えない環境」でこれらの配下に requirements.txt 相当のファイルが紛れ込んだ場合に
# 2 経路が異なる集合を返しうる(FS 側だけ拾う非対称)。`.gitignore` および
# `scripts/check_comments.py` の `REPO_CONFIGS["python-tools"]["skip_dir_names"]` と
# 手動で揃える(これらは独立した列挙であり自動で同期しない。増減時は 3 箇所とも見直すこと)。
# `.venv*` は `setup_dev.py` と同じ命名規約(ビルド用隔離venv は `.venv-build`)。
_FS_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        "python-wheelhouse",
        "__pycache__",
        ".pytest_cache",
        "dist",
        "build",
        "out",
        "coverage",
        "test-results",
    }
)
_FS_EXCLUDED_DIR_PREFIXES = (".venv",)

VENDOR_MANIFEST_REL = Path("docs") / "_build" / "vendor" / "manifest.txt"


def list_requirements_files_via_git(repo_root: Path) -> list[Path] | None:
    """`git ls-files -- '*requirements.txt'` で追跡中の requirements ファイルを列挙する。

    git が使えない、または `repo_root` が git 管理外なら `None` を返す(呼び出し元に
    FS フォールバックへの切り替えを促す)。

    列挙は `-z`(NUL 区切り)出力を使う。git は既定(`core.quotepath=true`)では非 ASCII
    パスを引用符 + 8 進エスケープした文字列で返し、`repo_root / line` が実在しないパスに
    なって黙って候補から落ち、FS フォールバックだけが拾う非対称(「2 経路一致」不変則の
    破れ)を生む(実証済み)。`-z` は `core.quotepath` の設定に関わらずエスケープなしの
    生バイト列を NUL 区切りで返すため、この問題が構造的に起きない。同型の修正が
    `scripts/check_comments.py`(`_staged_files`)・`scripts/check_requirements.py`
    (`find_pip_call_files`)・`scripts/setup_dev.py`(`list_requirements`)の計 4 箇所にある。
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z", "--", "*requirements.txt"],
            capture_output=True,
            text=True,
            # `encoding` を明示しないと Windows既定ロケール(cp932 等)で decode され、
            # `git` が出す UTF-8 出力で読み取りスレッド内 `UnicodeDecodeError` になり
            # うる(`scripts/hooks/post_commit.py` 経由の `--tag-only` → この関数の
            # 呼び出し連鎖で実機確認した不具合と同一クラス)。
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    files = [repo_root / p for p in result.stdout.split("\0") if p]
    return sorted(files, key=lambda p: p.relative_to(repo_root).as_posix())


def list_requirements_files_via_filesystem(repo_root: Path) -> list[Path]:
    """`name.endswith('requirements.txt')` の再帰探索で requirements ファイルを列挙する。

    git が使えない環境向けのフォールバック経路。除外ディレクトリは
    `_FS_EXCLUDED_DIR_NAMES` / `_FS_EXCLUDED_DIR_PREFIXES` のみ(ハードコード列挙を
    増やさない)。
    """
    found: list[Path] = []
    for path in repo_root.rglob("*requirements.txt"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(repo_root).parts[:-1]
        if any(
            part in _FS_EXCLUDED_DIR_NAMES or part.startswith(_FS_EXCLUDED_DIR_PREFIXES)
            for part in rel_parts
        ):
            continue
        found.append(path)
    return sorted(found, key=lambda p: p.relative_to(repo_root).as_posix())


def list_requirements_files(repo_root: Path) -> list[Path]:
    """requirements ファイルを列挙する(git 経路優先、フォールバックは FS 経路)。"""
    via_git = list_requirements_files_via_git(repo_root)
    if via_git is not None:
        return via_git
    return list_requirements_files_via_filesystem(repo_root)


# ── content-key 算出 ──


def _read_normalized_bytes(path: Path) -> bytes:
    """CR(0x0D)を除去して読む(CRLF/LF worktree 差を吸収する行末正規化)。

    Windows worktree(既定 `core.autocrlf=true`)はテキストファイルを CRLF で書き出す一方、
    GitHub の archive zip(codeload)や LF 前提のビルド機は同じ内容を LF のまま持つ。CR を
    残したまま content-key を測ると、改行コードだけの違いで別の key になり、配布先での
    `bundle.key` 突き合わせが恒久的に不一致になる。
    """
    return path.read_bytes().replace(b"\r", b"")


def compute_content_key(repo_root: Path, *, requirements_files: list[Path] | None = None) -> str:
    """content-key(重量物バンドルの変更検知キー)を算出する。

    `requirements_files` を渡さない場合は `list_requirements_files` で列挙する
    (呼び出し元がすでに列挙済みの場合は再列挙を避けるため引数で渡せる)。
    `docs/_build/vendor/manifest.txt` が存在すれば内容を折り込む(mermaid 同梱 JS の版が
    変わればバンドルの再生成が要るため)。存在しない場合はそのまま requirements のみで
    算出する(このリポでは常に存在する想定だが、フォールバック時に例外で落とさない)。
    各ファイルは `_read_normalized_bytes` で CR を除去してから連結する。
    """
    if requirements_files is None:
        requirements_files = list_requirements_files(repo_root)
    hasher = hashlib.sha256()
    for req in requirements_files:
        hasher.update(_read_normalized_bytes(req))
    manifest_path = repo_root / VENDOR_MANIFEST_REL
    if manifest_path.is_file():
        hasher.update(_read_normalized_bytes(manifest_path))
    return hasher.hexdigest()


# ── bundle.key(content-key を書いた 1 行ファイル)の読み書き ──


def write_bundle_key(path: Path, content_key: str) -> None:
    path.write_text(content_key, encoding="ascii")


def read_bundle_key(path: Path) -> str:
    return path.read_text(encoding="ascii").strip()


# ── バンドルの共通定数・部品(publish と setup の両側から参照する) ──

DEFAULT_TAG = "offline-bundle-v1"
BUNDLE_NAME = "offline-deps-bundle.tar.gz"
BUNDLE_KEY_NAME = "bundle.key"
WHEELHOUSE_DIR_NAME = "python-wheelhouse"
VENDOR_DIR_POSIX = "docs/_build/vendor"

# vendor 配下でバンドル由来(= `.gitignore` 対象・git 管理外)なのはこの JS 2 件だけ。
# `manifest.txt` は git 管理下なので setup 側の削除対象には含めない。
VENDOR_JS_ASSET_NAMES = ("mermaid.min.js", "mermaid-layout-elk.min.js")
VENDOR_REQUIRED_ASSET_NAMES = ("manifest.txt", *VENDOR_JS_ASSET_NAMES)

Runner = Callable[..., subprocess.CompletedProcess]


def default_runner(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    # `encoding` を明示しないと Windows既定ロケール(cp932 等)で decode され、`git` が出す
    # UTF-8 出力(日本語を含む警告・メッセージ)で読み取りスレッド内 `UnicodeDecodeError` に
    # なり、キャプチャ結果が欠落する(`scripts/hooks/post_commit.py` から `--tag-only` を
    # 呼ぶ経路で実機再現)。呼び出し元が別の `encoding` を明示した場合はそちらを優先する。
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    return subprocess.run(cmd, **kwargs)


def assert_vendor_assets_present(repo_root: Path) -> None:
    vendor_dir = repo_root / "docs" / "_build" / "vendor"
    missing = [name for name in VENDOR_REQUIRED_ASSET_NAMES if not (vendor_dir / name).is_file()]
    if missing:
        raise RuntimeError(
            f"docs/_build/vendor に不足があります: {missing}\n"
            "  offline\\setup-offline.bat で vendor 一式を展開してください。"
        )


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


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
