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


def _png(mode: str, color, size=(2, 2)) -> bytes:
    im = Image.new(mode, size, color)
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def test_rgb_image_becomes_L_png_with_same_luma():
    data, ext = to_gray_image(_png("RGB", (255, 0, 0)), "png")
    assert ext == "png"
    with Image.open(io.BytesIO(data)) as im:
        assert im.mode == "L"
        assert im.getpixel((0, 0)) == 76  # to_gray_color("#ff0000") の 0x4c と一致


def test_rgba_image_keeps_alpha_as_LA():
    data, _ = to_gray_image(_png("RGBA", (0, 255, 0, 128)), "png")
    with Image.open(io.BytesIO(data)) as im:
        assert im.mode == "LA"
        assert im.getpixel((0, 0)) == (150, 128)  # Pillow rounds 149.685 to 150


def test_jpeg_input_is_reencoded_as_png():
    im = Image.new("RGB", (2, 2), (0, 0, 255))
    out = io.BytesIO()
    im.save(out, format="JPEG")
    data, ext = to_gray_image(out.getvalue(), "jpeg")
    assert ext == "png"
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_undecodable_bytes_fall_back_to_original():
    junk = b"not an image at all"
    assert to_gray_image(junk, "png") == (junk, "png")


def test_oversized_image_falls_back_to_original(monkeypatch):
    monkeypatch.setattr(grayscale, "MAX_GRAY_IMAGE_PIXELS", 3)
    src = _png("RGB", (10, 20, 30), size=(2, 2))  # 4 画素 > 3
    assert to_gray_image(src, "png") == (src, "png")


def test_conversion_is_cached_per_bytes():
    src = _png("RGB", (1, 2, 3), size=(3, 3))
    to_gray_image.cache_clear()
    to_gray_image(src, "png")
    to_gray_image(src, "png")
    assert to_gray_image.cache_info().hits == 1
