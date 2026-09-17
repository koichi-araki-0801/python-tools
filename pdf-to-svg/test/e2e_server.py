# =============================================================================
# e2e_server.py — Playwright E2E 用のサーバ起動 (Edge を開かず固定ポートで待受)
# =============================================================================
# `src/app.py` の main() から「Edge 起動・watchdog・終了管理」を除いた最小構成。
# ポートは環境変数 PDFTOSVG_E2E_PORT で指定する (既定 5180。E2E fixture は 0 を渡して OS に選ばせ、
# bind した実ポートを PDFTOSVG_E2E_PORT_FILE のファイルから読む。固定ポートだと 2 本並走したときに
# 混線するため)。辞書はテンポラリに置き、実環境の data/dictionary.json を汚さない。終了は
# fixture のプロセス kill に任せる。
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

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


def wait_for_port_file(
    path: Path, proc: subprocess.Popen, *, timeout: float = 20.0, interval: float = 0.1
) -> int:
    """子プロセス ``proc`` が bind した実ポートを ``path`` へ書くのを待ち、その値を返す。

    子の標準出力を ``readline`` で待つ形にしないのは、子が待ち受けを始めずに固まったとき永久に
    ブロックし、Windows の pipe には ``select`` でタイムアウトを付けられないため。ファイルの出現を
    ポーリングする方が単純で、時間切れも子の死亡も検知できる。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text.isdigit():
                return int(text)
        if proc.poll() is not None:
            raise RuntimeError("e2e server が起動前に終了した: " + _stderr_text(proc))
        time.sleep(interval)
    raise RuntimeError(f"e2e server が {timeout} 秒以内に実ポートを {path} へ書かなかった")


def wait_until_serving(
    proc: subprocess.Popen, base_url: str, *, attempts: int = 100, interval: float = 0.2
) -> None:
    """起動した子プロセス ``proc`` が ``base_url`` で応答し始めるまで待つ。

    応答が無いまま子が終了していれば、stderr を添えて ``RuntimeError`` にする。
    """
    for _ in range(attempts):
        try:
            urllib.request.urlopen(base_url + "/", timeout=1)
            return
        except urllib.error.HTTPError:
            return  # 4xx/5xx でも「誰かが待ち受けている」とみなす
        except OSError:
            pass
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
    actual_port = server.server_address[1]  # PORT=0 のとき OS が選んだ実ポート
    print(f"e2e server listening on http://127.0.0.1:{actual_port}/", flush=True)
    port_file = os.environ.get("PDFTOSVG_E2E_PORT_FILE")
    if port_file:
        # fixture が実ポートを知る経路。書き込み途中を読まれないよう、別名で書いてから置き換える
        tmp_path = port_file + ".tmp"
        Path(tmp_path).write_text(str(actual_port), encoding="utf-8")
        os.replace(tmp_path, port_file)
    server.serve_forever()


if __name__ == "__main__":
    main()
