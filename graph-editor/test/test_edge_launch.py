"""Edge の起動引数と診断ログの扱い (`app.py` の「Edge の verbose 診断ログ」節) を固定する。

主張は 3 つ:

1. **既定では verbose ログを出さない**。既定プロファイルで開く設計 (VDI クラッシュ対策) の
   ため、`--enable-logging --v=1` は「このアプリの窓」ではなく利用者の Edge セッション全体の
   診断を、アプリ終了後も書き続ける。配布物 (exe) の隣にそれが溜まると、回覧のたびに他人の
   閲覧履歴由来の記録ごと配ることになる (CWE-532)。同時に、`--app=` の URL に載せた
   セッショントークンがログへ写る懸念も、ログを出さないことで検証に頼らず閉じる。
2. **opt-in 時の出力先は配布物の隣ではなくユーザー専用領域**で、起動ごとに作り直す
   (= ローテーション) うえ、終了時に上限で切り詰める。
3. **フラグを増やさない**。隔離 `--user-data-dir` と `--disable-gpu` は VDI でレンダラごと
   クラッシュした実績があり (設計正典の却下集)、どの経路でも付かないこと。

`import app` に副作用は無い (同梱資産の読み込みは `main()`/初回 GET の遅延読込。
`main()` は呼ばない)。
"""
from __future__ import annotations

import logging
import os

import app
import pytest

URL = "http://127.0.0.1:5179/?token=SECRET-TOKEN"


@pytest.fixture
def log():
    """テスト用の捨てロガー (`_setup_logging` はファイルを作るので使わない)。"""
    logger = logging.getLogger("labeleditor-test")
    logger.addHandler(logging.NullHandler())
    return logger


@pytest.fixture
def user_area(tmp_path, monkeypatch):
    """`LOCALAPPDATA` を一時ディレクトリへ差し替える (実ユーザープロファイルを汚さない)。"""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


# ── 既定: 診断ログのフラグが 1 つも載らない ──


def test_default_launch_args_have_no_logging_flags():
    args = app._edge_launch_args("msedge.exe", URL)
    assert args == ["msedge.exe", f"--app={URL}", "--no-first-run", "--no-default-browser-check"]
    joined = " ".join(args)
    for flag in ("--enable-logging", "--log-file", "--v="):
        assert flag not in joined


@pytest.mark.parametrize("value", [None, "", "0", "false", "FALSE", "no", "off", "  off  "])
def test_edge_log_is_off_unless_explicitly_enabled(monkeypatch, log, user_area, value):
    if value is None:
        monkeypatch.delenv(app.EDGE_LOG_ENV, raising=False)
    else:
        monkeypatch.setenv(app.EDGE_LOG_ENV, value)
    assert app._prepare_edge_log(log) is None
    # 出力先を用意すらしないこと (空フォルダが配られるのも避ける)。
    assert not (user_area / "LabelEditor").exists()


def test_launch_args_never_include_flags_that_crashed_vdi(monkeypatch, log, user_area):
    monkeypatch.setenv(app.EDGE_LOG_ENV, "1")
    joined = " ".join(app._edge_launch_args("msedge.exe", URL, app._prepare_edge_log(log)))
    assert "--user-data-dir" not in joined
    assert "--disable-gpu" not in joined


# ── opt-in: 出力先はユーザー専用領域 / 起動ごとに作り直す ──


def test_opt_in_log_lives_in_the_user_profile_not_next_to_the_exe(monkeypatch, log, user_area):
    monkeypatch.setenv(app.EDGE_LOG_ENV, "1")
    path = app._prepare_edge_log(log)
    assert path is not None
    assert os.path.commonpath([str(user_area), path]) == str(user_area)
    # 配布物の隣 (`data/logs/`) には置かない。
    assert os.path.commonpath([app._log_dir(), path]) != app._log_dir()


def test_opt_in_adds_exactly_the_three_logging_flags(monkeypatch, log, user_area):
    monkeypatch.setenv(app.EDGE_LOG_ENV, "1")
    path = app._prepare_edge_log(log)
    args = app._edge_launch_args("msedge.exe", URL, path)
    assert args[-3:] == ["--enable-logging", f"--log-file={path}", "--v=1"]


def test_previous_run_log_is_discarded_at_startup(monkeypatch, log, user_area):
    monkeypatch.setenv(app.EDGE_LOG_ENV, "1")
    path = app._prepare_edge_log(log)
    with open(path, "wb") as f:
        f.write(b"previous run\n" * 1000)
    # 2 回目の起動でも同じパスを使い、前回分は残さない (Edge は追記で開くため)。
    again = app._prepare_edge_log(log)
    assert again == path
    assert not os.path.exists(path)


# ── 終了時の後始末: 上限で切り詰める ──


def test_cleanup_truncates_an_oversized_log_to_the_tail(monkeypatch, log, user_area):
    monkeypatch.setenv(app.EDGE_LOG_ENV, "1")
    path = app._prepare_edge_log(log)
    body = b"x" * (app.EDGE_LOG_MAX_BYTES + 4096) + b"TAIL-MARKER"
    with open(path, "wb") as f:
        f.write(body)

    app._trim_edge_log(path, log)

    assert os.path.getsize(path) == app.EDGE_LOG_MAX_BYTES
    with open(path, "rb") as f:
        kept = f.read()
    assert kept.endswith(b"TAIL-MARKER")  # 直前の行が調査対象なので末尾を残す
    assert kept == body[-app.EDGE_LOG_MAX_BYTES:]


def test_cleanup_leaves_a_small_log_untouched(monkeypatch, log, user_area):
    monkeypatch.setenv(app.EDGE_LOG_ENV, "1")
    path = app._prepare_edge_log(log)
    with open(path, "wb") as f:
        f.write(b"small\n")

    app._trim_edge_log(path, log)

    with open(path, "rb") as f:
        assert f.read() == b"small\n"


def test_cleanup_is_a_no_op_when_logging_was_disabled(log):
    # 既定経路 (`_prepare_edge_log` が `None`) では終了処理も何もしない。
    app._trim_edge_log(None, log)


def test_cleanup_survives_a_missing_file(log, user_area):
    app._trim_edge_log(str(user_area / "gone.log"), log)


# ── 環境変数の読み方 ──


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("true", True), ("yes", True), ("on", True),
     ("0", False), ("false", False), ("no", False), ("off", False), ("diag", False),
     ("", False), ("   ", False)],
)
def test_env_flag_truthiness(monkeypatch, value, expected):
    monkeypatch.setenv("LABELEDITOR_TEST_FLAG", value)
    assert app._env_flag("LABELEDITOR_TEST_FLAG") is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # 許可集合外・空文字は無効 (fail-close)。末尾空白は畳まない (小文字化のみ)。
        ("disabled", False), ("2", False), ("TRUE ", False), ("", False),
        # 許可集合は小文字畳み後の完全一致。
        ("1", True), ("true", True), ("ON", True),
    ],
)
def test_env_flag_unknown_value_is_off(monkeypatch, value, expected):
    monkeypatch.setenv("LABELEDITOR_TEST_FLAG", value)
    assert app._env_flag("LABELEDITOR_TEST_FLAG") is expected
