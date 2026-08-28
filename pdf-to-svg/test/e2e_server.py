# =============================================================================
# e2e_server.py — Playwright E2E 用のサーバ起動 (Edge を開かず固定ポートで待受)
# =============================================================================
# `src/app.py` の main() から「Edge 起動・watchdog・終了管理」を除いた最小構成。
# 本番は空きポート (port 0) だが、E2E は playwright.config.ts の baseURL と合わせる
# ため固定ポート 5180 で待ち受ける。辞書はテンポラリに置き、実環境の
# data/dictionary.json を汚さない。終了は Playwright webServer のプロセス kill に任せる。
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402
from dictionary.store import DictionaryStore  # noqa: E402
from web.rpc_methods import WebSession  # noqa: E402
from web.server import create_server  # noqa: E402
from web.undo_stack import UndoStack  # noqa: E402

# Python E2E(pytest)は旧 TS E2E(:5180)と並走できるよう PDFTOSVG_E2E_PORT で別ポートを指定する。
PORT = int(os.environ.get("PDFTOSVG_E2E_PORT", "5180"))

# E2E だけの固定セッショントークン。本番は起動ごとの CSPRNG 値 (`create_server` の既定) で、
# ここは Playwright 側が `page.goto("/?token=...")` に同じ値を書けるようにするための例外。
# `app_flow.e2e.ts` の `TOKEN` と一致させること (片方だけ変えると全 RPC が 403 になる)。
TOKEN = "e2e-fixed-session-token"


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="pdftosvg-e2e-")
    store = DictionaryStore(os.path.join(tmp, "dictionary.json"))
    session = WebSession(store, UndoStack())
    # 属性の手組みはしない。同一オリジン検査の許可リスト設定 (`configure_guard`) を
    # 取りこぼすと全リクエストが 403 になるため、構築経路は `create_server` 1 本に畳む。
    server = create_server(str(config.resource_path("web")), session, port=PORT, token=TOKEN)
    print(f"e2e server listening on http://127.0.0.1:{PORT}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
