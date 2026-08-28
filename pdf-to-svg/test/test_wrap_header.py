"""折返し (複数行に分割された) ヘッダセルを 1 語として辞書照合する。

連結照合は連結由来 (`joined=True`) エントリのみに一致する: 連結取り込みで登録した
語だけが 2 行畳み込みの対象で、単独行で登録した語は偶然連結形と一致しても畳まない。
"""
from dictionary import apply as dict_apply
from dictionary.store import DictionaryStore
from export.svg_exporter import _fmt, page_to_svg
from model.document import Page
from model.elements import Rect, TextElement


def _text(s, x, oy, size=12.0, w=20.0):
    """origin (x, oy)・幅 w pt の TextElement を作る。bbox は列判定用。"""
    return TextElement(
        bbox=Rect(x, oy - size, w, size),
        text=s,
        font_size=size,
        origin_x=x,
        origin_y=oy,
    )


def _page(elements):
    pg = Page(index=0, width_pt=300.0, height_pt=200.0)
    pg.elements.extend(elements)
    return pg


def test_wrapped_header_joined_no_separator(tmp_path):
    """和文「商品」+「名称」(縦 2 行) を連結して "商品名称" で照合する。"""
    top = _text("商品", x=50, oy=40)
    bottom = _text("名称", x=50, oy=52)  # 直下・同列・同サイズ
    pg = _page([top, bottom])
    store = DictionaryStore(tmp_path / "d.json")
    store.add("商品名称", "Product", joined=True)

    n = dict_apply.auto_apply(pg, store)

    assert n == 1
    assert top.text == "Product"
    assert top.dict_match is not None and top.dict_match.source == "商品名称"
    assert bottom.deleted is True  # 2 行目は描画から除外
    # 畳み込み後、先頭要素はグループ全体の合成領域へ据え直される (縦の上詰まり防止)。
    # top bbox=(50,28,20,12) / bottom bbox=(50,40,20,12) → 合成 (50,28,20,24)。
    assert (top.bbox.x, top.bbox.y, top.bbox.w, top.bbox.h) == (50.0, 28.0, 20.0, 24.0)
    # 縦は下揃え (最終行のベースライン)、横は元の行揃え (両行とも左端 50 → 左揃え)。
    assert top.origin_y == 52.0 and top.wrap_align == "left"
    store.close()


def test_wrapped_header_joined_with_space(tmp_path):
    """欧文「Product」+「Name」は空白連結 "Product Name" で照合する。"""
    top = _text("Product", x=50, oy=40)
    bottom = _text("Name", x=50, oy=52)
    pg = _page([top, bottom])
    store = DictionaryStore(tmp_path / "d.json")
    store.add("Product Name", "製品名", joined=True)

    plans = dict_apply.plan_replacements(_detect(pg), store)

    assert len(plans) == 1
    rep = plans[0]
    assert rep.element is top and rep.target == "製品名"
    assert rep.extras == [bottom]
    # 折返しは合成領域 new_bbox を持つ (SVG 出力で下揃え + 元の行揃えに据え直す)。
    assert rep.new_bbox is not None
    assert (rep.new_bbox.x, rep.new_bbox.y, rep.new_bbox.w, rep.new_bbox.h) == (50.0, 28.0, 20.0, 24.0)
    assert rep.align == "left" and rep.baseline_y == 52.0
    store.close()


def test_non_joined_entry_not_wrap_matched(tmp_path):
    """単独行として登録した語 (joined=False) は連結形と一致しても 2 行を畳まない。"""
    top = _text("商品", x=50, oy=40)
    bottom = _text("名称", x=50, oy=52)  # 幾何的には折返しグループになる並び
    pg = _page([top, bottom])
    store = DictionaryStore(tmp_path / "d.json")
    store.add("商品名称", "Product")  # joined 指定なし = 手入力相当

    n = dict_apply.auto_apply(pg, store)

    assert n == 0
    assert top.text == "商品" and bottom.deleted is False
    store.close()


