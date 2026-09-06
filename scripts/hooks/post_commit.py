#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""post-commit フック本体。auto-push のベストエフォート呼び出し。

`scripts/hooks/post-commit`(sh シム)から `py -3.13` で起動される。git はコミットが
確定した**後**にこのフックを呼ぶため、ここで失敗してもコミット自体は取り消せない。
処理を警告のみ(exit 0)にとどめ、コミットの成否とは切り離す。

行うこと:
  1. auto-push: 現在ブランチを upstream(無ければ `origin HEAD` で新規 upstream 設定)へ
     push する。force はしない — non-fast-forward で拒否された場合はメッセージを出すだけで、
     force push はここから自動実行しない(amend 直後の分岐を誤検知して他人の push を
     潰す事故を避けるため。復旧は利用者が手動で `git push --force-with-lease` を行う)。

`git` を実際に呼ぶ処理は `runner` を受け取り、既定は実 `subprocess.run` だが呼び出し側から
差し替えられる(単体テストは偽 runner を注入し、実 git push は起動しない)。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent.parent

Runner = Callable[..., subprocess.CompletedProcess]


def default_runner(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    # `encoding` を明示しないと Windows既定ロケール (cp932 等) で decode され、`git push`
    # が出す UTF-8 出力 (pre-push フック自身が出す日本語メッセージを含む) で
    # `UnicodeDecodeError` が読み取りスレッド内で発生し、出力が欠落したまま呼び出し元へ
    # 戻ってしまう (実機で auto-push のメッセージが空文字になる形で再現)。
    return subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs
    )


# ── 1. auto-push ──
def has_upstream(*, runner: Runner = default_runner) -> bool:
    result = runner(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    return result.returncode == 0


def build_push_command(*, upstream_configured: bool) -> list[str]:
    """upstream の有無から push コマンドを組み立てる(判定と組み立てを分離してテストしやすくする)。"""
    return ["git", "push"] if upstream_configured else ["git", "push", "-u", "origin", "HEAD"]


def auto_push(*, runner: Runner = default_runner) -> None:
    cmd = build_push_command(upstream_configured=has_upstream(runner=runner))
    result = runner(cmd)
    if result.returncode == 0:
        out = (result.stdout or result.stderr or "done").strip()
        print(f"[post-commit] auto-push: {out}")
        return
    msg = (result.stderr or result.stdout or "").strip()
    print(f"[post-commit] auto-push をスキップしました: {msg}", file=sys.stderr)
    if any(k in msg.lower() for k in ("non-fast-forward", "rejected", "fetch first")):
        print(
            "[post-commit] リモートと分岐しています。amend 直後などツリーの一致を確認のうえ "
            "`git push --force-with-lease` を手動で実行してください。",
            file=sys.stderr,
        )


def _run_best_effort_step(name: str, step: Callable[[], None]) -> None:
    """ベストエフォート処理 1 件を実行する。`step` 自身が処理する失敗(非ゼロ終了等)は
    そのまま警告出力に任せるが、`FileNotFoundError`(git 未導入等)のような**未想定の
    例外**まで `main` へ伝播させると、post-commit というコミット確定後のフックで生の
    traceback が出てしまう(ベストエフォート設計と矛盾する)。ここで捕捉し、他方の
    ステップの実行を妨げないようにする。"""
    try:
        step()
    except Exception as exc:  # noqa: BLE001 - ベストエフォートの最終防波堤として意図的に広く捕捉する
        print(f"[post-commit] {name} で未想定の例外が発生しました(ベストエフォート): {exc!r}", file=sys.stderr)


def main() -> int:
    # Windows既定コンソール (cp932 等) では Japanese メッセージが UnicodeEncodeError で
    # 出力を落としうる。案内を確実に出すため UTF-8 へ固定する。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    _run_best_effort_step("auto-push", auto_push)
    # post-commit はコミット確定後のフックのため、ベストエフォート処理の失敗を
    # 非ゼロ終了で報告しない(git 側の後始末は無く、非ゼロにしても再試行を促す以上の
    # 効果が無いため。失敗は上記の warning 出力で利用者へ伝える)。
    return 0


if __name__ == "__main__":
    sys.exit(main())
