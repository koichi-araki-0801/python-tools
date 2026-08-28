"""同一オリジン検査 + セッショントークン認可 (CSRF / DNS リバインディング / 同一マシンの
別プロセス対策) の唯一の関所。

127.0.0.1 に bind するだけでは外部ページからの副作用を防げない。攻撃者ページの
`fetch(..., {mode:'no-cors'})` や `navigator.sendBeacon()` は応答を読めなくても
**リクエストは確実に届く**ため、`/rpc` の辞書書き換えや `/quit` は素通りしてしまう。
さらに短 TTL DNS で攻撃者ドメインを 127.0.0.1 へ再束縛されると、ブラウザから見て同一
オリジンになり応答まで読まれる (DNS リバインディング)。よって「どこから来たか」を
`Host` と `Origin` で検査する必要がある。

ただし `Host`/`Origin`/`Content-Type` は**ヘッダでしかない**。ブラウザは書き換えを禁じられて
いるが、同一マシンで動く非ブラウザのプロセスは自由に詐称できる。VDI/RDS では別ユーザーの
プロセスも 127.0.0.1 に届き、ポートは `data/logs/startup.log` と TCP テーブルから判るので、
ヘッダ検査だけでは「開いている PDF の全文を `pageSvg`/`exportSvg` で読む」「`dictAdd` +
`reapplyDict` で書き換える」「`/quit` で落とす」が誰にでもできる。そこで**起動ごとに
CSPRNG で発行したセッショントークン**の完全一致を非安全メソッドへ要求する (G6)。トークンを
知りうるのは `--app=` の URL で受け取った UI だけである (`app.py` を見よ)。

**検査は `parse_request()` の 1 箇所だけに置く。** `BaseHTTPRequestHandler` は
リクエスト行とヘッダを解析した直後に `parse_request()` を呼び、戻り値が偽なら
「エラー応答は送信済み」とみなして `do_*` へ分岐せず接続処理を終える。ここへ載せると
新しい `do_XXX` を足しても検査を忘れられない。各ハンドラの先頭に `if` を書く設計は
必ず書き忘れるので採らない。同じ理由で「危険な RPC メソッドだけ検査する」も採らない
(列挙 = ブロックリストは 1 つ足した瞬間に穴になるうえ、`pageSvg` / `dictJson` のような
読み出し系こそリバインディングの本命)。

判定はすべて**完全一致の許可リスト**で、`startswith` / 部分一致 / 正規表現は使わない
(`http://127.0.0.1:5180.evil.com` のような前方一致バイパスを構造的に排除する)。
`Access-Control-Allow-Origin` は**将来も出さない**: 出さないこと自体が防御であり、
許可外オリジンからのプリフライトを必ず失敗させる。

本モジュールは `graph-editor/app.py` の「同一オリジン検査」セクションと**同一仕様の
並行実装**である (graph-editor は実行時依存ゼロ・単一 `app.py` が設計前提のため共有
モジュールを持てない)。判定順・理由コード・許可リストの中身は逐語で揃えてあり、
**片方を変えたら必ず両方を変える**こと。テストベクタも両プロジェクトへ複製している
(`test/test_origin_guard.py` と `graph-editor/test/test_app_guard.py`)。
"""
from __future__ import annotations

import hmac
import http.server
import io
import logging
import secrets
import socket
import string
import time
from urllib.parse import parse_qs, urlsplit

# ── 許可リスト (2 プロジェクトで同一) ──

# 非安全メソッドで許す Content-Type。どちらも CORS セーフリスト外なので、クロスオリジンから
# 送るにはプリフライトが要る。本サーバは `do_OPTIONS` を持たず ACAO も出さないため、
# プリフライトは必ず失敗する。`text/plain;charset=UTF-8` の simple request は
# Origin 検査とは独立にここで閉じる。値は現行クライアントが実際に送っているものの写しで、
# 「サーバに合わせてクライアントを直す」のではなく「実態を許可リストとして固定する」向き。
ALLOWED_REQUEST_CONTENT_TYPES = frozenset({"application/json", "application/octet-stream"})

