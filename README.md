# python-tools

帳票図版の加工ツール群(`pdf-to-svg` / `graph-editor`)。Python 専用。

- `pdf-to-svg`: PDF から SVG への変換・辞書置換ツール(Edge シェル UI)。
  - 運用報告書の「当社のスチュワードシップ活動」の図だけを切り出してグレースケール SVG にする専用モードあり。
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
2. `git ls-files -- '*requirements.txt'` で動的に列挙した requirements 一式を
   PyPI から導入する。
3. docs の mermaid ランタイムを GitHub Releases から取得する(下記「docs の mermaid
   ランタイム」節)。取得できなくても警告に留めてセットアップは続行する。
4. `git config core.hooksPath scripts/hooks` — 下記「開発フロー」節の 3 フックを
   有効化する。

### docs の mermaid ランタイム

`docs/_build/vendor/` の `mermaid.min.js` / `mermaid-layout-elk.min.js`(合わせて約 4MB)は
git に入れず、GitHub Releases(タグ `docs-vendor-v1`)の `docs-vendor.tar.gz` として配布する。
`setup-dev.bat` が `scripts/fetch_docs_vendor.py` を呼んで取得し、git 管理下の
`docs/_build/vendor/manifest.txt` に書かれた sha256 と全件一致したときだけ配置する。
既に一致していれば取得しない。

取得できなくてもセットアップは成功で終わる。この 2 ファイルは docs の HTML ビルドだけが要る
依存で、未配置のときは mermaid 図が整形コード表示になる(`md2html.py` が警告を積む)。

`mermaid-layout-elk.min.js` は `@mermaid-js/layout-elk` を esbuild で単一 IIFE へ自前バンドル
したもので、CDN に同一物は無い。版を差し替えるときはリポジトリ所有者が次を行う。

```bat
tar -czf docs-vendor.tar.gz -C docs\_build\vendor mermaid.min.js mermaid-layout-elk.min.js
gh release upload docs-vendor-v1 docs-vendor.tar.gz --clobber
```

併せて `docs/_build/vendor/manifest.txt` の sha256 を新しい実体の値へ更新してコミットする。
更新を忘れると他端末の取得は sha256 不一致で配置されず警告が出る(黙って違う実体を使うことはない)。

## 開発フロー(Git hooks)

`scripts/hooks/`(sh シム + 同名 `.py` の対)に 3 フックを置く。有効化は上記セットアップの
手順4(`git config core.hooksPath scripts/hooks`)。

- **pre-commit**: ステージ済みファイルへコメント規約検査
  (`scripts/check_comments.py --staged`)を掛ける。
- **post-commit**: commit のたび次を**ベストエフォート**で実行する(失敗してもコミット
  自体は成立させる)。
  1. auto-push: 現在ブランチを upstream へ push する(force はしない。non-fast-forward で
     拒否された場合は警告を出すのみで、復旧は `git push --force-with-lease` を手動で行う)。
- **pre-push**: auto-push の `git push` を経由して**毎コミット同期的に**発火する。
  毎回次を順に実行し、1 つでも失敗すれば push を中止する:
  `pytest scripts` → `pytest docs/_build` → `pytest pdf-to-svg` → `pytest graph-editor` →
  `pytest pdf-to-svg -m e2e` → `pytest graph-editor -m e2e`。

  **実測(2026-08-29・全件緑の状態)**: 合計 **約 100 秒**(scripts 2.1s / docs/_build 0.6s /
  pdf-to-svg 39.3s / graph-editor 31.5s / pdf-to-svg e2e 9.7s / graph-editor e2e 16.8s)。
  想定していた 2-4 分より短く収まったため、e2e 2 種を pre-push から外す退避判断は
  **不要**と判断した(このまま維持する)。将来テストが増えて重くなった場合は、e2e 2 種を
  pre-push から外し `py -3.13 -m pytest <pdf-to-svg|graph-editor> -m e2e` による明示実行へ
  切り替える(その場合は本節と CI 実測の記録も更新すること)。

## CI(GitHub Actions)

`.github/workflows/ci.yml` は push / PR のたび ubuntu-latest + Python 3.13 で実行する:
requirements の形式検査(`check_requirements.py`)→ 6 requirements の pip install →
`playwright install --with-deps msedge` → `pytest scripts` / `pytest pdf-to-svg` /
`pytest graph-editor` / `pytest docs/_build`(既定収集。`browser` マーカーは含み `e2e` は
addopts で除外)。

## コメント規約

コメントの書き方は `docs/コメント規約.md` が唯一の正典。機械判定できる項目
(`.ps1` を持たない方針・レビュー所見番号の残存・装飾ボックスヘッダ有無)は
`scripts/check_comments.py` が検査する(単独実行も可):

```bat
py -3.13 scripts\check_comments.py
```
