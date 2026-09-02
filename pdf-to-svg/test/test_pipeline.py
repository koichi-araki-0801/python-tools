"""抽出 → 辞書適用 → クロップ → SVG 書き出しのエンドツーエンド。"""
import xml.etree.ElementTree as ET
from io import BytesIO

from fontTools.ttLib import TTFont

from dictionary import apply as dict_apply
from dictionary.store import DictionaryStore
from engine.pdf_engine import load_document
from export import font_embed
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


def test_subset_font_does_not_recalc_timestamp():
    """サブセット出力へ実行時刻を混ぜない (「SVG 出力は決定的」の前提)。

    fontTools は保存時に `head.modified` を現在時刻へ書き換えるのが既定のため、
    そのままだと同じページを書き出すたびに埋め込みフォントのバイト列が変わり、
    「同一モデル → 同一 SVG」が秒をまたいだ瞬間に崩れる。ソース側の値を保つこと。
    """
    name = "BIZUDPGothic-Regular.ttf"
    source = TTFont(BytesIO(font_embed._source_font_bytes(name)))
    subset = TTFont(BytesIO(font_embed._subset_woff2(name, set("見出し"))))
    assert subset["head"].modified == source["head"].modified


def test_svg_with_embedded_font_is_byte_stable(vector_pdf, tmp_path):
    """フォントを埋め込むページでも、同じモデルからの書き出しはバイト単位で一致する。"""
    doc = load_document(str(vector_pdf))
    pg = doc.pages[0]
    store = DictionaryStore(tmp_path / "d.json")
    store.add("Header A", "見出し A")
    dict_apply.auto_apply(pg, store)
    store.close()

    first = page_to_svg(pg)
    assert "data:font/woff2;base64," in first   # 埋め込みが起きる経路であることの確認
    assert page_to_svg(pg) == first


def _save_encrypted(vector_pdf, out, **kw):
    """`vector_pdf` を AES-256 で暗号化して `out` へ保存する (テスト用ヘルパ)。"""
    import fitz

    with fitz.open(str(vector_pdf)) as src:
        src.save(str(out), encryption=fitz.PDF_ENCRYPT_AES_256, **kw)
    return out


def test_user_password_pdf_is_rejected_with_japanese_message(vector_pdf, tmp_path):
    """開封パスワード付き PDF は、PyMuPDF の内部エラー文ではなく利用者向けの日本語で拒否する。"""
    import pytest

    locked = _save_encrypted(vector_pdf, tmp_path / "locked.pdf",
                             user_pw="secret", owner_pw="owner", permissions=0)
    with pytest.raises(ValueError, match="パスワード"):
        load_document(str(locked))


def test_owner_password_only_pdf_loads_like_plain(vector_pdf, tmp_path):
    """権限制限だけ (開封パスワード無し) の PDF は平文と同じ SVG を出す。"""
    limited = _save_encrypted(vector_pdf, tmp_path / "limited.pdf",
                              user_pw="", owner_pw="owner", permissions=0)
    plain = page_to_svg(load_document(str(vector_pdf)).pages[0])
    assert page_to_svg(load_document(str(limited)).pages[0]) == plain