def test_wide_gap_stack_not_joined(tmp_path):
    """縦間隔が広い (font*1.6) 同列セルは折返しとみなさず連結しない (誤判定の回帰防止)。"""
    # gap = 12*1.6 = 19.2 → LINE_GAP_RATIO(1.3) 超過。別々の単独行として扱う。
    top = _text("商品", x=50, oy=40)
    bottom = _text("名称", x=50, oy=40 + 12 * 1.6)  # 直下だが行間が広い
    pg = _page([top, bottom])
    store = DictionaryStore(tmp_path / "d.json")
    store.add("商品名称", "Product", joined=True)

    # 連結由来エントリでも幾何条件を満たさなければ当たらない。各行は元のまま。
    n = dict_apply.auto_apply(pg, store)

    assert n == 0
    assert top.text == "商品" and not bottom.deleted
    # 束ねられていないので候補は連結文字列でなく単独テキストを返す。
    assert dict_apply.joined_candidate(pg, top, join_wrapped=True) == ("商品", False)
    store.close()


def test_single_line_header_still_matches(tmp_path):
    """単独行ヘッダは従来どおり要素単位で照合される (折返し化の回帰防止)。"""
    head = _text("Qty", x=50, oy=40)
    pg = _page([head])
    store = DictionaryStore(tmp_path / "d.json")
    store.add("Qty", "数量")

    n = dict_apply.auto_apply(pg, store)

    assert n == 1
    assert head.text == "数量"
    store.close()


def test_body_stack_joined(tmp_path):
    """ヘッダでない本文セルの複数行 (1 文の折返し) も連結照合する (ヘッダに限定しない)。"""
    # top band (200*0.25=50) より下・非太字 → ヘッダ検出されないが連結対象。
    a = _text("商品", x=50, oy=120)
    b = _text("名称", x=50, oy=132)
    pg = _page([a, b])
    store = DictionaryStore(tmp_path / "d.json")
    store.add("商品名称", "Product", joined=True)

    n = dict_apply.auto_apply(pg, store)

    assert n == 1
    assert a.text == "Product"
    assert a.dict_match is not None and a.dict_match.source == "商品名称"
    assert b.deleted is True  # 2 行目は描画から除外
    store.close()


def test_wrap_align_detected_center(tmp_path):
    """行の中央が揃った折返しセルは中央揃えとして検出される。"""
    # 中央 60 で共通 (左端 40/50・右端 80/70 はばらつく)
    top = _text("Grand", x=40, oy=40, w=40)
    bottom = _text("Total", x=50, oy=52, w=20)
    pg = _page([top, bottom])
    store = DictionaryStore(tmp_path / "d.json")
    store.add("Grand Total", "総計", joined=True)

    plans = dict_apply.plan_replacements(_detect(pg), store)

    assert len(plans) == 1
    assert plans[0].align == "center" and plans[0].baseline_y == 52.0
    store.close()


def test_wrap_align_detected_right(tmp_path):
    """行の右端が揃った折返しセルは右揃えとして検出される。"""
    top = _text("Grand", x=40, oy=40, w=40)   # 右端 80
    bottom = _text("Total", x=60, oy=52, w=20)  # 右端 80
    pg = _page([top, bottom])
    store = DictionaryStore(tmp_path / "d.json")
    store.add("Grand Total", "総計", joined=True)

    plans = dict_apply.plan_replacements(_detect(pg), store)

    assert len(plans) == 1
    assert plans[0].align == "right"
    store.close()


def test_svg_joined_replacement_bottom_left(tmp_path):
    """左揃え折返しの置換は合成領域の左下 (最終行ベースライン) へ左揃えで描かれる。"""
    top = _text("商品", x=50, oy=40)
    bottom = _text("名称", x=50, oy=52)
    pg = _page([top, bottom])
    store = DictionaryStore(tmp_path / "d.json")
    store.add("商品名称", "品", joined=True)  # 短い置換語 → 幅超過なし = 圧縮しない
    dict_apply.auto_apply(pg, store)
    store.close()

    svg = page_to_svg(pg)
    line = next(ln for ln in svg.splitlines() if "品" in ln and "<text" in ln)
    assert f'x="{_fmt(50)}"' in line and f'y="{_fmt(52)}"' in line
    assert "text-anchor" not in line          # 左揃えは既定 anchor (start)
    assert "dominant-baseline" not in line    # 縦中央でなくベースライン下揃え
    assert "textLength" not in line           # 全幅への引き伸ばしはしない


