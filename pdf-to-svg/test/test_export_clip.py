"""``page_to_svg`` の ``grayscale`` / ``clip`` オプション。

既定 (両方 OFF) は従来出力とバイト一致 (``test_pipeline.py`` が固定)。ON の出力は
決定的で、グレーは有彩色 hex を 1 つも残さず、clip は viewBox と要素の取捨に効く。
"""
from __future__ import annotations

import io
import re

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
    # #3333cc → (51*299 + 51*587 + 204*114) // 1000 = 68 = 0x44
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
