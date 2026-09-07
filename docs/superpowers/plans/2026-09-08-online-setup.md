# オンライン構築への移行 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** オフライン構築の資産を撤去し、依存は PyPI から、docs の mermaid ランタイムは GitHub Releases から取得するオンライン構築へ一本化する。

**Architecture:** `setup_dev.py` と `build_venv.py` から wheelhouse 経路を落として `pip install -r` だけにする。docs の mermaid ランタイムは新規 `scripts/fetch_docs_vendor.py` が Release のアセットを HTTPS 取得し、`docs/_build/vendor/manifest.txt` の sha256 と突き合わせてから配置する。`offline/` 一式と関連テストを削除する。

**Tech Stack:** Python 3.13(標準ライブラリのみ。`urllib.request` / `tarfile` / `hashlib`)、pytest、Windows の `.bat` ランチャ、GitHub Releases。

**Spec:** `docs/superpowers/specs/2026-09-08-online-setup-design.md`

## Global Constraints

- Python は常に `py -3.13` を明示する。端末には他バージョンも入りうる。
- pytest の一括実行は禁止。`scripts` / `docs/_build` / `pdf-to-svg` / `graph-editor` の 4 ディレクトリを個別に指定する。
- `.ps1` の新規追加は禁止。`.bat` は同名 `.py` を `py -3.13` で起動する薄いシムに限る(CRLF + 冒頭 `chcp 65001 >nul`)。
- pip を呼ぶファイルは `scripts/check_requirements.py` の `KNOWN_PIP_ENTRYPOINTS`(現行 4 件: `scripts/setup_dev.py` / `scripts/lib/build_venv.py` / `docs/_build/build_all.bat` / `.github/workflows/ci.yml`)に登録され、`assert_requirements_file()` を経由すること。ガードテストがこれを機械確認する。
- 新規ファイルの本文へ「pip install」という語を書かない。`_PIP_CALL_RE` が散文中の表記も拾い、未登録の pip 入口としてガードテストが落ちる。
- コメントは日本語。`docs/コメント規約.md` が正典で、`scripts/check_comments.py` が機械判定項目を検査する。
- monorepo と対で保守する範囲は変更しない。`docs/コメント規約.md` の `.ps1` docstring 例示、`scripts/check_comments.py` の `REPO_CONFIGS["workspace"]`、`scripts/check_requirements.py` の `is_offline_requirement_line` という関数名。
- Release のタグは `docs-vendor-v1`、アセット名は `docs-vendor.tar.gz`、取得元は `koichi-araki-0801/python-tools`。
- コミットのたび post-commit の auto-push 経由で pre-push が同期実行され、検証一式におよそ 110 秒かかる。

---

### Task 1: docs vendor 取得スクリプトの新設

**Files:**
- Create: `scripts/fetch_docs_vendor.py`
- Test: `scripts/test_python_tools_scripts.py`(末尾へ新しい節を追加)

**Interfaces:**
- Consumes: なし(標準ライブラリのみ)。
- Produces:
  - `parse_manifest(text: str) -> dict[str, str]` — ファイル名から sha256 への写像。
  - `sha256_file(path: Path) -> str`
  - `vendor_is_current(vendor_dir: Path, expected: dict[str, str]) -> bool`
  - `asset_url(owner: str = OWNER, repo: str = REPO, tag: str = TAG, asset: str = ASSET_NAME) -> str`
  - `http_download(url: str, dest: Path) -> None`
  - `fetch(vendor_dir: Path = VENDOR_DIR, manifest_path: Path = MANIFEST, *, url: str | None = None, downloader: Callable[[str, Path], None] = http_download) -> bool`
  - `main(argv: list[str] | None = None) -> int`
  - Task 3 の `setup_dev.py` が `fetch()` を呼ぶ。

- [ ] **Step 1: テストの import 節へ新モジュールを足す**

`scripts/test_python_tools_scripts.py` の先頭 import 節(`import setup_dev` などが並ぶ箇所)へ 1 行加える。

```python
import fetch_docs_vendor  # noqa: E402
```

- [ ] **Step 2: 失敗するテストを書く**

`scripts/test_python_tools_scripts.py` の末尾へ次の節をまるごと追加する。

