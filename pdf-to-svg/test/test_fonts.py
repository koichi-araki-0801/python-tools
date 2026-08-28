"""フォント名マッピング (model.fonts) のユニットテスト。Qt 不要。"""
from model import fonts
from model.fonts import MappedFont, estimate_text_width, is_width_overflow, map_font


def test_estimate_text_width_wide_and_narrow():
    # 全角は font_size、半角は font_size*0.5 で合算
    assert estimate_text_width("品番", 12.0) == 24.0
    assert estimate_text_width("AB", 12.0) == 12.0
    assert estimate_text_width("A品", 10.0) == 15.0  # 5 + 10


def test_is_width_overflow_boundary():
    # 推定 24pt。許容 1.05 倍まで OK
    assert is_width_overflow("品番", 12.0, 20.0) is True    # 24 > 21
    assert is_width_overflow("品番", 12.0, 40.0) is False   # 24 <= 42
    assert is_width_overflow("品番", 12.0, 0.0) is False     # 箱幅不明は警告しない


def test_standard14_mapping():
    assert map_font("Times-Roman") == MappedFont("Times New Roman")
    assert map_font("Times-Bold") == MappedFont("Times New Roman", weight=700)
    assert map_font("Times-BoldItalic") == MappedFont("Times New Roman", weight=700, italic=True)
    assert map_font("Helvetica") == MappedFont("Arial")
    assert map_font("Helvetica-BoldOblique") == MappedFont("Arial", weight=700, italic=True)
    assert map_font("Courier") == MappedFont("Courier New")
    assert map_font("Courier-Oblique") == MappedFont("Courier New", italic=True)
    assert map_font("Symbol") == MappedFont("Segoe UI Symbol")


def test_common_aliases():
    assert map_font("ArialMT") == MappedFont("Arial")
    assert map_font("Arial-BoldMT") == MappedFont("Arial", weight=700)
    assert map_font("TimesNewRomanPSMT") == MappedFont("Times New Roman")
    assert map_font("TimesNewRomanPS-BoldItalicMT") == MappedFont(
        "Times New Roman", weight=700, italic=True
    )
    assert map_font("CourierNewPS-ItalicMT") == MappedFont("Courier New", italic=True)
    assert map_font("MS-PMincho") == MappedFont("MS PMincho")
    assert map_font("MS-Gothic") == MappedFont("MS Gothic")
    assert map_font("YuGothic-Bold") == MappedFont("Yu Gothic", weight=700)
    assert map_font("Meiryo") == MappedFont("Meiryo")


def test_paid_font_substitution():
    """有料フォントは同梱フォント (ゴシック=BIZ UD / 明朝=Noto Serif JP) へ置き換わる。"""
    assert map_font("HiraKakuProN-W6") == MappedFont("BIZ UDPGothic", weight=600)
    assert map_font("HiraMinProN-W3") == MappedFont("Noto Serif JP", weight=300)
    assert map_font("KozMinPr6N-Regular") == MappedFont("Noto Serif JP")
    assert map_font("KozGoPr6N-Bold") == MappedFont("BIZ UDPGothic", weight=700)
    assert map_font("NotoSansJP-Medium") == MappedFont("BIZ UDPGothic", weight=500)
    assert map_font("NotoSerifJP-Black") == MappedFont("Noto Serif JP", weight=900)
    assert map_font("IPAexMincho") == MappedFont("Noto Serif JP")


def test_morisawa_ud_fonts():
    """モリサワ UD 系 (交付運用報告書等で頻出) は明朝/ゴシックとウェイトを正しく判別する。"""
    assert map_font("UDReiminPr6N-Light", "あ") == MappedFont("Noto Serif JP", weight=300)
    assert map_font("UDReiminPr6N-Regular", "あ") == MappedFont("Noto Serif JP", weight=400)
    assert map_font("UDShinGoNTPr6N-Reg", "あ") == MappedFont("BIZ UDPGothic", weight=400)
    assert map_font("UDShinGoNTPr6N-Light", "あ") == MappedFont("BIZ UDPGothic", weight=300)
    assert map_font("UDShinGoNTPr6N-Medium", "あ") == MappedFont("BIZ UDPGothic", weight=500)
    assert map_font("UDShinGoNTPr6N-DeBold", "あ") == MappedFont("BIZ UDPGothic", weight=600)
    assert map_font("RyuminPro-Regular", "あ") == MappedFont("Noto Serif JP", weight=400)
    assert map_font("ShinGoPro-DB", "あ") == MappedFont("BIZ UDPGothic", weight=600)


def test_unmatched_heuristics():
    assert map_font("SomeMincho").family == "Noto Serif JP"
    assert map_font("FooMono").family == "Courier New"
    # 未知名 + 和文テキスト → 和文ゴシック
    assert map_font("UnknownFont", "請求書").family == "BIZ UDPGothic"
    # 未知名 + 欧文テキスト → 欧文 sans
    assert map_font("UnknownFont", "Invoice 123").family == "Arial"
    # 未知 serif 系 + 和文テキスト → 和文明朝
    assert map_font("FancySerif", "請求書").family == "Noto Serif JP"
    # スタイルトークンは未知名でも拾う
    m = map_font("UnknownFont-Bold", "abc")
    assert m.family == "Arial" and m.weight == 700


def test_contains_japanese():
    assert fonts.contains_japanese("ひらがな")
    assert fonts.contains_japanese("カタカナ")
    assert fonts.contains_japanese("漢字")
    assert fonts.contains_japanese("ﾊﾝｶｸ")
    assert fonts.contains_japanese("Ａ１")  # 全角英数
    assert not fonts.contains_japanese("ASCII text 123")


def test_fallback_chain():
    assert fonts.fallback_chain("Times New Roman", "Report") == ["Times New Roman", "serif"]
    assert fonts.fallback_chain("Times New Roman", "売上 Report") == [
        "Times New Roman", "Noto Serif JP", "serif",
    ]
    assert fonts.fallback_chain("Arial", "売上") == ["Arial", "BIZ UDPGothic", "sans-serif"]
    # 先頭が和文フォントなら重複挿入しない
    assert fonts.fallback_chain("BIZ UDPGothic", "売上") == ["BIZ UDPGothic", "sans-serif"]
    assert fonts.fallback_chain("Yu Mincho", "売上") == ["Yu Mincho", "serif"]


def test_fallback_css_quoting():
    assert fonts.fallback_css("Times New Roman", "売上") == (
        '"Times New Roman", "Noto Serif JP", serif'
    )
    assert fonts.fallback_css("Arial", "abc") == '"Arial", sans-serif'


def test_needs_embedding():
    assert fonts.needs_embedding("BIZ UDPGothic")
    assert fonts.needs_embedding("Noto Serif JP")
    assert not fonts.needs_embedding("Times New Roman")
    assert not fonts.needs_embedding("MS Gothic")
