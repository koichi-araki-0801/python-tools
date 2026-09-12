# 画像 + 不可視 OCR 文字層の PDF に対する辞書置換の上書き描画 設計

## 背景

複合機でスキャンして「検索可能 PDF」にした文書は、ページ全体が 1 枚の画像で、その上に
OCR 結果の文字が不可視(PDF の文字描画モード 3)で重ねてある。利用者はこれを
「印刷 PDF」と呼んでいる。

現行の PdfToSvg はこの形態を想定していない。

- `engine/classify.py` はテキストが 10 文字以上あればベクターページとして扱う。OCR 層は
  文字を持つので、この形態は常にベクター扱いになる。
- ベクター扱いのページでは、`_text_element` が OCR 層の span を通常の `TextElement` として
  取り込み、`svg_exporter._text_to_svg` が可視の `<text>` として描く。結果として画像の中の
  文字の上に代替フォントの文字が重なって描かれる(二重描画)。実測で確認済み
  (PyMuPDF 1.28.2。`get_text("dict")` の span は描画モードを返さず、`get_texttrace()` の
  `type` だけが 3 を返す)。
- 辞書置換をしても、元の文字は画像の画素として残るため、置換後の文字と重なって読めない。

## 目的

1. 画像 + 不可視 OCR 文字層のページで辞書置換をしたとき、元の文字を画像の背景色の矩形で
   隠し、その上に置換後の文字を描く。
2. 置換していない OCR 文字を書き出し SVG に描かない(二重描画の解消)。ただし編集画面では
   クリック取り込みと確認一覧のマーカーが今までどおり効くようにする。
3. 不可視文字を持たない PDF の出力はバイト単位で変えない。
4. 元の文字が読み取れない(文字層が無い、または OCR が化けて辞書が当たらない)ページでは、
   利用者が範囲をドラッグして置換語を入れる手動の上書きへフォールバックできる。

## 決定事項

利用者との確認(dig)により、次を決定済みとする。

1. 自動の辞書置換で扱うのは「画像 + 不可視 OCR 文字層」の形態に限る。文字が
   アウトライン化(パス化)された PDF や文字層の無いスキャンは自動では扱わず、OCR は
   行わない(設計書 16.2 節の非対応を維持)。これらは手動の上書き(決定事項 15)で補う。
2. 隠す矩形の色は背景画像の画素から自動で採る。常に白にはしない(帯や塗りセルの上で
   白抜きの穴になる)。
3. 矩形はモデルに持たず、書き出し時に exporter が合成する。グレー化・切り出しと同じ
   「モデルは変えず、生成点で決める」方式である。
4. 「不可視」は要素単位で `TextElement` に記録する。ページ単位の判定値は保存せず、
   通知用の集計は要素から都度数える。
5. 置換していない不可視文字は、書き出しでは出さず、編集画面(`annotate=True`)では
   透明(`fill-opacity="0"`)で描く。
6. 置換後の文字のフォントは現行のフォント対応表(`fonts.map_font`)に任せる。OCR 層の
   フォント名は `Helvetica` 等のダミーが普通で、和文は `fallback_css` が BIZ UDPGothic を
   補う。
7. 置換後の文字色も背景画像から採る(最頻色の次に多い色)。OCR 層の色は黒のダミーで、
   白抜き文字の帯の上では黒だと読めない。
8. 色の採取は bbox 内部の画素を各チャンネル 16 階調に量子化して最頻色を取る
   (JPEG ノイズで最頻が割れるのを防ぐ)。
9. 画像デコードの資源上限と失敗時の扱いは `to_gray_image` に倣う。上限超過・壊れた
   画像・下に画像が無い場合は白背景/黒文字へ degrade し、件数を UI へ返す(黙って
   消さない)。
10. 矩形の合成は自動(不可視かつ置換済みの要素に常時)。ON/OFF のオプションは持たない。
11. グレー化時は矩形色・文字色とも `color_fn` を通す。切り出し時の要素の取捨は既存の
    bbox 交差判定のまま。
12. 検出は `state` の集計値でトースト通知する(`truncated` / `noBackground` と同じ経路)。
13. テスト用 PDF は `conftest.py` で PyMuPDF により生成する(実機の検索可能 PDF は
    コミットしない)。
14. 既存フィクスチャの期待値は更新しない。不可視文字を持たない PDF の出力バイト一致は
    既存テストで固定し、本機能のテストは別に足す。
