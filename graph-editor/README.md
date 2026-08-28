# SVG ラベル位置エディタ（デスクトップ版）

pie-chart が生成した円グラフ SVG を読み込み、**ラベル（文字）と引出線（leader）をマウスでドラッグして位置を微調整**し、修正版 SVG を保存するスタンドアロンのデスクトップアプリです。`LabelEditor.exe` をダブルクリックすると、Windows 標準の **Microsoft Edge がアプリ窓として開いて**編集できます（裏で小さなローカルサーバが動くだけで、ターミナル操作は不要）。

---

## 使う人向け（非エンジニア）

1. 受け取った **`LabelEditor.exe` をダブルクリック**して起動します。Microsoft Edge のアプリ窓が開きます。
   - **Windows 10 / 11 どちらでも追加インストールは不要**です（描画には Windows 標準の Microsoft Edge を使います）。
   - **単一の exe ファイル**なので、好きな場所に置いて構いません（付属フォルダは不要）。
2. 左上の **「開く…」** をクリックし、編集したい SVG ファイルを選びます（複数選択可）。
3. グラフが表示されます。**ラベルの文字を掴んでドラッグ**すると動かせます。
   引出線は、文字に追従して伸び縮みします。
4. さらに細かく調整したいときは、ラベルをクリックして選択し、出てくる丸い点をドラッグします。
   - 🟢 **緑＝引出線の先端**（文字側）
   - 🔵 **青＝折れ点**
   - 🟠 **橙＝根元**（円に接する側。基本は動かしません）
5. 右パネルで **引出線の表示/非表示**、**文字色（黒／白）** を切り替えられます。
   さらに **「行数」で 1 行／2 行を切り替え**、**「長体」スライダで文字を横方向に圧縮**できます（100〜70%）。
   - 行数を変えると、名前と「○○%」を 1 行にまとめる／2 行に分けるが切り替わります。
   - 長体は名前部分だけを横に縮め、高さと「%」部分は変えません。
6. キーボード：**矢印キー**で 1px ずつ、**Shift+矢印**で 10px ずつ移動。**Ctrl+Z** で元に戻す。
7. 調整できたら右上の **「保存…」** をクリックします。修正版 SVG が
   **ダウンロードフォルダに保存**されます（保存先の選択画面は出ません）。
   - 元のファイルは上書きされません。

> ヒント：元データを直接書き換えるツールではありません。あくまで「出来上がった SVG の見た目を手直しする」ための道具です。

---

## 開発者向け

### 構成

| ファイル | 役割 |
|---|---|
| `app.py` | 標準ライブラリの小さな HTTP サーバ（127.0.0.1）で `resources/web/` の `ui.html` と `lib/leader_geom.cjs` を配信し、Edge をアプリモードで起動・常駐管理。実行時の外部依存なし |
| `resources/web/` | Web 資産集約先（`pdf-to-svg` と同構成）。`ui.html`（画面骨格のみ・インライン JS なし）/ `styles.css` / `js/`（編集ロジック本体の ES モジュール群。`editor.js` が中核）/ `lib/leader_geom.cjs` |
| `resources/web/lib/leader_geom.cjs` | 引出線まわりの DOM 非依存な純粋関数（`clampPointToBox`/`parsePath`/`buildPath` 等）。`ui.html` と `pie-chart` 側の vitest 単体テストで同一実装を共有（UMD: ブラウザは global `LeaderGeom`、node は `module.exports`） |
| `requirements.txt` | 実行は標準ライブラリのみ。`pyinstaller`（ビルド時のみ） |
| `scripts\build.bat` | exe をワンクリックでビルド（`--onefile`、`resources/web/` 一式を同梱） |

pie-chart のレンダラ（`src/`）には一切依存しません。ブラウザエンジンも同梱せず、OS の Edge を使うため配布物は単一 exe（~10MB）です。

### 触りやすさマップ（どこから触るか / どこは慎重に）

初めての変更は 🟢 から着手し、🔴 はレビュー（またはペア作業）を挟むこと。

| ゾーン | 場所 | 理由 |
|---|---|---|
| 🟢 まず触ってよい | `js/constants.js`・`js/geom.js`・`js/utils.js`・`js/icons.js` | 定数・純粋関数・部品。影響が局所 |
| 🟢 | `lib/leader_geom.cjs` | DOM 非依存の純粋関数。vitest でテスト済み |
| 🟢 | `app.py` | コメントが厚く独立性が高い（ただし Edge 起動フラグと終了契機は設計正典の却下集を先に読む） |
| 🟡 注意 | `js/label-state.js`・`js/main.js` | DOM 同期・起動/heartbeat。テストが薄い |
| 🔴 レビュー必須 | `js/editor.js` | 描画スケジューラ（rAF + dirty フラグ）・`load()` の再入レース・undo/redo が同居する中核 |

### 開発実行

```bat
python -m pip install -r requirements.txt
python app.py
```

### exe をビルド

ブラウザエンジンを同梱しないため、**前提作業は不要**です（OS の Edge を使います）。

```bat
scripts\build.bat
```

`dist\LabelEditor.exe`（**単一ファイル・~10MB**）が生成されます。**この exe を配布**すれば、受け取った人は
Python も WebView2 も無しに、Windows 10 / 11 で起動できます（描画は Windows 標準の Edge）。

手動で実行する場合：

```bat
python -m PyInstaller --noconfirm --onefile --windowed --name LabelEditor ^
  --add-data "resources/web/ui.html;." ^
  --add-data "resources/web/styles.css;." ^
  --add-data "resources/web/js;js" ^
  --add-data "resources/web/lib/leader_geom.cjs;lib" ^
  app.py
```

### 仕組み（なぜ動くか）

- `app.py` は標準ライブラリの HTTP サーバで `ui.html` を `http://127.0.0.1:<空きポート>` に配信し、
  `msedge.exe --app=<URL>` でアプリ窓として開きます（端末標準の「管理された」既定プロファイル）。窓を閉じると
  （プロセス終了／`pagehide` の `/quit` ビーコン）サーバも終了します。Edge が見つからない場合は既定ブラウザで開きます。
  以前は隔離 `--user-data-dir` ＋ `--disable-gpu` で起動していましたが、VDI ではこの非標準構成で
  アプリ窓がクラッシュしたため廃止し、余計なフラグを付けない構成に変更しています。
- ファイルの開く/保存は、従来型 `<input type=file>`（開く）／ダウンロード（保存）を使います。
  File System Access API のネイティブピッカー（`showOpenFilePicker` / `showSaveFilePicker`）は VDI/リモート
  デスクトップの管理された Edge ではレンダラごとクラッシュするため使いません（`utils.js` の `hasFsAccess()` は
  常に `false`）。機能差は実質「保存先がダウンロードフォルダ固定」になる点のみです。ドラッグ＆ドロップでも開けます。
- pie-chart の生成 SVG はフォントを base64 で自己内包しているため、DOM に挿入するだけで実フォントのまま正確に表示されます（WYSIWYG）。
- 各ラベルは `<g class="label" data-name="…">{引出線 <path>?}{<text>}</g>` 構造。
  文字は `<text>` の `transform=translate` で動かし、保存時に座標へ焼き込みます。
  引出線は `<path d="M…L…">` の点列を直接編集します（先頭＝根元固定／末尾＝文字側）。
- 保存時に編集用の補助要素（ハンドル等）を取り除いた、クリーンな SVG を書き出します。
