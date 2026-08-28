# -*- coding: utf-8 -*-
"""Playwright(chromium) ラスタライズ・撮影の共通定型部。

`svg2png.py` / `docs/pie-chart/_build/capture_examples.py` /
`docs/pdf-to-svg/_build/capture_screens.py` が個別に持っていた
「launch → new_context(device_scale_factor=2) → goto → networkidle → screenshot」の作法を
集約する。解像度規約（`DEVICE_SCALE_FACTOR` = 印刷時ににじまない 2 倍）の変更を 1 箇所で
済ませるため。オフライン制約により依存は追加しない（playwright は導入済みのものを遅延
import）。サーバ起動・UI 操作などスクリプト固有の撮影本体は共通化しない。

使い方（`docs/_build` 以外から）: `sys.path.insert(0, str(<repo>/docs/_build))` 後に
`import shot`。同階層の `svg2png.py` はそのまま `import shot` できる。
"""
from __future__ import annotations

import contextlib
import pathlib
from urllib.parse import urlsplit

# 印刷時ににじまない解像度の規約値。全図版・撮影で共通（変更はここだけ）。
DEVICE_SCALE_FACTOR = 2


def _is_scheme_allowed(url: str, allowed: frozenset[str]) -> bool:
    """`url` のスキームが許可集合に**完全一致**で含まれるか。危険スキームの数え上げ
    （denylist）ではなく「通すものだけ通す」allowlist。判定は純関数にしてテスト可能にする。"""
    return urlsplit(url).scheme.lower() in allowed


@contextlib.contextmanager
def chromium():
    """`sync_playwright()` + `chromium.launch()` の複合コンテキスト。browser を yield する。"""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


@contextlib.contextmanager
def page_context(browser, width: int, height: int, *, allowed_schemes):
    """規約解像度の new_context 済み page を yield する（goto は呼び出し側。
    `add_init_script` などナビゲーション前の仕込みを挟めるようにするため）。

    `allowed_schemes` は**必須引数**（既定値を持たない）。渡し忘れと「意図的な素通し」を
    字面で区別するため、素通しを選ぶ側は明示的に `None` を渡す。スキーム集合を渡すと、
    そのスキーム集合に**含まれない全リクエストを abort** する（通すものだけ通す
    allowlist）。自己完結な図版（外部参照を持たない SVG）を `file:` で描くとき
    `("file", "data")` を渡せば、SVG 内の `http(s)` 外部参照（保守者マシンからの SSRF 面）を
    Chromium が取りに行くのを止められる。`None` を渡すと素通し（ローカルサーバのスクショ
    撮影など、意図した取得がある経路向け）。"""
    ctx = browser.new_context(
        viewport={"width": width, "height": height},
        device_scale_factor=DEVICE_SCALE_FACTOR,
    )
    if allowed_schemes is not None:
        allowed = frozenset(allowed_schemes)
        ctx.route(
            "**/*",
            lambda route: route.continue_()
            if _is_scheme_allowed(route.request.url, allowed)
            else route.abort(),
        )
    try:
        yield ctx.new_page()
    finally:
        ctx.close()


def capture(browser, url: str, width: int, height: int,
            out: pathlib.Path, selector: str | None = None, *, allowed_schemes) -> None:
    """`url` を開き networkidle まで待って `out` へ PNG 撮影する一発ヘルパ。
    `selector` 指定時は要素単位（SVG 実寸ぴったりに切り出し、viewport の余白が混ざらない）。
    `allowed_schemes` は `page_context` と同じ**必須引数**（許可スキーム以外の取得を止める
    allowlist。素通しは `None` を明示で渡す）。"""
    with page_context(browser, width, height, allowed_schemes=allowed_schemes) as page:
        page.goto(url)
        page.wait_for_load_state("networkidle")
        target = page.locator(selector) if selector else page
        target.screenshot(path=str(out))
