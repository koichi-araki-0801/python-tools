# offline 重量物バンドルの配布・運用手順

`python-tools` の Python 依存(wheel)と docs ビルド用 JS(mermaid)は git に入れず、
GitHub Releases(ローリングタグ `offline-bundle-v1`)へ別配布する。本書は配布物の作成
(publish)・取得(setup)・両者を成立させている検証の仕組みと、運用上の残余リスクをまとめる。

## 全体像

- 公開元(開発機)は `offline\publish_bundle.py` で重量物バンドル
  (`python-wheelhouse/` + `docs/_build/vendor/`)を tar.gz へ固め、Ed25519 で署名して
  GitHub Releases へ upload する。同時に `offline\pinned-release.txt`(pin)を生成する。
- 配布先(取得機)は `offline\setup-offline.bat`(= `setup_offline.py`)で pin と公開鍵
  (`offline\bundle-signing.pub.pem`)だけを真正性の根拠として、Release から重量物を取得・
  検証・展開する。**pin と公開鍵は `offline/` フォルダごと手渡しで(= リポジトリのコミット
  として)配布先へ運ぶ前提**であり、いずれも欠けていれば setup は起動直後に中止する。
- ソースコード自体(python-tools リポジトリ本体)は `git clone` 等の別経路で配布先へ渡る
  前提である。`setup_offline.py` はソースを取得・展開しない(重量物だけを対象にする)。

## setup のブートストラップ順序(検証連鎖)

`setup_offline.py` は次の 8 手順を **この順序で** 実行する。順序そのものが検証の一部であり、
入れ替えると成立しなくなる箇所がある(理由は各項目末尾に記す)。

1. **pin 読込・公開鍵存在確認** — どちらか欠落・形式不正なら即座に中止する(fail closed)。
2. **Release からバンドル本体(.tar.gz)・分離署名(.sig)・`bundle.key` を取得** — `gh` CLI
   が認証済みなら private のリポジトリのまま取得できる(公開窓は不要)。`gh` が使えない/
   未認証なら無認証 HTTPS の Release アセット直 URL へフォールバックする(この経路は下記
   「一時 Public 化」が前提)。
3. **バンドルの sha256 を標準ライブラリ `hashlib` だけで pin と照合**(主アンカー)。まだ
   展開しておらず、まだ `cryptography` も要らない段階で行う。これが一致しなければ改ざん・
   取得ミスとして即座に中止し、以降の手順(展開)には一切進まない。
4. **展開の前に**、手元のソースが重量物と対の組であることを `bundle.key` で確認する。
   ローカルの content-key(`bundle_common.compute_content_key`。`publish_bundle.py` が
   公開時に算出するものと同一ロジック)を計算し、手順2で取得した `bundle.key` と比較する。
   これは「取得したバンドル自体が正しいか」ではなく「**手元の git checkout
   (requirements.txt / `docs/_build/vendor/manifest.txt` 等)が pin と対応する重量物と
   組み合っているか**」を確かめる検査で、pin より新しいコミットへ進んだ作業ツリーで
   setup を実行した場合に、ここで早期に気づける(無ければ手順自体は全部緑のまま通り、
   後続の `setup-dev.bat` が `--no-index` の解決失敗という分かりにくい形で初めて症状が
   出る)。**必ず展開より前に行う(I-3)**: `docs/_build/vendor/manifest.txt` は git 追跡下の
   ファイルで clean clone に必ず存在するため展開前でも算出できる一方、展開の**後**に
   測ると、バンドル自身が同梱する manifest.txt が git 管理下の実体を上書きしてしまい、
   以後の算出は「バンドル自身の manifest」対「バンドルの bundle.key」という堂々巡りの
   比較になって manifest だけの差分を構造的に検知できなくなる(旧実装で実際に発生した
   バグ)。
5. **展開**(`python-wheelhouse/` / `docs/_build/vendor/`)。手順4の照合を通過した組み合わせ
   だけを展開する(手順4の不一致は展開前に中止するため、その時点で削除すべき展開物は
   通常残らない)。手順7の署名検証失敗は、展開済みの内容
   (`python-wheelhouse/` と vendor の JS 2 件。`docs/_build/vendor/manifest.txt` は
   git 管理下なので残す)を削除してから非ゼロ終了する。
