"""アプリ全体のパス解決・設定。

PyInstaller でバンドルした場合 (`sys._MEIPASS` / `sys.executable`) と、ソース実行時の
双方でリソース/データのパスを正しく解決する。

データ (辞書・設定・ログ・一時領域) の置き場は `data_dir()` を見よ。**配布 exe では
ユーザー専用領域を既定**とし、可変状態をプログラムフォルダから出す (判断理由も同関数)。
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path


def is_frozen() -> bool:
    """PyInstaller でバンドルされた実行ファイルから起動されているか。"""
    return getattr(sys, "frozen", False)


def app_base_dir() -> Path:
    """アプリの基準フォルダ (データを置く場所の親)。

    - frozen 時: 実行ファイル (`PdfToSvg.exe`) のあるフォルダ
      (onedir はそこに、onefile でも展開先 temp ではなく永続フォルダになる)
    - ソース実行時: リポジトリ直下
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_dir() -> Path:
    """同梱リソース (icons / fonts 等) のルート。

    - frozen 時: ``sys._MEIPASS/resources`` (spec の datas が ``resources`` 配下へ展開)
    - ソース実行時: リポジトリ直下の ``resources/``
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS")) / "resources"
    return Path(__file__).resolve().parents[1] / "resources"


def resource_path(*parts: str) -> Path:
    return resource_dir().joinpath(*parts)


def font_dir() -> Path:
    """同梱フォントのルート (本プロジェクト配下の ``fonts/``)。

    BIZ UDPGothic (TTF) / Noto Serif JP を pdf-to-svg 専用に同梱する置き場
    (pie-chart は同ファミリの WOFF2 を自プロジェクト配下に別途持つ)。
    - frozen 時: ``_MEIPASS/fonts`` (spec の datas が ``fonts`` 配下へ展開)
    - ソース実行時: リポジトリ root (pdf-to-svg/) の ``fonts/``
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS")) / "fonts"
    return Path(__file__).resolve().parents[1] / "fonts"


def font_path(*parts: str) -> Path:
    return font_dir().joinpath(*parts)


# 可変状態の置き場を明示指定する環境変数。可搬運用 (USB・共有フォルダから持ち歩く)
# と検証で使う。指定した人が置き場の権限に責任を持つ、という意味でもある。
ENV_DATA_DIR = "PDFTOSVG_DATA_DIR"

# ユーザー専用領域に作るフォルダ名 (``%LOCALAPPDATA%/PdfToSvg/data``)。
_USER_DIR_NAME = "PdfToSvg"

# 解決済みの可変状態フォルダ (書き込み可否の実地確認を毎回やらないための記憶)。
_resolved_data_dir: "Path | None" = None


def _is_writable_dir(path: Path) -> bool:
    """作成できて実際に書けるフォルダか (**実書き込みで**確かめる)。

    VDI ではプロファイル配下でも書き込みが弾かれることがあり、`os.access` の申告や
    存在確認では判定にならない。プローブファイルを作って消すところまでやる。
    """
    probe = path / ".write-probe"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text("", encoding="utf-8")
    except OSError:
        return False
    finally:
        try:
            probe.unlink()
        except OSError:
            pass
    return True


def _portable_dictionary_present(portable: Path) -> bool:
    """exe 隣に可搬インストールの辞書実体があるか (OSError を「無い」と混同しない)。

    `Path.exists()` は Windows でドライブ未接続・共有瞬断系の OSError を握りつぶして
    False を返す。ネットワークドライブ上の可搬インストールでそれが起きると、置き場が
    黙ってユーザー専用領域へ切り替わり「辞書が消えた」ように見える (そのまま使い続けると
    別の場所に第 2 の辞書が育つ)。判定不能 (ENOENT 系以外の OSError) は「在る」側へ倒し、
    続く読み書きの失敗を見える形 (起動エラー・`load_failed` 通知) にする。
    """
    try:
        (portable / "dictionary.json").stat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _resolve_data_dir() -> Path:
    """可変状態フォルダを決める (`data_dir` の実体。判断理由は同関数の doc)。"""
    explicit = os.environ.get(ENV_DATA_DIR)
    if explicit:
        # 明示指定は最優先。作れなければ黙って別の場所へ逃げない (指定を無視した
        # 場所へ辞書が書かれるほうが事故になる)。
        d = Path(explicit).expanduser()
        d.mkdir(parents=True, exist_ok=True)
        return d

    portable = app_base_dir() / "data"
    if not is_frozen():
        # ソース実行はリポジトリ直下の ``data/`` (開発時の従来どおり)。
        portable.mkdir(parents=True, exist_ok=True)
        return portable

    if _portable_dictionary_present(portable):
        # 既存の可搬インストール。ここで置き場を変えると利用者の辞書が「消えた」ように
        # 見えるため、実体がある限りそのまま使い続ける (移行を壊さない)。
        return portable

    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        candidate = Path(base) / _USER_DIR_NAME / "data"
        if _is_writable_dir(candidate):
            return candidate

    # ユーザー専用領域が使えない環境 (%LOCALAPPDATA% 不在・書き込み不可の VDI) では
    # exe 隣へ落とす。この経路に落ちた配布は**プログラムフォルダの ACL 要件**が効く
    # (配布・運用手順書「配布フォルダの権限」を見よ)。
    portable.mkdir(parents=True, exist_ok=True)
    return portable