15. 元の文字が読み取れない場合のフォールバックは手動の上書きとする。利用者が範囲を
    ドラッグし、置換語を入力する。矩形の色は自動置換と同じく背景画像から採り、置換語が
    空なら矩形だけを重ねる。
16. 手動の上書きはモデルに「不可視かつ置換済み扱いの `TextElement`」として持つ。矩形の
    採色・描画は自動置換と同じ exporter の経路を使い、追加・削除・Undo は枠線
    (`addBorder`)と同じ仕組みに乗せる。
17. 置いた手動の上書きは、角ハンドルで大きさを、本体のドラッグで位置を、入力欄で置換語を
    後から変えられる(いずれも Undo 可)。伸縮・移動はグレーモードの図矩形(`figure.js`)の
    ハンドル操作を流用する。

## 非目標

- アウトライン化された文字の自動復元、スキャンページ(`is_scanned`)への OCR。
- 明朝/ゴシックの利用者選択、矩形色・文字色の利用者指定。
- 画像の回転・傾き(`ImageElement.rect` への線形写像だけを扱う)と `clip_d` の考慮。
- 自動の矩形合成を切る ON/OFF オプション(`pageSvg` / `exportSvg` への切替引数)。

## 設計

### 1. 検出(`src/engine/pdf_engine.py`、`src/model/elements.py`)

`_extract_page` は既に `page.get_texttrace()` を seqno 照合の候補に使っている。ここで
各エントリの `type`(文字描画モード)も拾い、`seqno → 不可視か` の表を作る。

- 不可視とみなす描画モードは 3(描かない)と 7(クリップのみ)の 2 つ。
- 同一 seqno に可視と不可視のエントリが混在した場合は可視とする。
- span の seqno 照合(`_SeqnoIndex.match`)は変更しない。照合で得た seqno で表を引き、
  `TextElement.invisible` を立てる。
- 照合失敗(既定値が返る)と `_SeqnoIndex.degraded`(照合放棄)のときは可視扱いにする。
  現行動作へ倒す方向であり、誤って本物の文字を消さない。

`TextElement` に `invisible: bool = False` を 1 つ足す。`original_text` と同様に
`__post_init__` では触らない。`STATE_FIELDS` 相当の列挙(`DictRevertInfo` /
`ReplaceTextCommand`)には含めない。置換や戻しで変わらない属性だからである。

### 2. 書き出し(`src/export/svg_exporter.py`、新規 `src/export/cover.py`)

`_element_to_svg` の `TextElement` の枝を、`invisible` で次のように分ける。

| 状態 | `annotate=False`(書き出し) | `annotate=True`(編集画面) |
|---|---|---|
| 可視(従来) | 従来どおり `<text>` | 従来どおり `<text data-el>` |
| 不可視・未置換(`dict_match is None`) | 出さない | `<text fill-opacity="0" data-el>` |
| 不可視・置換済み | `<g><rect/><text/></g>` | `<g data-el><rect/><text/></g>` |

「置換済み」は `dict_match is not None` で判定する。手動の上書き(6 節)もこの枝を通り、
`text` が空なら `<rect/>` だけを出す(`<g>` で包む点は同じ)。

- 透明で描く `<text>` は `fill` を残したまま `fill-opacity="0"` を付ける。SVG の
  既定 `pointer-events="visiblePainted"` は `fill="none"` だと当たり判定から外れるが、
  不透明度 0 は当たる。PDF の描画モード 3 と同じ「見えないが選べる」になる。
- `<g>` で包むのは `_with_data_el` が「1 要素 = 1 開きタグ」を前提に最初の空白へ
  `data-el` を差すためである。`app.js` の `flashElement` / `highlightElement` /
  マーカー描画は `getBoundingClientRect` と `getBBox` を使っており、`<g>` でも動く。
- 矩形は要素の `bbox` そのまま(折返し畳み込みは合成領域)。余白は足さない。
- 文字の据え方は現行の置換枝(縦中央 `dominant-baseline="central"`、幅超過時のみ
  `textLength` で圧縮、収まれば中央据え)を流用する。フォントも `map_font` の結果のまま。
  文字色だけは `el.color` を使わず、採取した文字色に置き換える。
- 埋め込みフォントの収集(`text_els`)は、実際に `<text>` を出した要素だけを対象にする。
  書き出しで出さない不可視・未置換の要素は含めない。

`cover.py` は Pillow だけに依存する純粋関数のモジュールとする。