6. **wheelhouse から `cryptography` を `pip install --no-index --find-links` で導入**
   (`check_requirements` によるファイル形式検査を経てから pip を呼ぶ。**対象は
   `offline/dev-requirements.txt`**。`cryptography` 1 件を含む最小構成)。**このリポジトリは
   per-repo の venv を持たず、`py -3.13` のグローバル環境へ直接導入する**(`setup_dev.py`
   の requirements 導入と同じ流儀)。
7. **Ed25519 分離署名を検証**(多層防御)。手順3の sha256 照合は「pin に書かれた値と一致
   するか」しか見ないが、署名検証は「秘密鍵の所持者が作った内容か」まで確かめる、一段強い
   根拠になる。**失敗したら、たとえ手順3を通っていても手順5で展開済みの内容を信用せず削除し、
   非ゼロ終了する。** ただし **手順6で `py -3.13` のグローバル環境へ導入済みの
   `cryptography` パッケージ自体はこの削除対象に含まれない**(署名未検証の wheelhouse から
   導入したものが site-packages に残る)。エラーメッセージにも表示されるとおり、気になる
   場合は `py -3.13 -m pip uninstall -y cryptography` を手動で実行すること。
8. **pin の source-zip-sha256 を、pin の source-commit のアーカイブ(codeload)を取得して
   照合する**(追加確認)。ソースコード自体は展開しない(手元の git checkout とは独立の経路で
   「公開時に生成された pin」と GitHub 上の実体が食い違っていないかを確かめるだけ)。

手順3(sha256)が手順6(`cryptography` 導入)より前にあるのは**鶏卵問題を避けるため**である。
Ed25519 署名の検証には `cryptography` が要るが、その `cryptography` 自体はこのバンドルの
wheelhouse にしか無い(配布先には未導入の状態で届く)。そこで「`cryptography` が無くても
判定できる sha256 照合」を主アンカーとして先に置き、`cryptography` を導入した後で初めて
署名検証(多層防御)を行う、という 2 段構えにしている。この理由により
`offline/lib/bundle_common.py` の署名系関数(`generate_signing_key_pair` /
`sign_bytes` / `verify_signature_bytes`)は `cryptography` を **モジュール冒頭ではなく
関数内で遅延 import** している。モジュール冒頭で import すると、`cryptography` がまだ無い
配布先での手順1-5の実行自体が import エラーで止まってしまうためである。

## 一時 Public 化(gh 未認証環境向けフォールバック)の運用

- **gh CLI が認証済みの環境では、一時 Public 化は不要**である。手順2(バンドル取得)・
  手順8(source zip 追加確認)とも `gh` を優先し、認証済みなら private のまま完結する。
- gh 未認証の環境(configured されていない別端末等)だけが無認証 HTTPS フォールバックを
  使い、そのときだけリポジトリの一時的な Public 公開が必要になる。手順は次のとおり:
  1. リポジトリ管理者の端末で `gh repo edit koichi-araki-0801/python-tools --visibility
     public --accept-visibility-change-consequences` を実行する。
  2. 配布先で `offline\setup-offline.bat` を実行する(手順2・手順8 とも無認証 HTTPS
     経路を通る)。
  3. 完了を確認したら、必ず `gh repo edit koichi-araki-0801/python-tools --visibility
     private --accept-visibility-change-consequences` で Private へ戻す。
- **`publish_bundle.py` 自体も pin 生成(手順8で照合する source-zip-sha256 の算出)のために
  同じ一時 Public 化を自動で行う**(`temporarily_public_repo`)。事前に現在の visibility を
  確認し、既に public ならそのまま(何もしない)。private から public へ変えた場合のみ、
  `finally` で元(private)へ必ず戻し、戻ったことを再取得して検証する。復帰コマンド自体の
  失敗、または戻した後の visibility が一致しないことは、どちらも例外(`RuntimeError`)として
  非ゼロ終了する(握り潰さない)。

## 中断時は必ず visibility を確認すること

上記の自動復帰は `finally` ブロックで行われるため、**通常の例外や `Ctrl+C`
(`KeyboardInterrupt`)では確実に働く**。ただし次の場合は `finally` 自体が実行されず、
リポジトリが Public のまま残る可能性がある:

