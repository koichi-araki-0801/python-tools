"""辞書置換の箇所単位の戻し: 復元情報 (`dict_revert`) と `RevertDictMatchCommand`。"""
from model.elements import DictMatch, DictRevertInfo, Rect, TextElement
from web.commands import ReplaceTextCommand, RevertDictMatchCommand
from web.undo_stack import UndoStack


def _text(s, x, oy, size=12.0, w=20.0):
    return TextElement(bbox=Rect(x, oy - size, w, size), text=s, font_size=size,
                       origin_x=x, origin_y=oy)


def test_replace_command_records_revert_info_and_undo_clears_it():
    el = _text("Item No.", 10, 20, w=40)
    cmd = ReplaceTextCommand(el, "品番", DictMatch(source="Item No.", target="品番"))
    stack = UndoStack()
    stack.push(cmd)
    assert el.text == "品番"
    assert el.dict_revert == DictRevertInfo(
        text="Item No.", bbox=Rect(10, 8, 40, 12), wrap_align=None, origin_y=20, extra_ids=[]
    )
    stack.undo()
    assert el.text == "Item No." and el.dict_revert is None
    stack.redo()
    assert el.dict_revert is not None and el.dict_revert.text == "Item No."


def test_replace_command_records_extras_for_wrapped_group():
    top = _text("商品", 50, 40)
    bottom = _text("名称", 50, 52)
    cmd = ReplaceTextCommand(
        top, "Product", DictMatch(source="商品名称", target="Product"),
        new_bbox=Rect(50, 28, 20, 24), wrap_align="left", baseline_y=52.0, extras=[bottom],
    )
    cmd.redo()
    assert top.dict_revert.extra_ids == [bottom.id]
    assert top.dict_revert.bbox == Rect(50, 28, 20, 12) and top.dict_revert.origin_y == 40


def test_text_element_defaults():
    el = _text("x", 0, 10)
    assert el.dict_revert is None


def test_revert_command_restores_single_line_and_is_undoable():
    el = _text("Item No.", 10, 20, w=40)
    stack = UndoStack()
    stack.push(ReplaceTextCommand(el, "品番", DictMatch(source="Item No.", target="品番")))
    stack.push(RevertDictMatchCommand(el, []))
    assert el.text == "Item No." and el.dict_match is None and el.dict_revert is None
    assert el.bbox == Rect(10, 8, 40, 12)
    stack.undo()  # 戻しの取り消し = 置換状態へ
    assert el.text == "品番" and el.dict_match.target == "品番" and el.dict_revert is not None
    stack.redo()
    assert el.text == "Item No." and el.dict_match is None


def test_revert_command_restores_wrapped_group():
    top = _text("商品", 50, 40)
    bottom = _text("名称", 50, 52)
    stack = UndoStack()
    stack.push(ReplaceTextCommand(
        top, "Product", DictMatch(source="商品名称", target="Product"),
        new_bbox=Rect(50, 28, 20, 24), wrap_align="left", baseline_y=52.0, extras=[bottom],
    ))
    bottom.deleted = True  # `_apply_plans` は extras を DeleteCommand で別途畳む
    stack.push(RevertDictMatchCommand(top, [bottom]))
    assert top.text == "商品" and top.bbox == Rect(50, 28, 20, 12)
    assert top.origin_y == 40 and top.wrap_align is None
    assert bottom.deleted is False
    stack.undo()
    assert top.text == "Product" and top.bbox == Rect(50, 28, 20, 24) and bottom.deleted is True


def test_revert_command_undo_restores_extra_not_deleted_before_revert():
    """戻す前に削除されていなかった extra は、戻しの取り消し (undo) 後も削除状態のまま
    にならない (redo が実測せず一律 True へ戻すと、削除していない後続行が消えてしまう)。"""
    top = _text("商品", 50, 40)
    bottom = _text("名称", 50, 52)
    top.dict_revert = DictRevertInfo(
        text="商品", bbox=Rect(50, 28, 20, 12), wrap_align=None, origin_y=40,
        extra_ids=[bottom.id],
    )
    top.text = "Product"
    top.dict_match = DictMatch(source="商品名称", target="Product")
    # bottom はこの置換で削除されていない (呼び出し元の実測どおりに扱われるべき)。
    assert bottom.deleted is False
    stack = UndoStack()
    stack.push(RevertDictMatchCommand(top, [bottom]))
    assert bottom.deleted is False  # redo は元の状態のまま
    stack.undo()
    assert bottom.deleted is False  # undo も実測値 (False) へ戻す。強制 True にしない


def test_chained_replace_keeps_the_first_revert_info():
    """A→B→C と辞書が連鎖しても、戻しは最初の原文まで一段で戻り畳み込み行も再表示する。

    再置換で `dict_revert` を上書きすると、戻し先が中間の置換結果になり、原文にも
    畳み込んだ後続行にも二度と戻れなくなる。
    """
    top = _text("商品", 50, 40)
    bottom = _text("名称", 50, 52)
    stack = UndoStack()
    stack.push(ReplaceTextCommand(
        top, "Product", DictMatch(source="商品名称", target="Product"),
        new_bbox=Rect(50, 28, 20, 24), wrap_align="left", baseline_y=52.0, extras=[bottom],
    ))
    bottom.deleted = True  # `_apply_plans` は extras を DeleteCommand で別途畳む
    # 置換済みのテキストへさらに別の語が当たる (Product → 製品)
    stack.push(ReplaceTextCommand(top, "製品", DictMatch(source="Product", target="製品")))
    assert top.dict_revert.text == "商品"
    assert top.dict_revert.extra_ids == [bottom.id]

    stack.push(RevertDictMatchCommand(top, [bottom]))
    assert top.text == "商品" and top.dict_match is None and top.dict_revert is None
    assert top.bbox == Rect(50, 28, 20, 12) and top.origin_y == 40
    assert bottom.deleted is False
