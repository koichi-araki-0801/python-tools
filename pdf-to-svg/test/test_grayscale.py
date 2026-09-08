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


def test_hex6_uses_pillow_luma():
    # Pillow の固定小数点式 (ITU-R 601-2): (R*19595 + G*38470 + B*7471 + 0x8000) >> 16
    # #ff0000: (255*19595 + 0 + 0 + 32768) >> 16 = 76 = 0x4c
    # #00ff00: (0 + 255*38470 + 0 + 32768) >> 16 = 150 = 0x96
    # #0000ff: (0 + 0 + 255*7471 + 32768) >> 16 = 29 = 0x1d
    assert to_gray_color("#ff0000") == "#4c4c4c"
    assert to_gray_color("#00ff00") == "#969696"
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
        # to_gray_color("#ff0000") の 0x4c = 76 にトーン補正を掛けた値
        assert im.getpixel((0, 0)) == grayscale.tone_curve(76)


def test_rgba_image_keeps_alpha_as_LA():
    data, _ = to_gray_image(_png("RGBA", (0, 255, 0, 128)), "png")
    with Image.open(io.BytesIO(data)) as im:
        assert im.mode == "LA"
        # 固定小数点式で #00ff00 は 150。アルファは補正を通しても素通し。
        assert im.getpixel((0, 0)) == (grayscale.tone_curve(150), 128)


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


def test_vector_and_image_luma_agree():
    """to_gray_color と to_gray_image が同じ Pillow 固定小数点式を使う (画像はトーン補正の分だけ明るい)。"""
    for rgb in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (51, 51, 204), (200, 100, 30)):
        hex_in = "#%02x%02x%02x" % rgb
        luma = int(to_gray_color(hex_in)[1:3], 16)
        data, _ = to_gray_image(_png("RGB", rgb, size=(1, 1)), "png")
        with Image.open(io.BytesIO(data)) as im:
            assert im.getpixel((0, 0)) == grayscale.tone_curve(luma), rgb


# --- smtam 公式モノクロ版への配色合わせ ---------------------------------------
# 三井住友トラスト・アセットマネジメントの運用報告書は、同じ図のカラー版とモノクロ版を
# 別々に配布している。モノクロ版はデザイナによる階調の再割当で、輝度変換では再現できない
# (赤 #f15b66 は輝度 137 相当だが、モノクロ版では最も濃い #231f20 に割り当てられている)。


def test_smtam_brand_colors_map_to_official_mono_palette():
    # カラー版 _id_140823_type_k とモノクロ版 _id_142871_type_k で図形 568 個の座標が
    # 一致し、そこから機械的に抽出した対応表 (7 組)。
    assert to_gray_color("#009eb4") == "#939598"
    assert to_gray_color("#3e8d60") == "#939598"
    assert to_gray_color("#f15b66") == "#231f20"
    assert to_gray_color("#09b26a") == "#4d4d4f"
    assert to_gray_color("#faa619") == "#6d6e71"
    assert to_gray_color("#b75669") == "#808285"
    assert to_gray_color("#bc9632") == "#a7a9ac"


def test_smtam_map_is_case_insensitive_and_keeps_alpha():
    assert to_gray_color("#009EB4") == "#939598"
    assert to_gray_color("#009eb480") == "#93959880"


def test_official_mono_colors_are_left_untouched():
    # 既にモノクロで配布されている報告書 (_id_142871 / _id_510183 / _id_510186) を
    # グレーモードで通しても色が 1 つも動かない。同社が黒に使う #231f20 は厳密には
    # 有彩色 (R-B 差 4) で、輝度変換すると #202020 へ寄ってしまう。
    for v in ("#231f20", "#4d4d4f", "#6d6e71", "#808285", "#939598", "#a7a9ac", "#dcddde"):
        assert to_gray_color(v) == v


def test_barely_chromatic_color_is_left_untouched():
    assert to_gray_color("#808184") == "#808184"  # チャンネル差 4 = 許容内
    assert to_gray_color("#808086") == "#808086"  # チャンネル差 6 = 許容の上限


def test_clearly_chromatic_color_still_converts():
    # チャンネル差 8 = 許容外。(128*19595 + 128*38470 + 136*7471 + 0x8000) >> 16 = 129
    assert to_gray_color("#808088") == "#818181"


# --- 画像のトーン補正 ---------------------------------------------------------
# ベクタの色は SMTAM_MONO_COLORS で公式モノクロ版の値そのものに合わせられるが、埋め込み画像
# (螺旋・矢印) はモノクロ版が別アセットのため対応表を作れない。カラー版を輝度変換した結果と
# モノクロ版を画素ごとに突き合わせた回帰でガンマ 0.8 が最良だった (平均絶対誤差 24.1 → 10.9)。


def test_chromatic_image_gets_tone_correction():
    # #ff0000 の輝度 76 に IMAGE_TONE_GAMMA を掛けた値。輝度そのままでは公式版より暗い。
    data, _ = to_gray_image(_png("RGB", (255, 0, 0)), "png")
    with Image.open(io.BytesIO(data)) as im:
        assert im.getpixel((0, 0)) == grayscale.tone_curve(76)
        assert im.getpixel((0, 0)) > 76


def test_tone_curve_keeps_endpoints():
    assert grayscale.tone_curve(0) == 0
    assert grayscale.tone_curve(255) == 255


def test_already_gray_image_is_not_brightened():
    # 既にモノクロで配布されている報告書の画像 (グレーだが RGBA で入っている) は動かさない。
    # 補正を掛けると公式版より明るくなり、かえってずれる。
    data, _ = to_gray_image(_png("RGBA", (128, 128, 128, 255)), "png")
    with Image.open(io.BytesIO(data)) as im:
        assert im.getpixel((0, 0)) == (128, 255)


def test_L_mode_image_is_not_brightened():
    data, _ = to_gray_image(_png("L", 100), "png")
    with Image.open(io.BytesIO(data)) as im:
        assert im.getpixel((0, 0)) == 100
