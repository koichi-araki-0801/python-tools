"""ページが「ベクター」か「スキャン(画像主体)」かを判定する。

判定根拠:
- 抽出できるテキスト量がごく僅か、かつ
- ページ面積の大半を画像が覆っている
場合にスキャンとみなす。どちらか弱い場合はベクター扱い (テキスト編集を優先)。
"""
from __future__ import annotations

import fitz  # PyMuPDF

# ── しきい値 ──
MIN_TEXT_CHARS = 10          # これ未満の文字数ならテキストはほぼ無いとみなす
IMAGE_COVERAGE_RATIO = 0.5   # 画像がページ面積のこれ以上を覆えば画像主体


# ── 判定本体 ──
def is_scanned_page(page: "fitz.Page") -> bool:
    """`page` がスキャン (画像主体) なら True。テキスト量と画像被覆率の両方で判定する。"""
    text = page.get_text("text").strip()
    if len(text) >= MIN_TEXT_CHARS:
        return False

    page_area = abs(page.rect.width * page.rect.height)
    if page_area <= 0:
        return False

    image_area = 0.0
    for info in page.get_image_info():
        bbox = info.get("bbox")
        if bbox:
            r = fitz.Rect(bbox)
            image_area += abs(r.width * r.height)

    coverage = image_area / page_area
    return coverage >= IMAGE_COVERAGE_RATIO
