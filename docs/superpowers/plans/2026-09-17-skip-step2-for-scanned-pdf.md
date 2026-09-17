# スキャン画像のみの PDF で手順 2 を省略する 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 文字要素を持たない純スキャンページ（`Page.is_scanned`）を手順 2「用語を置換」の対象外にし、全ページが対象外なら手順 1 の「次へ」でモーダルを出して手順 3 へ直行させる。

**Architecture:** サーバの `state` RPC がページ単位の `scanned[]` を返し、クライアント `state.js` の `status2` に 4 値目 `"na"`（置換対象外）を足して唯一の判定源にする。手順 2 のレール・ページ送り・一括操作は `"pending"` / `pass()` だけを見るので、`"na"` は自然に対象外になる。遷移（`phaseAfterLoad` / `stepAllowed` / 戻る先）はグレーモードと同じ 3 関数へ条件を足す。モーダルは本アプリ初の `<dialog>`。

**Tech Stack:** Python 3.13（標準ライブラリ HTTP サーバ・pytest・Playwright sync API）、vanilla JS（ES module）、HTML `<dialog>`。

**Spec:** 本計画はチャットで承認された設計（2026-09-17）を実装する。設計の要点は本書冒頭の Global Constraints と各タスクの Interfaces に転記済み。

## Global Constraints

- 「置換対象外」= `Page.is_scanned == True` のページのみ。OCR 文字層ページ（`TextElement.invisible`）は従来どおり手順 2 を通る。
- `status2` の値集合は `pending / reviewed / skipped / none / na` の 5 つ。`status3` に `na` は無い（手順 3 はスキャンページも編集対象）。
- `S.scanned[]` のような別配列は持たない。判定源は `status2 === "na"` だけ。
- `exportPageList` の `noskip` は変えない（スキャンページは背景画像として書き出す。手順 3 で置いた上書き・枠線も残る）。
- 手順 2 を省略したとき: ステップバーの 2 は非表示・クリック不可、「戻る」は 3→1、モーダルのボタンは「手順 3 へ進む」の 1 つ、Esc も同じ遷移。
- 混在時（一部だけスキャン）: モーダルは出さない。レールからスキャン行を消し、`S.page` がスキャンページなら手順 2 に入る 3 経路（次へ・戻る 3→2・ステップバー）で最初の対象ページへ差し替える。
- 読み込み直後のトーストは既存の `ocrPages` と同じ差分抑止（`degradedNoticed`）で出す。文言は「N ページはスキャン画像のため、用語の置換対象外です（手順 3 の「上書き」で置き換えられます）」。
- 手順 4 のまとめ: 「用語：確認 X / スキップ Y」に、`na` が 1 以上のときだけ「 / 対象外 N」を付ける。
- pytest は必ず `py -3.13 -m pytest <dir>` でディレクトリ個別指定（`pdf-to-svg`）。E2E は `-m e2e`。
- コミット時は pre-commit（`scripts/check_comments.py --staged`）と post-commit の auto-push（pre-push で pytest 4 ディレクトリ + E2E 2 種、約 2 分以上）が同期的に走る。Bash の `timeout` は 600000 を指定し、バックグラウンド実行にしない。
- コード内コメント・コミットメッセージ・ドキュメントは通常の日本語（genshijin 圧縮を適用しない）。既存の文体（`//` 行コメントで「なぜ」を書く）に合わせる。

---

## ファイル構成

| ファイル | 役割 | 変更 |
|---|---|---|
| `pdf-to-svg/src/web/rpc_methods.py` | `rpc_state` に `scanned[]` / `scannedPages` を追加 | 変更 |
| `pdf-to-svg/test/test_web_rpc.py` | 上記の単体テスト | 変更 |
| `pdf-to-svg/resources/web/state.js` | `"na"` 状態・`skipsPhase2` / `phaseBeforeTrim` / `landOnPhase2` の追加、遷移関数の条件追加 | 変更 |
| `pdf-to-svg/test/test_pdftosvg_state_js.py` | `state.js` の単体テスト（実ブラウザ） | 変更 |
| `pdf-to-svg/resources/web/rail.js` | 範囲指定の適用が `na` / `none` を触らないことを保証 | 変更 |
| `pdf-to-svg/resources/web/index.html` | `<dialog id="skip2-dialog">`、`#scan-skipnote` | 変更 |
| `pdf-to-svg/resources/web/styles.css` | `.stepbar.skip2` の非表示、`dialog` の見た目 | 変更 |
| `pdf-to-svg/resources/web/app.js` | `tryNext` / `back` / ステップバー / `reloadState` / `render` / まとめ表示 | 変更 |
| `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` | E2E 2 本（全スキャン・混在） | 変更 |
| `docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md` ほか原稿 4 冊 | 仕様・手引き・設計書・設計正典 | 変更 |
| `docs/pdf-to-svg/*.html` | `build_all.py` で再生成 | 再生成 |

---

### Task 1: サーバ `state` RPC が `scanned[]` と `scannedPages` を返す

**Files:**
- Modify: `pdf-to-svg/src/web/rpc_methods.py` （`rpc_state`。`changed3.append(True)` の直後と返り値 dict）
- Test: `pdf-to-svg/test/test_web_rpc.py` （`test_state_counts_pages_with_invisible_ocr_text` の直後に追加）

