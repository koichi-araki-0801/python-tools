"""画像 + 不可視 OCR 文字層の PDF に対する抽出・書き出し・RPC の結合テスト。

`ocr_layer_pdf` (conftest) は全面画像の上に不可視 (render_mode=3) の文字を 2 行、可視の
文字を 1 行持つ。不可視文字が `invisible` を持ち、書き出しでは未置換なら出ず・置換済みなら
背景色の矩形 + 文字になることを確認する。
"""
from __future__ import annotations

from engine.pdf_engine import load_document
from model.elements import TextElement


def _texts(page):
    return {e.text: e for e in page.elements if isinstance(e, TextElement)}


def test_invisible_spans_are_flagged(ocr_layer_pdf):
    doc = load_document(str(ocr_layer_pdf))
    pg = doc.pages[0]
    assert not pg.is_scanned  # 文字が 10 文字以上あるのでベクター扱い (従来どおり)
    texts = _texts(pg)
    assert texts["Header Text"].invisible is True
    assert texts["Body line one"].invisible is True
    assert texts["visible text"].invisible is False
    assert all(not e.manual_cover for e in texts.values())


def test_visible_only_pdf_has_no_invisible(vector_pdf):
    doc = load_document(str(vector_pdf))
    assert all(
        not e.invisible for e in doc.pages[0].elements if isinstance(e, TextElement)
    )