- プロセスの強制終了(タスクマネージャでの kill・電源断など)。
- OS 自体のクラッシュ・スリープ中のネットワーク切断でハングしたまま操作不能になった場合。

`publish_bundle.py` の実行を中断した場合、または実行後に応答が不審だった場合は、
**必ず** 次のコマンドで実際の visibility を確認すること:

```bat
gh repo view koichi-araki-0801/python-tools --json visibility
```

`"PUBLIC"` のままであれば、直ちに次のコマンドで Private へ戻す:

```bat
gh repo edit koichi-araki-0801/python-tools --visibility private --accept-visibility-change-consequences
```

### 実測で判明した追加の残余リスク: GitHub 側のレート制限

visibility の切り替えを短時間(数分以内)に連続して行うと、GitHub 側が
`HTTP 422: Failed to update visibility. A previous visibility change is still in
progress.` を返し、`gh repo edit --visibility` そのものが失敗することを実機で確認した。
この場合 `publish_bundle.py` の `_restore_repo_visibility` は例外を握り潰さず
`RuntimeError` を送出して非ゼロ終了する(設計どおりの fail closed)ため、**「復帰に
失敗した」こと自体は必ず気づける**。ただしこの失敗が起きた時点でリポジトリは Public の
ままなので、次の対応を行うこと:

1. 上記コマンドで visibility を確認する。`"PUBLIC"` のままであれば、
2. 数十秒〜数分待ってから(GitHub 側の変更処理が完了するのを待つ)、上記の Private への
   復帰コマンドを再実行する。
3. 復帰できたことを再度 `gh repo view` で確認する。

したがって **`publish_bundle.py` を短時間に連続実行しない**(特に `--force` を伴う本実行の
直後に、検証目的で再度 pin 生成相当の操作を行わない)ことを推奨する。やむを得ず連続実行する
場合は、必ず 1 回ごとに visibility の復帰を確認してから次を実行すること。

## setup 側の gh 認証 vs 無認証(source zip 取得の実装上の注意)

手順8(source zip の追加確認)は、GitHub REST API の `zipball` エンドポイント
(`gh api repos/<owner>/<repo>/zipball/<sha>`)ではなく、**`codeload.github.com` を
`gh auth token` のトークンを `Authorization` ヘッダへ載せて直接叩く**実装になっている
(`default_gh_authenticated_source_zip_download`)。理由は、REST API の `zipball`
エンドポイントと `codeload.github.com` が別経路で、生成される zip がバイト単位で一致しない
ことを実機で確認したため(同一コミットで sha256 が食い違った)。

pin の `source-zip-sha256` は `publish_bundle.py`(`download_source_zip`)が実際には
`https://github.com/<owner_repo>/archive/<sha>.zip` を無認証で取得して算出した値である
(**`codeload.github.com` を直接叩いているわけではない**)。この URL は
`codeload.github.com` への 302 リダイレクトを経由し、実機で最終的に得られるバイト列が
codeload 直叩きと一致することを確認済みである。つまり publish 側(`github.com/.../
archive/`)と setup の gh 認証パス(`codeload.github.com/.../zip/` 直叩き)は
**綴りの異なる 2 つの URL で同一実体を指している**。この対応関係を崩す変更(例えば
publish 側を `zipball` エンドポイントへ変える、setup 側を別のリダイレクト元へ変える)を
行うと、今回踏んだ「REST API zipball ≠ codeload」と同型の不整合が再発する
(`test_download_source_zip_uses_github_archive_url_matching_setup_side` /
`test_default_gh_authenticated_source_zip_download_uses_codeload_with_auth_header` の
2 テストが、それぞれの URL 形が変わっていないことを個別に固定している)。

## 配布検証の実測記録

`%TEMP%` の新規 `git clone` から次の順で確認した:

1. `offline\setup-offline.bat` → `setup-dev.bat` → `py -3.13 -m pytest pdf-to-svg -q`
   が緑(285 passed)であることを確認した。
2. 改ざん検出: 取得したバンドルの 1 byte を書き換えたコピーで `verify_bundle_sha256`
   を直接呼び、pin との不一致により `RuntimeError` が送出され、展開(手順5)に進まない
   ことを確認した。
