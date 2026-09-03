"""色・画像のグレースケール変換 (``export/grayscale.py``)。

ベクタの色も画像も同じ Rec.601 の整数式で灰色にする。SVG フィルタを使わないのは、
Office がフィルタを無視してカラーのまま貼り付き、ブラウザ印刷が文字をラスタ化するため。
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from export import grayscale
from export.grayscale import to_gray_color, to_gray_image


def test_hex6_uses_rec601_integer_luma():
    # 255*299//1000 = 76 = 0x4c / 255*587//1000 = 149 = 0x95 / 255*114//1000 = 29 = 0x1d
    assert to_gray_color("#ff0000") == "#4c4c4c"
    assert to_gray_color("#00ff00") == "#959595"
    assert to_gray_color("#0000ff") == "#1d1d1d"
    assert to_gray_color("#ffffff") == "#ffffff"
    assert to_gray_color("#000000") == "#000000"


def test_short_hex_and_alpha_are_preserved():
    assert to_gray_color("#f00") == "#4c4c4c"
    assert to_gray_color("#f008") == "#4c4c4c88"
    assert to_gray_color("#ff000080") == "#4c4c4c80"


def test_named_color_is_resolved():
    assert to_gray_color("red") == "#4c4c4c"
    assert to_gray_color("White") == "#ffffff"


def test_passthrough_values():
    assert to_gray_color("none") == "none"
    assert to_gray_color("currentColor") == "currentColor"
    assert to_gray_color(None) is None


def test_rejects_what_sanitize_color_rejects():
    with pytest.raises(ValueError):
        to_gray_color("rgb(0,0,0)")
    with pytest.raises(ValueError):
        to_gray_color('#000"/><script>')
