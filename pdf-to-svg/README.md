# PdfToSvg

PDF を編集可能な **SVG** に変換し、非エンジニアでも

1. **表ヘッダの用語統一・翻訳**（「元の語 → 置換後の語」を辞書登録し、開くたび自動適用）
2. **不要箇所のトリミング**（要素の選択削除＋矩形クロップ）

を行えるデスクトップツール。Windows で **.exe** として社内配布する前提。

---

## 特長

- **ベクター忠実**: PyMuPDF でテキスト/罫線/図形を構造化抽出し、各要素を SVG のまま編集。
- **本物の `<text>`**: 書き出した SVG のテキストはテキストのまま（後から検索・再編集可）。
- **辞書**: JSON ファイルで永続化（exe 隣の `data\dictionary.json`、ポータブル・C 非依存）。NFKC 正規化で全角半角差を吸収。手編集・共有可。
- **スキャン対応**: 画像主体ページはラスタ背景として SVG に埋め込み（ページ単位のクロップ等が可能）。

---

## かんたん操作（バッチ・ダブルクリック）

コマンド不要。リポジトリ直下の .bat をダブルクリックするだけ。

| バッチ | 役割 |
|---|---|
| **`run.bat`** | アプリを起動（exe を作らずソースから手軽に動かす） |
| **`scripts\build.bat`** | 依存導入 + `dist\PdfToSvg\PdfToSvg.exe` を生成 |

## 動かし方（開発・コマンド）

```powershell
# 依存インストール
python -m pip install -e .            # もしくは pip install PyMuPDF Pillow fonttools brotli
# 起動
python run.py
```

## 基本操作（4 ステップ・ウィザード）

UI は OS 標準の **Edge をアプリモード**で開いて表示する Web UI（`resources/web/`）。複数 PDF を一括で扱い、
上部のステップバーに沿って 1→4 を進める。各ページは「要確認 / 確認済み / スキップ /
変更なし」の状態を持ち、未確認が残ると「次へ」で確認ガードバーが出る。

| ステップ | 内容 |
|---|---|
| **1. PDFを選ぶ** | ドロップゾーンをクリック→ファイル選択（複数可）。選んだ順に処理。 |
| **2. 用語を置換** | 左レールでページ移動、中央に実ページ、右「確認」タブで置換一覧（クリックで該当箇所をハイライト）。「辞書」タブで用語の追加・削除・再適用（ヘッダ・本文を問わず全文が対象。主ボタンは「このページのみ」、全ファイルは明示選択）。中央ページ上の文字をクリック 1 回で「元の語」へ取り込める（折返しセルは畳んで 1 文を一括取得＝`dictSuggest`）。 |
| **3. 不要範囲を削除** | 「選択」で要素をクリック選択→「削除」。「クロップ」で残す範囲をドラッグ（外側は書き出し時に破棄）。「クロップ解除」で取消。 |
| **4. SVGに書き出す** | 表示中ページのみ / 全ページ を選び書き出し（`元ファイル名_pN.svg`）。 |

元に戻す / やり直しは上部アイコンまたは Ctrl+Z / Ctrl+Y。

---

## アーキテクチャ

```
PDF → engine(PyMuPDF抽出 + vector/scan判定) → model(Document/Page/Element)
   → dictionary(NFKC正規化 + ヘッダ検出 + 自動適用)
   → export(model→SVG直接シリアライズ) ……出力 & 画面プレビュー
   ↑↓ web.server(127.0.0.1 HTTP /rpc・/upload) ←→ resources/web(Edge アプリ窓のUI) ……編集UI
```

- **モデルが真実**。編集は Web UI から `/rpc` 経由で `web.commands` を `web.undo_stack` へ
  push してモデルを更新し、SVG はモデルから直接書き出す（決定的・GUI 非依存でテスト可能・
  フォント名が崩れない）。
- 画面のページ表示も `export/svg_exporter.py` の SVG を Web DOM に流し込む（書き出しと同一経路）。
- UI（HTML/CSS/JS）は `resources/web/`、Python との橋渡しは `src/web/`（`server.py` /
  `rpc_methods.py` / `loader.py` / `commands.py` / `undo_stack.py`）。`app.py` が
  小さなローカル HTTP サーバを立て、Edge を `--app=` で起動・常駐管理する。ネットワークには
  出ない（`127.0.0.1` のみ）。PDF の読み込みは UI がバイトを `/upload` し、開く = 従来型
  `<input type=file>`、SVG/辞書の保存 = `<a download>`（ダウンロード）で行う。File System Access API
  のネイティブピッカーは VDI/リモートデスクトップの管理された Edge でレンダラごとクラッシュするため
  使わない（`app.js` の `hasFsSave()` は常に `false`。保存先はダウンロードフォルダ固定）。
- 主要モジュール: `engine/pdf_engine.py`, `model/elements.py`, `export/svg_exporter.py`,
  `dictionary/apply.py`, `web/server.py`, `web/rpc_methods.py`。

> `resources/web/` の `index.html` / `app.js`（画面組み立て）/ `state.js`（状態機械 `S` と遷移）/
> `rail.js`（左ページレール）/ `icons.js` / `dom.js` / `geometry.js` / `rpc.js` / `styles.css` は
> 手書き管理（`styles.css` のフォントは UI 用に Windows 標準へ差し替え済み）。

### 触りやすさマップ（どこから触るか / どこは慎重に）

