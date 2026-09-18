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
| 3.1 | 1. PDF選択 | 書き出し方 | `#mode-normal` / `#mode-gray` | ラジオ 2 択のカード（`.mode-card.on` が選択中）。「ページを SVG にする」（既定）と「図だけをグレースケールで書き出す」。グレーは手順 2・3 を省略して手順 4 へ直行（サーバ側の状態には影響しない）。通常側の流れ表示の「2 用語」（`#flow-step2`）は手順 2 を省略するとき打ち消し |
| 3.2 | 1. PDF選択 | スキャン画像のバナー | `#scan-banner` | スキャンページが 1 ページ以上あるとき、ファイル一覧の見出しとカードの間に常設。文言は全ページ用と混在用の 2 系統（グレーモードでは出さない）。全ページが純スキャンなら「次へ」は案内を出さず手順 3 へ直行し、ステップバーの 2 は非表示（`.stepbar.skip2`。注記は `#scan-skipnote`）・クリック不可、手順 3 の「戻る」は手順 1 へ |
| 3.3 | 1. PDF選択 | ファイルカードのバッジ | `.file-card .chip` | スキャンページを持つファイルに「スキャン画像 n / m ページ」（n = そのファイルのスキャンページ数、m = ページ数） |
| 4 | 2. 用語置換 | ページプレビュー | `SVG表示（ズーム）` | 中央キャンバス |
| 4.1 | 2. 用語置換 | ページレール | `#pagenav` | 絞り込みの既定は「辞書に一致したページだけ」（もう一方は「すべてのページ」）。各行の右端に「置換 a ・ 未置換 b」（0 の側は省略）。純スキャンページはどちらの絞り込みでも行を出さない。見出しに「全 N ページ　辞書に一致 n ページ　対象外 k」（対象外はスキャンページが 1 ページ以上のときだけ）。行が 1 つも出ないときは「この絞り込みに該当するページはありません」（手順 3 と共通の文言） |
| 4.2 | 2. 用語置換 / 3. 削除・枠線 | ページへ移動 | `#pgnav-2` / `#pgnav-3`（`.page-jump`） | キャンバス下。ファイル選択 + ページ番号 + 「移動」+ 前後（‹ ›）。レールの絞り込みに出ていないページへも番号で移れる |
| 4.3 | 2. 用語置換 | 件数カード | `.count-card` | 「このページで置き換えた語」の数。中立の背景で 0 件でも緑にしない。説明文で未置換の残り件数を示す |
| 4.4 | 2. 用語置換 | ページ送り | `#prev-page-2` / `#next-match-2` | 右パネル下部。「前のページ」は通し −1、「次の一致ページ」は `nextMatched` で表示中より後ろの一致のあるページへ（末尾まで無ければ先頭から探す）。いずれも該当が無ければ無効 |
| 5 | 2. 用語置換 | 確認タブ | `置換一覧` | クリックでハイライト・幅超過警告。行ごとに番号マーカーと対応（No.12）、戻す/置換ボタンで箇所単位に取消・適用（No.11） |
| 6 | 2. 用語置換 | 元の語 | `#dict-src` | 辞書追加フォーム |
| 7 | 2. 用語置換 | 置換後 | `#dict-tgt` | 辞書追加フォーム |
| 8 | 2. 用語置換 | クリック取り込みで折返しを連結 | `#chk-suggest-join` | suggest_join フラグ（既定 OFF。ON で連結取り込み・連結由来を記録） |
| 9 | 2. 用語置換 | このページのみ再適用 | `#btn-reapply-page` | 主ボタン（既定）。表示中ページへ辞書適用（ヘッダ・本文を問わず全文） |
| 10 | 2. 用語置換 | 全ファイルに再適用 | `#btn-reapply` | 明示選択で辞書変更を全PDFへ |
| 11 | 2. 用語置換 | 戻す / 置換 | `.change-row .act-revert` / `.act-apply` | 確認一覧の行ごとに 1 箇所だけ置換前へ戻す / 1 箇所だけ置換する（Undo 可） |
| 12 | 2. 用語置換 | 番号マーカー | `#doc-master svg [data-editor-marks]` | 一覧の通し番号をページ上の該当箇所へ描く（表示用のみ・書き出しには含めない）。行ホバーで枠強調 |
| 13 | 2. 用語置換 | JSON書き出し / JSON読み込み | `#btn-dict-export / import` | 辞書の JSON 入出力（連結由来 joined を保持） |
| 14 | 3. 削除・枠線 | ツール | `範囲削除 / 枠線 / 上書き` | 編集モード切替（初期は無選択。押下中のタブを再度押すと無選択へ戻る。要素のクリック選択はツールに関係なく常に効く） |
| 14.1 | 3. 削除・枠線 | 上書きの置換語 | `#cover-text` | プレースホルダ「置換語（空なら矩形だけ）」。200 文字まで、空なら矩形のみの上書き |
| 14.2 | 3. 削除・枠線 | このページの編集 | `#trim-dyn .edit-row` | 削除・枠線・上書きの一覧（`data-kind` で種別）。削除の行は「戻す」、枠線・上書きの行は「削除」。1 件も無ければ「このページに編集はありません」 |
| 14.3 | 3. 削除・枠線 | 使い方 | `.howto` | 右パネル下部の箇条書き。表示中のページがスキャン画像かどうかで文言を切り替える |
| 14.4 | 3. 削除・枠線 | ページ送り | `#prev-page-3` / `#next-page-3` | 右パネル下部。「前のページ」「次のページ」は通しページで ±1（端で無効）。一致の有無は見ない |
| 14.5 | 3. 削除・枠線 | ページレール | `#pagenav-3` | 絞り込みの既定は「すべてのページ」（もう一方は「編集したページだけ」）。各行の右端に「削除 a ・ 枠線 b ・ 上書き c」（0 の項目は省略）。見出しに「全 N ページ　編集したページ n」。スキャンページも行に出す（上書きの対象になるため）。行が 1 つも出ないときは「この絞り込みに該当するページはありません」（手順 2 と共通の文言） |
| 15 | 3. 削除・枠線 | 枠線色 | `#border-color` | カラーピッカー。枠線を選んでいる間は選択中の枠線の色を変える |
| 16 | 3. 削除・枠線 | 枠線幅 | `#border-width` | 0.5〜20 pt。枠線を選んでいる間は選択中の枠線の太さを変える |
| 16.1 | 3. 削除・枠線 | 枠線のオーバーレイ | `.border-box` / `.border-box.sel` | 置いた枠線を箱で重ねる。クリックで選択、本体ドラッグで移動、角ハンドルで伸縮 |
| 17 | 3. 削除・枠線 | 削除 | `#btn-deletesel` | 選択要素・選択中の上書き・選択中の枠線の削除。何も選んでいない間は `disabled` |
| 18 | 4. 書き出し | 書き出す範囲 | `ボタン群（排他）` | 表示中のページのみ / 全ページ / ページを指定 |
| 18.1 | 4. 書き出し（グレーモード） | ページレール | `#pagenav-4` | 各ページの候補数バッジ（採用ありは緑）。クリックでページ移動 |
| 18.2 | 4. 書き出し（グレーモード） | 図の編集キャンバス | `#fig-stage` | グレースケールのページプレビューに候補矩形を重ねる |
| 18.3 | 4. 書き出し（グレーモード） | 候補／採用矩形 | `.fig-cand` / `.fig-cand.sel` | 点線=未採用の候補（クリックで採用）、実線=採用済み（角ハンドルで伸縮、× で採用解除）。空白ドラッグで自前の矩形を追加 |
| 18.4 | 4. 書き出し（グレーモード） | 書き出す範囲 | `#exp-modes-gray` | 表示中のページの図 / 全ページの採用した図 の 2 択（通常モードの 3 択 `#exp-modes` は非表示） |
| 18.5 | 4. 書き出し（グレーモード） | 採用した図の一覧 | `#fig-selist-box` / `#fig-selist` | 採用済みの図を書き出しファイル名（`<元名>_p<N>_fig<k>_gray.svg`）と pt 寸法で全ページ分列挙（`S.expMode` に関係なく常に全件）。クリックでそのページへ移動。0 件時は案内文を表示 |
| 19 | 4. 書き出し | SVGに書き出す | `button` | ファイル名は <元名>_pN.svg（グレーモードは <元名>_pN_figK_gray.svg） |
| 19.1 | 4. 書き出し | まとめ | `#export-summary`（`.sum-table`） | 3 行の表。PDF：F ファイル・全 N ページ／用語の置換：置換 a か所（p ページ）・未置換 b か所・対象外（スキャン画像）k ページ（0 の項目は省略）／削除・枠線：編集したページ n・削除 x・枠線 y・上書き z（0 件なら「編集したページはありません」） |
| 19.2 | 4. 書き出し | 注記 | `.note-line` | 「文字は文字のまま書き出します（後から検索・再編集できます）。」「使ったフォントだけを埋め込みます。」の 1 行注記 |
| 20 | トップバー | Undo/Redo | `#btn-undo` / `#btn-redo` | アイコンの右に「元に戻す」「やり直し」の文字ラベル付き。Ctrl+Z / Ctrl+Y でも同じ |

