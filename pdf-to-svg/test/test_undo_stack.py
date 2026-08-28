"""`web.undo_stack.UndoStack` の単体テスト (Qt 非依存・コマンドはダミー)。

要点は「マクロを 1 ステップに畳む」こと (`QUndoStack` 互換)。これにより辞書の全再適用
(N 件置換) が 1 回の undo で戻る。push 時の redo 実行・redo 分岐の破棄も検証する。
"""
from __future__ import annotations

from web.undo_stack import UndoStack


class _Cmd:
    def __init__(self, log, name):
        self.log = log
        self.name = name

    def redo(self):
        self.log.append("+" + self.name)

    def undo(self):
        self.log.append("-" + self.name)


def test_push_executes_redo_then_undo_redo():
    log = []
    s = UndoStack()
    s.push(_Cmd(log, "a"))
    assert log == ["+a"]  # push 時に redo を実行
    assert s.canUndo() and not s.canRedo()
    s.undo()
    assert log == ["+a", "-a"]
    assert not s.canUndo() and s.canRedo()
    s.redo()
    assert log == ["+a", "-a", "+a"]


def test_macro_collapses_to_single_step():
    log = []
    s = UndoStack()
    s.beginMacro()
    s.push(_Cmd(log, "a"))
    s.push(_Cmd(log, "b"))
    s.push(_Cmd(log, "c"))
    s.endMacro()
    assert log == ["+a", "+b", "+c"]  # 各 push で redo 済み
    assert s.canUndo() and not s.canRedo()
    s.undo()  # 1 回で全部戻る (逆順)
    assert log[-3:] == ["-c", "-b", "-a"]
    assert not s.canUndo() and s.canRedo()
    s.redo()  # 1 回で全部やり直し (順方向)
    assert log[-3:] == ["+a", "+b", "+c"]


def test_empty_macro_not_pushed():
    s = UndoStack()
    s.beginMacro()
    s.endMacro()
    assert not s.canUndo()


def test_new_push_truncates_redo_branch():
    log = []
    s = UndoStack()
    s.push(_Cmd(log, "a"))
    s.push(_Cmd(log, "b"))
    s.undo()  # b を undo
    assert s.canRedo()
    s.push(_Cmd(log, "c"))  # 新規 push で b の redo 分岐を破棄
    assert not s.canRedo()
    s.undo()
    assert log[-1] == "-c"
    s.undo()
    assert log[-1] == "-a"  # b はスキップされている


def test_restore_command_is_mirror_of_delete_command():
    from model.elements import Rect, TextElement
    from web.commands import RestoreCommand
    el = TextElement(bbox=Rect(0, 0, 10, 10), text="x", origin_x=0, origin_y=10)
    el.deleted = True
    stack = UndoStack()
    stack.push(RestoreCommand([el]))
    assert el.deleted is False
    stack.undo()
    assert el.deleted is True
    stack.redo()
    assert el.deleted is False
