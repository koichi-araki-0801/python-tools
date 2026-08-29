# -*- coding: utf-8 -*-
"""`scripts/` 配下の部品の単体テスト。実行: `py -3.13 -m pytest scripts -q`。

`check_requirements.py` のテストベクタは monorepo `offline/lib/verify.Tests.ps1`
(`Test-OfflineRequirementLine`) の受理/拒否ケースを逐語移植する。`build_venv.py` は
実際の venv 作成・pip install を伴わない純粋な部品 (wheelhouse fail-closed 判定・
Python ランチャ解決) だけを単体対象とする。実際にビルドが通ることは
`graph-editor/scripts/build.bat` / `pdf-to-svg/scripts/build.bat` の実行で確認する。

`offline/lib/bundle_common.py` / `offline/publish_bundle.py` は content-key 2 経路一致・
pin round-trip・署名生成/検証/改竄検出・pip 入口列挙ガードを対象とする。gh/git を呼ぶ
関数は本ファイルでは実行せず、注入した偽の runner (`subprocess.run` 互換の呼び出し記録)
で検証する (実 publish の実行は本テストの対象外)。
"""

import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "lib"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "offline"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "offline" / "lib"))

import pytest  # noqa: E402

import check_requirements  # noqa: E402
import build_venv  # noqa: E402
import bundle_common  # noqa: E402
import publish_bundle  # noqa: E402

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
    # この開発機は `py -3.13` の前提を持つ (README / setup_dev.py と同じ前提)。
    launcher = build_venv.resolve_python_launcher()
    assert launcher is not None
    exe = launcher[0].lower()
    assert exe in ("py", "python") or exe.endswith(("py.exe", "python.exe"))


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


# ── bundle_common: pin (offline/pinned-release.txt) の round-trip ──
def test_pin_round_trip(tmp_path):
    pin = bundle_common.PublishPin(
        source_commit="a" * 40,
        source_zip_sha256="b" * 64,
        bundle_sha256="c" * 64,
    )
    path = tmp_path / "pinned-release.txt"
    bundle_common.write_pin(path, pin)
    loaded = bundle_common.read_pin(path)
    assert loaded == pin


def test_read_pin_missing_file_raises(tmp_path):
    with pytest.raises(Exception):
        bundle_common.read_pin(tmp_path / "no-such-pin.txt")


