# -*- coding: utf-8 -*-
"""`scripts/` 配下の部品の単体テスト。実行: `py -3.13 -m pytest scripts -q`。

`check_requirements.py` のテストベクタは monorepo `offline/lib/verify.Tests.ps1`
(`Test-OfflineRequirementLine`) の受理/拒否ケースを逐語移植する。`build_venv.py` は
実際の venv 作成・依存導入を伴わない純粋な部品 (Python ランチャ解決・検査と導入の順序)
だけを単体対象とする。実際にビルドが通ることは
`graph-editor/scripts/build.bat` / `pdf-to-svg/scripts/build.bat` の実行で確認する。

実 git を使うテスト (`ls-files`/`init`/`add`/`commit`) はローカルで完結し、ネットワークには
一切アクセスしない。`fetch_docs_vendor.py` の HTTP 取得も注入可能で、実ネットワークへは
アクセスしない。
"""

import hashlib
import io
import pathlib
import shutil
import subprocess
import sys
import tarfile
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "lib"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "hooks"))

import pytest  # noqa: E402

import check_requirements  # noqa: E402
import check_comments  # noqa: E402
import build_venv  # noqa: E402
import setup_dev  # noqa: E402
import fetch_docs_vendor  # noqa: E402
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
    pip_cmds: list[list[str]] = []

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
            pip_cmds.append(list(cmd))
        else:
            calls.append("other")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(build_venv.subprocess, "run", fake_run)
    monkeypatch.setattr(
        build_venv, "assert_requirements_file", lambda path: calls.append("assert_requirements_file")
    )

    result = build_venv.build_venv(project_dir, requirements_path)

    assert result == venv_python
    assert calls.index("assert_requirements_file") < calls.index("pip_install")
    # オンライン導入なので索引を塞ぐ引数は付けない (requirements は -r で渡すだけ)。
    assert "--no-index" not in pip_cmds[0]
    assert "--find-links" not in pip_cmds[0]
    assert pip_cmds[0][-2:] == ["-r", str(requirements_path)]


# ── テスト用の一時 git repo (requirements 列挙・pip 入口ガードのテストで使う) ──
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


# ── build_pip_command: 索引を塞がずに PyPI から導入する ──
def test_build_pip_command_installs_from_index(tmp_path):
    req_a = tmp_path / "requirements.txt"
    req_b = tmp_path / "dev-requirements.txt"
    cmd = setup_dev.build_pip_command(["py", "-3.13"], [req_a, req_b])
    assert cmd[:5] == ["py", "-3.13", "-m", "pip", "install"]
    assert "--no-index" not in cmd
    assert "--find-links" not in cmd
    assert cmd[5:] == ["-r", str(req_a), "-r", str(req_b)]


def test_setup_dev_has_no_online_flag():
    # `--online` は既定がオンラインになったことで意味を失った。受け付けないことを固定する
    # (残っていると「明示 opt-in が要る」という誤解が生きたままになる)。
    with pytest.raises(SystemExit):
        setup_dev.parse_args(["--online"])


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
# scripts/hooks/pre_push.py(check_comments と pytest 一式を順に実行する)
# ═══════════════════════════════════════════════════════════════════════════


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
    monkeypatch.setattr(pre_push, "run_check_comments", lambda: calls.append("check_comments") or 1)
    monkeypatch.setattr(pre_push, "run_pytest_suite", lambda: calls.append("pytest_suite") or 0)

    code = pre_push.main()

    assert code == 1
    assert calls == ["check_comments"]


