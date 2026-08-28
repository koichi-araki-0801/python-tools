"""抽出 → 辞書適用 → クロップ → SVG 書き出しのエンドツーエンド。"""
import xml.etree.ElementTree as ET

from dictionary import apply as dict_apply
from dictionary.store import DictionaryStore
from engine.pdf_engine import load_document
from export.svg_exporter import _fmt, page_to_svg
from model.elements import TextElement


def test_extract_kinds(vector_pdf):
    doc = load_document(str(vector_pdf))
    pg = doc.pages[0]
    kinds = {e.kind for e in pg.elements}
    assert "text" in kinds and "line" in kinds and "rect" in kinds
    assert not pg.is_scanned


def test_svg_has_text_and_shapes(vector_pdf):
    doc = load_document(str(vector_pdf))
    svg = page_to_svg(doc.pages[0])
    assert "<text" in svg and "Header A" in svg
    assert "<line" in svg and "<rect" in svg
    assert 'viewBox="0 0 300 200"' in svg


def test_paint_order_text_above_banner(banner_pdf):
    """塗り矩形 → 白文字の順で描かれた PDF では、文字が矩形より上に来る。"""
    doc = load_document(str(banner_pdf))
    pg = doc.pages[0]
    text = next(e for e in pg.elements if isinstance(e, TextElement))
    rect = next(e for e in pg.elements if e.kind == "rect")
    assert text.z > rect.z
    svg = page_to_svg(pg)
    assert svg.index("<rect") < svg.index("WHITE TITLE")


def test_deleted_element_excluded(vector_pdf):
    doc = load_document(str(vector_pdf))
    pg = doc.pages[0]
    for e in pg.elements:
        if isinstance(e, TextElement) and e.text == "Value 123":
            e.deleted = True
    svg = page_to_svg(pg)
    assert "Value 123" not in svg
    assert "Header A" in svg


def test_dictionary_auto_apply_on_header(vector_pdf, tmp_path):
    doc = load_document(str(vector_pdf))
    pg = doc.pages[0]
    store = DictionaryStore(tmp_path / "d.json")
    store.add("Header A", "見出し A")
    n = dict_apply.auto_apply(pg, store)
    assert n == 1
    svg = page_to_svg(pg)
    assert "見出し A" in svg
    assert "Header A" not in svg
    store.close()


def test_svg_font_mapped_to_windows_name(vector_pdf):
    """conftest の insert_text は Helvetica → Arial へマッピングされて出力される。"""
    doc = load_document(str(vector_pdf))
    pg = doc.pages[0]
    assert all(e.font_family == "Arial" for e in pg.elements if isinstance(e, TextElement))
    svg = page_to_svg(pg)
    assert "Arial" in svg
    assert "Helvetica" not in svg
    # Windows 標準フォントのみなら @font-face 埋め込みは発生しない
    assert "@font-face" not in svg


def test_svg_textlength_on_unedited_text(vector_pdf):
    """未編集テキストには元 PDF の幅に合わせる textLength が付く。"""
    doc = load_document(str(vector_pdf))
    svg = page_to_svg(doc.pages[0])
    assert "textLength=" in svg
    assert 'lengthAdjust="spacingAndGlyphs"' in svg


def test_svg_unedited_text_uses_baseline(vector_pdf):
    """未編集テキストはベースライン原点に置き、dominant-baseline は付けない (従来不変)。"""
    doc = load_document(str(vector_pdf))
    pg = doc.pages[0]
    el = next(e for e in pg.elements if isinstance(e, TextElement) and e.text == "Value 123")
    svg = page_to_svg(pg)
    line = next(ln for ln in svg.splitlines() if "Value 123" in ln)
    assert 'dominant-baseline' not in line
    assert f'y="{_fmt(el.origin_y)}"' in line


def test_svg_replaced_text_centered_in_box(vector_pdf, tmp_path):
    """箱に収まる置換語は textLength を出さず、元グリフ箱の縦横中央へ据える。

    引き伸ばし (textLength + spacingAndGlyphs) は超過の恐れがあるときだけ。短い置換語へ
    残すとグリフごと水平拡大されて「横太り」に見える退行を起こす。
    """
    doc = load_document(str(vector_pdf))
    pg = doc.pages[0]
    el = next(e for e in pg.elements if isinstance(e, TextElement) and e.text == "Header A")
    cx, cy = el.bbox.x + el.bbox.w / 2, el.bbox.y + el.bbox.h / 2
    store = DictionaryStore(tmp_path / "d.json")
    store.add("Header A", "見出し")
    dict_apply.auto_apply(pg, store)
    store.close()
    svg = page_to_svg(pg)
    line = next(ln for ln in svg.splitlines() if "見出し" in ln)
    assert 'dominant-baseline="central"' in line
    assert 'text-anchor="middle"' in line
    assert "textLength" not in line
    assert f'x="{_fmt(cx)}"' in line and f'y="{_fmt(cy)}"' in line


def test_svg_replaced_text_overflow_keeps_textlength(vector_pdf, tmp_path):
    """箱の幅を超える置換語は従来どおり左端 + textLength で全幅圧縮する。"""
    doc = load_document(str(vector_pdf))
    pg = doc.pages[0]
    el = next(e for e in pg.elements if isinstance(e, TextElement) and e.text == "Header A")
    long_text = "十二全角文字の長い置換語です"  # 概算幅 14 全角 ≫ 元 bbox 幅
    cx = el.bbox.x
    store = DictionaryStore(tmp_path / "d.json")
    store.add("Header A", long_text)
    dict_apply.auto_apply(pg, store)
    store.close()
    svg = page_to_svg(pg)
    line = next(ln for ln in svg.splitlines() if long_text in ln)
    assert "textLength=" in line
    assert 'lengthAdjust="spacingAndGlyphs"' in line
    assert "text-anchor" not in line
    assert f'x="{_fmt(cx)}"' in line


def test_svg_strips_xml_invalid_control_chars(vector_pdf):
    """壊れた ToUnicode CMap 由来の制御文字 (0x01 等) が SVG を壊さない。"""
    doc = load_document(str(vector_pdf))
    pg = doc.pages[0]
    el = next(e for e in pg.elements if isinstance(e, TextElement))
    el.text = "\x01以下本書\x08において"
    svg = page_to_svg(pg)
    assert "\x01" not in svg and "\x08" not in svg
    assert "以下本書において" in svg
    ET.fromstring(svg)  # 不正な XML なら ParseError


def test_svg_embeds_bundled_font_for_japanese(vector_pdf, tmp_path):
    """辞書置換で和文になったテキストは BIZ UD をサブセット埋め込みする。"""
    doc = load_document(str(vector_pdf))
    pg = doc.pages[0]
    store = DictionaryStore(tmp_path / "d.json")
    store.add("Header A", "見出し A")
    dict_apply.auto_apply(pg, store)
    store.close()
    svg = page_to_svg(pg)
    assert "@font-face" in svg
    assert "BIZ UDPGothic" in svg
    assert "data:font/woff2;base64," in svg
    # 箱に収まる置換語は引き伸ばさず (textLength 無し)、元グリフ箱の中央へ据える
    # (text-anchor="middle" + dominant-baseline="central")。
    line = next(ln for ln in svg.splitlines() if "見出し A" in ln)
    assert "textLength" not in line
    assert 'text-anchor="middle"' in line
    assert 'dominant-baseline="central"' in line
    # サブセット化により SVG が肥大しない (フォント全体 ~5MB に対し数十 KB)
    assert len(svg) < 200_000
