"""可変状態の置き場 (`app._data_dir`) の決め方を固定する (pdf-to-svg と同一仕様)。

配布 exe の可変状態 (診断ログ) を**プログラムフォルダの外**へ出すのが主張である。
exe を共有フォルダ・ネットワークドライブへ置いて複数人が起動しても、`startup.log` の
共同追記 (記録の混線) と「プログラムフォルダが書き込み可能であること」の要件化
(DLL 差し替え = CWE-427 の温床) を起こさない。決定順の詳細は `_data_dir` の doc を参照。

`import app` に副作用は無い (同梱資産の読み込みは `main()`/初回 GET の遅延読込。
`main()` は呼ばない)。
"""
from __future__ import annotations

import os
from pathlib import Path

import app


def _freeze(monkeypatch, exe_dir: Path) -> None:
    """frozen 配布 (PyInstaller) を模す。"""
    monkeypatch.setattr(app, "_is_frozen", lambda: True)
    monkeypatch.setattr(app, "_app_base_dir", lambda: str(exe_dir))


def test_frozen_build_keeps_mutable_state_out_of_the_program_directory(monkeypatch, tmp_path):
    """既定はユーザー専用領域。exe の隣には何も作らない。"""
    exe_dir = tmp_path / "LabelEditor"
    exe_dir.mkdir()
    local = tmp_path / "LocalAppData"
    _freeze(monkeypatch, exe_dir)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv(app.DATA_DIR_ENV, raising=False)

    assert Path(app._data_dir()) == local / "LabelEditor" / "data"
    assert not (exe_dir / "data").exists()


def test_explicit_environment_override_wins(monkeypatch, tmp_path):
    """`LABELEDITOR_DATA_DIR` の明示指定が最優先 (可搬運用の逃げ道を残す)。"""
    exe_dir = tmp_path / "LabelEditor"
    exe_dir.mkdir()
    chosen = tmp_path / "usb" / "state"
    _freeze(monkeypatch, exe_dir)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setenv(app.DATA_DIR_ENV, str(chosen))

    assert Path(app._data_dir()) == chosen
    assert chosen.is_dir()


def test_falls_back_to_the_program_directory_when_the_user_area_is_unusable(
    monkeypatch, tmp_path
):
    """ユーザー領域が使えない端末 (VDI) では exe 隣へ落とす = 起動は必ずする。

    この経路に落ちた配布はプログラムフォルダの ACL 要件が効く (配布・運用手順書)。
    """
    exe_dir = tmp_path / "LabelEditor"
    exe_dir.mkdir()
    _freeze(monkeypatch, exe_dir)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv(app.DATA_DIR_ENV, raising=False)

    assert Path(app._data_dir()) == exe_dir / "data"


def test_unwritable_user_area_falls_back_too(monkeypatch, tmp_path):
    """書き込み可否は**実書き込み**で確かめる (存在確認や `os.access` では判定にならない)。"""
    exe_dir = tmp_path / "LabelEditor"
    exe_dir.mkdir()
    _freeze(monkeypatch, exe_dir)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.delenv(app.DATA_DIR_ENV, raising=False)
    monkeypatch.setattr(app, "_is_writable_dir", lambda path: False)

    assert Path(app._data_dir()) == exe_dir / "data"


def test_source_checkout_still_uses_the_repository_data_folder(monkeypatch, tmp_path):
    """ソース実行 (開発時) は従来どおりリポジトリ直下の ``data/``。"""
    monkeypatch.setattr(app, "_is_frozen", lambda: False)
    monkeypatch.setattr(app, "_app_base_dir", lambda: str(tmp_path))
    monkeypatch.delenv(app.DATA_DIR_ENV, raising=False)

    assert Path(app._data_dir()) == tmp_path / "data"


def test_log_dir_is_under_the_resolved_data_dir(monkeypatch, tmp_path):
    """`_log_dir` は解決済みデータ置き場の ``logs/`` (exe 隣に直書きへ退行しない)。"""
    exe_dir = tmp_path / "LabelEditor"
    exe_dir.mkdir()
    local = tmp_path / "LocalAppData"
    _freeze(monkeypatch, exe_dir)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv(app.DATA_DIR_ENV, raising=False)

    d = Path(app._log_dir())
    assert d == local / "LabelEditor" / "data" / "logs"
    assert d.is_dir()
    assert not (exe_dir / "data").exists()


def test_import_has_no_side_effects_and_resources_load_lazily(monkeypatch):
    """同梱資産は import 時に読まない (読み込み失敗をログ確保後に見える化するため)。

    `_load_resources` は冪等で、読めない環境では OSError を**握りつぶさず**投げる
    (`main()` が startup.log へ残して終了し、`do_GET` は 500 で伝える)。
    """
    # 遅延読込は冪等 (2 回呼んでも同じキャッシュ)。
    app._load_resources()
    ui_first = app.UI_HTML
    app._load_resources()
    assert app.UI_HTML is ui_first and ui_first  # 再読込せず、中身は空でない

    # 読めない環境では例外が呼び出し側 (main / do_GET) へ届く (黙って空配信しない)。
    monkeypatch.setattr(app, "UI_HTML", None)
    monkeypatch.setattr(app, "resource_path", lambda rel: os.path.join("no-such-dir", rel))
    try:
        app._load_resources()
    except OSError:
        pass
    else:  # pragma: no cover - 失敗経路の明示
        raise AssertionError("OSError expected")
