"""画像 + 不可視 OCR 文字層の PDF に対する抽出・書き出し・RPC の結合テスト。

`ocr_layer_pdf` (conftest) は全面画像の上に不可視 (render_mode=3) の文字を 2 行、可視の
文字を 1 行持つ。不可視文字が `invisible` を持ち、書き出しでは未置換なら出ず・置換済みなら
背景色の矩形 + 文字になることを確認する。
"""
from __future__ import annotations

import io
import re

from PIL import Image

from dictionary import apply as dict_apply
from dictionary.store import DictionaryStore
from engine.pdf_engine import load_document
from export import cover
from export.svg_exporter import ExportReport, page_to_svg
from model.document import Page, RasterBackground
from model.elements import DictMatch, Rect, TextElement


def _texts(page):
    return {e.text: e for e in page.elements if isinstance(e, TextElement)}


def _line_with(svg: str, needle: str) -> str:
    return next(ln for ln in svg.splitlines() if needle in ln)


def _replace(pg, tmp_path, source, target):
    store = DictionaryStore(tmp_path / "d.json")
    store.add(source, target)
    n = dict_apply.auto_apply(pg, store)
    store.close()
    assert n == 1


def test_invisible_spans_are_flagged(ocr_layer_pdf):
    doc = load_document(str(ocr_layer_pdf))
    pg = doc.pages[0]
    assert not pg.is_scanned  # 文字が 10 文字以上あるのでベクター扱い (従来どおり)
    texts = _texts(pg)
    assert texts["Header Text"].invisible is True
    assert texts["Body line one"].invisible is True
    assert texts["visible text"].invisible is False
    assert all(not e.manual_cover for e in texts.values())


def test_visible_only_pdf_has_no_invisible(vector_pdf):
    doc = load_document(str(vector_pdf))
    assert all(
        not e.invisible for e in doc.pages[0].elements if isinstance(e, TextElement)
    )


def test_unreplaced_invisible_text_is_omitted_from_export(ocr_layer_pdf):
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    svg = page_to_svg(pg)
    assert "Header Text" not in svg and "Body line one" not in svg
    assert "visible text" in svg  # 可視文字は従来どおり


def test_unreplaced_invisible_text_is_transparent_in_annotate(ocr_layer_pdf):
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    svg = page_to_svg(pg, annotate=True)
    line = _line_with(svg, "Header Text")
    assert line.startswith("<text data-el=")
    assert 'fill-opacity="0"' in line
    assert 'fill="' in line  # fill を残さないと当たり判定から外れる (クリック取り込みが効かなくなる)
    assert 'fill-opacity' not in _line_with(svg, "visible text")


def test_replaced_invisible_text_is_covered_with_sampled_colors(ocr_layer_pdf, tmp_path):
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    _replace(pg, tmp_path, "Header Text", "見出し")
    el = _texts(pg)["見出し"]
    svg = page_to_svg(pg)
    line = _line_with(svg, "見出し")
    assert line.startswith("<g><rect ")
    assert line.endswith("</text></g>")
    assert 'fill="#c8dcf0"' in line.split("<text")[0]  # 帯色 (200, 220, 240)
    assert 'fill="#000000"' in line.split("<text")[1]  # 単色領域 → 輝度で黒
    assert 'dominant-baseline="central"' in line  # 置換枝の据え方を流用


def test_replaced_invisible_text_on_white_uses_white(ocr_layer_pdf, tmp_path):
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    _replace(pg, tmp_path, "Body line one", "本文")
    line = _line_with(page_to_svg(pg), "本文")
    assert 'fill="#ffffff"' in line.split("<text")[0]


def test_replaced_invisible_text_annotate_puts_data_el_on_group(ocr_layer_pdf, tmp_path):
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    _replace(pg, tmp_path, "Header Text", "見出し")
    el = _texts(pg)["見出し"]
    line = _line_with(page_to_svg(pg, annotate=True), "見出し")
    assert line.startswith(f'<g data-el="{el.id}"><rect ')
    assert line.count("data-el=") == 1


def test_grayscale_converts_cover_colors(ocr_layer_pdf, tmp_path):
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    _replace(pg, tmp_path, "Header Text", "見出し")
    line = _line_with(page_to_svg(pg, grayscale=True), "見出し")
    assert not re.search(r'="#(?!([0-9a-f]{2})\1\1")[0-9a-f]{6}"', line)  # 有彩色が残らない


def test_cover_fallback_is_counted(ocr_layer_pdf, tmp_path, monkeypatch):
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    _replace(pg, tmp_path, "Header Text", "見出し")
    monkeypatch.setattr(cover, "MAX_COVER_IMAGE_PIXELS", 10)  # 画像をデコードできない状況
    report = ExportReport()
    svg = page_to_svg(pg, report=report)
    line = _line_with(svg, "見出し")
    assert 'fill="#ffffff"' in line.split("<text")[0]
    assert report.cover_fallback == 1


def test_report_is_optional_and_zero_without_invisible(vector_pdf):
    pg = load_document(str(vector_pdf)).pages[0]
    report = ExportReport()
    assert page_to_svg(pg, report=report) == page_to_svg(pg)
    assert report.cover_fallback == 0


def test_font_embedding_skips_omitted_invisible_text(ocr_layer_pdf, tmp_path):
    """書き出しで出さない不可視文字は、埋め込みフォントの収集にも入らない。"""
    pg = load_document(str(ocr_layer_pdf)).pages[0]
    for e in pg.elements:
        if isinstance(e, TextElement) and e.invisible:
            e.font_family = "BIZ UDPGothic"
    assert "<style>" not in page_to_svg(pg)


def test_scanned_background_is_used_for_sampling(tmp_path):
    """`ImageElement` が無いスキャンページでも、`page.background` から採色する。"""
    solid = Image.new("RGB", (10, 10), (10, 20, 30))
    buf = io.BytesIO()
    solid.save(buf, format="PNG")
    el = TextElement(
        bbox=Rect(0, 0, 10, 10),
        text="見出し",
        original_text="Header",
        invisible=True,
        manual_cover=True,
        dict_match=DictMatch(source="Header", target="見出し"),
    )
    pg = Page(
        index=0,
        width_pt=10,
        height_pt=10,
        is_scanned=True,
        background=RasterBackground(png_bytes=buf.getvalue(), rect=Rect(0, 0, 10, 10)),
        elements=[el],
    )
    svg = page_to_svg(pg)
    line = _line_with(svg, "見出し")
    assert 'fill="#0a141e"' in line.split("<text")[0]
    assert 'fill="#ffffff"' in line.split("<text")[1]
