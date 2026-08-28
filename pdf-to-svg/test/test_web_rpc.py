"""web.rpc_methods のディスパッチを Qt を起動せず検証する。

QUndoStack の代わりに FakeUndo (push で redo を即実行) を使うことで、
GUI なしで「状態の読み出し」「編集の反映」を確認できる。
"""
from __future__ import annotations

import pytest

from dictionary.store import DictionaryStore
from model.document import Document, Page, RasterBackground
from model.elements import DictMatch, LineElement, Rect, TextElement
from web import rpc_methods
from web.rpc_methods import WebSession


class FakeUndo:
    """QUndoStack の最小代用 (push=redo 実行、undo/redo、マクロは透過)。"""

    def __init__(self):
        self._stack = []
        self._pos = 0

    def clear(self):
        self._stack = []
        self._pos = 0

    def beginMacro(self):  # noqa: N802
        pass

    def endMacro(self):  # noqa: N802
        pass

    def push(self, cmd):
        del self._stack[self._pos:]
        cmd.redo()
        self._stack.append(cmd)
        self._pos += 1

    def canUndo(self):  # noqa: N802
        return self._pos > 0

    def canRedo(self):  # noqa: N802
        return self._pos < len(self._stack)

    def undo(self):
        if self.canUndo():
            self._pos -= 1
            self._stack[self._pos].undo()

    def redo(self):
        if self.canRedo():
            self._stack[self._pos].redo()
            self._pos += 1


def _make_doc(path="部品表.pdf") -> Document:
    page = Page(index=0, width_pt=200.0, height_pt=300.0)
    hdr = TextElement(
        bbox=Rect(10, 10, 40, 12), text="品番", original_text="Item No.",
        origin_x=10, origin_y=20, is_header=True,
        dict_match=DictMatch(source="Item No.", target="品番"),
    )
    body = TextElement(bbox=Rect(10, 40, 60, 12), text="A-1042", origin_x=10, origin_y=50)
    rule = LineElement(bbox=Rect(10, 30, 180, 0), x0=10, y0=30, x1=190, y1=30)
    page.elements = [hdr, body, rule]
    return Document(source_path=path, pages=[page])


@pytest.fixture()
def session(tmp_path):
    store = DictionaryStore(tmp_path / "dict.json")
    s = WebSession(store, FakeUndo())
    s.docs = [_make_doc()]
    return s


def test_state(session):
    st = rpc_methods.dispatch(session, "state", {})
    assert st["total"] == 1
    assert st["files"][0]["pages"] == 1
    assert st["changed2"] == [True]   # dict_match のあるページは要確認
    assert st["changed3"] == [True]   # トリミングは全ページ対象


def test_state_counts_scanned_pages_that_lost_their_background(session):
    """背景を作れなかったスキャンページは件数で表に出す (無言で白紙にしない)。

    ベクターページも `background is None` だが劣化ではないので数に入らない
    (`_make_doc` の 1 ページ目がその対照)。
    """
    doc = session.docs[0]
    doc.pages.append(Page(index=1, width_pt=200.0, height_pt=300.0, is_scanned=True))
    doc.pages.append(
        Page(
            index=2, width_pt=200.0, height_pt=300.0, is_scanned=True,
            background=RasterBackground(png_bytes=b"\x89PNG", rect=Rect(0, 0, 200, 300)),
        )
    )
    st = rpc_methods.dispatch(session, "state", {})
    assert st["noBackground"] == 1
    # 通知経路は `truncated` と同じ。こちらは劣化なしなので 0 のまま。
    assert st["truncated"] == 0


def test_page_svg_has_data_el(session):
    data = rpc_methods.dispatch(session, "pageSvg", {"fileIndex": 0, "pageInFile": 0})
    assert "data-el=" in data["svg"]
    assert data["width"] == 200.0 and data["height"] == 300.0


def test_plan_page(session):
    data = rpc_methods.dispatch(session, "planPage", {"fileIndex": 0, "pageInFile": 0})
    assert len(data["changes"]) == 1
    ch = data["changes"][0]
    assert ch["source"] == "Item No." and ch["target"] == "品番" and ch["loc"] == "ヘッダ"
    # "品番" (推定 24pt) は箱幅 40pt に収まるので幅超過なし
    assert ch["warning"] is False


