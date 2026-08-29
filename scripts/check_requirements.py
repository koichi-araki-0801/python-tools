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
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

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
    """検査に落ちたら `SystemExit`。**pip へ渡すすべての入口から呼ぶこと。**

    ガードが一部の入口にしか無いと、そこを迂回する経路 (別のビルドスクリプト・
    別のドキュメントビルド等) が素通りする。`--no-index` は requirements 内の
    `--find-links <URL>` を止めないので「オフラインだから安全」も成立しない。
    """
    violations = check_requirements_file(path)
    if violations:
        for v in violations:
            print(f"[requirements] {v}", file=sys.stderr)
        raise SystemExit(f"requirements の形式検査に失敗しました: {path}")


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
