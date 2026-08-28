"""並行実装の drift 検出 — graph-editor `app.py` ⇔ pdf-to-svg `src/web/` + `src/app.py`。

2 つのローカル HTTP サーバは同一仕様の並行実装で、両プロジェクトの設計正典に「片方を変えたら
必ず両方」と書いてある。それでも**片側だけの変更は実際に起きた**: 接続の資源上限
(`REQUEST_TIMEOUT` / `MAX_CONNECTIONS` / linger 期限) は pdf-to-svg にだけ入り、Edge の
verbose ログ既定 OFF は graph-editor にだけ入った。申し送りではなく機械で落とすのが本ファイル
の役目である。

主張の形は**「同じ名前の定数が両方にあり、値が一致する」**。片方を変えれば必ず落ちるので、
「揃え忘れ」ではなく「揃えるか、揃えない理由を書いてこの表を直すか」の二択になる。
`SECURITY_HEADERS` と `TOKEN_*` だけでは上記 2 件を取りこぼすため、判定表・接続の資源上限・
Edge 起動引数まで比較対象に含める。**新しい共有の決めごとを
足したら、この表にも足すこと。**

同じ主張を pdf-to-svg 側 (`test/test_parallel_impl_drift.py`) にも置いてある。CI は
`pnpm run ci:pdf-to-svg` / `ci:graph-editor` のように片側だけ走ることがあり、検査が片側に
しか無いと「変えた側の CI では落ちない」= drift を検出できないためで、この複製は
意図的である。

`import app` に副作用は無い (同梱資産の読み込みは `main()`/初回 GET の遅延読込。
`main()` は呼ばない)。
"""
from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import re
import sys
from pathlib import Path

import app
import pytest

GRAPH_EDITOR_DIR = Path(__file__).resolve().parents[1]
PDF_TO_SVG_DIR = Path(__file__).resolve().parents[2] / "pdf-to-svg"
PDF_TO_SVG_SRC = PDF_TO_SVG_DIR / "src"

# 依存欠けで drift 検査を降りるための明示的なスイッチ。既定では降りない (下の `_pdf_to_svg`)。
ALLOW_MISSING_DEPS_ENV = "DRIFT_ALLOW_MISSING_DEPS"


