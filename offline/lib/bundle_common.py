# -*- coding: utf-8 -*-
"""共通ライブラリ: offline 重量物バンドルの content-key 算出・pin 読み書き・Ed25519 署名。

`offline/publish_bundle.py` / `offline/setup_offline.py` から import して使う。
署名鍵は Ed25519-PEM(`cryptography`)を使う。content-key はファイル内容の連結を基本とし、
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

import base64
import binascii
import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

# `cryptography` はここでは import しない(モジュール冒頭での import は署名系の 3 関数
# だけが必要とする依存を本ファイル全体の import 条件にしてしまう)。配布先の
# `offline/setup_offline.py` は手順1-4(pin 読込・バンドル取得・sha256 照合・展開)を
# `cryptography` が入っていない状態で行い、手順5で wheelhouse から導入した後に初めて
# 署名検証(手順6)を呼ぶ。この順序を成立させるには、署名系の関数だけが個別に
# 遅延 import する必要がある(関数側の docstring 参照)。

# ── requirements.txt の列挙 ──

# FS フォールバックが除外するディレクトリ。`.git`(git 管理領域)と `python-wheelhouse`
# (重量物置き場。gitignore 対象)は git 経路でも最初から候補に入らないため、ここで除いておけば
# 「git が使えない環境」でも同じ集合になる。`.venv*` は `setup_dev.py` / `check_comments.py` と
# 同じ命名規約(ビルド用隔離venv は `.venv-build`)。
_FS_EXCLUDED_DIR_NAMES = frozenset({".git", "python-wheelhouse"})
_FS_EXCLUDED_DIR_PREFIXES = (".venv",)

VENDOR_MANIFEST_REL = Path("docs") / "_build" / "vendor" / "manifest.txt"


def list_requirements_files_via_git(repo_root: Path) -> list[Path] | None:
    """`git ls-files -- '*requirements.txt'` で追跡中の requirements ファイルを列挙する。

    git が使えない、または `repo_root` が git 管理外なら `None` を返す(呼び出し元に
    FS フォールバックへの切り替えを促す)。
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--", "*requirements.txt"],
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
    files = [repo_root / line for line in result.stdout.splitlines() if line.strip()]
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


# ── pin(offline/pinned-release.txt)の読み書き ──


@dataclass(frozen=True)
class PublishPin:
    """`offline/pinned-release.txt` の内容(公開時に publish が書き、setup が検証で読む)。"""

    source_commit: str
    source_zip_sha256: str
    bundle_sha256: str


def format_pin(pin: PublishPin) -> str:
    """`PublishPin` を pin ファイルのテキスト表現へ整形する。"""
    return (
        "# offline 配布物の pin(publish_bundle.py が自動生成。手で編集しない)。\n"
        "# 配布先の setup はこの値だけを真正性の根拠にする。\n"
        f"source-commit {pin.source_commit}\n"
        f"source-zip-sha256 {pin.source_zip_sha256}\n"
        f"bundle-sha256 {pin.bundle_sha256}\n"
    )


def write_pin(path: Path, pin: PublishPin) -> None:
    """pin ファイルを書き出す。"""
    path.write_text(format_pin(pin), encoding="utf-8")


def read_pin(path: Path) -> PublishPin:
    """pin ファイルを読み検証する。欠落・形式不正は `ValueError`(fail closed)。"""
    if not path.is_file():
        raise ValueError(
            f"pin ファイルがありません: {path}\n"
            "  offline/ 同梱の期待値が無いと取得物の真正性を配信元と独立に確かめられない。"
        )
    text = path.read_text(encoding="utf-8")
    values: dict[str, str] = {}
    for line in text.splitlines():
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        parts = t.split(None, 1)
        if len(parts) != 2:
            continue
        values[parts[0].lower()] = parts[1].strip().lower()

    for key in ("source-commit", "source-zip-sha256", "bundle-sha256"):
        if key not in values:
            raise ValueError(f"pin ファイルに {key} がありません: {path}")

    source_commit = values["source-commit"]
    if len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
        raise ValueError(f"pin ファイルの source-commit が 40 桁 16 進ではありません: {source_commit}")

    for key in ("source-zip-sha256", "bundle-sha256"):
        v = values[key]
        if len(v) != 64 or any(c not in "0123456789abcdef" for c in v):
            raise ValueError(f"pin ファイルの {key} が 64 桁 16 進ではありません: {v}")

    return PublishPin(
        source_commit=source_commit,
        source_zip_sha256=values["source-zip-sha256"],
        bundle_sha256=values["bundle-sha256"],
    )


