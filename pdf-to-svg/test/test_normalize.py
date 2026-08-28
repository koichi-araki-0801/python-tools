"""`dictionary.normalize` の `normalize` の単体テスト。

NFKC 正規化 (全角→半角)・trim + 連続空白圧縮・大文字小文字とカナの非変換を確認する。
"""
from dictionary.normalize import normalize


def test_nfkc_fullwidth_halfwidth():
    # 全角英数字 → 半角 (NFKC)
    assert normalize("ＡＢＣ１２３") == "ABC123"


def test_trim_and_collapse_ws():
    assert normalize("  売上   高 ") == "売上 高"


def test_case_and_kana_preserved():
    # 大文字小文字・カタカナは変換しない (照合キーは見た目どおり)
    assert normalize("ABC") == "ABC"
    assert normalize("カタカナ") == "カタカナ"