def test_read_pin_rejects_malformed_commit_id(tmp_path):
    path = tmp_path / "pinned-release.txt"
    path.write_text(
        "source-commit not-a-hex-id\n"
        f"source-zip-sha256 {'b' * 64}\n"
        f"bundle-sha256 {'c' * 64}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        bundle_common.read_pin(path)


def test_read_pin_rejects_short_sha256(tmp_path):
    path = tmp_path / "pinned-release.txt"
    path.write_text(
        f"source-commit {'a' * 40}\nsource-zip-sha256 deadbeef\nbundle-sha256 {'c' * 64}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        bundle_common.read_pin(path)


def test_read_pin_rejects_missing_key(tmp_path):
    path = tmp_path / "pinned-release.txt"
    path.write_text(f"source-commit {'a' * 40}\nbundle-sha256 {'c' * 64}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        bundle_common.read_pin(path)


# ── bundle_common: Ed25519 署名 (生成 -> 検証 -> 改竄検出) ──
def test_sign_and_verify_round_trip(tmp_path):
    private_pem, public_pem = bundle_common.generate_signing_key_pair()
    target = tmp_path / "bundle.bin"
    target.write_bytes(b"offline deps bundle content" * 100)
    sig = bundle_common.sign_file(target, private_pem)
    assert bundle_common.verify_signature(target, sig, public_pem) is True


def test_verify_signature_detects_tampering(tmp_path):
    private_pem, public_pem = bundle_common.generate_signing_key_pair()
    target = tmp_path / "bundle.bin"
    target.write_bytes(b"original content")
    sig = bundle_common.sign_file(target, private_pem)
    target.write_bytes(b"tampered content!")
    assert bundle_common.verify_signature(target, sig, public_pem) is False


def test_verify_signature_rejects_mismatched_key(tmp_path):
    private1, _public1 = bundle_common.generate_signing_key_pair()
    _private2, public2 = bundle_common.generate_signing_key_pair()
    target = tmp_path / "bundle.bin"
    target.write_bytes(b"data")
    sig = bundle_common.sign_file(target, private1)
    assert bundle_common.verify_signature(target, sig, public2) is False


def test_verify_signature_rejects_malformed_base64(tmp_path):
    _private, public_pem = bundle_common.generate_signing_key_pair()
    target = tmp_path / "bundle.bin"
    target.write_bytes(b"data")
    assert bundle_common.verify_signature(target, "not-valid-base64!!", public_pem) is False


def test_assert_bundle_signature_raises_on_failure(tmp_path):
    private_pem, public_pem = bundle_common.generate_signing_key_pair()
    target = tmp_path / "bundle.bin"
    target.write_bytes(b"x")
    sig = bundle_common.sign_file(target, private_pem)
    target.write_bytes(b"y")
    with pytest.raises(RuntimeError):
        bundle_common.assert_bundle_signature(target, sig, public_pem)


def test_assert_bundle_signature_passes_on_success(tmp_path):
    private_pem, public_pem = bundle_common.generate_signing_key_pair()
    target = tmp_path / "bundle.bin"
    target.write_bytes(b"x")
    sig = bundle_common.sign_file(target, private_pem)
    bundle_common.assert_bundle_signature(target, sig, public_pem)  # 例外を送出しないことを確認


# ── bundle_common: bundle.key の読み書き ──
def test_bundle_key_round_trip(tmp_path):
    path = tmp_path / "bundle.key"
    bundle_common.write_bundle_key(path, "deadbeef" * 8)
    assert bundle_common.read_bundle_key(path) == "deadbeef" * 8


# ── publish_bundle: 純粋な判定/構築部品 ──
def test_bundle_changed_true_on_force():
    assert publish_bundle.bundle_changed(
        force=True, release_exists=True, published_key="k", current_key="k"
    )


def test_bundle_changed_true_when_release_missing():
    assert publish_bundle.bundle_changed(
        force=False, release_exists=False, published_key=None, current_key="k"
    )


def test_bundle_changed_true_when_key_mismatch():
    assert publish_bundle.bundle_changed(
        force=False, release_exists=True, published_key="old", current_key="new"
    )


def test_bundle_changed_false_when_key_matches():
    assert not publish_bundle.bundle_changed(
        force=False, release_exists=True, published_key="k", current_key="k"
    )


def test_tag_only_skips_when_bundle_changed():
    assert publish_bundle.should_skip_tag_only(tag_only=True, changed=True) is True


def test_tag_only_does_not_skip_when_unchanged():
    assert publish_bundle.should_skip_tag_only(tag_only=True, changed=False) is False


def test_tag_only_flag_off_never_skips():
    assert publish_bundle.should_skip_tag_only(tag_only=False, changed=True) is False


def test_build_pip_download_command_targets_cp313_only_binary(tmp_path):
    wheelhouse = tmp_path / "python-wheelhouse"
    reqs = [tmp_path / "a" / "requirements.txt", tmp_path / "b" / "requirements.txt"]
    cmd = publish_bundle.build_pip_download_command(["py", "-3.13"], wheelhouse, reqs)
    assert cmd[:2] == ["py", "-3.13"]
    assert "download" in cmd
    assert "--python-version" in cmd and "3.13" in cmd
    assert "--only-binary=:all:" in cmd
    assert cmd.count("-r") == len(reqs)
    for req in reqs:
        assert str(req) in cmd
    assert str(wheelhouse) in cmd


def test_build_tar_command_includes_wheelhouse_and_vendor(tmp_path):
    cmd = publish_bundle.build_tar_command("tar.exe", tmp_path / publish_bundle.BUNDLE_NAME, tmp_path)
    assert cmd[0] == "tar.exe"
    assert "-czf" in cmd
    assert "python-wheelhouse" in cmd
    assert "docs/_build/vendor" in cmd


# ── publish_bundle: git/gh を呼ぶ関数 (注入した偽 runner で検証。実 subprocess は起動しない) ──
class _FakeRunner:
    """`subprocess.run` 互換の呼び出し記録スタブ。gh/git を実行せずに配線を検証する。"""

    def __init__(self, responses):
        # responses: {tuple(cmd): CompletedProcess} または呼び出し順のリスト
        self._responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        return self._responses.pop(0)


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_assert_head_pushed_passes_when_head_on_remote(tmp_path):
    sha = "a" * 40
    runner = _FakeRunner(
        [
            _completed(stdout=f"{sha}\n"),
            _completed(stdout=f"{sha}\trefs/heads/main\n"),
        ]
    )
    result = publish_bundle.assert_head_pushed(cwd=tmp_path, runner=runner)
    assert result == sha


def test_assert_head_pushed_raises_when_head_not_on_remote(tmp_path):
    runner = _FakeRunner(
        [
            _completed(stdout="a" * 40 + "\n"),
            _completed(stdout="b" * 40 + "\trefs/heads/main\n"),
        ]
    )
    with pytest.raises(RuntimeError):
        publish_bundle.assert_head_pushed(cwd=tmp_path, runner=runner)


def test_release_exists_true_on_zero_exit(tmp_path):
    runner = _FakeRunner([_completed(returncode=0)])
    assert publish_bundle.release_exists("offline-bundle-v1", runner=runner) is True


def test_release_exists_false_on_nonzero_exit(tmp_path):
    runner = _FakeRunner([_completed(returncode=1)])
    assert publish_bundle.release_exists("offline-bundle-v1", runner=runner) is False


def test_fetch_published_key_reads_downloaded_file(tmp_path):
    dest_dir = tmp_path / "dl"
    dest_dir.mkdir()
    # `gh release download` の実行結果として bundle.key が置かれた状態を模す
    # (実 gh は呼ばない。ダウンロード自体は runner 側の責務でテスト対象外)。
    (dest_dir / "bundle.key").write_text("deadbeef\n", encoding="ascii")
    runner = _FakeRunner([_completed(returncode=0)])
    key = publish_bundle.fetch_published_key("offline-bundle-v1", dest_dir, runner=runner)
    assert key == "deadbeef"
    assert runner.calls[0][0] == "gh"


def test_fetch_published_key_returns_none_on_download_failure(tmp_path):
    dest_dir = tmp_path / "dl"
    dest_dir.mkdir()
    runner = _FakeRunner([_completed(returncode=1)])
    assert publish_bundle.fetch_published_key("offline-bundle-v1", dest_dir, runner=runner) is None


def test_move_rolling_tag_pushes_force_ref(tmp_path):
    runner = _FakeRunner([_completed(returncode=0)])
    publish_bundle.move_rolling_tag("offline-bundle-v1", "a" * 40, cwd=tmp_path, runner=runner)
    assert runner.calls[0][:2] == ["git", "-C"]
    assert any("+"+"a" * 40+":refs/tags/offline-bundle-v1" in part for part in runner.calls[0])


def test_move_rolling_tag_raises_on_failure(tmp_path):
    runner = _FakeRunner([_completed(returncode=1, stderr="boom")])
    with pytest.raises(RuntimeError):
        publish_bundle.move_rolling_tag("offline-bundle-v1", "a" * 40, cwd=tmp_path, runner=runner)


# ── pip 入口列挙ガード ──
def test_pip_entrypoint_guard_matches_known_set_and_requires_check_requirements():
    found = publish_bundle.find_pip_call_files(REPO_ROOT)
    unknown = found - publish_bundle.KNOWN_PIP_ENTRYPOINTS
    assert not unknown, f"未知の pip 呼び出し箇所 (KNOWN_PIP_ENTRYPOINTS へ追加するか実装を見直す): {unknown}"
    # 実在するファイルはすべて check_requirements の検査を経由すること。
    for rel in found:
        path = REPO_ROOT / rel
        text = path.read_text(encoding="utf-8")
        assert "check_requirements" in text, f"{rel}: check_requirements の呼び出しが見当たらない"


def test_pip_entrypoint_guard_detects_publish_bundle_itself():
    # ガード自体が publish_bundle.py の pip download 呼び出しを検出できることの回帰確認
    # (検出ロジックが壊れて何も見つからなくなる = ガードが常に無風で通る、を防ぐ)。
    found = publish_bundle.find_pip_call_files(REPO_ROOT)
    assert "offline/publish_bundle.py" in found
