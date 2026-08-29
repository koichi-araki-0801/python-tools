# -*- coding: utf-8 -*-
"""`scripts/` 配下の部品の単体テスト。実行: `py -3.13 -m pytest scripts -q`。

`check_requirements.py` のテストベクタは monorepo `offline/lib/verify.Tests.ps1`
(`Test-OfflineRequirementLine`) の受理/拒否ケースを逐語移植する。`build_venv.py` は
実際の venv 作成・pip install を伴わない純粋な部品 (wheelhouse fail-closed 判定・
Python ランチャ解決) だけを単体対象とする。実際にビルドが通ることは
`graph-editor/scripts/build.bat` / `pdf-to-svg/scripts/build.bat` の実行で確認する。

`offline/lib/bundle_common.py` / `offline/publish_bundle.py` は content-key 2 経路一致・
pin round-trip・署名生成/検証/改竄検出・pip 入口列挙ガードを対象とする。requirements 列挙の
テストは実 git (`ls-files`/`init`/`add`/`commit`) をローカルで実行する (ネットワークには
一切アクセスしない)。`offline/publish_bundle.py` の gh/git を呼ぶ関数は注入した偽の runner
(`subprocess.run` 互換の呼び出し記録) で検証し、実 gh/git コマンドは呼ばない
(実 publish の実行は本テストの対象外)。

`offline/setup_offline.py` はブートストラップ順序(pin/公開鍵読込 → バンドル取得 →
sha256 照合 → 展開 → cryptography 導入 → 署名検証 → source zip 照合)の各部品を対象とする。
gh を呼ぶ関数・HTTP 取得を行う関数はすべて注入可能にしてあり、実ネットワークへは一切
アクセスしない。手順の実行順序そのもの (`main` の呼び出し順) は各部品を偽関数へ差し替えて
記録することで固定する。実際に別端末相当の配布検証を行うことは本テストの対象外
(`%TEMP%` の新規 clone での手動確認に委ねる)。
"""

import hashlib
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
import build_venv  # noqa: E402
import bundle_common  # noqa: E402
import publish_bundle  # noqa: E402
import setup_offline  # noqa: E402
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
    with pytest.raises(ValueError):
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


# ── publish_bundle: Release アセットサイズ上限(2GB) ──
def test_assert_release_asset_size_ok_passes_under_limit():
    publish_bundle.assert_release_asset_size_ok(1024)  # 例外を送出しないことを確認


def test_assert_release_asset_size_ok_raises_at_2gb_limit():
    with pytest.raises(RuntimeError):
        publish_bundle.assert_release_asset_size_ok(2 * 1024 * 1024 * 1024)


def test_assert_release_asset_size_ok_raises_above_limit():
    with pytest.raises(RuntimeError):
        publish_bundle.assert_release_asset_size_ok(3 * 1024 * 1024 * 1024)


# ── publish_bundle: gh_set_repo_visibility(常に --accept-visibility-change-consequences) ──
def test_gh_set_repo_visibility_always_includes_accept_flag():
    # gh 2.93.0 実測: このフラグは public 化のときだけでなく private への復帰でも必須。
    # 欠けるとクライアント側検証でリポジトリ解決より前に exit 1 になる。
    for visibility in ("public", "private"):
        runner = _FakeRunner([_completed(returncode=0)])
        publish_bundle.gh_set_repo_visibility(visibility, runner=runner)
        assert "--accept-visibility-change-consequences" in runner.calls[0]
        assert visibility in runner.calls[0]


def test_gh_set_repo_visibility_raises_on_failure():
    runner = _FakeRunner([_completed(returncode=1, stderr="boom")])
    with pytest.raises(RuntimeError):
        publish_bundle.gh_set_repo_visibility("private", runner=runner)


# ── publish_bundle: temporarily_public_repo(一時的な Public 化と検証付き復帰) ──
def test_temporarily_public_repo_skips_when_already_public():
    runner = _FakeRunner([_completed(stdout="public\n")])
    with publish_bundle.temporarily_public_repo(runner=runner):
        pass
    # 初期取得のみ。既に public のときは public 化も復帰も呼ばない。
    assert len(runner.calls) == 1


def test_temporarily_public_repo_makes_public_and_restores_private():
    runner = _FakeRunner(
        [
            _completed(stdout="private\n"),  # 初期取得
            _completed(returncode=0),  # public 化
            _completed(returncode=0),  # private への復帰
            _completed(stdout="private\n"),  # 復帰後の再取得 (検証)
        ]
    )
    with publish_bundle.temporarily_public_repo(runner=runner):
        pass
    assert len(runner.calls) == 4
    assert "public" in runner.calls[1]
    assert "private" in runner.calls[2]
    assert "--accept-visibility-change-consequences" in runner.calls[1]
    assert "--accept-visibility-change-consequences" in runner.calls[2]


