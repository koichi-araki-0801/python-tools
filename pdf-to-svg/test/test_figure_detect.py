# pdf-to-svg/test/test_figure_detect.py
"""スチュワードシップ図の文字アンカー検出 (``model/figure_detect.py``)。

幾何の指紋ではなく、見出し「当社のスチュワードシップ活動」と図内ラベルの文言で
領域を決める。図のレイアウトが変わっても文言が残れば追従し、文言が無ければ
検出しない (誤検出で強調ボックスを拾うより、候補なし → 手動へ倒すほうが安全)。
"""
from __future__ import annotations

from model.document import Page
from model.elements import ImageElement, LineElement, PathElement, Rect, RectElement, TextElement
from model.figure_detect import (
    MIN_LABEL_HITS,
    STEWARDSHIP_LABELS,
    detect_stewardship_figure,
    normalize_label_text,
)


def _text(x, y, w, h, s, **kw) -> TextElement:
    return TextElement(bbox=Rect(x, y, w, h), text=s, origin_x=x, origin_y=y + h, **kw)


def make_stewardship_page() -> Page:
    """実 PDF (595x842, 図は 85,249-483,650 付近) を模した合成ページ。"""
    pg = Page(index=0, width_pt=600, height_pt=800)
    els = [
        RectElement(bbox=Rect(0, 0, 600, 800), rect=Rect(0, 0, 600, 800), fill="#fdf3ee", stroke=None),   # ページ背景 (面積 100%)
        RectElement(bbox=Rect(0, 0, 600, 40), rect=Rect(0, 0, 600, 40), fill="#7a868d", stroke=None),      # ヘッダ帯 (幅 100%)
        _text(40, 140, 180, 14, "（3）当社のスチュワードシップ活動"),
        _text(40, 160, 510, 14, "当社は「責任ある機関投資家」として、エンゲージメント、議決権行使、投資の意思決定におけるESGの考慮を"),
        _text(40, 176, 510, 14, "3つの柱としてスチュワードシップ活動を推進しています。投資リターンの最大化を目指します。"),
        RectElement(bbox=Rect(113, 249, 370, 35), rect=Rect(113, 249, 370, 35), fill="#009eb4", stroke=None),
        _text(224, 265, 150, 16, "投資リターンの最大化", color="#ffffff"),
        PathElement(bbox=Rect(207, 320, 196, 174), d="M207 320 C 300 300 330 480 403 494", stroke="#c0392b"),
        _text(104, 356, 57, 12, "におけるESGの考慮"),
        _text(430, 344, 48, 12, "議決権行使"),
        _text(85, 468, 72, 12, "エンゲージメント"),
        RectElement(bbox=Rect(113, 526, 370, 70), rect=Rect(113, 526, 370, 70), fill="#009eb4", stroke=None),
        _text(162, 564, 191, 12, "［フィデューシャリー・デューティーの実践］", color="#ffffff"),
        RectElement(bbox=Rect(113, 600, 370, 50), rect=Rect(113, 600, 370, 50), fill=None, stroke="#000000"),
        ImageElement(bbox=Rect(120, 605, 40, 40), rect=Rect(120, 605, 40, 40), img_bytes=b"\x89PNG", ext="png"),
        _text(190, 640, 270, 10, "https://www.smtam.jp/institutional/stewardship_initiatives/"),
        LineElement(bbox=Rect(40, 790, 520, 0), x0=40, y0=790, x1=560, y1=790, color="#000000"),
        _text(40, 700, 160, 14, "（4）自社ESGスコアについて"),
    ]
    for i, el in enumerate(els):
        el.z = i
    pg.elements = els
    return pg


def test_normalize_folds_width_and_spaces():
    assert normalize_label_text("Ｅ Ｓ Ｇ の 考慮") == "ESGの考慮"
    assert normalize_label_text("＜当社の\nスチュワードシップ活動＞") == "<当社のスチュワードシップ活動>"


def test_detects_figure_bounded_by_labels_shapes_and_frame():
    r = detect_stewardship_figure(make_stewardship_page())
    assert r is not None
    assert (r.x, r.y, r.x1, r.y1) == (85, 249, 483, 650)


def test_background_and_header_band_are_not_absorbed():
    r = detect_stewardship_figure(make_stewardship_page())
    assert r.y > 40 and r.x > 0 and r.y1 < 790


def test_heading_only_returns_none():
    pg = Page(index=0, width_pt=600, height_pt=800)
    pg.elements = [_text(40, 140, 180, 14, "当社のスチュワードシップ活動")]
    assert detect_stewardship_figure(pg) is None


def test_fewer_than_min_labels_returns_none():
    pg = Page(index=0, width_pt=600, height_pt=800)
    pg.elements = [
        _text(40, 140, 180, 14, "当社のスチュワードシップ活動"),
        _text(100, 300, 100, 12, "エンゲージメント"),
        _text(100, 320, 100, 12, "議決権行使"),
    ]
    assert MIN_LABEL_HITS == 3
    assert detect_stewardship_figure(pg) is None


def test_wide_body_paragraph_does_not_count_as_label():
    pg = Page(index=0, width_pt=600, height_pt=800)
    pg.elements = [
        _text(40, 140, 180, 14, "当社のスチュワードシップ活動"),
        _text(40, 160, 510, 14, "エンゲージメント、議決権行使、ESGの考慮、投資リターンの最大化、フィデューシャリー"),
    ]
    assert detect_stewardship_figure(pg) is None


def test_labels_above_heading_are_ignored():
    pg = make_stewardship_page()
    # 見出しより上に同じ語が並んでいても数えない (前ページの続きなど)
    pg.elements.append(_text(100, 60, 100, 12, "議決権行使"))
    r = detect_stewardship_figure(pg)
    assert r.y == 249


def test_deleted_elements_are_ignored():
    pg = make_stewardship_page()
    for el in pg.elements:
        if isinstance(el, TextElement) and any(k in normalize_label_text(el.text) for k in STEWARDSHIP_LABELS):
            el.deleted = True
    assert detect_stewardship_figure(pg) is None


def test_expansion_terminates_on_long_chains():
    pg = make_stewardship_page()
    # 図の右端から 10pt 刻みで小矩形を 300 個つなぐ → 全部吸収して必ず返る
    x = 483 + 10
    for i in range(300):
        r = Rect(x, 400, 5, 5)
        pg.elements.append(RectElement(bbox=r, rect=r, fill="#123456", stroke=None, z=1000 + i))
        x += 10
    out = detect_stewardship_figure(pg)
    assert out is not None and out.x1 == x - 10 + 5
