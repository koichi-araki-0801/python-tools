"""Document / Page コンテナ。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .elements import Element, Rect


@dataclass
class RasterBackground:
    """スキャンページ等のラスタ背景。"""

    png_bytes: bytes
    rect: Rect


@dataclass
class Page:
    index: int
    width_pt: float
    height_pt: float
    is_scanned: bool = False
    background: Optional[RasterBackground] = None
    elements: List[Element] = field(default_factory=list)
    # 要素数の資源上限に当たって抽出を打ち切ったか (`engine/pdf_engine.py` の
    # `MAX_PAGE_ELEMENTS` / `MAX_DOC_ELEMENTS`)。UI が「一部を読み飛ばした」と伝える
    # ための印で、無言で欠落させないために持つ。
    truncated: bool = False

    def live_elements(self) -> List[Element]:
        """削除されていない要素 (z 昇順)。"""
        items = [e for e in self.elements if not e.deleted]
        return sorted(items, key=lambda e: e.z)

    def export_rect(self) -> Rect:
        """書き出し領域 (ページ全体)。"""
        return Rect(0, 0, self.width_pt, self.height_pt)


@dataclass
class Document:
    source_path: str
    pages: List[Page] = field(default_factory=list)