def test_temporarily_public_repo_reverts_on_body_exception():
    runner = _FakeRunner(
        [
            _completed(stdout="private\n"),
            _completed(returncode=0),
            _completed(returncode=0),
            _completed(stdout="private\n"),
        ]
    )
    with pytest.raises(ValueError):
        with publish_bundle.temporarily_public_repo(runner=runner):
            raise ValueError("body failed")
    # 本体が例外を送出しても finally の復帰 call (public化・復帰・検証) は発行される。
    assert len(runner.calls) == 4
    assert "private" in runner.calls[2]


def test_temporarily_public_repo_reverts_on_keyboardinterrupt():
    runner = _FakeRunner(
        [
            _completed(stdout="private\n"),
            _completed(returncode=0),
            _completed(returncode=0),
            _completed(stdout="private\n"),
        ]
    )
    with pytest.raises(KeyboardInterrupt):
        with publish_bundle.temporarily_public_repo(runner=runner):
            raise KeyboardInterrupt
    # KeyboardInterrupt は BaseException (Exception を継承しない) だが、finally は
    # BaseException でも必ず実行されるため復帰 call が発行される。
    assert len(runner.calls) == 4
    assert "private" in runner.calls[2]


def test_temporarily_public_repo_raises_when_restore_command_fails():
    runner = _FakeRunner(
        [
            _completed(stdout="private\n"),
            _completed(returncode=0),
            _completed(returncode=1, stderr="boom"),  # private への復帰コマンドが失敗
        ]
    )
    with pytest.raises(RuntimeError):
        with publish_bundle.temporarily_public_repo(runner=runner):
            pass


def test_temporarily_public_repo_raises_when_restore_verify_mismatches():
    runner = _FakeRunner(
        [
            _completed(stdout="private\n"),
            _completed(returncode=0),
            _completed(returncode=0),
            _completed(stdout="public\n"),  # 復帰コマンドは成功したが再取得が public のまま
        ]
    )
    with pytest.raises(RuntimeError):
        with publish_bundle.temporarily_public_repo(runner=runner):
            pass


# ── publish_bundle: sync_release(初回/既存の 2 分岐の call 順序) ──
def test_sync_release_first_time_creates_then_uploads():
    runner = _FakeRunner([_completed(returncode=0)] * 3)
    publish_bundle.sync_release(
        tag="offline-bundle-v1",
        head_sha="a" * 40,
        release_exists_flag=False,
        changed=True,
        notes_path=pathlib.Path("notes.md"),
        assets=[pathlib.Path("a"), pathlib.Path("b")],
        runner=runner,
    )
    # 順序: タグ移動(git push) -> release create(gh) -> release upload(gh)。
    assert runner.calls[0][0] == "git"
    assert runner.calls[1][:3] == ["gh", "release", "create"]
    assert runner.calls[2][:3] == ["gh", "release", "upload"]


def test_sync_release_first_time_skips_upload_when_unchanged():
    runner = _FakeRunner([_completed(returncode=0)] * 2)
    publish_bundle.sync_release(
        tag="offline-bundle-v1",
        head_sha="a" * 40,
        release_exists_flag=False,
        changed=False,
        notes_path=pathlib.Path("notes.md"),
        assets=[],
        runner=runner,
    )
    assert len(runner.calls) == 2
    assert runner.calls[0][0] == "git"
    assert runner.calls[1][:3] == ["gh", "release", "create"]


def test_sync_release_existing_uploads_then_moves_tag():
    runner = _FakeRunner([_completed(returncode=0)] * 3)
    publish_bundle.sync_release(
        tag="offline-bundle-v1",
        head_sha="a" * 40,
        release_exists_flag=True,
        changed=True,
        notes_path=pathlib.Path("notes.md"),
        assets=[pathlib.Path("a")],
        runner=runner,
    )
    # 順序: notes 更新(gh) -> release upload(gh, --clobber) -> タグ移動(git push)。
    # アセットを出し切ってからタグを進めることで、upload 途中失敗時はタグが旧コミットの
    # ままとなり、ソースと重量物が旧版どうしで整合する。
    assert runner.calls[0][:3] == ["gh", "release", "edit"]
    assert runner.calls[1][:3] == ["gh", "release", "upload"]
    assert runner.calls[2][0] == "git"


def test_sync_release_existing_skips_upload_when_unchanged():
    runner = _FakeRunner([_completed(returncode=0)] * 2)
    publish_bundle.sync_release(
        tag="offline-bundle-v1",
        head_sha="a" * 40,
        release_exists_flag=True,
        changed=False,
        notes_path=pathlib.Path("notes.md"),
        assets=[],
        runner=runner,
    )
    assert len(runner.calls) == 2
    assert runner.calls[0][:3] == ["gh", "release", "edit"]
    assert runner.calls[1][0] == "git"