def test_main_runs_pytest_suite_after_check_comments_passes(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(pre_push, "run_check_comments", lambda: calls.append("check_comments") or 0)
    monkeypatch.setattr(pre_push, "run_pytest_suite", lambda: calls.append("pytest_suite") or 0)

    code = pre_push.main()

    assert code == 0
    assert calls == ["check_comments", "pytest_suite"]


# ═══════════════════════════════════════════════════════════════════════════
# scripts/hooks/post_commit.py(auto-push のベストエフォート呼び出し)
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


# ── main: 常に 0 を返す(post-commit はベストエフォートで非ゼロ終了しない契約) ──
def test_main_always_returns_zero_even_when_steps_fail(monkeypatch, capsys):
    # `auto_push` 自身が捕捉しない**未想定の例外**(git 未導入時の `FileNotFoundError` 等)を
    # 投げても、`main` はそれを飲み込んで 0 を返すことを確認する(post-commit はコミット
    # 確定後のフックのため、生の traceback を出さない契約)。
    def failing_auto_push():
        raise RuntimeError("boom-auto-push")

    monkeypatch.setattr(post_commit, "auto_push", failing_auto_push)
    assert post_commit.main() == 0
    err = capsys.readouterr().err
    assert "auto-push" in err


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


# ═══════════════════════════════════════════════════════════════════════════
# scripts/fetch_docs_vendor.py
# ═══════════════════════════════════════════════════════════════════════════

_VENDOR_A = "mermaid.min.js"
_VENDOR_B = "mermaid-layout-elk.min.js"


def _vendor_fixture(tmp_path, contents):
    """manifest と空の vendor ディレクトリを作り、(vendor_dir, manifest_path, expected) を返す。"""
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    lines = ["# コメント行", ""]
    expected = {}
    for name, body in contents.items():
        digest = hashlib.sha256(body).hexdigest()
        expected[name] = digest
        lines.append(f"{name}  version=1.2.3  sha256={digest}")
    manifest = vendor / "manifest.txt"
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return vendor, manifest, expected


def _make_tar(path, members):
    """{アーカイブ内の名前: bytes} から tar.gz を作る。"""
    with tarfile.open(path, "w:gz") as tf:
        for name, body in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tf.addfile(info, io.BytesIO(body))


def test_parse_manifest_reads_name_and_sha256():
    text = (
        "# 説明行\n"
        "\n"
        "mermaid.min.js             version=11.12.2  sha256=" + "a" * 64 + "\n"
        "mermaid-layout-elk.min.js  source=@mermaid-js/layout-elk@0.2.2  sha256=" + "b" * 64 + "\n"
    )
    assert fetch_docs_vendor.parse_manifest(text) == {
        "mermaid.min.js": "a" * 64,
        "mermaid-layout-elk.min.js": "b" * 64,
    }


def test_parse_manifest_ignores_lines_without_sha256():
    # sha256 トークンを持たない行は「期待値が無い」ため対象にしない
    # (拾ってしまうと検証できないファイルを配置対象へ入れることになる)。
    text = "notes.txt  version=1\nmermaid.min.js  sha256=" + "c" * 64 + "\n"
    assert fetch_docs_vendor.parse_manifest(text) == {"mermaid.min.js": "c" * 64}


def test_vendor_is_current_true_when_all_files_match(tmp_path):
    vendor, _manifest, expected = _vendor_fixture(tmp_path, {_VENDOR_A: b"payload"})
    (vendor / _VENDOR_A).write_bytes(b"payload")
    assert fetch_docs_vendor.vendor_is_current(vendor, expected) is True


def test_vendor_is_current_false_when_missing_or_mismatched(tmp_path):
    vendor, _manifest, expected = _vendor_fixture(tmp_path, {_VENDOR_A: b"payload"})
    assert fetch_docs_vendor.vendor_is_current(vendor, expected) is False
    (vendor / _VENDOR_A).write_bytes(b"other")
    assert fetch_docs_vendor.vendor_is_current(vendor, expected) is False


def test_fetch_skips_download_when_already_current(tmp_path):
    vendor, manifest, _expected = _vendor_fixture(tmp_path, {_VENDOR_A: b"payload"})
    (vendor / _VENDOR_A).write_bytes(b"payload")
    calls = []

    def downloader(url, dest):
        calls.append(url)

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is True
    assert calls == []


def test_fetch_places_files_on_success(tmp_path):
    bodies = {_VENDOR_A: b"aaa", _VENDOR_B: b"bbb"}
    vendor, manifest, _expected = _vendor_fixture(tmp_path, bodies)
    archive = tmp_path / "src.tar.gz"
    _make_tar(archive, bodies)

    def downloader(url, dest):
        shutil.copyfile(archive, dest)

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is True
    assert (vendor / _VENDOR_A).read_bytes() == b"aaa"
    assert (vendor / _VENDOR_B).read_bytes() == b"bbb"


def test_fetch_rejects_unexpected_member_and_keeps_existing(tmp_path):
    # manifest に無い名前のメンバが 1 件でもあれば展開しない。
    bodies = {_VENDOR_A: b"aaa"}
    vendor, manifest, _expected = _vendor_fixture(tmp_path, bodies)
    (vendor / _VENDOR_A).write_bytes(b"old")
    archive = tmp_path / "src.tar.gz"
    _make_tar(archive, {_VENDOR_A: b"aaa", "evil.js": b"x"})

    def downloader(url, dest):
        shutil.copyfile(archive, dest)

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is False
    assert (vendor / _VENDOR_A).read_bytes() == b"old"
    assert not (vendor / "evil.js").exists()


def test_fetch_rejects_path_traversal_member(tmp_path):
    bodies = {_VENDOR_A: b"aaa"}
    vendor, manifest, _expected = _vendor_fixture(tmp_path, bodies)
    archive = tmp_path / "src.tar.gz"
    _make_tar(archive, {_VENDOR_A: b"aaa", "../escaped.js": b"x"})

    def downloader(url, dest):
        shutil.copyfile(archive, dest)

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is False
    assert not (tmp_path / "escaped.js").exists()


def test_fetch_rejects_non_regular_member(tmp_path):
    bodies = {_VENDOR_A: b"aaa"}
    vendor, manifest, _expected = _vendor_fixture(tmp_path, bodies)
    archive = tmp_path / "src.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo(_VENDOR_A)
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tf.addfile(info)

    def downloader(url, dest):
        shutil.copyfile(archive, dest)

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is False


def test_fetch_fails_on_sha256_mismatch_and_keeps_existing(tmp_path):
    vendor, manifest, _expected = _vendor_fixture(tmp_path, {_VENDOR_A: b"aaa"})
    (vendor / _VENDOR_A).write_bytes(b"old")
    archive = tmp_path / "src.tar.gz"
    _make_tar(archive, {_VENDOR_A: b"tampered"})

    def downloader(url, dest):
        shutil.copyfile(archive, dest)

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is False
    assert (vendor / _VENDOR_A).read_bytes() == b"old"


def test_fetch_fails_when_member_missing(tmp_path):
    bodies = {_VENDOR_A: b"aaa", _VENDOR_B: b"bbb"}
    vendor, manifest, _expected = _vendor_fixture(tmp_path, bodies)
    archive = tmp_path / "src.tar.gz"
    _make_tar(archive, {_VENDOR_A: b"aaa"})

    def downloader(url, dest):
        shutil.copyfile(archive, dest)

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is False
    assert not (vendor / _VENDOR_A).exists()


def test_fetch_returns_false_when_download_raises(tmp_path):
    vendor, manifest, _expected = _vendor_fixture(tmp_path, {_VENDOR_A: b"aaa"})

    def downloader(url, dest):
        raise OSError("ネットワークに到達できません")

    assert fetch_docs_vendor.fetch(vendor, manifest, downloader=downloader) is False


def test_fetch_returns_false_when_manifest_missing(tmp_path):
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    assert fetch_docs_vendor.fetch(vendor, vendor / "manifest.txt", downloader=None) is False


def test_asset_url_points_at_release_download():
    url = fetch_docs_vendor.asset_url()
    assert url == (
        "https://github.com/koichi-araki-0801/python-tools/releases/download/"
        "docs-vendor-v1/docs-vendor.tar.gz"
    )


def test_repo_manifest_lists_both_runtime_files():
    # 実リポの manifest が 2 件を持つこと (書式変更でパーサが空を返す退行の検出)。
    text = (REPO_ROOT / "docs" / "_build" / "vendor" / "manifest.txt").read_text(encoding="utf-8")
    entries = fetch_docs_vendor.parse_manifest(text)
    assert set(entries) == {"mermaid.min.js", "mermaid-layout-elk.min.js"}
    assert all(len(v) == 64 for v in entries.values())
