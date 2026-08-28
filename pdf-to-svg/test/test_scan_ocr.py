"""スキャン判定 (`is_scanned`)・背景画像の SVG 埋め込みの単体テスト (OCR は行わない)。

`load_document` がページをスキャン扱いし `background` を持つこと、`page_to_svg` が
背景を base64 PNG の `<image>` として埋め込むことを確認する。
"""
from engine.pdf_engine import load_document
from export.svg_exporter import page_to_svg


def test_scanned_page_detected(scanned_pdf):
    doc = load_document(str(scanned_pdf))
    pg = doc.pages[0]
    assert pg.is_scanned
    assert pg.background is not None
    assert pg.background.png_bytes


def test_scanned_svg_has_image(scanned_pdf):
    doc = load_document(str(scanned_pdf))
    svg = page_to_svg(doc.pages[0])
    assert "<image" in svg and "data:image/png;base64," in svg
