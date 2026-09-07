#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""requirements.txt が「名前 + 省略可能なバージョン指定子」だけで書かれているかを検査する。

monorepo `offline/lib/verify.ps1` の `Test-OfflineRequirementLine` /
`Assert-OfflineRequirementsFile` の移植。pip は requirements ファイル内のオプション行
(`--extra-index-url` / `--find-links` / `-e` 等)・直 URL 参照 (`pkg @ https://...`)・
ベアなローカルパス (`./downloads/numpy-1.9.2-cp34-none-win32.whl` は pip 公式ドキュメントに
載る正式な形) をすべて requirement として受け取る。編集 1 行で解決先そのものを差し替え
られるため、ここは**受け入れる形だけを書く** (危険物の列挙にしない)。

拒否条件を並べる方式は、書いた本人が思いつかなかった形を必ず通す。受け入れるのは
「名前 + 省略可能なバージョン指定子」だけ。extras / 環境マーカ / URL / パス / ハッシュ指定は
すべて不可。

CLI は `-Path <file>` (`docs/_build/build_all.bat` 互換) と位置引数の両方を受け付ける。
複数ファイルを渡すと全件を検査する。

pip を呼ぶ入口の列挙ガード(`KNOWN_PIP_ENTRYPOINTS` / `find_pip_call_files`)もここに置く。
検査を経ない pip 入口を作らないための機械検査で、`scripts/test_python_tools_scripts.py` が
既知集合との一致を固定する。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_SPEC = r"(?:==|>=|<=|~=|!=|>|<)\s*[A-Za-z0-9][A-Za-z0-9.*+!-]*"
_LINE_RE = re.compile(rf"^{_NAME}(?:\s*{_SPEC})*$")

# pip が**拡張子でアーカイブと判定**する綴りの全集合 (pip の `is_archive_file` と対になる
# 集合。ここが漏れると pip が別解釈で解決してしまう)。tar 系の別綴り (tbz / tlz /
# tar.lz = 末尾 lz / tar.lzma = 末尾 lzma) まで含めて網羅する。
_ARCHIVE_EXT_RE = re.compile(r"(?i)\.(?:whl|zip|tar|tgz|tbz2|tbz|txz|tlz|egg|gz|bz2|xz|lz|lzma)$")


def is_offline_requirement_line(line: str) -> bool:
    """1 行が「名前 + 省略可能なバージョン指定子」だけかを判定する。"""
    # 行内コメント (` #` 以降) は pip も無視するので落としてから見る。
    t = re.sub(r"\s+#.*$", "", line).strip()
    if not t:
        return True
    if not _LINE_RE.match(t):
        return False
    if _ARCHIVE_EXT_RE.search(t):
        return False
    # パス区切りを含む行はローカルパス参照。拡張子網羅と二重で、リポジトリ内ファイルを
    # 指す形を確実に落とす (ベアな名前は index/wheelhouse からしか解決されない)。
    if "\\" in t or "/" in t:
        return False
    return True


def check_requirements_file(path: Path) -> list[str]:
    """`path` の全行を検査し、違反の説明文字列の一覧を返す (空なら合格)。"""
    violations: list[str] = []
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        t = line.strip()
        if not t or t.startswith("#"):
            continue
        if not is_offline_requirement_line(line):
            violations.append(f"{path}:{lineno}: 名前とバージョン指定子だけを書けます: {t}")
    return violations