def data_dir() -> Path:
    """辞書・設定・ログ・一時領域を置くフォルダ。

    **判断: 配布 exe では exe の隣ではなくユーザー専用領域
    (``%LOCALAPPDATA%/PdfToSvg/data``) を既定にする。** onedir 配布は exe の隣に
    CPython のランタイム DLL と PyMuPDF のネイティブモジュールを置く。可変状態を
    そこへ書くと「プログラムフォルダが書き込み可能でなければ動かない」性質になり、
    共有ツールフォルダや共有ドライブへ置いた瞬間に、別の利用者が DLL を差し替えて
    **次に起動した人の権限で任意コードを実行**できる (CWE-427)。sidecar を捨てて
    単一 exe にした pie-chart と同じ判断を、こちらは「可変状態を外へ出す」側で採った
    (PyMuPDF のネイティブ依存があり単一 exe 化は現実的でないため)。

    可搬性 (フォルダごとコピーして使う) は捨てていない。`PDFTOSVG_DATA_DIR` で
    明示指定でき、既存の可搬インストール (exe 隣に ``data/dictionary.json`` がある)
    はそのまま使い続ける。ユーザー専用領域が使えない環境では exe 隣へ落とすため、
    **手順書側の ACL 要件も併せて残す** (どちらか一方では守り切れない)。
    """
    global _resolved_data_dir
    if _resolved_data_dir is None:
        _resolved_data_dir = _resolve_data_dir()
    _resolved_data_dir.mkdir(parents=True, exist_ok=True)
    return _resolved_data_dir


def log_dir() -> Path:
    """自前の起動診断ログ (``startup.log``) を置くフォルダ (`data_dir` 配下の ``logs/``)。

    終了時に削除する作業領域 (``data/tmp/<pid>``、`app.py` の `main` 参照) とは別階層にし、
    ログはアプリ終了後も残してポストモーテムに使える状態を保つ。

    ここへ書くのは**本プログラムが書式を決めた 1 行ログだけ**で、Edge の verbose ログは
    置かない (`data_dir` は可搬運用や ``%LOCALAPPDATA%`` 不在で exe 隣へ落ちうるため。
    `app.py` の `_edge_log_path` を参照)。"""
    d = data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# 実行時一時フォルダの解決結果 (プロセス内で 1 度だけ採番する。呼ぶたびに別名の
# フォルダを作らないための記憶)。
_resolved_run_tmp_dir: "Path | None" = None


def run_tmp_dir() -> Path:
    """実行時の一時データ (PDF・JSON 一時) を集約するフォルダ (作成込み・プロセス内で固定)。

    置き場は**ローカルのユーザー専用領域を最優先**にする (``%LOCALAPPDATA%/PdfToSvg/tmp``)。
    `data_dir` 配下は可搬運用・`PDFTOSVG_DATA_DIR` 明示指定でネットワークドライブに
    なりうる場所で、そこへ一時データを置くとアップロード PDF の実体が SMB を往復して
    極端に遅くなるうえ、消し損ねた機微文書が共有フォルダに残る。ユーザー専用領域が
    使えない端末 (VDI で C:/``%TEMP%``/プロファイルが書き込み不可) だけ、従来どおり
    `data_dir` 配下へ落とす。

    フォルダ名は ``<pid>-<uuid>``: PID の一意性は 1 台の中でしか成り立たず、置き場が
    共有フォルダのとき別マシンの別プロセスと普通に衝突する。衝突すると `main` の終了時
    削除が**他人の稼働中の一時データ**を消すため、uuid でマシンをまたいでも一意にする
    (pid は調査時にプロセスと突き合わせるための添え物)。`main` が終了時に丸ごと削除する。"""
    global _resolved_run_tmp_dir
    if _resolved_run_tmp_dir is None:
        name = f"{os.getpid()}-{uuid.uuid4().hex}"
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base and _is_writable_dir(Path(base) / _USER_DIR_NAME / "tmp"):
            _resolved_run_tmp_dir = Path(base) / _USER_DIR_NAME / "tmp" / name
        else:
            _resolved_run_tmp_dir = data_dir() / "tmp" / name
    _resolved_run_tmp_dir.mkdir(parents=True, exist_ok=True)
    return _resolved_run_tmp_dir


def dictionary_json_path() -> Path:
    return data_dir() / "dictionary.json"
