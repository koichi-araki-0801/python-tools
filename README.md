# python-tools

帳票図版の加工ツール群(`pdf-to-svg` / `graph-editor`)。Python 専用・オフライン配布対応。

- `pdf-to-svg`: PDF から SVG への変換・辞書置換ツール(Edge シェル UI)。
- `graph-editor`(旧 LabelEditor): SVG ラベル・引出線の手動微調整ツール(Edge シェル UI)。
- `docs/`: 各ツールの設計書・操作手順書・移植対応表。
- `docs/_build/`: ドキュメント生成エンジン(Markdown → HTML)。

## 必要環境

- Windows + `py -3.13`(Python ランチャ経由で 3.13 系を起動できること)。
- Microsoft Edge(`pdf-to-svg` / `graph-editor` は Edge シェル UI が前提)。

## セットアップ

```bat
setup-dev.bat
```

行うこと:

1. `py -3.13` と Edge の存在確認。
2. `python-wheelhouse/`(オフライン wheel 置き場)の存在確認。既定は fail-closed —
   無ければ「先に offline\setup-offline.bat を実行してください」と表示して失敗する。
   ネットワーク接続がある環境でオンライン導入したい場合のみ `setup-dev.bat --online`
   を明示指定する。
3. `git ls-files -- '*requirements.txt'` で動的に列挙した requirements 一式を
   `pip install`(既定はオフライン wheelhouse から `--no-index --find-links`)。
4. `git config core.hooksPath scripts/hooks` — commit のたびステージ済みファイルへ
   コメント規約検査(`scripts/check_comments.py --staged`)を掛ける pre-commit フックを
   有効化する。

## コメント規約

コメントの書き方は `docs/コメント規約.md` が唯一の正典。機械判定できる項目
(`.ps1` を持たない方針・レビュー所見番号の残存・装飾ボックスヘッダ有無)は
`scripts/check_comments.py` が検査する(単独実行も可):

```bat
py -3.13 scripts\check_comments.py
```