**Interfaces:**
- Produces: `state` RPC の返り値に `scanned: list[bool]`（`pages` と同じ長さ・同じ順）と `scannedPages: int`（`scanned` の True の数）が増える。Task 2 の `applyState(st)` が `st.scanned` を読む。Task 4 の `reloadState` が `st.scannedPages` を読む。

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_web_rpc.py` の `test_state_counts_pages_with_invisible_ocr_text` の直後に追加:

```python
def test_state_marks_scanned_pages_as_not_replaceable(session):
    """純スキャンページ (`is_scanned`) をページ単位の `scanned` 列と件数 `scannedPages` で返す。

    手順 2 の「置換対象外」の判定源はこの列だけ (クライアントは `status2 = "na"` に写す)。
    ベクターページは False。不可視 OCR 文字を持つページも `is_scanned` ではないので False
    (辞書が当たりうるため手順 2 を通す)。
    """
    doc = session.docs[0]
    scanned = Page(index=1, width_pt=200.0, height_pt=300.0, is_scanned=True)
    ocr = Page(index=2, width_pt=200.0, height_pt=300.0)
    ocr.elements = [TextElement(bbox=Rect(10, 10, 40, 12), text="OCR", invisible=True)]
    doc.pages.extend([scanned, ocr])
    st = rpc_methods.dispatch(session, "state", {})
    assert st["scanned"] == [False, True, False]
    assert st["scannedPages"] == 1
    # `scanned` は `pages` と添字で対応する (クライアントは添字で引く)
    assert len(st["scanned"]) == len(st["pages"])
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_web_rpc.py -k scanned_pages_as_not_replaceable -v`
Expected: FAIL with `KeyError: 'scanned'`

- [ ] **Step 3: 最小実装**

`pdf-to-svg/src/web/rpc_methods.py` の `rpc_state` を編集する。ループ内の `changed3.append(True)` の直後に 1 行:

```python
        for pi, pg in enumerate(d.pages):
            pages.append({"fileIndex": fi, "pageInFile": pi})
            # 手順2: 辞書置換が当たったページは「要確認」。
            changed2.append(_page_has_replacements(pg, s.store))
            # 手順3: トリミングは全ページが対象 (各ページを見て確認/スキップ)。
            changed3.append(True)
            # 手順2 の「置換対象外」: 文字要素を持たない純スキャンページ。辞書は構造的に
            # 当たらないので、クライアントはレールから外し全ページ該当なら手順 2 ごと省略する。
            # 不可視 OCR 文字のページは `is_scanned` ではない (辞書が当たりうる) ので含めない。
            scanned.append(bool(pg.is_scanned))
```

ループの前（`changed3: List[bool] = []` の直後）に `scanned: List[bool] = []` を宣言し、返り値 dict に次を足す（`"changed3": changed3,` の直後）:

```python
        "scanned": scanned,
        # `scanned` の True の数。`app.js` の `reloadState` が読み込み直後のトーストに使う
        # (`ocrPages` と同じ差分抑止の経路)。
        "scannedPages": sum(1 for x in scanned if x),
```

返り値の直前のコメント「クライアントの読者は files/pages/total/changed2/changed3 のみ」を
「files/pages/total/changed2/changed3/scanned のみ」に直す。

- [ ] **Step 4: テストが通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_web_rpc.py -v`
Expected: 全件 PASS（既存の `test_state` も含む）

- [ ] **Step 5: コミット**

```bash
cd /c/Users/caads/python-tools && git add pdf-to-svg/src/web/rpc_methods.py pdf-to-svg/test/test_web_rpc.py && git commit -m "feat(pdf-to-svg): state RPC が純スキャンページの scanned 列と scannedPages を返す

手順 2 の「置換対象外」判定の材料をサーバから渡す。判定源はこの列だけで、
クライアントは status2 の \"na\" に写す。"
```

（timeout 600000。post-commit の auto-push が pre-push 検証を同期実行する。）

---

### Task 2: `state.js` に `"na"` 状態と手順 2 省略の遷移を足す

**Files:**
- Modify: `pdf-to-svg/resources/web/state.js`
- Test: `pdf-to-svg/test/test_pdftosvg_state_js.py`

**Interfaces:**
- Consumes: `applyState(st)` の `st.scanned`（Task 1。省略時は全 false として扱う。既存テストの `RESET` は `scanned` を渡さない）。
- Produces（すべて `export` に追加）:
  - `initStatus(changed, scanned)` : `scanned[i]` が真なら `"na"`、それ以外は従来（`changed[i] ? "pending" : "none"`）。第 2 引数省略可。
  - `mergeStatus(changed, oldStatus, scanned)` : `scanned[i]` が真なら `"na"`。第 3 引数省略可。（既存はモジュール内関数。export に追加。）
  - `counts(arr)` の返り値に `na` を追加（`{done, skip, pend, none, na}`）。
  - `pass(st, filt)` : `st === "na"` なら `filt` に関わらず false。
  - `skipsPhase2()` : `S.TOTAL > 0 && S.status2.every(s => s === "na")`。
  - `phaseAfterLoad()` : `S.gray ? 4 : (skipsPhase2() ? 3 : 2)`。
  - `phaseBeforeTrim()` : 手順 3 の「戻る」の行き先。`skipsPhase2() ? 1 : 2`。
  - `stepAllowed(n)` : 既存の gray 条件に加え、`skipsPhase2() && n === 2` なら false。
  - `firstEditablePage2()` : `S.status2[i] !== "na"` の最小 i。無ければ 0。
  - `landOnPhase2()` : `S.status2[S.page] === "na"` なら `S.page = firstEditablePage2()`。手順 2 に入る全経路（Task 4）が呼ぶ。

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_pdftosvg_state_js.py` の末尾に追加:

```python
# ── 手順 2 の省略 (純スキャンページ = status2 "na") ──


def _apply_with_scanned(st, scanned, changed2=None):
    """5 ページ構成のまま `scanned` 列だけ差し替えて applyState する (RESET と同じページ列)。"""
    js(st, """(a) => window.__st.applyState({
        files: [{ name: "a.pdf", pages: 2 }, { name: "b.pdf", pages: 3 }],
        pages: [
          { fileIndex: 0, pageInFile: 0 }, { fileIndex: 0, pageInFile: 1 },
          { fileIndex: 1, pageInFile: 0 }, { fileIndex: 1, pageInFile: 1 }, { fileIndex: 1, pageInFile: 2 },
        ],
        total: 5,
        changed2: a.changed2, changed3: [false, false, false, false, false],
        scanned: a.scanned,
    })""", {"scanned": scanned, "changed2": changed2 or [True, False, True, True, False]})


def test_initstatus_marks_scanned_pages_na_regardless_of_changed(st):
    result = js(st, "window.__st.initStatus([true, false, true], [true, true, false])")
    assert result == ["na", "na", "pending"]
    # 第 2 引数を省略した既存の呼び方は従来どおり
    assert js(st, "window.__st.initStatus([true, false])") == ["pending", "none"]


def test_mergestatus_keeps_na_even_when_changed_flips(st):
    result = js(st, "window.__st.mergeStatus([true, true, false], ['reviewed', 'reviewed', 'none'], [true, false, false])")
    assert result == ["na", "reviewed", "none"]


def test_counts_tallies_na(st):
    result = js(st, "window.__st.counts(['na', 'pending', 'na', 'none'])")
    assert result == {"done": 0, "skip": 0, "pend": 1, "none": 1, "na": 2}


def test_pass_never_shows_na_even_for_all(st):
    assert js(st, "window.__st.pass('na', 'all')") is False
    assert js(st, "window.__st.pass('na', 'none')") is False
    assert js(st, "window.__st.pass('none', 'all')") is True