def test_plan_page_width_warning(session):
    """置換語が箱幅を超える場合、change に幅超過警告が乗る。"""
    hdr = session.page(0, 0).elements[0]  # bbox.w=40, font_size=12
    hdr.text = "品番品番品番"  # 全角 6 字 ≒ 72pt > 40*1.05
    data = rpc_methods.dispatch(session, "planPage", {"fileIndex": 0, "pageInFile": 0})
    assert data["changes"][0]["warning"] is True


def test_apply_delete_and_removed_list(session):
    page = session.page(0, 0)
    target = page.elements[1]  # body text
    rpc_methods.dispatch(session, "applyDelete",
                         {"fileIndex": 0, "pageInFile": 0, "elIds": [target.id]})
    assert target.deleted is True
    removed = rpc_methods.dispatch(session, "removedList", {"fileIndex": 0, "pageInFile": 0})
    assert len(removed["removed"]) == 1
    # undo で戻る
    rpc_methods.dispatch(session, "undo", {})
    assert target.deleted is False


def test_restore_elements_restores_only_the_requested_element(session):
    page = session.page(0, 0)
    hdr, body = page.elements[0], page.elements[1]
    # 2 回に分けて削除する (直近 1 件の undo では body しか戻らない状況を作る)
    rpc_methods.dispatch(session, "applyDelete",
                         {"fileIndex": 0, "pageInFile": 0, "elIds": [hdr.id]})
    rpc_methods.dispatch(session, "applyDelete",
                         {"fileIndex": 0, "pageInFile": 0, "elIds": [body.id]})
    assert hdr.deleted and body.deleted
    # 古い方 (hdr) だけを戻す
    rpc_methods.dispatch(session, "restoreElements",
                         {"fileIndex": 0, "pageInFile": 0, "elIds": [hdr.id]})
    assert hdr.deleted is False
    assert body.deleted is True  # 直近の削除は取り消されていない
    removed = rpc_methods.dispatch(session, "removedList", {"fileIndex": 0, "pageInFile": 0})
    assert [r["elId"] for r in removed["removed"]] == [body.id]
    # 戻しは Undo に乗る
    rpc_methods.dispatch(session, "undo", {})
    assert hdr.deleted is True


def test_restore_elements_ignores_live_or_unknown_ids(session):
    page = session.page(0, 0)
    body = page.elements[1]
    before = len(session.undo._stack)
    rpc_methods.dispatch(session, "restoreElements",
                         {"fileIndex": 0, "pageInFile": 0, "elIds": [body.id, 99999]})
    assert body.deleted is False
    assert len(session.undo._stack) == before  # 対象なしなら履歴を積まない


def test_removed_list_hides_lines_folded_by_dict_wrap(session):
    """辞書の折返し畳み込みで論理削除した後続行は「削除した要素」ではないので一覧に出さない。"""
    from model.elements import DictRevertInfo
    page = session.page(0, 0)
    hdr, body = page.elements[0], page.elements[1]
    body.deleted = True
    hdr.dict_revert = DictRevertInfo(text="Item", bbox=hdr.bbox, wrap_align=None,
                                     origin_y=hdr.origin_y, extra_ids=[body.id])
    removed = rpc_methods.dispatch(session, "removedList", {"fileIndex": 0, "pageInFile": 0})
    assert removed["removed"] == []


def test_delete_region(session):
    page = session.page(0, 0)
    body = page.elements[1]  # bbox(10,40,60,12)
    # 重なる矩形 → 削除される
    rpc_methods.dispatch(session, "deleteRegion",
                         {"fileIndex": 0, "pageInFile": 0,
                          "rect": {"x": 0, "y": 35, "w": 100, "h": 40}})
    assert body.deleted is True
    # 戻して、重ならない矩形では何も消えない
    rpc_methods.dispatch(session, "undo", {})
    assert body.deleted is False
    before = len(page.live_elements())
    rpc_methods.dispatch(session, "deleteRegion",
                         {"fileIndex": 0, "pageInFile": 0,
                          "rect": {"x": 150, "y": 150, "w": 10, "h": 10}})
    assert len(page.live_elements()) == before


