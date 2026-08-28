# =============================================================================
# editor_server.py — E2E 用の依存ゼロ静的サーバ(pytest fixture から起動)
# =============================================================================
# graph-editor/resources/web を配信する。防御ヘッダは app.py の SECURITY_HEADERS
# (タプル列)を直接 import して載せる(editor_server.mjs の逐語複製と違い drift しない)。
# `.cjs` の MIME は明示登録する: 既定の guess_type は .cjs を知らず octet-stream になり、
# nosniff 下で ui.html の classic script(lib/leader_geom.cjs)が実行拒否される。
# ポートは 0(ephemeral)で束縛し、実ポートを stdout の 1 行目で報告する(固定ポートは
# 居残りプロセスへの誤当たりを生む)。
import functools
import http.server
import importlib.util
import os

_APP_PATH = os.path.join(os.path.dirname(__file__), "..", "app.py")
_spec = importlib.util.spec_from_file_location("grapheditor_app", _APP_PATH)
_app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_app)  # import 時に副作用が無いことは drift テストが保証している

WEB_ROOT = os.path.join(os.path.dirname(__file__), "..", "resources", "web")


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".cjs": "text/javascript",
        ".js": "text/javascript",
        ".mjs": "text/javascript",
    }

    def end_headers(self):
        for k, v in _app.SECURITY_HEADERS:
            self.send_header(k, v)
        super().end_headers()

    def log_message(self, *args):
        pass


def main():
    handler = functools.partial(Handler, directory=os.path.abspath(WEB_ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    print(f"listening on http://127.0.0.1:{server.server_address[1]}/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
