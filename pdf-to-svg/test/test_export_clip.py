"""``page_to_svg`` の ``grayscale`` / ``clip`` オプション。

既定 (両方 OFF) は従来出力とバイト一致 (``test_pipeline.py`` が固定)。ON の出力は
決定的で、グレーは有彩色 hex を 1 つも残さず、clip は viewBox と要素の取捨に効く。
"""
from __future__ import annotations

import io
import re

import pytest
from PIL import Image

from export.svg_exporter import page_to_svg
from model.document import Page, RasterBackground
from model.elements import ImageElement, LineElement, PathElement, Rect, RectElement, TextElement

# "#rrggbb" のうち r・g・b が揃っていないもの = 有彩色
_CHROMATIC = re.compile(r"#(?!([0-9a-f]{2})\1\1(?:[0-9a-f]{2})?[\"\s])[0-9a-f]{6}")


def _png(color) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (2, 2), color).save(out, format="PNG")
    return out.getvalue()


def _page() -> Page:
    pg = Page(index=0, width_pt=300, height_pt=200)
    pg.elements = [
        TextElement(bbox=Rect(10, 10, 60, 12), text="Hello", origin_x=10, origin_y=20, color="#3333cc", z=0),
        LineElement(bbox=Rect(10, 30, 100, 0), x0=10, y0=30, x1=110, y1=30, color="#ff0000", z=1),
        RectElement(bbox=Rect(200, 150, 50, 30), rect=Rect(200, 150, 50, 30), fill="#00ff00", stroke="#0000ff", z=2),
        PathElement(bbox=Rect(120, 120, 40, 40), d="M120 120 C 130 100 150 160 160 160", stroke="#ff8800", fill=None, z=3),
        ImageElement(bbox=Rect(20, 100, 40, 40), rect=Rect(20, 100, 40, 40), img_bytes=_png((255, 0, 0)), ext="png", z=4),
    ]
    return pg


def test_default_arguments_do_not_change_output():
    pg = _page()
    assert page_to_svg(pg) == page_to_svg(pg, grayscale=False, clip=None)
    assert 'fill="#3333cc"' in page_to_svg(pg)


def test_grayscale_leaves_no_chromatic_hex():
    svg = page_to_svg(_page(), grayscale=True)
    assert not _CHROMATIC.search(svg), svg
    # #3333cc → Pillow の固定小数点式 (51*19595 + 51*38470 + 204*7471 + 0x8000) >> 16 = 68 = 0x44
    assert 'fill="#444444"' in svg


def test_grayscale_converts_images_and_background():
    pg = _page()
    pg.background = RasterBackground(png_bytes=_png((0, 0, 255)), rect=Rect(0, 0, 300, 200))
    svg = page_to_svg(pg, grayscale=True)
    # 画像は 2 枚 (背景 + ImageElement) とも PNG の data URI で、中身は L モード
    hrefs = re.findall(r'xlink:href="data:image/png;base64,([^"]+)"', svg)
    assert len(hrefs) == 2
    import base64
    for b64 in hrefs:
        with Image.open(io.BytesIO(base64.b64decode(b64))) as im:
            assert im.mode == "L"


def test_grayscale_output_is_deterministic():
    pg = _page()
    assert page_to_svg(pg, grayscale=True) == page_to_svg(pg, grayscale=True)


def test_clip_sets_viewbox_and_drops_outside_elements():
    svg = page_to_svg(_page(), clip=Rect(0, 0, 100, 100))
    assert 'viewBox="0 0 100 100"' in svg
    assert 'width="100"' in svg and 'height="100"' in svg
    assert "Hello" in svg                      # (10,10) は clip 内
    assert 'x="200"' not in svg               # (200,150) の矩形は clip 外
    # id は clip 矩形ごとに決定的 (座標を含む)。複数ページを 1 文書に inline しても衝突しない。
    assert '<clipPath id="clip-0-0-100-100">' in svg
    assert '<rect x="0" y="0" width="100" height="100"/>' in svg
    assert '<g clip-path="url(#clip-0-0-100-100)">' in svg
    assert svg.rstrip().endswith("</g>\n</svg>")


def test_clip_offset_origin():
    svg = page_to_svg(_page(), clip=Rect(100, 100, 100, 100))
    assert 'viewBox="100 100 100 100"' in svg
    assert "Hello" not in svg                  # clip 外
    assert 'd="M120 120' in svg                # 曲線は clip 内
    assert '<clipPath id="clip-100-100-100-100">' in svg
    assert '<g clip-path="url(#clip-100-100-100-100)">' in svg


