"""ページを構成するプリミティブ要素。

座標系は PDF/SVG/Qt で共通の「左上原点・y 下向き・単位 pt」。
PyMuPDF から抽出したものをそのまま保持し、SVG 書き出し時もそのまま使える。
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from typing import List, Optional

# 要素 ID 採番 (プロセス内で一意であれば十分)
_id_counter = itertools.count(1)


def new_id() -> int:
    return next(_id_counter)


# XML 1.0 で許されない制御文字 (tab/LF/CR を除く C0 制御と DEL)
_XML_INVALID = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str) -> str:
    """XML 1.0 で不正な制御文字を除去する (壊れた ToUnicode CMap 対策)。"""
    return _XML_INVALID.sub("", text)


# hex 表記 (3/4/6/8 桁)。engine 由来の色は必ず ``#rrggbb`` なのでこの形に収まる。
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

# CSS の名前付き色。正規表現で近似せず固定集合で持つ (近似は必ず余計な形を通す)。
_NAMED_COLORS = frozenset(
    """aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue
    blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk
    crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki
    darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen
    darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue
    dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite
    gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki
    lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan
    lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen
    lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen
    magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen
    mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream
    mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid
    palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum
    powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown
    seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen
    steelblue tan teal thistle tomato transparent turquoise violet wheat white whitesmoke
    yellow yellowgreen""".split()
)


def sanitize_color(value):
    """SVG paint として受理できる色だけを通す (不正値は ``ValueError``)。

    ``None`` はそのまま返す (``_paint`` が ``none`` を書く)。``rgb()`` / ``hsl()`` /
    ``url(#x)`` は**許さない** — 関数記法は CSS 経路で ``rgb(0,0,0);x:y`` と宣言を
    増やせ、``url()`` は外部参照と ``javascript:`` の入口になる。書き出した SVG は
    社内回覧される成果物なので、守るべきは表示面ではなく**生成点**である。
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"color must be a string: {value!r}")
    v = value.strip()
    if _HEX_COLOR.match(v) or v.lower() in _NAMED_COLORS or v in ("none", "currentColor"):
        return v
    raise ValueError(
        f"unsupported color: {value!r} "
        "(allowed: #rgb / #rgba / #rrggbb / #rrggbbaa / CSS named colors / none / currentColor)"
    )


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def x1(self) -> float:
        return self.x + self.w

    @property
    def y1(self) -> float:
        return self.y + self.h

    def intersects(self, other: "Rect") -> bool:
        return not (
            self.x1 <= other.x
            or other.x1 <= self.x
            or self.y1 <= other.y
            or other.y1 <= self.y
        )

    @classmethod
    def from_xyxy(cls, x0: float, y0: float, x1: float, y1: float) -> "Rect":
        return cls(x0, y0, x1 - x0, y1 - y0)


@dataclass
class DictMatch:
    """辞書による置換が当たったことを示す情報 (ハイライト/レビュー用)。"""

    source: str
    target: str


@dataclass
class DictRevertInfo:
    """辞書置換を 1 箇所だけ戻すための置換前状態。

    置換コマンドは Undo マクロの中に埋まっていて個別には辿れず、Undo 深さ上限で
    捨てられもするため、復元元は要素自身が持つ。`extra_ids` は折返し畳み込みで
    論理削除した後続行の id (戻すときに再表示する)。
    """

    text: str
    bbox: Rect
    wrap_align: Optional[str]
    origin_y: float
    extra_ids: List[int] = field(default_factory=list)


@dataclass
class Element:
    """全要素の基底。"""

    kind: str = "element"
    bbox: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    z: int = 0
    deleted: bool = False
    id: int = field(default_factory=new_id)


@dataclass
class TextElement(Element):
    kind: str = "text"
    text: str = ""
    original_text: str = ""  # 辞書置換前の値 (Undo / レビュー用)
    font_family: str = "sans-serif"
    font_size: float = 12.0
    weight: int = 400  # CSS フォントウェイト (100-900)。元 PDF のウェイトを保持
    italic: bool = False
    color: str = "#000000"
    origin_x: float = 0.0  # ベースライン原点 (SVG <text> の x)
    origin_y: float = 0.0  # ベースライン原点 (SVG <text> の y)
    is_header: bool = False
    dict_match: Optional[DictMatch] = None
    # 折返し畳み込み置換の水平揃え ("left"/"center"/"right")。None = 非連結の通常要素。
    # 設定時は SVG 出力が bbox (折返しグループの合成領域) の左/中央/右へ anchor し、
    # 縦は origin_y (最終行のベースラインへ据え直し済み) の下揃えで描く。
    wrap_align: Optional[str] = None
    # 置換が当たっている間だけ持つ復元情報 (箇所単位の「戻す」用)。None = 未置換。
    dict_revert: Optional[DictRevertInfo] = None

    def __post_init__(self) -> None:
        if not self.original_text:
            self.original_text = self.text

    @property
    def bold(self) -> bool:
        """太字相当か (weight>=600)。weight を単一ソースとする (辞書ヘッダ判定・エディタ表示の互換用)。"""
        return self.weight >= 600


@dataclass
class LineElement(Element):
    kind: str = "line"
    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0
    width: float = 1.0
    color: str = "#000000"


@dataclass
class RectElement(Element):
    kind: str = "rect"
    rect: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    stroke: Optional[str] = "#000000"
    fill: Optional[str] = None
    stroke_width: float = 1.0


@dataclass
class PathElement(Element):
    kind: str = "path"
    # SVG path の "d" 文字列。get_drawings の各 item を変換して格納。
    d: str = ""
    stroke: Optional[str] = "#000000"
    fill: Optional[str] = None
    stroke_width: float = 1.0


@dataclass
class ImageElement(Element):
    kind: str = "image"
    rect: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    # raw 画像バイト列を base64 で SVG に埋め込む。ext は "png"/"jpeg" 等。
    img_bytes: bytes = b""
    ext: str = "png"
