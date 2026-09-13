"""`export/cover.py` (上書き矩形の採色) の単体テスト。

画像は Pillow で小さく合成する。最頻色 = 背景、2 番目 = 文字色、コントラスト不足と
採取不能のときの黒/白への倒し、画素上限、bbox のクランプを確認する。
"""
from __future__ import annotations

import io
import math

from PIL import Image

from export import cover, grayscale
from model.elements import Rect


def _png(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def _image(w: int, h: int, color, marks=()) -> Image.Image:
    im = Image.new("RGB", (w, h), color)
    for (x, y), c in marks:
        im.putpixel((x, y), c)
    return im


def test_two_colors_background_is_mode_and_text_is_runner_up():
    marks = [((x, 5), (0, 0, 0)) for x in range(3, 8)]  # 5 px の黒
    im = _image(20, 10, (200, 220, 240), marks)
    c = cover.sample_colors(im, Rect(0, 0, 20, 10), Rect(0, 0, 20, 10))
    assert c.background == "#c8dcf0"
    assert c.foreground == "#000000"
    assert c.fallback is False


def test_mean_of_box_not_box_center():
    """白い紙 (255) は箱の中心値 248 ではなく平均値 255 になる。"""
    im = _image(8, 8, (255, 255, 255))
    c = cover.sample_colors(im, Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    assert c.background == "#ffffff"


def test_single_color_picks_text_by_luma():
    light = cover.sample_colors(_image(8, 8, (240, 240, 240)), Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    dark = cover.sample_colors(_image(8, 8, (20, 30, 40)), Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    assert light.foreground == "#000000"
    assert dark.foreground == "#ffffff"
    assert light.fallback is False and dark.fallback is False


def test_low_contrast_runner_up_falls_back_to_black_or_white():
    marks = [((x, 2), (215, 215, 215)) for x in range(0, 4)]  # 背景 200 との差 15 < MIN_CONTRAST
    im = _image(8, 8, (200, 200, 200), marks)
    c = cover.sample_colors(im, Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    assert c.background == "#c8c8c8"
    assert c.foreground == "#000000"


def test_bbox_maps_through_img_rect_scale():
    """画像 40×20px を 20×10pt に貼った場合、pt の bbox は 2 倍して画素へ写す。"""
    marks = [((x, y), (0, 0, 0)) for x in range(20, 40) for y in range(0, 20)]  # 右半分が黒
    im = _image(40, 20, (255, 255, 255), marks)
    left = cover.sample_colors(im, Rect(0, 0, 20, 10), Rect(0, 0, 10, 10))
    right = cover.sample_colors(im, Rect(0, 0, 20, 10), Rect(10, 0, 10, 10))
    assert left.background == "#ffffff"
    assert right.background == "#000000"


def test_bbox_outside_image_is_fallback():
    im = _image(8, 8, (10, 10, 10))
    c = cover.sample_colors(im, Rect(0, 0, 8, 8), Rect(50, 50, 4, 4))
    assert c == cover.CoverColors("#ffffff", "#000000", True)


def test_none_image_is_fallback():
    c = cover.sample_colors(None, Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    assert c == cover.CoverColors("#ffffff", "#000000", True)


def test_decode_image_returns_rgb():
    im = cover.decode_image(_png(_image(4, 4, (1, 2, 3))), "png")
    assert im is not None and im.mode == "RGB" and im.size == (4, 4)


def test_decode_image_rejects_broken_and_oversized(monkeypatch):
    assert cover.decode_image(b"\x89PNG broken", "png") is None
    monkeypatch.setattr(cover, "MAX_COVER_IMAGE_PIXELS", 8)
    assert cover.decode_image(_png(_image(4, 4, (0, 0, 0))), "png") is None


def test_deterministic_tie_break_prefers_smaller_color():
    """同数の 2 色は量子化値の小さい方が背景 (走査順に依存しない)。"""
    marks = [((x, y), (0, 0, 0)) for x in range(0, 4) for y in range(0, 8)]  # 左半分が黒
    im = _image(8, 8, (255, 255, 255), marks)
    c = cover.sample_colors(im, Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    assert c.background == "#000000"
    assert c.foreground == "#ffffff"


def test_non_finite_img_rect_is_fallback_not_exception():
    """`img_rect` が非有限 (inf/nan) でも例外を投げず fallback へ倒す。

    非有限は `sx`/`sy` を inf・nan にし、`math.floor`/`math.ceil` の結果を
    `int()` へ渡す段で `OverflowError`/`ValueError` になる (対策前は `page_to_svg`
    全体を止めていた)。
    """
    im = _image(8, 8, (10, 10, 10))
    for bad_rect in (
        Rect(0, 0, math.inf, 8),
        Rect(0, 0, 8, math.inf),
        Rect(0, 0, math.nan, 8),
        Rect(math.nan, 0, 8, 8),
    ):
        c = cover.sample_colors(im, bad_rect, Rect(0, 0, 8, 8))
        assert c == cover.CoverColors("#ffffff", "#000000", True)


def test_non_finite_bbox_is_fallback_not_exception():
    """`bbox` (置換箇所の矩形) が非有限でも fallback へ倒す。"""
    im = _image(8, 8, (10, 10, 10))
    for bad_bbox in (
        Rect(0, 0, math.inf, 4),
        Rect(0, 0, 4, math.nan),
        Rect(math.inf, math.inf, 4, 4),
    ):
        c = cover.sample_colors(im, Rect(0, 0, 8, 8), bad_bbox)
        assert c == cover.CoverColors("#ffffff", "#000000", True)


def test_bbox_partially_overlapping_image_is_clamped():
    """bbox が画像の右端を越えるとき、画像内側だけへクランプして採色する。"""
    im = _image(8, 8, (10, 20, 30))
    c = cover.sample_colors(im, Rect(0, 0, 8, 8), Rect(4, 0, 8, 8))  # 右半分は画像の外
    assert c == cover.CoverColors("#0a141e", "#ffffff", False)  # 輝度 18 → 暗色: 白


def test_one_pixel_crop_still_samples():
    """1px × 1px までクランプされても採色できる (空クロップにならない)。"""
    im = _image(8, 8, (10, 20, 30))
    c = cover.sample_colors(im, Rect(0, 0, 8, 8), Rect(7, 7, 8, 8))  # クランプで 1x1 になる
    assert c == cover.CoverColors("#0a141e", "#ffffff", False)


def test_max_image_pixels_matches_grayscale():
    """`MAX_COVER_IMAGE_PIXELS` は `grayscale.MAX_GRAY_IMAGE_PIXELS` のコメント同期コピー
    (設計正典に「片方を変えたら両方」とある)。値がずれたら片側の編集漏れなので、
    黙って別の画素数上限になる前にここで落とす。"""
    assert cover.MAX_COVER_IMAGE_PIXELS == grayscale.MAX_GRAY_IMAGE_PIXELS


def test_luma_matches_grayscale():
    """`cover._luma` は `grayscale._luma` のコメント同期コピー。実装がずれると
    上書き矩形の背景色から求める文字色の白黒判定がグレースケール書き出しと食い違う。"""
    for rgb in [(0, 0, 0), (255, 255, 255), (10, 20, 30), (200, 220, 240), (128, 64, 32), (1, 254, 77)]:
        assert cover._luma(*rgb) == grayscale._luma(*rgb)


def _rgba(w: int, h: int, color, alpha_box=None) -> Image.Image:
    """`alpha_box` (x0, y0, x1, y1) の内側だけ不透明、外は完全透明の RGBA 画像。"""
    im = Image.new("RGBA", (w, h), color + (0,))
    if alpha_box is not None:
        x0, y0, x1, y1 = alpha_box
        for x in range(x0, x1):
            for y in range(y0, y1):
                im.putpixel((x, y), color + (255,))
    return im


def test_transparent_pixels_composite_onto_white():
    """透明画素は格納 RGB ではなく白として数える (合成せずに捨てると黒い当て板になる)。"""
    im = cover.decode_image(_png(_rgba(8, 8, (0, 0, 0), alpha_box=(0, 0, 2, 2))), "png")
    assert im is not None and im.mode == "RGB"
    assert im.getpixel((7, 7)) == (255, 255, 255)   # 透明部分 → 白
    assert im.getpixel((0, 0)) == (0, 0, 0)         # 不透明部分 → そのまま


def test_mostly_transparent_image_samples_white_background():
    """透明が多数派の画像では背景色が白になる (黒い矩形で隠さない)。"""
    im = cover.decode_image(_png(_rgba(8, 8, (0, 0, 0), alpha_box=(0, 0, 2, 2))), "png")
    c = cover.sample_colors(im, Rect(0, 0, 8, 8), Rect(0, 0, 8, 8))
    assert c.background == "#ffffff"
    assert c.fallback is False


def test_grayscale_output_is_la_and_composites_to_white():
    """`to_gray_image` は透明を持つ画像を `LA` で返す。グレー書き出しの採色はこの分岐を通る。"""
    from export.grayscale import to_gray_image

    src = _png(_rgba(8, 8, (200, 30, 30), alpha_box=(0, 0, 3, 3)))
    gray_bytes, gray_ext = to_gray_image(src, "png")
    with Image.open(io.BytesIO(gray_bytes)) as g:
        assert g.mode == "LA"
    im = cover.decode_image(gray_bytes, gray_ext)
    assert im is not None and im.mode == "RGB"
    assert im.getpixel((7, 7)) == (255, 255, 255)   # 透明部分 → 白
    assert im.getpixel((0, 0)) != (255, 255, 255)   # 不透明部分 → 灰色が残る


def test_palette_transparency_composites_to_white():
    """透過色を持つパレット画像も白へ合成する (`P` + `transparency`)。"""
    im = Image.new("P", (8, 8), 0)
    im.putpalette([255, 0, 0] + [0, 0, 0] * 255)
    im.info["transparency"] = 0
    decoded = cover.decode_image(_png(im), "png")
    assert decoded is not None
    assert decoded.getpixel((0, 0)) == (255, 255, 255)