# ── publish_bundle: generate_pin(repo_root を実際に使うことの確認) ──
def test_generate_pin_writes_to_repo_root_offline_dir(tmp_path, monkeypatch):
    repo_root = tmp_path
    (repo_root / "offline").mkdir()

    def _fake_download(owner_repo, commit_sha, dest):
        dest.write_bytes(b"fake source zip contents")

    monkeypatch.setattr(publish_bundle, "download_source_zip", _fake_download)

    runner = _FakeRunner(
        [
            _completed(stdout="owner/repo\n"),  # gh_repo_name_with_owner
            _completed(stdout="public\n"),  # gh_repo_visibility (既に public なら復帰不要)
        ]
    )
    pin = publish_bundle.generate_pin(repo_root, "a" * 40, "b" * 64, runner=runner)
    pin_path = repo_root / "offline" / "pinned-release.txt"
    assert pin_path.is_file()
    assert bundle_common.read_pin(pin_path) == pin


# ── publish_bundle: download_source_zip の URL 形固定(I-4・codeload 統一の drift 検査) ──
#
# publish 側 (ここ) は `https://github.com/<owner_repo>/archive/<sha>.zip`、setup 側
# (`setup_offline.default_gh_authenticated_source_zip_download`)は
# `https://codeload.github.com/<owner>/<repo>/zip/<sha>` を叩く。前者は後者への
# リダイレクトを経由する実装(実機で 302 経由の同一バイト列を確認済み)なので両者は同一
# 実体を指すが、URL の綴りは別物である。片側だけ経路が変わると pin の
# source-zip-sha256 が setup 側と恒久的に不一致になる(今回踏んだ「REST API zipball ≠
# codeload」と同型の障害)。ここでは publish 側の URL 形が変わっていないことを固定する。
class _FakeUrlResponse:
    """`urllib.request.urlopen` の戻り値(コンテキストマネージャ)を模擬する。"""

    def __init__(self, data: bytes):
        self._chunks = [data, b""]

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, _n):
        return self._chunks.pop(0) if self._chunks else b""


def test_download_source_zip_uses_github_archive_url_matching_setup_side(monkeypatch, tmp_path):
    captured = {}

    def fake_urlopen(url, timeout=None):
        captured["url"] = url
        return _FakeUrlResponse(b"zip-bytes")

    monkeypatch.setattr(publish_bundle.urllib.request, "urlopen", fake_urlopen)

    dest = tmp_path / "source.zip"
    publish_bundle.download_source_zip("acme/widgets", "c" * 40, dest)

    assert captured["url"] == f"https://github.com/acme/widgets/archive/{'c' * 40}.zip"
    assert dest.read_bytes() == b"zip-bytes"


# ── pip 入口列挙ガード ──
def test_pip_entrypoint_guard_matches_known_set_and_requires_check_requirements():
    found = publish_bundle.find_pip_call_files(REPO_ROOT)
    unknown = found - publish_bundle.KNOWN_PIP_ENTRYPOINTS
    assert not unknown, f"未知の pip 呼び出し箇所 (KNOWN_PIP_ENTRYPOINTS へ追加するか実装を見直す): {unknown}"
    # 実在するファイルはすべて check_requirements の検査を経由すること
    # (.py は識別子 check_requirements、.bat はランチャ名 check-requirements のどちらか)。
    for rel in found:
        path = REPO_ROOT / rel
        text = path.read_text(encoding="utf-8")
        assert publish_bundle.has_check_requirements_marker(text), (
            f"{rel}: check_requirements の呼び出しが見当たらない"
        )


def test_pip_entrypoint_guard_finds_all_existing_known_entrypoints():
    # found ⊆ known だけでは _PIP_CALL_RE が壊れて found が空になっても検出できない。
    # 既知集合のうち実在するファイルは必ず found に入ることも固定する
    # (ci.yml は Task 6 で新設予定のため path.exists() で絞る)。
    found = publish_bundle.find_pip_call_files(REPO_ROOT)
    existing_known = {rel for rel in publish_bundle.KNOWN_PIP_ENTRYPOINTS if (REPO_ROOT / rel).exists()}
    missing = existing_known - found
    assert not missing, f"検出漏れ (走査ロジックの劣化の疑い): {missing}"


def test_pip_entrypoint_guard_detects_publish_bundle_itself():
    # ガード自体が publish_bundle.py の pip download 呼び出しを検出できることの回帰確認
    # (検出ロジックが壊れて何も見つからなくなる = ガードが常に無風で通る、を防ぐ)。
    found = publish_bundle.find_pip_call_files(REPO_ROOT)
    assert "offline/publish_bundle.py" in found


