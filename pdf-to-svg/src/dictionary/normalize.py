"""照合用の文字列正規化。

非エンジニアにも予測可能なよう、「trim + 連続空白圧縮 + NFKC(全角半角統一)」に固定する。
(大文字小文字無視・かな統一のオプションは持たない — 利用箇所が無い。)
"""
from __future__ import annotations

import re
import unicodedata

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """照合用キーへ正規化する (trim + NFKC + 連続空白圧縮)。"""
    return _WS.sub(" ", unicodedata.normalize("NFKC", text.strip()))
