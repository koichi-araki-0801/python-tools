"""中間モデル (Page) を SVG 文字列へ直接シリアライズする。

scene は編集 UI、モデルが真実。書き出しはモデルから直接行うことで決定的になり、
GUI なしでテスト可能・フォント名の崩れも起きない。
"""
from __future__ import annotations

import base64
from typing import List
from xml.sax.saxutils import escape, quoteattr

from export import font_embed
from model import fonts
from model.document import Page
from model.elements import (
    ImageElement,
    LineElement,
    PathElement,
    Rect,
    RectElement,
    TextElement,
    sanitize_color,
    sanitize_text,
)


def _fmt(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


# 既知拡張子だけの固定表 (`web/server.py` の `_MIME` と同型)。PDF から抽出した画像の ext は
# PyMuPDF の申告値をそのまま使っているため、任意拡張子から MIME を組み立てると
# `data:image/svg+xml;base64,...` 等の任意 MIME を作らせる入口になる。
_IMAGE_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
}


def _mime(ext: str) -> str:
    # 未知拡張子は `application/octet-stream` へ倒す (fail-close)。data URI の中身を
    # ブラウザが画像としてスニッフしないため、埋め込み画像相当には見えなくなる。
    return _IMAGE_MIME.get(ext.lower(), "application/octet-stream")


def page_to_svg(page: Page, *, annotate: bool = False) -> str:
    """Page を SVG 文字列へ。

    annotate=True のとき各要素タグに ``data-el="<id>"`` を付与する (Web UI が
    要素をクリック選択・ハイライトするため)。デフォルト False で従来出力と完全一致
    (テスト・書き出しは不変)。
    """
    rect = page.export_rect()
    lines: List[str] = []
    lines.append('<?xml version="1.0" encoding="UTF-8"?>')
    viewbox = f"{_fmt(rect.x)} {_fmt(rect.y)} {_fmt(rect.w)} {_fmt(rect.h)}"
    lines.append(
        "<svg "
        + _attr("xmlns", "http://www.w3.org/2000/svg")
        + " "
        + _attr("xmlns:xlink", "http://www.w3.org/1999/xlink")
        + " "
        + _attr("width", _fmt(rect.w))
        + " "
        + _attr("height", _fmt(rect.h))
        + " "
        + _attr("viewBox", viewbox)
        + ">"
    )

    # スキャン背景
    if page.background is not None:
        b = page.background
        if _intersects_export(b.rect, rect):
            lines.append(_image_tag(b.rect, b.png_bytes, "png"))

    text_els: List[TextElement] = []
    for el in page.live_elements():
        if not _intersects_export(el.bbox, rect):
            continue
        svg = _element_to_svg(el)
        if svg:
            if annotate:
                svg = _with_data_el(svg, el.id)
            lines.append(svg)
            if isinstance(el, TextElement):
                text_els.append(el)

    # 同梱フォント (BIZ UD) を使う場合のみサブセット WOFF2 を埋め込む
    css = font_embed.font_face_css(text_els)
    if css:
        lines.insert(2, f"<style>{css}</style>")

    lines.append("</svg>")
    return "\n".join(lines)


def _with_data_el(svg: str, el_id: int) -> str:
    """単一要素タグの開きタグ直後に data-el 属性を差し込む。"""
    # 先頭は必ず "<tagname" なので、最初の空白の位置に属性を挿入する。
    sp = svg.find(" ")
    if sp < 0:
        return svg
    return f"{svg[:sp]} {_attr('data-el', el_id)}{svg[sp:]}"


def _intersects_export(bbox: Rect, export: Rect) -> bool:
    # 幅・高さが 0 の要素 (細い罫線等) も拾えるよう緩めに交差判定
    if bbox.w == 0 and bbox.h == 0:
        return export.x <= bbox.x <= export.x1 and export.y <= bbox.y <= export.y1
    return bbox.intersects(export)


def _element_to_svg(el) -> str:
    if isinstance(el, TextElement):
        return _text_to_svg(el)
    if isinstance(el, LineElement):
        return (
            "<line "
            + _attr("x1", _fmt(el.x0))
            + " "
            + _attr("y1", _fmt(el.y0))
            + " "
            + _attr("x2", _fmt(el.x1))
            + " "
            + _attr("y2", _fmt(el.y1))
            + " "
            + _attr("stroke", sanitize_color(el.color))
            + " "
            + _attr("stroke-width", _fmt(el.width))
            + "/>"
        )
    if isinstance(el, RectElement):
        return (
            "<rect "
            + _attr("x", _fmt(el.rect.x))
            + " "
            + _attr("y", _fmt(el.rect.y))
            + " "
            + _attr("width", _fmt(el.rect.w))
            + " "
            + _attr("height", _fmt(el.rect.h))
            + " "
            + _paint("fill", el.fill)
            + " "
            + _paint("stroke", el.stroke)
            + " "
            + _attr("stroke-width", _fmt(el.stroke_width))
            + "/>"
        )
    if isinstance(el, PathElement):
        return (
            "<path "
            + _attr("d", el.d)
            + " "
            + _paint("fill", el.fill)
            + " "
            + _paint("stroke", el.stroke)
            + " "
            + _attr("stroke-width", _fmt(el.stroke_width))
            + "/>"
        )
    if isinstance(el, ImageElement):
        return _image_tag(el.rect, el.img_bytes, el.ext)
    return ""