```python
# ═══════════════════════════════════════════════════════════════════════════
# scripts/fetch_docs_vendor.py
# ═══════════════════════════════════════════════════════════════════════════

_VENDOR_A = "mermaid.min.js"
_VENDOR_B = "mermaid-layout-elk.min.js"


def _vendor_fixture(tmp_path, contents):
    """manifest と空の vendor ディレクトリを作り、(vendor_dir, manifest_path, expected) を返す。"""
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    lines = ["# コメント行", ""]
    expected = {}
    for name, body in contents.items():
        digest = hashlib.sha256(body).hexdigest()
        expected[name] = digest
        lines.append(f"{name}  version=1.2.3  sha256={digest}")
    manifest = vendor / "manifest.txt"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return vendor, manifest, expected


def _make_tar(path, members):
    """{アーカイブ内の名前: bytes} から tar.gz を作る。"""
    with tarfile.open(path, "w:gz") as tf:
        for name, body in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tf.addfile(info, io.BytesIO(body))


def test_parse_manifest_reads_name_and_sha256():
    text = (
        "# 説明行\n"
        "\n"
        "mermaid.min.js             version=11.12.2  sha256=" + "a" * 64 + "\n"
        "mermaid-layout-elk.min.js  source=@mermaid-js/layout-elk@0.2.2  sha256=" + "b" * 64 + "\n"
    )
    assert fetch_docs_vendor.parse_manifest(text) == {
        "mermaid.min.js": "a" * 64,
        "mermaid-layout-elk.min.js": "b" * 64,
    }


def test_parse_manifest_ignores_lines_without_sha256():
    # sha256 トークンを持たない行は「期待値が無い」ため対象にしない
    # (拾ってしまうと検証できないファイルを配置対象へ入れることになる)。
    text = "notes.txt  version=1\nmermaid.min.js  sha256=" + "c" * 64 + "\n"
    assert fetch_docs_vendor.parse_manifest(text) == {"mermaid.min.js": "c" * 64}


def test_vendor_is_current_true_when_all_files_match(tmp_path):
    vendor, _manifest, expected = _vendor_fixture(tmp_path, {_VENDOR_A: b"payload"})
    (vendor / _VENDOR_A).write_bytes(b"payload")
    assert fetch_docs_vendor.vendor_is_current(vendor, expected) is True


def test_vendor_is_current_false_when_missing_or_mismatched(tmp_path):
    vendor, _manifest, expected = _vendor_fixture(tmp_path, {_VENDOR_A: b"payload"})
    assert fetch_docs_vendor.vendor_is_current(vendor, expected) is False
    (vendor / _VENDOR_A).write_bytes(b"other")
    assert fetch_docs_vendor.vendor_is_current(vendor, expected) is False


def test_fetch_skips_download_when_already_current(tmp_path):
    vendor, manifest, _expected = _vendor_fixture(tmp_path, {_VENDOR_A: b"payload"})
    (vendor / _VENDOR_A).write_bytes(b"payload")
    calls = []

    def downloader(url, dest):
        calls.append(url)

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is True
    assert calls == []


def test_fetch_places_files_on_success(tmp_path):
    bodies = {_VENDOR_A: b"aaa", _VENDOR_B: b"bbb"}
    vendor, manifest, _expected = _vendor_fixture(tmp_path, bodies)
    archive = tmp_path / "src.tar.gz"
    _make_tar(archive, bodies)

    def downloader(url, dest):
        shutil.copyfile(archive, dest)

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is True
    assert (vendor / _VENDOR_A).read_bytes() == b"aaa"
    assert (vendor / _VENDOR_B).read_bytes() == b"bbb"


def test_fetch_rejects_unexpected_member_and_keeps_existing(tmp_path):
    # manifest に無い名前のメンバが 1 件でもあれば展開しない。
    bodies = {_VENDOR_A: b"aaa"}
    vendor, manifest, _expected = _vendor_fixture(tmp_path, bodies)
    (vendor / _VENDOR_A).write_bytes(b"old")
    archive = tmp_path / "src.tar.gz"
    _make_tar(archive, {_VENDOR_A: b"aaa", "evil.js": b"x"})

    def downloader(url, dest):
        shutil.copyfile(archive, dest)

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is False
    assert (vendor / _VENDOR_A).read_bytes() == b"old"
    assert not (vendor / "evil.js").exists()


def test_fetch_rejects_path_traversal_member(tmp_path):
    bodies = {_VENDOR_A: b"aaa"}
    vendor, manifest, _expected = _vendor_fixture(tmp_path, bodies)
    archive = tmp_path / "src.tar.gz"
    _make_tar(archive, {_VENDOR_A: b"aaa", "../escaped.js": b"x"})

    def downloader(url, dest):
        shutil.copyfile(archive, dest)

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is False
    assert not (tmp_path / "escaped.js").exists()


def test_fetch_rejects_non_regular_member(tmp_path):
    bodies = {_VENDOR_A: b"aaa"}
    vendor, manifest, _expected = _vendor_fixture(tmp_path, bodies)
    archive = tmp_path / "src.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo(_VENDOR_A)
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)

    def downloader(url, dest):
        shutil.copyfile(archive, dest)

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is False


def test_fetch_fails_on_sha256_mismatch_and_keeps_existing(tmp_path):
    vendor, manifest, _expected = _vendor_fixture(tmp_path, {_VENDOR_A: b"aaa"})
    (vendor / _VENDOR_A).write_bytes(b"old")
    archive = tmp_path / "src.tar.gz"
    _make_tar(archive, {_VENDOR_A: b"tampered"})

    def downloader(url, dest):
        shutil.copyfile(archive, dest)

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is False
    assert (vendor / _VENDOR_A).read_bytes() == b"old"


def test_fetch_fails_when_member_missing(tmp_path):
    bodies = {_VENDOR_A: b"aaa", _VENDOR_B: b"bbb"}
    vendor, manifest, _expected = _vendor_fixture(tmp_path, bodies)
    archive = tmp_path / "src.tar.gz"
    _make_tar(archive, {_VENDOR_A: b"aaa"})

    def downloader(url, dest):
        shutil.copyfile(archive, dest)

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is False
    assert not (vendor / _VENDOR_A).exists()


def test_fetch_returns_false_when_download_raises(tmp_path):
    vendor, manifest, _expected = _vendor_fixture(tmp_path, {_VENDOR_A: b"aaa"})

    def downloader(url, dest):
        raise OSError("ネットワークに到達できません")

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is False


def test_fetch_returns_false_when_manifest_missing(tmp_path):
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    assert fetch_docs_vendor.fetch(vendor, vendor / "manifest.txt", downloader=None) is False


def test_asset_url_points_at_release_download():
    url = fetch_docs_vendor.asset_url()
    assert url == (
        "https://github.com/koichi-araki-0801/python-tools/releases/download/"
        "docs-vendor-v1/docs-vendor.tar.gz"
    )


def test_repo_manifest_lists_both_runtime_files():
    # 実リポの manifest が 2 件を持つこと (書式変更でパーサが空を返す退行の検出)。
    text = (REPO_ROOT / "docs" / "_build" / "vendor" / "manifest.txt").read_text(encoding="utf-8")
    entries = fetch_docs_vendor.parse_manifest(text)
    assert set(entries) == {"mermaid.min.js", "mermaid-layout-elk.min.js"}
    assert all(len(v) == 64 for v in entries.values())
```

