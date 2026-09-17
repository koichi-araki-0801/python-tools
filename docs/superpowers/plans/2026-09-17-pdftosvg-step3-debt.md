# PdfToSvg 手順 3 技術的負債の解消 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 手順 3 の UI 改善 2 計画の最終レビューが「実害なし・後回しでよい」と判定した技術的負債 4 群——E2E サーバの固定ポート、枠線の太さ検査の三者不一致、削除ボタン同期の取りこぼしと名前衝突、E2E とオーバーレイの設計上の整理——を片付ける。

**Architecture:** ①E2E 用サーバをポート 0 で起動し、実際に bind したポートを子プロセスがファイルへ書き、fixture がその出現を待って読む。並走が構造的に可能になるので、起動前の占有検知（`ensure_port_is_free`）は撤去する。②枠線の太さの範囲は `index.html` の `min`/`max` を正典にし、JS はその属性を読んで検査、サーバ側の定数はそれと揃える旨のコメントで結ぶ。③`rect-overlay.js` の押下可否同期を早期 return でも呼び、削除直後に選択を即解除し、内部関数名の衝突を解く。④`rect-overlay.js` が「どのツール中に描くか」を `opts.isActive()` で受け取り、`state.js` への依存を外す。E2E の独自ポーリングは Playwright 標準の `wait_for_function` へ。

**Tech Stack:** Python 3.13（標準ライブラリ）、素の ES モジュール JavaScript、pytest + Playwright（Edge チャネル）。

**Spec:** 本計画の「設計（承認済み）」節。2026-09-17 の最終レビュー（前計画 8 タスク + 後続 3 タスクの全体レビュー）の Minor・Recommendation と、ユーザーへの選択肢確認で「今やる」と回答された 4 群に基づく。

## 設計（承認済み）

1. **E2E サーバの空きポートを OS に選ばせる**（並走の根本対策）
   - 何が困るか: テスト用サーバはポート 5181 固定。同時に 2 本走ると混線する（Windows では `SO_REUSEADDR` で二重 bind が成功し、接続がランダムに振り分けられる）。いまは起動前に応答の有無を見て `RuntimeError` で止まる（`ensure_port_is_free`）までで、並走できるようにはなっていない。今回のセッションでも、コントローラが手動確認用に立てたサーバが pre-push の E2E を止めた。
   - どうするか: fixture は `PDFTOSVG_E2E_PORT=0` と `PDFTOSVG_E2E_PORT_FILE=<一時ファイル>` を渡して子を起動する。`e2e_server.py` は `create_server(..., port=0)` で bind した実ポート（`server.server_address[1]`）を標準出力に加えてそのファイルへ書く。fixture はファイルの出現を待って（タイムアウト付きポーリング）読み、`BASE` を組む。`ensure_port_is_free` は撤去し、`wait_until_serving`（応答が出るまで待つ。無いまま子が死んだら stderr 付きで止める）は残す。
   - 理由: ポートが毎回違えば衝突しない。子の標準出力を `readline` で待つ方式は、子がハングしたとき永久に待ち、Windows の pipe には `select` でタイムアウトを付けられない。ファイルの出現ポーリングは単純で確実。`e2e_server.py` の `PORT` の既定値 5180 は変えない（`origin_guard.py` と drift 検出のテストベクタが 5180 を参照しており、そこは触らない）。
2. **枠線の太さの範囲をクライアントも [0.5, 20] にし、正典を 1 箇所にする**
   - 何が困るか: `index.html` は `min="0.5" max="20"`、サーバは `[0.5, 20]`（前回揃えた）、JS の `change` ハンドラは `v > 0` だけ。UI の `max` を越えて 25 と打つと JS は通し、サーバが拒否し、入力欄に 25 が残る。
   - どうするか: JS は `this.min` / `this.max` を読んで検査し、弾いたときは既存どおり「次に置く太さ」へ戻す。サーバの `BORDER_WIDTH_MIN` / `BORDER_WIDTH_MAX` は `MAX_COVER_TEXT_CHARS` の隣へ移し、`index.html` の `min`/`max` と揃える旨のコメントを付ける（前回の fix wave で `_border_width` の直前に置いたのを裁定どおりの位置へ）。
   - 理由: 範囲の数字を書く場所を HTML 1 箇所に減らす。サーバ側の定数は HTML を読めないので値を持つが、コメントで結ぶ。
3. **削除ボタン同期の取りこぼし・削除直後の一瞬のずれ・名前衝突**
   - 何が困るか: (a) `rect-overlay.js` の `draw()` と mouseup の `if (!svgEl) return;` が `syncDeleteButton` を飛ばす。(b) 削除ボタンを押した直後、`S.coverSel` / `S.borderSel` に削除済み id が残ったまま `render()` → `syncDeleteButton()` が走り、非同期の `draw()` → `clearSel()` が届くまで一瞬ボタンが有効のまま。(c) `rect-overlay.js` の内部関数 `clearSel` が `state.js` の export `clearSel`（`app.js` が import）と同名で紛らわしい。
   - どうするか: (a) 早期 return の前に `syncDeleteButton` を呼ぶ。(b) 削除ボタンのハンドラで `applyDelete` の直後に `S.coverSel = null; S.borderSel = null;` を置く（`afterEdit` の前）。(c) 内部関数を `clearOverlaySel` に改名し、返り値のキー `clearSel` は維持（`cover.js` / `border.js` の `overlay.clearSel()` を触らない）。
   - 理由: いずれも実害は表示の一瞬のずれと読みにくさだが、「選択が変わる全経路から呼ぶ」という `syncDeleteButton` の建前に穴が無い方が、次に経路を足す人が迷わない。
