"""素の Python による Undo/Redo スタック (Qt 非依存)。

旧実装は `QUndoStack` を使っていたが、QtWebEngine 撤廃に伴い標準ライブラリだけで
同等の API (`push` / `undo` / `redo` / `canUndo` / `canRedo` /
`beginMacro` / `endMacro` / `clear`) を提供する。コマンドは `redo()` /
`undo()` を持つ任意オブジェクト (`commands.py` 参照)。`push` は `QUndoStack` と同様に
追加時へ `redo()` を即実行する。

マクロ: `beginMacro`〜`endMacro` の間の push を 1 つの複合コマンドへまとめ、
undo/redo の 1 ステップとして扱う (`QUndoStack` の挙動)。これにより「辞書の全再適用」
(N 件置換) が 1 回の undo で戻る。
"""
from __future__ import annotations

from typing import List, Optional

# 保持する Undo 段数の上限。各コマンドは置換前後の要素状態を握るため、無制限に積むと
# 長時間の編集セッションでメモリが単調増加する。超過時は最古を捨てる (分類 B: degrade。
# 「これ以上戻れない」は編集を止めないが、上限が無いとアプリごと落ちる)。
MAX_UNDO_DEPTH = 200


class _Macro:
    """`beginMacro`〜`endMacro` でまとめた複合コマンド。"""

    def __init__(self):
        self.cmds: list = []

    def redo(self) -> None:
        for c in self.cmds:
            c.redo()

    def undo(self) -> None:
        for c in reversed(self.cmds):
            c.undo()


class UndoStack:
    """`QUndoStack` 互換の Undo/Redo スタック。`_pos` 以降は redo 分岐として保持する。"""

    def __init__(self):
        self._stack: List[object] = []
        self._pos = 0
        self._macro: Optional[_Macro] = None

    def push(self, cmd) -> None:
        # QUndoStack と同様、push 時にコマンドを実行 (redo) する。
        cmd.redo()
        if self._macro is not None:
            self._macro.cmds.append(cmd)
            return
        del self._stack[self._pos:]  # redo 分岐を破棄
        self._stack.append(cmd)
        self._pos += 1
        self._trim()

    def beginMacro(self) -> None:  # noqa: N802 (QUndoStack 互換 API 名。履歴ラベルは UI が無く受けない)
        self._macro = _Macro()

    def endMacro(self) -> None:  # noqa: N802
        m = self._macro
        self._macro = None
        if m is None or not m.cmds:
            return  # 空マクロはスタックへ積まない
        del self._stack[self._pos:]
        self._stack.append(m)  # 個々の push で redo 済み
        self._pos += 1
        self._trim()

    def _trim(self) -> None:
        """深さ上限を超えた分だけ最古を捨てる (`_pos` も同じ数だけ手前へずらす)。"""
        excess = len(self._stack) - MAX_UNDO_DEPTH
        if excess <= 0:
            return
        del self._stack[:excess]
        self._pos = max(0, self._pos - excess)

    def canUndo(self) -> bool:  # noqa: N802
        return self._pos > 0

    def canRedo(self) -> bool:  # noqa: N802
        return self._pos < len(self._stack)

    def undo(self) -> None:
        if self.canUndo():
            self._pos -= 1
            self._stack[self._pos].undo()

    def redo(self) -> None:
        if self.canRedo():
            self._stack[self._pos].redo()
            self._pos += 1

    def clear(self) -> None:
        self._stack = []
        self._pos = 0
        self._macro = None