テストが使う `io` / `shutil` / `tarfile` / `hashlib` が import 済みかを確認し、無ければ先頭の import 節へ足す。

- [ ] **Step 3: テストを実行して失敗を確認**

Run: `py -3.13 -m pytest scripts -k fetch_docs_vendor or manifest or vendor_is_current`
Expected: FAIL(`ModuleNotFoundError: No module named 'fetch_docs_vendor'`)

- [ ] **Step 4: 実装を書く**

Create `scripts/fetch_docs_vendor.py`:

```python
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

    メンバ名を許可リストと**完全一致**で照合するため、絶対パスや `..` を含む名前は
    そもそも一致せず落ちる(展開先を外へ逃がす経路が構造的に生じない)。`filter="data"` も併用する。
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
```

- [ ] **Step 5: テストを実行して通過を確認**

Run: `py -3.13 -m pytest scripts`
Expected: PASS(既存 83 件 + 新規 14 件)

- [ ] **Step 6: コメント規約検査**

Run: `py -3.13 scripts\check_comments.py`
Expected: 0 error

- [ ] **Step 7: コミット**

```bash
git add scripts/fetch_docs_vendor.py scripts/test_python_tools_scripts.py
git commit -m "feat(docs): mermaid ランタイムを Release から取得する fetch_docs_vendor を追加"
```

---

### Task 2: exe ビルド venv のオンライン化

**Files:**
- Modify: `scripts/lib/build_venv.py`
- Modify: `graph-editor/scripts/build.py:31`(`WHEELHOUSE` 定数)と `:57`(引数渡し)
- Modify: `pdf-to-svg/scripts/build.py:27`(`WHEELHOUSE` 定数)と `:53`(引数渡し)
- Test: `scripts/test_python_tools_scripts.py`(`require_wheelhouse` の 2 テストを削除、`build_venv` のテストを新シグネチャへ)

**Interfaces:**
- Consumes: `check_requirements.assert_requirements_file(path)`(既存)。
- Produces: `build_venv(project_dir: Path, requirements_path: Path, *, clean: bool = False) -> Path`
  — 第 3 引数の `wheelhouse_dir` が無くなる。`require_wheelhouse` は消える。

- [ ] **Step 1: テストを新しい契約へ書き換える**

`scripts/test_python_tools_scripts.py` から次を削除する。

- `test_require_wheelhouse_raises_when_missing`
- `test_require_wheelhouse_passes_when_present`

