# オンライン構築への移行設計

## 背景

本リポジトリの構築経路は「オフラインで組み立てられること」を要件として設計されている。

- `offline/setup-offline.bat` が GitHub Releases(タグ `offline-bundle-v1`)から
  `offline-deps-bundle.tar.gz`(約 73MB)を取得し、`bundle.key` と手元のソースの content-key を
  突き合わせてから `python-wheelhouse/` と `docs/_build/vendor/` へ展開する。
- `setup-dev.bat` は `python-wheelhouse/` の不在を fail-closed で拒否し、
  `pip install --no-index --find-links python-wheelhouse` で依存を導入する。
  オンライン導入は `--online` の明示 opt-in でしか行わない。
- exe ビルド用の隔離 venv(`scripts/lib/build_venv.py`)も wheelhouse 必須で、オンラインへの
  フォールバックを意図的に持たない。
- 重量物の生成と Release への公開は、配布担当の端末にだけある git 管理外の
  `local-only/offline-publish/` が担う。

この要件を取り下げ、オンライン構築を前提とする設計へ移行する。

## 目的

構築経路を PyPI の直参照へ一本化し、バンドルの生成・公開・content-key 照合という保守を無くす。
構築に必要な操作は「clone して `setup-dev.bat` を実行する」だけにする。

## 決定事項

利用者との確認により、次を決定済みとする。

1. オフライン構築の資産は完全撤去する。`offline/` 一式を削除し、`--no-index` による
   wheelhouse からの導入経路を残さない。`setup-dev.bat` の `--online` フラグも、
   既定がオンラインになるため廃止する。
2. docs の mermaid ランタイム 2 ファイルは git へ入れず、GitHub Releases の新タグへ
   tar.gz 1 個として置き、`setup-dev.bat` が自動取得する。取得失敗は警告して続行する。
3. exe ビルド用の隔離 venv もオンライン化する。wheelhouse 必須の fail-closed は撤去する。
4. 手元にある git 管理外の重量物(`python-wheelhouse/`・`offline-deps-bundle.tar.gz` と
   その `.sha256` / `.sig`・`bundle.key`・`local-only/offline-publish/`)を削除する。

## 非目標

- requirements の形式検査(`scripts/check_requirements.py`)は緩めない。オプション行・直 URL 参照・
  ローカルパスの拒否は、pip の解決先そのものを差し替えられることへの防御であり、
  索引をオンラインにするほど効き目が要る。検査を経ない pip 入口を作らない規律も維持する。
- monorepo(`C:\Users\caads\workspace`)と対で保守する範囲は据え置く。monorepo はオフライン運用を
  続けるため、`docs/コメント規約.md` の `.ps1` docstring 例示(`offline-bundle-v1` を含む)と
  `scripts/check_comments.py` の `REPO_CONFIGS["workspace"]` は変更しない。
- mermaid 自体の版は上げない。現行の 11.12.2 / layout-elk 0.2.2 をそのまま Release へ移す。

## 設計

### A. 依存の導入経路

`scripts/setup_dev.py`

- `WHEELHOUSE` 定数・`check_wheelhouse()`・`--online` 引数を削除する。
- `pip install` から `--no-index --find-links` を外し、requirements を PyPI から導入する。
- requirements の動的列挙(`git ls-files -z -- '*requirements.txt'`)と形式検査は維持する。
- 新工程として docs vendor の取得(下記 B)を呼ぶ。失敗しても続行する。
- 完了サマリの「導入元」表示をオンライン固定の表現へ改める。

`scripts/lib/build_venv.py`

- `require_wheelhouse()` を削除し、`build_venv()` の `wheelhouse_dir` 引数を落とす。
- install は `pip install -r <requirements>` のみとする。`assert_requirements_file()` の
  呼び出しは維持する(pip 入口ごとに検査するという規律は変えない)。
- docstring の「wheelhouse 必須・オンライン fallback を意図的に落とす」という趣旨の記述を、
  オンライン導入前提の記述へ書き換える。

`graph-editor/scripts/build.py` / `pdf-to-svg/scripts/build.py`

- `WHEELHOUSE` 定数と `build_venv()` への引数渡しを削除する。docstring も併せて改める。

`docs/_build/build_all.bat`

- `python-wheelhouse` の存在で分岐する `if exist` を削除し、常に `pip install -q -r` とする。
- 冒頭コメントからオフライン前提の記述を落とす。`check-requirements.bat` の先行呼び出しは残す。

`docs/_build/requirements.txt` / `docs/_build/md2html.py`

- 「オフライン時は同梱 python-wheelhouse から」という趣旨のコメントを現状へ合わせる。

### B. docs の mermaid ランタイム取得(新設)

