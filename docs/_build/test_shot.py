# -*- coding: utf-8 -*-
"""shot.py の allowlist スキーム判定の単体テスト（Playwright 不要の純関数）。

`svg2png.py` は図版 SVG を `file:` で Chromium に描かせるため、SVG 内の `http(s)` 外部参照を
保守者マシンから取りに行く SSRF 面があった。`_is_scheme_allowed` の allowlist（通すものだけ
通す）でそれを閉じる。実行: `python -m pytest docs/_build/test_shot.py`。
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import shot  # noqa: E402


def test_scheme_allowlist_passes_only_listed_schemes():
    allowed = frozenset({"file", "data"})
    # 自己完結な図版が要する取得だけを通す。
    assert shot._is_scheme_allowed("file:///C:/repo/docs/editor/images/fig.svg", allowed) is True
    assert shot._is_scheme_allowed("data:image/png;base64,AAAA", allowed) is True
    # 外部参照（SSRF 面）はすべて止める。
    assert shot._is_scheme_allowed("http://169.254.169.254/latest/meta-data/", allowed) is False
    assert shot._is_scheme_allowed("https://evil.example/x.png", allowed) is False
    assert shot._is_scheme_allowed("ftp://host/x", allowed) is False


def test_scheme_allowlist_normalizes_case():
    allowed = frozenset({"file", "data"})
    assert shot._is_scheme_allowed("HTTP://evil.example/x", allowed) is False
    assert shot._is_scheme_allowed("FILE:///x", allowed) is True


def test_page_context_requires_allowed_schemes():
    """`allowed_schemes` は必須引数。渡し忘れは呼び出し時点で `TypeError` になる
    （実行して初めて気付く「意図せぬ素通し」を防ぐ）。"""
    try:
        shot.page_context(browser=None, width=100, height=100)
    except TypeError:
        pass
    else:
        raise AssertionError("allowed_schemes 省略で TypeError にならなかった")


def test_capture_requires_allowed_schemes():
    try:
        shot.capture(browser=None, url="about:blank", width=100, height=100,
                     out=pathlib.Path("unused.png"))
    except TypeError:
        pass
    else:
        raise AssertionError("allowed_schemes 省略で TypeError にならなかった")