`build_venv` の呼び出しテスト(現行 `test_...(tmp_path)` 内で `wheelhouse_dir` を作って渡している箇所)を次へ置き換える。既存テストの前半(venv 作成の偽 runner 準備)はそのまま使い、呼び出しと表明だけ差し替える。

```python
    result = build_venv.build_venv(project_dir, requirements_path)

    assert result == project_dir / ".venv-build" / "Scripts" / "python.exe"
    install_cmd = fake_run.calls[-1]
    assert "--no-index" not in install_cmd
    assert "--find-links" not in install_cmd
    assert install_cmd[-2:] == ["-r", str(requirements_path)]
```

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `py -3.13 -m pytest scripts -k build_venv`
Expected: FAIL(`build_venv() missing 1 required positional argument: 'wheelhouse_dir'` または `--no-index` の表明で落ちる)

- [ ] **Step 3: `build_venv.py` を書き換える**

モジュール docstring の後半を差し替える。

```python
"""共通ライブラリ: Python exe ビルド用の隔離 venv 準備。

`graph-editor/scripts/build.py` / `pdf-to-svg/scripts/build.py` から import して使う
(両者でほぼ同一だった venv 作成〜依存導入のロジックを 1 か所へ集約)。

依存は PyPI から導入する。requirements の形式検査は導入の前に必ず通す
(`assert_requirements_file`)。索引がネットワーク上にあるぶん、オプション行や直 URL 参照で
解決先を差し替えられないことの確認は省けない。
"""
```

`require_wheelhouse()` の定義を削除する。`build_venv()` のシグネチャを次へ変える。

```python
def build_venv(
    project_dir: Path,
    requirements_path: Path,
    *,
    clean: bool = False,
) -> Path:
```

install の実行部を次へ置き換える。

```python
    print("=" * 44)
    print(" [1/2] 依存ライブラリをインストール (隔離 venv 内)")
    print("=" * 44)
    result = subprocess.run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "-r",
            str(requirements_path),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError("依存のインストールに失敗しました。")
```

`assert_requirements_file(requirements_path)` の直前コメントから「`--no-index` は requirements 内の `--find-links` や直 URL 参照を止めないので、オフラインでも省略できない」という文を、次へ置き換える。

```python
    # requirements の形式検査。**pip へ渡すすべての入口で行う** (検査が一部の入口にしか
    # 無いと、そこを迂回する経路が素通りする)。
```

- [ ] **Step 4: 呼び出し側 2 ファイルを直す**

`graph-editor/scripts/build.py` と `pdf-to-svg/scripts/build.py` の双方で、次を行う。

1. `WHEELHOUSE = WORKSPACE / "python-wheelhouse"` の行を削除する。
2. 呼び出しを `venv_python = build_venv(PROJECT_DIR, REQUIREMENTS, clean=(args.action == "clean"))` にする。
3. docstring の「wheelhouse から (オフライン専用・fail-closed) 依存を install した後」を
   「依存を install した後」に改める。

`WORKSPACE` 定数は `sys.path.insert` で使っているため残す。

- [ ] **Step 5: テストを実行して通過を確認**

Run: `py -3.13 -m pytest scripts`
Expected: PASS

- [ ] **Step 6: コミット**

```bash
git add scripts/lib/build_venv.py graph-editor/scripts/build.py pdf-to-svg/scripts/build.py scripts/test_python_tools_scripts.py
git commit -m "refactor(build): exe ビルド venv の依存導入をオンラインへ切り替える"
```

---

### Task 3: `setup_dev.py` のオンライン化と vendor 取得の呼び出し

**Files:**
- Modify: `scripts/setup_dev.py`
- Test: `scripts/test_python_tools_scripts.py`(`check_wheelhouse` の 3 テストを削除、pip コマンド組み立てのテストを追加)

**Interfaces:**
- Consumes: `fetch_docs_vendor.fetch()`(Task 1)。
- Produces: `build_pip_command(py: list[str], requirements: list[Path]) -> list[str]` — 組み立てを関数へ切り出してテスト可能にする。`WHEELHOUSE` 定数と `check_wheelhouse()` は消える。`parse_args()` から `--online` が消える。

- [ ] **Step 1: テストを書き換える**

`scripts/test_python_tools_scripts.py` から次の 3 件を削除する。

- `test_check_wheelhouse_exits_when_missing_and_not_online`
- `test_check_wheelhouse_passes_when_present`
- `test_check_wheelhouse_skips_check_when_online`

同じ節へ次を追加する。