3. ログ順序: `setup-offline.bat` の実行ログで `[3/8]`(sha256 照合)が `[6/8]`
   (`cryptography` 導入)より前に出力されることを確認した。

初回 publish(`py -3.13 offline\publish_bundle.py --force`)の実測:

- バンドルサイズ: 約 74 MB(`offline-deps-bundle.tar.gz` 77,622,542 bytes)。
- 所要時間: 約 26 秒(wheelhouse はキャッシュ済み wheel の再収集)。
- 一時 Public 化の窓: 数秒程度(visibility 切替 × 2 回 + source zip 取得(約 22MB)の
  合算。上記「GitHub 側のレート制限」の実測時に個別計測した内訳は、public 化に約 1 秒、
  ソース zip 取得(約 22MB)に約 1.5 秒、private への復帰に約 1 秒)。

## publish の前提条件(新規 publisher 端末での bootstrap)

`offline\publish_bundle.py` を実行する端末(publisher)は、次がすべて揃っていないと
成立しない。既に一度 publish したことがある端末では自明だが、**新規に publisher を
増やす場合は明示的な準備が要る**:

1. **HEAD が origin へ push 済みであること** — `assert_head_pushed` が最初に確認する
   (codeload は GitHub 上に存在するコミットしか返さないため)。
2. **署名鍵(Ed25519 秘密鍵 PEM)が手元にあること** — 既定パスは
   `%USERPROFILE%\.python-tools-signing\bundle-signing.key.pem`。無ければ
   `py -3.13 offline\new_signing_key.py` を **1 回だけ**実行して鍵ペアを作成する
   (`--signing-key` で別パスも指定できる)。
3. **公開鍵(`offline\bundle-signing.pub.pem`)がリポジトリにコミットされていること** —
   配布先はこのファイルだけを真正性の根拠にするため、`new_signing_key.py` が生成した
   公開鍵は必ずコミットする(秘密鍵は絶対にコミットしない)。
4. **`docs/_build/vendor/` に mermaid JS 2 件(`mermaid.min.js` /
   `mermaid-layout-elk.min.js`)+ `manifest.txt` が揃っていること(I-6)** — 次節参照。

### vendor JS の入手経路(I-6)

`docs/_build/vendor/` の mermaid JS 2 件は git 管理**外**(`.gitignore` 対象)で、
バンドルにだけ同梱される。`publish_bundle.py` はこの 2 件 + `manifest.txt` の存在を
`assert_vendor_assets_present` で検査してから重量物を組む(**検査は `pip download`
(74MB 級)より前に行う**。揃っていない端末で download を丸ごと無駄にしてから
失敗させないため)。**この検査自体は「無ければ setup-offline で展開してから publish
しろ」と案内するが、setup-offline は公開済みバンドルからしか JS を取得できないため、
真の初回(まだ Release が存在しない)ではこの案内だけでは足りない。** 新規 publisher
端末で vendor JS を用意する経路は 2 つ:

- **既に Release が存在する場合(通常の新規 publisher 端末)**: `offline\setup-offline.bat`
  を 1 回実行すれば、公開済みバンドルから `docs/_build/vendor/` へ展開される。
- **真の初回(Release がまだ存在しない)**: monorepo(`C:\Users\caads\workspace`)側の
  `docs/_build/vendor/` から `mermaid.min.js` / `mermaid-layout-elk.min.js` を
  手動でコピーする。**バージョンは `manifest.txt` の記載に一致させること**(食い違うと
  content-key が monorepo 側と一致せず、以後の変更検知が正しく働かない)。

## 運用上の注意点

- **`--tag-only` は post-commit フックからコミットのたび自動実行される**が、
  visibility の切り替え(一時 Public 化)は行わない。`should_skip_tag_only` が
  「重量物の更新が必要」と判定した場合は**タグも動かさず何もせず終了する**契約であり、
  重量物の再生成(= 下記「短時間に連続実行しない」対象の本実行)には `--force` または
  変更検知(content-key 不一致)が要る。したがって `--tag-only` の頻繁な自動実行と、
  下記のレート制限に関する注意は**別の話**であり、`--tag-only` 自体は連続実行しても
  visibility には触れない。