# ── bundle.key(content-key を書いた 1 行ファイル)の読み書き ──


def write_bundle_key(path: Path, content_key: str) -> None:
    path.write_text(content_key, encoding="ascii")


def read_bundle_key(path: Path) -> str:
    return path.read_text(encoding="ascii").strip()


# ── Ed25519 分離署名 ──


def generate_signing_key_pair() -> tuple[bytes, bytes]:
    """Ed25519 鍵ペアを生成し、`(private_pem, public_pem)` を返す。

    `cryptography` はここで初めて import する(遅延 import。モジュール冒頭のコメント参照)。
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    private_key = ed25519.Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def sign_bytes(data: bytes, private_key_pem: bytes) -> str:
    """`data` へ Ed25519 署名し、64 byte 署名の base64 文字列(`.sig` の中身)を返す。

    Ed25519 は incremental signing API を持たない(pure EdDSA はメッセージ全体を要求する)ため
    全内容をメモリへ持つ必要がある。バイト列版を公開しておくと、呼び出し側が同一内容を
    署名・検証の両方で使う場合(例: 自己検証)に読み込みを 1 回で済ませられる。

    `cryptography` はここで初めて import する(遅延 import。モジュール冒頭のコメント参照)。
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(private_key, ed25519.Ed25519PrivateKey):
        raise ValueError("秘密鍵が Ed25519 形式ではありません。")
    signature = private_key.sign(data)
    return base64.b64encode(signature).decode("ascii")


def sign_file(path: Path, private_key_pem: bytes) -> str:
    """`path` の内容へ Ed25519 署名し、64 byte 署名の base64 文字列(`.sig` の中身)を返す。

    重量物バンドル(tar.gz)は数百 MB 級になりうるが、署名は publish 時に 1 回だけ行う
    操作であり全読みを許容する。
    """
    return sign_bytes(path.read_bytes(), private_key_pem)


def verify_signature_bytes(data: bytes, signature_b64: str, public_key_pem: bytes) -> bool:
    """`data` を `signature_b64`(base64)/`public_key_pem` で検証する。真なら合格。

    署名・鍵の形式不正(base64 でない・PEM でない等)も「検証失敗」に倒す(fail closed)。

    `cryptography` はここで初めて import する(遅延 import。モジュール冒頭のコメント参照)。
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    try:
        signature = base64.b64decode(signature_b64.strip(), validate=True)
    except (binascii.Error, ValueError):
        return False
    try:
        public_key = serialization.load_pem_public_key(public_key_pem)
        if not isinstance(public_key, ed25519.Ed25519PublicKey):
            return False
        public_key.verify(signature, data)
        return True
    except InvalidSignature:
        return False
    except (ValueError, TypeError):
        return False


def verify_signature(path: Path, signature_b64: str, public_key_pem: bytes) -> bool:
    """`path` の内容を `signature_b64`(base64)/`public_key_pem` で検証する。真なら合格。"""
    return verify_signature_bytes(path.read_bytes(), signature_b64, public_key_pem)


def assert_bundle_signature(path: Path, signature_b64: str, public_key_pem: bytes) -> None:
    """署名検証を「必ず通す」入口。失敗したら `RuntimeError`(fail closed)。"""
    if not verify_signature(path, signature_b64, public_key_pem):
        raise RuntimeError(
            f"分離署名の検証に失敗しました: {path}\n"
            "  改ざん・すり替え、または公開鍵と署名鍵の不一致。処理を中止する。"
        )
