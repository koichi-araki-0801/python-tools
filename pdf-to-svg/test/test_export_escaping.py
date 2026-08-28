"""SVG 出力の属性エスケープと色の許可リストの退行ガード。

``PathElement.d`` は ``quoteattr``、テキストは ``escape`` を通っているのに**色だけ**が
素の f-string、という 1 箇所の取りこぼしがあると、``rpc_addBorder`` の ``color`` へ
``#000"/><script>alert(1)</script><rect stroke="#000`` を渡す注入が成立する。
書き出した SVG は社内回覧される成果物なので、守るべきは表示面ではなく生成点である。

「迂回入力で失敗すること」を主張する形で書く。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from export.svg_exporter import _mime, page_to_svg
from model.document import Page
from model.elements import (
    LineElement,
    Rect,
    RectElement,
    TextElement,
    sanitize_color,
)

# 属性を閉じて要素を差し込む形。
BREAKOUT = '#000"/><script>alert(document.domain)</script><rect stroke="#000'


def _page(*elements) -> Page:
    pg = Page(index=0, width_pt=300, height_pt=200)
    for i, el in enumerate(elements):
        el.z = i
        pg.elements.append(el)
    return pg


def test_sanitize_color_accepts_only_the_allowlist():
    for ok in ("#fff", "#ffff", "#112233", "#11223344", "rebeccapurple", "none", "currentColor"):
        assert sanitize_color(ok) == ok
    assert sanitize_color(None) is None
    # rgb()/hsl() は CSS 経路で宣言を増やせ、url() は外部参照と javascript: の入口。
    for bad in (BREAKOUT, "rgb(0,0,0)", "hsl(0,0%,0%)", "url(#x)", "javascript:alert(1)", 1):
        with pytest.raises(ValueError):
            sanitize_color(bad)


def test_rect_stroke_breakout_is_rejected_at_the_exporter():
    """入口 (rpc) を迂回してモデルへ直接入れても、出口の ``_paint`` が止める。"""
    rect = Rect(x=10, y=10, w=50, h=20)
    pg = _page(RectElement(bbox=rect, z=0, rect=rect, stroke=BREAKOUT, fill=None, stroke_width=1))
    with pytest.raises(ValueError):
        page_to_svg(pg)


def test_line_and_text_colors_are_guarded_too():
    line = LineElement(
        bbox=Rect(x=0, y=0, w=10, h=1), z=0, x0=0, y0=0, x1=10, y1=0, color=BREAKOUT, width=1
    )
    with pytest.raises(ValueError):
        page_to_svg(_page(line))

    text = TextElement(
        bbox=Rect(x=0, y=0, w=40, h=10),
        z=0,
        text="x",
        font_family="Helvetica",
        font_size=10,
        color=BREAKOUT,
    )
    with pytest.raises(ValueError):
        page_to_svg(_page(text))


def test_text_content_is_escaped_not_dropped():
    """テキストは注入されないが、消えてもいけない (欠測との取り違えを防ぐ)。"""
    text = TextElement(
        bbox=Rect(x=0, y=0, w=40, h=10),
        z=0,
        text='a"><script>alert(1)</script>',
        font_family="Helvetica",
        font_size=10,
        color="#000000",
    )
    svg = page_to_svg(_page(text))
    assert "<script" not in svg
    assert "&lt;script&gt;" in svg


def test_mime_unknown_ext_falls_to_octet_stream():
    """未知拡張子は PDF 由来の ext をそのまま MIME に仕立てず `application/octet-stream` へ倒す。

    既知拡張子の出力は不変であること (`test_pipeline.py` が退行網) と対で、固定表の外は
    fail-close することをここで固定する。
    """
    assert _mime("svg+xml") == "application/octet-stream"
    assert _mime("html") == "application/octet-stream"
    assert _mime("png") == "image/png"
    assert _mime("JPG") == "image/jpeg"


def test_no_attribute_is_built_with_a_raw_f_string():
    """構造で守っていることの機械検証。

    列挙 (「この属性もエスケープする」) は必ず漏れる。属性を書く手段を ``_attr``/``quoteattr``
    経由に絞ったので、漏れは「f-string 等で ``name="{...}"`` と生の値を差し込んでいる箇所」
    として検出できる。``src/export/`` 配下を**ファイル名のハードコード列挙をせず glob で
    全 .py 走査**する: 新しいファイルを足しても検査対象から漏れない。走査は
    ``**/*.py`` の再帰で行う — 直下だけを見る ``*.py`` では、出力の組み立てを
    サブパッケージへ切り出した瞬間に検査から外れる (「ファイル名を列挙しない」ことの
    目的は、置き場所を変えても網から出られないことにある)。

    検出正規表現の限界: 構文的な f-string 解析ではなく文字列パターンの走査であり、
    ``.format()`` や ``%`` 演算子での同種の組み立て、複数行にまたがる f-string、
    値を変数へ一旦代入してから ``+`` 連結する迂回形は捕捉しない。あくまで
    「``="`` の直後に式展開が来る」よくある形の退行検知に限る。
    """
    export_dir = Path(__file__).resolve().parents[1] / "src" / "export"
    pattern = re.compile(r'=\\?"\{[^}]*\}')
    # 行の完全一致 (strip 後) でだけ除外する既知の正当箇所。今のところ無い
    # (``_attr`` 自身の定義は ``={quoteattr(...)}`` の形でこの正規表現に掛からない)。
    ALLOWED_LINES: set[str] = set()

    scanned = [p for p in sorted(export_dir.glob("**/*.py")) if "__pycache__" not in p.parts]
    # 0 件走査で「常に緑」になるのを防ぐ(パス変更・パッケージ移動の検知)。
    assert len(scanned) >= 3, f"走査対象が見つからない: {export_dir}"

    offenders = []
    for path in scanned:
        rel = path.relative_to(export_dir).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if line.strip() in ALLOWED_LINES:
                continue
            if pattern.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert offenders == [], f"f-string で属性を組んでいる箇所が残っている: {offenders}"
