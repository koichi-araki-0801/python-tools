#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""コメント規約 (`docs/コメント規約.md`) のうち機械判定できる項目だけを検査する。

「日本語かどうか」の厳密判定はしない (誤検知を避けるため)。検査項目は 3 ルール族:

  - ハード失敗 (exit 1): `.ps1` の扱い (BOM / `.bat` 併設、またはリポによっては
    `.ps1` そのものの不在)、コメント・テスト名・docs 原稿に残るレビュー所見番号
    (英字 1 文字 + 番号の識別子)。
  - 警告のみ (exit 0): `.ts`/`.js` 系ファイル先頭の装飾ボックスヘッダ有無。

検査ロジックは monorepo `scripts/check-comments.mjs` と同一実装であり、リポジトリ間の
差異は本ファイル冒頭の `REPO_CONFIGS` にだけ閉じる。他リポで使う場合は新しいキーを
`REPO_CONFIGS` へ足し `ACTIVE_REPO` を切り替えるだけでよい (ロジック本体は変更しない)。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── 0. リポ別設定 ──
# 「同一実装 + リポ別設定」の要。検査ロジック (§3〜§5) はここを読むだけで、
# リポジトリ名指しの分岐を持たない。キーの意味:
#   skip_dir_names / skip_dir_prefixes : 全走査 (§4 box header・§5 所見番号) の除外
#   ps1_mode        : "forbid" = `.ps1` が 1 つでもあればエラー
#                      (Python + `.bat` ランチャのみで構成するリポ向け)。
#                      "check" = 旧来どおり BOM + `.bat` 併設を個別に検査
#                      (`.ps1` を実際に運用する monorepo 側で使う想定)。
#   ps1_skip_dir_names / ps1_skip_dir_prefixes : `.ps1` 探索専用の除外
#   bat_pairing_exceptions : "check" モードで `.bat` 併設を免除するパス集合
#   box_header_roots : 装飾ボックスヘッダ検査の対象ルート一覧。`None` はリポ全体
#   shell_shim_prefixes : 拡張子なしファイルをシェルスクリプト扱いする前方一致集合
#                          (例: git hook シム)
#   docs_src_pattern : docs 原稿側の所見番号検査を当てるパスの正規表現
#   finding_id_skip_prefixes : §5 所見番号検査だけを免除する前方一致パス集合
#                               (ディレクトリ自体は §4 等の走査対象に残る点が
#                               `skip_dir_names` と違う)。monorepo 側では PDF 抽出の
#                               生テキストサンプルを置く `("docs/_samples/",)` を使う。
#                               python-tools では該当ディレクトリが無いため空。
REPO_CONFIGS: dict[str, dict] = {
    "python-tools": {
        "skip_dir_names": frozenset(
            {
                ".git",
                "__pycache__",
                ".pytest_cache",
                "python-wheelhouse",
                "dist",
                "build",
                "out",
                "coverage",
                "test-results",
                "vendor",
            }
        ),
        "skip_dir_prefixes": (".venv",),
        "ps1_mode": "forbid",
        "ps1_skip_dir_names": frozenset({".git", "python-wheelhouse"}),
        "ps1_skip_dir_prefixes": (".venv",),
        "bat_pairing_exceptions": frozenset(),
        "box_header_roots": None,
        "shell_shim_prefixes": ("scripts/hooks/",),
        "docs_src_pattern": re.compile(r"^docs/[^/]+/src/"),
        "finding_id_skip_prefixes": (),
    },
}
ACTIVE_REPO = "python-tools"
CFG = REPO_CONFIGS[ACTIVE_REPO]

LINE_SPLIT_RE = re.compile(r"\r\n|\r|\n")


def rel(f: Path) -> str:
    """`ROOT` 基準の相対パスを `/` 区切りで返す。"""
    return f.relative_to(ROOT).as_posix()


# ── 1. ファイル収集 (§4 box header・§5 所見番号 共用) ──
def _is_skip_dir(name: str) -> bool:
    if name in CFG["skip_dir_names"]:
        return True
    return any(name.startswith(p) for p in CFG["skip_dir_prefixes"])


