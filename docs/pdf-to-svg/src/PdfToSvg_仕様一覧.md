---
audience: spec
title: PdfToSvg 仕様一覧（画面項目 / 入出力 / RPC・HTTP / テスト）
---

対象: PDF→SVG 変換ツール PdfToSvg（Edge シェル）・ 版 1.0 ・ 出典: pdf-to-svg/ 実装コード・テスト（DB なし）

# 画面項目定義

| No | ステップ | 項目 | コントロール | 説明 |
|:--:|---|---|---|---|
| 1 | 1. PDF選択 | ドロップゾーン | `D&D / ピッカー` | 複数PDF選択可 |
| 2 | 1. PDF選択 | ファイルリスト | `list（削除可）` | 選択PDF一覧 |
| 3 | 1. PDF選択 | 次へ | `button` | 1件以上で有効化 |
| 4 | 2. 用語置換 | ページプレビュー | `SVG表示（ズーム）` | 中央キャンバス |
| 5 | 2. 用語置換 | 確認タブ | `置換一覧` | クリックでハイライト・幅超過警告。行ごとに番号マーカーと対応（No.12）、戻す/置換ボタンで箇所単位に取消・適用（No.11） |
| 6 | 2. 用語置換 | 元の語 | `#dict-src` | 辞書追加フォーム |
| 7 | 2. 用語置換 | 置換後 | `#dict-tgt` | 辞書追加フォーム |
| 8 | 2. 用語置換 | クリック取り込みで折返しを連結 | `#chk-suggest-join` | suggest_join フラグ（既定 OFF。ON で連結取り込み・連結由来を記録） |
| 9 | 2. 用語置換 | このページのみ再適用 | `#btn-reapply-page` | 主ボタン（既定）。表示中ページへ辞書適用（ヘッダ・本文を問わず全文） |
| 10 | 2. 用語置換 | 全ファイルに再適用 | `#btn-reapply` | 明示選択で辞書変更を全PDFへ |
| 11 | 2. 用語置換 | 戻す / 置換 | `.change-row .act-revert` / `.act-apply` | 確認一覧の行ごとに 1 箇所だけ置換前へ戻す / 1 箇所だけ置換する（Undo 可） |
| 12 | 2. 用語置換 | 番号マーカー | `#doc-master svg [data-editor-marks]` | 一覧の通し番号をページ上の該当箇所へ描く（表示用のみ・書き出しには含めない）。行ホバーで枠強調 |
| 13 | 2. 用語置換 | JSON書き出し / JSON読み込み | `#btn-dict-export / import` | 辞書の JSON 入出力（連結由来 joined を保持） |
| 14 | 3. 削除・枠線 | ツール | `選択 / 範囲削除 / 枠線` | 編集モード切替 |
| 15 | 3. 削除・枠線 | 枠線色 | `#border-color` | カラーピッカー |
| 16 | 3. 削除・枠線 | 枠線幅 | `#border-width` | 0.5〜20 pt |
| 17 | 3. 削除・枠線 | 削除 | `#btn-deletesel` | 選択要素削除 |
| 18 | 4. 書き出し | 書き出す範囲 | `ボタン群（排他）` | 表示中のページのみ / 全ページ / スキップを除く / ページを指定 |
| 19 | 4. 書き出し | SVGに書き出す | `button` | ファイル名は <元名>_pN.svg |
| 20 | トップバー | Undo/Redo | `Ctrl+Z / Ctrl+Y` | 操作の取消/やり直し |

# 入出力定義

| No | 区分 | 項目 | 型/形式 | 説明 |
|:--:|:--:|---|---|---|
| 1 | 入力 | PDFファイル | `バイト列` | POST /upload?name= で受領 |
| 2 | 入力 | 辞書JSON | `[{source, target, enabled, joined}]` | data/dictionary.json。NFKC正規化。joined=連結由来（旧形式キー無しは false） |
| 3 | 入力 | フォント | `同梱フォント自動解決` | BIZ UDPゴシック / Noto Serif JP |
| 4 | 入力 | suggest_join | `bool（既定 false）` | クリック取り込みで折返し 2 行を連結するか |
| 5 | 入力 | 枠線色/幅 | `hex / 0.5〜20pt` | 枠線追加 |
| 6 | 入力 | 書き出す範囲 | `表示中のページのみ / 全ページ / スキップを除く / ページを指定` | ページ選別 |
| 7 | 出力 | SVGファイル | `決定的SVG` | 実<text>保持・使用グリフのみWOFF2埋込 |
| 8 | 出力 | PNG背景 | `ラスタ（SCAN_RENDER_SCALE=2.0）` | スキャンページ背景 |
| 9 | 設定 | config.py | `frozen exe / ソース共通` | データ置き場（既定 %LOCALAPPDATA%\PdfToSvg\data）に辞書・ログ・作業領域。`PDFTOSVG_DATA_DIR` で明示指定可 |

