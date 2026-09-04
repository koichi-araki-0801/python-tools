# pdf-to-svg/src/model/figure_detect.py
"""「当社のスチュワードシップ活動」の図を文字アンカーで見つける純粋関数。

運用報告書の当該図は号・ファンドごとに掲載ページも位置も違うが、見出しと図内ラベルの
文言は同じ。幾何の指紋 (曲線の本数など) に頼るとレイアウト変更で外れ、強調ボックスの
誤検出も多かったので、**文字で図を特定し、周りの図形へ広げる**方式にする。

- ``Page.live_elements()`` の bbox と文字列だけを見る (PyMuPDF 非依存。合成 ``Page`` で
  単体テストできる)。
- 1 ページにつき最大 1 矩形。見つからなければ ``None`` (UI は候補なし → 手動へ倒す)。
- 資源上限: 不動点ループは「取り込んだ要素は二度と候補にしない」ので、反復は要素数で
  上界される (必ず返る)。最悪計算量は図形数 n に対し O(n^2) (実測: 図形 6,000 件で
  約 1.6 秒。既存の資源上限 `MAX_PAGE_ELEMENTS` の件数まで外挿すると約 6.5 秒)。
  必ず終了するため、上限を超えて回り続けることはない。
"""
from __future__ import annotations

import unicodedata
from typing import List, Optional, Tuple

from model.document import Page
from model.elements import Element, ImageElement, LineElement, PathElement, Rect, RectElement, TextElement

# 見出し (NFKC 正規化 + 空白除去した文字列に含まれれば一致)
STEWARDSHIP_HEADING = "当社のスチュワードシップ活動"
# 図内ラベル。同じ語は直後の本文段落にも出るので、幅 (LABEL_MAX_WIDTH_RATIO) で本文を除外する。
STEWARDSHIP_LABELS: Tuple[str, ...] = (
    "投資リターンの最大化",
    "エンゲージメント",
    "議決権行使",
    "ESGの考慮",
    "フィデューシャリー",
    "stewardship_initiatives",
)
MIN_LABEL_HITS = 3            # これ未満なら「図が無い / 文言が変わった」と判断して None
FIGURE_EXPAND_TOL = 16.0      # 近傍として取り込む距離 (pt)
LABEL_MAX_WIDTH_RATIO = 0.5   # ラベルとみなす文字要素の最大幅 (ページ幅比)。本文段落は 0.8 超
BACKGROUND_AREA_RATIO = 0.5   # これ以上の面積の図形はページ背景とみなして取り込まない
BAND_WIDTH_RATIO = 0.9        # これ以上の幅の図形はヘッダ帯・区切り罫とみなして取り込まない

_SHAPE_TYPES = (RectElement, PathElement, LineElement, ImageElement)


def normalize_label_text(s: str) -> str:
    """NFKC 正規化して空白を全部落とす (全角・半角・改行の揺れを吸収)。"""
    return "".join(unicodedata.normalize("NFKC", s).split())


def _union(a: Rect, b: Rect) -> Rect:
    return Rect.from_xyxy(min(a.x, b.x), min(a.y, b.y), max(a.x1, b.x1), max(a.y1, b.y1))


def _grow(r: Rect, tol: float) -> Rect:
    return Rect(r.x - tol, r.y - tol, r.w + 2 * tol, r.h + 2 * tol)


def _overlaps(a: Rect, b: Rect) -> bool:
    """辺が触れるだけでも真 (``Rect.intersects`` は開区間なので高さ 0 の罫線を拾えない)。"""
    return not (a.x1 < b.x or b.x1 < a.x or a.y1 < b.y or b.y1 < a.y)


def _contains(outer: Rect, inner: Rect) -> bool:
    return outer.x <= inner.x and outer.y <= inner.y and inner.x1 <= outer.x1 and inner.y1 <= outer.y1


def detect_stewardship_figure(page: Page) -> Optional[Rect]:
    """図の矩形 (ページ座標 pt) を返す。見つからなければ None。"""
    width, height = page.width_pt, page.height_pt
    page_area = width * height
    elements: List[Element] = page.live_elements()
    texts = [(normalize_label_text(e.text), e) for e in elements if isinstance(e, TextElement)]

    heads = [e for t, e in texts if STEWARDSHIP_HEADING in t]
    if not heads:
        return None
    head_y = min(e.bbox.y for e in heads)

    max_label_w = width * LABEL_MAX_WIDTH_RATIO
    labels = [
        e for t, e in texts
        if e.bbox.y > head_y and e.bbox.w < max_label_w and any(k in t for k in STEWARDSHIP_LABELS)
    ]
    if len(labels) < MIN_LABEL_HITS:
        return None

    box = labels[0].bbox
    for e in labels[1:]:
        box = _union(box, e.bbox)

    # 近傍の図形・画像を不動点まで取り込む (背景と帯は除外)。
    # 最悪計算量は図形数の 2 乗 (外側 while が最大 n 周・内側 for が毎周 pending を全走査)。
    # 実測: 図形 6,000 件で約 1.6 秒、`MAX_PAGE_ELEMENTS` まで外挿しても約 6.5 秒で
    # 必ず終了する (docstring 参照)。
    pending = [
        e for e in elements
        if isinstance(e, _SHAPE_TYPES)
        and e.bbox.w * e.bbox.h < page_area * BACKGROUND_AREA_RATIO
        and e.bbox.w < width * BAND_WIDTH_RATIO
    ]
    grew = True
    while grew and pending:
        grew = False
        probe = _grow(box, FIGURE_EXPAND_TOL)
        rest = []
        for e in pending:
            if _overlaps(e.bbox, probe):
                if not _contains(box, e.bbox):
                    box = _union(box, e.bbox)
                    grew = True
            else:
                rest.append(e)
        pending = rest  # 取り込んだ要素は二度と見ない → 反復は要素数で上界

    # 領域に掛かる短い文字行 (ラベルの説明文) を取り込む
    for _t, e in texts:
        if e.bbox.w < max_label_w and _overlaps(e.bbox, box) and not _contains(box, e.bbox):
            box = _union(box, e.bbox)
    return box