```python
def test_build_pip_command_installs_from_index(tmp_path):
    # オンライン導入なので索引を塞ぐ引数は付けない。requirements は -r で列挙する。
    req_a = tmp_path / "requirements.txt"
    req_b = tmp_path / "dev-requirements.txt"
    cmd = setup_dev.build_pip_command(["py", "-3.13"], [req_a, req_b])
    assert cmd[:5] == ["py", "-3.13", "-m", "pip", "install"]
    assert "--no-index" not in cmd
    assert "--find-links" not in cmd
    assert cmd[5:] == ["-r", str(req_a), "-r", str(req_b)]


def test_setup_dev_has_no_online_flag():
    # `--online` は既定がオンラインになったことで意味を失った。受け付けないことを固定する
    # (残っていると「明示 opt-in が要る」という誤解が生きたままになる)。
    with pytest.raises(SystemExit):
        setup_dev.parse_args(["--online"])
```

`parse_args()` が引数リストを受け取れる必要があるため、実装側のシグネチャを
`parse_args(argv: list[str] | None = None)` にする(Step 3)。

- [ ] **Step 2: テストを実行して失敗を確認**

Run: `py -3.13 -m pytest scripts -k "pip_command or online_flag or check_wheelhouse"`
Expected: FAIL(`AttributeError: module 'setup_dev' has no attribute 'build_pip_command'`)

- [ ] **Step 3: `setup_dev.py` を書き換える**

1. モジュール docstring の手順表を次へ差し替える。

```python
"""python-tools の開発環境セットアップ (`setup-dev.bat` から起動)。

行うこと:
  1. `py -3.13` と Microsoft Edge の存在確認 (どちらもこのリポの前提)。
  2. requirements の形式検査 (`check_requirements`)。
  3. requirements を PyPI から `pip` で導入する。列挙は
     `git ls-files -- '*requirements.txt'`(ハードコードしない。ファイルが増減しても追随する)。
  4. docs の mermaid ランタイムを GitHub Releases から取得する
     (`fetch_docs_vendor`)。取得できなくても警告に留めて続行する — docs の HTML ビルド
     だけが要る依存で、未配置時は整形コード表示へフォールバックするため。
  5. `git config core.hooksPath scripts/hooks` (コメント規約検査の pre-commit フックを有効化)。
  6. 実行内容のサマリを表示する。
"""
```

2. `WHEELHOUSE = ROOT / "python-wheelhouse"` を削除する。
3. `import` 節へ `from check_requirements import assert_requirements_file` と同じ並びで
   `import fetch_docs_vendor  # noqa: E402` を足す。
4. `check_wheelhouse()` を削除し、節見出しコメント `# ── 2. wheelhouse / requirements ──` を
   `# ── 2. requirements ──` に改める。
5. `list_requirements()` の docstring から「content-key 算出 (将来のオフラインバンドル構築) と
   同一集合を保つため」という文と、`offline/lib/bundle_common.py` への言及を落とす。
   同型修正の箇所数は「計 4 箇所」から「計 3 箇所」へ直す。
6. `parse_args()` を次へ置き換える。

```python
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    return parser.parse_args(argv)
```

7. pip コマンドの組み立てを関数へ切り出す。

```python
def build_pip_command(py: list[str], requirements: list[Path]) -> list[str]:
    """requirements を PyPI から導入する pip 呼び出しを組み立てる。

    索引を塞ぐ引数は付けない。解決先を差し替える形の混入は、呼び出しの前に通す
    `check_requirements` (`assert_requirements_file`) が requirements 側で止める。
    """
    cmd = [*py, "-m", "pip", "install"]
    for req in requirements:
        cmd += ["-r", str(req)]
    return cmd
```

8. `main()` を次へ直す。

```python
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
```

- [ ] **Step 4: テストを実行して通過を確認**

Run: `py -3.13 -m pytest scripts`
Expected: PASS

- [ ] **Step 5: 実際に走らせて確認**

Run: `setup-dev.bat`
Expected: 依存が PyPI から導入され、vendor は配置済みのため取得を省略し、最後まで通る。

- [ ] **Step 6: コミット**

```bash
git add scripts/setup_dev.py scripts/test_python_tools_scripts.py
git commit -m "refactor(setup): 依存導入をオンラインへ切り替え docs vendor 取得を組み込む"
```

---

### Task 4: `offline/` の撤去

**Files:**
- Delete: `offline/README-offline.md` / `offline/lib/bundle_common.py` / `offline/setup-offline.bat` / `offline/setup_offline.py`
- Modify: `scripts/test_python_tools_scripts.py`(import と関連テストの削除)
- Modify: `.gitignore`
- Modify: `scripts/check_comments.py`(`REPO_CONFIGS["python-tools"]` のみ)
- Modify: `scripts/check_requirements.py`(`find_pip_call_files` docstring の言及)