def assert_requirements_file(path: Path) -> None:
    """検査に落ちたら `RuntimeError`。**pip へ渡すすべての入口から呼ぶこと。**

    ガードが一部の入口にしか無いと、そこを迂回する経路 (別のビルドスクリプト・
    別のドキュメントビルド等) が素通りする。`--no-index` は requirements 内の
    `--find-links <URL>` を止めないので「オフラインだから安全」も成立しない。

    `SystemExit` でなく `RuntimeError` を送出する: `SystemExit` は `BaseException` 直系で
    `Exception` を継承しないため、呼び出し側 (`build_venv.py` 経由の `graph-editor` /
    `pdf-to-svg` の `scripts/build.py`) が持つ通常の `except Exception` を素通りしてしまう
    (捕まらないと `[エラー] ...` 表示とダブルクリック起動時の一時停止が飛ぶ)。CLI (`main`)
    側でこの例外を受けて終了コード化する。
    """
    violations = check_requirements_file(path)
    if violations:
        for v in violations:
            print(f"[requirements] {v}", file=sys.stderr)
        raise RuntimeError(f"requirements の形式検査に失敗しました: {path}")


# ── pip 入口列挙ガード ──

# 「入口」= リポ内で pip install/download を実行するファイル。`.py` / `.yml` / `.yaml` に
# 加えて `.bat` も走査する(`docs/_build/build_all.bat` のように `.bat` から直接 pip を
# 呼ぶ実例があるため、拡張子で機械的に対象外にはできない)。
KNOWN_PIP_ENTRYPOINTS = frozenset(
    {
        "scripts/setup_dev.py",
        "scripts/lib/build_venv.py",
        "docs/_build/build_all.bat",
        ".github/workflows/ci.yml",
    }
)

# 除外は「ガード自身の定義・テストファイル」という構造的な 2 件だけ(どちらも
# 「pip install」という語を含む説明コメントを持つため、自己参照的に誤検知する)。
# 個々の pip 呼び出しファイルを見つけてから除外リストへ足す、という運用はしない
# (それは `KNOWN_PIP_ENTRYPOINTS` へ登録する形で行う)。
_GUARD_SELF_EXCLUDE = frozenset({"scripts/check_requirements.py", "scripts/test_python_tools_scripts.py"})

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


def find_pip_call_files(
    repo_root: Path, *, runner: Callable[..., subprocess.CompletedProcess] | None = None
) -> set[str]:
    """`pip install` / `pip download` を呼ぶ(と読める)追跡ファイルの相対パス集合を返す。

    走査対象は `_PIP_SCAN_EXTENSIONS`(`.py` / `.yml` / `.yaml` / `.bat`)に絞る。
    ガード自身の定義ファイルとテストファイルは除外する(`_GUARD_SELF_EXCLUDE`)。

    列挙は `-z`(NUL 区切り)出力を使う。git は既定(`core.quotepath=true`)では非 ASCII
    パスを引用符 + 8 進エスケープした文字列で返し、`rel.endswith(_PIP_SCAN_EXTENSIONS)` が
    末尾の `"` に阻まれて一致しなくなる(検査対象から黙って落ちる。実証済み)。`-z` は
    `core.quotepath` の設定に関わらずエスケープなしの生バイト列を NUL 区切りで返すため、
    この問題が構造的に起きない。同型の修正が `scripts/check_comments.py`
    (`_staged_files`)・`scripts/setup_dev.py`(`list_requirements`)の計 3 箇所にある。
    """
    cmd = ["git", "-C", str(repo_root), "ls-files", "-z"]
    if runner is None:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    else:
        result = runner(cmd)
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


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-Path",
        dest="path_flag",
        default=None,
        help="検査対象 requirements.txt (docs/_build/build_all.bat 互換の呼び出し形)",
    )
    parser.add_argument(
        "paths", nargs="*", help="検査対象 requirements.txt (複数可。-Path 未指定時に使う)"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    targets = [args.path_flag] if args.path_flag else list(args.paths)
    if not targets:
        print(
            "[error] 検査対象の requirements.txt を指定してください (-Path または位置引数)",
            file=sys.stderr,
        )
        return 1

    ok = True
    for t in targets:
        violations = check_requirements_file(Path(t))
        if violations:
            ok = False
            for v in violations:
                print(f"[requirements] {v}", file=sys.stderr)
        else:
            print(f"[ok] {t}")

    if not ok:
        print("requirements の形式検査に失敗しました", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
