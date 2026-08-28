"""`_match_seqno` の描画順 (seqno) 照合ロジックの単体テスト。

凡例ラベルが消える不具合の回帰防止。軸ラベル全体を 1 度に描いた巨大 span が
内側の小さな凡例ラベルを吸い込み、誤って早い seqno を与える問題を検証する。
`query` に最もフィットする狭い候補を選び、無限大 bbox は IoU で弾く。
"""
from engine.pdf_engine import _match_seqno
from model.elements import Rect


def test_prefers_tight_span_over_large_enclosing_one():
    """query を内包する巨大候補 (早い seqno) ではなく、フィットする狭い候補を選ぶ。"""
    query = Rect.from_xyxy(105, 238, 171, 252)  # 凡例ラベル相当
    candidates = [
        # 軸ラベル全体を 1 度に描いた巨大 span。query を完全内包するが描画順は早い。
        (12, Rect.from_xyxy(62, 214, 475, 274)),
        # 凡例ラベルの正しい span。query とほぼ一致し描画順は後。
        (26, Rect.from_xyxy(105, 243, 195, 251)),
    ]
    assert _match_seqno(query, candidates, default=0) == 26


def test_single_enclosing_candidate_is_matched():
    """候補が 1 つしか重ならないときは従来どおりその seqno を返す。"""
    query = Rect.from_xyxy(105, 243, 171, 251)
    candidates = [(7, Rect.from_xyxy(100, 240, 200, 255))]
    assert _match_seqno(query, candidates, default=0) == 7


def test_no_overlap_returns_default():
    query = Rect.from_xyxy(0, 0, 10, 10)
    candidates = [(3, Rect.from_xyxy(100, 100, 200, 200))]
    assert _match_seqno(query, candidates, default=-1) == -1


def test_infinite_bbox_candidate_is_rejected():
    """fill-shade のような無限大 bbox の候補は IoU≈0 で弾かれる。"""
    query = Rect.from_xyxy(100, 100, 120, 110)
    big = 2_147_483_648.0
    candidates = [
        (0, Rect.from_xyxy(-big, -big, big, big)),  # 無限大 shade
        (5, Rect.from_xyxy(99, 99, 121, 111)),       # 実体にフィット
    ]
    assert _match_seqno(query, candidates, default=-1) == 5