**Interfaces:**
- Consumes: なし。
- Produces: なし(撤去のみ)。

- [ ] **Step 1: テストから offline への依存を落とす**

`scripts/test_python_tools_scripts.py` から次を削除する。

1. モジュール docstring のうち `bundle_common` と `setup_offline` を説明する段落。
2. `sys.path.insert(...)` の 2 行(`offline` と `offline/lib` を足している箇所)。
3. `import bundle_common` と `import setup_offline` の 2 行。
4. `bundle_common` を使うテスト一式(requirements 列挙の 2 経路一致・content-key・
   `bundle.key` 読み書き・tar コマンド組み立て・`sha256_file`・vendor アセット検査)。
   節見出しコメントごと消す。
5. `setup_offline` を使うテスト一式(手元バンドル探索・Release 取得・sha256 サイドカー照合・
   `main` のフロー・展開・content-key 照合・統合シナリオ)。節見出しコメントごと消す。

削除後に未使用となる import(`tarfile` などを Task 1 の新テストが使うなら残す)を整理する。

- [ ] **Step 2: テストを実行して通過を確認**

Run: `py -3.13 -m pytest scripts`
Expected: PASS(`bundle_common` / `setup_offline` を参照するテストが 1 件も残っていない)

- [ ] **Step 3: `offline/` を削除する**

```bash
git rm -r offline
rm -rf offline/__pycache__
```

- [ ] **Step 4: `.gitignore` から 3 行を削除する**

削除するのは次の 3 行。

```
python-wheelhouse/
offline-deps-bundle.tar.gz*
bundle.key
```

`docs/_build/vendor/mermaid.min.js` と `docs/_build/vendor/mermaid-layout-elk.min.js` の 2 行は
残す(Release から取得する運用が続くため)。`local-only/` の行も残す
(`local-only/archive-github-dist/` が残るため)。末尾コメントの
「配布担当の端末にだけ置くバンドル生成スクリプトと、撤去した配布機構の複製」は
「撤去した配布機構の複製」へ改める。

- [ ] **Step 5: `check_comments.py` の python-tools 設定を直す**

`REPO_CONFIGS["python-tools"]` の `skip_dir_names` と `ps1_skip_dir_names` から
`"python-wheelhouse"` を削除する。`REPO_CONFIGS["workspace"]` は monorepo と対で保守する
設定のため触らない。

`check_comments.py` の `_staged_files` 付近にある「同型の修正が … `offline/lib/bundle_common.py`
… の計 4 箇所にある」という注記を、`offline/lib/bundle_common.py` を除いた「計 3 箇所」へ直す。

- [ ] **Step 6: `check_requirements.py` の注記を直す**

`find_pip_call_files` の docstring にある同型注記から `offline/lib/bundle_common.py`
(`list_requirements_files_via_git`)への言及を落とし、「計 3 箇所」へ直す。
`is_offline_requirement_line` という関数名と、その由来を説明する冒頭コメントは変更しない
(monorepo と対で保守する範囲)。

- [ ] **Step 7: 検査とテストを走らせる**

Run: `py -3.13 scripts\check_comments.py`
Expected: 0 error

Run: `py -3.13 -m pytest scripts`
Expected: PASS

- [ ] **Step 8: コミット**

```bash
git add -A
git commit -m "chore(offline): オフライン構築の資産一式を撤去する"
```

---

### Task 5: docs ビルド経路のオンライン化

**Files:**
- Modify: `docs/_build/build_all.bat:3-14`
- Modify: `docs/_build/requirements.txt:2`
- Modify: `docs/_build/md2html.py:16-24`

**Interfaces:**
- Consumes: なし。
- Produces: なし(既存の入口の挙動を変えるのみ)。

- [ ] **Step 1: `build_all.bat` を書き換える**

冒頭コメントと分岐を次へ置き換える(CRLF・`chcp 65001 >nul` は維持)。

```bat
@echo off
chcp 65001 >nul
rem 依存(PyYAML / markdown-it-py / python-frontmatter)を用意してから build_all.py を実行する。
rem pip へ渡す前に requirements の形式を検査する(オプション行・直 URL・ローカルパスを拒否)。
call "%~dp0..\..\scripts\check-requirements.bat" -Path "%~dp0requirements.txt"
if errorlevel 1 exit /b 1
rem py -3.13 を使う(本リポの前提。裸の python は WindowsApps の未導入エイリアスに化ける端末がある)。
py -3.13 -m pip install -q -r "%~dp0requirements.txt"
rem 同梱の build_all.py を実行（引数はそのまま転送）。全原稿から閲覧用 HTML（手引き/設計）を一括生成する。
py -3.13 "%~dp0build_all.py" %*
exit /b %ERRORLEVEL%
```

