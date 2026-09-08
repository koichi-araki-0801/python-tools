"""PDF のクリップパス (`W n`) で切り抜かれた画像を、SVG でも同じ形に切り抜く。

シェーディングを螺旋等の形へ切り抜いて描く PDF では、クリップを落とすと bbox の矩形が
そのまま貼られ、下に正しく描かれている図形を不透明な矩形が覆い隠す。
"""
from __future__ import annotations

from engine.pdf_engine import load_document
from export.svg_exporter import page_to_svg
from model.elements import ImageElement


def _images(page):
    return [e for e in page.live_elements() if isinstance(e, ImageElement)]


def test_clipped_image_gets_clip_path(clipped_image_pdf):
    """クリップ下で描かれた画像には clip_d が入る。"""
    doc = load_document(str(clipped_image_pdf))
    imgs = _images(doc.pages[0])
    assert len(imgs) == 1
    assert imgs[0].clip_d != ""
    # 三角形の 3 頂点が d に現れる (M/L の並びは _items_to_path_d の出力形式)
    assert "M50,50" in imgs[0].clip_d
    assert "L150,50" in imgs[0].clip_d


def test_clipped_image_svg_has_clippath(clipped_image_pdf):
    """書き出した SVG に <clipPath> が出て、<image> がそれを参照する。"""
    doc = load_document(str(clipped_image_pdf))
    svg = page_to_svg(doc.pages[0])
    assert "<clipPath id=\"imgclip-" in svg
    assert "clip-path=\"url(#imgclip-" in svg


def test_unclipped_image_has_no_clip(scanned_pdf):
    """クリップの無い画像には clip_d が入らない (既存 PDF の出力を変えない)。"""
    doc = load_document(str(scanned_pdf))
    for pg in doc.pages:
        for img in _images(pg):
            assert img.clip_d == ""


def test_rect_only_clip_is_ignored(vector_pdf):
    """items が矩形 1 個だけの clip は無視する (画像 bbox と同じで切り抜きの効果が無い)。

    ページ全体を覆う既定のクリップは全 PDF に付くため、これを拾うと無意味な
    <clipPath> が画像の数だけ増える。
    """
    doc = load_document(str(vector_pdf))
    svg = page_to_svg(doc.pages[0])
    assert "imgclip-" not in svg
