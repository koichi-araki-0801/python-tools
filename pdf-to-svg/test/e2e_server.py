# =============================================================================
# e2e_server.py — Playwright E2E 用のサーバ起動 (Edge を開かず固定ポートで待受)
# =============================================================================
# `src/app.py` の main() から「Edge 起動・watchdog・終了管理」を除いた最小構成。
# 本番は空きポート (port 0) だが、E2E は playwright.config.ts の baseURL と合わせる
# ため固定ポート 5180 で待ち受ける。辞書はテンポラリに置き、実環境の
# data/dictionary.json を汚さない。終了は Playwright webServer のプロセス kill に任せる。
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

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


def _stderr_text(proc: subprocess.Popen) -> str:
    return proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""


def _responds(base_url: str) -> bool:
    """``base_url`` に HTTP で応答するものがいるか (4xx/5xx でも「誰かが待ち受けている」とみなす)。"""
    try:
        urllib.request.urlopen(base_url + "/", timeout=1)
    except urllib.error.HTTPError:
        return True
    except OSError:
        return False
    return True


def ensure_port_is_free(base_url: str) -> None:
    """E2E 用サーバを起動する**前**に、同じ URL で別のサーバが応答していないことを確かめる。

    起動したあとで「応答があるか」だけを見ると、既に別の E2E が同じポートで動いていても起動成功に
    見える。しかも Windows では ``ThreadingHTTPServer`` の既定 ``allow_reuse_address``
    (``SO_REUSEADDR``) により LISTEN 中のポートへの二重 bind が成功するので、後発の子は死なず、
    2 つのサーバが同じポートで LISTEN して接続がどちらに届くか不定になる (2 つのテスト実行が
    互いの文書を消し合う)。bind の失敗では検知できないため、起動前に応答の有無で見る。
    先発の子が待ち受けを始める前の 1〜2 秒の窓で並走を始めた 2 本は検知できないが、
    並走の検知には十分。
    """
    if _responds(base_url):
        raise RuntimeError(
            f"{base_url} で別のサーバが既に応答している。E2E を並走させていないか確かめてください"
        )


def wait_until_serving(
    proc: subprocess.Popen, base_url: str, *, attempts: int = 100, interval: float = 0.2
) -> None:
    """起動した子プロセス ``proc`` が ``base_url`` で応答し始めるまで待つ。

    応答が無いまま子が終了していれば、stderr を添えて ``RuntimeError`` にする。
    起動前の「他のサーバがいないこと」の確認は ``ensure_port_is_free`` が担う。
    """
    for _ in range(attempts):
        if _responds(base_url):
            return
        if proc.poll() is not None:
            raise RuntimeError("e2e server が起動前に終了した: " + _stderr_text(proc))
        time.sleep(interval)
    raise RuntimeError("e2e server が起動しない")


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