def test_pip_entrypoint_guard_scans_bat_launchers_too():
    # `.bat` を走査対象へ含めないと docs/_build/build_all.bat の直接 pip 呼び出しを
    # 検出できない (未検査の pip 入口が実在するのに無風で通る)。
    found = publish_bundle.find_pip_call_files(REPO_ROOT)
    assert "docs/_build/build_all.bat" in found


# ═══════════════════════════════════════════════════════════════════════════
# offline/setup_offline.py
# ═══════════════════════════════════════════════════════════════════════════


def _make_side_effect_runner(effects):
    """`_FakeRunner` に副作用 (ファイル生成等) を足した簡易版。

    `effects` は `(効果関数 または None, CompletedProcess)` のタプルの列。gh コマンドの
    実行結果として「ファイルが作られる」ところまで模擬したいテスト向け
    (`_FakeRunner` は呼び出し記録と応答返却だけで副作用を持てない)。
    """
    calls: list[list[str]] = []
    remaining = list(effects)

    def runner(cmd, **kwargs):
        calls.append(list(cmd))
        effect, result = remaining.pop(0)
        if effect is not None:
            effect(cmd)
        return result

    runner.calls = calls
    return runner


_DUMMY_PIN = bundle_common.PublishPin(
    source_commit="a" * 40, source_zip_sha256="b" * 64, bundle_sha256="c" * 64
)


# ── _NoAuthRedirectHandler (I-1: Authorization ヘッダのリダイレクト越え転送を防ぐ) ──
#
# `urllib.request.HTTPRedirectHandler.redirect_request` は Content-Length / Content-Type
# は落とすが Authorization はそのまま転送する (requests/urllib3 と違いホスト変更時の除去を
# 行わない。実機の Python 3.13 で確認済み)。codeload が将来 3xx を返す構成へ変わった場合に
# `gh auth token` のトークンが別ホストへ漏れることを防ぐための回帰テスト。
def test_no_auth_redirect_handler_strips_authorization_on_host_change():
    handler = setup_offline._NoAuthRedirectHandler()
    req = urllib.request.Request(
        f"https://codeload.github.com/acme/widgets/zip/{'c' * 40}",
        headers={"Authorization": "token secret"},
    )
    new_req = handler.redirect_request(
        req, None, 302, "Found", {}, "https://objects.githubusercontent.com/elsewhere"
    )
    assert new_req is not None
    assert new_req.get_header("Authorization") is None


def test_no_auth_redirect_handler_keeps_authorization_on_same_host():
    handler = setup_offline._NoAuthRedirectHandler()
    req = urllib.request.Request(
        f"https://codeload.github.com/acme/widgets/zip/{'c' * 40}",
        headers={"Authorization": "token secret"},
    )
    new_req = handler.redirect_request(
        req, None, 302, "Found", {}, "https://codeload.github.com/acme/widgets/zip2"
    )
    assert new_req is not None
    assert new_req.get_header("Authorization") == "token secret"


# ── load_pin_and_public_key (手順1) ──
def test_load_pin_and_public_key_raises_when_pin_missing(tmp_path):
    with pytest.raises(ValueError):
        setup_offline.load_pin_and_public_key(
            pin_path=tmp_path / "pinned-release.txt", public_key_path=tmp_path / "pub.pem"
        )


def test_load_pin_and_public_key_raises_when_public_key_missing(tmp_path):
    pin_path = tmp_path / "pinned-release.txt"
    bundle_common.write_pin(pin_path, _DUMMY_PIN)
    with pytest.raises(RuntimeError):
        setup_offline.load_pin_and_public_key(pin_path=pin_path, public_key_path=tmp_path / "missing.pem")


def test_load_pin_and_public_key_succeeds(tmp_path):
    pin_path = tmp_path / "pinned-release.txt"
    bundle_common.write_pin(pin_path, _DUMMY_PIN)
    pub_path = tmp_path / "pub.pem"
    pub_path.write_bytes(b"dummy-pem")

    pin, pub_bytes = setup_offline.load_pin_and_public_key(pin_path=pin_path, public_key_path=pub_path)
    assert pin == _DUMMY_PIN
    assert pub_bytes == b"dummy-pem"


# ── gh_download_bundle_assets / fetch_bundle_assets (手順2) ──
def _make_bundle_asset_files(dest_dir):
    (dest_dir / publish_bundle.BUNDLE_NAME).write_bytes(b"bundle")
    (dest_dir / f"{publish_bundle.BUNDLE_NAME}.sig").write_text("sig", encoding="ascii")
    (dest_dir / setup_offline.BUNDLE_KEY_NAME).write_text("deadbeef", encoding="ascii")