```python
MAX_COVER_IMAGE_PIXELS = 16_000_000   # grayscale.MAX_GRAY_IMAGE_PIXELS と同値
QUANT_SHIFT = 4                        # 各チャンネル 16 階調
MIN_CONTRAST = 48                      # 文字色と背景色のチャンネル差の最大がこれ未満なら黒/白へ倒す

@dataclass(frozen=True)
class CoverColors:
    background: str   # "#rrggbb"
    foreground: str   # "#rrggbb"
    fallback: bool    # True = 採れずに白/黒へ倒した

def sample_colors(pixels: "DecodedImage | None", img_rect: Rect, bbox: Rect) -> CoverColors
def decode_image(img_bytes: bytes, ext: str) -> "DecodedImage | None"
```

- `decode_image` は `Image.open` のヘッダで画素数を確かめ、`MAX_COVER_IMAGE_PIXELS` 超過と
  壊れた画像は `None` を返す(例外を外へ出さない)。RGB へ変換して保持する。
- `sample_colors` は `bbox` を `img_rect` からの線形写像で画素座標へ変換し、画像の範囲で
  クランプする。範囲が空なら fallback。
- 量子化した色の出現回数を数え、(件数の降順, 量子化値の昇順) で並べる。先頭が背景色、
  2 番目が文字色。代表色は量子化した箱の中心値を使う(決定的で、JPEG ノイズに引かれない)。
- 2 番目が無い、または背景色とのチャンネル差の最大が `MIN_CONTRAST` 未満なら、背景の
  輝度(Rec.601、`grayscale._luma` と同じ)が 128 以上で黒、未満で白を文字色にする。
  この倒しは `fallback=False`(背景色は採れている)。
- `pixels is None`(デコード不能・画像無し)は白背景/黒文字で `fallback=True`。

`page_to_svg` 側の組み立て:

- 採取元は「text の bbox の中心を含む `ImageElement` のうち z が最大のもの」。無ければ
  スキャンページの `page.background`(`RasterBackground`。手動の上書きで使う)。どちらも
  無ければ `pixels=None` として fallback。
- 画像のデコードは 1 回の `page_to_svg` 呼び出しの中で画像ごと 1 度(要素 id をキーにした
  ローカル辞書)。呼び出しをまたぐキャッシュは持たない(バイト列キーのキャッシュを
  `to_gray_image` が持つのは変換結果が大きいため。ここでは解決済みの色 2 つを要素ごとに
  計算するだけで、デコードは呼び出し内で済む)。
- 背景色・文字色は `color_fn` を通してから属性に載せる(グレー化で灰色になる)。
- 件数の返し方は `page_to_svg(..., report: Optional[ExportReport] = None)` とする。
  `ExportReport` は `cover_fallback: int = 0` を持つ dataclass で、渡されたときだけ exporter が
  加算する。exporter 自体は状態を持たない(呼び手が受け皿を渡す)。

### 3. 辞書(変更なし)

`plan_replacements` / `ReplaceTextCommand` / `RevertDictMatchCommand` / `dict_revert` は
変更しない。不可視文字も可視文字と同じく照合対象で、置換すると `dict_match` が付き、戻すと
消える。矩形の有無は `dict_match` の有無で決まるので、戻し・Undo の経路に矩形の処理を
足す必要が無い。

### 4. Web 層と UI(`src/web/rpc_methods.py`、`resources/web/app.js`)

自動置換に関する変更は次のとおり。手動の上書きは 6 節にまとめる。

- `rpc_state` に `ocrPages`(不可視文字を 1 つ以上持つページの数)を足す。`truncated` /
  `noBackground` と同じ集計の並びに置く。
- `pageSvg` の応答に `coverFallback`(そのページの描画で白へ倒した件数)を足す。
  `exportSvg` でも同じ受け皿を渡し、応答に載せる。
- `app.js`:
  - アップロード後の `state` で `ocrPages > 0` なら 1 回トースト
    「画像 + OCR 文字のページを N ページ検出しました。置換箇所は画像の上に矩形で上書きします」。
  - `pageSvg` / `exportSvg` の `coverFallback > 0` でトースト
    「背景色を採れなかった N 箇所は白で上書きしました」。
  - 文字クリック・マーカー・フラッシュは変更しない(`<g data-el>` と透明 `<text data-el>`
    で今の実装がそのまま動くことを E2E で確かめる)。

### 5. テスト

- `test/conftest.py` に `ocr_layer_pdf` を足す。ページ全面の画像(上部に有彩色の帯、
  下は白)+ `insert_text(render_mode=3)` の不可視文字 2 行(帯の上と白地の上)+ 可視文字
  1 行を PyMuPDF で生成する。
