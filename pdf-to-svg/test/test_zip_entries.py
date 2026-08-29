"""ZIP 集約 (``rpc_zipEntries``) のエントリ名の衝突回避。

同名の PDF を複数選ぶと推奨ファイル名 (``<元ファイル名>_pN.svg``) が丸ごと重なる。
ZIP は同名エントリを許してしまうため、そのまま詰めると展開時に片方が失われる。
"""
import base64
import io
import zipfile

from web.rpc_methods import rpc_zipEntries


def _names(entries):
    res = rpc_zipEntries(None, {"entries": entries})
    buf = io.BytesIO(base64.b64decode(res["zipBase64"]))
    with zipfile.ZipFile(buf) as zf:
        return zf.namelist(), res["count"]


def test_同名エントリは連番を付けて衝突を避ける():
    names, count = _names(
        [
            {"name": "sample_p1.svg", "text": "<svg>a</svg>"},
            {"name": "sample_p1.svg", "text": "<svg>b</svg>"},
            {"name": "sample_p1.svg", "text": "<svg>c</svg>"},
        ]
    )
    assert names == ["sample_p1.svg", "sample_p1_2.svg", "sample_p1_3.svg"]
    assert len(set(names)) == 3
    assert count == 3


def test_衝突しない名前はそのまま保つ():
    names, _ = _names(
        [
            {"name": "a_p1.svg", "text": "<svg/>"},
            {"name": "b_p1.svg", "text": "<svg/>"},
        ]
    )
    assert names == ["a_p1.svg", "b_p1.svg"]


def test_連番を足した名前がさらに衝突しても重ならない():
    names, _ = _names(
        [
            {"name": "x_p1.svg", "text": "<svg/>"},
            {"name": "x_p1_2.svg", "text": "<svg/>"},
            {"name": "x_p1.svg", "text": "<svg/>"},
        ]
    )
    assert len(set(names)) == 3
    assert names[0] == "x_p1.svg"
    assert names[1] == "x_p1_2.svg"


def test_中身は名前の変更後も対応するエントリのまま():
    res = rpc_zipEntries(
        None,
        {
            "entries": [
                {"name": "s_p1.svg", "text": "<svg>first</svg>"},
                {"name": "s_p1.svg", "text": "<svg>second</svg>"},
            ]
        },
    )
    buf = io.BytesIO(base64.b64decode(res["zipBase64"]))
    with zipfile.ZipFile(buf) as zf:
        assert zf.read("s_p1.svg").decode() == "<svg>first</svg>"
        assert zf.read("s_p1_2.svg").decode() == "<svg>second</svg>"
