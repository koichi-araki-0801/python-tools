# -*- coding: utf-8 -*-
"""全プロジェクトの原稿（`docs/<project>/src/`）を閲覧用 HTML へ一括生成する。

出力は **HTML のみ**。原稿を読者別に振り分け、
1 プロジェクトにつき最大 2 枚のライトモード HTML を生成する（`md2html.build_project`）:

  - `docs/<proj>/<proj>_手引き.html` … audience=guide（操作手順書。読者=オペレータ/利用者）
  - `docs/<proj>/<proj>_設計.html`   … audience=spec（設計正典・設計書・デプロイ運用手順書・
    仕様一覧。読者=エンジニア）

Mermaid 図の描画は `docs/_build/vendor/mermaid.min.js`（あれば）を HTML へインラインして行う。

使い方:
  python docs/_build/build_all.py                 全プロジェクト
  python docs/_build/build_all.py --project editor 指定プロジェクトのみ
"""
from __future__ import annotations

import argparse
import pathlib
import sys

import md2html

DOCS = pathlib.Path(__file__).resolve().parents[1]   # <repo>/docs
SKIP_DIRS = {"_build", "_samples"}


def discover_projects():
    """`docs/<project>/src/` を持つプロジェクトディレクトリを列挙する。"""
    for proj in sorted(DOCS.iterdir()):
        if not proj.is_dir() or proj.name in SKIP_DIRS:
            continue
        if (proj / "src").is_dir():
            yield proj


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", help="対象プロジェクト名（docs 直下のフォルダ名）")
    args = ap.parse_args(argv)

    warnings: list[str] = []
    built = failed = 0
    for proj in discover_projects():
        if args.project and proj.name != args.project:
            continue
        try:
            for out_path in md2html.build_project(proj, warnings=warnings):
                built += 1
                print(f"  [ok] {proj.name}/{out_path.name}")
        except Exception as exc:  # noqa: BLE001 - 1 プロジェクトの失敗で全体を止めない
            failed += 1
            print(f"  [NG] {proj.name}: {exc}")

    print(f"\n生成 {built} 件" + (f" / 失敗 {failed} 件" if failed else ""))
    if warnings:
        print("警告:")
        for w in warnings:
            print(f"  - {w}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