- **手順6(`cryptography` 導入)の対象は `offline/dev-requirements.txt`**
  (`cryptography` 1 件を含む最小構成。`setup-dev.bat` が導入する開発依存一式とは別物)。
- **requirements ファイル群と `docs/_build/vendor/manifest.txt` の編集は、次の publish と
  不可分**である。これらは content-key の算出対象なので、コメント 1 行の追記でも公開済みの
  `bundle.key`・pin と食い違い、配布先の setup が手順4で止まるようになる。編集する場合は
  同じ作業の中で `publish_bundle.py --force` を実行し、生成された pin をコミットすること。
- **publish はリポジトリ直下に 74MB 級の生成物を残す** — `offline-deps-bundle.tar.gz`
  (+ `.sha256` / `.sig`)と `bundle.key` は `.gitignore` 対象で git には入らないが、
  実ファイルとしてはディスクに残り続ける(次の publish で上書きされるまで)。作業ツリーの
  空き容量に注意すること。
- **I-4: pin 生成(手順)は Release 反映より先に行うが、pin ファイル自体のコミットは
  publisher が手動で行う契約**であり、`publish_bundle.py` は `offline/pinned-release.txt`
  を書き換えるだけでコミットまではしない。したがって **publish 実行直後 〜 pin を
  コミットするまでの間は、ローカルの pin ファイルと origin へ push 済みのコミットの
  対応関係が「未確定」の窓になる**(この間に別の publish を走らせたり、pin を
  コミットし忘れたまま次の作業へ進んだりしないこと)。`publish_bundle.py` の実行後は
  必ず表示される案内(`※ この pin ファイルをコミットしてください`)に従って
  `offline/pinned-release.txt` をコミットすること。

## 触る前のチェックリスト

1. `setup_offline.py` のブートストラップ順序(1-8)を変更する? → 「鶏卵問題」の節を
   再読し、sha256 照合(手順3)が `cryptography` 導入(手順6)より前であることを保つこと。
   手順4の内容キー照合(bundle.key)は hashlib だけで完結するので手順6より前に置ける
   (crypto を要求する変更を持ち込まないこと)。**手順4は必ず展開(手順5)より前**
   (I-3。展開後だと bundle 同梱の manifest.txt が git 管理下の実体を上書きし、
   manifest の差分を検知できなくなる)。
2. `publish_bundle.py` の main() の順序を変更する? → **pin 生成(`generate_pin`)は
   Release 反映(`sync_release`)より必ず先**(I-4。逆順だと pin 生成の失敗時に
   「新バンドル(Release)× 旧 pin」の不整合を配布してしまう)。**vendor 前提の検査
   (`assert_vendor_assets_present`)は `build_wheelhouse`(74MB の pip download)より
   必ず先**(I-6。揃っていない端末で download を無駄にしないため)。
3. `publish_bundle.py` / `setup_offline.py` の gh 呼び出しを変更する? → `gh api` の
   `zipball` エンドポイントと `codeload.github.com` はバイト単位で一致しない(上記参照)。
   新しい取得経路を足す場合は、pin の `source-zip-sha256` を算出した経路
   (`publish_bundle.download_source_zip`。実体は `github.com/.../archive/` 経由の
   codeload リダイレクト)と同一実体を指すエンドポイントを使うこと。
4. `_http_download` に新しい呼び出し元を足す? → `Authorization` ヘッダを載せる場合は
   `_NoAuthRedirectHandler` を経由する既定 opener(`_NO_AUTH_REDIRECT_OPENER`)を
   そのまま使うこと(自前で `urllib.request.urlopen` を直に呼ばない。ホスト変更を伴う
   リダイレクトでトークンが漏れる経路を作らないため)。
5. 一時 Public 化を伴う操作を追加する? → 直前の操作から十分な間隔を空けるか、
   `gh repo view --json visibility` での事後確認を必須にすること。
6. 検証は `py -3.13 -m pytest scripts -q` + `py -3.13 scripts\check_comments.py`。
   `bundle.key` 比較(手順4)を変更した場合は `%TEMP%` の新規 clone で
   `setup-offline.bat` を再実行し、content-key 一致が通ることまで確認する。
