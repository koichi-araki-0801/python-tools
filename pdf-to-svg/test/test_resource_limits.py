"""資源上限の退行ガード。

「正しい入力を正しく処理する」ではなく**「迂回入力で破綻しない」**を主張する形で書く。
所要時間ではなく**上限が効くこと**を見る (実時間はマシン依存で脆い): 上限に当たったら
拒否するか degrade して**必ず返る**こと、そして上限が正常系を壊していないこと。
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from engine import pdf_engine
from engine.pdf_engine import (
    MAX_RASTER_PIXELS,
    MIN_RENDER_SCALE,
    ElementBudget,
    RasterBudget,
    _match_seqno,
    _PageElements,
    _render_background,
    _SeqnoIndex,
)
from model.document import Page
from model.elements import Rect, TextElement
from web import origin_guard
from web import server as server_mod
from web.server import MAX_RPC_BYTES, MAX_UPLOAD_BYTES

fitz = pytest.importorskip("fitz")


def _page_of(width_pt: float, height_pt: float):
    """指定 MediaBox の 1 ページ PDF を開いて返す (呼び出し側で close)。"""
    doc = fitz.open()
    doc.new_page(width=width_pt, height=height_pt)
    return doc


# ── ラスタ化のピクセル予算 ────────────────────────────────────────────

def test_huge_mediabox_is_rendered_within_the_pixel_budget():
    """20000x20000 pt の PDF は実体 3.6KB で 4.8 GB を確保し 36〜42 秒かかっていた。

    倍率を下げて上限内へ収め、秒オーダーで返ることを主張する。
    """
    doc = _page_of(20_000, 20_000)
    try:
        t0 = time.perf_counter()
        bg = _render_background(doc[0], RasterBudget())
        elapsed = time.perf_counter() - t0
    finally:
        doc.close()
    # `MIN_RENDER_SCALE` まで下げても 20000x20000 は上限を超えるので背景は諦める。
    assert bg is None
    assert elapsed < 5.0


def test_scale_is_reduced_rather_than_refused_when_it_fits():
    """縮小すれば収まるページは degrade して背景を作る (無言の停止より可視な劣化)。"""
    # 5000x5000 pt: 等倍で 25M px (上限超過)、0.5 倍で 6.25M px (収まる)。
    doc = _page_of(5_000, 5_000)
    try:
        bg = _render_background(doc[0], RasterBudget())
    finally:
        doc.close()
    assert bg is not None
    # rect は論理座標のままで、ラスタ倍率が変わっても配置は変わらない。
    assert bg.rect.w == pytest.approx(5_000)


def test_document_budget_stops_many_in_limit_pages():
    """1 ページの上限だけでは「上限内のページを大量に並べる」形を止められない。"""
    budget = RasterBudget(total=MAX_RASTER_PIXELS)  # 1 ページぶんだけの予算
    doc = _page_of(2_000, 2_000)  # 等倍 16M px = ちょうど上限
    try:
        first = _render_background(doc[0], budget)
        second = _render_background(doc[0], budget)
    finally:
        doc.close()
    assert first is not None
    assert second is None


def test_a4_at_the_default_scale_is_untouched():
    """通常の A4 は上限にかからない (上限が正当な運用を止めていないこと)。"""
    doc = _page_of(595, 842)
    try:
        bg = _render_background(doc[0], RasterBudget())
    finally:
        doc.close()
    assert bg is not None
    assert MIN_RENDER_SCALE < 1.0  # 縮小の下限は 1.0 未満 (縮小が起きうる形)


# ── リクエスト本文の上限 ─────────────────────────────────────────────

# 使い捨てサーバの固定セッショントークン (本番は起動ごとの CSPRNG 値)。認可の主張は
# `test/test_origin_guard.py` が持ち、ここは資源上限だけを見る。
_TOKEN = "resource-limits-test-token"


def _post(base: str, path: str, body: bytes, content_length: int | None = None,
          content_type: str = "application/json"):
    """A2 の Origin/Host/content-type/トークンのガードを満たした上で本文上限だけを試す。"""
    req = urllib.request.Request(base + path, data=body, method="POST")
    if content_length is not None:
        req.add_header("Content-Length", str(content_length))
    req.add_header("Origin", base)
    req.add_header("X-Session-Token", _TOKEN)
    req.add_header("Content-Type", content_type)
    return urllib.request.urlopen(req, timeout=10)


@pytest.fixture()
def running_server(tmp_path):
    import config
    from dictionary.store import DictionaryStore
    from web.rpc_methods import WebSession
    from web.server import create_server
    from web.undo_stack import UndoStack

    session = WebSession(DictionaryStore(tmp_path / "dict.json"), UndoStack())
    server = create_server(str(config.resource_path("web")), session, token=_TOKEN)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        session.store.close()


def test_oversized_upload_is_refused_without_reading_the_body(running_server):
    """申告値だけで 413 にする。実体を送りつけなくても拒否されること = 読み切っていない。"""
    with pytest.raises(urllib.error.HTTPError) as ei:
        _post(running_server, "/upload?name=x.pdf", b"", MAX_UPLOAD_BYTES + 1,
              content_type="application/octet-stream")
    assert ei.value.code == 413


def test_oversized_rpc_is_refused(running_server):
    with pytest.raises(urllib.error.HTTPError) as ei:
        _post(running_server, "/rpc", b"", MAX_RPC_BYTES + 1)
    assert ei.value.code == 413


def test_malformed_content_length_is_refused(running_server):
    with pytest.raises(urllib.error.HTTPError) as ei:
        _post(running_server, "/rpc", b"", -1)
    assert ei.value.code == 413


def test_normal_rpc_still_works(running_server):
    """上限が正常系を壊していないこと (拒否だけを固定すると気付けない)。"""
    body = json.dumps({"method": "state", "args": {}}).encode("utf-8")
    with _post(running_server, "/rpc", body) as res:
        payload = json.loads(res.read())
    assert payload["ok"] is True


# ── Undo スタックの深さ上限 ──────────────────────────────────────────

def test_undo_stack_drops_the_oldest_beyond_the_depth_limit():
    """各コマンドは置換前後の要素状態を握るので、無制限に積むとメモリが単調増加する。"""
    from web.undo_stack import MAX_UNDO_DEPTH, UndoStack

    class Noop:
        def redo(self):
            pass

        def undo(self):
            pass

    st = UndoStack()
    for _ in range(MAX_UNDO_DEPTH + 50):
        st.push(Noop())
    assert len(st._stack) == MAX_UNDO_DEPTH
    # 上限に当たっても「戻れる」状態は保たれる (degrade であって機能停止ではない)。
    assert st.canUndo() is True
    for _ in range(MAX_UNDO_DEPTH):
        st.undo()
    assert st.canUndo() is False


# ── seqno 照合の索引と要素数予算 ──────────────────────────────────────

def _rect(x, y, w, h) -> Rect:
    return Rect(x, y, w, h)


def test_seqno_index_returns_the_same_answer_as_the_linear_scan():
    """索引化は**結果を変えない**高速化であること (同点の解決順まで含めて)。"""
    candidates = []
    for i in range(200):
        candidates.append((i, _rect(10 + (i % 7) * 12, i * 4.0, 30, 9)))
    # 完全に同じ矩形を 2 つ置き、同点は「元の並びが先」を採ることまで見る。
    candidates.append((900, _rect(10, 40, 30, 9)))
    queries = [_rect(10, 40, 30, 9), _rect(0, 0, 5, 5), _rect(12, 100, 20, 8),
               _rect(-5, 380, 60, 30)]
    index = _SeqnoIndex(candidates)
    for q in queries:
        assert index.match(q, -1) == _match_seqno(q, candidates, -1)


def _count_overlap_calls(monkeypatch) -> list:
    """`_overlap_area` の呼び出し回数を数える (= 1 クエリの実走査量)。"""
    calls: list = []
    original = pdf_engine._overlap_area

    def counting(a, b):
        calls.append(1)
        return original(a, b)

    monkeypatch.setattr(pdf_engine, "_overlap_area", counting)
    return calls


def test_seqno_index_only_scans_candidates_in_the_same_row_band(monkeypatch):
    """1 クエリの走査量が候補数に比例しないこと (これが O(n^2) を切る本体)。"""
    candidates = [(i, _rect(10, i * 20.0, 30, 9)) for i in range(5_000)]
    index = _SeqnoIndex(candidates)
    scanned = _count_overlap_calls(monkeypatch)
    seqno = index.match(_rect(10, 4_000.0, 30, 9), -1)
    assert seqno == 200  # 4000 / 20
    # 5000 件の候補を持つ索引でも、見るのは同じ行バンドのごく一部だけ。
    assert len(scanned) <= 8


def test_seqno_index_gives_up_when_flooded_with_page_tall_candidates():
    """バンドに載らない巨大 bbox を敷き詰められたら**照合を諦める** (回し続けない)。"""
    big = 2_147_483_648.0
    flood = [(i, _rect(-big, -big, big * 2, big * 2))
             for i in range(pdf_engine._SEQNO_MAX_TALL + 1)]
    index = _SeqnoIndex(flood)
    assert index.degraded is True
    # 諦めた場合は既定値 (= 抽出順のフォールバック) を返し、例外にはしない。
    assert index.match(_rect(0, 0, 10, 10), 7) == 7


def test_seqno_index_is_not_even_built_beyond_the_candidate_cap(monkeypatch):
    """候補が桁違いなら索引を組まずに諦める (構築コストも候補数に比例するため)。"""
    monkeypatch.setattr(pdf_engine, "_SEQNO_MAX_CANDIDATES", 10)
    index = _SeqnoIndex([(i, _rect(0, i * 20.0, 10, 10)) for i in range(11)])
    assert index.degraded is True and index.bands == {}
    assert index.match(_rect(0, 0, 10, 10), 3) == 3


def test_seqno_scan_limit_bounds_a_single_query(monkeypatch):
    """同一バンドへ候補を敷き詰めても 1 クエリの走査数は上限で頭打ちになる。"""
    candidates = [(i, _rect(0, 0, 10, 10)) for i in range(pdf_engine._SEQNO_MAX_SCAN * 3)]
    index = _SeqnoIndex(candidates)
    scanned = _count_overlap_calls(monkeypatch)
    index.match(_rect(0, 0, 10, 10), -1)
    assert len(scanned) <= pdf_engine._SEQNO_MAX_SCAN


def test_page_element_budget_truncates_instead_of_growing_without_bound(monkeypatch):
    """1 ページの要素数上限に当たったら切り捨て、`truncated` を立てる。"""
    monkeypatch.setattr(pdf_engine, "MAX_PAGE_ELEMENTS", 3)
    page = Page(index=0, width_pt=100, height_pt=100)
    sink = _PageElements(page, ElementBudget())
    added = [sink.add(TextElement(bbox=_rect(0, 0, 1, 1), text="x")) for _ in range(5)]
    assert added == [True, True, True, False, False]
    assert len(page.elements) == 3
    assert page.truncated is True and sink.full is True


def test_document_element_budget_stops_many_in_limit_pages():
    """ページ上限だけでは「上限内のページを大量に並べる」形を止められない。"""
    budget = ElementBudget(total=2)
    first, second = Page(index=0, width_pt=1, height_pt=1), Page(index=1, width_pt=1, height_pt=1)
    a, b = _PageElements(first, budget), _PageElements(second, budget)
    assert a.add(TextElement(bbox=_rect(0, 0, 1, 1), text="x")) is True
    assert b.add(TextElement(bbox=_rect(0, 0, 1, 1), text="y")) is True
    assert b.add(TextElement(bbox=_rect(0, 0, 1, 1), text="z")) is False
    assert second.truncated is True and first.truncated is False


def test_extract_page_honours_the_element_budget(monkeypatch, vector_pdf):
    """予算は `_extract_page` の実経路まで配線されている (機構だけ作って未接続にしない)。"""
    monkeypatch.setattr(pdf_engine, "MAX_PAGE_ELEMENTS", 2)
    doc = fitz.open(str(vector_pdf))
    try:
        page = pdf_engine._extract_page(doc[0], 0, RasterBudget(), ElementBudget())
    finally:
        doc.close()
    assert len(page.elements) == 2
    assert page.truncated is True


# ── 辞書取り込みの上限とバッチ化 ─────────────────────────────────────

def _dict_json(count: int, prefix: str = "w") -> str:
    return json.dumps([{"source": f"{prefix}{i}", "target": f"t{i}"} for i in range(count)])


def test_dictionary_import_writes_the_file_once_regardless_of_entry_count(tmp_path):
    """N 件の取り込みで保存も索引再構築も **1 回**だけ (1 件ごとだと N 回 = O(N^2) 書き込み)。"""
    from dictionary import store as store_mod

    src = tmp_path / "shared.json"
    src.write_text(_dict_json(300), encoding="utf-8")
    s = store_mod.DictionaryStore(tmp_path / "d.json")
    saves, rebuilds = [], []
    original_save, original_rebuild = s._save, s._rebuild_index
    s._save = lambda: (saves.append(1), original_save())[1]
    s._rebuild_index = lambda: (rebuilds.append(1), original_rebuild())[1]

    result = s.import_json(src)

    assert result.imported == 300
    assert len(saves) == 1 and len(rebuilds) == 1
    assert s.lookup("w299") == "t299"
    s.close()


def test_dictionary_import_beyond_the_entry_cap_is_refused_without_changing_anything(tmp_path):
    """上限超過は**何も変更せず**拒否する (途中まで書いた辞書を残さない)。"""
    from dictionary import store as store_mod

    src = tmp_path / "huge.json"
    src.write_text(_dict_json(store_mod.MAX_DICT_ENTRIES + 1), encoding="utf-8")
    path = tmp_path / "d.json"
    s = store_mod.DictionaryStore(path)
    s.add("keep", "残す")

    with pytest.raises(ValueError) as ei:
        s.import_json(src)

    assert "上限" in str(ei.value)
    assert [m.source_raw for m in s.all()] == ["keep"]
    assert json.loads(path.read_text(encoding="utf-8"))[0]["source"] == "keep"
    s.close()


def test_dictionary_import_of_duplicates_is_not_counted_against_the_cap(tmp_path):
    """同じ辞書を上限ちょうどで再取り込みしても拒否されない (重複は増えない)。"""
    from dictionary import store as store_mod

    src = tmp_path / "shared.json"
    src.write_text(_dict_json(store_mod.MAX_DICT_ENTRIES), encoding="utf-8")
    s = store_mod.DictionaryStore(tmp_path / "d.json")

    first = s.import_json(src)
    second = s.import_json(src)  # 2 回目も同じキーなので新規は 0 件

    assert first.imported == second.imported == store_mod.MAX_DICT_ENTRIES
    assert len(s.all()) == store_mod.MAX_DICT_ENTRIES
    s.close()


def test_oversized_dictionary_file_is_not_loaded_into_memory(tmp_path, monkeypatch):
    """件数上限はパース後にしか効かない。載せる前にバイト数で足切りすること。"""
    from dictionary import store as store_mod

    monkeypatch.setattr(store_mod, "MAX_DICT_FILE_BYTES", 64)
    path = tmp_path / "d.json"
    path.write_text(_dict_json(50), encoding="utf-8")  # 64 バイト超

    s = store_mod.DictionaryStore(path)

    assert s.all() == []
    assert s.load_failed is True  # 黙って空にせず「読めなかった」を伝える
    with pytest.raises(ValueError):
        s.import_json(path)
    s.close()


def test_dictionary_add_beyond_the_entry_cap_is_refused(tmp_path, monkeypatch):
    """1 件ずつの追加にも同じ上限が効く (取り込み口だけ塞いでも意味がない)。"""
    from dictionary import store as store_mod

    monkeypatch.setattr(store_mod, "MAX_DICT_ENTRIES", 2)
    s = store_mod.DictionaryStore(tmp_path / "d.json")
    s.add("a", "あ")
    s.add("b", "い")
    with pytest.raises(ValueError):
        s.add("c", "う")
    assert len(s.all()) == 2
    s.close()


def test_dictionary_load_drops_entries_beyond_the_cap(tmp_path, monkeypatch):
    """上限超過のファイルでも**起動はする** (拒否ではなく degrade + 件数通知)。"""
    from dictionary import store as store_mod

    monkeypatch.setattr(store_mod, "MAX_DICT_ENTRIES", 2)
    path = tmp_path / "d.json"
    path.write_text(_dict_json(5), encoding="utf-8")

    s = store_mod.DictionaryStore(path)

    assert len(s.all()) == 2
    assert s.load_skipped == 3
    s.close()


# ── 折返しグループ化の走査上限 ────────────────────────────────────────

def _stacked_texts(count: int, y_step: float, font_size: float = 12.0) -> list:
    from model.elements import TextElement as TE

    return [
        TE(bbox=Rect(10, i * y_step - font_size, 20, font_size), text=f"t{i}",
           font_size=font_size, origin_x=10, origin_y=i * y_step)
        for i in range(count)
    ]


def _count_follower_checks(monkeypatch) -> list:
    from dictionary import apply as dict_apply

    calls: list = []
    original = dict_apply._is_wrap_follower

    def counting(top, below):
        calls.append(1)
        return original(top, below)

    monkeypatch.setattr(dict_apply, "_is_wrap_follower", counting)
    return calls


def test_wrap_groups_stops_scanning_once_the_vertical_gap_is_exceeded(monkeypatch):
    """縦に離れた要素の走査は 1 要素あたり定数回で打ち切られる (打ち切りが無いと全要素走査)。"""
    from dictionary import apply as dict_apply

    texts = _stacked_texts(500, y_step=100.0)  # gap 100 >> 12 * LINE_GAP_RATIO
    checks = _count_follower_checks(monkeypatch)
    groups = dict_apply._wrap_groups(texts)
    assert len(groups) == 500  # どれも連結しない (結果は従来どおり)
    # 打ち切りが効いていれば要素数の定数倍。効かなければ n^2/2 = 124,750 回。
    assert len(checks) <= 2 * len(texts)


def test_wrap_group_scan_is_capped_when_everything_shares_one_row_band(monkeypatch):
    """同じ y 帯へ要素を敷き詰められても 1 要素あたりの走査数は上限で頭打ちになる。"""
    from dictionary import apply as dict_apply

    monkeypatch.setattr(dict_apply, "MAX_WRAP_SCAN", 8)
    texts = [
        TextElement(bbox=Rect(i * 0.001, 0, 20, 12), text=f"t{i}", font_size=12.0,
                    origin_x=i * 0.001, origin_y=12.0)
        for i in range(400)
    ]
    checks = _count_follower_checks(monkeypatch)
    groups = dict_apply._wrap_groups(texts)
    assert len(groups) == 400  # 同一行なので連結は起きない
    assert len(checks) <= len(texts) * 8


def test_wrap_groups_still_joins_a_real_wrapped_cell():
    """上限・打ち切りを入れても本来の折返し連結は壊れていないこと。"""
    from dictionary import apply as dict_apply

    texts = _stacked_texts(3, y_step=12.0)  # gap 12 <= 12 * 1.3 → 3 行が 1 グループ
    groups = dict_apply._wrap_groups(texts)
    assert [len(g) for g in groups] == [3]


# ── 接続の資源上限 ────────────────────────────────────────────────────

def _serve(session, token, **kwargs):
    """`create_server` でサーバを起動して base URL を返す (呼び出し側で shutdown)。"""
    import config
    from web.server import create_server

    server = create_server(str(config.resource_path("web")), session, token=token, **kwargs)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture()
def session(tmp_path):
    from dictionary.store import DictionaryStore
    from web.rpc_methods import WebSession
    from web.undo_stack import UndoStack

    s = WebSession(DictionaryStore(tmp_path / "dict.json"), UndoStack())
    yield s
    s.store.close()


def test_silent_connection_is_closed_by_the_handler_timeout(monkeypatch, session):
    """何も送らない接続はスレッドを恒久占有できない (`parse_request` は届かない)。

    ガードはリクエスト行とヘッダが揃って初めて走るので、無言の接続はガードの手前で
    ブロックし続けていた。ハンドラ側の期限だけがこれを閉じられる。
    """
    monkeypatch.setattr(server_mod.Handler, "timeout", 0.5)
    server = _serve(session, "timeout-test-token")
    try:
        sock = socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=10)
        sock.settimeout(10)
        # 1 バイトも送らない。期限が効いていれば向こうから閉じる (recv が EOF を返す)。
        assert sock.recv(1) == b""
        sock.close()
    finally:
        server.shutdown()
        server.server_close()


def test_dripping_connection_is_closed_by_the_request_deadline(monkeypatch, session):
    """改行を送らずに少しずつ送り続ける接続も、**要求単位の絶対期限**で閉じられる。

    per-recv の `timeout` は recv ごとに再武装されるので、per-recv より短い間隔で 1 バイトずつ
    送り続ければ `readline` を無限に引き延ばして 1 スレッドを恒久占有できた。`MAX_REQUEST_SECONDS`
    はこれを閉じる。ここでは per-recv を十分長く (5s)、期限を短く (1s) して、閉じているのが
    期限であることを主張する。
    """
    monkeypatch.setattr(server_mod.Handler, "timeout", 5.0)
    monkeypatch.setattr(origin_guard, "MAX_REQUEST_SECONDS", 1.0)
    server = _serve(session, "drip-test-token")
    try:
        sock = socket.create_connection(("127.0.0.1", server.server_address[1]), timeout=10)
        sock.settimeout(0.3)
        start = time.monotonic()
        closed_by_server = False
        wall = start + 6.0  # 安全弁 (期限が効かなければここまで回り続けて False で落ちる)
        while time.monotonic() < wall:
            try:
                sock.sendall(b"a")  # 改行なし = リクエスト行は完成しない
            except OSError:
                closed_by_server = True
                break
            try:
                if sock.recv(1) == b"":  # 向こう (サーバ) が閉じた
                    closed_by_server = True
                    break
            except socket.timeout:
                pass  # まだ開いている。次のドリップへ。
            time.sleep(0.15)  # per-recv (5s) には遠く及ばない間隔
        sock.close()
        assert closed_by_server, "ドリップ接続が期限で閉じられていない"
        # 期限 (1s) + 余裕。per-recv (5s) にはまだ達していないので、閉じたのは期限である。
        assert time.monotonic() - start < 4.0
    finally:
        server.shutdown()
        server.server_close()


def test_connection_cap_refuses_extra_connections(monkeypatch, session):
    """同時接続数の上限を超えた接続は受け付けず即切断する (スレッドを積み上げない)。"""
    monkeypatch.setattr(server_mod.Handler, "timeout", 5.0)
    server = _serve(session, "cap-test-token", max_connections=2)
    port = server.server_address[1]
    hogs = []
    try:
        for _ in range(2):  # 無言接続で枠を 2 つとも埋める
            s = socket.create_connection(("127.0.0.1", port), timeout=10)
            hogs.append(s)
        time.sleep(0.2)  # accept → ハンドラスレッド起動まで待つ
        extra = socket.create_connection(("127.0.0.1", port), timeout=10)
        extra.settimeout(10)
        assert extra.recv(1) == b""  # 枠が無いので応答せず切断される
        extra.close()

        for s in hogs:  # 枠を返せば通常のリクエストがまた通る
            s.close()
        hogs = []
        deadline = time.monotonic() + 10
        while True:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as res:
                    assert res.status == 200
                break
            except urllib.error.URLError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
    finally:
        for s in hogs:
            s.close()
        server.shutdown()
        server.server_close()