def test_applystate_without_scanned_column_has_no_na(st):
    # RESET は scanned を渡さない。旧サーバ・既存テストとの互換で全ページ非スキャン扱い
    assert js(st, "window.__st.S.status2.includes('na')") is False
    assert js(st, "window.__st.skipsPhase2()") is False


def test_applystate_maps_scanned_to_na_and_preserves_status_on_reload(st):
    _apply_with_scanned(st, [True, False, False, False, True])
    assert js(st, "window.__st.S.status2") == ["na", "none", "pending", "pending", "na"]
    js(st, "window.__st.S.status2[2] = 'reviewed'")
    # 同じページ列で再取得しても na は na のまま、確認済みも引き継ぐ
    _apply_with_scanned(st, [True, False, False, False, True])
    assert js(st, "window.__st.S.status2") == ["na", "none", "reviewed", "pending", "na"]


def test_skipsphase2_only_when_every_page_is_na(st):
    _apply_with_scanned(st, [True, True, True, True, True])
    assert js(st, "window.__st.skipsPhase2()") is True
    assert js(st, "window.__st.phaseAfterLoad()") == 3
    assert js(st, "window.__st.phaseBeforeTrim()") == 1
    assert js(st, "[1,2,3,4].map(n => window.__st.stepAllowed(n))") == [True, False, True, True]
    _apply_with_scanned(st, [True, True, True, True, False])
    assert js(st, "window.__st.skipsPhase2()") is False
    assert js(st, "window.__st.phaseAfterLoad()") == 2
    assert js(st, "window.__st.phaseBeforeTrim()") == 2
    assert js(st, "[1,2,3,4].map(n => window.__st.stepAllowed(n))") == [True, True, True, True]


def test_skipsphase2_is_false_with_no_pages(st):
    js(st, "window.__st.applyState({ files: [], pages: [], total: 0, changed2: [], changed3: [], scanned: [] })")
    assert js(st, "window.__st.skipsPhase2()") is False


def test_gray_mode_wins_over_skipsphase2(st):
    _apply_with_scanned(st, [True, True, True, True, True])
    js(st, "window.__st.S.gray = true")
    assert js(st, "window.__st.phaseAfterLoad()") == 4
    assert js(st, "[1,2,3,4].map(n => window.__st.stepAllowed(n))") == [True, False, False, True]


def test_landonphase2_moves_off_a_scanned_page_to_the_first_editable_one(st):
    _apply_with_scanned(st, [True, True, False, True, False])
    js(st, "window.__st.S.page = 0; window.__st.landOnPhase2()")
    assert js(st, "window.__st.S.page") == 2
    # 対象ページに居るときは動かさない (戻ったときに見ていたページを保つ)
    js(st, "window.__st.S.page = 4; window.__st.landOnPhase2()")
    assert js(st, "window.__st.S.page") == 4
    assert js(st, "window.__st.firstEditablePage2()") == 2


def test_nextpending_and_firstpending_never_land_on_na(st):
    _apply_with_scanned(st, [True, False, True, False, True], [True, True, True, True, True])
    assert js(st, "window.__st.S.status2") == ["na", "pending", "na", "pending", "na"]
    js(st, "window.__st.S.page = 1")
    assert js(st, "window.__st.nextPending(window.__st.S.status2)") == 3
    assert js(st, "window.__st.firstPending(window.__st.S.status2)") == 1


def test_export_noskip_keeps_na_pages(st):
    _apply_with_scanned(st, [True, False, False, False, False])
    js(st, "window.__st.S.status2[1] = 'skipped'; window.__st.S.expMode = 'noskip'")
    pages = js(st, "window.__st.exportPageList('', () => [])")
    assert [p["pageInFile"] for p in pages if p["fileIndex"] == 0] == [0]
    assert len(pages) == 4
```

- [ ] **Step 2: テストが失敗することを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_state_js.py -k "na or skipsphase2 or landonphase2 or noskip_keeps or never_land" -v`
Expected: FAIL（`initStatus` が `na` を返さない、`skipsPhase2 is not a function` 等）

- [ ] **Step 3: 実装**

`pdf-to-svg/resources/web/state.js` を編集する。

(a) `S` の定義のコメントを更新（`status2: [], status3: [],` の行）:

```js
  status2: [], status3: [],     // ページごとの確認状態 (pending/reviewed/skipped/none。status2 のみ na = 置換対象外)
```

(b) `counts` に `na` を足す（既存の実装を確認して `none` と同じ形で加える）。現在の `counts` は `{done, skip, pend, none}` を返しているので、初期値と集計分岐に `na` を 1 つ足す:

```js
function counts(arr) {
  var c = { done: 0, skip: 0, pend: 0, none: 0, na: 0 };
  arr.forEach(function (s) {
    if (s === "reviewed") c.done++; else if (s === "skipped") c.skip++;
    else if (s === "pending") c.pend++; else if (s === "na") c.na++; else c.none++;
  });
  return c;
}
```

（既存の `counts` の本体が上と違う書き方なら、その書き方を保ったまま `na` の枝だけ足す。返り値のキー集合が `{done, skip, pend, none, na}` になることが要件。）

(c) `pass` と `initStatus`:

```js
// "na" (置換対象外 = 純スキャンページ) は「すべて」でもレールに出さない。手順 2 で見せない
// 根拠をここ 1 箇所に置く (レール・ファイル行の件数・全選択は全部 pass を通る)。
function pass(st, filt) { if (st === "na") return false; return filt === "all" ? true : st === filt; }
// scanned[i] が真なら changed に関わらず "na"。手順 3 の status3 は scanned を渡さないので na を持たない。
function initStatus(ch, scanned) {
  return ch.map(function (c, i) { return scanned && scanned[i] ? "na" : (c ? "pending" : "none"); });
}
```

(d) `mergeStatus` に第 3 引数:

```js
function mergeStatus(changed, oldStatus, scanned) {
  return changed.map(function (isChanged, i) {
    if (scanned && scanned[i]) return "na";   // スキャン判定はページの属性で変わらない
    var old = oldStatus[i];
    if (!isChanged) return "none";
    return old === "none" ? "pending" : old;
  });
}
```

(e) `applyState` 内の 2 箇所:

```js
  var scanned = st.scanned || [];   // 旧形式 (列なし) は全ページ非スキャン扱い
  if (samePages) {
    S.status2 = mergeStatus(S.changed2, oldStatus2, scanned);
    S.status3 = mergeStatus(S.changed3, oldStatus3);
  } else {
    S.status2 = initStatus(S.changed2, scanned); S.status3 = initStatus(S.changed3);
```