- `test_ocr_layer.py`(新規):
  - engine: 不可視 span に `invisible=True`、可視 span は `False`。
  - exporter: 未置換は `annotate=False` で `<text>` が出ず、`annotate=True` で
    `fill-opacity="0"` 付きで出る。置換後は `<g><rect><text>` の順で、`rect` の `fill` が
    帯色(量子化の箱の中心値)、白地では `#f8f8f8` 相当(量子化後の白の箱の中心値)になる。
    文字色は帯の上で黒/白の倒し、グレー化で `rect` / `text` とも灰色になる。
  - degrade: 画素上限を超える画像(モンキーパッチで上限を下げる)で白/黒になり
    `ExportReport.cover_fallback` が数えられる。
  - 既存 `vector_pdf` の出力は `annotate` の有無を問わず従来と一致(`invisible` が無ければ
    経路に入らない)。
- `test_cover.py`(新規、`cover.py` 単体): 量子化、同点解決の決定性、コントラスト不足時の
  黒/白の倒し、bbox のクランプ、画素上限、壊れた画像。
- `test_rpc_*`: `state.ocrPages` と `pageSvg.coverFallback`。
- E2E(`test/*.e2e.ts`): 透明文字のクリックで `dictSuggest` が飛ぶこと、置換後の `<g>` に
  マーカーが付くこと。

### 6. 手動の上書き(フォールバック)

元の文字が読み取れないページ(文字層が無い、または OCR の誤りで辞書が当たらない)では、
自動では場所も語も決められない。そこで利用者が範囲を指定して置換語を置く手動の経路を、
手順 3 の「枠線」ツールと同じ形で足す。

**モデル**: `TextElement` に `manual_cover: bool = False` を足す。手動の上書きは次の値を
持つ `TextElement` で、通常の要素と同じく `page.elements` に入る。

| 属性 | 値 |
|---|---|
| `bbox` / `origin_x` / `origin_y` | ドラッグした矩形(原点は矩形の左下) |
| `z` | ページ内の最大 z + 1(`addBorder` と同じ。元の文字とパスを必ず覆う) |
| `text` / `original_text` | 入力した置換語(空可) |
| `invisible` | `True` |
| `manual_cover` | `True` |
| `dict_match` | `DictMatch(source="", target=text)`(exporter の「置換済み」判定を通すため) |
| `dict_revert` | `None`(戻す対象ではない) |
| `font_family` / `weight` / `italic` | フォント名無しとして `fonts.map_font("", text)` の既定 |
| `font_size` | 矩形の高さ × 0.7 を 4〜200pt にクランプ |
| `color` | 使わない(採取した文字色で描く) |

**RPC** `addCover {fileIndex, pageInFile, rect, text}`: `rect` の検査は `addBorder` と同じ
(有限・ページ内・正の大きさ)。`text` は `sanitize_text` を通し、200 文字で切る。要素を
作って `AddElementCommand` で push する(Undo 可)。削除は手順 3 の選択ツールで要素を
選んで削除する既存経路(`DeleteCommand`)で、削除一覧には「上書き「語」」と出す
(`rpc_removedList` の `label`)。

**exporter**: 2 節の「不可視・置換済み」の枝をそのまま通る。色の採取元は 2 節のとおり
(画像 → スキャン背景 → 無ければ白/黒へ倒す)。アウトライン文字だけのベクターページでは
下に画像が無いので白になる。

**確認一覧・state**: `rpc_planPage` は `manual_cover` の要素を除く(辞書置換ではなく、
「戻す」の対象でもない)。`_page_has_replacements` は変更しない(`plan_replacements` は
`dict_match` 付きの要素を候補にしないため、手動の上書きが要確認に数えられることは無い
ことをテストで確かめる)。

**UI**: 手順 3 の `float-tools` に「上書き」ボタン(`data-tool="cover"`)を足す。
`border-opts` と同じ位置に `cover-opts`(置換語の入力欄 1 つ)を出し、ドラッグの mouseup で
`addCover` を呼ぶ。ドラッグの仕組み(`cropDrag` / ラバーバンド)は `border` と共用し、
`mode === "cover"` の分岐を足すだけにする。置換語は入力欄に残し、続けて複数箇所へ同じ語を
置けるようにする。ブラウザの `prompt()` は使わない(モーダルは拡張のイベントを止める)。