4. **E2E とオーバーレイの設計上の整理**
   - 何が困るか: (a) E2E の `_poll_borders` が `eval("(" + predicateSrc + ")")` でページ内に JS 関数を再構成しており、Playwright 標準の `wait_for_function` より非慣用的。(b) `rect-overlay.js` が `S.phase` / `S.tool` をシングルトンから直接読み、「`opts` で受け取ったものだけで動く」という自身の設計原則と食い違う。実ブラウザ単体テストが `S` を書き換えざるを得ない原因もここ。
   - どうするか: (a) `_poll_borders` を `page.wait_for_function` に置き換える（RPC の結果が期待値になるまで待つ、という意味は変えない）。これで「確定の反映待ち」は DOM 属性の `expect` と `wait_for_function` の 2 つになり、どちらも Playwright 標準。(b) `createRectOverlay` の `opts` に `isActive: () => boolean` を足し、`draw()` の `S.phase !== 3 || S.tool !== opts.tool` を `!opts.isActive()` に置き換え、`rect-overlay.js` から `import { S } from "./state.js"` を外す。`cover.js` / `border.js` が `isActive: function () { return S.phase === 3 && S.tool === "cover"; }` を渡す。`opts.tool` は不要になるので外す。実ブラウザ単体テストは `S` を触らず `isActive: () => true` を渡す形になり、teardown の `S` 復元も不要になる。
   - 理由: (b) で `rect-overlay.js` が本当に「`opts` だけで動く」純粋な部品になり、単体テストが共有ページを汚す構造的な理由が消える。

## Global Constraints

- Python は常に `py -3.13` を明示して呼ぶ。
- **pytest の一括実行は禁止**。`py -3.13 -m pytest <dir または file>` の形で個別に指定する（本計画で使うのは `pdf-to-svg`・`docs/_build`・`scripts`）。
- **Task 1 が完了するまで E2E を並走させない**（テスト用サーバがポート 5181 固定のため。Task 1 完了後は並走できる）。実装者が E2E を回している間、コントローラは E2E も `test_e2e_server.py` も回さない。コミット後の pre-push も E2E を回すので、E2E 全件はコミットの**前**に済ませる。
- `xdist` / `pytest-randomly` を入れない。
- `src/web/server.py` / `src/web/origin_guard.py` / graph-editor 側には触らない（並行実装で drift 検出の対象）。`e2e_server.py` の `PORT` の既定値 5180 も変えない。
- ブランチ運用は **main への直接コミット**。トピックブランチを作らない。
- コミットすると post-commit フックが auto-push を試み、pre-push フックが check_comments（フルツリー）+ pytest 6 本を順に走らせる。コミット 1 回ごとに約 130 秒。
- コード中の日本語コメント・原稿・コミットメッセージは通常の丁寧な日本語で書く。既存の文体・コメント規約に従う。
- コミットメッセージは Conventional Commits 形式。末尾に次の 2 行を付ける。`Co-Authored-By` のモデル名は**実際にそのコミットを書いた実行主体のもの**。

```
Co-Authored-By: <実際に書いた実行主体のモデル名> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
```

- 「実装を変えたら、原稿 → HTML 生成 までが 1 セット」。原稿の更新は各タスクに含め、HTML の再生成は最後のタスクでまとめて行う。GitHub リリース `2026.09.08` の差し替えは全タスク完了後にコントローラが行う。

## ファイル構成

| ファイル | 責務 | 変更の種類 |
|---|---|---|
| `pdf-to-svg/test/e2e_server.py` | 実ポートをファイルへ書く。`ensure_port_is_free` を撤去 | 変更 |
| `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` | fixture がポート 0 で起動しファイルから読む。`_poll_borders` を `wait_for_function` へ | 変更 |
| `pdf-to-svg/test/test_e2e_server.py` | 占有検知のテストを撤去し、ポート 0 起動のテストへ | 変更 |
| `pdf-to-svg/resources/web/app.js` | 太さ検査を `min`/`max` から、削除直後の選択解除 | 変更 |
| `pdf-to-svg/src/web/rpc_methods.py` | `BORDER_WIDTH_MIN/MAX` の配置 | 変更 |
| `pdf-to-svg/resources/web/rect-overlay.js` | 早期 return の `syncDeleteButton`、`clearOverlaySel` 改名、`opts.isActive`、`state.js` 依存の除去 | 変更 |
| `pdf-to-svg/resources/web/cover.js` / `border.js` | `isActive` を渡す | 変更 |
| `pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py` | `isActive` を渡し `S` を触らない形へ。早期 return の同期テスト | 変更 |
| `pdf-to-svg/test/conftest.py` | `edge_page` docstring の規約（`S` を触るテストは戻す）を「原則 `S` を触らない」へ | 変更 |
| `docs/pdf-to-svg/src/設計書.md` / `PdfToSvg_仕様一覧.md` / `設計正典.md` | E2E 節・`rect-overlay.js` 行・テスト表・改訂履歴 2.19 | 変更 |

---

### Task 1: E2E サーバの空きポートを OS に選ばせる

**Files:**
- Modify: `pdf-to-svg/test/e2e_server.py`（`main()`、`ensure_port_is_free` / `_responds` の撤去、冒頭コメント）
- Modify: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`（`PORT` / `BASE` 定数と `e2e_server` fixture、29-45 行付近）
- Modify: `pdf-to-svg/test/test_e2e_server.py`
- Modify: `docs/pdf-to-svg/src/設計書.md`（E2E の節）、`docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`（テスト表 38）、`docs/pdf-to-svg/src/設計正典.md`（並走に関する記述があれば）

**Interfaces:**
- Consumes: `create_server(web_root, session, port=0, token=...)`（既存。`port=0` で OS に選ばせ、`server.server_address[1]` が実ポート）
- Produces:
  - 環境変数 `PDFTOSVG_E2E_PORT_FILE`: 指定されていれば `e2e_server.py` が bind 後に実ポートを 10 進文字列で書く
  - `wait_for_port_file(path: Path, proc: subprocess.Popen, *, timeout: float = 20.0, interval: float = 0.1) -> int`（`e2e_server.py`。ファイルが現れて中身が整数になるまで待ち、子が死んだら stderr 付き `RuntimeError`、時間切れも `RuntimeError`）
  - `wait_until_serving(proc, base_url, *, attempts=100, interval=0.2)`（既存。据え置き）
  - fixture `e2e_server` が返す `BASE` は実行ごとに変わる（`http://127.0.0.1:<実ポート>`）

- [ ] **Step 1: 失敗する単体テストを書く**

`pdf-to-svg/test/test_e2e_server.py` を次で置き換える（`ensure_port_is_free` のテストは撤去し、ポート 0 起動とファイル経由の受け渡しを検証する）。

