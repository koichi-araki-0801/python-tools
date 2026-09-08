"""全角約物 1 文字の字送り (``export/svg_exporter.py``)。

元 PDF が等幅の和文フォントで組まれていると、``］`` は全角枠の左半分・``［`` は右半分に
字面が来る前提で座標が付く (両者の枠はほぼ重なる)。同梱の BIZ UDPGothic はプロポーショナル
なので約物の字面を左へ詰め、そのまま置くと ``］［`` が同じ位置に落ちて 1 つの塊に潰れる。
さらに ``textLength`` で全角幅へ引き伸ばすとグリフ自体が倍幅になり、潰れがより濃くなる。
"""
from __future__ import annotations

import pytest

from export.svg_exporter import page_to_svg
from model.document import Page
from model.elements import Rect, TextElement


def _page_with(text: str, x: float = 100.0, w: float = 11.5) -> str:
    el = TextElement(
        bbox=Rect(x, 50.0, w, 11.5),
        text=text,
        font_family="BIZ UDPGothic",
        font_size=11.5,
        origin_x=x,
        origin_y=60.0,
    )
    page = Page(index=0, width_pt=200.0, height_pt=100.0, elements=[el])
    return next(ln for ln in page_to_svg(page).splitlines() if f">{text}<" in ln)


def test_opening_bracket_is_anchored_to_box_right_edge():
    line = _page_with("［")
    assert "textLength" not in line
    assert 'text-anchor="end"' in line
    assert 'x="111.5"' in line  # bbox の右端 (100 + 11.5)


def test_closing_bracket_stays_at_box_left_edge():
    line = _page_with("］")
    assert "textLength" not in line
    assert "text-anchor" not in line
    assert 'x="100"' in line


def test_katakana_middle_dot_is_centered():
    line = _page_with("・")
    assert "textLength" not in line
    assert 'text-anchor="middle"' in line
    assert 'x="105.75"' in line  # bbox の中央


@pytest.mark.parametrize("ch", ["「", "（", "【", "〔"])
def test_other_opening_punctuation_is_anchored_right(ch):
    assert 'text-anchor="end"' in _page_with(ch)


@pytest.mark.parametrize("ch", ["」", "）", "、", "。"])
def test_other_closing_punctuation_keeps_left_edge(ch):
    line = _page_with(ch)
    assert "textLength" not in line
    assert "text-anchor" not in line


def test_halfwidth_punctuation_keeps_textlength():
    """半角の約物は元 PDF でも字面が詰まっている前提なので従来どおり。"""
    line = _page_with("(", w=5.75)
    assert "textLength=" in line
    assert 'lengthAdjust="spacingAndGlyphs"' in line


def test_multi_character_text_keeps_textlength():
    """約物を含んでいても 2 文字以上なら従来どおり幅を合わせる。"""
    line = _page_with("［実践", w=34.5)
    assert "textLength=" in line
    assert "text-anchor" not in line


def test_single_ideograph_keeps_textlength():
    """約物でない全角 1 文字は従来どおり (字面が枠いっぱいで詰めが起きない)。"""
    line = _page_with("実")
    assert "textLength=" in line