def test_remove_file(session):
    session.docs.append(_make_doc("図面.pdf"))
    assert len(session.docs) == 2
    rpc_methods.dispatch(session, "removeFile", {"fileIndex": 0})
    assert len(session.docs) == 1
    # 先頭を消したので残るのは 2 番目に追加したファイル
    assert session.docs[0].source_path == "図面.pdf"
    # 範囲外の index は無視 (例外を投げない)
    rpc_methods.dispatch(session, "removeFile", {"fileIndex": 9})
    assert len(session.docs) == 1


def test_add_border(session):
    page = session.page(0, 0)
    before = len(page.live_elements())
    rpc_methods.dispatch(session, "addBorder",
                         {"fileIndex": 0, "pageInFile": 0,
                          "rect": {"x": 5, "y": 5, "w": 100, "h": 80},
                          "color": "#ff0000", "width": 2})
    el = page.elements[-1]  # AddElementCommand は末尾へ追加する
    assert el.stroke == "#ff0000" and el.fill is None and el.stroke_width == 2.0
    assert el.kind == "rect" and el.deleted is False
    assert len(page.live_elements()) == before + 1
    # 書き出し SVG に枠線が出る (塗りなし stroke 指定)
    data = rpc_methods.dispatch(session, "pageSvg", {"fileIndex": 0, "pageInFile": 0})
    assert 'stroke="#ff0000"' in data["svg"] and 'fill="none"' in data["svg"]
    # undo で消え、redo で戻る (既存の選択→削除でも消せる前提の通常要素)
    rpc_methods.dispatch(session, "undo", {})
    assert el.deleted is True and len(page.live_elements()) == before
    rpc_methods.dispatch(session, "redo", {})
    assert el.deleted is False and len(page.live_elements()) == before + 1


def test_dict_add_and_list(session):
    rpc_methods.dispatch(session, "dictAdd", {"source": "Q'ty", "target": "数量"})
    lst = rpc_methods.dispatch(session, "dictList", {})
    sources = [e["source"] for e in lst["entries"]]
    assert "Q'ty" in sources
    # joined 指定なしの手入力登録は非連結、payload には suggestJoin も乗る
    assert lst["entries"][0]["joined"] is False
    assert lst["suggestJoin"] is False


def _wrapped_pair_session(tmp_path):
    """折返し 2 行 (商品/名称) を持つ 1 ページのセッションを作る。"""
    page = Page(index=0, width_pt=200.0, height_pt=300.0)
    top = TextElement(bbox=Rect(50, 28, 20, 12), text="商品",
                      font_size=12, origin_x=50, origin_y=40)
    bottom = TextElement(bbox=Rect(50, 40, 20, 12), text="名称",
                         font_size=12, origin_x=50, origin_y=52)
    page.elements = [top, bottom]
    s = WebSession(DictionaryStore(tmp_path / "d.json"), FakeUndo())
    s.docs = [Document(source_path="表.pdf", pages=[page])]
    return s, top, bottom


def test_dict_suggest_joins_only_when_enabled(tmp_path):
    """クリック取り込みの連結は setSuggestJoin ON のときのみ。既定はクリック行を返す。"""
    s, _top, bottom = _wrapped_pair_session(tmp_path)

    r = rpc_methods.dispatch(
        s, "dictSuggest", {"fileIndex": 0, "pageInFile": 0, "elId": bottom.id}
    )
    assert r["source"] == "名称" and r["joined"] is False  # 既定 OFF はクリック行のみ

    rpc_methods.dispatch(s, "setSuggestJoin", {"value": True})
    r = rpc_methods.dispatch(
        s, "dictSuggest", {"fileIndex": 0, "pageInFile": 0, "elId": bottom.id}
    )
    # ON ならクリックは 2 行目でも文全体を返し、連結の印が立つ
    assert r["source"] == "商品名称" and r["joined"] is True

    # 範囲外/不明な elId は空文字 (クライアントはクリック行へフォールバック)
    r2 = rpc_methods.dispatch(
        s, "dictSuggest", {"fileIndex": 0, "pageInFile": 0, "elId": 999999}
    )
    assert r2["source"] == "" and r2["joined"] is False


