# -*- coding: utf-8 -*-
"""`docs/<project>/images/` の手書き SVG 図版を Word 挿入用 PNG へラスタライズする。

SVG が正典・PNG はコミット済み成果物という運用（`build_all.py` には組み込まない。playwright を
文書ビルドの必須依存にしないため）。図版（*.svg）を追加・変更したときだけ本スクリプトを手動
実行し、隣に同名 .png を再生成して両方コミットする。python-docx は SVG を直接埋め込めないため
PNG 化が必要。

ラスタライズは導入済みの Playwright(chromium) を再利用する（cairosvg 等の依存追加はオフライン
制約に反するため不採用）。launch/コンテキスト/撮影の定型部と解像度規約（印刷ににじまない
`device_scale_factor`）は同階層の `shot.py` に集約している。フォント（`BIZ UDPGothic`）は
Windows 同梱のものを chromium の実描画で使う。

使い方:
  python docs/_build/svg2png.py                    docs/*/images/*.svg 全件
  python docs/_build/svg2png.py --project editor   指定プロジェクトのみ
"""
from __future__ import annotations

import argparse
import math
import pathlib
import re
import sys

DOCS = pathlib.Path(__file__).resolve().parents[1]   # <repo>/docs

# viewBox="minX minY width height" から実寸を拾う（自作図版は width/height 属性も持つが、
# viewport 決定は viewBox を正とする）。
_VIEWBOX = re.compile(r'viewBox\s*=\s*"[\d.+-]+[\s,]+[\d.+-]+[\s,]+([\d.]+)[\s,]+([\d.]+)"')


def _svg_size(svg_path: pathlib.Path):
    m = _VIEWBOX.search(svg_path.read_text(encoding="utf-8"))
    if not m:
        return 1200, 650   # 自作図版の標準サイズへフォールバック
    return math.ceil(float(m.group(1))), math.ceil(float(m.group(2)))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="対象プロジェクト名（docs 直下のフォルダ名）")
    args = ap.parse_args(argv)

    targets = sorted(DOCS.glob("*/images/*.svg"))
    if args.project:
        targets = [p for p in targets if p.parents[1].name == args.project]
    if not targets:
        print("対象 SVG がありません")
        return 0

    import shot

    with shot.chromium() as browser:
        for svg in targets:
            w, h = _svg_size(svg)
            out = svg.with_suffix(".png")
            # 図版は自己完結（外部参照を持たない）。file:/data: 以外の取得は allowlist で
            # 止める（SVG 内の http(s) 外部参照による保守者マシンからの SSRF 面を閉じる）。
            shot.capture(browser, svg.resolve().as_uri(), w, h, out, selector="svg",
                         allowed_schemes=("file", "data"))
            print(f"  [ok] {out.relative_to(DOCS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
