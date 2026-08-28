"""開発実行 & PyInstaller のエントリスクリプト。

`src/` を `sys.path` 先頭へ挿入してから `app.main` を起動する。

    python run.py            # アプリ起動 (要 PYTHONPATH=src か editable install)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
