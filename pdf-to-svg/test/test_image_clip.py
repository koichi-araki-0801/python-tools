"""PDF のクリップパス (`W n`) で切り抜かれた画像を、SVG でも同じ形に切り抜く。

シェーディングを螺旋等の形へ切り抜いて描く PDF では、クリップを落とすと bbox の矩形が
そのまま貼られ、下に正しく描かれている図形を不透明な矩形が覆い隠す。
"""
from __future__ import annotations

import fitz

from engine.pdf_engine import _clip_index, load_document
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


def test_rect_only_clip_is_ignored():
    """items が矩形 1 個だけの clip は無視する (画像 bbox と同じで切り抜きの効果が無い)。

    ページ全体を覆う既定のクリップは全 PDF に付くため、これを拾うと無意味な
    <clipPath> が画像の数だけ増える。

    `_clip_index` を直接呼んで検証する。画像を持たないページ (`vector_pdf` 等) で
    `page_to_svg` の出力を見る形にすると、そもそも <image> も imgclip- も出しようが
    ないため assertion が構造的に常に真になってしまい、「items が矩形 1 個だけの
    clip は索引へ入れない」という仕様を検証できない (rect-only スキップ分岐を
    削除しても壊れないテストになる)。対比として、re 以外の items を持つ clip は
    同じ scissor でも索引に入ることも確かめ、「常に空になるだけの索引」に
    すり替わっていないことを示す。
    """
    scissor = fitz.Rect(50, 50, 150, 150)
    rect_only_clip = {
        "type": "clip",
        "scissor": scissor,
        "items": [("re", scissor)],
    }
    triangle_clip = {
        "type": "clip",
        "scissor": scissor,
        "items": [
            ("l", fitz.Point(50, 50), fitz.Point(150, 50)),
            ("l", fitz.Point(150, 50), fitz.Point(150, 150)),
            ("l", fitz.Point(150, 150), fitz.Point(50, 50)),
        ],
    }

    assert _clip_index([rect_only_clip]) == {}
    assert len(_clip_index([triangle_clip])) == 1
