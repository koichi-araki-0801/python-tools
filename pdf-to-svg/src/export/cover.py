"""上書き矩形の採色。画像の画素から「背景色」と「文字色」を決める純粋関数。

スキャン画像の上に OCR 文字を透明で重ねた PDF では、辞書置換しても元の字面が画像の画素として
残る。置換箇所を隠す矩形の色を画像から採り、白抜き文字の帯でも読めるよう文字色も同じ領域から
採る。``fitz`` には依存しない (AGPL 依存は ``engine/pdf_engine.py`` に隔離する)。

採り方: bbox 内の画素を各チャンネル 16 階調 (``QUANT_SHIFT``) に量子化し、最も多い箱を背景・
2 番目を文字色にする。代表色は箱に入った画素の平均 (箱の中心値だと白い紙が ``#f8f8f8`` になる)。
2 番目が無い、または背景との差が ``MIN_CONTRAST`` 未満なら、背景の輝度で黒か白へ倒す。
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image, ImageChops, ImageStat

from model.elements import Rect

# 画像 1 枚あたりのデコード上限画素数。`grayscale.MAX_GRAY_IMAGE_PIXELS` と同値 (片方を変えたら両方)。
MAX_COVER_IMAGE_PIXELS = 16_000_000
# 量子化の右シフト量。4 = 各チャンネル 16 階調 (JPEG ノイズで最頻色が割れるのを防ぐ)。
QUANT_SHIFT = 4
# 文字色と背景色のチャンネル差の最大がこれ未満なら、文字色を黒/白へ倒す。
MIN_CONTRAST = 48
FALLBACK_BACKGROUND = "#ffffff"
FALLBACK_FOREGROUND = "#000000"

_QUANT_TABLE = [v >> QUANT_SHIFT for v in range(256)] * 3


@dataclass(frozen=True)
class CoverColors:
    """採色結果。``fallback`` は画像から採れず既定の白/黒へ倒したことを示す。"""

    background: str
    foreground: str
    fallback: bool


_FALLBACK = CoverColors(FALLBACK_BACKGROUND, FALLBACK_FOREGROUND, True)


def decode_image(img_bytes: bytes, ext: str) -> Optional[Image.Image]:
    """画像バイト列を RGB の Pillow 画像へ。上限超過・壊れたバイト列は ``None``。

    画像は PDF 由来 = 攻撃者が用意できる入力なので、デコードの前に画素数を
    ``MAX_COVER_IMAGE_PIXELS`` で切る (``Image.open`` はヘッダしか読まない)。例外は外へ出さない
    (1 枚の画像で書き出し全体を止めない)。
    """
    del ext  # 形式は Pillow がヘッダから判定する
    try:
        with Image.open(io.BytesIO(img_bytes)) as im:
            if im.width * im.height > MAX_COVER_IMAGE_PIXELS:
                return None
            return im.convert("RGB")
    except Exception:  # noqa: BLE001 - 壊れた画像は採色を諦めるだけ
        return None


def _luma(r: int, g: int, b: int) -> int:
    # `grayscale._luma` と同じ固定小数点式 (ITU-R 601-2)。
    return (r * 19595 + g * 38470 + b * 7471 + 0x8000) >> 16


def _hex(rgb: Tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def _pixel_box(
    img_rect: Rect, bbox: Rect, width: int, height: int
) -> Optional[Tuple[int, int, int, int]]:
    """pt の bbox を画像画素の (x0, y0, x1, y1) へ線形写像し、画像の範囲でクランプする。空なら None。

    `img_rect` / `bbox` は PDF 由来 (攻撃者が細工できる) の座標なので、非有限値
    (inf/nan) を先に弾く。素通しすると `sx`/`sy` が inf・nan になり、後段の
    `math.floor`/`math.ceil` から `int()` への変換が `OverflowError`/`ValueError` を
    投げて `page_to_svg` 全体を止める (`pdf_engine._band_range` と同じ判断)。
    """
    if not all(math.isfinite(v) for v in (img_rect.x, img_rect.y, img_rect.w, img_rect.h)):
        return None
    if not all(math.isfinite(v) for v in (bbox.x, bbox.y, bbox.w, bbox.h)):
        return None
    if img_rect.w <= 0 or img_rect.h <= 0:
        return None
    sx = width / img_rect.w
    sy = height / img_rect.h
    x0 = int(math.floor((bbox.x - img_rect.x) * sx))
    y0 = int(math.floor((bbox.y - img_rect.y) * sy))
    x1 = int(math.ceil((bbox.x1 - img_rect.x) * sx))
    y1 = int(math.ceil((bbox.y1 - img_rect.y) * sy))
    x0, x1 = max(0, min(x0, width)), max(0, min(x1, width))
    y0, y1 = max(0, min(y0, height)), max(0, min(y1, height))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _box_mean(
    region: Image.Image, quantized: Image.Image, box: Tuple[int, int, int]
) -> Tuple[int, int, int]:
    """量子化値が ``box`` に一致する画素の平均色 (整数へ丸め)。マスクは Pillow の C 実装で作る。"""
    solid = Image.new("RGB", quantized.size, box)
    diff_bands = ImageChops.difference(quantized, solid).split()
    bands = [b.point(lambda v: 255 if v == 0 else 0) for b in diff_bands]
    mask = ImageChops.multiply(ImageChops.multiply(bands[0], bands[1]), bands[2])
    mean = ImageStat.Stat(region, mask).mean
    return tuple(int(round(m)) for m in mean)  # type: ignore[return-value]


def sample_colors(img: Optional[Image.Image], img_rect: Rect, bbox: Rect) -> CoverColors:
    """``img`` (``img_rect`` へ貼られた画像) の ``bbox`` 内から背景色と文字色を採る。

    採れない (画像無し・bbox が画像の外) ときは白/黒の ``fallback=True``。文字色が決まらない
    ときの黒/白への倒しは背景が採れているので ``fallback=False``。
    """
    if img is None:
        return _FALLBACK
    px = _pixel_box(img_rect, bbox, img.width, img.height)
    if px is None:
        return _FALLBACK
    region = img.crop(px)
    quantized = region.point(_QUANT_TABLE)
    max_colors = 1 << (3 * (8 - QUANT_SHIFT))
    colors: List[Tuple[int, Tuple[int, int, int]]] = quantized.getcolors(max_colors) or []
    if not colors:
        return _FALLBACK
    # 同数は量子化値の小さい方を先にする (走査順に依存せず決定的)。
    ranked = sorted(colors, key=lambda kv: (-kv[0], kv[1]))
    bg = _box_mean(region, quantized, ranked[0][1])
    fg: Optional[Tuple[int, int, int]] = None
    if len(ranked) > 1:
        fg = _box_mean(region, quantized, ranked[1][1])
        if max(abs(a - b) for a, b in zip(bg, fg)) < MIN_CONTRAST:
            fg = None
    if fg is None:
        fg = (0, 0, 0) if _luma(*bg) >= 128 else (255, 255, 255)
    return CoverColors(_hex(bg), _hex(fg), False)
