# offline 重量物の取得と展開

`python-tools` の Python 依存(wheel)と docs ビルド用 JS(mermaid)は git に入れず、GitHub Releases
(タグ `offline-bundle-v1`)の `offline-deps-bundle.tar.gz` として配布する。ソースコードは `git clone` で
受け取る。

## 重量物の内訳(Release のアセット offline-deps-bundle.tar.gz に同梱)

- `python-wheelhouse/` … 追跡中の各 `requirements.txt` の wheel(cp313 固定)
- `docs/_build/vendor/mermaid.min.js` / `mermaid-layout-elk.min.js` … docs の Mermaid 描画ランタイム

同じ場所の `bundle.key` は、そのバンドルがどの `requirements.txt` / `docs/_build/vendor/manifest.txt` から
作られたかを示す content-key。setup はこれと手元のソースを突き合わせる。

## 手順(他端末)

1. リポジトリを clone する: `git clone https://github.com/koichi-araki-0801/python-tools.git`
2. `offline\setup-offline.bat` を実行する。次を全自動で行う:
   - リポジトリ直下(または `bk\`)に `offline-deps-bundle.tar.gz` と `bundle.key` があればそれを使い、
     無ければ Release から HTTPS で直取得する(`gh` 不要)。取得したときは Release の `.sha256` で
     転送破損を検査する
   - **展開の前に** `bundle.key` と手元のソースの content-key を突き合わせる(不一致は中止)。
     展開の後に測ると、バンドル同梱の `manifest.txt` が git 管理下の実体を上書きし、
     manifest だけの差分を検知できなくなるため
   - 展開する(`python-wheelhouse/` と `docs/_build/vendor/` の JS 2 件)
3. 続けて `setup-dev.bat` を実行し、wheelhouse から開発依存を導入する。

ネットに出られない端末では、別の端末で Release から `offline-deps-bundle.tar.gz` と `bundle.key` を
落としてリポジトリ直下へ置いてから実行する。

## 重量物の更新(配布担当の端末のみ)

生成と Release への upload は git 管理外の `local-only\offline-publish\publish-bundle.bat` で行う
(配布担当の端末にだけある)。追跡中の `requirements.txt` か `docs/_build/vendor/manifest.txt` を変えて
push したら、忘れずに実行する。実行を忘れると、他端末の setup は content-key 不一致で止まる
(黙って古い重量物を使うことはない)。コミットフックからは何も自動実行しない。

## 前提と受け入れているリスク

- Release のアセットのすり替えは検出しない。`.sha256` は Release と同じ場所にあるので転送破損の
  検知にしか使えない。Release を更新できるのはリポジトリ所有者だけで、配布先は同じ所有者の
  Public リポジトリを clone している前提で受け入れる。
- ソースと重量物の整合は content-key(`bundle.key`)で担保する。

## トラブルシュート

- 「手元のソースと重量物が対の組ではありません」で止まる
  → 配布担当に `publish-bundle.bat` の実行を依頼する。または `bundle.key` に対応するコミットへ
    checkout し直す。
- ダウンロードが 404
  → タグ名(`--tag`)とリポジトリの公開状態を確認する。