# 入出力定義

| No | 区分 | 項目 | 型/形式 | 説明 |
|:--:|:--:|---|---|---|
| 1 | 入力 | PDFファイル | `バイト列` | POST /upload?name= で受領 |
| 2 | 入力 | 辞書JSON | `[{source, target, enabled, joined}]` | data/dictionary.json。NFKC正規化。joined=連結由来（旧形式キー無しは false） |
| 3 | 入力 | フォント | `同梱フォント自動解決` | BIZ UDPゴシック / Noto Serif JP |
| 4 | 入力 | suggest_join | `bool（既定 false）` | クリック取り込みで折返し 2 行を連結するか |
| 5 | 入力 | 枠線色/幅 | `hex / 0.5〜20pt` | 枠線追加 |
| 6 | 入力 | 書き出す範囲 | `表示中のページのみ / 全ページ / ページを指定` | ページ選別 |
| 6.1 | 入力 | 上書きの矩形/置換語 | `{x,y,w,h}` / 200 文字まで | 手動の上書き |
| 7 | 出力 | SVGファイル | `決定的SVG` | 実<text>保持・使用グリフのみWOFF2埋込 |
| 8 | 出力 | PNG背景 | `ラスタ（SCAN_RENDER_SCALE=2.0）` | スキャンページ背景 |
| 8.1 | 出力 | 上書き矩形 | `<g><rect><text>` | 不可視OCR文字の置換箇所・手動の上書き。色は画像から採色 |
| 9 | 設定 | config.py | `frozen exe / ソース共通` | データ置き場（既定 %LOCALAPPDATA%\PdfToSvg\data）に辞書・ログ・作業領域。`PDFTOSVG_DATA_DIR` で明示指定可 |
| 10 | 出力 | グレー書き出しファイル名 | `<元ファイル名>_p<N>_fig<k>_gray.svg` / `<元ファイル名>_gray_svg.zip` | 図だけをグレースケールで書き出すモードの命名。`k` は同ページ内の採用順（1 始まり）。カラー版の `_pN.svg` と衝突しない |