# Origin を要求しないメソッド。Fetch 仕様上、GET/HEAD 以外にはブラウザが必ず Origin を
# 付けるので、非安全メソッドで Origin が無い = ブラウザ以外とみなして拒否できる。
SAFE_METHODS = frozenset({"GET", "HEAD"})

# セッショントークンの運び方 (2 プロジェクトで同一)。`fetch` はヘッダで送る。
# `navigator.sendBeacon('/quit')` は**ヘッダを付けられない** API なので、そこだけは
# クエリ文字列で送る。クエリを常時許すのは「ビーコンだけ別の判定を書く」= 経路ごとの
# 分岐を作らないため (分岐は必ず片方を書き忘れる)。クエリ値がプロセス一覧やブラウザ履歴へ
# 残る点は下の `new_session_token` の注記を見よ。
TOKEN_HEADER = "X-Session-Token"
TOKEN_QUERY = "token"

# 全応答 (成功 `_send` と拒否 `_reject` の双方) へ載せる防御ヘッダ。**1 応答でも欠けると、
# その URL が `<iframe>` や `<script src>` の足がかりになる**ので、送信経路を増やしたら
# 付与は `end_headers()` の override 1 箇所に集約してある (呼び出し側は意識しない)。
# - `frame-ancestors 'none'` / `X-Frame-Options: DENY`: 攻撃者ページが本 UI を frame へ
#   埋め込むのを拒む。同一オリジン検査は frame 化を防げない — frame の中身は**アプリ自身**で、
#   その `pagehide` が撃つ `/quit` ビーコンは Origin が完全一致して検査を正当に通過する。
# - `default-src 'self'`: 同梱資産以外を読ませない。inline `<script>` もこれで禁止になる
#   (両アプリとも inline script を持たない。`<style>` と `style=` 属性だけを例外にする)。
# - `style-src 'unsafe-inline'`: `index.html` の inline `<style>` と多数の `style=` 属性、
#   および描画する SVG が `<style>` で `@font-face` を持つため。
# - `img-src`/`font-src` の `data:`: PDF 由来の画像とサブセットフォントを data URI で
#   埋め込んだ SVG を表示するため。
# - `nosniff` / `Cross-Origin-Resource-Policy: same-origin`: MIME 誤解釈と、他オリジンからの
#   no-cors 読み出し (既知パスの 200/404 差によるポート探索オラクル) を断つ。
SECURITY_HEADERS = (
    ("X-Frame-Options", "DENY"),
    ("Content-Security-Policy",
     "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
     "font-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
)

# 403 の理由コードごとにログへ出す上限。全件出すと攻撃者にログを膨らませられる
# (`startup.log` はローテーションを持たない)。
REJECT_LOG_LIMIT = 3

# 403 を返す前に読み捨てる本文の上限。読み捨てずに閉じると未読データの残った TCP が RST し、
# クライアントは 403 ではなく接続エラーを見る。上限超はそのまま閉じる (DoS 対策を優先)。
_DRAIN_LIMIT = 1 << 20

# `_drain_body` で読み切れなかった本文を応答送信後に読み捨てる**全体**の待ち時間 (秒)。
# 相手が応答を読んで閉じれば即 EOF になるので、これは相手が黙り込んだ場合に接続を抱え
# 続けないための上限。recv ごとに測り直すと「0.4 秒ごとに 1 バイト」を送る相手が
# `_DRAIN_LIMIT` (1 MiB) 到達までスレッドを握り続けられるため、**期限は接続単位**で持つ。
_LINGER_TIMEOUT = 0.5

# 1 要求あたりの実時間の絶対上限 (秒)。`Handler.timeout` (= `REQUEST_TIMEOUT`) は **recv ごとに
# 再武装される無通信上限**なので、「N 秒ごとに 1 バイト」を送り続ける相手は 1 要求を無限に
# 引き延ばして 1 スレッドを恒久占有できる (リクエスト行は改行が来るまで終わらず、`readline` の
# バイト上限 65537 に達するまで日単位で握れる)。要求の読み取りは `_DeadlineSocketIO` が
# **要求単位の絶対期限**で縛り、各 recv の手前で残り時間へタイムアウトを張り直す
# (`_linger_close` と同じ「期限は per-recv でなく単位ごと」の規約)。正常系の往復は数ミリ秒。
MAX_REQUEST_SECONDS = 30.0


class _DeadlineSocketIO(socket.SocketIO):
    """`rfile` の下地。各 `readinto` の手前でソケットタイムアウトを「この要求の絶対期限までの
    残り」へ張り直す。`BufferedReader` の内部読み取りはすべて `readinto` を通るので、改行を
    送らずにドリップして `readline` を無限に引き延ばす形もここで閉じる。素の per-recv
    タイムアウトは recv ごとに再武装されるため、これが無いと期限が効かない。"""

    def __init__(self, sock, handler):
        super().__init__(sock, "rb")
        self._handler = handler

    def readinto(self, b):
        remaining = self._handler._request_deadline - time.monotonic()
        if remaining <= 0:
            raise socket.timeout("request deadline exceeded")
        cap = self._handler.timeout or MAX_REQUEST_SECONDS
        self._sock.settimeout(min(cap, remaining))
        return super().readinto(b)

# ログへ出す詳細値の整形。攻撃者が入れた制御文字でログ行を偽装できないよう、印字可能 ASCII
# 以外は落として短く切る。
_LOG_SAFE_CHARS = frozenset(string.ascii_letters + string.digits + "-._:[]/")
_LOG_DETAIL_MAX = 64

_log = logging.getLogger("pdftosvg")


def allowed_hosts(port: int) -> frozenset[str]:
    """許可する `Host` ヘッダ値。ブラウザは Host を書き換えられないので、これが
    DNS リバインディング (攻撃者ドメイン名のまま 127.0.0.1 へ解決) の決定的な壁になる。"""
    return frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})