新規 `scripts/fetch_docs_vendor.py` を追加する。`.bat` ランチャは設けない
(`setup-dev.bat` から呼ばれるのが通常の入口で、単独実行は `py -3.13 scripts\fetch_docs_vendor.py`)。

**取得先**

- 所有者・リポジトリ名はソース内の定数(`koichi-araki-0801` / `python-tools`)とする。
  `git remote` から導出しない。remote は clone 元によって動くため、そこから取得先 URL を
  組み立てると、fork やミラーから clone した端末が別の配布物を掴む。
- タグは `docs-vendor-v1`(ローリング)、アセットは `docs-vendor.tar.gz` の 1 件。
- URL は `https://github.com/<owner>/<repo>/releases/download/<tag>/docs-vendor.tar.gz`。
  `gh` コマンドには依存せず `urllib.request` で取得する。

**正典は `docs/_build/vendor/manifest.txt`**

manifest は git 管理下にあり、ファイル名と sha256 を持つ。取得したアセットが正しいかは
これと突き合わせて判定する。Release に併置する `.sha256` サイドカーは、アセットと同じ場所に
あるため転送破損の検知にしかならず、追加しない。

manifest のパーサは、`#` で始まらない有意行を空白区切りで読み、先頭トークンをファイル名、
`sha256=` で始まるトークンを期待ハッシュとして拾う。`version=` / `source=` のような他のトークンは
無視する(将来トークンが増えても壊れない)。

**手順**

1. manifest を読み、期待する(ファイル名, sha256)の集合を得る。
2. `docs/_build/vendor/` の既存配置が全件一致していれば、取得せずに成功として返す
   (毎回の `setup-dev.bat` で 4MB を落とさない)。
3. tar.gz を一時ディレクトリへ取得する。
4. tar のメンバを検査する。manifest に載る名前と完全一致する通常ファイルだけを許可し、
   それ以外(ディレクトリ・シンボリックリンク・絶対パス・`..` を含む名前・未知のファイル名)を
   1 件でも含むなら中止する。展開には `filter="data"` も併用する。
   許可リストで名前を照合する形にしておけば、tar の展開先を外へ逃がす経路が構造的に生じない。
5. 一時ディレクトリへ展開し、各ファイルの sha256 を manifest と突き合わせる。
6. **全件一致したときにだけ** `docs/_build/vendor/` へ配置する。
   1 件でも不一致・不足があれば既存の配置物に触れずに失敗を返す。不一致のときに古い配置を
   消してしまうと、それまで揃っていた vendor を失うだけで何も得られない。
7. どの段階の失敗でも、既存の配置物は変更しない。

**失敗時の扱い**

vendor は docs の HTML ビルドだけが要る依存で、`md2html.py` は未配置時に
`<pre class="mermaid">` へフォールバックし警告を積む経路を既に持つ。したがって取得失敗は
セットアップ全体の失敗とはしない。

- `setup_dev.py` から呼ぶ経路: 失敗しても警告を出して続行し、セットアップは成功で終える。
- 単独実行(`main()`)の経路: 明示的な取得操作なので、失敗は終了コード 1 とする。

**Release への公開手順**

mermaid の版を差し替えるときの手順を README に記載する。自動化スクリプトは設けない
(頻度が年単位で低く、`gh release upload` と sha256 の書き戻しで足りるため)。

```
tar -czf docs-vendor.tar.gz -C docs/_build/vendor mermaid.min.js mermaid-layout-elk.min.js
gh release upload docs-vendor-v1 docs-vendor.tar.gz --clobber
```

tar の中身はフラット(ディレクトリを含まず、2 ファイルが直下)とする。manifest のファイル名と
tar のメンバ名がそのまま対応し、取得側の許可リスト照合が単純な集合比較で済む。
併せて `docs/_build/vendor/manifest.txt` の sha256 を新しい実体の値へ更新し、コミットする。
manifest を更新し忘れると、他端末の取得は sha256 不一致で配置されず警告が出る
(黙って古い実体や差し替えられた実体を使うことはない)。

### C. 撤去

git 追跡下から削除するもの。

- `offline/README-offline.md`
- `offline/lib/bundle_common.py`
- `offline/setup-offline.bat`
- `offline/setup_offline.py`

`.gitignore` から削除する行。

- `python-wheelhouse/`
- `offline-deps-bundle.tar.gz*`
- `bundle.key`

`docs/_build/vendor/mermaid.min.js` と `mermaid-layout-elk.min.js` の 2 行は残す
(引き続き git 管理外で Release から取得するため)。`local-only/` の行も残す
(`local-only/archive-github-dist/` が残るため)。

