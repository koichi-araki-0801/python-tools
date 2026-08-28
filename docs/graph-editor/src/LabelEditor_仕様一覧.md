---
audience: spec
title: LabelEditor 仕様一覧（画面項目 / 入出力 / テスト）
---

対象: SVG ラベル位置エディタ LabelEditor（graph-editor）・ 版 3.1（操作手順書と同期） ・ 出典: graph-editor/ 実装コード・テスト（DB なし）

# 画面項目定義

| No | 画面/ステップ | 項目 | コントロール | 値/範囲 | 説明 |
|:--:|---|---|---|---|---|
| 1 | 1. ファイルを開く | SVG選択 | `D&D / ファイルピッカー` | `複数可` | pie-chart 出力 SVG を読み込む |
| 2 | 1. ファイルを開く | ファイル一覧 | `list` |  | 開いたファイルの表示 |
| 3 | 2. 位置を調整 | ファイル一覧 | `左レール` |  | ファイル+ラベルの一覧（選択中ファイルの直下にラベル一覧） |
| 4 | 2. 位置を調整 | キャンバス | `SVG表示` |  | ドラッグ編集・ズーム |
| 5 | 2. 位置を調整 | 引出線 | `toggle` | `表示 / 非表示` | leader の表示切替 |
| 6 | 2. 位置を調整 | 曲げ点 | `toggle` | `あり / なし` | leader の中間曲げ点の有無（引出線が表示のときのみ） |
| 7 | 2. 位置を調整 | 文字色 | `toggle` | `黒 / 白` | テキスト色 |
| 8 | 2. 位置を調整 | 行数 | `toggle` | `1行 / 2行` | 名前と%の分割 |
| 9 | 2. 位置を調整 | 長体 | `range slider` | `70〜100%` | 名前部分の水平圧縮 |
| 10 | 2. 位置を調整 | テキスト位置 | `drag` | `x,y px` | translate 移動（矢印1px/10px） |
| 11 | 2. 位置を調整 | leader端点(緑) | `drag` | `x,y px` | テキスト側端点。box へクランプ |
| 12 | 2. 位置を調整 | leader曲げ点(青) | `drag` | `x,y px` | 中間の曲げ点 |
| 13 | 2. 位置を調整 | leader根元(橙) | `fixed` |  | pie 接点（固定） |
| 14 | 2. 位置を調整 | Undo | `Ctrl+Z` |  | 操作の取り消し |
| 15 | 3. SVGを保存 | 保存 | `button` |  | 補助要素を除去した SVG を保存 |

# 入出力定義

| No | 区分 | 項目 | 型/形式 | 説明 |
|:--:|:--:|---|---|---|
| 1 | 入力 | SVGファイル | `pie-chart 出力 SVG` | ユーザ指定も可 |
| 2 | 入力 | ラベル構造 | `g.label > path? + text` | data-name 付き。path=引出線(任意) |
| 3 | 入力 | transform | `translate(x,y)` | テキスト位置 |
| 4 | 出力 | 修正済みSVG | `SVG` | 編集補助要素を除去して保存 |
| 5 | 共有 | leader_geom.cjs | `UMD（ブラウザと graph-editor の vitest で共有。pie-chart とは並行実装）` | parsePath / buildPath / clampPointToBox / parseTranslate / normColor |

# テスト仕様

| No | 区分 | テスト観点 | 期待結果 | 結果 |
|:--:|---|---|---|:--:|
| 1 | 共有geom | clampPointToBox: 点を矩形へクランプ | leader端点がbox上に乗る | 未 |
| 2 | 共有geom | parsePath / buildPath の往復 | パス文字列が保存される | 未 |
| 3 | 共有geom | parseTranslate: transform 抽出 | translate 値が取れる | 未 |
| 4 | 共有geom | normColor: 色文字列正規化 | 色表記が正規化される | 未 |
| 5 | E2E | SVG読込→ドラッグ→保存 | 保存SVGに位置反映 | 未 |
| 6 | E2E | Undo（Ctrl+Z） | 直前操作が戻る | 未 |
