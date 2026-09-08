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

from PIL import Image, ImageChops, ImageColor

from model.elements import sanitize_color

_HEX = re.compile(r"^#([0-9a-fA-F]{3,8})$")

# 画像 1 枚あたりの変換上限画素数。`engine/pdf_engine.py` の `MAX_RASTER_PIXELS` と同値だが、
# あちらは fitz を import するモジュールなので値を複製する (片方を変えたら両方)。
MAX_GRAY_IMAGE_PIXELS = 16_000_000

# 三井住友トラスト・アセットマネジメントの運用報告書は、同じ「当社のスチュワードシップ活動」の
# 図をカラー版とモノクロ版の 2 通りで配布している。モノクロ版はデザイナによる階調の再割当で、
# 輝度変換では再現できない (赤 #f15b66 の輝度は 137 相当だが、モノクロ版では最も濃い #231f20 が
# 割り当てられ、明暗が逆転する)。カラー版 (_id_140823 / _id_140812 / _id_700001) とモノクロ版
# (_id_142871 / _id_510183 / _id_510186) は図形 568 個の座標が一致するため、その対応をそのまま
# 表にしてある。3 本のカラー版に出る有彩色はこの 7 色ですべてで、残りは黒・白・薄灰 (無彩色) の
# ため輝度変換で足りる。表に無い色は従来どおり Rec.601 の輝度変換へ落ちる。
SMTAM_MONO_COLORS = {
    "#009eb4": "#939598",
    "#3e8d60": "#939598",
    "#f15b66": "#231f20",
    "#09b26a": "#4d4d4f",
    "#faa619": "#6d6e71",
    "#b75669": "#808285",
    "#bc9632": "#a7a9ac",
}


# 埋め込み画像 (螺旋・矢印) は公式モノクロ版が別アセットのため ``SMTAM_MONO_COLORS`` のような
# 対応表を作れない。カラー版を輝度変換した画素とモノクロ版の画素を突き合わせた回帰では、
# ガンマ 0.8 が平均絶対誤差を 24.1 から 10.9 へ半減させた (線形当てはめ・単純ゲインより良い)。
IMAGE_TONE_GAMMA = 0.8

# チャンネル間の最大差がこれ以下なら無彩色とみなし、色は動かさず画像にもトーン補正を掛けない。
# 既にモノクロで配布されている報告書へ補正を掛けると、公式版より明るくなってかえってずれる。
# 6 なのは、公式モノクロ版のパレットが厳密な灰色ではないため (#808285 / #939598 / #a7a9ac の
# R-B 差が 5、黒に使う #231f20 が 4)。これらを輝度変換に通すと通しただけで色が変わる。
CHROMA_TOLERANCE = 6


def tone_curve(y: int) -> int:
    """輝度 ``y`` (0-255) を ``IMAGE_TONE_GAMMA`` で持ち上げる。両端 (0 / 255) は動かない。"""
    return round(255 * (y / 255.0) ** IMAGE_TONE_GAMMA)


def _is_chromatic(im: "Image.Image") -> bool:
    """画像が色を持つか (グレースケールモード、および全画素が灰色の RGB は False)。"""
    if im.mode in ("L", "LA", "1", "I", "F", "I;16"):
        return False
    r, g, b = im.convert("RGB").split()
    return (
        ImageChops.difference(r, g).getextrema()[1] > CHROMA_TOLERANCE
        or ImageChops.difference(g, b).getextrema()[1] > CHROMA_TOLERANCE
    )


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
        mono = SMTAM_MONO_COLORS.get("#%02x%02x%02x" % (r, g, b))
        if mono is not None:
            return f"{mono}{alpha}"
    else:
        try:
            r, g, b = ImageColor.getrgb(v.lower())[:3]
        except ValueError:
            return v
        alpha = ""
    if max(r, g, b) - min(r, g, b) <= CHROMA_TOLERANCE:
        # 既に灰色なら動かさない。輝度変換を通すと、同社が黒に使う #231f20 (R-B 差 4) が
        # #202020 へ寄ってしまい、モノクロ版の報告書を通しただけで色が変わる。
        return f"#{r:02x}{g:02x}{b:02x}{alpha}"
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
            if _is_chromatic(im):
                lut = [tone_curve(i) for i in range(256)]
                if gray.mode == "LA":
                    lum, alpha = gray.split()
                    gray = Image.merge("LA", (lum.point(lut), alpha))
                else:
                    gray = gray.point(lut)
            out = io.BytesIO()
            gray.save(out, format="PNG")
            return out.getvalue(), "png"
    except Exception:  # noqa: BLE001 - 壊れた画像は原本へ倒す (上記 docstring)
        return img_bytes, ext