- [ ] **Step 2: `requirements.txt` のコメントを直す**

2 行目を次へ差し替える。

```
# build_all.bat が導入する(PyPI から)。
```

- [ ] **Step 3: `md2html.py` の設計方針コメントを直す**

「依存は `docs/_build/requirements.txt`・オフライン時は同梱 `python-wheelhouse` から導入する。」を
「依存は `docs/_build/requirements.txt` に固定し PyPI から導入する。」へ改める。

Mermaid の説明にある「（git 管理外・オフライン重量物バンドル同梱）」を
「（git 管理外。`setup-dev.bat` が GitHub Releases から取得する）」へ改める。

- [ ] **Step 4: docs ビルドを実行して確認**

Run: `docs\_build\build_all.bat`
Expected: 依存が導入され HTML が生成される。mermaid 図が描画されている(vendor は配置済みのため)。

- [ ] **Step 5: テストと検査**

Run: `py -3.13 -m pytest docs/_build`
Expected: PASS

Run: `py -3.13 -m pytest scripts`
Expected: PASS(pip 入口ガードが `docs/_build/build_all.bat` を検出し続けること)

- [ ] **Step 6: コミット**

```bash
git add docs/_build/build_all.bat docs/_build/requirements.txt docs/_build/md2html.py
git commit -m "refactor(docs): docs ビルドの依存導入をオンラインへ切り替える"
```

---

### Task 6: ドキュメントの更新

**Files:**
- Modify: `README.md:3`(冒頭)・`:19-40`(セットアップ節とオフライン重量物節)
- Modify: `docs/_build/vendor/manifest.txt:1-6`(先頭の説明)
- Modify: `docs/graph-editor/src/設計書.md:471`
- Modify: `docs/pdf-to-svg/src/設計書.md:735`
- Modify: `.github/workflows/ci.yml:62`
- Modify: `CLAUDE.md:63`(git 管理外)

**Interfaces:**
- Consumes: なし。
- Produces: なし。

- [ ] **Step 1: `README.md` の冒頭とセットアップ節を書き換える**

3 行目の「Python 専用・オフライン配布対応。」を「Python 専用。」へ改める。

セットアップ節の「行うこと」を次へ差し替える。

```markdown
行うこと:

1. `py -3.13` と Edge の存在確認。
2. `git ls-files -- '*requirements.txt'` で動的に列挙した requirements 一式を
   PyPI から `pip` で導入する。
3. docs の mermaid ランタイムを GitHub Releases から取得する(下記「docs の mermaid
   ランタイム」節)。取得できなくても警告に留めてセットアップは続行する。
4. `git config core.hooksPath scripts/hooks` — 下記「開発フロー」節の 3 フックを
   有効化する。
```

- [ ] **Step 2: 「オフライン重量物の取得」節を差し替える**

節の見出しと本文をまるごと次へ置き換える。

```markdown
### docs の mermaid ランタイム

`docs/_build/vendor/` の `mermaid.min.js` / `mermaid-layout-elk.min.js`(合わせて約 4MB)は
git に入れず、GitHub Releases(タグ `docs-vendor-v1`)の `docs-vendor.tar.gz` として配布する。
`setup-dev.bat` が `scripts/fetch_docs_vendor.py` を呼んで取得し、git 管理下の
`docs/_build/vendor/manifest.txt` に書かれた sha256 と全件一致したときだけ配置する。
既に一致していれば取得しない。

取得できなくてもセットアップは成功で終わる。この 2 ファイルは docs の HTML ビルドだけが要る
依存で、未配置のときは mermaid 図が整形コード表示になる(`md2html.py` が警告を積む)。

`mermaid-layout-elk.min.js` は `@mermaid-js/layout-elk` を esbuild で単一 IIFE へ自前バンドル
したもので、CDN に同一物は無い。版を差し替えるときはリポジトリ所有者が次を行う。

```bat
tar -czf docs-vendor.tar.gz -C docs\_build\vendor mermaid.min.js mermaid-layout-elk.min.js
gh release upload docs-vendor-v1 docs-vendor.tar.gz --clobber
```

併せて `docs/_build/vendor/manifest.txt` の sha256 を新しい実体の値へ更新してコミットする。
更新を忘れると他端末の取得は sha256 不一致で配置されず警告が出る(黙って違う実体を使うことはない)。
```

- [ ] **Step 3: `manifest.txt` の説明を直す**

先頭のコメント 6 行のうち、配布方法を説明する部分を次へ差し替える(版と sha256 の 2 行は変えない)。