def _attr(name: str, value) -> str:
    """SVG 属性 1 個を ``name="value"`` の形で直列化する。

    **SVG 属性はこの関数経由でのみ書く**。f-string で属性を直接組む箇所を残すと、
    そこが次の注入点になる (色だけがエスケープ漏れしていた実績がそれ)。列挙ではなく
    構造で守るという反転で、漏れは「この関数を使っていない箇所」として機械検出できる
    (``test/test_export_escaping.py``)。

    出力バイトの不変則: ``quoteattr`` は ``"`` を含まない値へ ``"..."`` を付けるだけ
    なので、既存出力と 1 バイトも変わらない (``test/test_pipeline.py`` が固定)。
    """
    return f"{name}={quoteattr(str(value))}"


def _paint(attr: str, color) -> str:
    """塗り/線の色属性。**出口側の関門**で、入口 (``rpc_addBorder``) を迂回して
    モデルへ直接不正な色を入れられても、ここで ``ValueError`` になる。"""
    return _attr(attr, sanitize_color(color)) if color else _attr(attr, "none")


def _text_to_svg(el: TextElement) -> str:
    # 代替フォントでも崩れないよう和文補完 + 汎用名のフォールバックチェーンを付与
    family = fonts.fallback_css(el.font_family, el.text)
    weight = f" {_attr('font-weight', el.weight)}" if el.weight != 400 else ""
    style = ' font-style="italic"' if el.italic else ""
    # 元 PDF 上のグリフ箱の幅 (bbox.w) に収め、代替フォントの字幅差があっても元の
    # 水平位置 (中央/左/右の揃え) を維持する。置換で箱に収まるほど短くなった場合は
    # 後段の各枝が stretch を外す (引き伸ばしは超過の恐れがあるときだけ)。
    stretch = ""
    if el.bbox.w > 0:
        stretch = (
            f" {_attr('textLength', _fmt(el.bbox.w))}"
            f" {_attr('lengthAdjust', 'spacingAndGlyphs')}"
        )
    if el.text == el.original_text:
        # 未編集: 元 PDF のベースライン原点に置く (従来出力と完全一致)。
        x, y, base = el.origin_x, el.origin_y, ""
    elif el.wrap_align is not None:
        # 折返し畳み込み置換: 縦は下揃え (origin_y = 最終行のベースラインに据え直し済み)、
        # 横は元の折返し行の揃え (`wrap_align`) を text-anchor で踏襲する。全幅への
        # 引き伸ばしはせず、合成領域の幅を超える恐れがあるときだけ textLength で圧縮する。
        y, base = el.origin_y, ""
        if el.wrap_align == "center":
            x, base = el.bbox.x + el.bbox.w / 2, ' text-anchor="middle"'
        elif el.wrap_align == "right":
            x, base = el.bbox.x1, ' text-anchor="end"'
        else:
            x = el.bbox.x
        if not fonts.is_width_overflow(el.text, el.font_size, el.bbox.w):
            stretch = ""
    else:
        # 置換後 (単独行): 垂直は箱の縦中央へ `dominant-baseline="central"` で据える。
        # フォント置換でアセントが変わっても縦中央が保たれ、ベースライン据えで起きる
        # 「上詰まり」を防ぐ。水平は折返し枝と同じ超過判定で二分する — 元グリフ箱の幅を
        # 超える恐れがあるときだけ左端 + textLength で全幅圧縮し、収まる場合は textLength
        # を外して箱中央へ据える (spacingAndGlyphs はグリフ自体を水平拡大するため、短い
        # 置換語を元の広い幅へ引き伸ばすと「横太り」に見える。中央据えは元テキストの
        # 視覚中心を保ち、セルの真の揃えが不明でもずれを幅差の半分に抑える)。
        y = el.bbox.y + el.bbox.h / 2
        if fonts.is_width_overflow(el.text, el.font_size, el.bbox.w):
            x = el.bbox.x
            base = ' dominant-baseline="central"'
        else:
            stretch = ""
            x = el.bbox.x + el.bbox.w / 2
            base = ' dominant-baseline="central" text-anchor="middle"'
    return (
        "<text "
        + _attr("x", _fmt(x))
        + " "
        + _attr("y", _fmt(y))
        + f"{base} "
        + _attr("font-family", family)
        + " "
        + _attr("font-size", _fmt(el.font_size))
        + " "
        + _attr("fill", sanitize_color(el.color))
        + f"{weight}{style}{stretch}>"
        + escape(sanitize_text(el.text))
        + "</text>"
    )


def _image_tag(rect: Rect, data: bytes, ext: str) -> str:
    b64 = base64.b64encode(data).decode("ascii")
    href = f"data:{_mime(ext)};base64,{b64}"
    return (
        "<image "
        + _attr("x", _fmt(rect.x))
        + " "
        + _attr("y", _fmt(rect.y))
        + " "
        + _attr("width", _fmt(rect.w))
        + " "
        + _attr("height", _fmt(rect.h))
        + " "
        + _attr("xlink:href", href)
        + "/>"
    )