```python
# =============================================================================
# test_e2e_server.py — E2E 用サーバの起動 (ポート 0 → 実ポートをファイルで受け渡す) と待ち合わせ
# =============================================================================
# E2E はテスト用サーバをポート 0 で起動し、OS が選んだ実ポートを子プロセスがファイルへ書き、
# fixture がその出現を待って読む。固定ポートだと 2 本並走したときに混線する (Windows では
# SO_REUSEADDR で二重 bind が成功し、接続がどちらへ届くか不定になる) ため、毎回違うポートに
# して衝突そのものを無くす。ここでは、ファイルに実ポートが書かれてそのポートで応答すること、
# 子が起動前に死んだら stderr 付きで止まることを確かめる。
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from .e2e_server import wait_for_port_file, wait_until_serving


def _spawn(port_file: Path, *, port: str = "0") -> subprocess.Popen:
    env = dict(os.environ, PDFTOSVG_E2E_PORT=port, PDFTOSVG_E2E_PORT_FILE=str(port_file))
    return subprocess.Popen(
        [sys.executable, os.path.join(os.path.dirname(__file__), "e2e_server.py")],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def test_port_zero_writes_the_actual_port_to_the_file_and_serves_there():
    """ポート 0 で起動すると、OS が選んだ実ポートがファイルへ書かれ、そのポートで応答する。"""
    with tempfile.TemporaryDirectory() as tmp:
        port_file = Path(tmp) / "port"
        proc = _spawn(port_file)
        try:
            port = wait_for_port_file(port_file, proc)
            assert 1024 <= port <= 65535
            wait_until_serving(proc, f"http://127.0.0.1:{port}")  # 例外が出ないこと
            assert proc.poll() is None
        finally:
            proc.kill()
            proc.wait()


def test_two_servers_started_at_once_get_different_ports():
    """2 本同時に起動しても別のポートになる (並走で混線しない根拠)。"""
    with tempfile.TemporaryDirectory() as tmp:
        f1, f2 = Path(tmp) / "p1", Path(tmp) / "p2"
        p1, p2 = _spawn(f1), _spawn(f2)
        try:
            port1 = wait_for_port_file(f1, p1)
            port2 = wait_for_port_file(f2, p2)
            assert port1 != port2
        finally:
            for p in (p1, p2):
                p.kill()
                p.wait()


def test_wait_for_port_file_fails_when_the_child_dies_before_writing():
    """子が起動前に死んだら (ここでは不正なポート指定で bind に失敗させる)、待ち続けずに
    stderr を添えて RuntimeError になる。"""
    with tempfile.TemporaryDirectory() as tmp:
        port_file = Path(tmp) / "port"
        proc = _spawn(port_file, port="99999")  # 範囲外 → bind で OverflowError
        try:
            with pytest.raises(RuntimeError, match="起動前に終了"):
                wait_for_port_file(port_file, proc, timeout=15.0)
        finally:
            proc.kill()
            proc.wait()
```

