"""同梱フォントを使用グリフのみサブセット化し WOFF2 で SVG へ埋め込む。

Windows 標準フォントは閲覧環境にあるため名前参照のみで埋め込まない。
同梱フォント (model.fonts.BUNDLED_FONTS / BUNDLED_VARIABLE) だけが対象。
サブセット化により全グリフ埋め込み (数 MB) を避け、実用上数十 KB に収める。

ウェイトの扱い:
- 可変フォント (Noto Serif JP): wght 軸を保持したまま 1 本サブセットし、@font-face を
  font-weight:100 900 で宣言する。<text> の数値 font-weight で Light〜Bold を出し分ける。
- 静的フォント (BIZ UDGothic): 実在ウェイト (Regular/Bold) ごとにサブセットし、@font-face を
  STATIC_WEIGHT_RANGE の範囲で宣言する。中間ウェイト要求は faux-bold 無しで最寄りへ解決される。
"""
from __future__ import annotations

import base64
from functools import lru_cache
from io import BytesIO
from typing import Dict, Iterable, Set, Tuple

from fontTools import subset
from fontTools.ttLib import TTFont

import config
from model import fonts
from model.elements import TextElement



def font_face_css(elements: Iterable[TextElement]) -> str:
    """テキスト要素群が必要とする @font-face CSS を生成する (不要なら空文字)。"""
    var_usage, static_usage = _collect_usage(elements)
    rules = []

    for family in sorted(var_usage):
        data = _subset_woff2(fonts.BUNDLED_VARIABLE[family], var_usage[family])
        if data is None:
            continue
        rules.append(_face(family, "100 900", data))

    for (family, bucket) in sorted(static_usage):
        data = _subset_woff2(fonts.BUNDLED_FONTS[(family, bucket)], static_usage[(family, bucket)])
        if data is None:
            continue
        rules.append(_face(family, fonts.STATIC_WEIGHT_RANGE[bucket], data))

    return "".join(rules)


def _face(family: str, weight: str, data: bytes) -> str:
    b64 = base64.b64encode(data).decode("ascii")
    return (
        f'@font-face{{font-family:"{family}";font-weight:{weight};'
        f"font-style:normal;"
        f'src:url(data:font/woff2;base64,{b64}) format("woff2");}}'
    )


def _collect_usage(
    elements: Iterable[TextElement],
) -> Tuple[Dict[str, Set[str]], Dict[Tuple[str, int], Set[str]]]:
    """埋め込みが必要な使用文字を、可変は family 単位・静的は (family, bucket) 単位で集める。

    フォールバックチェーンで補完される和文フォント (欧文フォント + 和文テキストの
    ケース) も対象に含める。
    """
    var_usage: Dict[str, Set[str]] = {}
    static_usage: Dict[Tuple[str, int], Set[str]] = {}
    for el in elements:
        if not el.text:
            continue
        for family in fonts.fallback_chain(el.font_family, el.text):
            if fonts.is_variable_family(family):
                var_usage.setdefault(family, set()).update(el.text)
            elif fonts.needs_embedding(family):
                bucket = fonts.static_weight_bucket(family, el.weight)
                static_usage.setdefault((family, bucket), set()).update(el.text)
    return var_usage, static_usage


@lru_cache(maxsize=None)
def _source_font_bytes(filename: str) -> bytes | None:
    """同梱ソースフォントのバイト列 (存在しなければ None)。複数ページ書き出しでの
    ディスク再読込を避けるためプロセス内でキャッシュする。

    在否を `exists()` で先に見ない: Windows の `exists()` は共有瞬断系の OSError を
    握りつぶして False を返すため、ネットワークドライブ配置の exe では一瞬の切断が
    「フォント無し」に化け、**埋め込みを黙って欠いた SVG** が書き出される (しかも
    キャッシュが None を記憶してプロセスの間ずっと直らない)。真の不在
    (`FileNotFoundError` = 同梱漏れ) だけ None とし、それ以外の OSError は投げて
    書き出し自体を失敗させる (無音の品質劣化より見えるエラー)。例外は
    `lru_cache` に記憶されないので、復旧後の再実行はやり直せる。"""
    path = config.font_path(filename)
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _subset_woff2(filename: str, chars: Set[str]) -> bytes | None:
    """同梱フォントを使用文字でサブセット化し WOFF2 バイト列を返す。

    ソース ``filename`` は TTF/WOFF1 等の無変換形式であること (model.fonts 参照)。
    WOFF2 をソースにすると fontTools が変換済み glyf を全グリフ再構築するため極端に
    遅くなる。出力は ``flavor='woff2'`` で常に WOFF2。

    可変フォントは subset がデフォルトで fvar/gvar 等を保持するため、軸を維持したまま
    1 本に収まる (実行時インスタンス化は行わない)。
    """
    data = _source_font_bytes(filename)
    if data is None:
        return None

    # subset は font を破壊的に変更するため、毎回キャッシュ済みバイト列から再構築する。
    font = TTFont(BytesIO(data))
    options = subset.Options()
    options.flavor = "woff2"
    subsetter = subset.Subsetter(options)
    subsetter.populate(text="".join(chars))
    subsetter.subset(font)
    font.flavor = "woff2"
    buf = BytesIO()
    font.save(buf)
    return buf.getvalue()
