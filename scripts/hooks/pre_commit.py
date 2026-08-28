#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pre-commit フック本体。ステージ済みファイルへコメント規約検査を掛ける。

`scripts/hooks/pre-commit`(sh シム。`git config core.hooksPath scripts/hooks` で
有効化する)から `py -3.13` で起動される。検査ロジックは `scripts/check_comments.py`
(`--staged`)を呼ぶだけで、フック自身は薄いディスパッチャに留める。今後フックへ検査を
足す場合もこのファイルへ積み増す。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CHECK_COMMENTS = ROOT / "scripts" / "check_comments.py"


def main() -> int:
    # Windows既定コンソール (cp932 等) では Japanese メッセージが UnicodeEncodeError で
    # 出力を落としうる。フック失敗時の案内を確実に出すため UTF-8 へ固定する。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    result = subprocess.run([sys.executable, str(CHECK_COMMENTS), "--staged"], cwd=ROOT)
    if result.returncode != 0:
        print(
            "[pre-commit] コメント規約検査で失敗しました。上記を修正して再度 commit してください。",
            file=sys.stderr,
        )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