`scripts/check_comments.py` の `REPO_CONFIGS["python-tools"]` から、
`skip_dir_names` と `ps1_skip_dir_names` の `python-wheelhouse` を外す
(当該ディレクトリが存在しなくなるため)。`REPO_CONFIGS["workspace"]` は触らない。

作業ディレクトリから削除するもの(いずれも git 管理外のため git では復元できない)。

- `python-wheelhouse/`(約 70MB)
- `offline-deps-bundle.tar.gz` と `offline-deps-bundle.tar.gz.sha256` /
  `offline-deps-bundle.tar.gz.sig`
- `bundle.key`
- `local-only/offline-publish/`

### D. テスト

`scripts/test_python_tools_scripts.py` から削除するもの。

- `offline` / `offline/lib` への `sys.path` 追加と `bundle_common` / `setup_offline` の import。
- `bundle_common` の全テスト(requirements 列挙の 2 経路一致・content-key・`bundle.key` 読み書き・
  tar コマンド組み立て・vendor アセット検査)。
- `setup_offline` の全テスト(手元バンドル探索・Release 取得・sha256 サイドカー照合・
  main のフロー・展開・content-key 照合)。
- `build_venv.require_wheelhouse` の 2 テスト。
- `setup_dev.check_wheelhouse` の 3 テスト。

書き換えるもの。

- `build_venv.build_venv` のテストを新しいシグネチャ(wheelhouse 引数なし)へ合わせ、
  pip 呼び出しに `--no-index` が含まれないことを確認する。

新規に書くもの(TDD で先に書く)。`scripts/test_python_tools_scripts.py` へ追加する。

- manifest のパース。`version=` / `source=` の混在した現行の書式から名前と sha256 を拾えること。
  コメント行と空行を無視すること。
- 既存配置が全件一致していれば取得を呼ばずに成功すること。
- sha256 が 1 件でも不一致なら失敗を返し、**既存の配置物を変更しない**こと。
- tar が manifest に無い名前のメンバを含むとき、絶対パスや `..` を含むメンバを含むとき、
  通常ファイルでないメンバを含むときに、展開せず失敗すること。
- ネットワーク取得の失敗(例外)を握って失敗を返し、例外を呼び出し側へ抜けさせないこと。
- 全件一致したときに `docs/_build/vendor/` へ 2 ファイルが配置されること。

HTTP 取得はテストから注入できる形にする(`setup_offline.download_release_assets` が
`http_download` を引数で受けていたのと同じ手口)。テストは実ネットワークへ出ない。

### E. ドキュメント

- `README.md`: 冒頭の「オフライン配布対応」を改める。セットアップ節の手順 2 と 3 を
  オンライン導入へ書き換え、「オフライン重量物の取得」節を mermaid ランタイムの取得と
  Release への公開手順の節へ差し替える。
- `docs/_build/vendor/manifest.txt`: 冒頭の説明を「offline 重量物バンドル同梱」から
  「Release `docs-vendor-v1` の `docs-vendor.tar.gz` として配布し、`setup-dev.bat` が取得する」へ改める。
- `docs/graph-editor/src/設計書.md` と `docs/pdf-to-svg/src/設計書.md`: ビルド節の
  「オフライン優先・共有 wheelhouse 使用」の記述を現状へ合わせる。
- `.github/workflows/ci.yml`: `scripts` のテスト内容を説明するコメントから
  「offline の setup」への言及を落とす。CI の install 手順自体は既に PyPI からのため変更しない。
- `CLAUDE.md`(git 管理外): `.bat` ランチャ規約の雛形列挙から `offline/setup-offline.bat` を外す。

## 受け入れ基準

1. `git grep -niE "offline|wheelhouse"` が、monorepo と対で保守する範囲
   (`docs/コメント規約.md` の `.ps1` 例示・`check_comments.py` の `workspace` 設定・
   `check_requirements.py` の `is_offline_requirement_line` という関数名とその由来コメント)
   以外に該当しない。
2. `py -3.13 -m pytest scripts` が全通過する。
3. `py -3.13 -m pytest docs/_build` / `pdf-to-svg` / `graph-editor` が全通過する
   (4 ディレクトリを個別に実行する)。
4. `py -3.13 scripts\check_comments.py` が通る。
5. `python-wheelhouse/` が無い状態で `setup-dev.bat` が最後まで通り、依存が導入される。
6. Release がまだ存在しない状態でも、vendor 取得の失敗が警告に留まり `setup-dev.bat` が成功する。

## 残作業(実装のスコープ外)

`docs-vendor-v1` タグと `docs-vendor.tar.gz` の作成・公開は、リポジトリ所有者が
GitHub 上で行う必要がある。実装完了時点では取得先が 404 になるため、
受け入れ基準 6 の経路(警告して続行)で動作する。公開後に取得が成功へ変わる。
