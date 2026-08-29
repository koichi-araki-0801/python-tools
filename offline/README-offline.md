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

`setup_offline.py` は次の 7 手順を **この順序で** 実行する。順序そのものが検証の一部であり、
入れ替えると成立しなくなる箇所がある(理由は各項目末尾に記す)。

1. **pin 読込・公開鍵存在確認** — どちらか欠落・形式不正なら即座に中止する(fail closed)。
2. **Release からバンドル本体(.tar.gz)と分離署名(.sig)を取得** — `gh` CLI が認証済みなら
   private のリポジトリのまま取得できる(公開窓は不要)。`gh` が使えない/未認証なら無認証
   HTTPS の Release アセット直 URL へフォールバックする(この経路は下記「一時 Public 化」が
   前提)。
3. **バンドルの sha256 を標準ライブラリ `hashlib` だけで pin と照合**(主アンカー)。まだ
   展開しておらず、まだ `cryptography` も要らない段階で行う。これが一致しなければ改ざん・
   取得ミスとして即座に中止し、以降の手順(展開)には一切進まない。
4. **展開**(`python-wheelhouse/` / `docs/_build/vendor/`)。
5. **wheelhouse から `cryptography` を `pip install --no-index --find-links` で導入**
   (`check_requirements` によるファイル形式検査を経てから pip を呼ぶ)。
6. **Ed25519 分離署名を検証**(多層防御)。手順3の sha256 照合は「pin に書かれた値と一致
   するか」しか見ないが、署名検証は「秘密鍵の所持者が作った内容か」まで確かめる、一段強い
   根拠になる。**失敗したら、たとえ手順3を通っていても手順4で展開済みの内容を信用せず削除し、
   非ゼロ終了する。**
7. **pin の source-zip-sha256 を、pin の source-commit のアーカイブ(codeload)を取得して
   照合する**(追加確認)。ソースコード自体は展開しない(手元の git checkout とは独立の経路で
   「公開時に生成された pin」と GitHub 上の実体が食い違っていないかを確かめるだけ)。

手順3(sha256)が手順5(`cryptography` 導入)より前にあるのは**鶏卵問題を避けるため**である。
Ed25519 署名の検証には `cryptography` が要るが、その `cryptography` 自体はこのバンドルの
wheelhouse にしか無い(配布先には未導入の状態で届く)。そこで「`cryptography` が無くても
判定できる sha256 照合」を主アンカーとして先に置き、`cryptography` を導入した後で初めて
署名検証(多層防御)を行う、という 2 段構えにしている。この理由により
`offline/lib/bundle_common.py` の署名系関数(`generate_signing_key_pair` /
`sign_bytes` / `verify_signature_bytes`)は `cryptography` を **モジュール冒頭ではなく
関数内で遅延 import** している。モジュール冒頭で import すると、`cryptography` がまだ無い
配布先での手順1-4の実行自体が import エラーで止まってしまうためである。

## 一時 Public 化(gh 未認証環境向けフォールバック)の運用

- **gh CLI が認証済みの環境では、一時 Public 化は不要**である。手順2(バンドル取得)・
  手順7(source zip 追加確認)とも `gh` を優先し、認証済みなら private のまま完結する。
- gh 未認証の環境(configured されていない別端末等)だけが無認証 HTTPS フォールバックを
  使い、そのときだけリポジトリの一時的な Public 公開が必要になる。手順は次のとおり:
  1. リポジトリ管理者の端末で `gh repo edit koichi-araki-0801/python-tools --visibility
     public --accept-visibility-change-consequences` を実行する。
  2. 配布先で `offline\setup-offline.bat` を実行する(手順2・手順7 とも無認証 HTTPS
     経路を通る)。
  3. 完了を確認したら、必ず `gh repo edit koichi-araki-0801/python-tools --visibility
     private --accept-visibility-change-consequences` で Private へ戻す。
- **`publish_bundle.py` 自体も pin 生成(手順7で照合する source-zip-sha256 の算出)のために
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

手順7(source zip の追加確認)は、GitHub REST API の `zipball` エンドポイント
(`gh api repos/<owner>/<repo>/zipball/<sha>`)ではなく、**`codeload.github.com` を
`gh auth token` のトークンを `Authorization` ヘッダへ載せて直接叩く**実装になっている
(`default_gh_authenticated_source_zip_download`)。理由は、REST API の `zipball`
エンドポイントと `codeload.github.com` が別経路で、生成される zip がバイト単位で一致しない
ことを実機で確認したため(同一コミットで sha256 が食い違った)。pin の
`source-zip-sha256` は `publish_bundle.py` が `codeload.github.com` から取得した値
なので、setup 側も同じエンドポイントを叩かなければ照合が成立しない。無認証時のフォール
バック(`https://github.com/<owner>/<repo>/archive/<sha>.zip`)は codeload への
リダイレクトを経由するため、こちらは元から同じバイト列になる。

## 配布検証の実測記録

`%TEMP%` の新規 `git clone` から次の順で確認した:

1. `offline\setup-offline.bat` → `setup-dev.bat` → `py -3.13 -m pytest pdf-to-svg -q`
   が緑(285 passed)であることを確認した。
2. 改ざん検出: 取得したバンドルの 1 byte を書き換えたコピーで `verify_bundle_sha256`
   を直接呼び、pin との不一致により `RuntimeError` が送出され、展開(手順4)に進まない
   ことを確認した。
3. ログ順序: `setup-offline.bat` の実行ログで `[3/7]`(sha256 照合)が `[5/7]`
   (`cryptography` 導入)より前に出力されることを確認した。

初回 publish(`py -3.13 offline\publish_bundle.py --force`)の実測:

- バンドルサイズ: 約 74 MB(`offline-deps-bundle.tar.gz` 77,622,542 bytes)。
- 所要時間: 約 26 秒(wheelhouse はキャッシュ済み wheel の再収集)。
- 一時 Public 化の窓: 数秒程度(visibility 切替 × 2 回 + source zip 取得(約 22MB)の
  合算。上記「GitHub 側のレート制限」の実測時に個別計測した内訳は、public 化に約 1 秒、
  ソース zip 取得(約 22MB)に約 1.5 秒、private への復帰に約 1 秒)。

## 触る前のチェックリスト

1. `setup_offline.py` のブートストラップ順序(1-7)を変更する? → 「鶏卵問題」の節を
   再読し、sha256 照合が `cryptography` 導入より前であることを保つこと。
2. `publish_bundle.py` / `setup_offline.py` の gh 呼び出しを変更する? → `gh api` の
   `zipball` エンドポイントと `codeload.github.com` はバイト単位で一致しない(上記参照)。
   新しい取得経路を足す場合は、pin の `source-zip-sha256` を算出した経路
   (`publish_bundle.download_source_zip`)と同じエンドポイントを使うこと。
3. 一時 Public 化を伴う操作を追加する? → 直前の操作から十分な間隔を空けるか、
   `gh repo view --json visibility` での事後確認を必須にすること。
4. 検証は `py -3.13 -m pytest scripts -q` + `py -3.13 scripts\check_comments.py`。
