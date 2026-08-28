"""アプリのエントリポイント。

QtWebEngine を同梱せず、OS 標準の Edge を「アプリモード」で開いて UI を表示する
(graph-editor と同方式)。本ファイルは小さなローカル HTTP サーバ (web.server) を
起動し、Edge を起動・常駐管理する。ファイル入出力は UI 側 (resources/web) が
従来型の `<input type=file>` / `<a download>` で行う — File System Access API は
VDI の管理された Edge でクラッシュするため無効化してある (app.js `hasFsSave` 参照)。

これにより PySide6 / QtWebEngine ランタイムを同梱せずに済み、配布物が大幅に小さくなる。
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
import webbrowser
from urllib.parse import quote

import config
from dictionary.store import DictionaryStore
from web.rpc_methods import WebSession
from web.server import create_server
from web.undo_stack import UndoStack

# 既定ブラウザ(フォールバック)経路ではプロセスハンドルが無いため、UI からの定期
# ハートビート (/ping) が途絶してからこの秒数で self-shutdown する。本来の終了契機は
# 窓を閉じたときの /quit ビーコン。これはビーコン不達/タブクラッシュ時の保険。
IDLE_TIMEOUT = 60

try:
    import winreg  # Windows のみ (Edge のパス探索に使用)
except ImportError:  # pragma: no cover - 非 Windows 開発時
    winreg = None

EDGE_EXE = "msedge.exe"
EDGE_APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
EDGE_INSTALL_ENV_DIRS = ("ProgramFiles(x86)", "ProgramFiles", "LocalAppData")


def _find_edge():
    """msedge.exe のパスを探す (App Paths レジストリ → 既知のインストール先)。無ければ None。"""
    if winreg is not None:
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, EDGE_APP_PATHS_KEY) as k:
                    path, _ = winreg.QueryValueEx(k, None)
                    if path and os.path.exists(path):
                        return path
            except OSError:
                pass
    for env in EDGE_INSTALL_ENV_DIRS:
        base = os.environ.get(env)
        if base:
            cand = os.path.join(base, "Microsoft", "Edge", "Application", EDGE_EXE)
            if os.path.exists(cand):
                return cand
    return None


def _idle_watchdog(server):
    """ハートビート途絶を見張り、最終アクセスから IDLE_TIMEOUT 秒で self-shutdown する。
    Edge 経路・フォールバック経路の共通の終了バックストップ。窓を閉じた時の /quit ビーコンが
    本来の終了契機で、これはビーコン不達/タブクラッシュ時の保険。
    quit_event が立つまで IDLE_TIMEOUT/4 ごとに確認する。"""
    while not server.quit_event.wait(IDLE_TIMEOUT / 4):
        if time.monotonic() - server.last_seen > IDLE_TIMEOUT:
            server.quit_event.set()
            return


def _setup_logging():
    """起動診断ログを `config.log_dir()` の ``startup.log`` へ出す。

    exe は ``console=False`` (packaging/pdftosvg.spec) で stderr が無く、起動失敗が一切
    見えないため、データ置き場の ``logs/`` にファイル出力して可観測性を確保する
    (置き場の決め方は `config.data_dir`)。ログの用意に失敗しても起動は止めない
    (NullHandler へフォールバック)。"""
    log = logging.getLogger("pdftosvg")
    log.setLevel(logging.INFO)
    log.propagate = False
    if log.handlers:  # 二重起動防止 (テスト等で複数回呼ばれても重複させない)
        return log
    try:
        handler = logging.FileHandler(config.log_dir() / "startup.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
    except OSError:
        log.addHandler(logging.NullHandler())
    return log


# ── Edge の verbose 診断ログ (既定 OFF・opt-in) ──

# Edge 側ログを有効にする環境変数。**既定は無効**で、`--enable-logging` / `--log-file` /
# `--v=1` はコマンドラインに載らない。
#
# なぜ既定で外すか: 本アプリは隔離 `--user-data-dir` を付けず端末標準の既定プロファイルで
# 開く (VDI クラッシュ対策。`main()` のコメント参照)。Edge が未起動だった場合、起動した
# プロセスがそのプロファイルのブラウザ本体になるため、`--v=1` は**利用者が同じ Edge で開く
# 全ての窓・タブ**の診断 (ナビゲーション・ネットワーク周り) をアプリ終了後も書き続ける。
# 出力先が `config.log_dir()` だと、可搬運用や `%LOCALAPPDATA%` 不在の環境では配布フォルダの
# 隣がその置き場になり (`config.data_dir` の判断を見よ)、共有フォルダや USB で配られた
# 配布物にその記録が溜まって回覧のたびに一緒に渡ることになる (CWE-532)。
#
# 併せて閉じる懸念: セッショントークンは `--app=` の URL クエリで渡す
# (`web/origin_guard.py` の `new_session_token`)。verbose ログにはナビゲーション URL が
# 写りうるので、既定 ON のままだと**そのトークンがディスク上のログへ落ちる**可能性が残る
# (実際に写るかは Edge のビルド依存で断定できない)。既定でログ自体を出さないことで、
# この経路を検証に頼らず構造的に閉じる。opt-in 時の出力先をユーザー専用領域に固定するのも
# 同じ理由 (配布物の隣にも他ユーザーからも見える場所へ置かない)。
# ⚠ graph-editor (`app.py` の同名節) との並行実装。環境変数名だけがプロジェクト固有で、
# 構造・既定・後始末は逐語で揃える。片方を変えたら必ず両方を変えること。
EDGE_LOG_ENV = "PDFTOSVG_EDGE_LOG"

# 環境変数を「有効」とみなす値の許可集合 (小文字畳み後の完全一致)。有効側は診断ログを開く
# 方向 = セッショントークンがディスクへ落ちる面を開く方向なので、未知の綴り・空文字は
# 「無効」へ倒す (fail-close)。否定リストで判定すると、想定外の値がそのまま「有効」に
# 転がり込む。
_TRUTHY_ENV_VALUES = frozenset({"1", "true", "yes", "on"})

# opt-in 時の Edge ログの保持上限。Edge 自身はサイズ上限もローテーションも持たないため、
# 起動時の作り直し (前回分を残さない) と終了時の末尾切り詰めで上限を強制する。
EDGE_LOG_MAX_BYTES = 4 << 20

EDGE_LOG_NAME = "edge.log"

# opt-in 時の出力先を作るユーザー専用領域のフォルダ名 (`%LOCALAPPDATA%/PdfToSvg/logs`)。
# `config.data_dir()` の解決 (可搬・明示指定・exe 隣へのフォールバック) には**乗せない** —
# Edge ログだけは「配布物の隣には絶対に置かない」を無条件で保ちたいためである。
_EDGE_LOG_USER_DIR_NAME = "PdfToSvg"


def _env_flag(name: str) -> bool:
    """環境変数を真偽として読む。`_TRUTHY_ENV_VALUES` の完全一致 (小文字畳み後) だけが True。"""
    return os.environ.get(name, "").lower() in _TRUTHY_ENV_VALUES


def _edge_log_path() -> "str | None":
    """opt-in 時の Edge ログの出力先 (ユーザー専用領域)。用意できなければ `None`。

    配布物の隣 (`config.log_dir()` が落ちうる場所) には置かない: 配布物は共有フォルダ・USB で
    回覧される前提で、そこへ他人の閲覧履歴由来の診断を残すと配布のたびに持ち出されてしまう。
    `LOCALAPPDATA` はそのユーザーのプロファイル配下で、既定 ACL で他ユーザーから読めない。
    """
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    try:
        d = os.path.join(base, _EDGE_LOG_USER_DIR_NAME, "logs")
        os.makedirs(d, exist_ok=True)
    except OSError:
        return None
    return os.path.join(d, EDGE_LOG_NAME)


def _prepare_edge_log(log) -> "str | None":
    """opt-in 時に Edge ログの出力先を用意して返す (無効なら `None`)。

    前回起動分は**残さず消す** (= 起動ごとのローテーション)。Edge は追記で開くので、
    消さないと起動のたびに無制限に伸びる。用意に失敗しても起動は止めない (ログは診断目的で、
    無くてもアプリは成立する)。
    """
    if not _env_flag(EDGE_LOG_ENV):
        return None
    path = _edge_log_path()
    if path is None:
        log.warning("edge logging requested but the log directory is unavailable")
        return None
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        log.warning("edge log rotation failed: %s", exc)
        return None
    log.info("edge logging enabled (%s=1) -> %s", EDGE_LOG_ENV, path)
    return path


def _trim_edge_log(path, log) -> None:
    """終了時の後始末: 上限を超えた分を捨て、末尾 `EDGE_LOG_MAX_BYTES` だけを残す。

    セッション中の書き込みは Edge の中で起きるので上限を掛けられない。掛けられるのは
    「起動時に作り直す」と「終了時に切り詰める」の 2 点だけで、この 2 つで
    `EDGE_LOG_MAX_BYTES` + 1 セッション分にディスク占有を抑える。末尾を残すのは、
    クラッシュ調査で読みたいのが直前の行だからである。
    """
    if not path:
        return
    try:
        if os.path.getsize(path) <= EDGE_LOG_MAX_BYTES:
            return
        with open(path, "rb") as f:
            f.seek(-EDGE_LOG_MAX_BYTES, os.SEEK_END)
            tail = f.read()
        with open(path, "wb") as f:
            f.write(tail)
        log.info("edge log truncated to the last %d bytes", EDGE_LOG_MAX_BYTES)
    except OSError as exc:
        log.warning("edge log cleanup failed: %s", exc)


def _edge_launch_args(edge: str, url: str, log_path=None) -> "list[str]":
    """`msedge.exe` の起動引数を組む。**フラグを増やさないこと**が要点。

    隔離 `--user-data-dir` と `--disable-gpu` は VDI でレンダラごとクラッシュした実績があり
    (設計正典の却下集)、`--enable-logging` 系は `log_path` を渡した opt-in 時にだけ付く。
    """
    args = [edge, f"--app={url}", "--no-first-run", "--no-default-browser-check"]
    if log_path:
        args += ["--enable-logging", f"--log-file={log_path}", "--v=1"]
    return args


def _watch_proc(proc, log):
    """起動した msedge.exe の終了を観測してログするだけ (サーバ終了の引き金にはしない)。

    Edge はコールド時、新規 user-data-dir のプロファイル生成過程で自身を別プロセスへ
    再起動し、最初に起動したプロセスだけが早期終了することがある。これに proc.wait() で
    引きずられてサーバを畳むと、生き残った Edge 窓が読みに来た時にはポートが死んでいて
    初回起動が空白になる。終了は /quit ビーコン + ハートビート watchdog に任せ、ここでは
    早期終了を記録するだけにすることで初回から成功させる。"""
    started = time.monotonic()
    code = proc.wait()
    log.info("spawned edge proc exited code=%s after %.1fs (server kept alive)",
             code, time.monotonic() - started)


def main() -> int:
    log = _setup_logging()
    # 実行時に書く一時データ (PDF・JSON 一時) を専用フォルダに集約する (置き場の決め方は
    # `config.run_tmp_dir`)。`tempfile` の既定先をここへ付け替えることで `loader.py` /
    # `rpc_methods.py` の `tempfile.*` が一括で C:/``%TEMP%`` を避ける (各呼び出し側は
    # 無改修)。Edge は端末標準の既定プロファイルを使うため、ここに Edge プロファイルは
    # 置かない。終了時に丸ごと削除する。
    # 用意に失敗しても起動は止めない: exe は console=False で例外が画面に出ず、ここで
    # 投げると (`_setup_logging` が NullHandler へ落ちた環境では記録すら無い) 無言の
    # 起動不能になる。その場合は `tempfile` の既定 (%TEMP%) のまま続行する。
    run_tmp = None
    try:
        run_tmp = config.run_tmp_dir()
        tempfile.tempdir = str(run_tmp)
        log.info("run tmp dir: %s", run_tmp)
    except OSError as exc:
        log.error("run tmp dir unavailable, keeping the default temp: %s", exc)

    store = DictionaryStore(config.dictionary_json_path())
    session = WebSession(store, UndoStack())
    server = create_server(str(config.resource_path("web")), session)
    port = server.server_address[1]
    # UI へはセッショントークン付き URL を渡す。トークンを知る文脈だけが `/rpc` `/upload`
    # `/quit` `/ping` を撃てる (`web/origin_guard.py` の G6)。**ログには素の URL を書く** —
    # `startup.log` はアプリ終了後もデータ置き場に残り、ポートを知りたい攻撃者が最初に
    # 読む場所なので、そこへトークンを置いたら認可を自分で無効化することになる。
    url = f"http://127.0.0.1:{port}/?token={quote(server.guard_token, safe='')}"
    log.info("server listening on http://127.0.0.1:%s/ (frozen=%s)", port, config.is_frozen())

    threading.Thread(target=server.serve_forever, daemon=True).start()

    edge = _find_edge()
    log.info("edge: %s", edge or "(not found, falling back to default browser)")
    proc = None
    edge_log = None
    if edge:
        # 端末標準の「管理された」既定プロファイルでアプリ窓を開く。隔離 `--user-data-dir` や
        # `--disable-gpu` (ソフトウェア描画固定) を付けると、VDI では非標準構成でレンダラが
        # 不安定になり窓ごとクラッシュする (実測。Edge ログに "GetGpuDriverOverlayInfo failed to
        # retrieve video device"。通常の Edge ブラウジングは安定)。余計なフラグを付けず、
        # 安定動作している既定 Edge と同じ構成で `--app=` のみで開く。診断ログは既定で出さず、
        # `PDFTOSVG_EDGE_LOG` を立てたときだけユーザー専用領域へ出す (`_prepare_edge_log`)。
        edge_log = _prepare_edge_log(log)
        try:
            proc = subprocess.Popen(_edge_launch_args(edge, url, edge_log))
            log.info("edge launched pid=%s", proc.pid)
        except OSError as exc:
            log.warning("edge launch failed: %s", exc)
            proc = None

    # サーバの寿命は起動した msedge.exe プロセスの終了に縛らない。終了契機は窓を閉じた時の
    # /quit ビーコンと、ハートビート途絶を見張る watchdog に一本化する (Edge・既定ブラウザ
    # 共通)。これにより Edge のコールド再起動で起動プロセスが早期終了してもサーバが落ちず、
    # 初回起動から成功する。proc は終了時に Edge を片付けるためのハンドルとしてのみ保持する。
    try:
        if proc is None:
            webbrowser.open(url)
        else:
            # 早期終了を観測ログに残すだけ (終了の引き金にはしない)。
            threading.Thread(target=_watch_proc, args=(proc, log), daemon=True).start()
        threading.Thread(target=_idle_watchdog, args=(server,), daemon=True).start()
        server.quit_event.wait()
        # /quit ビーコン (窓閉鎖) か watchdog (ハートビート途絶) かを last_seen から推定。
        idle = time.monotonic() - server.last_seen
        log.info("shutting down (reason=%s, idle=%.1fs)",
                 "idle-timeout" if idle > IDLE_TIMEOUT else "quit-beacon", idle)
    finally:
        server.shutdown()
        server.server_close()
        if proc is not None and proc.poll() is None:
            proc.terminate()
        # PDF/JSON 一時をまとめて削除 (run_tmp ごと)。まだ掴まれている可能性に備え ignore_errors。
        if run_tmp is not None:
            shutil.rmtree(run_tmp, ignore_errors=True)
        # opt-in 時のみ存在する Edge ログの後始末 (上限超過分の切り詰め)。
        _trim_edge_log(edge_log, log)
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
