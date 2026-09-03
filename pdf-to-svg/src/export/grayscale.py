"""色と画像をグレースケールへ変換する純粋関数。

ベクタ要素の色 (``to_gray_color``) と埋め込み画像 (``to_gray_image``) を**同じ
Rec.601 の整数式** ``(R*299 + G*587 + B*114) // 1000`` で灰色にする (Pillow の
``convert("L")`` と同じ係数なので、文字・線と画像の明度が揃う)。

SVG フィルタ (``feColorMatrix``) を使わないのは意図的で、Office はフィルタを無視して
カラーのまま貼り付き、ブラウザの印刷はフィルタ領域を丸ごとラスタ化して文字を画像に
してしまう。色そのものを書き換えれば、どの消費側でも灰色のまま・文字は文字のままになる。

``fitz`` (PyMuPDF) には依存しない — AGPL 依存は ``engine/pdf_engine.py`` に隔離する。
"""
from __future__ import annotations

import functools
import io
import re
from typing import Optional, Tuple

from PIL import Image, ImageColor

from model.elements import sanitize_color

_HEX = re.compile(r"^#([0-9a-fA-F]{3,8})$")

# 画像 1 枚あたりの変換上限画素数。`engine/pdf_engine.py` の `MAX_RASTER_PIXELS` と同値だが、
# あちらは fitz を import するモジュールなので値を複製する (片方を変えたら両方)。
MAX_GRAY_IMAGE_PIXELS = 16_000_000


def _luma(r: int, g: int, b: int) -> int:
    return (r * 299 + g * 587 + b * 114) // 1000


def to_gray_color(value: Optional[str]) -> Optional[str]:
    """``sanitize_color`` が許す色を灰色 hex にする。``none`` / ``currentColor`` / ``None`` は素通し。

    許可形以外は ``sanitize_color`` と同じく ``ValueError`` (出口の関門をここで緩めない)。
    Pillow が知らない CSS 色名は変換せずそのまま返す (色は残るが、例外で書き出しを止めない)。
    """
    v = sanitize_color(value)
    if v is None or v in ("none", "currentColor"):
        return v
    m = _HEX.match(v)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        alpha = h[6:8].lower()
    else:
        try:
            r, g, b = ImageColor.getrgb(v.lower())[:3]
        except ValueError:
            return v
        alpha = ""
    y = _luma(r, g, b)
    return f"#{y:02x}{y:02x}{y:02x}{alpha}"


def to_gray_image(image: Image.Image) -> Image.Image:
    """埋め込み画像を Rec.601 でグレースケール化する。"""
    # TODO: Implement in Task 2
    raise NotImplementedError("to_gray_image will be implemented in Task 2")
