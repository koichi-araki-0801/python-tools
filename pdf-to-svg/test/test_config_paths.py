"""可変状態の置き場 (`config.data_dir`) の決め方を固定する。

配布 exe の可変状態を**プログラムフォルダの外**へ出すのが主張である。プログラム
フォルダは CPython ランタイム DLL と PyMuPDF のネイティブモジュールを抱えており、
そこが書き込み可能である必要をなくすことが目的 (書き込み可能なら DLL 差し替えで
「次に起動した人の権限で任意コード実行」が成立する)。

`_resolve_data_dir` を直接呼ぶ (`data_dir` は解決結果を記憶するため、記憶の有無に
テストが依存しないようにする)。
"""
from __future__ import annotations

import os
from pathlib import Path

import config


def _freeze(monkeypatch, exe_dir: Path) -> None:
    """frozen 配布 (PyInstaller onedir) を模す。"""
    monkeypatch.setattr(config, "is_frozen", lambda: True)
    monkeypatch.setattr(config, "app_base_dir", lambda: exe_dir)


def test_frozen_build_keeps_mutable_state_out_of_the_program_directory(monkeypatch, tmp_path):
    """既定はユーザー専用領域。exe の隣には何も作らない。"""
    exe_dir = tmp_path / "PdfToSvg"
    exe_dir.mkdir()
    local = tmp_path / "LocalAppData"
    _freeze(monkeypatch, exe_dir)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)

    resolved = config._resolve_data_dir()

    assert resolved == local / "PdfToSvg" / "data"
    assert not (exe_dir / "data").exists()


def test_explicit_environment_override_wins(monkeypatch, tmp_path):
    """`PDFTOSVG_DATA_DIR` の明示指定が最優先 (可搬運用の逃げ道を残す)。"""
    exe_dir = tmp_path / "PdfToSvg"
    exe_dir.mkdir()
    chosen = tmp_path / "usb" / "state"
    _freeze(monkeypatch, exe_dir)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.setenv(config.ENV_DATA_DIR, str(chosen))

    assert config._resolve_data_dir() == chosen
    assert chosen.is_dir()


def test_existing_portable_installation_is_left_alone(monkeypatch, tmp_path):
    """既に exe 隣へ辞書がある配布はそのまま使う (置き場を変えて辞書を失わせない)。"""
    exe_dir = tmp_path / "PdfToSvg"
    (exe_dir / "data").mkdir(parents=True)
    (exe_dir / "data" / "dictionary.json").write_text("[]", encoding="utf-8")
    _freeze(monkeypatch, exe_dir)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)

    assert config._resolve_data_dir() == exe_dir / "data"


def test_falls_back_to_the_program_directory_when_the_user_area_is_unusable(
    monkeypatch, tmp_path
):
    """ユーザー領域が使えない端末 (VDI) では exe 隣へ落とす = 起動は必ずする。

    この経路に落ちた配布はプログラムフォルダの ACL 要件が効く
    (配布・運用手順書 1.1 節)。
    """
    exe_dir = tmp_path / "PdfToSvg"
    exe_dir.mkdir()
    _freeze(monkeypatch, exe_dir)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)

    assert config._resolve_data_dir() == exe_dir / "data"


def test_unwritable_user_area_falls_back_too(monkeypatch, tmp_path):
    """書き込み可否は**実書き込み**で確かめる (存在確認や `os.access` では判定にならない)。"""
    exe_dir = tmp_path / "PdfToSvg"
    exe_dir.mkdir()
    _freeze(monkeypatch, exe_dir)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)
    monkeypatch.setattr(config, "_is_writable_dir", lambda path: False)

    assert config._resolve_data_dir() == exe_dir / "data"


def test_source_checkout_still_uses_the_repository_data_folder(monkeypatch, tmp_path):
    """ソース実行 (開発時) は従来どおりリポジトリ直下の ``data/``。"""
    monkeypatch.setattr(config, "is_frozen", lambda: False)
    monkeypatch.setattr(config, "app_base_dir", lambda: tmp_path)
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)

    assert config._resolve_data_dir() == tmp_path / "data"


def test_share_glitch_does_not_silently_move_the_data_dir(monkeypatch, tmp_path):
    """可搬判定が OSError (共有瞬断) のときは可搬側に留まる (黙って置き場を変えない)。

    `Path.exists()` は瞬断系 OSError を握りつぶして False を返すため、それを信じると
    ネットワークドライブ上の可搬インストールが一瞬読めないだけで置き場がユーザー
    専用領域へ切り替わり、「辞書が消えた」ように見えて別の場所に第 2 の辞書が育つ。
    判定不能は「在る」側へ倒し、失敗は後段で見える形にする。
    """
    exe_dir = tmp_path / "PdfToSvg"
    exe_dir.mkdir()
    _freeze(monkeypatch, exe_dir)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)

    real_stat = Path.stat

    def flaky_stat(self, *args, **kwargs):
        if self.name == "dictionary.json":
            raise OSError(21, "device not ready")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", flaky_stat)

    assert config._resolve_data_dir() == exe_dir / "data"


# ── 実行時一時フォルダ (`run_tmp_dir`) の置き場 ──────────────────────────────

def test_run_tmp_prefers_the_local_user_area(monkeypatch, tmp_path):
    """一時データはローカルのユーザー専用領域が最優先 (data_dir が共有でも SMB を往復させない)。

    フォルダ名は ``<pid>-<uuid>``: 置き場が共有フォルダになったときも別マシンの同一
    PID と衝突せず、終了時削除が他人の稼働中一時データを消さない。
    """
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(config, "_resolved_run_tmp_dir", None)

    d = config.run_tmp_dir()

    assert d.parent == local / "PdfToSvg" / "tmp"
    assert d.name.startswith(f"{os.getpid()}-")
    assert len(d.name) > len(f"{os.getpid()}-")  # uuid 部が付いている
    assert d.is_dir()
    assert config.run_tmp_dir() == d  # プロセス内で固定 (呼ぶたびに別フォルダを作らない)


def test_run_tmp_falls_back_to_the_data_dir_when_the_user_area_is_unusable(
    monkeypatch, tmp_path
):
    """ユーザー領域が使えない端末 (VDI) は従来どおり data_dir 配下へ落とす = 必ず動く。"""
    monkeypatch.setattr(config, "_resolved_run_tmp_dir", None)
    monkeypatch.setattr(config, "_is_writable_dir", lambda path: False)
    monkeypatch.setattr(config, "data_dir", lambda: tmp_path / "data")

    d = config.run_tmp_dir()

    assert d.parent == tmp_path / "data" / "tmp"
    assert d.name.startswith(f"{os.getpid()}-")
    assert d.is_dir()