def test_reapply_joins_only_joined_entries(tmp_path):
    """一括適用の連結照合は連結由来 (joined=True) エントリのみに一致する。"""
    s, top, bottom = _wrapped_pair_session(tmp_path)

    # 手入力 (joined なし) の連結形は一致しない = 2 行は畳まれない
    rpc_methods.dispatch(s, "dictAdd", {"source": "商品名称", "target": "Product"})
    r = rpc_methods.dispatch(s, "reapplyDictPage", {"fileIndex": 0, "pageInFile": 0})
    assert r["count"] == 0
    assert top.text == "商品" and bottom.deleted is False

    # 連結取り込み由来 (joined=True) で登録し直すと連結照合され 2 行目が畳まれる
    rpc_methods.dispatch(
        s, "dictAdd", {"source": "商品名称", "target": "Product", "joined": True}
    )
    r = rpc_methods.dispatch(s, "reapplyDictPage", {"fileIndex": 0, "pageInFile": 0})
    assert r["count"] == 1
    assert top.text == "Product" and bottom.deleted is True
    # undo で戻る (FakeUndo はマクロ透過のため置換と削除を 1 回ずつ戻す)
    rpc_methods.dispatch(s, "undo", {})
    rpc_methods.dispatch(s, "undo", {})
    assert top.text == "商品" and bottom.deleted is False


def test_dict_json_roundtrip(tmp_path):
    # 書き出し元セッション: dictJson が共有用 JSON 文字列を返す
    s1 = WebSession(DictionaryStore(tmp_path / "d1.json"), FakeUndo())
    rpc_methods.dispatch(s1, "dictAdd", {"source": "Item No.", "target": "品番"})
    rpc_methods.dispatch(s1, "dictAdd", {"source": "Q'ty", "target": "数量"})
    res = rpc_methods.dispatch(s1, "dictJson", {})
    assert res["count"] == 2

    # 別セッションへ文字列のまま取り込み (ブラウザ保存/読込を模す)
    s2 = WebSession(DictionaryStore(tmp_path / "d2.json"), FakeUndo())
    imp = rpc_methods.dispatch(s2, "dictImportJson", {"json": res["json"]})
    assert imp["imported"] == 2
    sources = [e["source"] for e in imp["entries"]]
    assert "Item No." in sources and "Q'ty" in sources


def test_reapply_dict(session):
    # 辞書に body テキストの語を登録して再適用 (ヘッダ・本文を問わず全文が対象)
    rpc_methods.dispatch(session, "dictAdd", {"source": "A-1042", "target": "ボルト"})
    r = rpc_methods.dispatch(session, "reapplyDict", {})
    assert r["count"] >= 1
    assert r["warnings"] == 0  # "ボルト" は箱幅に収まる
    assert session.page(0, 0).elements[1].text == "ボルト"


def test_reapply_dict_page_scopes_to_one_page(session):
    """reapplyDictPage は指定ページだけに効き、他ファイル/ページは変えない。"""
    session.docs.append(_make_doc("図面.pdf"))  # file 1 を追加 (計 2 ファイル)
    rpc_methods.dispatch(session, "dictAdd", {"source": "A-1042", "target": "ボルト"})

    r = rpc_methods.dispatch(session, "reapplyDictPage", {"fileIndex": 1, "pageInFile": 0})

    assert r["count"] == 1 and r["warnings"] == 0
    assert session.page(1, 0).elements[1].text == "ボルト"   # 対象ページは置換
    assert session.page(0, 0).elements[1].text == "A-1042"  # 他ファイルは不変
    # undo で対象ページのみ戻る
    rpc_methods.dispatch(session, "undo", {})
    assert session.page(1, 0).elements[1].text == "A-1042"