def test_gh_download_bundle_assets_succeeds_and_creates_files(tmp_path):
    runner = _make_side_effect_runner(
        [(lambda cmd: _make_bundle_asset_files(tmp_path), _completed(returncode=0))]
    )
    ok = setup_offline.gh_download_bundle_assets(
        "offline-bundle-v1", tmp_path, owner="acme", repo="widgets", runner=runner
    )
    assert ok is True
    assert "release" in runner.calls[0] and "download" in runner.calls[0]
    # M-1: cwd の git remote 推測に依存せず、常に対象リポジトリを明示する。
    assert "--repo" in runner.calls[0]
    assert "acme/widgets" in runner.calls[0]
    # bundle.key もパターンに含める(I-3: 内容キー照合に使う)。
    assert setup_offline.BUNDLE_KEY_NAME in runner.calls[0]


def test_gh_download_bundle_assets_fails_when_command_fails(tmp_path):
    runner = _FakeRunner([_completed(returncode=1, stderr="not authenticated")])
    ok = setup_offline.gh_download_bundle_assets("offline-bundle-v1", tmp_path, runner=runner)
    assert ok is False


def test_gh_download_bundle_assets_fails_when_bundle_key_missing(tmp_path):
    # gh コマンド自体は成功でも bundle.key が来ていなければ失敗扱い(I-3 の前提)。
    def make_partial_files(cmd):
        (tmp_path / publish_bundle.BUNDLE_NAME).write_bytes(b"bundle")
        (tmp_path / f"{publish_bundle.BUNDLE_NAME}.sig").write_text("sig", encoding="ascii")

    runner = _make_side_effect_runner([(make_partial_files, _completed(returncode=0))])
    ok = setup_offline.gh_download_bundle_assets("offline-bundle-v1", tmp_path, runner=runner)
    assert ok is False


def test_fetch_bundle_assets_uses_gh_when_available_and_skips_http(tmp_path):
    runner = _make_side_effect_runner(
        [(lambda cmd: _make_bundle_asset_files(tmp_path), _completed(returncode=0))]
    )
    http_calls = []
    bundle_path, sig_path, key_path = setup_offline.fetch_bundle_assets(
        "offline-bundle-v1", tmp_path, runner=runner, http_download=lambda url, dest: http_calls.append(url)
    )
    assert bundle_path.is_file() and sig_path.is_file() and key_path.is_file()
    assert http_calls == []


def test_fetch_bundle_assets_falls_back_to_http_when_gh_unavailable(tmp_path):
    runner = _FakeRunner([_completed(returncode=1, stderr="not authenticated")])
    http_calls = []

    def fake_http(url, dest):
        http_calls.append(url)
        dest.write_bytes(b"x")

    bundle_path, sig_path, key_path = setup_offline.fetch_bundle_assets(
        "offline-bundle-v1", tmp_path, owner="acme", repo="widgets", runner=runner, http_download=fake_http
    )
    assert bundle_path.is_file() and sig_path.is_file() and key_path.is_file()
    assert len(http_calls) == 3
    assert all("acme/widgets" in u and "offline-bundle-v1" in u for u in http_calls)
    assert any(u.endswith(setup_offline.BUNDLE_KEY_NAME) for u in http_calls)


def test_fetch_bundle_assets_raises_when_both_paths_fail(tmp_path):
    runner = _FakeRunner([_completed(returncode=1, stderr="boom")])

    def failing_http(url, dest):
        raise OSError("network down")

    with pytest.raises(RuntimeError):
        setup_offline.fetch_bundle_assets("offline-bundle-v1", tmp_path, runner=runner, http_download=failing_http)


# ── verify_bundle_sha256 (手順3・主アンカー) ──
def test_verify_bundle_sha256_passes_on_match(tmp_path):
    bundle_path = tmp_path / "bundle.tar.gz"
    bundle_path.write_bytes(b"hello")
    digest = hashlib.sha256(b"hello").hexdigest()
    pin = bundle_common.PublishPin(source_commit="a" * 40, source_zip_sha256="b" * 64, bundle_sha256=digest)
    setup_offline.verify_bundle_sha256(bundle_path, pin)  # 例外が出ないこと


def test_verify_bundle_sha256_raises_on_mismatch(tmp_path):
    bundle_path = tmp_path / "bundle.tar.gz"
    bundle_path.write_bytes(b"hello")
    pin = bundle_common.PublishPin(source_commit="a" * 40, source_zip_sha256="b" * 64, bundle_sha256="0" * 64)
    with pytest.raises(RuntimeError):
        setup_offline.verify_bundle_sha256(bundle_path, pin)


# ── extract_bundle / remove_extracted_bundle (手順4) ──
def _make_bundle_tar(tmp_path, *, include_vendor=True):
    stage = tmp_path / "stage"
    wheelhouse = stage / publish_bundle.WHEELHOUSE_DIR_NAME
    wheelhouse.mkdir(parents=True)
    (wheelhouse / "dummy.whl").write_bytes(b"x")
    if include_vendor:
        vendor = stage / "docs" / "_build" / "vendor"
        vendor.mkdir(parents=True)
        (vendor / "manifest.txt").write_text("v1\n", encoding="utf-8")
        (vendor / "mermaid.min.js").write_bytes(b"x")
        (vendor / "mermaid-layout-elk.min.js").write_bytes(b"x")
    tar_path = tmp_path / publish_bundle.BUNDLE_NAME
    with tarfile.open(tar_path, "w:gz") as tf:
        tf.add(wheelhouse, arcname=publish_bundle.WHEELHOUSE_DIR_NAME)
        if include_vendor:
            tf.add(stage / "docs", arcname="docs")
    return tar_path