初めての変更は 🟢 から着手し、🔴 はレビュー（またはペア作業）を挟むこと。
禁じ手（Edge 起動フラグ追加・ネイティブピッカー等）は `docs/pdf-to-svg/src/設計正典.md` の
「却下済み設計」を先に読むこと。

| ゾーン | 場所 | 理由 |
|---|---|---|
| 🟢 まず触ってよい | `src/dictionary/`（normalize / store） | 純粋寄り・pytest 完備 |
| 🟢 | `src/model/elements.py`・`src/engine/classify.py`・`src/engine/colors.py` | dataclass・判定関数。テスト済み |
| 🟢 | `src/web/undo_stack.py`・`src/web/commands.py` | コマンドパターンの器。テスト済み |
| 🟢 | `resources/web/geometry.js` | 純粋関数のみ。`test/geometry.test.js` あり |
| 🟡 注意 | `src/web/rpc_methods.py`・`src/export/`・`src/model/fonts.py`・`src/dictionary/apply.py` | 範囲は広いが 1 RPC = 1 関数で局所改修は可 |
| 🔴 レビュー必須 | `resources/web/app.js` | 972 行・単一 IIFE・可変グローバル状態多数。自動テストなし |
| 🔴 | `src/engine/pdf_engine.py` | PyMuPDF 抽出と z 順復元（`_match_seqno`）。AGPL 隔離境界でもある |
| 🔴 | `src/web/server.py`・`src/app.py` | スレッド・Edge ライフサイクル（/quit + watchdog） |

---

## テスト

```powershell
python -m pip install pytest
python -m pytest
```

抽出→辞書適用→クロップ→SVG 書き出し、正規化、ストア照合、スキャン画像埋め込み、RPC
ディスパッチ・Undo スタック・SVG 書き出しを網羅。コアは UI/Qt 非依存のため Qt 無しで走る。

フロントは `pnpm --filter pdf-to-svg run test`（vitest: `geometry.js` / `state.js` の純粋関数）と
`pnpm --filter pdf-to-svg run test:e2e`（Playwright: 実 Python サーバ + 実ブラウザで
取込→置換→削除/Undo→書き出しを通し、書き出した SVG の中身まで検証。
`test/e2e_server.py` が Edge を開かず固定ポートで起動する）。

---

## .exe ビルド

通常は `scripts\build.bat`（隔離 venv で依存導入 + ビルド）をダブルクリックすればよい。手動の場合:

```powershell
python -m pip install pyinstaller
pyinstaller packaging/pdftosvg.spec --clean --noconfirm --distpath dist --workpath build
# 出力: dist/PdfToSvg/PdfToSvg.exe (onedir)
```

配布はこの onedir フォルダ (`dist\PdfToSvg\`) をそのままコピーするポータブル方式。

> UI は OS 標準の **Edge をアプリモード**で開くため、QtWebEngine（Chromium）を同梱しない。
> `packaging/pdftosvg.spec` は `PySide6` / `shiboken6` を除外しており、`dist\PdfToSvg\` に
> `QtWebEngineProcess.exe` / `*.pak` / `locales\` / ICU / Qt DLL が **無い**こと（従来比
> ~120〜150MB 縮小）、`fitz`（PyMuPDF）のネイティブが揃っていること、ネットワーク遮断下でも
> 起動・書き出しができることをビルド後に確認する。Edge は Windows 10/11 に標準搭載。

---

## ライセンス注意

本ツールは **PyMuPDF (AGPL)** に依存する。**社内/身内限定の配布**を前提に採用している。
外部・商用配布が必要になった場合は、抽出部 `engine/pdf_engine.py`（薄い境界）を
BSD ライセンスの **pypdfium2** 等へ差し替えるか、Artifex の商用ライセンスを取得すること。
UI は OS 標準の Edge をアプリモードで開く方式のため Qt 依存は無い。

### 同梱フォント

フォントは本プロジェクト配下の **`fonts/`** に同梱している。**BIZ UDPゴシック**
（ゴシック代替・サブセット元は TTF 原本）と **Noto Serif JP**（明朝代替）を使い、いずれも **SIL OFL 1.1**
（`fonts/OFL-BIZUDPGothic.txt` / `fonts/OFL-NotoSerifJP.txt`）で再配布可。解決は `config.font_path()`、
SVG 出力時は使用グリフのみ WOFF2 サブセット埋め込みするため出力は数十 KB に収まる（`export/font_embed.py`）。

元 PDF の **ウェイト（Light/Regular/Medium/Bold）を保持**するため、フォント名から CSS ウェイトを
抽出し（`model/fonts.py`）、`<text>` に数値 `font-weight` を出力する。

- **明朝（Noto Serif JP）**: 可変フォント `NotoSerifJP-VF.ttf` を **wght 軸を保持したまま**サブセット埋め込みし、
  `@font-face` を `font-weight:100 900` で宣言。1 本で Light〜Bold を出し分ける。
- **ゴシック（BIZ UDPGothic）**: Regular/Bold の 2 ウェイトのみ存在。`@font-face` を範囲指定
  （Regular=`1 599` / Bold=`600 1000`）で宣言し、中間ウェイト要求を faux-bold 無しで最寄りへ解決させる
  （Medium ゴシックは Regular になる）。pie-chart のグラフと同一字形の BIZ UDPGothic で統一。
