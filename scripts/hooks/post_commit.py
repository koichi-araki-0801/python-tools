#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""post-commit フック本体。auto-push + `offline/publish_bundle.py --tag-only` の
ベストエフォート呼び出し。

`scripts/hooks/post-commit`(sh シム)から `py -3.13` で起動される。git はコミットが
確定した**後**にこのフックを呼ぶため、ここで失敗してもコミット自体は取り消せない。
両方の処理を警告のみ(exit 0)にとどめ、コミットの成否とは切り離す。

行うこと:
  1. auto-push: 現在ブランチを upstream(無ければ `origin HEAD` で新規 upstream 設定)へ
     push する。force はしない — non-fast-forward で拒否された場合はメッセージを出すだけで、
     force push はここから自動実行しない(amend 直後の分岐を誤検知して他人の push を
     潰す事故を避けるため。復旧は利用者が手動で `git push --force-with-lease` を行う)。
  2. `offline/publish_bundle.py --tag-only` をベストエフォートで実行する。content-key が
     Release 側 `bundle.key` と一致する場合のみローリングタグ(`offline-bundle-v1`)を
     HEAD へ移動する(不一致・Release 未取得時は何もせず終了する契約。詳細は同スクリプトの
     docstring)。`gh` 未認証環境では自然に失敗するため、その場合も警告に留める。

`git` / `publish_bundle.py` を実際に呼ぶ処理は `runner` を受け取り、既定は実
`subprocess.run` だが呼び出し側から差し替えられる(単体テストは偽 runner を注入し、
実 git push や実 publish_bundle.py は起動しない)。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent.parent
PUBLISH_BUNDLE = ROOT / "offline" / "publish_bundle.py"

Runner = Callable[..., subprocess.CompletedProcess]


def default_runner(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, **kwargs)


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


# ── 2. publish_bundle.py --tag-only ──
def publish_tag_only(*, runner: Runner = default_runner, publish_bundle_path: Path = PUBLISH_BUNDLE) -> None:
    if not publish_bundle_path.is_file():
        # 配布物の同梱状況によっては offline/ 一式が無いチェックアウトもありうる
        # (本リポでは常時同梱だが、契約としてここで踏み倒さない)。
        return
    result = runner([sys.executable, str(publish_bundle_path), "--tag-only"])
    output = "\n".join(s for s in (result.stdout, result.stderr) if s and s.strip())
    if output:
        print(output.strip())
    if result.returncode != 0:
        print(
            "[post-commit] publish_bundle.py --tag-only が失敗しました"
            "(ベストエフォート。コミット自体は成立しています)。",
            file=sys.stderr,
        )


def main() -> int:
    # Windows既定コンソール (cp932 等) では Japanese メッセージが UnicodeEncodeError で
    # 出力を落としうる。案内を確実に出すため UTF-8 へ固定する。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    auto_push()
    publish_tag_only()
    # post-commit はコミット確定後のフックのため、ベストエフォート処理の失敗を
    # 非ゼロ終了で報告しない(git 側の後始末は無く、非ゼロにしても再試行を促す以上の
    # 効果が無いため。失敗は上記の warning 出力で利用者へ伝える)。
    return 0


if __name__ == "__main__":
    sys.exit(main())