def walk(directory: Path, acc: list[Path]) -> None:
    """`directory` 配下のファイルを再帰収集する (`skip_dir_names` 等は降りない)。"""
    for entry in sorted(directory.iterdir(), key=lambda p: p.name):
        if entry.is_dir():
            if _is_skip_dir(entry.name):
                continue
            walk(entry, acc)
        else:
            acc.append(entry)


# ── 2. PowerShell 検査 (§3: forbid / check の 2 モード) ──
def _find_ps1_files() -> list[Path]:
    skip_names = CFG["ps1_skip_dir_names"]
    skip_prefixes = CFG["ps1_skip_dir_prefixes"]

    def is_skip(name: str) -> bool:
        if name in skip_names:
            return True
        return any(name.startswith(p) for p in skip_prefixes)

    acc: list[Path] = []

    def _walk(directory: Path) -> None:
        for entry in sorted(directory.iterdir(), key=lambda p: p.name):
            if entry.is_dir():
                if is_skip(entry.name):
                    continue
                _walk(entry)
            elif entry.suffix == ".ps1":
                acc.append(entry)

    _walk(ROOT)
    return acc


def check_ps1(errors: list[str], restrict_to: frozenset[str] | None = None) -> None:
    mode = CFG["ps1_mode"]
    ps1_files = _find_ps1_files()
    if restrict_to is not None:
        ps1_files = [f for f in ps1_files if rel(f) in restrict_to]

    if mode == "forbid":
        # このリポは Python + `.bat` ランチャだけで構成する方針 (設計正典参照)。
        # `.ps1` が 1 つでも見つかったら、置き場を間違えたコードとして落とす。
        for f in ps1_files:
            errors.append(
                f"{rel(f)}: .ps1 は使用しない方針 (このリポは Python + .bat ランチャで統一する。"
                ".py へ書き換えるか、.ps1 が要るリポの config へ移す)"
            )
        return

    if mode == "check":
        # 非 ASCII を含む `.ps1` は cp932 環境での文字化け回避のため UTF-8 BOM 必須。
        # 併せて、単体起動する `.ps1` には同名 `.bat` ランチャの併設を要求する
        # (dot-source 専用ライブラリ・Pester テストは `bat_pairing_exceptions` で免除)。
        exceptions = CFG["bat_pairing_exceptions"]
        for f in ps1_files:
            r = rel(f)
            buf = f.read_bytes()
            has_non_ascii = any(b > 0x7F for b in buf)
            has_bom = buf[:3] == b"\xef\xbb\xbf"
            if has_non_ascii and not has_bom:
                errors.append(
                    f"{r}: 非 ASCII を含む .ps1 に UTF-8 BOM が無い (cp932 文字化け回避のため必須)"
                )
            if r not in exceptions and not r.endswith(".Tests.ps1"):
                bat = f.with_suffix(".bat")
                if not bat.exists():
                    errors.append(f"{r}: 同名 .bat ランチャが無い (.ps1 には .bat を併設する)")
        return

    raise ValueError(f"unknown ps1_mode: {mode!r}")


# ── 3. TS/JS のファイル先頭装飾ボックスヘッダ (§4: 警告のみ) ──
TSJS_EXT = {".ts", ".tsx", ".js", ".cjs", ".mjs"}


def _starts_with_box_header(text: str) -> bool:
    # 先頭の shebang / triple-slash 指示子 / 'use strict' 行は読み飛ばして判定する。
    lines = LINE_SPLIT_RE.split(text)
    i = 0
    while i < len(lines):
        t = lines[i].strip()
        if t == "":
            i += 1
            continue
        if t.startswith("#!") or t.startswith("///") or t.startswith("'use "):
            i += 1
            continue
        break
    return i < len(lines) and lines[i].strip().startswith("// ===")


def _in_box_root(r: str) -> bool:
    roots = CFG["box_header_roots"]
    if roots is None:
        return True
    return any(r == root or r.startswith(f"{root}/") for root in roots)