- [ ] **Step 2: テストを走らせて失敗を確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_e2e_server.py -v`
Expected: FAIL（`ImportError: cannot import name 'wait_for_port_file'`）

- [ ] **Step 3: `e2e_server.py` を書き換える**

`pdf-to-svg/test/e2e_server.py` の冒頭コメント（3〜7 行目付近の「E2E は playwright.config.ts の baseURL と合わせるため固定ポート 5180 で待ち受ける」）を次に直す。

```python
# `src/app.py` の main() から「Edge 起動・watchdog・終了管理」を除いた最小構成。
# ポートは環境変数 PDFTOSVG_E2E_PORT で指定する (既定 5180。E2E fixture は 0 を渡して OS に選ばせ、
# bind した実ポートを PDFTOSVG_E2E_PORT_FILE のファイルから読む。固定ポートだと 2 本並走したときに
# 混線するため)。辞書はテンポラリに置き、実環境の data/dictionary.json を汚さない。終了は
# fixture のプロセス kill に任せる。
```

`_responds` と `ensure_port_is_free` を**削除**し、代わりに `wait_for_port_file` を `wait_until_serving` の前へ置く。

```python
def wait_for_port_file(
    path: Path, proc: subprocess.Popen, *, timeout: float = 20.0, interval: float = 0.1
) -> int:
    """子プロセス ``proc`` が bind した実ポートを ``path`` へ書くのを待ち、その値を返す。

    子の標準出力を ``readline`` で待つ形にしないのは、子が待ち受けを始めずに固まったとき永久に
    ブロックし、Windows の pipe には ``select`` でタイムアウトを付けられないため。ファイルの出現を
    ポーリングする方が単純で、時間切れも子の死亡も検知できる。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text.isdigit():
                return int(text)
        if proc.poll() is not None:
            raise RuntimeError("e2e server が起動前に終了した: " + _stderr_text(proc))
        time.sleep(interval)
    raise RuntimeError(f"e2e server が {timeout} 秒以内に実ポートを {path} へ書かなかった")
```

`main()` を次にする（`PORT` の既定値 5180 は変えない。`create_server` に渡した後の実ポートを出力し、ファイルが指定されていれば書く）。冒頭の `import` に `from pathlib import Path` を加える。

```python
def main() -> None:
    tmp = tempfile.mkdtemp(prefix="pdftosvg-e2e-")
    store = DictionaryStore(os.path.join(tmp, "dictionary.json"))
    session = WebSession(store, UndoStack())
    # 属性の手組みはしない。同一オリジン検査の許可リスト設定 (`configure_guard`) を
    # 取りこぼすと全リクエストが 403 になるため、構築経路は `create_server` 1 本に畳む。
    server = create_server(str(config.resource_path("web")), session, port=PORT, token=TOKEN)
    actual_port = server.server_address[1]  # PORT=0 のとき OS が選んだ実ポート
    print(f"e2e server listening on http://127.0.0.1:{actual_port}/", flush=True)
    port_file = os.environ.get("PDFTOSVG_E2E_PORT_FILE")
    if port_file:
        # fixture が実ポートを知る経路。書き込み途中を読まれないよう、別名で書いてから置き換える
        tmp_path = port_file + ".tmp"
        Path(tmp_path).write_text(str(actual_port), encoding="utf-8")
        os.replace(tmp_path, port_file)
    server.serve_forever()
```

- [ ] **Step 4: fixture をポート 0 起動へ乗せ換える**

`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` の `PORT = 5181` / `BASE = f"http://127.0.0.1:{PORT}"` の 2 行を削除し、fixture を次にする。冒頭の import を `from .e2e_server import wait_for_port_file, wait_until_serving` に直し、`import tempfile` と `from pathlib import Path` を加える（無ければ）。ファイル冒頭の説明コメント「旧 TS E2E(:5180)と並走できるよう別ポート(:5181)を使う」は「ポートは OS に選ばせる（`e2e_server.py` の説明を参照）」に直す。

```python
@pytest.fixture(scope="module")
def e2e_server():
    # ポート 0 で起動して OS に選ばせ、子が bind した実ポートをファイルで受け取る。固定ポートだと
    # 2 本並走したときに混線する (Windows では SO_REUSEADDR で二重 bind が成功し、接続が
    # どちらへ届くか不定になる) ため、毎回違うポートにして衝突そのものを無くす
    with tempfile.TemporaryDirectory(prefix="pdftosvg-e2e-port-") as tmp:
        port_file = Path(tmp) / "port"
        env = dict(os.environ, PDFTOSVG_E2E_PORT="0", PDFTOSVG_E2E_PORT_FILE=str(port_file))
        proc = subprocess.Popen(
            [sys.executable, os.path.join(os.path.dirname(__file__), "e2e_server.py")],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            port = wait_for_port_file(port_file, proc)
            base = f"http://127.0.0.1:{port}"
            wait_until_serving(proc, base)
            yield base
        finally:
            proc.kill()
            proc.wait()
```

`BASE` を fixture 外で参照している箇所が無いことを `grep -n "BASE\b" pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` で確かめる（fixture 内のみのはず。`page.goto(f"/?token={TOKEN}")` は `base_url` 経由なので影響なし）。

- [ ] **Step 5: テストが通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_e2e_server.py -v`
Expected: PASS（3 件）

- [ ] **Step 6: E2E 全件が通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q`
Expected: PASS（fixture の乗せ換えで起動が壊れていないこと）

- [ ] **Step 7: 非 E2E 全件を確認する**

Run: `py -3.13 -m pytest pdf-to-svg -q`
Expected: PASS

- [ ] **Step 8: 原稿を直す**

`docs/pdf-to-svg/src/設計書.md` の E2E の節で、`ensure_port_is_free` を説明している段落（「E2E のテスト用サーバは `e2e_server.py` がポート 5181 固定で起動する。`e2e_server` fixture は起動する**前**に `ensure_port_is_free` で……」から「E2E を Ctrl+C で中断すると子サーバが残り……再実行する。」まで）を次で置き換える。

```markdown
E2E のテスト用サーバは `e2e_server.py` を **ポート 0** で起動し、OS が選んだ実ポートを子プロセスが `PDFTOSVG_E2E_PORT_FILE` のファイルへ書き、`e2e_server` fixture が `wait_for_port_file` でその出現を待って読む。固定ポートだと 2 本並走したときに混線する——Windows では `ThreadingHTTPServer` の既定 `allow_reuse_address`（`SO_REUSEADDR`）により LISTEN 中のポートへの二重 bind が成功するので、後発の子は死なず、2 つのサーバが同じポートで LISTEN して接続がどちらに届くか不定になる——ため、毎回違うポートにして衝突そのものを無くす。子の標準出力を `readline` で待たないのは、子が固まったとき永久にブロックし、Windows の pipe には `select` でタイムアウトを付けられないため。起動後は `wait_until_serving` が応答を待ち、応答が無いまま子が死んだら stderr を添えて止める。`test_e2e_server.py` が、ポート 0 で起動すると実ポートがファイルに書かれそこで応答すること、2 本同時に起動すると別のポートになること、子が起動前に死んだら待ち続けず止まることを固定する。この方式により E2E は並走できる（以前あった「E2E を別ディレクトリ・別プロセスで並走させてはならない」制約は解消）。
```

`docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md` のテスト表 38 を次で置き換える。

```markdown
| 38 | `test_e2e_server.py::test_port_zero_writes_the_actual_port_to_the_file_and_serves_there` ほか | E2E 用サーバをポート 0 で起動すると OS が選んだ実ポートがファイルに書かれそこで応答すること、2 本同時起動で別ポートになること、子が起動前に死んだら `wait_for_port_file` が待ち続けず `RuntimeError` になること（Edge 不使用の単体） | E2E が並走しても混線しない | 未 |
```

`docs/pdf-to-svg/src/設計正典.md` に E2E の並走禁止に触れる記述があれば（`grep -n "並走" docs/pdf-to-svg/src/設計正典.md`）、「ポート 0 で起動するため並走できる」に直す。無ければ何もしない。

- [ ] **Step 9: コミット**

```bash
git add pdf-to-svg/test/e2e_server.py pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py pdf-to-svg/test/test_e2e_server.py docs/pdf-to-svg/src/設計書.md docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md docs/pdf-to-svg/src/設計正典.md
git commit -m "$(cat <<'EOF'
test(pdf-to-svg): E2E 用サーバをポート 0 で起動し、実ポートをファイルで受け渡して並走できるようにする

Co-Authored-By: <実際に書いた実行主体のモデル名> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

`設計正典.md` に変更が無ければ `git add` から外す。

---

### Task 2: 枠線の太さの範囲をクライアントも検査し、正典を HTML に寄せる

**Files:**
- Modify: `pdf-to-svg/resources/web/app.js`（`wireEditTools` の `widthInput` の `change` ハンドラ、1020 行付近）
- Modify: `pdf-to-svg/src/web/rpc_methods.py`（`BORDER_WIDTH_MIN` / `BORDER_WIDTH_MAX` の位置、480 行付近 → `MAX_COVER_TEXT_CHARS` の隣）
- Modify: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`（新規 E2E 1 件）
- Modify: `docs/pdf-to-svg/src/設計書.md`（8 章ステップ 3 節の入力欄の記述）

**Interfaces:**
- Consumes: `index.html` の `#border-width` の `min="0.5"` / `max="20"`（既存。これが正典）、`S.borderWidth`
- Produces: なし

- [ ] **Step 1: 失敗する E2E を書く**

`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` の `test_undo_after_typing_a_width_then_placing_a_border_undoes_the_border` の直後へ足す。

```python
def test_border_width_outside_the_html_range_is_rejected_and_the_input_is_restored(e2e_page, ocr_layer_pdf):
    """入力欄の max (20) を越える太さを打って確定すると、サーバへ送らず入力欄を直前の妥当な値へ戻す。

    HTML の `min` / `max` はブラウザの number 入力で強制力が弱く、25 と打てば JS はその値を読める。
    JS が HTML の属性を正典として検査しないと、サーバが拒否した値が入力欄に残ったままになる。
    """
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="border"]')
    page.fill("#border-width", "3")
    page.press("#border-width", "Enter")  # 次に置く太さを 3 に確定
    page.fill("#border-width", "25")
    page.press("#border-width", "Enter")
    expect(page.locator("#border-width")).to_have_value("3")  # 弾かれて 3 に戻る
    assert page.evaluate("() => window.__state.borderWidth") == 3
    page.fill("#border-width", "0.2")
    page.press("#border-width", "Enter")
    expect(page.locator("#border-width")).to_have_value("3")
```

- [ ] **Step 2: E2E を走らせて失敗を確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -k outside_the_html_range -v`
Expected: FAIL（25 が `v > 0` を通って `commitBorderStyle` へ渡り、`S.borderWidth` が 25 になる。または入力欄が 25 のまま）

- [ ] **Step 3: JS の検査を HTML の `min` / `max` から読む形にする**

`pdf-to-svg/resources/web/app.js` の `widthInput` の `change` ハンドラを次にする。

```javascript
    widthInput.addEventListener("change", function () {
      // 範囲の正典は HTML の min / max (index.html の #border-width)。ここで数字を書かず属性から読むのは、
      // 範囲を HTML・JS・サーバの 3 箇所に書くとどれかがずれるため (サーバ側の BORDER_WIDTH_MIN/MAX は
      // HTML と揃える旨をコメントで結んである)。number 入力の min / max はブラウザが強制しないので、
      // JS で検査しないと範囲外の値がサーバへ届き、拒否された値が入力欄に残る。
      var v = parseFloat(this.value);
      var lo = parseFloat(this.min), hi = parseFloat(this.max);
      if (!isNaN(v) && v >= lo && v <= hi) { commitBorderStyle({ width: v }); return; }
      // 弾いた値を表示に残すと、`change` は値が変わらない限り再発火しないので「表示だけ嘘」の状態で
      // 次の操作へ進める。直前の妥当な値 (次に置く太さ) へ戻す
      this.value = String(S.borderWidth);
    });
```

`input` イベントのハンドラ（`if (!isNaN(v) && v > 0 && S.borderSel === null) S.borderWidth = v;`）も同じ範囲検査にする。

```javascript
    widthInput.addEventListener("input", function () {
      var v = parseFloat(this.value);
      var lo = parseFloat(this.min), hi = parseFloat(this.max);
      if (!isNaN(v) && v >= lo && v <= hi && S.borderSel === null) S.borderWidth = v;
    });
```

- [ ] **Step 4: サーバ側の定数を裁定どおりの位置へ移す**

`pdf-to-svg/src/web/rpc_methods.py` の `BORDER_WIDTH_MIN = 0.5` / `BORDER_WIDTH_MAX = 20.0`（`_border_width` の直前、480 行付近）を、`MAX_COVER_TEXT_CHARS = 200` の**直後**へ移す。コメントを次にする。

```python
# 手動の上書きの置換語の上限文字数 (外部由来の入力なので上限を置く)。
MAX_COVER_TEXT_CHARS = 200

# 枠線の太さの範囲 (pt)。正典は `resources/web/index.html` の `#border-width` の `min` / `max` で、
# クライアントはその属性を読んで検査する。サーバは HTML を読めないので同じ値をここに持つ。
# 片方だけ変えると、UI で打てる値がサーバで拒否される (または逆)。
BORDER_WIDTH_MIN = 0.5
BORDER_WIDTH_MAX = 20.0
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -k "outside_the_html_range or border" -v`
Expected: PASS

Run: `py -3.13 -m pytest pdf-to-svg -q`
Expected: PASS

- [ ] **Step 6: 設計書を直す**

`docs/pdf-to-svg/src/設計書.md` 8 章ステップ 3 節の、入力欄の二面性を説明している箇条書き（「箱をクリックして選ぶと、枠線なら色・太さの入力欄……」）の末尾へ 1 文足す。

```markdown
太さの範囲の正典は `index.html` の `#border-width` の `min` / `max`（0.5〜20 pt）で、JS の `change` ハンドラはその属性を読んで検査し、範囲外なら「次に置く太さ」へ戻す（number 入力の `min` / `max` はブラウザが強制しないため）。サーバ側の `BORDER_WIDTH_MIN` / `BORDER_WIDTH_MAX` は同じ値を持ち、HTML と揃える旨のコメントで結ぶ。
```

- [ ] **Step 7: コミット**

```bash
git add pdf-to-svg/resources/web/app.js pdf-to-svg/src/web/rpc_methods.py pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py docs/pdf-to-svg/src/設計書.md
git commit -m "$(cat <<'EOF'
fix(pdf-to-svg): 枠線の太さの範囲を HTML の min/max を正典にしてクライアントでも検査する

Co-Authored-By: <実際に書いた実行主体のモデル名> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

---

### Task 3: 削除ボタン同期の取りこぼし・削除直後の選択解除・名前衝突

**Files:**
- Modify: `pdf-to-svg/resources/web/rect-overlay.js`（`draw()` と mouseup の `if (!svgEl) return;`、内部関数 `clearSel` の改名）
- Modify: `pdf-to-svg/resources/web/app.js`（`btn-deletesel` の click ハンドラ、1037 行付近）
- Modify: `pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py`（早期 return でも同期が呼ばれる単体）
- Modify: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`（`test_delete_button_is_enabled_by_a_border_selection` を拡張）

**Interfaces:**
- Consumes: `ui.syncDeleteButton`（既存。`app.js` が `deps` で渡す）
- Produces: `createRectOverlay` の返り値のキーは `{ draw, installDrag, clearSel }` のまま（内部名だけ `clearOverlaySel`）

- [ ] **Step 1: 失敗するテストを書く（単体）**

`pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py` の `SETUP` の `ui` に呼び出し回数を数える `syncDeleteButton` を足し、テストを 1 件足す。

`SETUP` の `ui` 定義を次にする。

```javascript
  const ui = {
    rpc: () => new Promise((resolve) => { pending.push(resolve); }),
    afterEdit: async () => {},
    pageOf: () => ({ fileIndex: 0, pageInFile: 0 }),
    syncCalls: 0,
    syncDeleteButton() { this.syncCalls++; },
  };
```

`window.__ro = { host, pending, ov, promises: [], saved, st, ui };` と `ui` も退避する。

テストを足す。

```python
def test_draw_syncs_the_delete_button_even_when_the_svg_is_missing(ro):
    """host に svg が無いとき draw() は早期 return するが、押下可否の同期は飛ばさない
    (「選択が変わる全経路から呼ぶ」に穴を作らない)。"""
    before = js(ro, "window.__ro.ui.syncCalls")
    js(ro, "(() => { const c = window.__ro; c.host.querySelector('svg').remove(); return 0; })()")
    js(ro, "window.__ro.ov.draw(window.__ro.host)")
    after = js(ro, "window.__ro.ui.syncCalls")
    assert after == before + 1
    # svg を戻す (後続のテストのため)
    js(ro, "(() => { window.__ro.host.innerHTML = '<svg viewBox=\"0 0 300 200\" width=\"300\" height=\"200\"></svg>'; return 0; })()")
```

- [ ] **Step 2: 失敗するテストを書く（E2E）**

`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` の `test_delete_button_is_enabled_by_a_border_selection` を次で置き換える（削除直後に**同期的に**無効になることまで確かめる）。

```python
def test_delete_button_is_enabled_by_a_border_selection_and_disabled_right_after_deleting(e2e_page, ocr_layer_pdf):
    """枠線を選んだときに「削除」ボタンが有効になり、削除した直後には (一覧の再取得を待たず) 無効に戻る。

    削除の直後は `S.borderSel` に削除済みの id が残ったまま `render()` が走るため、以前は非同期の
    一覧再取得が届くまで一瞬ボタンが有効のままだった。削除のハンドラで選択を即座に解く。
    """
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    _place_border(page)
    page.locator("#trim-stage .border-box").click()
    expect(page.locator("#btn-deletesel")).to_be_enabled()
    page.click("#btn-deletesel")
    # 削除の RPC 往復を待たずに、クリック直後の同期処理で無効になっていること
    assert page.evaluate("() => window.__state.borderSel") is None
    expect(page.locator("#btn-deletesel")).to_be_disabled()
    expect(page.locator("#trim-stage .border-box")).to_have_count(0)
```

- [ ] **Step 3: テストを走らせて失敗を確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py -v`
Expected: 新規 1 件 FAIL（`after == before`）

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -k "disabled_right_after_deleting" -v`
Expected: FAIL（`borderSel` が削除済み id のまま、またはボタンが一瞬有効）

- [ ] **Step 4: `rect-overlay.js` を直す**

早期 return の 2 箇所を、同期してから return する形にする。`draw()`:

```javascript
    var svgEl = host.querySelector("svg");
    if (!svgEl) { if (ui.syncDeleteButton) ui.syncDeleteButton(); return; }
```

`installDrag` の mouseup（`var svgEl = host.querySelector("svg"); if (!svgEl) return;` の箇所）も同じ形に。

内部関数 `clearSel` を `clearOverlaySel` に改名する（定義・`draw()` 内の 2 呼び出し・返り値）。返り値のキーは維持する。

```javascript
  return { draw: draw, installDrag: installDrag, clearSel: clearOverlaySel };
```

`clearOverlaySel` のコメント冒頭に 1 文足す: 「`state.js` が export する `clearSel`（ページレールの選択を解く）と同名にならないよう、内部名はこれにする。公開名は呼び出し側（`cover.js` / `border.js`）を変えないため `clearSel` のまま。」

- [ ] **Step 5: `app.js` の削除ハンドラを直す**

`btn-deletesel` の click ハンドラで、`applyDelete` の `await` の直後・`afterEdit()` の前に 2 行足す。

```javascript
      await rpc("applyDelete", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elIds: ids });
      // 削除した要素の選択を即座に解く。残すと `afterEdit` → `render()` → `syncDeleteButton()` が
      // 削除済みの id を見て有効のままにし、非同期の一覧再取得が届くまでボタンが一瞬ずれる
      S.coverSel = null;
      S.borderSel = null;
      await afterEdit();
```

> **訂正（実装時、2026-09-17）:** 上の 2 行（`S.coverSel = null; S.borderSel = null;`）は
> `await rpc("applyDelete", ...)` の**前**（`ids` を確定した直後）に置く。上記のとおり `await` の後に
> 置くと、E2E `test_delete_button_is_enabled_by_a_border_selection_and_disabled_right_after_deleting`
> の `page.evaluate` が RPC の完了前に `S.borderSel` を読み、9 回中 7 回失敗した（Playwright の往復と
> RPC 往復 15〜16 ms の競合）。削除はクリック時点で確定した利用者の意図なので、選択の解除を RPC の前に
> 行っても問題はない（RPC が失敗した場合は選択が外れて要素が残るだけで、再選択すれば済む）。
> コミット `3d3623d` はこの配置で実装している。

- [ ] **Step 6: テストが通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py -v`
Expected: PASS（全件）

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q`
Expected: PASS（全件）

- [ ] **Step 7: コミット**

```bash
git add pdf-to-svg/resources/web/rect-overlay.js pdf-to-svg/resources/web/app.js pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py
git commit -m "$(cat <<'EOF'
fix(pdf-to-svg): 削除ボタンの押下可否を早期 return と削除直後でも同期し、オーバーレイの内部名の衝突を解く

Co-Authored-By: <実際に書いた実行主体のモデル名> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

---

### Task 4: `rect-overlay.js` の `state.js` 依存を外し、E2E の独自ポーリングを標準の待ち方へ

**Files:**
- Modify: `pdf-to-svg/resources/web/rect-overlay.js`（`import { S }` の除去、`opts.isActive`）
- Modify: `pdf-to-svg/resources/web/cover.js` / `border.js`（`isActive` を渡し、`tool` を外す）
- Modify: `pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py`（`S` を触らない形へ）
- Modify: `pdf-to-svg/test/conftest.py`（`edge_page` docstring）
- Modify: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`（`_poll_borders` → `wait_for_function`）
- Modify: `docs/pdf-to-svg/src/設計書.md`（JS モジュール表の `rect-overlay.js` 行、改訂履歴 2.19）、`docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`（テスト表 39〜）
- Regenerate: `docs/pdf-to-svg/pdf-to-svg_設計.html`

**Interfaces:**
- Consumes: `createRectOverlay(opts)`（Task 3 まで）
- Produces: `opts.isActive: () -> boolean`（必須。true のときだけ `draw()` が箱を描く）。`opts.tool` は廃止

- [ ] **Step 1: 失敗するテストを書く（単体）**

`pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py` の `SETUP` を、`S` を一切触らない形にする。

- `const st = await import('/state.js');` と `st.S.phase = 3; st.S.tool = "cover";` と `saved` を削除
- `createRectOverlay` の引数から `tool: "cover"` を外し、`isActive: () => window.__roActive !== false` を足す
- `window.__ro = { host, pending, ov, promises: [], ui };`
- `window.__roTeardown` は `c.host.remove(); delete window.__ro;` だけにする（`S` の復元は不要）

テストを 1 件足す。

```python
def test_draw_does_nothing_but_clear_when_not_active(ro):
    """isActive() が false のとき draw() は箱を描かず選択を解くだけ (以前は S.phase / S.tool を直接
    読んでいた判定。opts 経由にして rect-overlay.js を state.js から切り離す)。"""
    js(ro, "(() => { window.__roActive = false; return 0; })()")
    try:
        n = js(ro, "(() => { const c = window.__ro; c.promises.push(c.ov.draw(c.host)); return c.pending.length; })()")
        # RPC は呼ばれない (pending が増えない)
        assert n == js(ro, "window.__ro.pending.length")
        assert _box_ids(ro) == []
    finally:
        js(ro, "(() => { window.__roActive = true; return 0; })()")
```

ただし、このテストは既存テストの `pending` の状態に依存するので、**ファイル内の最初のテストとして置く**（`test_draw_discards_a_stale_list_...` の前）。既存テストの `pending[0]` / `pending[1]` の添字がずれないよう、このテストでは RPC を発生させない（`isActive` が false なら `draw()` は RPC の前に return する）ことを利用する。

> **訂正（実装時、2026-09-17）:** 新規テストでは `c.promises.push(c.ov.draw(c.host))` とせず `c.ov.draw(c.host);`
> とだけ書く。`ro` fixture は module スコープで `window.__ro.promises` をファイル内の全テストが共有しており、
> 新規テストが `promises[0]` を占めると既存テストが読む `promises[1]` / `promises[0]` の添字がずれ、まだ
> 解決していない `pending` を待つ `page.evaluate` が無期限に止まる（実測では 300〜360 秒後にブラウザが
> 応答不能になり `TargetClosedError`）。上の説明は `pending` の添字だけを見て `promises` を見落としていた。
> `isActive()` が false の `draw()` は `await` に到達せず同期で終わるので、追跡する必要もない。
> コミット `6bc9637` はこの形で実装している。

- [ ] **Step 2: テストを走らせて失敗を確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py -v`
Expected: FAIL（`isActive` を渡しても `draw()` は `S.phase` / `S.tool` を見るので、`S.phase` が 3 でなければ全部 return し、既存テストも壊れる。または `opts.tool` が無くて `S.tool !== undefined` が常に真で何も描かない）

- [ ] **Step 3: `rect-overlay.js` を `opts` だけで動く形にする**

- `import { S } from "./state.js";` を削除
- `draw()` の `if (S.phase !== 3 || S.tool !== opts.tool) { clearOverlaySel(); return; }` を
  `if (!opts.isActive()) { clearOverlaySel(); return; }` に
- ファイル冒頭のコメント「両者で違うのは『どの一覧 RPC を引くか』『選択したとき入力欄に何を映すか』だけなので、それを `opts` で受け取る」に「『いまこのオーバーレイを描くべきか』（`isActive`）」を加える。`state.js` に依存しないことも 1 文で書く（「このファイルは `S` を読まない。手順やツールの状態は `opts.isActive()` で受け取る。単体テストが共有ページの `S` を書き換えずに済み、部品として本当に `opts` だけで動く」）

- [ ] **Step 4: `cover.js` / `border.js` を直す**

`cover.js` の `createRectOverlay({ ... })` から `tool: "cover",` を外し、次を足す。

```javascript
    isActive: function () { return S.phase === 3 && S.tool === "cover"; },
```

`border.js` も同様に `tool: "border",` を外し `isActive: function () { return S.phase === 3 && S.tool === "border"; },` を足す。

- [ ] **Step 5: `conftest.py` の規約を直す**

`edge_page` fixture の docstring に前回足した「`/state.js` の `S` を書き換えるテストは、fixture の teardown で元の値へ戻すこと……」の文を次に差し替える。

```
`/state.js` の `S` はモジュールシングルトンで、このページを共有する全テストに見える。
browser テストは原則 `S` を書き換えない（部品側が状態を `opts` で受け取る形にしてある）。
やむを得ず書き換えるときは fixture の teardown で元の値へ戻すこと。`edge_page` は session スコープで、
`pytest-randomly` を入れない運用のため順序に依存した汚染は黙って通る。
```

- [ ] **Step 6: `_poll_borders` を `wait_for_function` に置き換える**

`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` の `_poll_borders` の定義を次で置き換える（`eval` による関数の再構成を止め、Playwright 標準の待ち方にする。呼び出し側の引き渡し方は変えない）。

```python
def _poll_borders(page, predicate_src, timeout_ms=3000):
    """`borderList` の結果が `predicate_src`（JS の関数式。引数は borders 配列）を満たすまで待ち、
    満たした時点の borders を返す。Playwright の `wait_for_function` に任せる（以前は文字列を
    `eval` で関数に戻して自前でポーリングしていた）。Python ↔ JS を往復するたびに競合の窓が開くので、
    待機と読み取りをブラウザ側の 1 回で済ませる。"""
    handle = page.wait_for_function(
        """async ([src]) => {
            const pred = (0, eval)(src);
            const r = await window.rpc("borderList", { fileIndex: 0, pageInFile: 0 });
            return pred(r.borders) ? r.borders : false;
        }""",
        arg=[predicate_src],
        timeout=timeout_ms,
        polling=100,
    )
    return handle.json_value()
```

`predicate_src` に関数式の文字列を渡す既存の呼び出し（`test_border_overlay_resize_and_width_change` 等）は変えなくてよい。`(0, eval)(src)` は間接 eval で、Playwright の `wait_for_function` の引数として関数式を受ける最小の形。**もし呼び出し側が全部「特定の値になるまで待つ」だけなら**、`predicate_src` を止めて `expected` の値を渡す形へ単純化してよい（例: `_wait_border_width(page, 7)`）。呼び出し側を読んで判断し、報告に書くこと。

> **訂正（実装時、2026-09-17）:** 上のコード例は実際には動かない。実測で 2 点が分かった。
> (a) `wait_for_function` に async の述語を渡すと 1 回しか呼ばれず、その戻り値をそのまま最終結果にして
> ポーリングしない（`polling` の指定を変えても同じ）。(b) 本アプリの応答には CSP（`default-src 'self'`、
> `unsafe-eval` なし）が付いており、`wait_for_function` の述語内で `eval` を呼ぶと `EvalError` になる
> （通常の `page.evaluate` は CDP 経由で CSP の対象にならないため、旧実装では通っていた）。
> 実装では、`borderList` の取得を `setInterval` でブラウザ側の裏更新に出し、述語は同期関数にし、関数式の
> 実体化は `evaluate_handle` で 1 回だけ行って JSHandle を `wait_for_function` へ渡す。引数名 `predicate_js`
> と述語形の契約、呼び出し側 3 箇所は変えていない（呼び出しの 1 つが `w > 100 && h > 25` の述語なので、
> 期待値 1 個への単純化は成立しない）。コミット `6bc9637` を参照。

- [ ] **Step 7: テストが通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py -v`
Expected: PASS（全件。`S` を触らないので teardown も単純化）

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_state_js.py -v`
Expected: PASS（`rect_overlay` テストが `S` を汚さなくなったことの間接確認）

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q`
Expected: PASS

Run: `py -3.13 -m pytest pdf-to-svg -q`
Expected: PASS

- [ ] **Step 8: 原稿を直す**

`docs/pdf-to-svg/src/設計書.md` の JS モジュール表、`rect-overlay.js` の行の「`opts` で受け取るのは箱の CSS クラス・対象ツール名・一覧 RPC と応答キー・更新 RPC・選択とドラッグ状態の出し入れ・選択が変わったときの入力欄同期の 6 点だけで」を次に直す。

```markdown
`opts` で受け取るのは箱の CSS クラス・いま描くべきかの判定（`isActive`）・一覧 RPC と応答キー・更新 RPC・選択とドラッグ状態の出し入れ・選択が変わったときの入力欄同期の 6 点だけで、`state.js` の `S` は読まない（手順やツールの状態は `isActive` で受け取る。単体テストが共有ページの `S` を書き換えずに済み、部品として本当に `opts` だけで動く）。
```

改訂履歴に 2.19 を足し、`version: "2.19"` に上げる。

```markdown
  - 2.19 | 2026-09-17 | E2E 用サーバをポート 0 起動 + 実ポートのファイル受け渡しにして並走可能に（13 章）、枠線の太さの範囲の正典を `index.html` の `min`/`max` に寄せクライアントでも検査（8 章）、`rect-overlay.js` から `state.js` 依存を外し `opts.isActive` で受け取る形に（JS モジュール表）、削除ボタン同期の早期 return と削除直後の選択解除、内部名 `clearOverlaySel`
```

`docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md` のテスト表末尾へ足す（項番は既存の続き）。

```markdown
| 40 | `test_pdftosvg_app_flow_e2e.py::test_border_width_outside_the_html_range_is_rejected_and_the_input_is_restored` | 入力欄の `max` を越える太さを確定すると、JS が HTML の `min`/`max` を読んで弾き、入力欄を直前の妥当な値へ戻すこと（E2E） | 範囲外の太さがサーバへ届かず入力欄に残らない | 未 |
| 41 | `test_pdftosvg_rect_overlay_js.py::test_draw_syncs_the_delete_button_even_when_the_svg_is_missing` / `::test_draw_does_nothing_but_clear_when_not_active`、`test_pdftosvg_app_flow_e2e.py::test_delete_button_is_enabled_by_a_border_selection_and_disabled_right_after_deleting` | `draw()` の早期 return でも押下可否を同期すること、`isActive()` が false なら RPC を呼ばず選択だけ解くこと（実ブラウザ単体）、削除直後に一覧の再取得を待たずボタンが無効に戻ること（E2E） | 押下可否の同期に穴が無く、`rect-overlay.js` が `S` に依存しない | 未 |
```

- [ ] **Step 9: HTML を再生成する**

Run: `py -3.13 docs/_build/build_all.py --project pdf-to-svg`
Expected: `docs/pdf-to-svg/pdf-to-svg_設計.html` が更新される（Task 1〜4 の原稿変更をまとめて反映）

- [ ] **Step 10: 原稿まわりのテストを走らせる**

Run: `py -3.13 -m pytest docs/_build -q`
Expected: PASS

Run: `py -3.13 -m pytest scripts -q`
Expected: PASS

- [ ] **Step 11: コミット**

```bash
git add pdf-to-svg/resources/web/rect-overlay.js pdf-to-svg/resources/web/cover.js pdf-to-svg/resources/web/border.js pdf-to-svg/test/test_pdftosvg_rect_overlay_js.py pdf-to-svg/test/conftest.py pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py docs/pdf-to-svg/src/設計書.md docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md docs/pdf-to-svg/pdf-to-svg_設計.html docs/superpowers/plans/2026-09-17-pdftosvg-step3-debt.md
git commit -m "$(cat <<'EOF'
refactor(pdf-to-svg): rect-overlay.js の state.js 依存を opts.isActive に置き換え、E2E の独自ポーリングを標準の待ち方にする

Co-Authored-By: <実際に書いた実行主体のモデル名> <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

計画書（`docs/superpowers/plans/2026-09-17-pdftosvg-step3-debt.md`）はこのコミットへ同梱する。

---

## 完了の確認

すべてのタスクを終えたら、pre-push フックと同じ順で通しておく（Task 1 完了後は E2E を並走させてもよいが、pre-push は 1 本ずつ順に走る）。

```
py -3.13 scripts/check_comments.py
py -3.13 -m pytest scripts
py -3.13 -m pytest docs/_build
py -3.13 -m pytest pdf-to-svg
py -3.13 -m pytest graph-editor
py -3.13 -m pytest pdf-to-svg -m e2e
py -3.13 -m pytest graph-editor -m e2e
```

さらに、**E2E を 2 本同時に走らせて両方通る**ことを確かめる（Task 1 の目的そのもの）。

```
py -3.13 -m pytest pdf-to-svg -m e2e -q &
py -3.13 -m pytest pdf-to-svg -m e2e -q
```

完了後にコントローラが行うこと: GitHub リリース `2026.09.08` を HEAD へ差し替え（タグ移動 + ノート追記）、メモリ `e2e-never-run-in-parallel` を「並走できるようになった」へ更新。
