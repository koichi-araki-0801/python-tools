"""色と画像をグレースケールへ変換する純粋関数。

ベクタ要素の色 (``to_gray_color``) と埋め込み画像 (``to_gray_image``) を**Pillow の
``convert("L")`` と同じ固定小数点式**（ITU-R 601-2）で灰色にする。文字・線と画像の
明度が完全に一致する。

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
    # Pillow の convert("L") と同じ固定小数点式 (ITU-R 601-2)。整数式 (R*299+G*587+B*114)//1000
    # では端数の丸めが Pillow と 1 だけずれる (例: #00ff00 は 149 vs 150) ので、画像と同じ式を使う。
    return (r * 19595 + g * 38470 + b * 7471 + 0x8000) >> 16


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


@functools.lru_cache(maxsize=16)
def to_gray_image(img_bytes: bytes, ext: str) -> Tuple[bytes, str]:
    """埋め込み画像を灰色 PNG にする。変換できないときは原本を返す (degrade)。

    画像バイトは PDF 由来 = 攻撃者が用意できる入力なので、デコードの前に画素数を
    ``MAX_GRAY_IMAGE_PIXELS`` で切る (``Image.open`` はヘッダしか読まないので寸法は
    デコード前に分かる)。壊れた画像・巨大画像は**原本をそのまま返し**、例外を外へ
    出さない — 1 枚の画像で書き出し全体を止めない。
    キャッシュはバイト列そのものをキーにする (プレビューと書き出しで同じ画像を何度も
    変換しないため)。
    """
    try:
        with Image.open(io.BytesIO(img_bytes)) as im:
            if im.width * im.height > MAX_GRAY_IMAGE_PIXELS:
                return img_bytes, ext
            has_alpha = im.mode in ("RGBA", "LA", "PA") or (
                im.mode == "P" and "transparency" in im.info
            )
            gray = im.convert("LA" if has_alpha else "L")
            out = io.BytesIO()
            gray.save(out, format="PNG")
            return out.getvalue(), "png"
    except Exception:  # noqa: BLE001 - 壊れた画像は原本へ倒す (上記 docstring)
        return img_bytes, ext