def test_extract_bundle_creates_wheelhouse_and_vendor(tmp_path):
    tar_path = _make_bundle_tar(tmp_path)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    setup_offline.extract_bundle(tar_path, repo_root)
    assert (repo_root / publish_bundle.WHEELHOUSE_DIR_NAME / "dummy.whl").is_file()
    assert (repo_root / "docs" / "_build" / "vendor" / "manifest.txt").is_file()


def test_extract_bundle_raises_when_vendor_assets_missing(tmp_path):
    tar_path = _make_bundle_tar(tmp_path, include_vendor=False)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    with pytest.raises(RuntimeError):
        setup_offline.extract_bundle(tar_path, repo_root)


def test_remove_extracted_bundle_deletes_wheelhouse_and_vendor_js_but_keeps_manifest(tmp_path):
    repo_root = tmp_path
    wheelhouse = repo_root / publish_bundle.WHEELHOUSE_DIR_NAME
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


# ── build_pip_install_command / install_cryptography_from_wheelhouse (手順5) ──
def test_build_pip_install_command_uses_no_index_and_find_links(tmp_path):
    cmd = setup_offline.build_pip_install_command(
        [sys.executable], tmp_path / "python-wheelhouse", tmp_path / "offline" / "dev-requirements.txt"
    )
    assert "--no-index" in cmd
    assert "--find-links" in cmd
    assert str(tmp_path / "python-wheelhouse") in cmd
    assert "-r" in cmd
    assert str(tmp_path / "offline" / "dev-requirements.txt") in cmd


# ── verify_bundle_signature_or_cleanup (手順6・多層防御) ──
def test_verify_bundle_signature_or_cleanup_passes_with_matching_key(tmp_path):
    bundle_path = tmp_path / "bundle.tar.gz"
    bundle_path.write_bytes(b"bundle-bytes")
    sig_path = tmp_path / f"{publish_bundle.BUNDLE_NAME}.sig"
    private_pem, public_pem = bundle_common.generate_signing_key_pair()
    sig_path.write_text(bundle_common.sign_bytes(bundle_path.read_bytes(), private_pem), encoding="ascii")

    # 例外が出ないことの確認 (削除対象の展開物が無くても問題なく通ること)。
    setup_offline.verify_bundle_signature_or_cleanup(bundle_path, sig_path, public_pem, repo_root=tmp_path)


def test_verify_bundle_signature_or_cleanup_removes_extracted_content_on_failure(tmp_path):
    repo_root = tmp_path
    wheelhouse = repo_root / publish_bundle.WHEELHOUSE_DIR_NAME
    wheelhouse.mkdir()
    (wheelhouse / "dummy.whl").write_bytes(b"x")
    vendor = repo_root / "docs" / "_build" / "vendor"
    vendor.mkdir(parents=True)
    (vendor / "mermaid.min.js").write_bytes(b"x")
    (vendor / "manifest.txt").write_text("v1\n", encoding="utf-8")

    bundle_path = repo_root / "bundle.tar.gz"
    bundle_path.write_bytes(b"bundle-bytes")
    sig_path = repo_root / f"{publish_bundle.BUNDLE_NAME}.sig"
    private_pem, _correct_public_pem = bundle_common.generate_signing_key_pair()
    _other_private_pem, wrong_public_pem = bundle_common.generate_signing_key_pair()
    sig_path.write_text(bundle_common.sign_bytes(bundle_path.read_bytes(), private_pem), encoding="ascii")

    with pytest.raises(RuntimeError):
        setup_offline.verify_bundle_signature_or_cleanup(
            bundle_path, sig_path, wrong_public_pem, repo_root=repo_root
        )

    assert not wheelhouse.exists()
    assert not (vendor / "mermaid.min.js").exists()
    assert (vendor / "manifest.txt").is_file()


def test_verify_bundle_signature_or_cleanup_raises_on_missing_sig_file(tmp_path):
    # M-2: .sig 欠落を FileNotFoundError のまま __main__ の捕捉外へ漏らさず、
    # RuntimeError(fail closed の契約内)として入口で拒否する。
    bundle_path = tmp_path / "bundle.tar.gz"
    bundle_path.write_bytes(b"bundle-bytes")
    missing_sig_path = tmp_path / "does-not-exist.sig"
    _private_pem, public_pem = bundle_common.generate_signing_key_pair()

    with pytest.raises(RuntimeError):
        setup_offline.verify_bundle_signature_or_cleanup(
            bundle_path, missing_sig_path, public_pem, repo_root=tmp_path
        )


