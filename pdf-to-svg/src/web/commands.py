"""編集操作のコマンド群。モデル (Page/Element) を直接更新する。

旧実装は ``QUndoCommand`` 派生だったが、QtWebEngine 撤廃に伴い素の Python クラスへ。
:class:`web.undo_stack.UndoStack` が push 時に ``redo()`` を実行し、``undo()`` /
``redo()`` で巻き戻す。``redo()`` / ``undo()`` の本体とコンストラクタ・シグネチャは
従来と不変 (rpc_methods 側は無改変)。
"""
from __future__ import annotations

from typing import List, Optional

from model.document import Page
from model.elements import DictMatch, DictRevertInfo, Element, Rect, TextElement


class DeleteCommand:
    def __init__(self, elements: List[Element]):
        self.elements = list(elements)

    def redo(self) -> None:
        for el in self.elements:
            el.deleted = True

    def undo(self) -> None:
        for el in self.elements:
            el.deleted = False


class RestoreCommand:
    """論理削除した要素を再表示する (``DeleteCommand`` の鏡像)。

    削除一覧の行ごとの「戻す」が使う。全体の Undo と違い、指定した要素だけを対象に
    するので、後から別の要素を削除していても巻き込まない。
    """

    def __init__(self, elements: List[Element]):
        self.elements = list(elements)

    def redo(self) -> None:
        for el in self.elements:
            el.deleted = False

    def undo(self) -> None:
        for el in self.elements:
            el.deleted = True


class AddElementCommand:
    """要素を 1 つページに追加する (枠線など)。``DeleteCommand`` と対称で、
    redo で可視化・undo で非表示にする (要素はリストに残し ``deleted`` で制御)。"""

    def __init__(self, page: Page, element: Element):
        self.page = page
        self.element = element

    def redo(self) -> None:
        if self.element not in self.page.elements:
            self.page.elements.append(self.element)
        self.element.deleted = False

    def undo(self) -> None:
        self.element.deleted = True


class ReplaceTextCommand:
    def __init__(
        self,
        el: TextElement,
        new_text: str,
        dict_match: Optional[DictMatch] = None,
        new_bbox: Optional[Rect] = None,
        wrap_align: Optional[str] = None,
        baseline_y: Optional[float] = None,
        extras: Optional[List[TextElement]] = None,
    ):
        self.el = el
        self.new_text = new_text
        self.dict_match = dict_match
        # 折返し畳み込み時に結合テキストを据え直す合成領域と据え方 (`dictionary/apply.py`
        # の `Replacement.new_bbox` / `align` / `baseline_y`)。None なら変更しない。
        self.new_bbox = new_bbox
        self.wrap_align = wrap_align
        self.baseline_y = baseline_y
        self.old_text = el.text
        self.old_match = el.dict_match
        self.old_bbox = el.bbox
        self.old_wrap_align = el.wrap_align
        self.old_origin_y = el.origin_y
        self.old_revert = el.dict_revert
        # 箇所単位の「戻す」が復元に使う置換前状態。後続行 (extras) は id で持つ。
        self.revert_info = DictRevertInfo(
            text=el.text, bbox=el.bbox, wrap_align=el.wrap_align, origin_y=el.origin_y,
            extra_ids=[e.id for e in (extras or [])],
        )

    def redo(self) -> None:
        self.el.text = self.new_text
        if self.dict_match is not None:
            self.el.dict_match = self.dict_match
        if self.new_bbox is not None:
            self.el.bbox = self.new_bbox
        if self.wrap_align is not None:
            self.el.wrap_align = self.wrap_align
        if self.baseline_y is not None:  # 折返し畳み込みは下揃え (最終行のベースライン)
            self.el.origin_y = self.baseline_y
        # 既に復元情報があるなら上書きしない。A→B→C と辞書が連鎖したとき、上書きすると
        # 戻し先が中間の置換結果 B になり、原文 A にも畳み込んだ後続行にも戻れなくなる。
        # 「戻す」は常に最初の原文まで一段で戻す。
        if self.el.dict_revert is None:
            self.el.dict_revert = self.revert_info

    def undo(self) -> None:
        self.el.text = self.old_text
        self.el.dict_match = self.old_match
        self.el.bbox = self.old_bbox
        self.el.wrap_align = self.old_wrap_align
        self.el.origin_y = self.old_origin_y
        self.el.dict_revert = self.old_revert


class RevertDictMatchCommand:
    """辞書置換を 1 箇所だけ置換前へ戻す (Undo 可)。

    復元元は要素の `dict_revert` (`ReplaceTextCommand` が書く)。`extras` は折返し
    畳み込みで論理削除した後続行で、戻すときに再表示し、undo で再び畳む。
    """

    def __init__(self, el: TextElement, extras: List[TextElement]):
        self.el = el
        self.extras = list(extras)
        info = el.dict_revert
        if info is None:
            raise ValueError("dict_revert が無い要素は戻せない")
        self.info = info
        # undo (= 置換状態へ戻す) 用に現在値を握る
        self.cur_text = el.text
        self.cur_match = el.dict_match
        self.cur_bbox = el.bbox
        self.cur_wrap_align = el.wrap_align
        self.cur_origin_y = el.origin_y
        # extras は「折返し畳み込みで削除された後続行」が典型だが、それを redo が
        # 前提してよいとは限らない (extras の由来は呼び出し元の `dict_revert.extra_ids`
        # で、この要素自身が置換の一部として削除したとは限らない)。実測値を控え、
        # undo では強制 True ではなくここへ戻す。
        self.extra_was_deleted = [e.deleted for e in self.extras]

    def redo(self) -> None:
        self.el.text = self.info.text
        self.el.bbox = self.info.bbox
        self.el.wrap_align = self.info.wrap_align
        self.el.origin_y = self.info.origin_y
        self.el.dict_match = None
        self.el.dict_revert = None
        for ex in self.extras:
            ex.deleted = False

    def undo(self) -> None:
        self.el.text = self.cur_text
        self.el.bbox = self.cur_bbox
        self.el.wrap_align = self.cur_wrap_align
        self.el.origin_y = self.cur_origin_y
        self.el.dict_match = self.cur_match
        self.el.dict_revert = self.info
        for ex, was_deleted in zip(self.extras, self.extra_was_deleted):
            ex.deleted = was_deleted