def check_box_headers(warnings: list[str], all_files: list[Path]) -> None:
    for f in all_files:
        if f.suffix not in TSJS_EXT:
            continue
        r = rel(f)
        if not _in_box_root(r):
            continue
        if r.endswith(".d.ts"):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "AUTO-GENERATED" in text[:200]:  # 自動生成物は手編集しない
            continue
        if not _starts_with_box_header(text):
            warnings.append(f"{r}: ファイル先頭の装飾ボックスヘッダ (// ===) が無い")


# ── 4. レビュー所見番号の残存 (§5: ハード失敗) ──
# 規約「過去の経緯を書かない」のうち機械判定できる形 = 監査所見の識別子 (「所見」+ 番号、
# 英字 F/P/R + 番号、root + 英字番号、run + 番号) を、コメント行・テスト名・docs 原稿から
# 締め出す。番号は監査資料の中でしか意味を持たず、コードを読む人には解決できない参照になる
# ため。誤検知が出たら除外表を足すのではなく文面を直す。
FINDING_ID_CODE = [
    re.compile(r"所見\s*[A-Z]?\d"),
    re.compile(r"(?<![A-Za-z0-9_])[FPR]\d{1,3}(?![A-Za-z0-9_.])"),
    re.compile(r"root A\d"),
    re.compile(r"旧 P\d{3}"),
    re.compile(r"前回 R\d"),
    re.compile(r"(?<![A-Za-z0-9_])run \d(?![A-Za-z0-9_])"),
]
# docs 原稿は mermaid のノード ID (英字 + 番号) やキー名を含むため、番号単独では見ず
# 所見参照の言い回しだけを拾う。
FINDING_ID_DOCS = [
    re.compile(r"所見\s*[A-Z]?\d"),
    re.compile(r"旧 P\d{3}"),
    re.compile(r"前回 R\d"),
    re.compile(
        r"(?<![A-Za-z0-9_])[FPR]\d{1,3}\s*(の|と同じ|と同一)\s*"
        r"(判断|経路|脅威|仕様|主張|実害|再発)"
    ),
]
TEST_NAME_RE = re.compile(
    r"(?<![A-Za-z0-9_.])(?:describe|it|test)(?:\.\w+)*\(\s*(['\"`])((?:\\.|(?!\1).)*)\1"
)

# 拡張子ごとの行コメント接頭辞とブロックコメントの開閉。ブロック内の行は全部コメント行。
COMMENT_SYNTAX = {
    "ts": {"line": ["//"], "block": [("/*", "*/"), ("<!--", "-->")]},
    "py": {"line": ["#"], "block": [('"""', '"""'), ("'''", "'''")]},
    "ps1": {"line": ["#"], "block": [("<#", "#>")]},
    "sh": {"line": ["#"], "block": []},
    "sql": {"line": ["--"], "block": [("/*", "*/")]},
}
EXT_SYNTAX = {
    ".ts": "ts",
    ".tsx": "ts",
    ".js": "ts",
    ".cjs": "ts",
    ".mjs": "ts",
    ".vue": "ts",
    ".py": "py",
    ".ps1": "ps1",
    ".psm1": "ps1",
    ".sh": "sh",
    ".sql": "sql",
}
IS_TEST_FILE_RE = re.compile(r"(\.test\.|\.e2e\.|\.spec\.|/test_[^/]*\.py$)")


def _is_test_file(r: str) -> bool:
    return bool(IS_TEST_FILE_RE.search(r))


def _syntax_key_for(r: str, ext: str) -> str | None:
    if ext in EXT_SYNTAX:
        return EXT_SYNTAX[ext]
    if ext == "" and any(r.startswith(p) for p in CFG["shell_shim_prefixes"]):
        return "sh"
    return None


