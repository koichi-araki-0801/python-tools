# -*- coding: utf-8 -*-
"""`scripts/` 配下の部品の単体テスト。実行: `py -3.13 -m pytest scripts -q`。

`check_requirements.py` のテストベクタは monorepo `offline/lib/verify.Tests.ps1`
(`Test-OfflineRequirementLine`) の受理/拒否ケースを逐語移植する。`build_venv.py` は
実際の venv 作成・pip install を伴わない純粋な部品 (wheelhouse fail-closed 判定・
Python ランチャ解決) だけを単体対象とする。実際にビルドが通ることは
`graph-editor/scripts/build.bat` / `pdf-to-svg/scripts/build.bat` の実行で確認する。

`offline/lib/bundle_common.py` は content-key 2 経路一致・bundle.key 読み書き・pip 入口列挙
ガードを対象とする。requirements 列挙のテストは実 git (`ls-files`/`init`/`add`/`commit`) を
ローカルで実行する (ネットワークには一切アクセスしない)。

`offline/setup_offline.py` は手元のバンドル探索 → Release からの HTTPS 取得 → `.sha256` 照合 →
content-key 照合 → 展開の各部品を対象とする。HTTP 取得は注入可能で実ネットワークへはアクセス
しない。
"""

import hashlib
import io
import pathlib
import subprocess
import sys
import tarfile
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "lib"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "hooks"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "offline"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "offline" / "lib"))

import pytest  # noqa: E402

import check_requirements  # noqa: E402
import check_comments  # noqa: E402
import build_venv  # noqa: E402
import bundle_common  # noqa: E402
import setup_offline  # noqa: E402
import setup_dev  # noqa: E402
import pre_push  # noqa: E402
import post_commit  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


# ── is_offline_requirement_line: 受け入れる形 ──
def test_bare_name_is_accepted():
    assert check_requirements.is_offline_requirement_line("markdown-it-py") is True


def test_name_with_version_spec_is_accepted():
    assert check_requirements.is_offline_requirement_line("PyYAML==6.0.1") is True


def test_blank_and_comment_lines_are_accepted():
    assert check_requirements.is_offline_requirement_line("") is True
    assert check_requirements.is_offline_requirement_line("  # comment") is True


def test_dotted_package_names_are_accepted():
    # PEP 508 の名前はドットを許す。index/wheelhouse 解決のみで解決先を動かせない。
    assert check_requirements.is_offline_requirement_line("zope.interface") is True
    assert check_requirements.is_offline_requirement_line("ruamel.yaml==0.18.6") is True


# ── is_offline_requirement_line: 拒否する形 ──
def test_basic_archive_extensions_are_rejected():
    for ext in ("whl", "zip", "tar", "tgz", "tbz2", "txz", "egg", "gz", "bz2", "xz"):
        assert check_requirements.is_offline_requirement_line(f"payload.{ext}") is False


def test_tar_variant_extensions_are_rejected():
    assert check_requirements.is_offline_requirement_line("payload.tbz") is False
    assert check_requirements.is_offline_requirement_line("payload.tlz") is False
    assert check_requirements.is_offline_requirement_line("payload.tar.lz") is False
    assert check_requirements.is_offline_requirement_line("payload.tar.lzma") is False


def test_local_path_references_are_rejected():
    # 拡張子網羅と二重の防御。
    assert (
        check_requirements.is_offline_requirement_line(
            "./downloads/numpy-1.9.2-cp34-none-win32.whl"
        )
        is False
    )
    assert check_requirements.is_offline_requirement_line("sub\\dir\\pkg") is False


def test_url_and_option_lines_are_rejected():
    assert (
        check_requirements.is_offline_requirement_line("pkg @ https://evil/pkg.tar.gz") is False
    )
    assert check_requirements.is_offline_requirement_line("--find-links https://evil/") is False
    assert check_requirements.is_offline_requirement_line("-e .") is False


