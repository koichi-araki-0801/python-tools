"""PDF フォント名 → Windows 標準フォント / 同梱代替フォントへのマッピング。

PDF から抽出したフォント名 (Times-Roman, ArialMT, HiraKakuProN-W3 など) は
Windows のフォントファミリ名と一致しないことが多い。本モジュールで

1. 既知名は Windows 標準フォントへ対応付け (Times-Roman → "Times New Roman")
2. 対応付けできない場合は文字種別 (欧文 serif/sans/等幅、和文 明朝/ゴシック)
   ごとの代替フォントへフォールバック
3. 有料フォント (ヒラギノ・小塚等) は同梱の BIZ UD フォントへ置き換え

を行う。BIZ UDPゴシック (モリサワ製・SIL OFL) と Noto Serif JP は本プロジェクト配下の
``fonts/`` に同梱し、SVG 出力時は使用フォントのみ WOFF2 化して埋め込む
(config.font_path / font_embed 参照)。

純 Python (Qt / fitz 非依存) — model 層に置き engine / export / editor で共有する。
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class MappedFont:
    """マッピング結果。family はマッピング後のファミリ名、weight は CSS 数値 (100-900)。"""

    family: str
    weight: int = 400
    italic: bool = False


# 同梱・静的フォント (本プロジェクトの fonts/)。(family, weight bucket) → フォントファイル名。
# サブセット元は正規 TTF 原本 (Morisawa/Google Fonts・SIL OFL) を使う。WOFF2 をサブセット
# 元にすると fontTools が変換済み glyf を全グリフ再構築するため数十秒かかり実用に耐えない
# (TTF/WOFF1 は無変換で高速。SVG 埋め込み出力は font_embed が WOFF2 で書き出す)。pie-chart は
# 同ファミリの BIZ UDPGothic WOFF2 を自プロジェクト配下に別途持つ。Regular/Bold の
# 2 ウェイトのみ存在するため bucket は 400/700。@font-face は STATIC_WEIGHT_RANGE で範囲
# 宣言し、中間ウェイト要求を faux-bold 無しで最寄りの静的フォントへ解決させる。
BUNDLED_FONTS: Dict[Tuple[str, int], str] = {
    ("BIZ UDPGothic", 400): "BIZUDPGothic-Regular.ttf",
    ("BIZ UDPGothic", 700): "BIZUDPGothic-Bold.ttf",
}

# 静的フォントの @font-face font-weight 範囲。bucket → "min max"。
STATIC_WEIGHT_RANGE: Dict[int, str] = {400: "1 599", 700: "600 1000"}

# 同梱・可変フォント。family → VF ファイル名。wght 軸を保持したままサブセット埋め込み
# し、@font-face を font-weight:100 900 で宣言する (1 本で全ウェイトを賄う)。
BUNDLED_VARIABLE: Dict[str, str] = {
    "Noto Serif JP": "NotoSerifJP-VF.ttf",
}

_STATIC_FAMILIES = {family for family, _w in BUNDLED_FONTS}
_BUNDLED_FAMILIES = _STATIC_FAMILIES | set(BUNDLED_VARIABLE)


def needs_embedding(family: str) -> bool:
    """SVG への埋め込みが必要か (同梱フォントのみ。Windows 標準は名前参照で足りる)。"""
    return family in _BUNDLED_FAMILIES


def is_variable_family(family: str) -> bool:
    """可変フォントとして wght 軸保持で埋め込むファミリか。"""
    return family in BUNDLED_VARIABLE


def static_weight_bucket(family: str, weight: int) -> int:
    """静的ファミリで、要求 weight を実在する最寄りのバケット (400/700) へ丸める。

    @font-face の STATIC_WEIGHT_RANGE 宣言と一致させるため、各バケットの範囲下限で
    判定する (例: 1-599→400 / 600-1000→700。よって weight 600 は太字バケット)。
    """
    buckets = sorted(w for fam, w in BUNDLED_FONTS if fam == family)
    if not buckets:
        return weight
    chosen = buckets[0]
    for b in buckets:
        lo = int(STATIC_WEIGHT_RANGE[b].split()[0])
        if weight >= lo:
            chosen = b
    return chosen


# マッピング先ファミリの属性: family → (generic, 和文フォントか)
_FAMILY_META: Dict[str, Tuple[str, bool]] = {
    "Times New Roman": ("serif", False),
    "Georgia": ("serif", False),
    "Cambria": ("serif", False),
    "Arial": ("sans-serif", False),
    "Segoe UI": ("sans-serif", False),
    "Segoe UI Symbol": ("sans-serif", False),
    "Verdana": ("sans-serif", False),
    "Tahoma": ("sans-serif", False),
    "Calibri": ("sans-serif", False),
    "Courier New": ("monospace", False),
    "Consolas": ("monospace", False),
    "MS Mincho": ("serif", True),
    "MS PMincho": ("serif", True),
    "Yu Mincho": ("serif", True),
    "Noto Serif JP": ("serif", True),
    "MS Gothic": ("sans-serif", True),
    "MS PGothic": ("sans-serif", True),
    "MS UI Gothic": ("sans-serif", True),
    "Yu Gothic": ("sans-serif", True),
    "Meiryo": ("sans-serif", True),
    "BIZ UDPGothic": ("sans-serif", True),
}

# 種別ごとのデフォルト代替フォント。欧文は Windows 標準 (埋め込み不要)、
# 和文は同梱 BIZ UD (SVG へ WOFF2 埋め込み)。有料フォントは使わない。
_DEFAULTS: Dict[Tuple[str, str], str] = {
    ("latin", "serif"): "Times New Roman",
    ("latin", "sans-serif"): "Arial",
    ("latin", "monospace"): "Courier New",
    ("ja", "serif"): "Noto Serif JP",
    ("ja", "sans-serif"): "BIZ UDPGothic",
    ("ja", "monospace"): "BIZ UDPGothic",
}


def _norm(name: str) -> str:
    """照合キー: 小文字化し空白・ハイフン・アンダースコア・カンマを除去。"""
    return "".join(c for c in name.lower() if c not in " -_,")


_EXACT: Dict[str, MappedFont] = {}


def _reg(names: List[str], family: str, weight: int = 400, italic: bool = False) -> None:
    for n in names:
        _EXACT[_norm(n)] = MappedFont(family, weight, italic)


# --- PDF 標準 14 フォント + 欧文エイリアス -----------------------------------
_reg(["Times-Roman", "Times", "TimesNewRoman", "TimesNewRomanPSMT", "TimesNewRomanPS"],
     "Times New Roman")
_reg(["Helvetica", "Arial", "ArialMT", "ArialUnicodeMS", "Helv"], "Arial")
_reg(["Courier", "CourierNew", "CourierNewPSMT", "CourierNewPS", "CourierStd"],
     "Courier New")
_reg(["Symbol", "ZapfDingbats"], "Segoe UI Symbol")

# --- Windows 標準フォント (恒等) ---------------------------------------------
for _f in ("Segoe UI", "Verdana", "Tahoma", "Georgia", "Calibri", "Cambria",
           "Consolas", "Times New Roman", "Courier New", "Segoe UI Symbol"):
    _reg([_f], _f)

# --- Windows 標準和文フォント (そのまま維持・埋め込み不要) --------------------
_reg(["MS-Mincho", "MSMincho", "MS 明朝", "MS Mincho"], "MS Mincho")
_reg(["MS-PMincho", "MSPMincho", "MS P明朝", "MS PMincho"], "MS PMincho")
_reg(["MS-Gothic", "MSGothic", "MS ゴシック", "MS Gothic"], "MS Gothic")
_reg(["MS-PGothic", "MSPGothic", "MS Pゴシック", "MS PGothic"], "MS PGothic")
_reg(["MS-UIGothic", "MSUIGothic", "MS UI Gothic"], "MS UI Gothic")
_reg(["YuMincho", "Yu Mincho", "YuMin"], "Yu Mincho")
_reg(["YuMincho-Demibold", "YuMin-Demibold"], "Yu Mincho", weight=600)
_reg(["YuGothic", "Yu Gothic", "YuGo", "YuGothicUI", "Yu Gothic UI"], "Yu Gothic")
_reg(["Meiryo", "MeiryoUI", "Meiryo UI", "メイリオ"], "Meiryo")

# --- 有料・Windows 非搭載の和文フォント → 同梱 BIZ UD へ代替 ------------------
# ヒラギノ (Apple/有料)
_reg(["HiraMinProN", "HiraMinPro", "HiraMinStdN", "ヒラギノ明朝 ProN", "ヒラギノ明朝 Pro"],
     "Noto Serif JP")
_reg(["HiraKakuProN", "HiraKakuPro", "HiraKakuStdN", "HiraginoSans", "Hiragino Sans",
      "ヒラギノ角ゴ ProN", "ヒラギノ角ゴ Pro"], "BIZ UDPGothic")
_reg(["HiraMaruProN", "HiraMaruPro", "ヒラギノ丸ゴ ProN"], "BIZ UDPGothic")
# 小塚 (Adobe 製品同梱)
_reg(["KozMinPr6N", "KozMinProVI", "KozMinPro", "KozMinStd", "小塚明朝"], "Noto Serif JP")
_reg(["KozGoPr6N", "KozGoProVI", "KozGoPro", "KozGoStd", "小塚ゴシック"], "BIZ UDPGothic")
# Noto / 源ノ (無料だが Windows 非搭載 → 同梱フォントで代替)
_reg(["NotoSerifJP", "NotoSerifCJKjp", "NotoSerifCJKJP", "SourceHanSerif", "SourceHanSerifJP",
      "源ノ明朝"], "Noto Serif JP")
_reg(["NotoSansJP", "NotoSansCJKjp", "NotoSansCJKJP", "SourceHanSans", "SourceHanSansJP",
      "源ノ角ゴシック"], "BIZ UDPGothic")
# IPA フォント
_reg(["IPAMincho", "IPAexMincho", "IPAPMincho", "IPA明朝", "IPAex明朝", "IPAP明朝"],
     "Noto Serif JP")
_reg(["IPAGothic", "IPAexGothic", "IPAPGothic", "IPAゴシック", "IPAexゴシック", "IPAPゴシック"],
     "BIZ UDPGothic")
# BIZ UD 自身。同梱は pie-chart と共有の BIZ UDPGothic (プロポーショナル) に一本化したため、
# 等幅 UDGothic 由来も UDPGothic へ寄せる。明朝は Noto Serif JP へ一本化。
_reg(["BIZUDGothic", "BIZ UDGothic", "BIZUDPGothic", "BIZ UDPGothic"], "BIZ UDPGothic")
_reg(["BIZUDMincho", "BIZ UDMincho", "BIZUDPMincho", "BIZ UDPMincho"], "Noto Serif JP")

# 末尾スタイルトークン: (トークン, weight, italic)。weight=None はウェイトに影響しない
# 接尾辞 (mt/ps など)。weight は CSS 数値 (100-900)。
_STYLE_TOKENS: List[Tuple[str, Optional[int], bool]] = [
    ("bolditalic", 700, True),
    ("boldoblique", 700, True),
    ("debold", 600, False),   # モリサワ DeBold ≒ DemiBold
    ("exbold", 800, False),
    ("demibold", 600, False),
    ("semibold", 600, False),
    ("bold", 700, False),
    ("db", 600, False),       # DemiBold 略号
    ("eb", 800, False),       # ExtraBold 略号
    ("heavy", 800, False),
    ("black", 900, False),
    ("bd", 700, False),
    ("w6", 600, False),
    ("w7", 700, False),
    ("w8", 800, False),
    ("w9", 900, False),
    ("italic", None, True),
    ("oblique", None, True),
    ("it", None, True),
    ("regular", 400, False),
    ("normal", 400, False),
    ("medium", 500, False),
    ("light", 300, False),
    ("thin", 100, False),
    ("w3", 300, False),
    ("w4", 400, False),
    ("w5", 500, False),
    ("mt", None, False),
    ("psmt", None, False),
    ("ps", None, False),
]


def _strip_style(key: str) -> Tuple[str, Optional[int], bool]:
    """正規化キー末尾のスタイルトークンを剥がし (基底キー, weight, italic) を返す。

    "timesnewromanpsboldmt" → ("timesnewromanps", 700, False) のように
    バリアント名の爆発を抑えて完全一致表へ再照合できるようにする。
    weight は検出した最も重いウェイト (無ければ None)。
    """
    weight: Optional[int] = None
    italic = False
    changed = True
    while changed:
        changed = False
        for token, w, i in _STYLE_TOKENS:
            if key.endswith(token) and len(key) > len(token):
                key = key[: -len(token)]
                if w is not None:
                    weight = w if weight is None else max(weight, w)
                italic = italic or i
                changed = True
                break
    return key, weight, italic


def contains_japanese(text: str) -> bool:
    """和文文字 (かな・漢字・全角形・CJK 記号) を含むか。"""
    for ch in text:
        o = ord(ch)
        if (
            0x3000 <= o <= 0x30FF      # CJK 記号・ひらがな・カタカナ
            or 0x3400 <= o <= 0x9FFF   # CJK 統合漢字 (拡張 A 含む)
            or 0xF900 <= o <= 0xFAFF   # CJK 互換漢字
            or 0xFF00 <= o <= 0xFFEF   # 全角英数・半角カナ
        ):
            return True
    return False


def _classify(name: str) -> Tuple[str, bool]:
    """未知フォント名から (generic, 和文ヒント) を推定する。"""
    n = _norm(name)
    if "mincho" in n or "明朝" in n or "ming" in n or "song" in n:
        return "serif", True
    # モリサワ系明朝 (UD黎ミン・リュウミン・太ミン等)
    if "reimin" in n or "ryumin" in n or "futomin" in n or "黎ミン" in n or "リュウミン" in n:
        return "serif", True
    # モリサワ系ゴシック (UD新ゴ・太ゴ・見出ゴ等)
    if "shingo" in n or "futogo" in n or "midashigo" in n or "新ゴ" in n:
        return "sans-serif", True
    if "ゴシック" in n or "maru" in n:
        return "sans-serif", True
    if "mono" in n or "courier" in n or "consol" in n or "typewriter" in n:
        return "monospace", False
    if "sans" in n:
        return "sans-serif", False
    if "gothic" in n or "kaku" in n:
        # Century Gothic 等の欧文も含むため和文かはテキスト側で判定する
        return "sans-serif", contains_japanese(name)
    for kw in ("serif", "times", "roman", "georgia", "garamond", "century", "book"):
        if kw in n:
            return "serif", False
    return "sans-serif", contains_japanese(name)


def map_font(pdf_name: str, text: str = "") -> MappedFont:
    """PDF フォント名を Windows 標準 / 同梱代替フォントへマッピングする。

    text は要素のテキスト。未知フォント名のとき和文/欧文の判定に使う。
    """
    key = _norm(pdf_name)
    hit = _EXACT.get(key)
    weight: Optional[int] = None
    italic = False
    if hit is None:
        base, weight, italic = _strip_style(key)
        hit = _EXACT.get(base)
    if hit is not None:
        # 名前末尾の重み指定 (例 "-W3"/"-Bold") はそのフォント実体のウェイトなので、
        # 基底エントリの既定 weight より優先する。接尾辞が無ければ基底の weight。
        resolved = weight if weight is not None else hit.weight
        return MappedFont(hit.family, resolved, hit.italic or italic)

    generic, ja_hint = _classify(pdf_name)
    script = "ja" if (ja_hint or contains_japanese(text)) else "latin"
    return MappedFont(_DEFAULTS[(script, generic)], weight or 400, italic)


def family_meta(family: str) -> Tuple[str, bool]:
    """ファミリ名から (generic, 和文フォントか) を返す。"""
    meta = _FAMILY_META.get(family)
    if meta is not None:
        return meta
    return _classify(family)


def fallback_chain(family: str, text: str) -> List[str]:
    """SVG / Qt 用のフォールバックチェーンを構築する。

    テキストが和文を含み先頭ファミリが和文非対応なら同梱の和文フォントを
    挿入する。辞書置換でテキストが変わり得るため出力・描画時に呼ぶこと。
    """
    generic, is_ja = family_meta(family)
    chain = [family]
    if contains_japanese(text) and not is_ja:
        chain.append("Noto Serif JP" if generic == "serif" else "BIZ UDPGothic")
    chain.append(generic)
    return chain


def fallback_css(family: str, text: str) -> str:
    """fallback_chain を CSS font-family 値へ整形 (具体名は二重引用符で囲む)。"""
    parts = []
    for name in fallback_chain(family, text):
        if name in ("serif", "sans-serif", "monospace"):
            parts.append(name)
        else:
            parts.append(f'"{name}"')
    return ", ".join(parts)


# 辞書置換語が元グリフ箱の幅を超えると `textLength` で圧縮表示され見栄えが崩れる。
# 実グリフの advance を測らず、東アジア全角(W/F)を 1em・他を 0.5em とみなす簡易推定で
# 「超過の恐れ」を検出して警告するための係数 (プロポーショナル欧文は誤差あり=注意喚起用途)。
WIDTH_OVERFLOW_TOL = 1.05  # 箱幅をこの倍率超えたら警告


def estimate_text_width(text: str, font_size: float) -> float:
    """テキストの描画幅を簡易推定する (警告用途の概算)。

    東アジア全角 (east_asian_width が W/F) は `font_size`、それ以外は `font_size*0.5`
    として合算する。実フォントの advance ではないため厳密ではない。
    """
    return sum(
        font_size * (1.0 if unicodedata.east_asian_width(ch) in ("W", "F") else 0.5)
        for ch in text
    )


def is_width_overflow(text: str, font_size: float, box_w: float) -> bool:
    """`text` の推定幅が収め先の箱幅 `box_w` を許容倍率超えるか (置換の幅超過警告)。"""
    return box_w > 0 and estimate_text_width(text, font_size) > box_w * WIDTH_OVERFLOW_TOL