def test_clip_id_is_unique_per_rect_within_a_document():
    """異なる clip 矩形を同じページから 2 回書き出しても id が衝突しない
    (2 ページ分の SVG を 1 文書へ inline したときに `<clipPath>` の id 重複を防ぐ)。"""
    svg1 = page_to_svg(_page(), clip=Rect(0, 0, 100, 100))
    svg2 = page_to_svg(_page(), clip=Rect(10, 20, 30, 40))
    id1 = re.search(r'clipPath id="([^"]+)"', svg1).group(1)
    id2 = re.search(r'clipPath id="([^"]+)"', svg2).group(1)
    assert id1 != id2
    assert id2 == "clip-10-20-30-40"


def test_clip_with_zero_size_is_rejected():
    with pytest.raises(ValueError):
        page_to_svg(_page(), clip=Rect(0, 0, 0, 10))


def test_no_clip_has_no_clippath():
    assert "clipPath" not in page_to_svg(_page())


def _page_with_clipped_image() -> Page:
    """クリップ形状を持つ画像 1 枚だけのページ。"""
    pg = Page(index=0, width_pt=100, height_pt=100)
    pg.elements = [
        ImageElement(
            bbox=Rect(10, 10, 40, 40),
            rect=Rect(10, 10, 40, 40),
            img_bytes=_png((255, 0, 0)),
            ext="png",
            z=0,
            clip_d="M10,10 L50,10 L50,50 Z",
        )
    ]
    return pg


def test_image_clip_emits_clippath_and_reference():
    """クリップ形状を持つ画像は <defs><clipPath> を伴い、<image> がそれを参照する。"""
    svg = page_to_svg(_page_with_clipped_image())
    cid = re.search(r'<clipPath id="(imgclip-[0-9a-f]+)">', svg).group(1)
    assert f'<clipPath id="{cid}"><path d="M10,10 L50,10 L50,50 Z"/></clipPath>' in svg
    assert f'clip-path="url(#{cid})"' in svg
    # <image> は単一タグのままであること (annotate の data-el 差し込みが開きタグを壊さない)
    assert svg.count("<image ") == 1


def test_image_without_clip_has_no_clippath():
    """clip_d が空の画像は従来どおり <clipPath> を作らない (既存出力を変えない)。"""
    pg = _page_with_clipped_image()
    pg.elements[0].clip_d = ""
    svg = page_to_svg(pg)
    assert "clipPath" not in svg
    assert "clip-path" not in svg


def test_same_clip_shape_is_defined_once():
    """同じ形状を使う画像が複数あっても <clipPath> の定義は 1 個にまとまる。"""
    from copy import deepcopy

    pg = _page_with_clipped_image()
    dup = deepcopy(pg.elements[0])
    dup.z = 2
    pg.elements.append(dup)
    svg = page_to_svg(pg)
    assert svg.count("<clipPath ") == 1
    assert svg.count("clip-path=") == 2


def test_image_clip_id_is_deterministic():
    """同一モデルからは常に同一の id が出る (決定的出力の不変則)。"""
    a = page_to_svg(_page_with_clipped_image())
    b = page_to_svg(_page_with_clipped_image())
    assert a == b


def test_image_clip_survives_annotate():
    """annotate=True でも <image> の開きタグに data-el が入り、clip-path が残る。"""
    svg = page_to_svg(_page_with_clipped_image(), annotate=True)
    assert re.search(r'<image data-el="\d+" ', svg)
    assert "clip-path=" in svg


def test_page_clip_and_image_clip_combine():
    """ページ全体の clip (書き出し領域) と画像の clip_d (切り抜き形状) を同時に使うと、
    <defs> が 2 ブロック出て (領域用の clip-... と画像用の imgclip-...)、どちらの id も
    出力に現れ、<image> は imgclip- を参照する。"""
    svg = page_to_svg(_page_with_clipped_image(), clip=Rect(0, 0, 100, 100))
    assert svg.count("<defs>") == 2
    assert '<clipPath id="clip-0-0-100-100">' in svg
    assert '<g clip-path="url(#clip-0-0-100-100)">' in svg
    cid = re.search(r'<clipPath id="(imgclip-[0-9a-f]+)">', svg).group(1)
    assert f'<clipPath id="{cid}"><path d="M10,10 L50,10 L50,50 Z"/></clipPath>' in svg
    assert f'clip-path="url(#{cid})"' in svg
    assert svg.count("<image ") == 1