（`var scanned = ...` は `S.changed2 = st.changed2; S.changed3 = st.changed3;` の直後に置く。）

(f) 遷移関数（`phaseAfterLoad` / `phaseBeforeExport` / `stepAllowed` の並び）を置き換え・追加:

```js
/** 全ページが置換対象外 (純スキャン) か。ページが無ければ false (手順 1 の「次へ」は別途無効) */
function skipsPhase2() {
  return S.TOTAL > 0 && S.status2.every(function (s) { return s === "na"; });
}
/** 手順 1 の「次へ」の行き先。グレーモードが最優先、次に手順 2 の省略 */
function phaseAfterLoad() { return S.gray ? 4 : (skipsPhase2() ? 3 : 2); }
/** 手順 3 の「戻る」の行き先。手順 2 を省略していれば手順 1 へ */
function phaseBeforeTrim() { return skipsPhase2() ? 1 : 2; }
/** 手順 4 の「戻る」の行き先 */
function phaseBeforeExport() { return S.gray ? 1 : 3; }
/** ステップバーのクリックで移ってよい手順か */
function stepAllowed(n) {
  if (S.gray) return n === 1 || n === 4;
  if (skipsPhase2() && n === 2) return false;
  return true;
}
/** 手順 2 で表示してよい (置換対象外でない) 最初のページ。無ければ 0 */
function firstEditablePage2() {
  for (var i = 0; i < S.TOTAL; i++) if (S.status2[i] !== "na") return i;
  return 0;
}
/** 手順 2 に入る直前に呼ぶ。表示中のページが置換対象外ならレールに出ているページへ差し替える
 * (レールに無いページに立つと、キャンバスに画像だけが出て何の画面か分からない)。対象ページに
 * 居るときは動かさない (「戻る」で見ていたページを保つ)。 */
function landOnPhase2() { if (S.status2[S.page] === "na") S.page = firstEditablePage2(); }
```

(g) `export` に `mergeStatus, skipsPhase2, phaseBeforeTrim, firstEditablePage2, landOnPhase2` を追加。

- [ ] **Step 4: テストが通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_state_js.py -v`
Expected: 全件 PASS（既存 `test_pure_helpers_counts_tallies_by_status` は `na: 0` が増えるので期待値を `{"done": 1, "skip": 1, "pend": 2, "none": 1, "na": 0}` に更新する）

- [ ] **Step 5: 既存の JS スモークが壊れていないことを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_js_smoke.py -v`
Expected: PASS

- [ ] **Step 6: コミット**

```bash
cd /c/Users/caads/python-tools && git add pdf-to-svg/resources/web/state.js pdf-to-svg/test/test_pdftosvg_state_js.py && git commit -m "feat(pdf-to-svg): status2 に置換対象外 \"na\" を足し、全ページ該当なら手順 2 を省略する遷移を state.js に置く

純スキャンページは辞書が構造的に当たらないため手順 2 のレールから外す。
判定源は status2 だけで、別配列は持たない。"
```

---

### Task 3: レールの範囲指定が `na` / `none` の行を触らないことを保証する

**Files:**
- Modify: `pdf-to-svg/resources/web/rail.js`（`wireRail` の `[data-rg]` クリック処理、97〜106 行付近）
- Test: 既存の E2E ではカバーしにくいので、Task 4 の混在 E2E で「レールにスキャン行が無い」ことを確認する。本タスクはコードの読み取りと最小修正。

**Interfaces:**
- Consumes: `pass` / `counts`（Task 2）。
- Produces: なし（振る舞いの保証のみ）。

- [ ] **Step 1: 範囲指定の適用処理を読む**

Run: `sed -n 95,108p pdf-to-svg/resources/web/rail.js`

現状の該当行:

```js
    for (var pp = from; pp <= to; pp++) { var gg = start + (pp - 1); if (arr[gg] !== "none") arr[gg] = act; }
```

`"none"` は除外しているが `"na"` は除外していない。

- [ ] **Step 2: `na` も除外する**

上の行を次に置き換える:

```js
    // 変更なし・置換対象外 (純スキャン) は確認状態を持たないので範囲に含まれても書き換えない
    for (var pp = from; pp <= to; pp++) { var gg = start + (pp - 1); if (arr[gg] !== "none" && arr[gg] !== "na") arr[gg] = act; }
```

同様に `[data-skipall]`（未確認をまとめてスキップ）が `pending` だけを対象にしていることを確認する（`=== "pending"` なら変更不要）。

- [ ] **Step 3: 手順 2 のレール描画で `na` が出ないことを机上確認**

`buildRail` の行描画は `pass(arr[gg], filt)` を通した `idxs` だけを出す。Task 2 の `pass` が `na` を常に落とすので、行・ファイル行の件数 `fcount`・全選択 `visSelectable` のいずれにも `na` は現れない。ファイル内が全部 `na` ならファイル行ごと出ない（`idxs.length === 0` で return）。変更不要であることを確認してから次へ。

- [ ] **Step 4: コミット（変更があった場合のみ）**

```bash
cd /c/Users/caads/python-tools && git add pdf-to-svg/resources/web/rail.js && git commit -m "fix(pdf-to-svg): レールの範囲指定が置換対象外 (na) の行の確認状態を書き換えないようにする"
```

---

### Task 4: モーダル・ステップバー・遷移・通知・まとめ表示（`app.js` / `index.html` / `styles.css`）と E2E

**Files:**
- Modify: `pdf-to-svg/resources/web/index.html`（ステップバーの `#gray-skipnote` の隣、`#toast` の直前）
- Modify: `pdf-to-svg/resources/web/styles.css`（`.stepbar.gray-mode` の直後）
- Modify: `pdf-to-svg/resources/web/app.js`（import、`reloadState`、`renderSummary`、`render`、`tryNext`、`back`、`wireNav`）
- Test: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`（末尾に 2 本）

**Interfaces:**
- Consumes: `skipsPhase2` / `phaseBeforeTrim` / `landOnPhase2` / `counts(...).na`（Task 2）、`st.scannedPages`（Task 1）。
- Produces: DOM id `#skip2-dialog`（`<dialog>`）、`#skip2-n`（ページ数）、`#skip2-go`（ボタン）、`#scan-skipnote`（ステップバー注記）、`.stepbar.skip2`（手順 2 非表示クラス）。E2E はこれらの id で待つ。

- [ ] **Step 1: 失敗する E2E を書く**

`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` の末尾に追加:

```python
def test_all_scanned_pdf_skips_step2_via_dialog(e2e_page, scanned_pdf):
    """全ページが純スキャンなら、手順 1 の「次へ」でモーダルが出て手順 3 へ直行する。

    手順 2 はステップバーから消え、「戻る」は 3→1 になる。手順 4 のまとめには「対象外」が出る。
    """
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files(str(scanned_pdf))
    expect(page.locator("#filelist-count")).to_contain_text("1 ファイル", timeout=30_000)
    # 読み込み直後のトースト (混在時にも出る通知)
    expect(page.locator("#toast")).to_contain_text("1 ページはスキャン画像のため", timeout=30_000)
    # 読み込んだ時点でステップバーの 2 が消え、注記が出る (グレーモードと同じ見せ方)
    expect(page.locator('#stepbar .step[data-step="2"]')).to_be_hidden()
    expect(page.locator("#scan-skipnote")).to_be_visible()

    page.click("#btn-next")
    dialog = page.locator("#skip2-dialog")
    expect(dialog).to_be_visible()
    expect(dialog).to_contain_text("上書き")
    expect(page.locator("#skip2-n")).to_have_text("1")
    # モーダルの間は手順 1 のまま
    expect(page.locator('[data-screen="1"]')).to_have_class(re.compile("on"))
    page.click("#skip2-go")
    expect(dialog).to_be_hidden()
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
    expect(page.locator('#stepbar .step[data-step="2"]')).to_be_hidden()

    # 「戻る」は手順 1 へ (手順 2 を飛ばしたので)
    page.click("#btn-back")
    expect(page.locator('[data-screen="1"]')).to_have_class(re.compile("on"))
    # もう一度「次へ」→ Esc でもモーダルは閉じて手順 3 へ進む (ボタンと同じ遷移)
    page.click("#btn-next")
    expect(dialog).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))

    # 手順 3 は未確認のまま「書き出しへ」→ ガード → 未確認をスキップして手順 4
    page.click("#btn-next")
    expect(page.locator("#guard")).to_be_visible()
    page.click("#guard-skip")
    expect(page.locator('[data-screen="4"]')).to_have_class(re.compile("on"))
    expect(page.locator("#export-summary")).to_contain_text("対象外 1")
    # ステップバーの 2 はクリックしても手順 2 に入れない
    expect(page.locator('#stepbar .step[data-step="2"]')).to_be_hidden()
    # 手順 4 の「戻る」は手順 3 のまま (手順 2 の省略は 3→1 だけに効く)
    page.click("#btn-back")
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))


def test_mixed_scanned_and_vector_pdfs_hide_scanned_rows_without_a_dialog(e2e_page, scanned_pdf, vector_pdf):
    """スキャン PDF とベクター PDF が混在するときはモーダルを出さず手順 2 へ進む。

    スキャンページはレールに出ず、手順 2 に入った時点の表示ページはベクター側になる
    (スキャンを先に読み込んで通し index 0 がスキャンページになる構成で確かめる)。
    """
    page = e2e_page
    page.goto(f"/?token={TOKEN}")
    reset_session(page)
    with page.expect_file_chooser() as fc_info:
        page.click("#btn-pick")
    fc_info.value.set_files([str(scanned_pdf), str(vector_pdf)])
    expect(page.locator("#filelist-count")).to_contain_text("2 ファイル", timeout=30_000)
    expect(page.locator("#toast")).to_contain_text("1 ページはスキャン画像のため", timeout=30_000)
    # 混在ならステップバーの 2 は残る
    expect(page.locator('#stepbar .step[data-step="2"]')).to_be_visible()
    expect(page.locator("#scan-skipnote")).to_be_hidden()

    page.click("#btn-next")
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))
    expect(page.locator("#skip2-dialog")).to_be_hidden()
    # レールにはベクター PDF の 1 行だけ。スキャン PDF はファイル行ごと出ない
    expect(page.locator("#pagenav .pg-row2")).to_have_count(1)
    expect(page.locator("#pagenav .pl-file")).to_have_count(1)
    expect(page.locator("#pagenav .pl-file")).to_contain_text("vector_sample.pdf")
    # 表示中のページはスキャンページ (通し 0) ではなくベクター側
    expect(page.locator("#pgnav-2")).to_contain_text("vector_sample.pdf")
    assert page.evaluate("() => window.__state.page") == 1
    assert page.evaluate("() => window.__state.status2") == ["na", "none"]
    # 手順 2 上部のまとめにも「対象外 1」
    expect(page.locator("#sum-2")).to_contain_text("対象外 1")

    # 手順 3 へ進み、戻ると手順 2 のベクターページに戻る (3→2 のまま)
    page.click("#btn-next")
    expect(page.locator('[data-screen="3"]')).to_have_class(re.compile("on"))
    page.click("#btn-back")
    expect(page.locator('[data-screen="2"]')).to_have_class(re.compile("on"))
    assert page.evaluate("() => window.__state.page") == 1
```

注意: `window.__state` は `app.js` 末尾で `S` そのものを公開している（`window.__state = S`）。`S.page` は `window.__state.page` で読む。

- [ ] **Step 2: E2E が失敗することを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py -m e2e -k "all_scanned or mixed_scanned" -v`
Expected: FAIL（`#scan-skipnote` / `#skip2-dialog` が見つからない）

- [ ] **Step 3: `index.html` に注記とダイアログを足す**

ステップバーの `<span class="skipnote" id="gray-skipnote" hidden>手順 2・3 は省略されます</span>` の直後に:

```html
    <span class="skipnote" id="scan-skipnote" hidden>手順 2 は省略されます（スキャン画像のみのため）</span>
```

`<div class="toast" id="toast" ...>` の直前に:

```html
  <!-- 全ページが純スキャン (文字を持たない画像だけ) のとき、手順 1 の「次へ」で出す案内。
       閉じる操作 (ボタン・Esc) はすべて手順 3 への遷移として扱う (`app.js` の `wireNav`)。 -->
  <dialog class="notice" id="skip2-dialog" aria-labelledby="skip2-title">
    <h2 id="skip2-title">用語の置換ができるページがありません</h2>
    <p>読み込んだ <b id="skip2-n">0</b> ページはすべてスキャン画像で、置き換えられる文字を持ちません。手順 2「用語を置換」は省略します。</p>
    <p>文字の置き換えは、手順 3 の<b>「上書き」</b>ツールで矩形と置換語を置いて行えます。</p>
    <div class="actions"><button class="btn primary" id="skip2-go" autofocus>手順 3 へ進む</button></div>
  </dialog>
```