def allowed_origins(port: int) -> frozenset[str]:
    """許可する `Origin` ヘッダ値。`null` (sandbox iframe・`file://`・`data:`) は含めない。
    IPv6 の `[::1]` も含めない (127.0.0.1 に bind しているので到達しない)。"""
    return frozenset({f"http://127.0.0.1:{port}", f"http://localhost:{port}"})


def new_session_token() -> str:
    """この起動のセッショントークンを CSPRNG で作る (URL 安全な 32 バイト相当)。

    受け渡しは `--app=` の URL クエリ 1 本に絞る (`app.py`)。**配信する HTML へ埋める案は
    採らない**: `GET /` は安全メソッドで誰でも撃てるため、埋めた瞬間に「トークンを持たない
    ローカルプロセス」が読み出せてしまい、守ろうとしている脅威 (同一マシンの別ユーザー) そのものを開く。
    残る漏えい面は「起動した `msedge.exe` のコマンドライン」と、フォールバック経路での
    ブラウザ履歴である (Jupyter の `?token=` と同じ割り切り)。ログには書かない。
    """
    return secrets.token_urlsafe(32)


def configure_guard(server, port: int, token: str) -> None:
    """サーバへ許可リストとセッショントークンを固定する。**bind 後の実ポート**で呼ぶこと
    (port 0 で組むと全滅する)。設定されていないサーバは `unconfigured` で全拒否になり、
    トークンだけが空なら非安全メソッドが全拒否になる (いずれも fail closed)。"""
    server.guard_hosts = allowed_hosts(port)
    server.guard_origins = allowed_origins(port)
    server.guard_token = token
    server.guard_reject_counts = {}


class GuardedHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
    """`parse_request()` で同一オリジン検査を行うハンドラ基底。

    サブクラスは `do_GET` / `do_POST` を素直に書けばよく、検査は上に載る。
    **`do_GET` / `do_HEAD` に副作用を持たせないこと**: 安全メソッドは Origin 無しでも
    通す (ブラウザが付けないため) ので、副作用を置くと CSRF が素通りする。同じ理由で
    **安全メソッドから機微データやセッショントークンを返さないこと**: 安全メソッドは
    トークンも要求しない (G6) ので、返した瞬間に任意のローカルプロセスが読み出せる。
    idle watchdog 用の `last_seen` 更新もその副作用の 1 つなので、判定と同じ場所
    (`_touch_if_same_origin`) に置いて `do_*` からは触らせない。
    """

    def setup(self) -> None:
        # `rfile` を要求期限つきの下地から作り直す。素の `makefile` 済み `rfile` は per-recv
        # タイムアウトしか持たないため、ドリップに弱い (`_DeadlineSocketIO` / `MAX_REQUEST_SECONDS`)。
        super().setup()
        self._request_deadline = time.monotonic() + MAX_REQUEST_SECONDS
        size = self.rbufsize if self.rbufsize and self.rbufsize > 0 else io.DEFAULT_BUFFER_SIZE
        self.rfile = io.BufferedReader(_DeadlineSocketIO(self.connection, self), size)

    def handle_one_request(self) -> None:
        # keep-alive で接続が再利用される場合、各要求を独立に上限で縛る (要求ごとに期限を引き直す)。
        self._request_deadline = time.monotonic() + MAX_REQUEST_SECONDS
        super().handle_one_request()

    def parse_request(self) -> bool:
        # `super()` の解析後 (self.command / self.path / self.headers が揃った直後) かつ
        # `do_*` への分岐前が唯一の共通点。ここで落とせばハンドラ本体へは一切到達しない
        # ("実行してから 403 を返す" = `quit_event` が立ってしまう形を構造的に避ける)。
        if not super().parse_request():
            return False
        reason = self._guard_reason()
        if reason is not None:
            return self._reject(reason)
        self._touch_if_same_origin()
        return True

    def _touch_if_same_origin(self) -> None:
        """idle watchdog の最終アクセス時刻を更新する。**Origin が完全一致した
        リクエストだけ**が対象である。

        安全メソッドは Origin 無しでも通す (G3/G4) ため、`do_GET` 側で無条件に更新すると
        クロスオリジンの no-cors GET (`<img src>` / `<link href>` の連打) で
        `IDLE_TIMEOUT` を永久に先送りでき、ゾンビサーバを維持できてしまう。正規の
        ハートビートは `resources/web/app.js` の `POST /ping` で必ず Origin を伴うので、
        Origin 無しの経路を延命へ使わせない。
        """
        origin = self._single_header("Origin")
        if origin is None:
            return
        if origin.strip().lower() in (getattr(self.server, "guard_origins", None) or ()):
            self.server.last_seen = time.monotonic()

    # ── 判定 ──

    def _guard_reason(self) -> str | None:
        """拒否理由コードを返す。通してよければ `None`。判定順は graph-editor と同一。"""
        hosts = getattr(self.server, "guard_hosts", None)
        origins = getattr(self.server, "guard_origins", None)
        if not hosts or not origins:
            return "unconfigured"

        # G0: リクエストターゲットは origin-form (`/...`) のみ。absolute-form
        # (`POST http://127.0.0.1:p/quit`) を許すと `urlsplit(path).path` での経路分岐は
        # 通るのに Host は攻撃者値、という食い違いを作れる。
        if not self.path.startswith("/"):
            return "request-target"

        # G1: Host は完全一致。重複ヘッダは `get()` が先頭しか返さず食い違うので個数を見る。
        host = self._single_header("Host")
        if host is None or host.strip().lower() not in hosts:
            return "host-mismatch"

        # G2: フレーミングは Content-Length 単独のみ。`Transfer-Encoding` は本文が未読のまま
        # keep-alive 接続に残り、次のリクエスト行として解釈されうる (デシンク)。
        if self.headers.get_all("Transfer-Encoding"):
            return "framing"
        if len(self.headers.get_all("Content-Length") or ()) > 1:
            return "framing"

        raw_origin = self.headers.get_all("Origin")
        if raw_origin:
            # G3: Origin があるなら完全一致。`null` は許可リストに入れていないので落ちる。
            if len(raw_origin) != 1 or raw_origin[0].strip().lower() not in origins:
                return "origin-mismatch"
        elif self.command not in SAFE_METHODS:
            # G4: 非安全メソッドで Origin が無い = ブラウザではない。ローカルの非ブラウザ
            # プロセスは任意ヘッダを詐称できて防御力が変わらない以上、閉じる方を採る。
            # 注意: 応答へ `Referrer-Policy: no-referrer` を足すと sendBeacon (no-cors POST)
            # の Origin が `null` へ置換され `/quit` が 403 になる。足すなら `same-origin` か
            # `strict-origin-when-cross-origin` を選ぶこと。
            return "origin-missing"

        # G5/G6: 非安全メソッドだけに掛かる検査。安全メソッド (静的配信) はトークンを
        # 要求しない — 下位資産 (`app.js` / `styles.css`) の取得にトークンは載らないうえ、
        # `do_GET` は副作用も機微データも持たないためである。逆に言えば、GET 側へ副作用や
        # 秘密の読み出しを足した瞬間にこの前提が崩れる (`GuardedHTTPRequestHandler` の
        # クラス doc の禁止事項)。
        if self.command not in SAFE_METHODS:
            return self._content_type_reason() or self._token_reason()
        return None

    def _token_reason(self) -> str | None:
        """G6: セッショントークンの完全一致。`X-Session-Token` ヘッダ、無ければクエリ
        `?token=` を見る (`sendBeacon` はヘッダを付けられないため)。

        比較は `hmac.compare_digest` の定時間比較。素朴な `==` は一致した接頭辞の長さに
        比例して所要時間が変わり、同一マシンから何度でも試せるローカル攻撃者にとっては
        現実的な桁数のオラクルになる。トークン未設定のサーバは全拒否 (fail closed)。
        """
        expected = getattr(self.server, "guard_token", None)
        if not expected:
            return "token"
        supplied = self._single_header(TOKEN_HEADER)
        if supplied is None:
            values = parse_qs(urlsplit(self.path).query).get(TOKEN_QUERY) or ()
            # 2 本以上は「どちらが真か」を決められない (ヘッダ重複と同じ扱いで拒否)。
            supplied = values[0] if len(values) == 1 else None
        if supplied is None:
            return "token"
        try:
            ok = hmac.compare_digest(supplied.strip().encode("utf-8"), expected.encode("utf-8"))
        except UnicodeError:
            return "token"  # サロゲート等でエンコードできない値は一致しえない。
        return None if ok else "token"

    def _content_type_reason(self) -> str | None:
        raw = self.headers.get_all("Content-Type")
        if not raw:
            length = self._single_header("Content-Length")
            if length is not None and length.strip() not in ("", "0"):
                return "content-type"
            return None
        if len(raw) != 1:
            return "content-type"
        if raw[0].split(";", 1)[0].strip().lower() not in ALLOWED_REQUEST_CONTENT_TYPES:
            return "content-type"
        return None

    def _single_header(self, name: str) -> str | None:
        """ちょうど 1 本だけ存在するときにその値を返す。0 本・2 本以上は `None`。"""
        values = self.headers.get_all(name)
        return values[0] if values and len(values) == 1 else None

    # ── 応答ヘッダ ──

    def send_security_headers(self) -> None:
        """`SECURITY_HEADERS` を応答へ載せる。**呼び出し側は意識しなくてよい** —
        `end_headers()` の override がすべての応答へ自動で載せる (下記)。"""
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)

    def end_headers(self) -> None:
        """全応答の共通出口。ここで `SECURITY_HEADERS` を載せる。

        規約 (「全応答経路から呼ぶこと」) ではなく**構造**で強制する。明示呼び出し方式では
        自分で書いた経路 (`_send` / `_reject`) しか覆えず、基底クラスが直接返す応答
        — `HEAD` に `do_HEAD` が無いときの **501**、リクエスト行が長すぎるときの **414**、
        その他 `send_error()` 全般 — が素通りになる。ヘッダの無い応答が 1 本でもあれば、
        `Cross-Origin-Resource-Policy` が効かず「このポートでこのアプリが動いている」を
        クロスオリジンから確定できる (ポート探索オラクル)。

        二重付与を避けるため 1 応答につき 1 回だけ載せる。`send_response_only()` が
        新しい応答の開始点なので、そこでフラグを戻す。
        """
        if not getattr(self, "_sec_headers_done", False):
            self._sec_headers_done = True
            self.send_security_headers()
        super().end_headers()

    def send_response_only(self, code, message=None):  # type: ignore[override]
        """応答の開始点。`end_headers()` の二重付与ガードをここで戻す。"""
        self._sec_headers_done = False
        super().send_response_only(code, message)

    # ── 拒否応答 ──

    def _reject(self, reason: str) -> bool:
        """本文を読み捨ててから 403 を返し、接続を閉じる。常に `False` を返す
        (= `handle_one_request` から見て「エラー応答送信済み」)。"""
        drained = self._drain_body()
        self.close_connection = True
        body = b"forbidden"
        try:
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass  # 相手が先に切っただけ。ログを増やさない。
        if not drained:
            self._linger_close()
        self._log_reject(reason)
        return False

    def _drain_body(self) -> bool:
        """宣言された本文を上限まで読み捨てる。403 の本体はリクエスト内容を一切反射しない。
        未読データを残していなければ `True`、残したなら `False` (呼び出し側が lingering close)。"""
        if self.headers.get_all("Transfer-Encoding"):
            return False  # チャンク解析はしない (それ自体がデシンクの温床)。残りは linger 任せ。
        raw = self._single_header("Content-Length")
        if raw is None:
            # Content-Length も Transfer-Encoding も無ければ本文は存在しない。重複 Content-Length
            # (`_single_header` が None) はどちらが真か決められないので読まずに linger へ回す。
            return not self.headers.get_all("Content-Length")
        try:
            remaining = int(raw.strip())
        except ValueError:
            return False
        if remaining == 0:
            return True
        if remaining < 0 or remaining > _DRAIN_LIMIT:
            return False  # 未認可の巨大 body は読まない (DoS 対策を優先)。
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 65536))
            if not chunk:
                return True  # 相手が先に切った。未読データは残らない。
            remaining -= len(chunk)
        return True

    def _linger_close(self) -> None:
        """応答送信後、相手が送った未読データを短時間だけ読み捨ててから接続を手放す。

        未読データを残したまま閉じると OS は RST を送り、**送信済みの 403 ごと**クライアントの
        受信バッファが捨てられる (Windows で顕在化し、クライアントは接続エラーだけを見る)。
        書き込み側だけ先に閉じて FIN を届け、相手が閉じるまで読み捨てる。`_DRAIN_LIMIT` と
        `_LINGER_TIMEOUT` で上限を切り、拒否した相手に接続を抱えさせない。期限は
        **ループ全体**に掛ける (recv ごとの期限だと少しずつ送り続ける相手を止められない)。
        """
        sock = self.connection
        deadline = time.monotonic() + _LINGER_TIMEOUT
        try:
            sock.shutdown(socket.SHUT_WR)
            drained = 0
            while drained < _DRAIN_LIMIT:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                sock.settimeout(remaining)
                chunk = sock.recv(65536)
                if not chunk:
                    return
                drained += len(chunk)
        except OSError:
            pass  # timeout・相手が先に切った等。いずれも RST 回避の努力目標でしかない。

    def _log_reject(self, reason: str) -> None:
        counts = getattr(self.server, "guard_reject_counts", None)
        if counts is None:
            counts = self.server.guard_reject_counts = {}
        seen = counts.get(reason, 0) + 1
        counts[reason] = seen
        if seen > REJECT_LOG_LIMIT:
            return
        _log.warning("rejected request reason=%s host=%s origin=%s",
                     reason,
                     _log_safe(self.headers.get("Host")),
                     _log_safe(self.headers.get("Origin")))


def _log_safe(value: str | None) -> str:
    """ログへ出す前に印字可能 ASCII の部分集合だけへ落として短く切る (ログ行の偽装防止)。"""
    if not value:
        return "-"
    kept = "".join(c for c in value if c in _LOG_SAFE_CHARS)
    return (kept[:_LOG_DETAIL_MAX] or "-")