def _comment_lines(text: str, syntax: dict) -> list[tuple[int, str]]:
    """コメント行を列挙する。ブロックコメントは開始行〜終了行までを丸ごと拾う。"""
    out: list[tuple[int, str]] = []
    open_end: str | None = None
    lines = LINE_SPLIT_RE.split(text)
    for i, raw in enumerate(lines):
        t = raw.strip()
        if open_end is not None:
            out.append((i + 1, raw))
            if open_end in t:
                open_end = None
            continue
        if any(t.startswith(p) for p in syntax["line"]) or t.startswith("*"):
            out.append((i + 1, raw))
            continue
        # 行末コメント (`code  # 説明`)。文字列中の `#`/`//` を拾う誤検知は、所見番号の形が
        # 文字列に現れないこと (URL・色コードは英字+数字の並びが違う) で実用上避けられる。
        trailing_positions = [p for p in (raw.find(f" {t2}") for t2 in syntax["line"]) if p >= 0]
        if trailing_positions:
            at = min(trailing_positions)
            out.append((i + 1, raw[at:]))
            continue
        for start, end in syntax["block"]:
            at = raw.find(start)
            if at < 0:
                continue
            out.append((i + 1, raw))
            if end not in raw[at + len(start) :]:  # 同じ行で閉じていなければ開いたまま次行へ
                open_end = end
            break
    return out


def _check_finding_ids(errors: list[str], r: str, text: str, syntax_key: str, patterns: list) -> None:
    syntax = COMMENT_SYNTAX[syntax_key]
    for ln, line in _comment_lines(text, syntax):
        hit = next((p for p in patterns if p.search(line)), None)
        if hit:
            errors.append(
                f"{r}:{ln}: コメントにレビュー所見番号が残っている ({hit.pattern}) — "
                "現在形の理由へ書き換える"
            )
    if _is_test_file(r):
        for m in TEST_NAME_RE.finditer(text):
            name = m.group(2)
            hit = next((p for p in patterns if p.search(name)), None)
            if not hit:
                continue
            ln = text[: m.start()].count("\n") + 1
            errors.append(
                f"{r}:{ln}: テスト名にレビュー所見番号が残っている ({hit.pattern}) — "
                "番号を外し内容で名付ける"
            )


def check_finding_ids_all(errors: list[str], all_files: list[Path]) -> None:
    docs_pattern = CFG["docs_src_pattern"]
    skip_prefixes = CFG["finding_id_skip_prefixes"]
    for f in all_files:
        r = rel(f)
        if any(r.startswith(p) for p in skip_prefixes):
            continue
        ext = f.suffix
        key = _syntax_key_for(r, ext)
        if key:
            if r.endswith(".d.ts"):
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            _check_finding_ids(errors, r, text, key, FINDING_ID_CODE)
            continue
        if ext == ".md" and docs_pattern.match(r):
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for i, line in enumerate(LINE_SPLIT_RE.split(text)):
                hit = next((p for p in FINDING_ID_DOCS if p.search(line)), None)
                if hit:
                    errors.append(
                        f"{r}:{i + 1}: docs 原稿にレビュー所見番号が残っている ({hit.pattern}) — "
                        "番号を消し内容で書く"
                    )


# ── 5. エントリポイント ──
def _force_utf8_streams() -> None:
    # Windows既定コンソールは cp932 等になり、メッセージ中の em dash 等が
    # UnicodeEncodeError で出力を落とす。検査結果を確実に出せるよう UTF-8 へ固定する。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _staged_files() -> frozenset[str]:
    """`git diff --cached` のステージ済みファイル一覧を `/` 区切り相対パスで返す。

    削除 (`D`) はここでは対象外にする (ファイル実体が無く検査できないため)。
    """
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return frozenset(line.strip() for line in out.stdout.splitlines() if line.strip())


def main() -> int:
    _force_utf8_streams()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--staged",
        action="store_true",
        help=(
            "全ツリーではなく `git diff --cached` のステージ済みファイルだけを検査する "
            "(pre-commit フック用。無関係な既存ファイルの警告/エラーで commit を止めない)"
        ),
    )
    args = parser.parse_args()

    restrict: frozenset[str] | None = None
    if args.staged:
        restrict = _staged_files()
        all_files = [f for p in restrict if (f := ROOT / p).is_file()]
    else:
        all_files = []
        walk(ROOT, all_files)

    errors: list[str] = []
    warnings: list[str] = []

    check_ps1(errors, restrict_to=restrict)
    check_box_headers(warnings, all_files)
    check_finding_ids_all(errors, all_files)

    for w in warnings:
        print(f"WARN  {w}", file=sys.stderr)
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)

    print(
        f"\ncheck-comments: {len(errors)} error(s), {len(warnings)} warning(s) "
        f"(走査 {len(all_files)} files)"
    )

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