- [ ] **Step 4: `styles.css` に見た目を足す**

`.stepbar .skipnote { ... }` の直後に:

```css
/* 手順 2 の省略 (全ページが純スキャン)。グレーモードの `.gray-mode` と同じ隠し方で手順 2 だけ消す */
.stepbar.skip2 .step[data-step="2"], .stepbar.skip2 .step[data-step="2"] + .step-sep { display: none; }

/* 案内モーダル (本アプリで唯一の `<dialog>`)。色・角丸はガードバー / パネルに合わせる */
dialog.notice { border: 1px solid var(--border-strong); border-radius: 12px; padding: 22px 26px; max-width: 460px; color: var(--ink); background: #fff; box-shadow: 0 18px 48px rgba(0,0,0,.18); }
dialog.notice::backdrop { background: rgba(20, 24, 32, .35); }
dialog.notice h2 { margin: 0 0 10px; font-size: 16px; font-weight: 700; }
dialog.notice p { margin: 0 0 10px; font-size: 13px; line-height: 1.65; color: var(--muted); }
dialog.notice p b { color: var(--ink); }
dialog.notice .actions { display: flex; justify-content: flex-end; margin-top: 16px; }
```

`--border-strong` / `--muted` / `--ink` は `:root`（`styles.css` 39 行〜）に定義済み。

- [ ] **Step 5: `app.js` を編集する**

(a) import に追加（`phaseAfterLoad, phaseBeforeExport, stepAllowed,` の行）:

```js
  phaseAfterLoad, phaseBeforeExport, phaseBeforeTrim, stepAllowed, skipsPhase2, landOnPhase2,
```

(b) `reloadState`: `degradedNoticed` に `scannedPages: 0` を足し、`ocrPages` の分岐の直後に:

```js
    if (st.scannedPages && st.scannedPages !== degradedNoticed.scannedPages) {
      msgs.push(st.scannedPages + " ページはスキャン画像のため、用語の置換対象外です（手順 3 の「上書き」で置き換えられます）");
    }
```

と `degradedNoticed.scannedPages = st.scannedPages || 0;`。

(c) `renderSummary`: 末尾の「変更なし」の項目の後に、`na` があるときだけ 1 項目:

```js
      '<span class="si"><span class="d pend" style="background:var(--border-strong)"></span>変更なし <b>' + c.none + "</b></span>" +
      (c.na ? '<span class="si"><span class="d pend" style="background:var(--border-strong)"></span>対象外 <b>' + c.na + "</b></span>" : "");
```

(d) `render()`: `document.getElementById("gray-skipnote").hidden = !S.gray;` の直後に:

```js
    // 手順 2 の省略 (全ページが純スキャン)。グレーモード中はそちらの注記だけ出す
    var skip2 = !S.gray && skipsPhase2();
    stepbar.classList.toggle("skip2", skip2);
    document.getElementById("scan-skipnote").hidden = !skip2;
```

手順 1 のヒント（`setHint(S.TOTAL ? "「次へ」で用語の置換に進みます" : ...)`）を:

```js
      setHint(!S.TOTAL ? "変換するPDFを選びます"
        : (skipsPhase2() && !S.gray) ? "「次へ」で削除・枠線の編集に進みます（スキャン画像のみのため用語の置換は省略）"
        : "「次へ」で用語の置換に進みます");
```

手順 4 のまとめ（`"用語：確認 " + s2.done + " / スキップ " + s2.skip +`）を:

```js
        "用語：確認 " + s2.done + " / スキップ " + s2.skip + (s2.na ? " / 対象外 " + s2.na : "") +
```

(e) `tryNext` の phase 1 分岐:

```js
    if (S.phase === 1) {
      if (!S.TOTAL) return;
      if (!S.gray && skipsPhase2()) {
        // 全ページが純スキャン: 理由と代替手段 (手順 3 の上書き) を読ませてから進む。
        // 遷移は dialog の close ハンドラ (`wireNav`) が行う (ボタンと Esc を同じ経路にする)
        document.getElementById("skip2-n").textContent = S.TOTAL;
        document.getElementById("skip2-dialog").showModal();
        return;
      }
      S.phase = phaseAfterLoad(); S.page = 0; S.guarding = false; resetPhaseUi();
      if (S.phase === 2) landOnPhase2();
      render();
      if (S.gray) prefetchFigCand();
      return;
    }
```

(f) `back`:

```js
  function back() {
    S.guarding = false;
    resetPhaseUi();
    if (S.phase === 2) S.phase = 1;
    else if (S.phase === 3) S.phase = phaseBeforeTrim();
    else if (S.phase === 4) S.phase = phaseBeforeExport();
    if (S.phase === 2) landOnPhase2();
    render();
  }
```

(g) `wireNav` のステップバークリック: `S.guarding = false; S.phase = n; clearSel(); render();` を

```js
        S.guarding = false; S.phase = n; clearSel();
        if (n === 2) landOnPhase2();
        render();
```

(h) `wireNav` に dialog の配線を足す（`guard-skip` の直後）:

```js
    // 手順 2 省略の案内モーダル。ボタンも Esc も `close` に集約し、閉じたら手順 3 へ進む
    var skip2 = document.getElementById("skip2-dialog");
    document.getElementById("skip2-go").addEventListener("click", function () { skip2.close(); });
    skip2.addEventListener("close", function () {
      if (S.phase !== 1 || !S.TOTAL) return;   // 閉じる前にファイルを消した等の取りこぼし
      S.phase = 3; S.page = 0; S.guarding = false; resetPhaseUi(); render();
    });
```

- [ ] **Step 6: E2E が通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py -m e2e -k "all_scanned or mixed_scanned" -v`
Expected: 2 件 PASS

- [ ] **Step 7: 既存の通し E2E と単体を回して退行がないことを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -v` と `py -3.13 -m pytest pdf-to-svg -v`
Expected: 全件 PASS（`test_four_step_flow` / `test_gray_figure_flow` / OCR 系が従来どおり通る）

- [ ] **Step 8: コミット**

```bash
cd /c/Users/caads/python-tools && git add pdf-to-svg/resources/web/app.js pdf-to-svg/resources/web/index.html pdf-to-svg/resources/web/styles.css pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py && git commit -m "feat(pdf-to-svg): 全ページがスキャン画像のときは案内モーダルを出して手順 2 を省略する

混在時はスキャンページを手順 2 のレールから外し、表示ページも対象ページへ寄せる。
読み込み直後のトーストと手順 4 のまとめに「対象外」の件数を出す。"
```

---