# RPC・HTTP

| No | 種別 | 名称 | 説明 |
|:--:|:--:|---|---|
| 1 | HTTP | `GET /` | 静的配信（resources/web） |
| 2 | HTTP | `POST /rpc` | JSON-RPC ディスパッチ |
| 3 | HTTP | `POST /upload` | PDF 読み込み（バイト列。辞書は適用しない。適用は再適用 RPC のみ） |
| 4 | HTTP | `POST /quit` | 終了ビーコン |
| 5 | HTTP | `POST /ping` | ハートビート |
| 6 | RPC | `state` | ファイル一覧・ページ一覧・総ページ数と、ページごとの件数の列を返す。`matches2: [[置換済み, 未置換], ...]`、`edits3: [[削除, 枠線, 上書き], ...]`、`scanned: bool[]`（ページ単位の純スキャン判定。文字要素を持たないページ）と `scannedPages`（その件数）。ページごとの確認状態は返さない |
| 6.1 | RPC | `figureCandidates` | スチュワードシップ図の候補矩形を取得。引数 `fileIndex`, `pageInFile`。返り値 `{rects: [{x, y, w, h}]}`（0 または 1 件）。検出の想定外例外はページ単位で握って候補なしにする |
| 7 | RPC | `pageSvg` | ページSVG取得（annotate 付き）。引数に `grayscale: bool = false`, `clip: {x,y,w,h}`（省略時 null）を追加。`clip` の検査は `_parse_rect_arg`（ページ内を要求） |
| 8 | RPC | `planPage` | 置換予定の算出。確認一覧の行を出現順に返し、各行に `state`（applied/pending）を含める |
| 9 | RPC | `removedList` | 削除要素一覧 |
| 10 | RPC | `dictList / dictAdd / dictDelete` | 辞書 参照 / 追加 / 削除 |
| 11 | RPC | `dictSuggest` | ページ上の文字クリックから「元の語」候補を返す（suggest_join ON なら折返し行を連結） |
| 12 | RPC | `reapplyDict / reapplyDictPage` | 辞書の全ファイル / 単一ページ再適用（連結照合は joined エントリのみ） |
| 13 | RPC | `revertDictMatch` | 指定要素の置換を 1 箇所だけ戻す（`dict_revert` から復元、`RevertDictMatchCommand`。次の再適用ではまた置換される） |
| 14 | RPC | `applyDictMatch` | 指定要素 1 件だけ辞書を当てる（1 マクロ） |
| 15 | RPC | `dictJson / dictImportJson` | 辞書JSONの文字列受け渡し（ファイル保存/読込はブラウザ側） |
| 16 | RPC | `setSuggestJoin` | クリック取り込み連結フラグ更新 |
| 17 | RPC | `applyDelete / deleteRegion / restoreElements / addBorder / borderList / updateBorder` | 削除 / 範囲削除 / 削除一覧の行ごとの戻し / 枠線の追加・一覧・変更（いずれも Undo へ push）。矩形を取る `deleteRegion`/`addBorder`/`updateBorder` は `_parse_rect_arg` の 1 本で検査し（数値 4 つの有限性・正の寸法は常に要求）、範囲削除だけはページ外の矩形も許す（`inside_page=False`。矩形自体は成果物に残らず、重なる要素を選ぶだけのため）。枠線はページ内を要求する。太さの範囲検査は `_border_width` を `addBorder` と `updateBorder` が共有する。一覧・変更の対象は `manual_border` の印が付いた未削除の枠線だけ |
| 17.1 | RPC | `addCover` | 手動の上書きを 1 つ追加（引数 `fileIndex, pageInFile, rect, text`。不可視かつ置換済み扱いの `TextElement` を作り Undo へ push）。`rect` の検査は `_parse_rect_arg`（ページ内を要求） |
| 17.2 | RPC | `coverList` | 指定ページの手動の上書き一覧を取得（引数 `fileIndex, pageInFile`。返り値 `{covers: [{elId, rect, text}]}`） |
| 17.3 | RPC | `updateCover` | 手動の上書きの矩形/置換語を変更（引数 `fileIndex, pageInFile, elId` + 任意で `rect, text`。`UpdateCoverCommand` で Undo へ push）。`rect` の検査は `addCover` と同じ `_parse_rect_arg` |
| 18 | RPC | `undo / redo` | 操作の取消 / やり直し |
| 19 | RPC | `exportSvg` | 範囲指定で SVG 書き出し。引数に `grayscale`, `clip`, `figIndex: int = 1` を追加。`clip` があれば `_fig<k>`、`grayscale` が真なら `_gray` を独立して付け加える（`<stem>_p<N>[_fig<k>][_gray].svg`）。UI のグレーモードは常に両方を送るため成果物は `<stem>_p<N>_fig<k>_gray.svg` |
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
| 12 | `test_figure_detect.py` | スチュワードシップ図の文字アンカー検出（見出し・ラベル数・背景/帯の除外・不動点ループの停止） | 合成ページで矩形検出が正しい | 未 |
| 13 | `test_grayscale.py` | 色hex・色名・alpha・`none`/`currentColor`のグレー化、画像RGB→L/RGBA→LA、巨大画素・壊れたバイトは原本、`lru_cache` | Pillowの`convert("L")`と一致 | 未 |
| 14 | `test_export_clip.py` | `clip`のviewBox/width/height、交差外要素の除外、`<clipPath>`、`grayscale=True`でカラーhexが残らないこと、既定OFFのバイト一致、画像の`clip_d`の`<defs>`集約・同一形状の重複排除・`annotate`との併存・ページclipとの組合せ | クロップ・グレー化出力が正しい | 未 |
| 15 | `test_pdftosvg_app_flow_e2e.py::test_gray_figure_flow` | チェックON→手順4直行→候補が採用済み→書き出しファイル名に`_fig1_gray`が付く（E2E） | 一連の動線が通る | 未 |
| 16 | `test_image_clip.py` | クリップ下で描かれた画像に`clip_d`が入る、SVGに`<clipPath>`と`clip-path`が出る、クリップ無しの画像は`clip_d`が空、items が矩形1個だけのclipは索引へ入れない | 切り抜き形状が再現される | 未 |
| 17 | `test_ocr_layer.py` | 不可視span への`invisible`付与、未置換の書き出し省略/編集画面の透明描画、置換済みの`<g><rect><text>`と採色（帯色・単色領域の黒白倒し）、グレー化での灰色化、`MAX_COVER_IMAGE_PIXELS`超過時の白フォールバックと`ExportReport.cover_fallback`、不可視文字を持たないPDFのバイト一致、書き出さない不可視文字をフォント埋込対象から除外、スキャン背景からの採色 | 不可視OCR文字層の検出・隠し描画が正しい | 未 |
| 18 | `test_cover.py` | 量子化16階調での最頻色/次点色の決定性、代表色は箱の平均値、`MIN_CONTRAST`未満での黒/白への倒し、bboxの画像範囲へのクランプ、`MAX_COVER_IMAGE_PIXELS`超過・壊れた画像の`None`化 | `cover.py`の採色ロジックが正しい | 未 |
| 19 | `test_pdftosvg_app_flow_e2e.py::test_ocr_layer_upload_notifies` | 画像+不可視OCR文字層のPDFアップロード時のトースト通知（E2E） | 検出ページ数が通知される | 未 |
| 20 | `test_pdftosvg_app_flow_e2e.py::test_manual_cover_tool_places_cover` ほか | 「上書き」ツールでのドラッグ配置、角ハンドルでの伸縮、置換語の変更（選択中の編集が次の上書きへ漏れないこと含む）、Undoでの巻き戻し（E2E） | 手動の上書きの配置・編集が正しく反映される | 未 |
| 21 | `test_ocr_layer.py::test_grayscale_cover_matches_the_grayscaled_image` ほか | グレー書き出しの上書き矩形の色が、書き出しに乗るグレー化後の画像から採った色と一致する（元のカラー画像から採らない）、カラー書き出しの採色は従来どおり元画像から採ったまま変わらない（`test_color_cover_is_unchanged_by_the_grayscale_fix`） | 採色元と書き出し画像の色が一致 | 未 |
| 22 | `test_cover.py::test_transparent_pixels_composite_onto_white` ほか | 透過を持つ画像（RGBA等）はRGB化の前に白へ合成してから採色する（透明画素が黒い当て板にならない） | 透明部分は白として採る | 未 |
| 23 | `test_web_rpc.py::test_update_cover_rejects_a_deleted_cover` | 削除済みの上書き要素に対する`updateCover`が例外で拒否される | 削除済み要素を書き換えない | 未 |
| 24 | `test_pdftosvg_geometry_js.py` | `figure.js`から`geometry.js`へ移した矩形ヘルパ（`copyRect`/`clampToPage`/`MIN_SIZE_PT`/`pageSizeOf`）の単体 | 移動後も挙動が変わらない | 未 |
| 25 | `test_cover.py::test_grayscale_output_is_la_and_composites_to_white` ほか | グレー化後の`LA`画像・透過付きパレット画像（`P`+`transparency`）も白へ合成すること（透明を持つかの判定は`grayscale.has_alpha_channel`を`cover.decode_image`と共有し、二重実装を持たない） | 他形式の透明も白へ合成される | 未 |
| 26 | `test_ocr_layer.py::test_degraded_seqno_index_leaves_text_visible` | seqno索引が候補数上限で照合を諦めた（`degraded`）ページで、文字に不可視判定を与えないこと | 索引degrade時も文字が可視のまま抽出される | 未 |
| 27 | `test_pdftosvg_geometry_js.py::test_resizebycorner_*` ほか、`test_pdftosvg_app_flow_e2e.py::test_gray_figure_flow` | 角ハンドルの伸縮計算`resizeByCorner`（掴んだ角の移動・反対角の固定・反対辺を越えた入替・`MIN_SIZE_PT`未満へのクランプ）とハンドルのマークアップ`CORNER_HANDLES_HTML`の単体、手順4での伸縮操作が実際に矩形の幅・高さへ反映されること（E2E） | 伸縮計算が正しく、画面上の伸縮にも反映される | 未 |
| 28 | `test_pdftosvg_geometry_js.py::test_rectfromdrag_*` | ドラッグの2点からページ内の矩形を作る`rectFromDrag`（ページ外へのはみ出しをページ内へ収める・引く向きの正規化・`MIN_SIZE_PT`未満の誤クリック拒否・収めた結果が`MIN_SIZE_PT`未満になる場合も拒否） | 手順3・4が共有する矩形確定ロジックが正しい | 未 |
| 29 | `test_web_rpc.py::test_rect_arg_rejects_non_finite_values` ほか | 矩形検査の一本化`_parse_rect_arg`（非有限値は`deleteRegion`/`addBorder`のどちらからでも拒否、範囲削除はページ外の矩形も許容、枠線は同じ矩形をページ外として拒否） | 矩形検査がRPC全体で揃っている | 未 |
| 30 | `test_resource_limits.py::test_raster_and_gray_pixel_caps_stay_equal` | `pdf_engine`（`fitz` import隔離のため複製）と`grayscale`が持つラスタ化の画素上限`MAX_RASTER_PIXELS`/`MAX_GRAY_IMAGE_PIXELS`の等値 | 対で保守する定数がずれていない | 未 |
| 31 | `test_pdftosvg_app_flow_e2e.py::test_manual_cover_drag_past_the_page_edge_still_places_a_cover` | ページの端をまたいでドラッグしても上書きが置かれること（`rectFromDrag`のページ内クランプが効く）（E2E） | ページ外へ引いても上書きが成立する | 未 |
| 32 | `test_pdftosvg_app_flow_e2e.py::test_manual_cover_delete_button_removes_cover_selected_with_cover_tool` ほか、`test_pdftosvg_state_js.py::test_transition_resetphaseui_*` ほか | 上書きツールのまま選んだ上書きを削除ボタンで消せること、ツール切替で要素の選択が解けること、手順を戻っても表示中のページが保たれツール・選択が既定へ戻ること（戻るボタンの4→3・3→2、ステップバーの4→3。2ページのPDFを使う）（E2E）と、`resetPhaseUi`の単体 | 手順を行き来したあとも上書きを削除でき、見ていたページへ戻れる | 未 |
| 33 | `test_web_rpc.py::test_border_list_returns_manual_borders_only` ほか | 枠線の一覧・変更 RPC（印の付いた未削除の枠線だけを返す、位置・色・太さの変更と Undo、太さだけの変更、無変更の呼び出し・削除済み要素・PDF 由来要素・ページ外の矩形・範囲外の太さの拒否） | 置いた枠線だけを後から安全に編集できる | 未 |
| 34 | `test_pdftosvg_app_flow_e2e.py::test_border_overlay_resize_and_width_change` ほか | 枠線オーバーレイの伸縮・選択して太さ変更・Undo、選択中の編集が次に置く枠線へ漏れないこと、枠線ツールのまま選んだ枠線を削除ボタンで消せること（E2E） | 枠線の後編集が画面で成立する | 未 |
| 35 | `test_pdftosvg_app_flow_e2e.py::test_element_click_selection_works_while_a_tool_is_active` ほか、`test_pdftosvg_state_js.py::test_transition_resetphaseui_*` | 選択タブ廃止後もどのツール中でもクリックで要素を選んで削除できること、押下中のタブの再クリックで無選択へ戻ること、何も選んでいない間は削除ボタンが `disabled` であること（E2E）と、`resetPhaseUi` がツールを無選択へ戻す単体 | 選択タブが無くても削除の導線が成立する | 未 |
| 36 | `test_pdftosvg_app_flow_e2e.py::test_undo_after_typing_a_word_then_placing_a_cover_undoes_the_cover` ほか | 入力欄に値を打ってから範囲を引いて置き、そのまま Ctrl+Z で戻ること（上書き・枠線それぞれ）。範囲を引いた時点で入力欄のフォーカスが外れ、Ctrl+Z がアプリの Undo に届く（E2E）。ジッター E2E にも Ctrl+Z 時点でフォーカスが無いことの明示的な確認を足し、実行順への依存を断つ | 値を打った直後の Ctrl+Z がアプリの Undo として効く | 未 |
| 37 | `test_pdftosvg_rect_overlay_js.py::test_draw_discards_a_stale_list_that_arrives_after_a_newer_one` | `rect-overlay.js` の `draw()` が同じページで 2 回重なり、先に出した一覧 RPC の応答が後から届いても、古い一覧で箱を作り直さないこと（`ui.rpc` を外から resolve できる Promise に差し替えて届く順を制御。実ブラウザ単体） | 追い越された古い応答が箱を重複させない | 未 |
| 38 | `test_e2e_server.py::test_port_zero_writes_the_actual_port_to_the_file_and_serves_there` ほか | E2E 用サーバをポート 0 で起動すると OS が選んだ実ポートがファイルに書かれそこで応答すること、2 本同時起動で別ポートになること、子が起動前に死んだら `wait_for_port_file` が待ち続けず `RuntimeError` になること（Edge 不使用の単体） | E2E が並走しても混線しない | 未 |
| 39 | `test_pdftosvg_app_flow_e2e.py::test_click_after_offpage_drag_and_overlay_select_selects_in_one_click`、`test_pdftosvg_rect_overlay_js.py` の `ro` fixture の teardown | ページ外へはみ出すドラッグで枠線を置いた直後にその箱をクリックして選んでも `S.dragMoved` が消費されずに残らないこと（`window.__state` で直接確認）、続けて要素をクリックすれば1回で選べること（E2E）。`rect-overlay.js` 単体テストは `isActive` を `opts` で渡すだけで `S` を触らないため、teardown は共有の `edge_page` を汚さないよう `host` と `window.__ro` を消すだけでよい | オーバーレイの mousedown 経由でもクリック握り潰しが再発しない、テストの実行順に依存しない | 未 |
| 40 | `test_pdftosvg_app_flow_e2e.py::test_border_width_outside_the_html_range_is_rejected_and_the_input_is_restored` | 入力欄の `max` を越える太さを確定すると、JS が HTML の `min`/`max` を読んで弾き、入力欄を直前の妥当な値へ戻すこと（E2E） | 範囲外の太さがサーバへ届かず入力欄に残らない | 未 |
| 41 | `test_pdftosvg_rect_overlay_js.py::test_draw_syncs_the_delete_button_even_when_the_svg_is_missing` / `::test_draw_does_nothing_but_clear_when_not_active`、`test_pdftosvg_app_flow_e2e.py::test_delete_button_is_enabled_by_a_border_selection_and_disabled_right_after_deleting` / `::test_deleting_a_selected_border_restores_the_width_input_to_the_next_value` | `draw()` の早期 return でも押下可否を同期すること、`isActive()` が false なら RPC を呼ばず選択だけ解くこと（実ブラウザ単体）、削除直後に一覧の再取得を待たずボタンが無効に戻ること（E2E）、削除ボタンが選択を `clearSel` 経由で解き、入力欄が「次に置く値」へ戻ること（E2E） | 押下可否の同期に穴が無く、`rect-overlay.js` が `S` に依存しない | 未 |
| 42 | `test_web_rpc.py::test_state_counts_pending_candidates_and_reverted_matches` / `::test_state_counts_removed_borders_and_covers_per_page` / `::test_state_marks_scanned_pages_as_not_replaceable`、`test_pdftosvg_state_js.py::test_railpages_*` / `::test_nextmatched_*` / `::test_skipsphase2_only_when_every_page_is_scanned` / `::test_export_modes_are_page_all_spec_only` ほか | `state` が `matches2`（未適用の候補と戻した箇所を未置換として数える）・`edits3`（削除 / 枠線 / 上書きをページごとに数える）・`scanned` 列と件数を返すこと、レールの絞り込みの既定（手順 2 は「辞書に一致したページだけ」・手順 3 は「すべてのページ」）とスキャンページの除外、「次の一致ページ」の巡回、全ページがスキャンのときだけ `phaseAfterLoad()=3` / `phaseBeforeTrim()=1` / `stepAllowed(2)=false` になること、`landOnPhase2` が対象ページへ寄せること、書き出しモードが `page` / `all` / `spec` の 3 つだけであること | ページごとの確認を持たずに件数から画面を組み立てられ、手順 2 の省略が状態機械で閉じる | 未 |
| 43 | `test_pdftosvg_app_flow_e2e.py::test_all_scanned_pdf_shows_banner_and_skips_step2_without_a_dialog` / `::test_mixed_scanned_and_vector_pdfs_hide_scanned_rows_without_a_dialog` | 全ページ純スキャンなら手順 1 に常設バナーとファイルカードのバッジが出て、モーダルは出ず、「次へ」で止まらずに手順 3 へ進み、ステップバーの 2 が消え、手順 3 の「戻る」が手順 1 へ戻り、手順 4 のまとめに「対象外」が出ること。混在なら手順 2 へ進み、レールにスキャン行が無く表示ページがベクター側になること（E2E） | スキャン画像だけの PDF で手順 2 に迷い込まず、案内が常に画面に出ている | 未 |
| 44 | `test_pdftosvg_page_jump_js.py`、`test_pdftosvg_app_flow_e2e.py::test_page_jump_moves_by_number_and_arrows_including_pages_hidden_from_the_rail` / `::test_page_jump_file_select_resets_number_and_arrows_cross_files` | `resolveJump` がファイル内のページ番号を通し index へ変換し、範囲外は 1〜ページ数へ丸め、数字でない値は 1 とみなし、未知のファイルは -1 を返すこと（実ブラウザ単体）。実画面で番号入力・「移動」・前後ボタンによりページが変わり、レールの絞り込みに出ていないページへも移れること、ファイル選択を変えると番号と上限だけが戻り「移動」で確定すること、前後ボタンがファイルの境をまたぐこと（E2E） | レールに出ないページへも確実にたどり着ける | 未 |