# ── verify_local_checkout_matches_bundle_key (手順4付随・I-3) ──
def test_verify_local_checkout_matches_bundle_key_passes_on_match(tmp_path, monkeypatch):
    monkeypatch.setattr(bundle_common, "compute_content_key", lambda repo_root: "same-key")
    key_path = tmp_path / "bundle.key"
    key_path.write_text("same-key", encoding="ascii")

    # 例外が出ないことの確認。
    setup_offline.verify_local_checkout_matches_bundle_key(key_path, repo_root=tmp_path)


def test_verify_local_checkout_matches_bundle_key_raises_and_cleans_up_on_mismatch(tmp_path, monkeypatch):
    repo_root = tmp_path
    wheelhouse = repo_root / publish_bundle.WHEELHOUSE_DIR_NAME
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


# ── gh_auth_token / default_gh_authenticated_source_zip_download (手順7・追加確認) ──
#
# GitHub REST API の zipball エンドポイント (`gh api repos/.../zipball/<sha>`) は
# codeload.github.com とは別経路で、生成される zip がバイト単位で一致しない
# (実機確認: 同一コミットで sha256 が食い違った)。pin の source-zip-sha256 は
# publish 側が codeload から取得した値なので、setup 側も同じ codeload の URL を
# `gh auth token` のトークンを Authorization ヘッダへ載せて直接叩く。
def test_gh_auth_token_returns_token_on_success():
    runner = _FakeRunner([_completed(stdout="ghp_dummytoken\n")])
    token = setup_offline.gh_auth_token(runner=runner)
    assert token == "ghp_dummytoken"
    assert runner.calls[0] == ["gh", "auth", "token"]


def test_gh_auth_token_returns_none_on_failure():
    runner = _FakeRunner([_completed(returncode=1, stderr="not logged in")])
    assert setup_offline.gh_auth_token(runner=runner) is None


def test_default_gh_authenticated_source_zip_download_returns_false_without_token(tmp_path):
    runner = _FakeRunner([_completed(returncode=1, stderr="not logged in")])
    dest = tmp_path / "source.zip"
    ok = setup_offline.default_gh_authenticated_source_zip_download(
        "acme", "widgets", "c" * 40, dest, runner=runner
    )
    assert ok is False
    assert not dest.exists()


def test_default_gh_authenticated_source_zip_download_uses_codeload_with_auth_header(tmp_path, monkeypatch):
    # このテストの核心: gh api の zipball エンドポイントではなく codeload.github.com を
    # Authorization ヘッダ付きで直接叩くこと (実装が REST API 経路へ戻ったら赤くなる)。
    captured = {}

    def fake_http_download(url, dest, *, timeout, max_bytes, headers=None):
        captured["url"] = url
        captured["headers"] = headers
        dest.write_bytes(b"zip-bytes-from-codeload")

    monkeypatch.setattr(setup_offline, "_http_download", fake_http_download)
    runner = _FakeRunner([_completed(stdout="ghp_dummytoken\n")])

    dest = tmp_path / "source.zip"
    ok = setup_offline.default_gh_authenticated_source_zip_download(
        "acme", "widgets", "c" * 40, dest, runner=runner
    )

    assert ok is True
    assert captured["url"] == f"https://codeload.github.com/acme/widgets/zip/{'c' * 40}"
    assert captured["headers"] == {"Authorization": "token ghp_dummytoken"}
    assert dest.read_bytes() == b"zip-bytes-from-codeload"


def test_default_gh_authenticated_source_zip_download_reports_distinct_reason_after_token(
    tmp_path, monkeypatch, capsys
):
    # M-3: token 取得に成功した後で取得自体が失敗した場合、この関数は False を返すだけだが
    # (呼び出し側 verify_source_zip_sha256 はこの後「未認証等」と一般化して表示する)、
    # 実際には未認証ではないので、ここで真の理由を先に出力し「未認証」と誤解させない。
    def failing_http_download(url, dest, *, timeout, max_bytes, headers=None):
        raise OSError("network down")

    monkeypatch.setattr(setup_offline, "_http_download", failing_http_download)
    runner = _FakeRunner([_completed(stdout="ghp_dummytoken\n")])

    dest = tmp_path / "source.zip"
    ok = setup_offline.default_gh_authenticated_source_zip_download(
        "acme", "widgets", "c" * 40, dest, runner=runner
    )

    assert ok is False
    assert not dest.exists()
    out = capsys.readouterr().out
    assert "認証済み" in out
    assert "ghp_dummytoken" not in out  # トークン値は出力しない