def test_revert_dict_match_single_and_plan_page_states(session):
    """1 件だけ戻す: 要素は置換前へ、planPage は pending 行として並べ続ける。"""
    rpc_methods.dispatch(session, "dictAdd", {"source": "A-1042", "target": "ボルト"})
    rpc_methods.dispatch(session, "reapplyDictPage", {"fileIndex": 0, "pageInFile": 0})
    body = session.page(0, 0).elements[1]
    assert body.text == "ボルト"
    plan = rpc_methods.dispatch(session, "planPage", {"fileIndex": 0, "pageInFile": 0})
    assert [c["state"] for c in plan["changes"]] == ["applied", "applied"]

    r = rpc_methods.dispatch(session, "revertDictMatch",
                             {"fileIndex": 0, "pageInFile": 0, "elId": body.id})
    assert r["reverted"] is True
    assert body.text == "A-1042" and body.dict_match is None and body.dict_revert is None
    plan = rpc_methods.dispatch(session, "planPage", {"fileIndex": 0, "pageInFile": 0})
    rows = {c["elId"]: c for c in plan["changes"]}
    assert rows[body.id]["state"] == "pending"
    assert rows[body.id]["source"] == "A-1042" and rows[body.id]["target"] == "ボルト"
    # 戻した後もページは「要確認」のまま (一覧から消えない)
    assert rpc_methods.dispatch(session, "state", {})["changed2"] == [True]
    # 戻しは Undo/Redo に乗る
    rpc_methods.dispatch(session, "undo", {})
    assert body.text == "ボルト"
    rpc_methods.dispatch(session, "redo", {})
    assert body.text == "A-1042"
    # 復元情報が無い要素は no-op
    r = rpc_methods.dispatch(session, "revertDictMatch",
                             {"fileIndex": 0, "pageInFile": 0, "elId": body.id})
    assert r["reverted"] is False
    # 戻しはその場限り: 次の再適用でまた置換される
    r = rpc_methods.dispatch(session, "reapplyDictPage", {"fileIndex": 0, "pageInFile": 0})
    assert r["count"] == 1 and body.text == "ボルト"


def test_revert_dict_match_wrapped_group(tmp_path):
    """折返し畳み込みを戻すと 2 行目が再表示され、合成領域・ベースラインも元へ戻る。"""
    s, top, bottom = _wrapped_pair_session(tmp_path)
    rpc_methods.dispatch(s, "dictAdd", {"source": "商品名称", "target": "Product", "joined": True})
    rpc_methods.dispatch(s, "reapplyDictPage", {"fileIndex": 0, "pageInFile": 0})
    assert top.text == "Product" and bottom.deleted is True
    rpc_methods.dispatch(s, "revertDictMatch", {"fileIndex": 0, "pageInFile": 0, "elId": top.id})
    assert top.text == "商品" and bottom.deleted is False
    assert (top.bbox.x, top.bbox.y, top.bbox.w, top.bbox.h) == (50.0, 28.0, 20.0, 12.0)
    assert top.origin_y == 40 and top.wrap_align is None


def test_apply_dict_match_applies_only_one_element(session):
    """applyDictMatch は指定要素だけを置換する (他の候補は未置換のまま)。"""
    session.page(0, 0).elements.append(
        TextElement(bbox=Rect(10, 60, 60, 12), text="A-1042", origin_x=10, origin_y=70)
    )
    body, other = session.page(0, 0).elements[1], session.page(0, 0).elements[3]
    rpc_methods.dispatch(session, "dictAdd", {"source": "A-1042", "target": "ボルト"})
    r = rpc_methods.dispatch(session, "applyDictMatch",
                             {"fileIndex": 0, "pageInFile": 0, "elId": other.id})
    assert r["count"] == 1
    assert other.text == "ボルト" and body.text == "A-1042"
    plan = rpc_methods.dispatch(session, "planPage", {"fileIndex": 0, "pageInFile": 0})
    rows = {c["elId"]: c for c in plan["changes"]}
    assert rows[body.id]["state"] == "pending" and rows[other.id]["state"] == "applied"
    # 候補でない要素は no-op
    r = rpc_methods.dispatch(session, "applyDictMatch",
                             {"fileIndex": 0, "pageInFile": 0, "elId": 999999})
    assert r["count"] == 0


def test_state_changed2_true_for_pending_candidates(session):
    """未適用の候補しか無いページも要確認 (戻した箇所を一覧から消さない)。"""
    hdr = session.page(0, 0).elements[0]
    hdr.dict_match = None  # 置換済みを消し、候補だけの状態にする
    rpc_methods.dispatch(session, "dictAdd", {"source": "A-1042", "target": "ボルト"})
    assert rpc_methods.dispatch(session, "state", {})["changed2"] == [True]