# ── check_requirements_file: ファイル単位 ──
def test_check_requirements_file_reports_violation_with_line_number(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("markdown-it-py\n-e .\nPyYAML==6.0.1\n", encoding="utf-8")
    violations = check_requirements.check_requirements_file(path)
    assert len(violations) == 1
    assert str(path) in violations[0]
    assert ":2:" in violations[0]


def test_check_requirements_file_passes_clean_file(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("# comment\nmarkdown-it-py\nPyYAML==6.0.1\n\n", encoding="utf-8")
    assert check_requirements.check_requirements_file(path) == []


def test_assert_requirements_file_raises_on_violation(tmp_path):
    # `RuntimeError` を送出すること (`SystemExit` にしない)。`SystemExit` は `BaseException`
    # 直系で `Exception` を継承しないため、呼び出し側の通常の `except Exception` (build.py)
    # を素通りしてしまう。
    path = tmp_path / "requirements.txt"
    path.write_text("--find-links https://evil/\n", encoding="utf-8")
    try:
        check_requirements.assert_requirements_file(path)
    except RuntimeError:
        pass
    else:
        raise AssertionError("違反ファイルで RuntimeError が送出されなかった")


def test_assert_requirements_file_passes_clean_file(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("markdown-it-py\n", encoding="utf-8")
    check_requirements.assert_requirements_file(path)  # 例外を送出しないことを確認


def test_assert_requirements_file_exception_is_caught_by_except_exception(tmp_path):
    """`graph-editor` / `pdf-to-svg` の `scripts/build.py` が持つ通常の `except Exception`
    で確実に捕まることを回帰的に確認する。`SystemExit` を送出していた版では
    `BaseException` 直系のため `except Exception` を素通りし、`[エラー] ...` 表示と
    ダブルクリック起動時の一時停止 (`_pause()`) が飛んでいた。"""
    path = tmp_path / "requirements.txt"
    path.write_text("-e .\n", encoding="utf-8")
    caught = False
    try:
        check_requirements.assert_requirements_file(path)
    except Exception:
        caught = True
    assert caught is True


# ── CLI: -Path / 位置引数 ──
def test_main_accepts_path_flag(tmp_path, capsys):
    path = tmp_path / "requirements.txt"
    path.write_text("markdown-it-py\n", encoding="utf-8")
    code = check_requirements.main(["-Path", str(path)])
    assert code == 0
    assert "[ok]" in capsys.readouterr().out


def test_main_accepts_positional_path(tmp_path, capsys):
    path = tmp_path / "requirements.txt"
    path.write_text("markdown-it-py\n", encoding="utf-8")
    code = check_requirements.main([str(path)])
    assert code == 0


def test_main_returns_nonzero_on_violation(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("-e .\n", encoding="utf-8")
    code = check_requirements.main(["-Path", str(path)])
    assert code == 1


def test_main_returns_nonzero_when_no_target_given():
    assert check_requirements.main([]) == 1


# ── build_venv.py の純粋部品 ──
def test_require_wheelhouse_raises_when_missing(tmp_path):
    missing = tmp_path / "no-such-wheelhouse"
    try:
        build_venv.require_wheelhouse(missing)
    except RuntimeError as exc:
        assert "wheelhouse" in str(exc)
    else:
        raise AssertionError("wheelhouse が無いのに RuntimeError が送出されなかった")


def test_require_wheelhouse_passes_when_present(tmp_path):
    present = tmp_path / "wheelhouse"
    present.mkdir()
    build_venv.require_wheelhouse(present)  # 例外を送出しないことを確認


def test_resolve_python_launcher_finds_py_or_python():
    # この開発機(Windows)は `py -3.13` の前提を持つ (README / setup_dev.py と同じ前提)。
    # CI(ubuntu)は `py` ランチャが無く `python` へフォールバックし、`shutil.which` は
    # フルパス(例 `/opt/hostedtoolcache/python/3.13.15/x64/bin/python`)を返すため、
    # 判定はフルパスそのものでなく basename(`.exe` 有無を問わない)で行う。
    launcher = build_venv.resolve_python_launcher()
    assert launcher is not None
    exe_name = pathlib.Path(launcher[0]).name.lower()
    assert exe_name in ("py", "python", "py.exe", "python.exe")


# ── build_venv(): requirements 検査 (assert_requirements_file) が pip install より先(M-5) ──
def test_build_venv_checks_requirements_before_pip_install(monkeypatch, tmp_path):
    calls: list[str] = []
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    requirements_path = tmp_path / "requirements.txt"
    requirements_path.write_text("markdown-it-py\n", encoding="utf-8")
    wheelhouse_dir = tmp_path / "python-wheelhouse"
    wheelhouse_dir.mkdir()

    # 既存の健全な venv を装う(python.exe が存在し --version が成功する)ことで、実際の
    # `python -m venv` 作成(重い実処理)を経由せずに、検査 → pip install の呼び出し順序
    # だけを確認する。
    venv_python = project_dir / ".venv-build" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_bytes(b"dummy")

    def fake_run(cmd, **kwargs):
        if str(venv_python) in cmd and "--version" in cmd:
            calls.append("venv_probe")
        elif "pip" in cmd:
            calls.append("pip_install")
        else:
            calls.append("other")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(build_venv.subprocess, "run", fake_run)
    monkeypatch.setattr(
        build_venv, "assert_requirements_file", lambda path: calls.append("assert_requirements_file")
    )

    result = build_venv.build_venv(project_dir, requirements_path, wheelhouse_dir)

    assert result == venv_python
    assert calls.index("assert_requirements_file") < calls.index("pip_install")


# ── bundle_common: requirements.txt 列挙 (git 経路 / FS フォールバック経路の一致) ──
def _init_git_repo(repo: pathlib.Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "-A"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=repo,
        check=True,
    )


def test_requirements_files_via_git_and_filesystem_match(tmp_path):
    (tmp_path / "requirements.txt").write_text("a\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "dev-requirements.txt").write_text("b\n", encoding="utf-8")
    # gitignore 相当 (追跡しない) の除外ディレクトリ。両経路とも除外することを確認する。
    # git 側は「そもそも追跡しない (add しない)」ことで、FS 側は名前判定で、同じ集合へ倒す。
    wheelhouse = tmp_path / "python-wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "requirements.txt").write_text("ignored\n", encoding="utf-8")
    venv_dir = tmp_path / ".venv-build"
    venv_dir.mkdir()
    (venv_dir / "requirements.txt").write_text("ignored\n", encoding="utf-8")
    # M-6 回帰: `.gitignore` に列挙されたビルド生成物ディレクトリ (dist/build/out 等) は
    # git 側では未追跡で最初から候補に入らない。FS フォールバックにも同じ除外が無いと、
    # ここに紛れ込んだファイルだけ FS 側が拾ってしまう非対称になる。
    for name in ("dist", "build", "out", "coverage", "test-results", "__pycache__"):
        d = tmp_path / name
        d.mkdir()
        (d / "requirements.txt").write_text("ignored\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "add",
         "requirements.txt", "sub/dev-requirements.txt"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=tmp_path,
        check=True,
    )

    via_git = bundle_common.list_requirements_files_via_git(tmp_path)
    via_fs = bundle_common.list_requirements_files_via_filesystem(tmp_path)
    assert via_git is not None
    rel_git = sorted(p.relative_to(tmp_path).as_posix() for p in via_git)
    rel_fs = sorted(p.relative_to(tmp_path).as_posix() for p in via_fs)
    assert rel_git == rel_fs == ["requirements.txt", "sub/dev-requirements.txt"]


def test_list_requirements_files_via_git_returns_none_when_git_unavailable(tmp_path, monkeypatch):
    # git 実行ファイルを発見できない環境では git 経路は None (呼び出し元が FS フォールバック
    # へ切り替える)。PATH を空同然にして `git` を解決不能にする。
    monkeypatch.setenv("PATH", str(tmp_path))
    assert bundle_common.list_requirements_files_via_git(tmp_path) is None


def test_list_requirements_files_prefers_git_when_available(tmp_path):
    (tmp_path / "requirements.txt").write_text("a\n", encoding="utf-8")
    _init_git_repo(tmp_path)
    files = bundle_common.list_requirements_files(tmp_path)
    assert [p.name for p in files] == ["requirements.txt"]


# ── list_requirements_files_via_git: 非 ASCII パスの quotepath 回帰 (I-1) ──
def test_list_requirements_files_via_git_handles_non_ascii_directory_name(tmp_path):
    # git は既定 (core.quotepath=true) で非 ASCII パスを引用符 + 8 進エスケープした
    # 文字列で返す。`-z` (NUL 区切り) を使わないと `repo_root / line` が実在しないパスに
    # なり、この日本語ディレクトリ配下の requirements.txt が黙って候補から落ちる。
    jp_dir = tmp_path / "日本語ディレクトリ"
    jp_dir.mkdir()
    (jp_dir / "requirements.txt").write_text("a\n", encoding="utf-8")
    _init_git_repo(tmp_path)

    files = bundle_common.list_requirements_files_via_git(tmp_path)
    assert files is not None
    rel = [p.relative_to(tmp_path).as_posix() for p in files]
    assert "日本語ディレクトリ/requirements.txt" in rel


# ── bundle_common: content-key ──
def test_compute_content_key_changes_with_requirements_content(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("pkgA==1.0\n", encoding="utf-8")
    key1 = bundle_common.compute_content_key(tmp_path, requirements_files=[req])
    req.write_text("pkgA==2.0\n", encoding="utf-8")
    key2 = bundle_common.compute_content_key(tmp_path, requirements_files=[req])
    assert key1 != key2
    assert len(key1) == 64
    int(key1, 16)  # hex digest であること


def test_compute_content_key_folds_in_vendor_manifest(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("pkgA==1.0\n", encoding="utf-8")
    vendor = tmp_path / "docs" / "_build" / "vendor"
    vendor.mkdir(parents=True)
    manifest = vendor / "manifest.txt"
    manifest.write_text("mermaid.min.js version=1\n", encoding="utf-8")
    key_before = bundle_common.compute_content_key(tmp_path, requirements_files=[req])
    manifest.write_text("mermaid.min.js version=2\n", encoding="utf-8")
    key_after = bundle_common.compute_content_key(tmp_path, requirements_files=[req])
    assert key_before != key_after


def test_compute_content_key_via_git_and_filesystem_paths_agree(tmp_path):
    # 「両経路は最初から同一集合」を content-key の値でも固定する。
    (tmp_path / "requirements.txt").write_text("pkgA==1.0\n", encoding="utf-8")
    vendor = tmp_path / "docs" / "_build" / "vendor"
    vendor.mkdir(parents=True)
    (vendor / "manifest.txt").write_text("m\n", encoding="utf-8")
    _init_git_repo(tmp_path)

    key_via_git = bundle_common.compute_content_key(
        tmp_path, requirements_files=bundle_common.list_requirements_files_via_git(tmp_path)
    )
    key_via_fs = bundle_common.compute_content_key(
        tmp_path, requirements_files=bundle_common.list_requirements_files_via_filesystem(tmp_path)
    )
    assert key_via_git == key_via_fs


def test_compute_content_key_is_line_ending_invariant(tmp_path):
    # Windows worktree (既定 core.autocrlf=true) は CRLF、GitHub の archive zip (codeload) は
    # LF になる。同じ内容が改行コードだけの違いで別の content-key を生むと、配布先での
    # bundle.key 突き合わせが恒久的に不一致になる。
    repo_crlf = tmp_path / "crlf"
    repo_lf = tmp_path / "lf"
    for repo, newline in ((repo_crlf, "\r\n"), (repo_lf, "\n")):
        repo.mkdir()
        content = f"pkgA==1.0{newline}pkgB==2.0{newline}"
        (repo / "requirements.txt").write_bytes(content.encode("utf-8"))
        vendor = repo / "docs" / "_build" / "vendor"
        vendor.mkdir(parents=True)
        (vendor / "manifest.txt").write_bytes(f"mermaid.min.js version=1{newline}".encode("utf-8"))

    key_crlf = bundle_common.compute_content_key(
        repo_crlf, requirements_files=[repo_crlf / "requirements.txt"]
    )
    key_lf = bundle_common.compute_content_key(
        repo_lf, requirements_files=[repo_lf / "requirements.txt"]
    )
    assert key_crlf == key_lf


# ── bundle_common: bundle.key の読み書き ──
def test_bundle_key_round_trip(tmp_path):
    path = tmp_path / "bundle.key"
    bundle_common.write_bundle_key(path, "deadbeef" * 8)
    assert bundle_common.read_bundle_key(path) == "deadbeef" * 8


# ── bundle_common: バンドル共通部品 ──
def test_build_tar_command_includes_wheelhouse_and_vendor_from_bundle_common(tmp_path):
    cmd = bundle_common.build_tar_command("tar", tmp_path / "b.tar.gz", tmp_path)
    assert cmd[:2] == ["tar", "-czf"]
    assert bundle_common.WHEELHOUSE_DIR_NAME in cmd
    assert bundle_common.VENDOR_DIR_POSIX in cmd


def test_sha256_file_matches_hashlib(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"payload")
    assert bundle_common.sha256_file(p) == hashlib.sha256(b"payload").hexdigest()


def test_assert_vendor_assets_present_raises_when_js_missing(tmp_path):
    vendor = tmp_path / "docs" / "_build" / "vendor"
    vendor.mkdir(parents=True)
    (vendor / "manifest.txt").write_text("v1\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        bundle_common.assert_vendor_assets_present(tmp_path)


# ── _FakeRunner / _completed: subprocess.run 互換の呼び出し記録スタブ(post-commit の runner 検証で使う) ──
class _FakeRunner:
    """`subprocess.run` 互換の呼び出し記録スタブ。実プロセスを起動せずに配線を検証する。"""

    def __init__(self, responses):
        # responses: {tuple(cmd): CompletedProcess} または呼び出し順のリスト
        self._responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        return self._responses.pop(0)


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ── pip 入口列挙ガード ──
def test_pip_entrypoint_guard_matches_known_set_and_requires_check_requirements():
    found = check_requirements.find_pip_call_files(REPO_ROOT)
    unknown = found - check_requirements.KNOWN_PIP_ENTRYPOINTS
    assert not unknown, f"未知の pip 呼び出し箇所 (KNOWN_PIP_ENTRYPOINTS へ追加するか実装を見直す): {unknown}"
    # 実在するファイルはすべて check_requirements の検査を経由すること
    # (.py は識別子 check_requirements、.bat はランチャ名 check-requirements のどちらか)。
    for rel in found:
        path = REPO_ROOT / rel
        text = path.read_text(encoding="utf-8")
        assert check_requirements.has_check_requirements_marker(text), (
            f"{rel}: check_requirements の呼び出しが見当たらない"
        )


def test_pip_entrypoint_guard_finds_all_existing_known_entrypoints():
    # found ⊆ known だけでは _PIP_CALL_RE が壊れて found が空になっても検出できない。
    # 既知集合のうち実在するファイルは必ず found に入ることも固定する
    # (ci.yml は Task 6 で新設予定のため path.exists() で絞る)。
    found = check_requirements.find_pip_call_files(REPO_ROOT)
    existing_known = {rel for rel in check_requirements.KNOWN_PIP_ENTRYPOINTS if (REPO_ROOT / rel).exists()}
    missing = existing_known - found
    assert not missing, f"検出漏れ (走査ロジックの劣化の疑い): {missing}"


def test_pip_entrypoint_guard_detects_setup_dev_itself():
    # 検出ロジックが壊れて何も見つからなくなる(ガードが常に無風で通る)ことを防ぐ回帰確認。
    found = check_requirements.find_pip_call_files(REPO_ROOT)
    assert "scripts/setup_dev.py" in found


def test_pip_entrypoint_guard_scans_bat_launchers_too():
    # `.bat` を走査対象へ含めないと docs/_build/build_all.bat の直接 pip 呼び出しを
    # 検出できない (未検査の pip 入口が実在するのに無風で通る)。
    found = check_requirements.find_pip_call_files(REPO_ROOT)
    assert "docs/_build/build_all.bat" in found


def test_find_pip_call_files_detects_non_ascii_named_file(tmp_path):
    # I-2 回帰: git は既定 (core.quotepath=true) で非 ASCII パスを引用符 + 8 進エスケープ
    # した文字列で返す。`-z` を使わないと `rel.endswith(_PIP_SCAN_EXTENSIONS)` が末尾の
    # `"` に阻まれて一致せず、無検査の pip 呼び出しが黙って通過する
    # (実証: 「セットアップ.bat」に無検査 pip を置いてもガードテストが緑のまま)。
    jp_bat = tmp_path / "セットアップ.bat"
    jp_bat.write_text("pip install -r requirements.txt\n", encoding="utf-8")
    _init_git_repo(tmp_path)

    found = check_requirements.find_pip_call_files(tmp_path)
    assert "セットアップ.bat" in found


# ═══════════════════════════════════════════════════════════════════════════
# scripts/setup_dev.py
# ═══════════════════════════════════════════════════════════════════════════


def test_list_requirements_handles_non_ascii_directory_name(tmp_path, monkeypatch):
    # I-1 回帰: `-z` を使わないと git の quotepath エスケープで `ROOT / line` が実在しない
    # パスになり、日本語ディレクトリ配下の requirements.txt が黙って install 対象から落ちる。
    jp_dir = tmp_path / "日本語ディレクトリ"
    jp_dir.mkdir()
    (jp_dir / "requirements.txt").write_text("a\n", encoding="utf-8")
    _init_git_repo(tmp_path)

    monkeypatch.setattr(setup_dev, "ROOT", tmp_path)
    files = setup_dev.list_requirements()
    rel = [p.relative_to(tmp_path).as_posix() for p in files]
    assert "日本語ディレクトリ/requirements.txt" in rel


def test_list_requirements_finds_root_and_nested_files(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("a\n", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "dev-requirements.txt").write_text("b\n", encoding="utf-8")
    _init_git_repo(tmp_path)

    monkeypatch.setattr(setup_dev, "ROOT", tmp_path)
    files = setup_dev.list_requirements()
    rel = sorted(p.relative_to(tmp_path).as_posix() for p in files)
    assert rel == ["requirements.txt", "sub/dev-requirements.txt"]


# ── check_wheelhouse: fail-closed(--online 未指定なら必須。M-5) ──
def test_check_wheelhouse_exits_when_missing_and_not_online(monkeypatch, tmp_path):
    monkeypatch.setattr(setup_dev, "WHEELHOUSE", tmp_path / "no-such-wheelhouse")
    with pytest.raises(SystemExit) as excinfo:
        setup_dev.check_wheelhouse(False)
    assert excinfo.value.code == 1


def test_check_wheelhouse_passes_when_present(monkeypatch, tmp_path):
    wheelhouse = tmp_path / "python-wheelhouse"
    wheelhouse.mkdir()
    monkeypatch.setattr(setup_dev, "WHEELHOUSE", wheelhouse)
    setup_dev.check_wheelhouse(False)  # 例外を送出しないことを確認


def test_check_wheelhouse_skips_check_when_online(monkeypatch, tmp_path):
    # --online (明示 opt-in) のときは wheelhouse 不在でも fail-closed の対象外。
    monkeypatch.setattr(setup_dev, "WHEELHOUSE", tmp_path / "no-such-wheelhouse")
    setup_dev.check_wheelhouse(True)  # 例外を送出しないことを確認


# ── check_requirements: assert_requirements_file と同じ契約 (RuntimeError。M-4) ──
def test_check_requirements_raises_runtime_error_on_violation(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("--find-links https://evil/\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        setup_dev.check_requirements([path])


def test_check_requirements_passes_clean_files(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("markdown-it-py\n", encoding="utf-8")
    setup_dev.check_requirements([path])  # 例外を送出しないことを確認


# ═══════════════════════════════════════════════════════════════════════════
# scripts/check_comments.py
# ═══════════════════════════════════════════════════════════════════════════


# ── _staged_files: 非 ASCII パスの quotepath 回帰 (I-1・実証済みの原因箇所) ──
def test_staged_files_returns_non_ascii_path_name(tmp_path, monkeypatch):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    jp_file = docs_dir / "設計書.md"
    jp_file.write_text("# ダミー\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "docs/設計書.md"],
        cwd=tmp_path,
        check=True,
    )

    monkeypatch.setattr(check_comments, "ROOT", tmp_path)
    staged = check_comments._staged_files()
    assert "docs/設計書.md" in staged


def test_staged_files_excludes_deleted_entries(tmp_path, monkeypatch):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    _init_git_repo(tmp_path)
    (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "b.py"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").unlink()
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True)  # ステージ済みの削除

    monkeypatch.setattr(check_comments, "ROOT", tmp_path)
    staged = check_comments._staged_files()
    assert staged == frozenset({"b.py"})


# ── _check_finding_ids: レビュー所見番号の検出 (§5) ──
#
# フィクスチャの所見番号文字列は連結で組み立てる (`"所見" + "3"` 等)。素の文字列リテラルで
# 書くと、このテストファイル自身を check_comments.py がスキャンしたときに「フィクスチャの
# サンプル」ではなく「実際に残った所見番号」として誤検知する (自己参照)。
_SAMPLE_FINDING_REF = "所見" + "3"


def test_check_finding_ids_flags_finding_reference_in_python_comment():
    errors: list[str] = []
    text = f"x = 1  # {_SAMPLE_FINDING_REF} は解消済み\n"
    check_comments._check_finding_ids(errors, "scripts/example.py", text, "py", check_comments.FINDING_ID_CODE)
    assert len(errors) == 1
    assert "scripts/example.py:1" in errors[0]


def test_check_finding_ids_allows_ordinary_comment():
    errors: list[str] = []
    text = "# ここは現在形の理由を書く\n"
    check_comments._check_finding_ids(errors, "scripts/example.py", text, "py", check_comments.FINDING_ID_CODE)
    assert errors == []


def test_check_finding_ids_flags_test_name_with_finding_number():
    errors: list[str] = []
    text = f'test("{_SAMPLE_FINDING_REF} の再発防止を確認する", () => {{\n  expect(1).toBe(1);\n}});\n'
    check_comments._check_finding_ids(
        errors, "web/test/example.test.ts", text, "ts", check_comments.FINDING_ID_CODE
    )
    assert any("テスト名にレビュー所見番号" in e for e in errors)


# ── main --staged: 一時 git repo で ERROR が出ることを確認する自己検知テスト (I-5) ──
def test_main_staged_detects_finding_id_violation(tmp_path, monkeypatch, capsys):
    (tmp_path / "a.py").write_text(f"x = 1  # {_SAMPLE_FINDING_REF} の対応\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True)  # commit しない (ステージのみ)

    monkeypatch.setattr(check_comments, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_comments.py", "--staged"])
    code = check_comments.main()
    out = capsys.readouterr()
    assert code == 1
    assert "ERROR" in (out.out + out.err)


def test_main_staged_passes_clean_tree(tmp_path, monkeypatch, capsys):
    (tmp_path / "a.py").write_text("x = 1  # 現在形の理由\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "a.py"], cwd=tmp_path, check=True)  # commit しない (ステージのみ)

    monkeypatch.setattr(check_comments, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_comments.py", "--staged"])
    code = check_comments.main()
    assert code == 0


# ═══════════════════════════════════════════════════════════════════════════
# offline/setup_offline.py
# ═══════════════════════════════════════════════════════════════════════════

# ── find_local_bundle: 直下優先、無ければ bk\ ──
def test_find_local_bundle_prefers_repo_root(tmp_path):
    (tmp_path / bundle_common.BUNDLE_NAME).write_bytes(b"b")
    (tmp_path / bundle_common.BUNDLE_KEY_NAME).write_text("k", encoding="ascii")
    bk = tmp_path / "bk"
    bk.mkdir()
    (bk / bundle_common.BUNDLE_NAME).write_bytes(b"old")
    (bk / bundle_common.BUNDLE_KEY_NAME).write_text("old", encoding="ascii")
    found = setup_offline.find_local_bundle(tmp_path)
    assert found == (tmp_path / bundle_common.BUNDLE_NAME, tmp_path / bundle_common.BUNDLE_KEY_NAME)


def test_find_local_bundle_falls_back_to_bk(tmp_path):
    bk = tmp_path / "bk"
    bk.mkdir()
    (bk / bundle_common.BUNDLE_NAME).write_bytes(b"b")
    (bk / bundle_common.BUNDLE_KEY_NAME).write_text("k", encoding="ascii")
    assert setup_offline.find_local_bundle(tmp_path) == (bk / bundle_common.BUNDLE_NAME, bk / bundle_common.BUNDLE_KEY_NAME)


def test_find_local_bundle_requires_both_files(tmp_path):
    (tmp_path / bundle_common.BUNDLE_NAME).write_bytes(b"b")
    assert setup_offline.find_local_bundle(tmp_path) is None


# ── download_release_assets: 3 アセットを HTTPS で取得(注入したダウンローダで検証) ──
def test_download_release_assets_fetches_bundle_sha256_and_key(tmp_path):
    urls: list[str] = []

    def fake_download(url, dest):
        urls.append(url)
        dest.write_bytes(b"x")

    bundle, sha, key = setup_offline.download_release_assets(
        "offline-bundle-v1", tmp_path, owner="o", repo="r", http_download=fake_download
    )
    base = "https://github.com/o/r/releases/download/offline-bundle-v1"
    assert urls == [
        f"{base}/{bundle_common.BUNDLE_NAME}",
        f"{base}/{bundle_common.BUNDLE_NAME}.sha256",
        f"{base}/{bundle_common.BUNDLE_KEY_NAME}",
    ]
    assert bundle.is_file() and sha.is_file() and key.is_file()


def test_download_release_assets_raises_when_download_fails(tmp_path):
    def failing(url, dest):
        raise OSError("boom")

    with pytest.raises(RuntimeError):
        setup_offline.download_release_assets("t", tmp_path, owner="o", repo="r", http_download=failing)


# ── verify_bundle_sha256_sidecar: Release の .sha256(転送破損の検知) ──
def test_verify_bundle_sha256_sidecar_passes_on_match(tmp_path):
    b = tmp_path / "b.tar.gz"
    b.write_bytes(b"payload")
    s = tmp_path / "b.tar.gz.sha256"
    s.write_text(f"{hashlib.sha256(b'payload').hexdigest()}  b.tar.gz", encoding="ascii")
    setup_offline.verify_bundle_sha256_sidecar(b, s)


def test_verify_bundle_sha256_sidecar_raises_on_mismatch(tmp_path):
    b = tmp_path / "b.tar.gz"
    b.write_bytes(b"payload")
    s = tmp_path / "b.tar.gz.sha256"
    s.write_text(f"{'0' * 64}  b.tar.gz", encoding="ascii")
    with pytest.raises(RuntimeError):
        setup_offline.verify_bundle_sha256_sidecar(b, s)


# ── main: 手元のバンドルがあれば取得しない / 無ければ取得して .sha256 を照合する ──
def test_main_uses_local_bundle_without_download(monkeypatch, tmp_path):
    calls: list[str] = []
    monkeypatch.setattr(setup_offline, "ROOT", tmp_path)
    monkeypatch.setattr(setup_offline, "find_local_bundle", lambda root: (tmp_path / "b", tmp_path / "k"))
    monkeypatch.setattr(setup_offline, "download_release_assets", lambda *a, **k: calls.append("download"))
    monkeypatch.setattr(setup_offline, "verify_bundle_sha256_sidecar", lambda *a, **k: calls.append("sha256"))
    monkeypatch.setattr(
        setup_offline, "verify_local_checkout_matches_bundle_key", lambda *a, **k: calls.append("key")
    )
    monkeypatch.setattr(setup_offline, "extract_bundle", lambda *a, **k: calls.append("extract"))
    assert setup_offline.main([]) == 0
    assert calls == ["key", "extract"]


def test_main_downloads_and_checks_sidecar_when_no_local_bundle(monkeypatch, tmp_path):
    calls: list[str] = []
    monkeypatch.setattr(setup_offline, "ROOT", tmp_path)
    monkeypatch.setattr(setup_offline, "find_local_bundle", lambda root: None)

    def fake_download(tag, dest_dir, **kwargs):
        calls.append("download")
        return dest_dir / "b", dest_dir / "b.sha256", dest_dir / "k"

    monkeypatch.setattr(setup_offline, "download_release_assets", fake_download)
    monkeypatch.setattr(setup_offline, "verify_bundle_sha256_sidecar", lambda *a, **k: calls.append("sha256"))
    monkeypatch.setattr(
        setup_offline, "verify_local_checkout_matches_bundle_key", lambda *a, **k: calls.append("key")
    )
    monkeypatch.setattr(setup_offline, "extract_bundle", lambda *a, **k: calls.append("extract"))
    assert setup_offline.main([]) == 0
    assert calls == ["download", "sha256", "key", "extract"]


# ── extract_bundle / remove_extracted_bundle (手順5) ──
def _make_bundle_tar(tmp_path, *, include_vendor=True):
    stage = tmp_path / "stage"
    wheelhouse = stage / bundle_common.WHEELHOUSE_DIR_NAME
    wheelhouse.mkdir(parents=True)
    (wheelhouse / "dummy.whl").write_bytes(b"x")
    if include_vendor:
        vendor = stage / "docs" / "_build" / "vendor"
        vendor.mkdir(parents=True)
        (vendor / "manifest.txt").write_text("v1\n", encoding="utf-8")
        (vendor / "mermaid.min.js").write_bytes(b"x")
        (vendor / "mermaid-layout-elk.min.js").write_bytes(b"x")
    tar_path = tmp_path / bundle_common.BUNDLE_NAME
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(wheelhouse, arcname=bundle_common.WHEELHOUSE_DIR_NAME)
        if include_vendor:
            tf.add(stage / "docs", arcname="docs")
    return tar_path

def test_extract_bundle_creates_wheelhouse_and_vendor(tmp_path):
    tar_path = _make_bundle_tar(tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    setup_offline.extract_bundle(tar_path, repo_root)
    assert (repo_root / bundle_common.WHEELHOUSE_DIR_NAME / "dummy.whl").is_file()
    assert (repo_root / "docs" / "_build" / "vendor" / "manifest.txt").is_file()


def test_extract_bundle_raises_when_vendor_assets_missing(tmp_path):
    tar_path = _make_bundle_tar(tmp_path, include_vendor=False)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    with pytest.raises(RuntimeError):
        setup_offline.extract_bundle(tar_path, repo_root)


def test_remove_extracted_bundle_deletes_wheelhouse_and_vendor_js_but_keeps_manifest(tmp_path):
    repo_root = tmp_path
    wheelhouse = repo_root / bundle_common.WHEELHOUSE_DIR_NAME
    wheelhouse.mkdir()
    (wheelhouse / "dummy.whl").write_bytes(b"x")
    vendor = repo_root / "docs" / "_build" / "vendor"
    vendor.mkdir(parents=True)
    (vendor / "mermaid.min.js").write_bytes(b"x")
    (vendor / "mermaid-layout-elk.min.js").write_bytes(b"x")
    (vendor / "manifest.txt").write_text("v1\n", encoding="utf-8")

    setup_offline.remove_extracted_bundle(repo_root)

    assert not wheelhouse.exists()
    assert not (vendor / "mermaid.min.js").exists()
    assert not (vendor / "mermaid-layout-elk.min.js").exists()
    assert (vendor / "manifest.txt").is_file()  # git 管理下のファイルは消さない


# ── verify_local_checkout_matches_bundle_key (手順4・I-3) ──
def test_verify_local_checkout_matches_bundle_key_passes_on_match(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle_common, "compute_content_key", lambda repo_root: "same-key")
    key_path = tmp_path / "bundle.key"
    key_path.write_text("same-key", encoding="ascii")

    # 例外が出ないことの確認。
    setup_offline.verify_local_checkout_matches_bundle_key(key_path, repo_root=tmp_path)


def test_verify_local_checkout_matches_bundle_key_raises_and_cleans_up_on_mismatch(tmp_path, monkeypatch):
    repo_root = tmp_path
    wheelhouse = repo_root / bundle_common.WHEELHOUSE_DIR_NAME
    wheelhouse.mkdir()
    (wheelhouse / "dummy.whl").write_bytes(b"x")
    vendor = repo_root / "docs" / "_build" / "vendor"
    vendor.mkdir(parents=True)
    (vendor / "mermaid.min.js").write_bytes(b"x")
    (vendor / "manifest.txt").write_text("v1\n", encoding="utf-8")

    monkeypatch.setattr(bundle_common, "compute_content_key", lambda repo_root: "local-key")
    key_path = repo_root / "bundle.key"
    key_path.write_text("published-key", encoding="ascii")

    with pytest.raises(RuntimeError):
        setup_offline.verify_local_checkout_matches_bundle_key(key_path, repo_root=repo_root)

    # 不一致は改ざんと同様に展開済みの重量物を残さない(半端な状態で setup-dev.bat を
    # 迎えさせない)。
    assert not wheelhouse.exists()
    assert not (vendor / "mermaid.min.js").exists()
    assert (vendor / "manifest.txt").is_file()


# ── I-3: 展開前後での照合結果の違いを実際に固定する ──
def test_i3_checking_before_extraction_detects_manifest_drift_that_after_extraction_misses(tmp_path):
    """公開後に `docs/_build/vendor/manifest.txt` だけが更新されたシナリオ:
    バンドル(公開時点)は旧 manifest("v1")を同梱・content-key に含める。手元チェックアウト
    は新 manifest("v2")へ進んでいる。展開の**前**に照合すれば不一致を検知できる一方、
    展開の**後**に測ると、バンドル同梱の旧 manifest が手元の新 manifest を上書きしてしまい
    検知できなくなる(旧実装で実際に起きていたバグ。I-3 の修正が「展開前」を要求する理由を
    実際に両方の順序を実行して固定する)。
    """
    # バンドル同梱の manifest は "v1"(`_make_bundle_tar` の既定値)。
    tar_path = _make_bundle_tar(tmp_path)

    # 公開時の content-key ("v1" の requirements + manifest から算出) を bundle.key として保存。
    stage = tmp_path / "publish_stage"
    (stage / "docs" / "_build" / "vendor").mkdir(parents=True)
    (stage / "requirements.txt").write_text("pkgA==1.0\n", encoding="utf-8")
    (stage / "docs" / "_build" / "vendor" / "manifest.txt").write_text("v1\n", encoding="utf-8")
    published_key = bundle_common.compute_content_key(stage)
    key_path = tmp_path / "bundle.key"
    bundle_common.write_bundle_key(key_path, published_key)

    # 手元チェックアウトは公開後に manifest だけ "v2" へ更新された状態。
    repo_root = tmp_path / "repo"
    (repo_root / "docs" / "_build" / "vendor").mkdir(parents=True)
    (repo_root / "requirements.txt").write_text("pkgA==1.0\n", encoding="utf-8")
    (repo_root / "docs" / "_build" / "vendor" / "manifest.txt").write_text("v2\n", encoding="utf-8")

    # I-3 の新順序: 展開の前に照合すれば不一致を検知する。
    with pytest.raises(RuntimeError):
        setup_offline.verify_local_checkout_matches_bundle_key(key_path, repo_root=repo_root)

    # 対照 (旧順序の再現): 展開の後に測ると、バンドル同梱の "v1" manifest が repo_root の
    # "v2" を上書きし、不一致が構造的に検知できなくなる。
    setup_offline.extract_bundle(tar_path, repo_root)
    setup_offline.verify_local_checkout_matches_bundle_key(key_path, repo_root=repo_root)  # 例外なし = 検知漏れ


# ═══════════════════════════════════════════════════════════════════════════
# scripts/hooks/pre_push.py(タグのみ push は pytest 一式をスキップする判定)
# ═══════════════════════════════════════════════════════════════════════════


# ── parse_remote_refs: stdin ペイロードの 3 列目(remote ref)抽出 ──
def test_parse_remote_refs_extracts_third_column():
    stdin_text = (
        "refs/heads/main abcdef0123456789abcdef0123456789abcdef01 "
        "refs/heads/main 0000000000000000000000000000000000000000\n"
    )
    assert pre_push.parse_remote_refs(stdin_text) == ["refs/heads/main"]


def test_parse_remote_refs_handles_multiple_lines():
    stdin_text = (
        "refs/heads/main a refs/heads/main b\n"
        "refs/tags/offline-bundle-v1 c refs/tags/offline-bundle-v1 d\n"
    )
    assert pre_push.parse_remote_refs(stdin_text) == ["refs/heads/main", "refs/tags/offline-bundle-v1"]


def test_parse_remote_refs_returns_empty_list_for_blank_stdin():
    assert pre_push.parse_remote_refs("") == []
    assert pre_push.parse_remote_refs("\n\n") == []


def test_parse_remote_refs_handles_tag_deletion_push():
    # `git push origin :refs/tags/<tag>` の削除 push は 1 列目が `(delete)`・2 列目が
    # 全ゼロ sha1 になる(githooks(5))。3 列目(remote ref)は削除対象そのものの実名なので、
    # 削除 push でも実際にタグ削除できた(手順書に記載の検証手順)ことが示すとおり、
    # 1〜2 列目の綴りに関わらず parse_remote_refs は 3 列目だけを見れば正しく動く。
    stdin_text = (
        "(delete) 0000000000000000000000000000000000000000 "
        "refs/tags/offline-bundle-v1 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
    )
    assert pre_push.parse_remote_refs(stdin_text) == ["refs/tags/offline-bundle-v1"]


def test_decide_pre_push_action_skips_for_tag_deletion_push():
    refs = pre_push.parse_remote_refs(
        "(delete) 0000000000000000000000000000000000000000 "
        "refs/tags/offline-bundle-v1 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
    )
    assert pre_push.decide_pre_push_action(refs, ahead=None) == "skip"


def test_decide_pre_push_action_runs_for_branch_deletion_push():
    refs = pre_push.parse_remote_refs(
        "(delete) 0000000000000000000000000000000000000000 "
        "refs/heads/tmp-branch aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
    )
    assert pre_push.decide_pre_push_action(refs, ahead=None) == "run"


# ── decide_pre_push_action: タグのみ push はスキップ、ブランチ混在は実行 ──
def test_decide_pre_push_action_runs_for_branch_ref():
    assert pre_push.decide_pre_push_action(["refs/heads/main"], ahead=None) == "run"


def test_decide_pre_push_action_skips_for_tag_only_refs():
    assert pre_push.decide_pre_push_action(["refs/tags/offline-bundle-v1"], ahead=None) == "skip"


def test_decide_pre_push_action_runs_when_tag_and_branch_are_mixed():
    # ローリングタグ移動と同時にブランチも push する状況(手動 `git push --tags` 等)は
    # ブランチ ref が 1 つでも混じっていれば実行側へ倒す。
    assert (
        pre_push.decide_pre_push_action(["refs/tags/offline-bundle-v1", "refs/heads/main"], ahead=None)
        == "run"
    )


def test_decide_pre_push_action_falls_back_to_ahead_count_when_refs_empty():
    assert pre_push.decide_pre_push_action([], ahead=0) == "skip"
    assert pre_push.decide_pre_push_action([], ahead=3) == "run"


def test_decide_pre_push_action_runs_when_ahead_count_unavailable():
    # upstream 未設定・git 失敗等で ahead が取れない場合は安全側(実行)へ倒す。
    assert pre_push.decide_pre_push_action([], ahead=None) == "run"


# ── count_ahead_of_upstream: 実 git を使った ahead 数の取得 ──
def test_count_ahead_of_upstream_returns_none_without_upstream(tmp_path):
    _init_git_repo_with_commit(tmp_path)
    assert pre_push.count_ahead_of_upstream(cwd=tmp_path) is None


def test_count_ahead_of_upstream_counts_commits_ahead_of_upstream_branch(tmp_path):
    remote = tmp_path / "remote.git"
    remote.mkdir()
    subprocess.run(["git", "init", "-q", "--bare"], cwd=remote, check=True)

    work = tmp_path / "work"
    work.mkdir()
    _init_git_repo_with_commit(work)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=work, check=True)
    subprocess.run(["git", "push", "-q", "-u", "origin", "HEAD:refs/heads/main"], cwd=work, check=True)

    (work / "b.txt").write_text("b\n", encoding="utf-8")
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "b.txt"],
        cwd=work,
        check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "second"],
        cwd=work,
        check=True,
    )

    assert pre_push.count_ahead_of_upstream(cwd=work) == 1


def _init_git_repo_with_commit(repo: pathlib.Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "a.txt"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "init"],
        cwd=repo,
        check=True,
    )


# ── run_pytest_suite: 失敗したステップで即座に打ち切る ──
def test_run_pytest_suite_stops_at_first_failure(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None):
        calls.append(list(cmd))
        # 2 ステップ目(docs/_build)を失敗させる。
        rc = 1 if cmd[-1] == "docs/_build" else 0
        return subprocess.CompletedProcess(args=cmd, returncode=rc)

    monkeypatch.setattr(pre_push.subprocess, "run", fake_run)
    code = pre_push.run_pytest_suite(cwd=tmp_path)
    assert code == 1
    # scripts, docs/_build までで打ち切り、pdf-to-svg 以降は呼ばれない。
    assert [c[-1] for c in calls] == ["scripts", "docs/_build"]


def test_run_pytest_suite_runs_all_steps_when_all_pass(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(pre_push.subprocess, "run", fake_run)
    code = pre_push.run_pytest_suite(cwd=tmp_path)
    assert code == 0
    assert len(calls) == len(pre_push.PYTEST_STEPS)


# ── run_check_comments / main: I-5 (check_comments はフルツリー・pytest より先) ──
def test_run_check_comments_invokes_script_without_staged_flag(monkeypatch, tmp_path):
    calls: list[list[str]] = []

    def fake_run(cmd, cwd=None):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(pre_push.subprocess, "run", fake_run)
    code = pre_push.run_check_comments(cwd=tmp_path)
    assert code == 0
    assert len(calls) == 1
    assert str(pre_push.CHECK_COMMENTS_SCRIPT) in calls[0]
    assert "--staged" not in calls[0]  # フルツリーを検査する (pre-commit と役割分担)


def test_run_check_comments_returns_nonzero_on_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        pre_push.subprocess, "run", lambda cmd, cwd=None: subprocess.CompletedProcess(args=cmd, returncode=1)
    )
    assert pre_push.run_check_comments(cwd=tmp_path) == 1


def test_main_runs_check_comments_before_pytest_suite_and_stops_on_failure(monkeypatch):
    # check_comments が失敗したら pytest 一式(重い・数分かかる)は 1 つも走らせない。
    calls: list[str] = []
    monkeypatch.setattr(sys, "stdin", io.StringIO("refs/heads/main a b refs/heads/main c\n"))
    monkeypatch.setattr(pre_push, "run_check_comments", lambda: calls.append("check_comments") or 1)
    monkeypatch.setattr(pre_push, "run_pytest_suite", lambda: calls.append("pytest_suite") or 0)

    code = pre_push.main()

    assert code == 1
    assert calls == ["check_comments"]


def test_main_runs_pytest_suite_after_check_comments_passes(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(sys, "stdin", io.StringIO("refs/heads/main a b refs/heads/main c\n"))
    monkeypatch.setattr(pre_push, "run_check_comments", lambda: calls.append("check_comments") or 0)
    monkeypatch.setattr(pre_push, "run_pytest_suite", lambda: calls.append("pytest_suite") or 0)

    code = pre_push.main()

    assert code == 0
    assert calls == ["check_comments", "pytest_suite"]


# ═══════════════════════════════════════════════════════════════════════════
# scripts/hooks/post_commit.py(auto-push + publish_bundle.py --tag-only)
# ═══════════════════════════════════════════════════════════════════════════


def _post_commit_completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


# ── build_push_command: upstream 有無で push コマンドを出し分ける ──
def test_build_push_command_uses_plain_push_when_upstream_configured():
    assert post_commit.build_push_command(upstream_configured=True) == ["git", "push"]


def test_build_push_command_sets_upstream_when_not_configured():
    assert post_commit.build_push_command(upstream_configured=False) == ["git", "push", "-u", "origin", "HEAD"]


# ── has_upstream ──
def test_has_upstream_true_on_zero_exit():
    runner = _FakeRunner([_completed(returncode=0)])
    assert post_commit.has_upstream(runner=runner) is True


def test_has_upstream_false_on_nonzero_exit():
    runner = _FakeRunner([_completed(returncode=1)])
    assert post_commit.has_upstream(runner=runner) is False


# ── auto_push: force しない(non-fast-forward 等は警告のみで例外を投げない) ──
def test_auto_push_runs_plain_push_when_upstream_exists(capsys):
    runner = _FakeRunner([_post_commit_completed(returncode=0), _post_commit_completed(returncode=0, stdout="ok")])
    post_commit.auto_push(runner=runner)
    assert runner.calls[1] == ["git", "push"]
    assert "auto-push" in capsys.readouterr().out


def test_auto_push_sets_upstream_when_missing():
    runner = _FakeRunner([_post_commit_completed(returncode=1), _post_commit_completed(returncode=0)])
    post_commit.auto_push(runner=runner)
    assert runner.calls[1] == ["git", "push", "-u", "origin", "HEAD"]


def test_auto_push_does_not_raise_on_non_fast_forward(capsys):
    # force push を自動実行しない契約: push が拒否されても例外を投げず、
    # 警告メッセージだけを stderr へ出す。
    runner = _FakeRunner(
        [
            _post_commit_completed(returncode=0),
            _post_commit_completed(returncode=1, stderr="! [rejected] main -> main (non-fast-forward)"),
        ]
    )
    post_commit.auto_push(runner=runner)  # 例外を送出しないことを確認
    err = capsys.readouterr().err
    assert "force-with-lease" in err
    assert all(c != ["git", "push", "--force"] for c in runner.calls)
    assert all("--force" not in c and "-f" not in c for c in runner.calls)


# ── publish_tag_only: ファイル不在ならベストエフォートで何もしない ──
def test_publish_tag_only_skips_when_publish_bundle_missing(tmp_path):
    runner = _FakeRunner([])
    post_commit.publish_tag_only(runner=runner, publish_bundle_path=tmp_path / "no-such-file.py")
    assert runner.calls == []


def test_publish_tag_only_invokes_publish_bundle_with_tag_only_flag(tmp_path):
    publish_bundle_path = tmp_path / "publish_bundle.py"
    publish_bundle_path.write_text("# dummy\n", encoding="utf-8")
    runner = _FakeRunner([_post_commit_completed(returncode=0, stdout="[skip] unchanged")])
    post_commit.publish_tag_only(runner=runner, publish_bundle_path=publish_bundle_path)
    assert runner.calls[0][1] == str(publish_bundle_path)
    assert runner.calls[0][2] == "--tag-only"


def test_publish_tag_only_warns_but_does_not_raise_on_failure(tmp_path, capsys):
    publish_bundle_path = tmp_path / "publish_bundle.py"
    publish_bundle_path.write_text("# dummy\n", encoding="utf-8")
    runner = _FakeRunner([_post_commit_completed(returncode=1, stderr="boom")])
    post_commit.publish_tag_only(runner=runner, publish_bundle_path=publish_bundle_path)  # 例外なし
    assert "失敗しました" in capsys.readouterr().err


# ── main: 常に 0 を返す(post-commit はベストエフォートで非ゼロ終了しない契約) ──
def test_main_always_returns_zero_even_when_steps_fail(monkeypatch, capsys):
    # `auto_push` / `publish_tag_only` 自身が捕捉しない**未想定の例外**(git 未導入時の
    # `FileNotFoundError` 等)を投げても、`main` はそれを飲み込んで 0 を返すことを確認する
    # (post-commit はコミット確定後のフックのため、生の traceback を出さない契約)。
    def failing_auto_push():
        raise RuntimeError("boom-auto-push")

    def failing_publish_tag_only():
        raise FileNotFoundError("boom-publish-tag-only")

    monkeypatch.setattr(post_commit, "auto_push", failing_auto_push)
    monkeypatch.setattr(post_commit, "publish_tag_only", failing_publish_tag_only)
    assert post_commit.main() == 0
    err = capsys.readouterr().err
    assert "auto-push" in err
    assert "publish_bundle.py --tag-only" in err


def test_main_still_runs_publish_tag_only_after_auto_push_raises(monkeypatch):
    # ベストエフォートの各ステップは独立: 1 つ目が未想定の例外で落ちても 2 つ目は
    # 実行されること(前段の失敗で後段を巻き込んで止めない)。
    calls: list[str] = []

    def failing_auto_push():
        raise RuntimeError("boom")

    monkeypatch.setattr(post_commit, "auto_push", failing_auto_push)
    monkeypatch.setattr(post_commit, "publish_tag_only", lambda: calls.append("publish_tag_only"))
    assert post_commit.main() == 0
    assert calls == ["publish_tag_only"]


# ── _run_best_effort_step: 未想定の例外を捕捉して警告のみに倒す ──
def test_run_best_effort_step_catches_exception_and_warns(capsys):
    def raiser():
        raise ValueError("nope")

    post_commit._run_best_effort_step("some-step", raiser)  # 例外を送出しないことを確認
    err = capsys.readouterr().err
    assert "some-step" in err
    assert "未想定の例外" in err


def test_run_best_effort_step_runs_step_when_no_exception():
    calls: list[str] = []
    post_commit._run_best_effort_step("ok-step", lambda: calls.append("ran"))
    assert calls == ["ran"]


def test_repo_configs_workspace_has_all_required_fields():
    # monorepo 側の複製は ACTIVE_REPO を "workspace" へ切り替えるだけで動く契約。
    # フィールド欠落は複製先で初回実行時の KeyError になるため、python-tools 側の
    # テストで先に固定する(python-tools キーを必須フィールドの正とみなす)
    required = set(check_comments.REPO_CONFIGS["python-tools"].keys())
    workspace = check_comments.REPO_CONFIGS["workspace"]
    assert required - set(workspace.keys()) == set()
    # monorepo は .ps1 現役のため forbid ではなく check モードであること
    assert workspace["ps1_mode"] == "check"
    # .husky シムと docs/_samples 除外は monorepo 固有の必須設定
    assert ".husky/" in workspace["shell_shim_prefixes"]
    assert "docs/_samples/" in workspace["finding_id_skip_prefixes"]