def test_svg_joined_replacement_bottom_center(tmp_path):
    """中央揃え折返しの置換は合成領域の下辺中央へ text-anchor=middle で描かれる。"""
    top = _text("Grand", x=40, oy=40, w=40)
    bottom = _text("Total", x=50, oy=52, w=20)
    pg = _page([top, bottom])
    store = DictionaryStore(tmp_path / "d.json")
    store.add("Grand Total", "計", joined=True)
    dict_apply.auto_apply(pg, store)
    store.close()

    svg = page_to_svg(pg)
    line = next(ln for ln in svg.splitlines() if "計" in ln and "<text" in ln)
    # 合成領域 x=40..80 → 中央 60、最終行ベースライン 52
    assert f'x="{_fmt(60)}"' in line and f'y="{_fmt(52)}"' in line
    assert 'text-anchor="middle"' in line


def test_joined_candidate_wrapped_no_separator():
    """連結 ON の折返し和文セルは、どの行をクリックしても連結 "商品名称" を候補に返す。"""
    top = _text("商品", x=50, oy=40)
    bottom = _text("名称", x=50, oy=52)
    pg = _page([top, bottom])

    assert dict_apply.joined_candidate(pg, top, join_wrapped=True) == ("商品名称", True)
    assert dict_apply.joined_candidate(pg, bottom, join_wrapped=True) == ("商品名称", True)


def test_joined_candidate_wrapped_with_space():
    """連結 ON の折返し欧文セルは空白連結 "Product Name" を候補に返す。"""
    top = _text("Product", x=50, oy=40)
    bottom = _text("Name", x=50, oy=52)
    pg = _page([top, bottom])

    assert dict_apply.joined_candidate(pg, top, join_wrapped=True) == ("Product Name", True)


def test_joined_candidate_off_returns_clicked_line():
    """連結 OFF (既定) では折返しセルでもクリック行の文字列をそのまま候補に返す。"""
    top = _text("商品", x=50, oy=40)
    bottom = _text("名称", x=50, oy=52)
    pg = _page([top, bottom])

    assert dict_apply.joined_candidate(pg, top) == ("商品", False)
    assert dict_apply.joined_candidate(pg, bottom) == ("名称", False)


def test_joined_candidate_single_line():
    """単独行は連結 ON でもその行の文字列をそのまま候補に返す (連結しない)。"""
    head = _text("Qty", x=50, oy=40)
    pg = _page([head])

    assert dict_apply.joined_candidate(pg, head, join_wrapped=True) == ("Qty", False)


def _detect(pg):
    dict_apply.detect_headers(pg)
    return pg


def test_apply_replacement_writes_dict_revert(tmp_path):
    """バッチ用 `apply_replacement` も Command と同じく復元情報を残す。"""
    top = _text("商品", x=50, oy=40)
    bottom = _text("名称", x=50, oy=52)
    pg = _page([top, bottom])
    store = DictionaryStore(tmp_path / "d.json")
    store.add("商品名称", "Product", joined=True)
    dict_apply.auto_apply(pg, store)
    assert top.dict_revert is not None
    assert top.dict_revert.text == "商品" and top.dict_revert.extra_ids == [bottom.id]
    assert top.dict_revert.origin_y == 40 and top.dict_revert.wrap_align is None
    store.close()


def test_has_replacement_candidate_true_for_page_with_hit(tmp_path):
    """`state` RPC 用の軽量判定: 辞書に一致する要素が 1 件でもあれば True。"""
    el = _text("Qty", x=50, oy=40)
    pg = _page([el])
    store = DictionaryStore(tmp_path / "d.json")
    store.add("Qty", "数量")
    assert dict_apply.has_replacement_candidate(pg, store) is True
    store.close()


def test_has_replacement_candidate_false_for_empty_store(tmp_path):
    """辞書が空なら、置換対象になりうる要素があっても走査せず False を返す。"""
    el = _text("Qty", x=50, oy=40)
    pg = _page([el])
    store = DictionaryStore(tmp_path / "d.json")
    assert dict_apply.has_replacement_candidate(pg, store) is False
    store.close()


def test_has_replacement_candidate_false_for_no_hits(tmp_path):
    """辞書に登録があってもページ内のどの要素とも一致しなければ False。"""
    el = _text("Qty", x=50, oy=40)
    pg = _page([el])
    store = DictionaryStore(tmp_path / "d.json")
    store.add("Amount", "金額")
    assert dict_apply.has_replacement_candidate(pg, store) is False
    store.close()