def test_verify_source_zip_sha256_passes_via_gh_without_http_fallback(tmp_path):
    content = b"source-zip-bytes"
    digest = hashlib.sha256(content).hexdigest()
    pin = bundle_common.PublishPin(source_commit="a" * 40, source_zip_sha256=digest, bundle_sha256="b" * 64)

    def fake_gh_download(owner, repo, commit_sha, dest):
        dest.write_bytes(content)
        return True

    setup_offline.verify_source_zip_sha256(
        pin,
        gh_download=fake_gh_download,
        http_download=lambda url, dest: pytest.fail("gh が成功したので http は呼ばれないはず"),
    )


def test_verify_source_zip_sha256_falls_back_to_http_and_raises_on_mismatch(tmp_path):
    pin = bundle_common.PublishPin(source_commit="a" * 40, source_zip_sha256="0" * 64, bundle_sha256="b" * 64)

    def fake_gh_download(owner, repo, commit_sha, dest):
        return False

    def fake_http(url, dest):
        dest.write_bytes(b"different-bytes")

    with pytest.raises(RuntimeError):
        setup_offline.verify_source_zip_sha256(pin, gh_download=fake_gh_download, http_download=fake_http)


def test_verify_source_zip_sha256_passes_via_http_fallback(tmp_path):
    content = b"source-zip-bytes-via-http"
    digest = hashlib.sha256(content).hexdigest()
    pin = bundle_common.PublishPin(source_commit="a" * 40, source_zip_sha256=digest, bundle_sha256="b" * 64)

    def fake_gh_download(owner, repo, commit_sha, dest):
        return False

    def fake_http(url, dest):
        dest.write_bytes(content)

    setup_offline.verify_source_zip_sha256(pin, gh_download=fake_gh_download, http_download=fake_http)


# ── main: ブートストラップ順序の固定 (手順3の sha256 照合が手順5の cryptography 導入より前) ──
def test_main_runs_bootstrap_steps_in_correct_order(monkeypatch, tmp_path):
    calls: list[str] = []

    def fake_load_pin(**kwargs):
        calls.append("load_pin")
        return _DUMMY_PIN, b"dummy-pubkey"

    def fake_fetch(tag, dest_dir, **kwargs):
        calls.append("fetch")
        return tmp_path / "bundle.tar.gz", tmp_path / "bundle.tar.gz.sig", tmp_path / "bundle.key"

    def fake_verify_sha256(bundle_path, pin):
        calls.append("verify_sha256")

    def fake_extract(bundle_path, repo_root=None):
        calls.append("extract")

    def fake_verify_content_key(key_path, repo_root=None):
        calls.append("verify_content_key")

    def fake_install_crypto(repo_root=None, **kwargs):
        calls.append("install_crypto")

    def fake_verify_sig(bundle_path, sig_path, public_key_pem, **kwargs):
        calls.append("verify_signature")

    def fake_verify_source_zip(pin, **kwargs):
        calls.append("verify_source_zip")

    monkeypatch.setattr(setup_offline, "load_pin_and_public_key", fake_load_pin)
    monkeypatch.setattr(setup_offline, "fetch_bundle_assets", fake_fetch)
    monkeypatch.setattr(setup_offline, "verify_bundle_sha256", fake_verify_sha256)
    monkeypatch.setattr(setup_offline, "extract_bundle", fake_extract)
    monkeypatch.setattr(
        setup_offline, "verify_local_checkout_matches_bundle_key", fake_verify_content_key
    )
    monkeypatch.setattr(setup_offline, "install_cryptography_from_wheelhouse", fake_install_crypto)
    monkeypatch.setattr(setup_offline, "verify_bundle_signature_or_cleanup", fake_verify_sig)
    monkeypatch.setattr(setup_offline, "verify_source_zip_sha256", fake_verify_source_zip)

    rc = setup_offline.main([])

    assert rc == 0
    assert calls == [
        "load_pin",
        "fetch",
        "verify_sha256",
        "extract",
        "verify_content_key",
        "install_crypto",
        "verify_signature",
        "verify_source_zip",
    ]
    # 主張の核心: sha256 照合 (手順3) が cryptography 導入 (手順5) より前に行われる。
    assert calls.index("verify_sha256") < calls.index("install_crypto")
    assert calls.index("install_crypto") < calls.index("verify_signature")
    # I-3: 内容キー照合(bundle.key)は展開の直後・cryptography 導入より前に行う
    # (照合自体が hashlib だけで完結するため、鶏卵回避の制約に触れずここへ置ける)。
    assert calls.index("extract") < calls.index("verify_content_key") < calls.index("install_crypto")


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
def test_main_always_returns_zero_even_when_steps_fail(monkeypatch):
    monkeypatch.setattr(post_commit, "auto_push", lambda: None)
    monkeypatch.setattr(post_commit, "publish_tag_only", lambda: None)
    assert post_commit.main() == 0