# RPC・HTTP

| No | 種別 | 名称 | 説明 |
|:--:|:--:|---|---|
| 1 | HTTP | `GET /` | 静的配信（resources/web） |
| 2 | HTTP | `POST /rpc` | JSON-RPC ディスパッチ |
| 3 | HTTP | `POST /upload` | PDF 読み込み（バイト列。辞書は適用しない。適用は再適用 RPC のみ） |
| 4 | HTTP | `POST /quit` | 終了ビーコン |
| 5 | HTTP | `POST /ping` | ハートビート |
| 6 | RPC | `state` | ファイル/ページ/置換当たり等の状態取得 |
| 7 | RPC | `pageSvg` | ページSVG取得（annotate 付き） |
| 8 | RPC | `planPage` | 置換予定の算出。確認一覧の行を出現順に返し、各行に `state`（applied/pending）を含める |
| 9 | RPC | `removedList` | 削除要素一覧 |
| 10 | RPC | `dictList / dictAdd / dictDelete` | 辞書 参照 / 追加 / 削除 |
| 11 | RPC | `dictSuggest` | ページ上の文字クリックから「元の語」候補を返す（suggest_join ON なら折返し行を連結） |
| 12 | RPC | `reapplyDict / reapplyDictPage` | 辞書の全ファイル / 単一ページ再適用（連結照合は joined エントリのみ） |
| 13 | RPC | `revertDictMatch` | 指定要素の置換を 1 箇所だけ戻す（`dict_revert` から復元、`RevertDictMatchCommand`。次の再適用ではまた置換される） |
| 14 | RPC | `applyDictMatch` | 指定要素 1 件だけ辞書を当てる（1 マクロ） |
| 15 | RPC | `dictJson / dictImportJson` | 辞書JSONの文字列受け渡し（ファイル保存/読込はブラウザ側） |
| 16 | RPC | `setSuggestJoin` | クリック取り込み連結フラグ更新 |
| 17 | RPC | `applyDelete / deleteRegion / restoreElements / addBorder` | 削除 / 範囲削除 / 削除一覧の行ごとの戻し / 枠線（Undoへpush） |
| 18 | RPC | `undo / redo` | 操作の取消 / やり直し |
| 19 | RPC | `exportSvg` | 範囲指定で SVG 書き出し |
| 20 | RPC | `zipEntries` | 複数 SVG を ZIP 1 本にまとめて base64 で返す |
| 21 | RPC | `removeFile` | 選択ファイルを一覧から除去 |

# テスト仕様

| No | テスト | テスト観点 | 期待結果 | 結果 |
|:--:|---|---|---|:--:|
| 1 | `test_pipeline.py` | 抽出→辞書→SVG・ペイント順序・textLength | E2E が一致 | 未 |
| 2 | `test_web_rpc.py` | RPC の状態変更（削除/編集/Undo・FakeUndo） | 状態遷移が正しい | 未 |
| 3 | `test_fonts.py` | フォント名マッピング・ウェイト・幅オーバーフロー | フォント解決が正しい | 未 |
| 4 | `test_undo_stack.py` | マクロ化Undo（複数コマンド1ステップ） | Undo が一括で戻る | 未 |
| 5 | `test_wrap_header.py` | 折返しセルの畳み込み（複数行→1行。連結は joined エントリのみ。下揃え + 元の行揃え踏襲） | セルが1行化 | 未 |
| 6 | `test_normalize.py` | NFKC 正規化（全角/半角差吸収） | 正規化が一致 | 未 |
| 7 | `test_store_matcher.py` | 辞書ストア照合ロジック | マッチングが正しい | 未 |
| 8 | `test_seqno_match.py` | ペイント順序と抽出要素の対応付け | 順序対応が正しい | 未 |
| 9 | `test_font_weight.py` | ウェイト保持とCSS出力 | Light/Regular/Bold保持 | 未 |
| 10 | `test_scan_ocr.py` | スキャン判定・ラスタ化 | スキャン処理が正しい | 未 |
| 11 | `test_shell_rpc.py` | RPC ディスパッチのJSON化可能性 | JSON化できる | 未 |