def _pdf_to_svg(dotted: str, alias: str | None = None):
    """相手側のモジュールを読み込む。同居していない配布形態では skip する。

    `alias` を渡すとその名前で読み込む。pdf-to-svg 側にも `app.py` があり、素の名前で
    import すると**こちらの `app` を上書きしてしまう**ので、トップレベルの `app` だけは
    必ず別名で読むこと。`sys.path` への追加は読み込みの間だけに限る (居座らせると以降の
    `import` が相手側を拾う)。
    """
    if not (PDF_TO_SVG_SRC / "web" / "origin_guard.py").exists():
        pytest.skip("pdf-to-svg のソースが同居していない")
    if alias is not None and alias in sys.modules:
        return sys.modules[alias]
    sys.path.insert(0, str(PDF_TO_SVG_SRC))
    try:
        if alias is None:
            return importlib.import_module(dotted)
        spec = importlib.util.spec_from_file_location(
            alias, PDF_TO_SVG_SRC / (dotted.replace(".", "/") + ".py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[alias] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(alias, None)  # 半端な module を残さない
            raise
        return module
    except ImportError as exc:  # 相手側の依存 (PyMuPDF 等) が入っていない環境
        # 依存欠けを黙って skip すると、**drift 検査そのものが緑のまま消える**。ソースが
        # 同居している以上、import できないのは環境整備の不足であって検査を諦める理由には
        # ならないので、既定では失敗させる。相手側の依存を入れられない環境だけが環境変数で
        # 明示的に降りられる (降りたことは skip の理由として画面に出る)。
        if os.environ.get(ALLOW_MISSING_DEPS_ENV) == "1":
            pytest.skip(f"{ALLOW_MISSING_DEPS_ENV}=1 のため drift 検査を降りる: {exc}")
        pytest.fail(
            f"pdf-to-svg を import できないため drift を検査できない: {exc}\n"
            f"  pdf-to-svg の依存を入れて再実行するか、{ALLOW_MISSING_DEPS_ENV}=1 で"
            "明示的に降りること (黙って skip はしない)。")
    finally:
        sys.path.remove(str(PDF_TO_SVG_SRC))


def _js_escape_map(js_path: Path, func_name: str) -> dict:
    """`func_name` 関数の本体から HTML エスケープの置換表 (1 文字 → 置換後文字列) を抽出する。

    JS を実行せずソーステキストを読むだけなので、`function` 宣言と内側のアロー関数呼び出しの
    どちらでも (= 体裁が両側で違っても) 実際に使われる置換ペアだけを比較できる。波括弧の対応を
    数えて関数本体を切り出し、その中の `"x": "y"` 形の対だけを拾う。
    """
    text = js_path.read_text(encoding="utf-8")
    start = text.index(f"function {func_name}(")
    body_start = text.index("{", start)
    depth = 0
    body_end = None
    for i in range(body_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                body_end = i
                break
    assert body_end is not None, f"{func_name} の閉じ括弧が見つからない"
    body = text[body_start:body_end]
    pairs = re.findall(r'''(["'])(.)\1\s*:\s*(["'])((?:\\.|[^"'\\])*)\3''', body)
    return {key: value for _q1, key, _q2, value in pairs}


# ── HTML エスケープ (JS 並行実装) ──


def test_html_escape_map_matches():
    """graph-editor `utils.js` の `escapeHtml` と pdf-to-svg `dom.js` の `esc` が
    同じ置換表を持つこと。

    `'` の抜けは (属性が二重引用符で書かれる限り) 表示上の破綻を起こさないが、片方だけ
    抜けたまま気付かれない形こそが並行実装の drift そのものなので、逐語比較で機械的に塞ぐ。
    """
    if not PDF_TO_SVG_DIR.exists():
        pytest.skip("pdf-to-svg のソースが同居していない")
    ge_map = _js_escape_map(
        GRAPH_EDITOR_DIR / "resources" / "web" / "js" / "utils.js", "escapeHtml")
    pdf_map = _js_escape_map(PDF_TO_SVG_DIR / "resources" / "web" / "dom.js", "esc")
    assert ge_map == pdf_map
    assert ge_map == {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}


# ── 認可・防御ヘッダ ──


def test_security_headers_and_token_transport_match():
    """防御ヘッダとセッショントークンの運び方が**逐語で一致**すること。

    `SECURITY_HEADERS` は 1 応答でも欠ければ frame 化の足がかりになる性質のもので、
    片側だけ緩めると「片方のアプリだけ守られていない」状態が黙って成立する。"""
    guard = _pdf_to_svg("web.origin_guard")
    assert app.SECURITY_HEADERS == guard.SECURITY_HEADERS
    assert app.TOKEN_HEADER == guard.TOKEN_HEADER
    assert app.TOKEN_QUERY == guard.TOKEN_QUERY


def test_security_headers_are_attached_at_end_headers_on_both_sides():
    """付与の**やり方**まで一致すること (値の一致だけでは足りない)。

    値が同じでも「どこで載せるか」が違えば、片側だけ抜ける応答が生まれる。実際、両側とも
    自分で書いた送信経路 (`_send` / `_reject`) からの明示呼び出しだった頃は、基底クラスが
    直接返す応答 (`HEAD` → 501、長すぎるリクエスト行 → 414、その他 `send_error()`) に
    ヘッダが載っていなかった。**両側に同じ穴があったので値の照合では検出できない** —
    このテストはその形の drift を狙う。

    主張は「`end_headers()` を override して 1 応答 1 回だけ載せる」形であること。
    """
    guard = _pdf_to_svg("web.origin_guard")
    # クラス名は両側で揃っていない(graph-editor=`GuardedHandler` /
    # pdf-to-svg=`GuardedHTTPRequestHandler`)。揃えるべきは名前ではなく**付与のやり方**なので、
    # それぞれの基底ハンドラを名指しで取る。
    for mod, handler in (
        (app, app.GuardedHandler),
        (guard, guard.GuardedHTTPRequestHandler),
    ):
        # 基底のままではない = override している。
        assert "end_headers" in vars(handler), mod.__name__
        # 二重付与ガードのために応答の開始点も押さえている。
        assert "send_response_only" in vars(handler), mod.__name__


def test_session_token_is_minted_and_compared_the_same_way():
    """セッショントークンの**作り方と突き合わせ方**が一致すること。

    値ではなく手段の一致を見る。片側だけ `secrets.token_urlsafe(16)` へ縮めたり、
    `hmac.compare_digest` を素の `==` へ戻したりしても、`TOKEN_HEADER` / `TOKEN_QUERY` の
    照合(運び方の検査)は通ってしまう。前者は総当たりの現実味を、後者は一致した接頭辞の
    長さに比例する所要時間のオラクルを、片側にだけ作る。
    """
    guard = _pdf_to_svg("web.origin_guard")
    for mint in (app._new_session_token, guard.new_session_token):
        assert "secrets.token_urlsafe(32)" in inspect.getsource(mint)
        # 32 バイトの URL 安全表現は 43 文字。桁数でも実物を押さえる。
        assert len(mint()) >= 43
    for reason in (app.GuardedHandler._token_reason, guard.GuardedHTTPRequestHandler._token_reason):
        assert "hmac.compare_digest" in inspect.getsource(reason)


def test_guard_decision_table_matches():
    """判定表 (許可 Content-Type・Origin 不要メソッド) とログ・読み捨ての上限が一致すること。"""
    guard = _pdf_to_svg("web.origin_guard")
    assert app.ALLOWED_REQUEST_CONTENT_TYPES == guard.ALLOWED_REQUEST_CONTENT_TYPES
    assert app.SAFE_METHODS == guard.SAFE_METHODS
    assert app.REJECT_LOG_LIMIT == guard.REJECT_LOG_LIMIT
    assert app._DRAIN_LIMIT == guard._DRAIN_LIMIT


# ── 接続の資源上限 ──


def test_connection_resource_limits_match():
    """接続の資源上限が一致すること (今回の drift の本体)。

    - `REQUEST_TIMEOUT`: 無言の接続はガードに届かないので、ハンドラ側の期限だけが閉じられる。
    - `MAX_CONNECTIONS`: `ThreadingHTTPServer` は接続ごとに無制限にスレッドを起こす。
    - `_LINGER_TIMEOUT`: 拒否後の読み捨ての期限。**接続単位**で持つこと自体が仕様の一部で、
      per-recv に戻すと少しずつ送り続ける相手にスレッドを握られる (値の一致だけでは
      その退行を捕まえられないので、挙動は各プロジェクトのガードテストが持つ)。
    """
    server = _pdf_to_svg("web.server")
    guard = _pdf_to_svg("web.origin_guard")
    assert app.REQUEST_TIMEOUT == server.REQUEST_TIMEOUT
    assert app.MAX_CONNECTIONS == server.MAX_CONNECTIONS
    assert app._LINGER_TIMEOUT == guard._LINGER_TIMEOUT
    # 要求単位の絶対期限。per-recv タイムアウトを接続 (要求) 単位へ引き上げた本体で、
    # 片側だけ緩めると「ドリップに弱いのは片方だけ」の drift が黙って成立する。
    assert app.MAX_REQUEST_SECONDS == guard.MAX_REQUEST_SECONDS
    # 定数を宣言しただけで配線し忘れる形 (`timeout` 未設定) をここで落とす。
    assert app.Handler.timeout == server.Handler.timeout == app.REQUEST_TIMEOUT


# ── Edge の起動引数 ──


def test_edge_launch_args_match_and_carry_no_logging_flags_by_default():
    """Edge 起動引数が一致し、**既定では logging 系フラグが 1 つも載らない**こと。

    verbose ログは `--app=` の URL (= セッショントークン) を書き込みうるうえ、既定プロファイル
    で開く設計上その記録は利用者の Edge セッション全体に及ぶ。既定 OFF が片側だけになると、
    その片側だけがトークンをディスクへ落とす可能性を抱え続ける。
    `--user-data-dir` / `--disable-gpu` は付けない (両正典の却下集)。どちらのプロジェクトでも
    どの経路でも付かないことを併せて固定する。
    """
    other = _pdf_to_svg("app", alias="pdftosvg_app")
    url = "http://127.0.0.1:5179/?token=SECRET-TOKEN"

    ours, theirs = app._edge_launch_args("msedge.exe", url), other._edge_launch_args(
        "msedge.exe", url)
    assert ours == theirs
    for flag in ("--enable-logging", "--log-file", "--v=", "--user-data-dir", "--disable-gpu"):
        assert flag not in " ".join(theirs)

    # opt-in 時に足す 3 フラグの並びも揃える (片側だけ `--v=2` 等になると診断の量が食い違う)。
    opted_in = app._edge_launch_args("msedge.exe", url, "L.log")
    assert opted_in == other._edge_launch_args("msedge.exe", url, "L.log")
    assert opted_in[-3:] == ["--enable-logging", "--log-file=L.log", "--v=1"]

    # ログの保持上限・ファイル名・環境変数の読み方も同一 (環境変数**名**だけがプロジェクト固有)。
    assert app.EDGE_LOG_MAX_BYTES == other.EDGE_LOG_MAX_BYTES
    assert app.EDGE_LOG_NAME == other.EDGE_LOG_NAME
    # 有効判定の許可集合 (真値リテラル)。片側だけ広げると、片方の配布物だけ未知の綴りで
    # 診断ログ (= トークン漏えい面) が開いてしまう。
    assert app._TRUTHY_ENV_VALUES == other._TRUTHY_ENV_VALUES
    assert app.EDGE_LOG_ENV != other.EDGE_LOG_ENV


# ── 可変状態の置き場 ──


def test_mutable_state_stays_out_of_the_program_directory(monkeypatch, tmp_path):
    """可変状態の置き場の決定が両実装で揃っていること。

    exe を共有フォルダ・ネットワークドライブへ置く配布で可変状態 (診断ログ等) を exe 隣へ
    書くと、複数人の同時起動が `startup.log` を共同追記して記録が混ざるうえ、プログラム
    フォルダの書き込み可能要件が DLL 差し替え (CWE-427) の温床になる。両実装とも frozen 時は
    ユーザー専用領域 (`%LOCALAPPDATA%/<App>/data`) を最優先し、書けない端末だけ exe 隣へ
    落とす。graph-editor に可搬インストール継続マーカー (pdf-to-svg の `dictionary.json`
    判定) が無いのは、失って困る利用者データを持たない (診断ログのみ) ための**意図した差分**。
    """
    config = _pdf_to_svg("config", alias="pdftosvg_config")
    local = tmp_path / "LocalAppData"
    exe_dir = tmp_path / "exe"
    exe_dir.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.delenv(config.ENV_DATA_DIR, raising=False)
    monkeypatch.delenv(app.DATA_DIR_ENV, raising=False)

    monkeypatch.setattr(app, "_is_frozen", lambda: True)
    monkeypatch.setattr(app, "_app_base_dir", lambda: str(exe_dir))
    assert Path(app._data_dir()) == local / "LabelEditor" / "data"

    monkeypatch.setattr(config, "is_frozen", lambda: True)
    monkeypatch.setattr(config, "app_base_dir", lambda: exe_dir)
    assert config._resolve_data_dir() == local / "PdfToSvg" / "data"

    # 明示指定の環境変数は**名前だけ**がプロジェクト固有 (Edge ログ env と同じ運用)。
    assert config.ENV_DATA_DIR != app.DATA_DIR_ENV
    # どちらも exe 隣には何も作っていない (ユーザー領域が使える限り触らない)。
    assert not (exe_dir / "data").exists()