**移動・伸縮・置換語の変更**: 置いた上書きは、手順 3 で「上書き」ツールが選ばれている間、
`figure.js` の採用矩形(`.fig-cand.sel`)と同じ HTML オーバーレイ(角ハンドル 4 つ +
本体)で表示する。角ハンドルのドラッグで伸縮(掴んだ角を動かし反対の角は固定、
`MIN_SIZE_PT` 未満にしない、ページ内へクランプ)、本体のドラッグで移動(大きさを保ち
ページ内へクランプ)。mouseup で RPC `updateCover {fileIndex, pageInFile, elId, rect}` を呼び、
`afterEdit` で描き直す。ドラッグ中はオーバーレイだけを動かし、サーバへは mouseup の
1 回だけ送る。

置換語の変更は、オーバーレイをクリックして選ぶと `cover-opts` の入力欄にその上書きの語が
入り、Enter または欄からフォーカスが外れたとき(`change` イベント)に
`updateCover {fileIndex, pageInFile, elId, text}` を呼ぶ。語が変わらなければ呼ばない。
どの上書きも選んでいないときは、入力欄の語は次に置く上書きの語になる(既存の動作)。

- オーバーレイの元データは RPC `coverList {fileIndex, pageInFile}` が返す
  `[{elId, rect, text}]`(そのページの `manual_cover` かつ未削除の要素)。表示 SVG から
  座標を拾わず、モデルを正にする。
- `updateCover` は `rect` と `text` のどちらか一方以上を取る。`rect` の検査は `addBorder` と
  同じ、`text` の検査は `addCover` と同じ(`sanitize_text`、200 文字)。`elId` が
  `manual_cover` の `TextElement` でなければ拒否する。`UpdateCoverCommand`(新規)が
  `bbox` / `origin_x` / `origin_y` / `font_size`(`rect` を変えたときは新しい高さ × 0.7 で
  計算し直す)/ `text` / `original_text` / `dict_match`(`target` を新しい語にする)の新旧を
  控え、`redo` / `undo` で書き戻す。矩形色・文字色は書き出し時に新しい `bbox` から採り直され
  るので、コマンドは色を持たない。
- 「上書き」ツール以外(選択ツール等)のときはオーバーレイを出さず、要素は `<g data-el>`
  として通常のクリック選択・削除の対象になる。

**テスト**: `test_ocr_layer.py` に手動の上書きの節を足す。`addCover` が要素を作り
`pageSvg` に `<g data-el><rect><text>` が出ること、`text` 空なら `<rect>` だけ、`undo` で消える
こと、スキャンページで背景 PNG から採色すること、ベクターページ(画像無し)で白になり
`coverFallback` に数えられること、`planPage` に出ないこと、`removedList` のラベル。
`updateCover` で `rect` を渡すと `bbox` / `origin` / `font_size` が、`text` を渡すと `text` /
`dict_match.target` が変わり、`undo` でどちらも戻ること、`manual_cover` でない要素・ページ外の
`rect`・`rect` も `text` も無い呼び出しを拒否すること、`coverList` が削除済みを除くこと。
E2E で「上書き」ツールのドラッグ → 入力 → 描画までを 1 本、角ハンドルの伸縮と置換語の変更 →
描き直しを 1 本。

### 7. 文書

- `docs/pdf-to-svg/src/設計正典.md`: 中核原則に「不可視 OCR 文字層の扱い」を 1 項、
  セキュリティの資源上限に `MAX_COVER_IMAGE_PIXELS` を追記。
- `docs/pdf-to-svg/src/設計書.md`: 3.1 節(`invisible` / `manual_cover`)、4.1 節
  (texttrace の `type`)、5.1 節(不可視文字の 3 分岐と `cover.py`)、7.2 節(`ocrPages` /
  `coverFallback` / `addCover` / `coverList` / `updateCover`)、7.3 節(`AddElementCommand` と
  `UpdateCoverCommand`)、8 節(トースト・「上書き」ツール・ハンドル操作)。
- `docs/pdf-to-svg/src/操作手順書.md`(利用者向け): 手順 3 の「上書き」ツールの使い方。
- `docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`: 出力・テストの行を追加。
- `docs/_build/build_all.py` で HTML を再生成し、リリースの配布物を差し替える。

## 決定性と互換性

- 色の採取は量子化 → 件数 → 値の順序で決まり、同じ画像・同じ bbox なら同じ色になる。
- 不可視文字を持たない PDF は、新しい分岐に入らないため出力が従来とバイト一致する。
- `<g>` で包む要素は不可視・置換済みのときだけで、他の要素の直列化は変えない。