```
# docs mermaid vendor manifest。
# mermaid.min.js と mermaid-layout-elk.min.js は git に入れず GitHub Releases
# (タグ docs-vendor-v1 の docs-vendor.tar.gz)として配布し、setup-dev.bat が
# scripts/fetch_docs_vendor.py 経由で docs/_build/vendor/ へ展開する。build 時は
# md2html.py がそこから読んで HTML へインラインする(mermaid 未配置時は <pre class="mermaid">
# フォールバック + 警告 / elk 未配置時は dagre + step へフォールバック)。下の有意行(版 + sha256)が
# 取得側の照合に使われ、実体を差し替えたらここも更新する。
# mermaid-layout-elk は `@mermaid-js/layout-elk` を esbuild で単一 IIFE へ自前バンドルしたもの
# (global mermaidLayoutElk)。差し替えは同手順で再バンドルする。
```

- [ ] **Step 4: 両プロジェクトの設計書を直す**

`docs/graph-editor/src/設計書.md:471` の「（オフライン優先、共有 wheelhouse 使用）」を削除する。
`docs/pdf-to-svg/src/設計書.md:735` の「（オフライン優先 = 共有 wheelhouse 使用）」を削除する。

- [ ] **Step 5: CI のコメントを直す**

`.github/workflows/ci.yml:62` の「(pip 入口ガード・requirements 検査・offline の setup)」を
「(pip 入口ガード・requirements 検査・vendor 取得)」へ改める。CI の手順自体は変えない。

- [ ] **Step 6: `CLAUDE.md` を直す**

`.bat` ランチャ規約の雛形列挙から `offline/setup-offline.bat` を外し、
`setup-dev.bat` と `scripts/check-requirements.bat` の 2 件にする。
`CLAUDE.md` は `.gitignore` 済みのためコミット対象には入らない。

- [ ] **Step 7: 検査**

Run: `py -3.13 scripts\check_comments.py`
Expected: 0 error

- [ ] **Step 8: コミット**

```bash
git add README.md docs/_build/vendor/manifest.txt docs/graph-editor/src/設計書.md docs/pdf-to-svg/src/設計書.md .github/workflows/ci.yml
git commit -m "docs: 構築手順の記述をオンライン構築の現状へ合わせる"
```

---

### Task 7: 手元の重量物を削除

**Files:**
- Delete(git 管理外): `python-wheelhouse/` / `offline-deps-bundle.tar.gz` /
  `offline-deps-bundle.tar.gz.sha256` / `offline-deps-bundle.tar.gz.sig` / `bundle.key` /
  `local-only/offline-publish/`

**Interfaces:**
- Consumes: なし。
- Produces: なし。

- [ ] **Step 1: 削除対象が git 管理外であることを確認**

Run: `git status --porcelain` と `git ls-files -- python-wheelhouse bundle.key offline-deps-bundle.tar.gz local-only`
Expected: いずれも出力が空(追跡されていない)。

- [ ] **Step 2: 削除する**

```bash
rm -rf python-wheelhouse local-only/offline-publish
rm -f offline-deps-bundle.tar.gz offline-deps-bundle.tar.gz.sha256 offline-deps-bundle.tar.gz.sig bundle.key
```

- [ ] **Step 3: 依存がインストール済みのまま動くことを確認**

Run: `py -3.13 -m pytest scripts` / `py -3.13 -m pytest docs/_build` /
`py -3.13 -m pytest pdf-to-svg` / `py -3.13 -m pytest graph-editor`
Expected: いずれも PASS(既に導入済みの依存で動く。wheelhouse を参照する経路が残っていない)。

- [ ] **Step 4: e2e も含めた検証一式**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e` と `py -3.13 -m pytest graph-editor -m e2e`
Expected: PASS

- [ ] **Step 5: コミット不要**

削除対象はすべて git 管理外のため、コミットは発生しない。`git status` が clean であることを確認する。

---

## 受け入れ確認

すべてのタスク完了後に次を実行する。

- [ ] `git grep -niE "offline|wheelhouse"` の結果が、monorepo と対で保守する範囲
  (`docs/コメント規約.md` の `.ps1` 例示・`check_comments.py` の `workspace` 設定・
  `check_requirements.py` の `is_offline_requirement_line`)だけであること。
- [ ] `py -3.13 scripts\check_comments.py` が 0 error。
- [ ] 4 ディレクトリの pytest がすべて PASS。
- [ ] `pdf-to-svg` / `graph-editor` の e2e が PASS。
- [ ] `python-wheelhouse/` が無い状態で `setup-dev.bat` が最後まで通る。
- [ ] Release がまだ無い状態で vendor 取得が警告に留まり、セットアップが成功する
  (`docs/_build/vendor/` の 2 ファイルを一時退避して確認し、確認後に戻す)。