### Task 5: 原稿 4 冊の更新・HTML 再生成・リリース差し替え

**Files:**
- Modify: `docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`
- Modify: `docs/pdf-to-svg/src/操作手順書.md`
- Modify: `docs/pdf-to-svg/src/設計書.md`
- Modify: `docs/pdf-to-svg/src/設計正典.md`
- Regenerate: `docs/pdf-to-svg/PdfToSvg_手引き.html` / `PdfToSvg_設計.html`（`py -3.13 docs/_build/build_all.py`）

**Interfaces:**
- Consumes: Task 1〜4 の id・関数名・RPC 形。

- [ ] **Step 1: 仕様一覧に行を足す**

`docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`:

画面項目定義の `| 3.1 | 1. PDF選択 | 図だけをグレースケールで書き出す | ... |` の直後に:

```markdown
| 3.2 | 1. PDF選択 | 手順 2 省略の案内 | `#skip2-dialog` | 全ページが純スキャン（文字を持たない画像だけ）のとき「次へ」で表示。ボタン「手順 3 へ進む」（`#skip2-go`）・Esc のどちらでも閉じて手順 3 へ進む。ステップバーの 2 は非表示（`#scan-skipnote`）・クリック不可、手順 3 の「戻る」は手順 1 へ |
| 3.3 | 1. PDF選択 | スキャンページの通知 | `#toast` | 読み込み直後に「N ページはスキャン画像のため、用語の置換対象外です」。混在時も出る |
```

手順 2 の項目（`| 4 | 2. 用語置換 | ページプレビュー | ...` の前後）に:

```markdown
| 4.1 | 2. 用語置換 | ページレール | `#pagenav` | 純スキャンページ（`status2 = "na"`）は「すべて」の絞り込みでも行を出さない。上部のまとめ（`#sum-2`）に「対象外 N」 |
```

手順 4 の書き出し項目に「まとめ（`#export-summary`）: 用語：確認 X / スキップ Y / 対象外 N（N は 1 以上のときだけ）」を 1 行足す（既存の番号体系に合わせて枝番を付ける）。

RPC 表の `state` の行（`grep -n "\`state\`" docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md` で探す）に「`scanned: bool[]`（ページ単位の純スキャン判定）と `scannedPages`（件数）を返す」を追記。

テスト表の末尾（No 41 の次）に:

```markdown
| 42 | `test_web_rpc.py::test_state_marks_scanned_pages_as_not_replaceable`、`test_pdftosvg_state_js.py::test_skipsphase2_only_when_every_page_is_na` ほか | `state` が純スキャンページの `scanned` 列と件数を返すこと、`status2` の `na` が `changed2` に関わらず付き再取得でも保たれること、`pass` が `na` を「すべて」でも落とすこと、全ページ `na` のときだけ `phaseAfterLoad()=3` / `phaseBeforeTrim()=1` / `stepAllowed(2)=false` になること、`landOnPhase2` が対象ページへ寄せること、`noskip` 書き出しが `na` を落とさないこと | 純スキャンページの判定源が 1 本で、手順 2 の省略が状態機械で閉じる | 未 |
| 43 | `test_pdftosvg_app_flow_e2e.py::test_all_scanned_pdf_skips_step2_via_dialog` / `::test_mixed_scanned_and_vector_pdfs_hide_scanned_rows_without_a_dialog` | 全ページ純スキャンなら「次へ」で `#skip2-dialog` が出てボタン・Esc のどちらでも手順 3 へ進み、ステップバーの 2 が消え、手順 3 の「戻る」が手順 1 へ戻り、手順 4 のまとめに「対象外」が出ること。混在ならモーダルを出さず手順 2 へ進み、レールにスキャン行が無く表示ページがベクター側になること（E2E） | スキャン画像だけの PDF で手順 2 に迷い込まない | 未 |
```

- [ ] **Step 2: 操作手順書に節を足す**

`docs/pdf-to-svg/src/操作手順書.md` の 3 章「ステップ 1」の `> [!INFO] 複合機でスキャンして...` の直後に:

```markdown
> [!INFO] 選んだ PDF が**スキャン画像だけ**（文字をまったく持たない PDF）のときは、読み込み直後に「N ページはスキャン画像のため、用語の置換対象外です」と通知が出ます。辞書による置き換えはできないため、「次へ」を押すとステップ 2 を省略する案内が表示され、**「手順 3 へ進む」** でステップ 3 に直接進みます。文字を置き換えたいときは、ステップ 3 の「上書き」ツール（5.5 節）で矩形と置換語を置いてください。文字を持つ PDF と混ぜて選んだときは、スキャン画像のページだけがステップ 2 の一覧に出なくなります。
```

- [ ] **Step 3: 設計書に節を足す**

`docs/pdf-to-svg/src/設計書.md` の `## 8.1 グレーモード` 節の直後（`# 9. データ・設定・フォント` の前）に:

```markdown
## 8.2 手順 2 の省略（純スキャンページは置換対象外）

文字要素を持たない純スキャンページ（`Page.is_scanned`。2.x 節の判定）は辞書が構造的に当たらない。手順 2「用語を置換」でそのページを見せても利用者にできることが無く、全ページが該当するときは手順そのものが空になる。手動の上書き（8 章の `manual_cover`）が置換の代替手段として使えるようになったため、手順 2 を省略して手順 3 へ誘導する。

**判定源**: サーバの `state` RPC が `changed2` と同じ長さの `scanned: bool[]`（`Page.is_scanned`）と件数 `scannedPages` を返す。クライアントは `applyState` で `status2` の当該ページを `"na"`（置換対象外）にする（`initStatus(changed, scanned)` / `mergeStatus(changed, old, scanned)`。`scanned` はページの属性で変わらないため、再取得でも `"na"` のまま）。`status2` の値集合は `pending / reviewed / skipped / none / na` の 5 つになり、`status3` は従来の 4 つ（手順 3 はスキャンページも編集対象）。別配列 `S.scanned[]` は持たない（判定源が 2 本になると食い違う）。不可視 OCR 文字を持つページ（5.x 節）は `is_scanned` ではないので対象外にならない（OCR が正しければ辞書が当たる。外れたときの逃げ道が上書きツール）。

**レール・ページ送り**: `pass(st, filt)` が `"na"` を絞り込みに関わらず落とすため、レールの行・ファイル行の件数・全選択のいずれにも出ない。ファイル内が全部 `"na"` ならファイル行ごと出ない。`nextPending` / `firstPending` / 「未確認をまとめてスキップ」/ 範囲指定は `"pending"` だけを対象にするので `"na"` に着地しない。手順 2 に入る 3 経路（手順 1 の「次へ」・手順 3 の「戻る」・ステップバー）は `landOnPhase2()` を通し、表示中のページが `"na"` なら最初の対象ページ（`firstEditablePage2()`）へ差し替える（対象ページに居るときは動かさず、戻ったときに見ていたページを保つ）。

**遷移**: `skipsPhase2()` = ページが 1 つ以上あり `status2` がすべて `"na"`。`phaseAfterLoad()` は `gray ? 4 : (skipsPhase2() ? 3 : 2)`、手順 3 の「戻る」の行き先 `phaseBeforeTrim()` は `skipsPhase2() ? 1 : 2`、`stepAllowed(2)` は `skipsPhase2()` のとき false。グレーモードが常に優先する。手順 4 の「戻る」（`phaseBeforeExport`）は変えない。

**画面**: 読み込み直後に `scannedPages` の差分で「N ページはスキャン画像のため、用語の置換対象外です（手順 3 の「上書き」で置き換えられます）」をトースト（`ocrPages` と同じ `degradedNoticed` の抑止）。`skipsPhase2()` のときはステップバーの 2 を隠し（`.stepbar.skip2`）「手順 2 は省略されます（スキャン画像のみのため）」（`#scan-skipnote`）を出す。手順 1 の「次へ」は `<dialog id="skip2-dialog">`（本アプリで唯一のモーダル）を `showModal()` で開き、ボタン「手順 3 へ進む」（`#skip2-go`）と Esc のどちらも `close` イベントに集約して手順 3 へ遷移する（経路を 1 本にし、Esc だけ手順 1 に留まる非対称を作らない）。手順 2 上部のまとめ（`renderSummary`）と手順 4 のまとめ（`#export-summary`）は `"na"` が 1 以上のときだけ「対象外 N」を付ける。

**書き出し**: `exportPageList` の `noskip` は `skipped` だけを除外するので、スキャンページは背景画像として従来どおり書き出される。手順 3 で置いた上書き・枠線も残る（「スキップを除く」でスキャンページを落とす案は、上書きを置いたのに書き出されない退行になるため却下）。
```

`2.x 節` / `5.x 節` は実際の節番号を `grep -n "^## " docs/pdf-to-svg/src/設計書.md` で確認して置き換える。改訂履歴の表（冒頭）に「2.7 | 2026-09-17 | 手順 2 の省略（8.2）を新設、`state` RPC に `scanned` を追加」の行を足す。

- [ ] **Step 4: 設計正典に 1 項目足す**

`docs/pdf-to-svg/src/設計正典.md` の「中核原則」の末尾（「入力欄は『次に置く値』と…」の直後）に:

```markdown
- **純スキャンページは手順 2 の対象外にし、全ページ該当なら手順 2 を省略する**: 文字を持たない
  ページ（`Page.is_scanned`）は辞書が構造的に当たらない。`state` RPC の `scanned[]` を
  `status2` の `"na"` に写し、判定源はそれだけにする（別配列を持たない）。`"na"` はレールに
  出さず、全ページ `"na"` なら手順 1 の「次へ」で `<dialog>` を出して手順 3 へ直行する
  （`skipsPhase2` / `phaseAfterLoad` / `phaseBeforeTrim` / `stepAllowed`。グレーモードが優先）。
  不可視 OCR 文字のページは対象外にしない（辞書が当たりうる）。「スキップを除く」書き出しで
  スキャンページを落とさない（手順 3 で置いた上書きが書き出されなくなる）。
```

- [ ] **Step 5: HTML を再生成して差分を確認する**

Run: `cd /c/Users/caads/python-tools && py -3.13 docs/_build/build_all.py && git status --short docs/`
Expected: `docs/pdf-to-svg/PdfToSvg_手引き.html` と `PdfToSvg_設計.html` に差分。他プロジェクトの HTML には差分なし。

- [ ] **Step 6: docs のテストを回す**

Run: `py -3.13 -m pytest docs/_build -v`
Expected: PASS

- [ ] **Step 7: コミット**

```bash
cd /c/Users/caads/python-tools && git add docs/pdf-to-svg && git commit -m "docs(pdf-to-svg): 手順 2 の省略（純スキャンページ）を仕様一覧・手引き・設計書・設計正典に載せ HTML を再生成"
```

- [ ] **Step 8: リリースを現在の main へ差し替える**

既存タグを確認: `git tag --list '2026.*' | tail -3` と `gh release list --limit 3`。
最新の日付タグ `<TAG>` を HEAD へ動かし、ノートの「## 含まれる変更」配下の先頭に `###` 節を 1 つ追記する（既存の節は消さない。`## 検証` を二重にしない）:

```bash
cd /c/Users/caads/python-tools
git tag -f <TAG> $(git rev-parse HEAD)
git push origin -f refs/tags/<TAG>          # pre-push 検証が走る (timeout 600000)
gh release view <TAG> --json body -q .body > "$TMP/notes.md"
# notes.md の「## 含まれる変更」直後に次の ### 節を挿入して保存
gh release edit <TAG> --notes-file "$TMP/notes.md"
```

追記する節:

```markdown
### スキャン画像だけの PDF で手順 2 を省略（2026-09-17）

- 文字を持たない純スキャンページを手順 2「用語を置換」の対象外にし、レールに出さない。
- 全ページが対象外なら手順 1 の「次へ」で案内モーダルを出し、手順 3「削除・枠線の編集」へ直行する（上書きツールで置換）。
- 読み込み直後のトーストと手順 4 のまとめに「対象外」の件数を出す。
```

いずれかのコマンドが権限で拒否されたら、そこで止めて利用者に通常モードでの承認を依頼する（自動では再試行しない）。

---

## Self-Review

- 設計の各要件 → タスク: サーバ列（T1）／`na` と遷移（T2）／レール（T3）／モーダル・注記・トースト・まとめ・3 経路の `landOnPhase2`（T4）／E2E 2 本（T4）／文書・HTML・リリース（T5）。`noskip` 不変は T2 のテストで固定。
- プレースホルダ: なし。`2.x 節` / `5.x 節` / `<TAG>` は実行時に確認して埋める指示付き。
- 名前の整合: `skipsPhase2` / `phaseBeforeTrim` / `landOnPhase2` / `firstEditablePage2` / `scanned` / `scannedPages` / `#skip2-dialog` / `#skip2-go` / `#skip2-n` / `#scan-skipnote` / `.stepbar.skip2` を T2〜T5 で同じ綴りで使用。
