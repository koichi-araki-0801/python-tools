# PdfToSvg 手順 3 UI 改善 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 手順 3（削除・枠線の編集）で、置いた枠線を後から削除・移動・伸縮・色/太さ変更できるようにし、併せて「選択」タブの廃止・削除ボタンの無効化・手順 1 の説明文の改行を行う。

**Architecture:** 枠線は現在ただの `RectElement` としてページへ足されるだけで、利用者が置いたものかどうかを区別する印を持たない。手動の上書き（`TextElement.manual_cover`）と同じ流儀で `RectElement.manual_border` を足し、`borderList` / `updateBorder` の 2 本の RPC と `UpdateBorderCommand` を用意する。クライアント側は、既存の `cover.js` が持つ「矩形オーバーレイを重ねて移動・伸縮し、mouseup の 1 回だけ更新 RPC を送る」仕組みを `rect-overlay.js` へ括り出し、`cover.js` と新設の `border.js` がそれを共有する（複製すると必ず drift するため）。「選択」タブは廃止し、クリックでの要素選択をどのツール中でも効く既定動作にする。

**Tech Stack:** Python 3.13（標準ライブラリ + PyMuPDF）、素の ES モジュール JavaScript（フレームワーク無し）、pytest + Playwright（Edge チャネル）。

**Spec:** 本計画の「設計（承認済み）」節（brainstorming で合意し、bounded から計画作成へ昇格したもの）。

## 設計（承認済み）

1. **枠線の後編集**は上書きと同じオーバーレイ方式。枠線ツール中、既存の枠線に角ハンドル付きの箱を重ね、クリックで選択・ドラッグで移動・角ハンドルで伸縮する。色と太さの入力欄は、未選択なら「次に置く枠線」の値、選択中なら選択中の枠線を直接変える（`#cover-text` が `S.coverText` / `S.coverSel` でやっている振り分けと同じ）。削除は既存の削除ボタンへ相乗りする。
2. **「選択」タブの廃止**。タブは「範囲削除 / 枠線 / 上書き」の 3 つで、初期状態は無選択。無選択のときはドラッグが効かず、クリックでの要素選択だけができる。押下中のタブをもう一度押すと無選択へ戻る。クリックでの要素選択はどのツール中でも効く。
3. **削除ボタン**は位置を動かさず、何も選んでいない間は `disabled` にする。
4. **説明文の改行**。手順 1 のグレースケール説明文を「選んだ範囲だけを切り出し、」の直後で改行する。

## Global Constraints

- Python は常に `py -3.13` を明示して呼ぶ。
- **pytest の一括実行は禁止**。`py -3.13 -m pytest <dir>` の形で対象ディレクトリを個別に指定する（本計画で使うのは `pdf-to-svg` のみ）。
- `xdist` / `pytest-randomly` を入れない。
- 新規スクリプトは Python 第一。`.ps1` の新規追加は禁止。
- 本リポのブランチ運用は **main への直接コミット**。トピックブランチを作らない。
- コミットすると post-commit フックが auto-push を試み、pre-push フックが `pytest scripts` → `pytest docs/_build` → `pytest pdf-to-svg` → `pytest graph-editor` → `pytest pdf-to-svg -m e2e` → `pytest graph-editor -m e2e` を順に走らせる。**コミット 1 回ごとにこの連鎖が同期的に走る**ので、コミット前にローカルで該当テストを通しておくこと。
- `origin_guard.py` と graph-editor `app.py` の並行実装（セキュリティヘッダ・トークン・資源上限・Edge 起動引数）には本計画は一切触れない。`test_parallel_impl_drift.py` の対象外。
- ドキュメント（`docs/` 配下の原稿）・コードコメント・コミットメッセージは通常の丁寧な日本語で書く。既存の文体・コメント規約に従う。
- コミットメッセージは Conventional Commits 形式。末尾に次の 2 行を付ける。

```
Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
```

  ただし `Co-Authored-By` の**モデル名は、実際にそのコミットを書いた実行主体のもの**にする
  （このタスクを別のモデルへ委譲して実装した場合は、そのモデル名が入るのが正しい）。
  この行は「誰が書いたか」の事実記録なので、上の例の `Claude Opus 5 (1M context)` を
  逐語で写す必要はない。`Claude-Session` の URL は常に上のとおり。各タスクのコミット手順に
  書いてある 2 行も同じ扱いとする。

## ファイル構成

| ファイル | 責務 | 変更の種類 |
|---|---|---|
| `pdf-to-svg/src/model/elements.py` | 要素の dataclass。`RectElement` に「利用者が置いた枠線」の印を足す | 変更 |
| `pdf-to-svg/src/web/commands.py` | Undo 可能なコマンド。`UpdateBorderCommand` を足す | 変更 |
| `pdf-to-svg/src/web/rpc_methods.py` | RPC の実体。`borderList` / `updateBorder` を足し、`addBorder` に印を付けさせる | 変更 |
| `pdf-to-svg/resources/web/rect-overlay.js` | 矩形オーバーレイの共通部分（箱の描画・選択・移動・伸縮・更新送信） | **新規** |
| `pdf-to-svg/resources/web/cover.js` | 上書き固有の部分（一覧の取り方・置換語の同期）だけを持つ形へ | 変更 |
| `pdf-to-svg/resources/web/border.js` | 枠線固有の部分（一覧の取り方・色/太さの同期） | **新規** |
| `pdf-to-svg/resources/web/state.js` | `S.borderSel` / `S.borderDrag` を足し、ツールの既定を無選択にする | 変更 |
| `pdf-to-svg/resources/web/app.js` | ツール切替・クリック選択・削除ボタンの有効無効 | 変更 |
| `pdf-to-svg/resources/web/index.html` | 「選択」タブの削除、手順 1 の説明文の改行 | 変更 |
| `pdf-to-svg/resources/web/styles.css` | `.border-box`（枠線オーバーレイの見た目） | 変更 |
| `pdf-to-svg/test/test_web_rpc.py` | RPC の単体テスト | 変更 |
| `pdf-to-svg/test/test_pdftosvg_state_js.py` | `state.js` の単体テスト | 変更 |
| `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` | 実 Edge の E2E | 変更 |
| `docs/pdf-to-svg/src/設計正典.md` ほか原稿 4 冊 | 設計・仕様・操作手順の原稿 | 変更 |
| `docs/pdf-to-svg/_build/capture_screens.py` | 操作手順書の画面写真の撮影 | 変更 |

---

### Task 1: 手順 1 の説明文を「切り出し、」で改行する

独立した 1 行の変更。先に片付けて、以降のタスクの diff から切り離す。

**Files:**
- Modify: `pdf-to-svg/resources/web/index.html:86`

**Interfaces:**
- Consumes: なし
- Produces: なし

- [ ] **Step 1: 現在の文言を確認する**

`pdf-to-svg/resources/web/index.html` の 86 行目を読む。次の 1 行である。

```html
              <div class="d">「当社のスチュワードシップ活動」の図を自動で見つけて候補にします。選んだ範囲だけを切り出し、文字・線・画像をすべてグレースケールにした SVG を書き出します。用語の置換と削除・枠線の手順は省略します。</div>
```

- [ ] **Step 2: 「切り出し、」の直後へ `<br>` を入れる**

```html
              <div class="d">「当社のスチュワードシップ活動」の図を自動で見つけて候補にします。選んだ範囲だけを切り出し、<br>文字・線・画像をすべてグレースケールにした SVG を書き出します。用語の置換と削除・枠線の手順は省略します。</div>
```

- [ ] **Step 3: コミット**

```bash
git add pdf-to-svg/resources/web/index.html
git commit -m "$(cat <<'EOF'
style(pdf-to-svg): グレースケールの説明文を読点で改行して読みやすくする

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

---

### Task 2: 枠線に「利用者が置いた」印を付ける（モデル + `addBorder`）

後編集の対象を特定できるようにする。ここは Python だけで完結し、UI からは見えない。

**Files:**
- Modify: `pdf-to-svg/src/model/elements.py:190-196`（`RectElement`）
- Modify: `pdf-to-svg/src/web/rpc_methods.py:476-500`（`rpc_addBorder`）
- Test: `pdf-to-svg/test/test_web_rpc.py`

**Interfaces:**
- Consumes: なし
- Produces: `RectElement.manual_border: bool`（既定 `False`。`rpc_addBorder` が作る要素だけ `True`）

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_web_rpc.py` の `test_add_border` の直後へ足す。

```python
def test_add_border_marks_the_element_as_a_manual_border(session):
    """枠線ツールで置いた矩形だけに「利用者が置いた」印が付く (PDF 由来の矩形には付かない)。"""
    page = session.page(0, 0)
    pdf_rects = [e for e in page.elements if e.kind == "rect"]
    assert all(getattr(e, "manual_border", False) is False for e in pdf_rects)
    rpc_methods.dispatch(session, "addBorder",
                         {"fileIndex": 0, "pageInFile": 0,
                          "rect": {"x": 5, "y": 5, "w": 100, "h": 80},
                          "color": "#ff0000", "width": 2})
    assert page.elements[-1].manual_border is True
```

- [ ] **Step 2: テストを走らせて失敗を確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_web_rpc.py::test_add_border_marks_the_element_as_a_manual_border -v`
Expected: FAIL（`AttributeError` か `assert False is True`）

- [ ] **Step 3: `RectElement` に印を足す**

`pdf-to-svg/src/model/elements.py` の `RectElement` を次にする。

```python
@dataclass
class RectElement(Element):
    kind: str = "rect"
    rect: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    stroke: Optional[str] = "#000000"
    fill: Optional[str] = None
    stroke_width: float = 1.0
    # 利用者が手順 3 の「枠線」ツールで置いた要素。後から選んで動かす・太さを変える
    # 対象をこれで特定する (PDF 由来の矩形は False のまま = 後編集の対象にしない)。
    # 手動の上書き (`TextElement.manual_cover`) と同じ流儀。
    manual_border: bool = False
```

- [ ] **Step 4: `rpc_addBorder` に印を付けさせる**

`pdf-to-svg/src/web/rpc_methods.py` の `rpc_addBorder` 末尾、`RectElement(...)` の生成を次にする。

```python
    el = RectElement(
        bbox=rect, z=z, rect=rect, stroke=color, fill=None, stroke_width=width,
        manual_border=True,
    )
```

- [ ] **Step 5: テストが通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_web_rpc.py -v`
Expected: PASS（既存の `test_add_border` を含め全件）

- [ ] **Step 6: 書き出しが従来と一致することを確認する**

`manual_border` は書き出しに出てはいけない（`annotate=False` の出力はバイト一致が前提）。

Run: `py -3.13 -m pytest pdf-to-svg -x -q`
Expected: PASS（`test_pipeline.py` を含め全件）

- [ ] **Step 7: コミット**

```bash
git add pdf-to-svg/src/model/elements.py pdf-to-svg/src/web/rpc_methods.py pdf-to-svg/test/test_web_rpc.py
git commit -m "$(cat <<'EOF'
feat(pdf-to-svg): 利用者が置いた枠線に印を付けて後編集の対象を特定できるようにする

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

---

### Task 3: 枠線の一覧と変更の RPC（`borderList` / `updateBorder`）

`coverList` / `updateCover` の鏡像を作る。ここも Python だけで完結する。

**Files:**
- Modify: `pdf-to-svg/src/web/commands.py`（末尾に `UpdateBorderCommand`）
- Modify: `pdf-to-svg/src/web/rpc_methods.py`（`_border_width` / `_manual_border` / `rpc_borderList` / `rpc_updateBorder` / `HANDLERS` / import）
- Test: `pdf-to-svg/test/test_web_rpc.py`

**Interfaces:**
- Consumes: `RectElement.manual_border`（Task 2）
- Produces:
  - `UpdateBorderCommand(el: RectElement, rect: Optional[Rect], color: Optional[str], width: Optional[float])` — `label = "枠線の変更"`
  - RPC `borderList {fileIndex, pageInFile}` → `{"borders": [{"elId": int, "rect": {x,y,w,h}, "color": str, "width": float}]}`
  - RPC `updateBorder {fileIndex, pageInFile, elId, rect?, color?, width?}` → `{}`

- [ ] **Step 1: 失敗するテストを書く**

`pdf-to-svg/test/test_web_rpc.py` の Task 2 で足したテストの直後へ足す。

```python
def _place_border(session, *, color="#000000", width=1.0):
    """テスト用に枠線を 1 つ置き、その要素を返す。"""
    rpc_methods.dispatch(session, "addBorder",
                         {"fileIndex": 0, "pageInFile": 0,
                          "rect": {"x": 5, "y": 5, "w": 100, "h": 80},
                          "color": color, "width": width})
    return session.page(0, 0).elements[-1]


def test_border_list_returns_manual_borders_only(session):
    """一覧に出るのは利用者が置いた未削除の枠線だけ (PDF 由来の矩形は出ない)。"""
    el = _place_border(session, color="#ff0000", width=2)
    got = rpc_methods.dispatch(session, "borderList", {"fileIndex": 0, "pageInFile": 0})["borders"]
    assert got == [{"elId": el.id, "rect": {"x": 5.0, "y": 5.0, "w": 100.0, "h": 80.0},
                    "color": "#ff0000", "width": 2.0}]
    # 削除したら一覧から消える
    rpc_methods.dispatch(session, "applyDelete",
                         {"fileIndex": 0, "pageInFile": 0, "elIds": [el.id]})
    assert rpc_methods.dispatch(session, "borderList", {"fileIndex": 0, "pageInFile": 0})["borders"] == []


def test_update_border_changes_rect_color_and_width_and_undo_restores_them(session):
    """位置・色・太さを変えられ、Undo で元へ戻る。"""
    el = _place_border(session, color="#000000", width=1)
    rpc_methods.dispatch(session, "updateBorder",
                         {"fileIndex": 0, "pageInFile": 0, "elId": el.id,
                          "rect": {"x": 10, "y": 20, "w": 50, "h": 40},
                          "color": "#00ff00", "width": 3})
    assert el.stroke == "#00ff00" and el.stroke_width == 3.0
    assert (el.bbox.x, el.bbox.y, el.bbox.w, el.bbox.h) == (10.0, 20.0, 50.0, 40.0)
    assert (el.rect.x, el.rect.y, el.rect.w, el.rect.h) == (10.0, 20.0, 50.0, 40.0)
    rpc_methods.dispatch(session, "undo", {})
    assert el.stroke == "#000000" and el.stroke_width == 1.0
    assert (el.bbox.x, el.bbox.y, el.bbox.w, el.bbox.h) == (5.0, 5.0, 100.0, 80.0)


def test_update_border_accepts_width_alone(session):
    """太さだけを変えられる (矩形を送らずに済む)。"""
    el = _place_border(session, width=1)
    rpc_methods.dispatch(session, "updateBorder",
                         {"fileIndex": 0, "pageInFile": 0, "elId": el.id, "width": 4})
    assert el.stroke_width == 4.0
    assert (el.bbox.x, el.bbox.w) == (5.0, 100.0)  # 矩形は動かない


def test_update_border_requires_at_least_one_change(session):
    """何も指定しない `updateBorder` は拒否する (無変更の 1 段が Undo に積まれるのを防ぐ)。"""
    el = _place_border(session)
    with pytest.raises(ValueError):
        rpc_methods.dispatch(session, "updateBorder",
                             {"fileIndex": 0, "pageInFile": 0, "elId": el.id})


def test_update_border_rejects_a_deleted_border(session):
    """削除済みの枠線は書き換えない。"""
    el = _place_border(session)
    rpc_methods.dispatch(session, "applyDelete",
                         {"fileIndex": 0, "pageInFile": 0, "elIds": [el.id]})
    with pytest.raises(ValueError):
        rpc_methods.dispatch(session, "updateBorder",
                             {"fileIndex": 0, "pageInFile": 0, "elId": el.id, "width": 2})


def test_update_border_rejects_a_non_border_element(session):
    """PDF 由来の要素を `updateBorder` で書き換えられない。"""
    other = session.page(0, 0).live_elements()[0]
    with pytest.raises(ValueError):
        rpc_methods.dispatch(session, "updateBorder",
                             {"fileIndex": 0, "pageInFile": 0, "elId": other.id, "width": 2})


def test_update_border_rejects_a_rect_past_the_page_edge(session):
    """枠線は成果物に残るので、変更後もページ内を要求する (`addBorder` と同じ検査)。"""
    el = _place_border(session)
    with pytest.raises(ValueError):
        rpc_methods.dispatch(session, "updateBorder",
                             {"fileIndex": 0, "pageInFile": 0, "elId": el.id,
                              "rect": {"x": 150, "y": 250, "w": 200, "h": 200}})


@pytest.mark.parametrize("bad", [0, -1, 101, float("inf")])
def test_update_border_rejects_an_out_of_range_width(session, bad):
    """太さは `addBorder` と同じ範囲 (0 より大きく 100 以下・有限) を要求する。"""
    el = _place_border(session)
    with pytest.raises(ValueError):
        rpc_methods.dispatch(session, "updateBorder",
                             {"fileIndex": 0, "pageInFile": 0, "elId": el.id, "width": bad})
```

- [ ] **Step 2: テストを走らせて失敗を確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_web_rpc.py -k border -v`
Expected: FAIL（`KeyError: 'borderList'` — `HANDLERS` に無い）

- [ ] **Step 3: `UpdateBorderCommand` を書く**

`pdf-to-svg/src/web/commands.py` の `UpdateCoverCommand` の直後へ足す。`RectElement` の import も足すこと（ファイル冒頭の import 行に `RectElement` を加える）。

```python
class UpdateBorderCommand:
    """利用者が置いた枠線 (`RectElement.manual_border`) の位置・大きさ・色・太さを変える。

    `RectElement` は外枠 (`bbox`) と描画する矩形 (`rect`) の 2 つを持ち、枠線ではこの 2 つが
    常に同じ値である (`rpc_addBorder` が同じ `Rect` を両方へ入れる)。片方だけ書き換えると
    書き出しの見た目と、範囲削除の交差判定が食い違うので、必ず対で書き換える。
    """

    def __init__(self, el: RectElement, rect: Optional[Rect], color: Optional[str], width: Optional[float]):
        self.label = "枠線の変更"
        self.el = el
        self.new_rect = rect
        self.new_color = color
        self.new_width = width
        self.old_bbox = el.bbox
        self.old_rect = el.rect
        self.old_color = el.stroke
        self.old_width = el.stroke_width

    def redo(self) -> None:
        if self.new_rect is not None:
            self.el.bbox = self.new_rect
            self.el.rect = self.new_rect
        if self.new_color is not None:
            self.el.stroke = self.new_color
        if self.new_width is not None:
            self.el.stroke_width = self.new_width

    def undo(self) -> None:
        self.el.bbox = self.old_bbox
        self.el.rect = self.old_rect
        self.el.stroke = self.old_color
        self.el.stroke_width = self.old_width
```

- [ ] **Step 4: 太さ検査を関数へ括り出し、`rpc_addBorder` をそれに乗せ換える**

`pdf-to-svg/src/web/rpc_methods.py` の `rpc_addBorder` の直前へ `_border_width` を置き、`rpc_addBorder` 内の太さ検査をこの呼び出しに置き換える。検査を 2 箇所に書くと `addBorder` と `updateBorder` で許す範囲がずれる。

```python
def _border_width(args: dict) -> float:
    """``args["width"]`` を枠線の太さ (pt) にする。外部由来なので範囲を見る —
    ``float()`` は ``inf`` / ``nan`` を通し、``_fmt`` がそれを書いて SVG が壊れる。
    ``addBorder`` と ``updateBorder`` が同じ検査を共有する (片方だけ緩むのを防ぐ)。"""
    width = float(args.get("width") or 1.0)
    if not math.isfinite(width) or not (0 < width <= 100):
        raise ValueError(f"width must be a finite number in (0, 100]: {width!r}")
    return width
```

`rpc_addBorder` の該当行（`width = float(...)` と続く 2 行の検査）を次の 1 行にする。

```python
    width = _border_width(args)
```

- [ ] **Step 5: `_manual_border` / `rpc_borderList` / `rpc_updateBorder` を書く**

`rpc_addBorder` の直後（`MAX_COVER_TEXT_CHARS` の定義より前）へ足す。

```python
def _manual_border(pg: Page, el_id) -> RectElement:
    """ページ上の未削除の枠線 (利用者が置いたもの) を id で引く。それ以外は ``ValueError``。"""
    try:
        eid = int(el_id)
    except (TypeError, ValueError):
        raise ValueError(f"elId must be an integer: {el_id!r}") from None
    for e in pg.elements:
        if e.id == eid and isinstance(e, RectElement) and e.manual_border and not e.deleted:
            return e
    raise ValueError(f"elId {el_id!r} is not a manual border on this page")


def rpc_borderList(s: WebSession, args: dict) -> dict:
    """ページ上の枠線 (未削除) を要素の並び順で返す。UI のオーバーレイの元データ
    (表示 SVG から座標を拾わず、モデルを正にする)。"""
    pg = s.page(args["fileIndex"], args["pageInFile"])
    borders = [
        {
            "elId": e.id,
            "rect": {"x": e.bbox.x, "y": e.bbox.y, "w": e.bbox.w, "h": e.bbox.h},
            "color": e.stroke or "#000000",
            "width": e.stroke_width,
        }
        for e in pg.elements
        if isinstance(e, RectElement) and e.manual_border and not e.deleted
    ]
    return {"borders": borders}


def rpc_updateBorder(s: WebSession, args: dict) -> dict:
    """枠線の矩形 (`rect`)・色 (`color`)・太さ (`width`) のどれか以上を変える (Undo 可)。

    3 つとも省かれた呼び出しは拒否する。受け入れると変化の無い 1 段が Undo スタックへ積まれ、
    次の Ctrl+Z が「何も起きない」ように見える (`updateCover` と同じ方針)。
    """
    pg = s.page(args["fileIndex"], args["pageInFile"])
    el = _manual_border(pg, args.get("elId"))
    rect = _parse_rect_arg(args, "rect", pg)
    color = sanitize_color(args["color"]) if "color" in args else None
    width = _border_width(args) if "width" in args else None
    if rect is None and color is None and width is None:
        raise ValueError("rect, color or width is required")
    s.undo.push(UpdateBorderCommand(el, rect, color, width))
    return {}
```

- [ ] **Step 6: import と `HANDLERS` へ登録する**

`pdf-to-svg/src/web/rpc_methods.py` 冒頭のコマンド import へ `UpdateBorderCommand` を足す（アルファベット順で `UpdateCoverCommand` の前）。

```python
from web.commands import (
    AddElementCommand,
    DeleteCommand,
    ReplaceTextCommand,
    RestoreCommand,
    RevertDictMatchCommand,
    UpdateBorderCommand,
    UpdateCoverCommand,
)
```

`HANDLERS` の `"addBorder": rpc_addBorder,` の直後へ 2 行足す。

```python
    "addBorder": rpc_addBorder,
    "borderList": rpc_borderList,
    "updateBorder": rpc_updateBorder,
```

- [ ] **Step 7: テストが通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_web_rpc.py -v`
Expected: PASS（全件）

- [ ] **Step 8: 既存テストの全件を確認する**

Run: `py -3.13 -m pytest pdf-to-svg -x -q`
Expected: PASS

- [ ] **Step 9: コミット**

```bash
git add pdf-to-svg/src/web/commands.py pdf-to-svg/src/web/rpc_methods.py pdf-to-svg/test/test_web_rpc.py
git commit -m "$(cat <<'EOF'
feat(pdf-to-svg): 置いた枠線の一覧取得と位置・色・太さの変更を RPC で行えるようにする

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

---

### Task 4: 矩形オーバーレイの共通部分を `rect-overlay.js` へ括り出す

枠線のオーバーレイを新規に書く前に、上書きのオーバーレイから共通部分を抜く。**このタスクは振る舞いを一切変えない**（既存の上書きの E2E がそのまま回帰テストになる）。

**Files:**
- Create: `pdf-to-svg/resources/web/rect-overlay.js`
- Modify: `pdf-to-svg/resources/web/cover.js`（全面的に書き換え）
- Test: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`（既存の上書き E2E をそのまま使う。新規追加なし）

**Interfaces:**
- Consumes: `geometry.js` の `clientToPage` / `copyRect` / `pageSizeOf` / `clampToPage` / `placeRect` / `MIN_SIZE_PT` / `resizeFromPointer` / `CORNER_HANDLES_HTML`
- Produces: `createRectOverlay(opts) -> { draw(host), installDrag(host), clearSel() }`
  - `opts.boxClass: string` — 箱の CSS クラス名（`"cover-box"` / `"border-box"`）
  - `opts.tool: string` — このオーバーレイを出すツール名（`"cover"` / `"border"`）
  - `opts.listRpc: string` / `opts.listKey: string` — 一覧 RPC 名と応答のキー
  - `opts.updateRpc: string` — 矩形更新 RPC 名
  - `opts.getSel() -> number|null` / `opts.setSel(id|null)` — 選択中の要素 id の出し入れ
  - `opts.getDrag() -> object|null` / `opts.setDrag(obj|null)` — ドラッグ状態の出し入れ
  - `opts.onSelect(item|null)` — 選択が変わったとき、入力欄を item に合わせる（未選択なら「次に置く値」へ戻す）
  - `opts.ui` — `{ rpc, afterEdit, pageOf }`（`app.js` が注入する既存の 3 つ）

- [ ] **Step 1: `rect-overlay.js` を書く**

`pdf-to-svg/resources/web/rect-overlay.js` を新規作成する。中身は既存 `cover.js` の `drawCoverOverlay` / `installCoverDrag` / `rectsNearlyEqual` / `JITTER_EPS_PT` を、上書き固有の名前を `opts` 経由に置き換えたもの。

```javascript
// =============================================================================
// rect-overlay.js — ページ上の矩形を HTML の箱で重ね、移動・角ハンドル伸縮させる共通部分
// =============================================================================
// 手順 3 の「上書き」(`cover.js`) と「枠線」(`border.js`) は、置いた矩形を後から選び・動かし・
// 大きさを変える点で同じ振る舞いをする。モデルを正とし (表示 SVG から座標を拾わない)、ドラッグ中は
// 箱だけを動かし、mouseup の 1 回だけ更新 RPC を送る、という流儀もそろえる。両者で違うのは
// 「どの一覧 RPC を引くか」「選択したとき入力欄に何を映すか」だけなので、それを `opts` で受け取る。
// 複製して 2 本持つと、片方だけ直した不具合がもう片方に残る。
// 矩形操作のヘルパ (`copyRect` / `pageSizeOf` / `clampToPage` / `placeRect` / `MIN_SIZE_PT` /
// `resizeFromPointer` / `CORNER_HANDLES_HTML`) は手順 4 の採用矩形と共通なので `geometry.js` から読む。
import { clientToPage, copyRect, pageSizeOf, clampToPage, placeRect, MIN_SIZE_PT, resizeFromPointer, CORNER_HANDLES_HTML } from "./geometry.js";
import { S } from "./state.js";

// ジッター判定のしきい値 (ページ座標 pt)。通常の表示倍率ではおおむね画面 1px 相当で、
// 意図した伸縮・移動 (数 pt 以上動く) までは無視しない。
var JITTER_EPS_PT = 1;

/** 2 矩形が `JITTER_EPS_PT` 未満の差しか無いか (クリックの手ブレとみなせるか) */
function rectsNearlyEqual(a, b) {
  return (
    Math.abs(a.x - b.x) < JITTER_EPS_PT && Math.abs(a.y - b.y) < JITTER_EPS_PT &&
    Math.abs(a.w - b.w) < JITTER_EPS_PT && Math.abs(a.h - b.h) < JITTER_EPS_PT
  );
}

/** 1 種類の矩形オーバーレイを作る。返り値の `draw` / `installDrag` / `clearSel` を呼び出し側が使う。 */
function createRectOverlay(opts) {
  var ui = opts.ui;

  /** 選択を解き、入力欄を「次に置く値」へ戻す。選択解除の経路 (ツール切替・空白クリック・
   *  ページ移動・選んでいた要素が消えた等) をここへ一元化し、選択中に編集した値が
   *  「次に置く値」へ紛れ込んだまま入力欄に残らないようにする。 */
  function clearSel() {
    opts.setSel(null);
    opts.onSelect(null);
  }

  /** 手順 3 で対象のツールが選ばれている間だけ、ページ上の矩形を箱で重ねる。呼ぶたびに描き直す */
  async function draw(host) {
    host.querySelectorAll("." + opts.boxClass).forEach(function (b) { b.remove(); });
    if (S.phase !== 3 || S.tool !== opts.tool) { clearSel(); return; }
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    var pg = ui.pageOf();
    var res = await ui.rpc(opts.listRpc, { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
    if (host.querySelector("svg") !== svgEl) return; // 取得中にページが変わった
    var items = res[opts.listKey] || [];
    var sel = opts.getSel();
    if (sel !== null && !items.some(function (c) { return c.elId === sel; })) clearSel();
    items.forEach(function (c) {
      var box = document.createElement("div");
      box.className = opts.boxClass + (c.elId === opts.getSel() ? " sel" : "");
      box.dataset.elId = c.elId;
      box.innerHTML = CORNER_HANDLES_HTML;
      placeRect(box, c.rect, svgEl, host);
      box.querySelectorAll(".h").forEach(function (h) {
        h.addEventListener("mousedown", function (e) {
          e.stopPropagation(); e.preventDefault();
          opts.setDrag({ mode: "resize", elId: c.elId, rect: copyRect(c.rect), orig: copyRect(c.rect), corner: h.dataset.corner, box: box, moved: false, item: c });
        });
      });
      box.addEventListener("mousedown", function (e) {
        e.stopPropagation(); e.preventDefault();
        opts.setDrag({ mode: "move", elId: c.elId, rect: copyRect(c.rect), orig: copyRect(c.rect), origin: { x: e.clientX, y: e.clientY }, box: box, moved: false, item: c });
      });
      box.addEventListener("click", function (e) { e.stopPropagation(); });
      host.appendChild(box);
    });
    var cur = items.find(function (c) { return c.elId === opts.getSel(); });
    if (cur) opts.onSelect(cur);
  }

  /** 移動・伸縮のドラッグ。起動時に一度だけ張る (多重登録防止) */
  function installDrag(host) {
    window.addEventListener("mousemove", function (e) {
      var d = opts.getDrag(); if (!d) return;
      var svgEl = host.querySelector("svg"); if (!svgEl) return;
      var sz = pageSizeOf(svgEl);
      d.moved = true;
      if (d.mode === "move") {
        var a = clientToPage(svgEl, d.origin.x, d.origin.y);
        var b = clientToPage(svgEl, e.clientX, e.clientY);
        var moved = { x: d.orig.x + (b.x - a.x), y: d.orig.y + (b.y - a.y), w: d.orig.w, h: d.orig.h };
        // 大きさを保ったままページ内へ収める
        moved.x = Math.max(0, Math.min(moved.x, sz.w - moved.w));
        moved.y = Math.max(0, Math.min(moved.y, sz.h - moved.h));
        d.rect = moved;
      } else {
        d.rect = resizeFromPointer(svgEl, d, e.clientX, e.clientY);
      }
      placeRect(d.box, d.rect, svgEl, host);
    });
    window.addEventListener("mouseup", async function () {
      var d = opts.getDrag(); if (!d) return;
      opts.setDrag(null);
      opts.setSel(d.elId);
      if (!d.moved) {
        // クリック = 選択だけ。一覧の再取得 (RPC 往復) を待って反映すると、その間に利用者が
        // 入力欄へ打ち始めた値を巻き戻してしまう (往復の完了が入力より遅れて着く競合)。
        // 選ぶだけなら mousedown 時点で拾った値で足りるので、待たずに即時反映する
        // (矩形・見た目は据え置きのままなので再取得も不要)。
        host.querySelectorAll("." + opts.boxClass).forEach(function (b) { b.classList.toggle("sel", b.dataset.elId === String(d.elId)); });
        opts.onSelect(d.item);
        return;
      }
      var svgEl = host.querySelector("svg"); if (!svgEl) return;
      var sz = pageSizeOf(svgEl);
      var r = clampToPage(d.rect, sz.w, sz.h);
      if (r.w < MIN_SIZE_PT || r.h < MIN_SIZE_PT) { await draw(host); return; }
      if (rectsNearlyEqual(r, d.orig)) {
        // `mousemove` は 1px のジッターでも `d.moved` を立てるため、結果の矩形が元と実質同じなら
        // クリック扱いにして更新 RPC を送らない。送ると変化の無い 1 段が Undo スタックへ積まれ、
        // 次の Ctrl+Z が「何も起きない」ように見える。
        await draw(host);
        return;
      }
      var pg = ui.pageOf();
      await ui.rpc(opts.updateRpc, { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elId: d.elId, rect: r });
      await ui.afterEdit();
    });
  }

  return { draw: draw, installDrag: installDrag, clearSel: clearSel };
}

export { createRectOverlay };
```

- [ ] **Step 2: `cover.js` を共通部分に乗せ換える**

`pdf-to-svg/resources/web/cover.js` を次の内容で置き換える。公開する関数名（`initCover` / `drawCoverOverlay` / `installCoverDrag` / `commitCoverText` / `clearCoverSel`）は変えない。`app.js` の import 行を触らずに済む。

```javascript
// =============================================================================
// cover.js — 手順 3「上書き」ツールのオーバーレイ (置換語の同期だけを持つ)
// =============================================================================
// 箱の描画・選択・移動・角ハンドル伸縮は `rect-overlay.js` と共有する。ここが持つのは
// 「上書き固有の部分」= どの一覧 RPC を引くか (`coverList`) と、選んだとき入力欄 (`#cover-text`) に
// 何を映すか、そして入力欄の確定 (`updateCover {text}`) だけ。
import { createRectOverlay } from "./rect-overlay.js";
import { S } from "./state.js";

let ui = null;      // { rpc, afterEdit, pageOf } を app.js が注入する
let overlay = null; // createRectOverlay の返り値

function initCover(deps) {
  ui = deps;
  overlay = createRectOverlay({
    ui: deps,
    boxClass: "cover-box",
    tool: "cover",
    listRpc: "coverList",
    listKey: "covers",
    updateRpc: "updateCover",
    getSel: function () { return S.coverSel; },
    setSel: function (id) { S.coverSel = id; },
    getDrag: function () { return S.coverDrag; },
    setDrag: function (d) { S.coverDrag = d; },
    onSelect: syncTextInput,
  });
}

/** 選んでいる上書きの語を入力欄へ。未選択 (`item === null`) なら「次に置く語」へ戻す */
function syncTextInput(item) {
  var input = document.getElementById("cover-text"); if (!input) return;
  input.value = item ? item.text : S.coverText;
}

function drawCoverOverlay(host) { return overlay.draw(host); }
function installCoverDrag(host) { return overlay.installDrag(host); }
function clearCoverSel() { overlay.clearSel(); }

/** 入力欄の確定 (Enter / change)。上書きを選んでいれば選択中の要素の語だけを変え、
 *  `S.coverText` (次に置く語) には触れない。未選択なら次に置く語を確定する。
 *  (選択中の編集で `S.coverText` を書き換えると、選択を解いたあとに置く上書きへ
 *  編集中の語が紛れ込む — `input` リスナーの選択有無ガードと対で守る) */
async function commitCoverText(text) {
  if (S.coverSel === null) { S.coverText = text; return; }
  var pg = ui.pageOf();
  var res = await ui.rpc("coverList", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
  var cur = (res.covers || []).find(function (c) { return c.elId === S.coverSel; });
  if (!cur || cur.text === text) return;
  await ui.rpc("updateCover", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elId: S.coverSel, text: text });
  await ui.afterEdit();
}

export { initCover, drawCoverOverlay, installCoverDrag, commitCoverText, clearCoverSel };
```

- [ ] **Step 3: 既存の上書き E2E が全部通ることを確認する**

振る舞いを変えていないので、既存テストがそのまま回帰テストになる。

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -k cover -v`
Expected: PASS（`test_manual_cover_tool_places_cover` ほか 6 件）

- [ ] **Step 4: 手順 3 の E2E 全件を確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add pdf-to-svg/resources/web/rect-overlay.js pdf-to-svg/resources/web/cover.js
git commit -m "$(cat <<'EOF'
refactor(pdf-to-svg): 矩形オーバーレイの共通部分を切り出して枠線と共有できるようにする

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

---

### Task 5: 枠線のオーバーレイ（`border.js` + 色・太さ入力欄の二面性）

**Files:**
- Create: `pdf-to-svg/resources/web/border.js`
- Modify: `pdf-to-svg/resources/web/state.js`（`borderSel` / `borderDrag`）
- Modify: `pdf-to-svg/resources/web/app.js`（import・初期化・描画フック・入力欄の配線・削除の相乗り）
- Modify: `pdf-to-svg/resources/web/styles.css`（`.border-box`）
- Test: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`

**Interfaces:**
- Consumes: RPC `borderList` / `updateBorder`（Task 3）、`createRectOverlay`（Task 4）
- Produces: `initBorder(deps)` / `drawBorderOverlay(host)` / `installBorderDrag(host)` / `commitBorderStyle(patch)` / `clearBorderSel()`
  - `commitBorderStyle({color?: string, width?: number})` — 枠線を選んでいれば選択中の枠線へ `updateBorder` を送る。未選択なら `S.borderColor` / `S.borderWidth`（次に置く枠線の値）を更新する
- Produces: `S.borderSel: number|null` / `S.borderDrag: object|null`

- [ ] **Step 1: 失敗する E2E を書く**

`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` の `test_manual_cover_delete_button_removes_cover_selected_with_cover_tool` の直前へ、ヘルパと 3 件を足す。

```python
def _place_border(page, width="2"):
    """枠線ツールでページ座標 (20,110)-(120,135) へ枠線を 1 つ置く。"""
    page.click('[data-tool="border"]')
    expect(page.locator("#border-opts")).to_be_visible()
    page.fill("#border-width", width)
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200
    page.mouse.move(box["x"] + 20 * sx, box["y"] + 110 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 120 * sx, box["y"] + 135 * sy, steps=5)
    page.mouse.up()
    expect(page.locator("#trim-stage .border-box")).to_have_count(1)


def test_border_overlay_resize_and_width_change(e2e_page, ocr_layer_pdf):
    """置いた枠線を角ハンドルで伸縮でき、選んでから太さを変えられる (どちらも Undo 可)。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    _place_border(page, width="2")
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200

    # 右下ハンドルで伸縮 → updateBorder(rect)
    overlay = page.locator("#trim-stage .border-box")
    h = overlay.locator(".h.se").bounding_box()
    page.mouse.move(h["x"] + h["width"] / 2, h["y"] + h["height"] / 2)
    page.mouse.down()
    page.mouse.move(h["x"] + 40 * sx, h["y"] + 20 * sy, steps=5)
    page.mouse.up()
    rect = page.evaluate("""async () => (await window.rpc("borderList", { fileIndex: 0, pageInFile: 0 })).borders[0].rect""")
    assert rect["w"] > 100 and rect["h"] > 25

    # オーバーレイをクリックして選び、太さを変える → updateBorder(width)
    page.locator("#trim-stage .border-box").click()
    expect(page.locator("#border-width")).to_have_value("2")
    page.fill("#border-width", "5")
    page.press("#border-width", "Enter")
    width = page.evaluate("""async () => (await window.rpc("borderList", { fileIndex: 0, pageInFile: 0 })).borders[0].width""")
    assert width == 5

    # Undo で太さが戻る
    page.keyboard.press("Control+z")
    width = page.evaluate("""async () => (await window.rpc("borderList", { fileIndex: 0, pageInFile: 0 })).borders[0].width""")
    assert width == 2


def test_border_selected_edit_does_not_leak_into_the_next_border(e2e_page, ocr_layer_pdf):
    """選択中に変えた太さが、選択を解いたあとに置く枠線へ紛れ込まない。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    _place_border(page, width="2")
    page.locator("#trim-stage .border-box").click()
    page.fill("#border-width", "7")
    page.press("#border-width", "Enter")

    # 空白をドラッグすると選択が解け、2 本目は「次に置く枠線」の太さ 2 で置かれる
    box = page.locator("#trim-stage svg").bounding_box()
    sx, sy = box["width"] / 300, box["height"] / 200
    page.mouse.move(box["x"] + 150 * sx, box["y"] + 40 * sy)
    page.mouse.down()
    page.mouse.move(box["x"] + 250 * sx, box["y"] + 80 * sy, steps=5)
    page.mouse.up()
    expect(page.locator("#trim-stage .border-box")).to_have_count(2)
    widths = page.evaluate("""async () => (await window.rpc("borderList", { fileIndex: 0, pageInFile: 0 })).borders.map(b => b.width)""")
    assert sorted(widths) == [2, 7]


def test_border_delete_button_removes_border_selected_with_border_tool(e2e_page, ocr_layer_pdf):
    """枠線ツールのままクリックで選んだ枠線を、「削除」ボタンで消せる。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    _place_border(page)
    page.locator("#trim-stage .border-box").click()
    expect(page.locator("#trim-stage .border-box.sel")).to_have_count(1)
    page.click("#btn-deletesel")
    expect(page.locator("#trim-stage .border-box")).to_have_count(0)
    borders = page.evaluate("""async () => (await window.rpc("borderList", { fileIndex: 0, pageInFile: 0 })).borders""")
    assert borders == []
```

- [ ] **Step 2: E2E を走らせて失敗を確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -k border -v`
Expected: FAIL（`.border-box` が 0 件のままタイムアウト）

- [ ] **Step 3: `state.js` に枠線の選択とドラッグ状態を足す**

`pdf-to-svg/resources/web/state.js` の `S` 定義、`borderWidth` の行の直後へ 2 行足す。

```javascript
  borderColor: "#000000",       // 枠線ツールの色 (未選択のとき = 次に置く枠線の色)
  borderWidth: 1,       // 枠線ツールの太さ (pt。未選択のとき = 次に置く枠線の太さ)
  borderSel: null,      // 枠線ツールで選んでいる要素 id (null = 未選択。入力欄は次に置く値)
  borderDrag: null,     // 枠線の移動・伸縮中の状態 (`border.js` が使う)
```

`resetPhaseUi` に枠線の選択解除を足す（ツールの既定は Task 6 で変える。ここでは触らない）。

```javascript
function resetPhaseUi() {
  S.elSel = {};
  S.coverSel = null;
  S.borderSel = null;
  S.tool = "select";
}
```

併せて関数のドキュメンテーションコメントの「要素の選択 (青枠)・上書きの選択 (緑枠)・ツールの 3 つ」を「要素の選択 (青枠)・上書きの選択 (緑枠)・枠線の選択・ツールの 4 つ」に直す。

- [ ] **Step 4: `border.js` を書く**

`pdf-to-svg/resources/web/border.js` を新規作成する。

```javascript
// =============================================================================
// border.js — 手順 3「枠線」ツールのオーバーレイ (色・太さの同期だけを持つ)
// =============================================================================
// 箱の描画・選択・移動・角ハンドル伸縮は `rect-overlay.js` と共有する。ここが持つのは
// 「枠線固有の部分」= どの一覧 RPC を引くか (`borderList`) と、選んだとき色・太さの入力欄に
// 何を映すか、そして入力欄の確定 (`updateBorder {color|width}`) だけ。
import { createRectOverlay } from "./rect-overlay.js";
import { S } from "./state.js";

let ui = null;      // { rpc, afterEdit, pageOf } を app.js が注入する
let overlay = null; // createRectOverlay の返り値

function initBorder(deps) {
  ui = deps;
  overlay = createRectOverlay({
    ui: deps,
    boxClass: "border-box",
    tool: "border",
    listRpc: "borderList",
    listKey: "borders",
    updateRpc: "updateBorder",
    getSel: function () { return S.borderSel; },
    setSel: function (id) { S.borderSel = id; },
    getDrag: function () { return S.borderDrag; },
    setDrag: function (d) { S.borderDrag = d; },
    onSelect: syncStyleInputs,
  });
}

/** 選んでいる枠線の色・太さを入力欄へ。未選択 (`item === null`) なら「次に置く枠線」の値へ戻す */
function syncStyleInputs(item) {
  var color = document.getElementById("border-color");
  var width = document.getElementById("border-width");
  if (color) color.value = item ? item.color : S.borderColor;
  if (width) width.value = String(item ? item.width : S.borderWidth);
}

function drawBorderOverlay(host) { return overlay.draw(host); }
function installBorderDrag(host) { return overlay.installDrag(host); }
function clearBorderSel() { overlay.clearSel(); }

/** 色・太さの確定。枠線を選んでいれば選択中の枠線だけを変え、「次に置く枠線」の値
 *  (`S.borderColor` / `S.borderWidth`) には触れない。未選択なら次に置く値を確定する。
 *  (選択中の編集で次に置く値を書き換えると、選択を解いたあとに置く枠線へ編集中の値が
 *  紛れ込む — `cover.js` の置換語と同じ守り方) */
async function commitBorderStyle(patch) {
  if (S.borderSel === null) {
    if (patch.color !== undefined) S.borderColor = patch.color;
    if (patch.width !== undefined) S.borderWidth = patch.width;
    return;
  }
  var pg = ui.pageOf();
  var res = await ui.rpc("borderList", { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile });
  var cur = (res.borders || []).find(function (b) { return b.elId === S.borderSel; });
  if (!cur) return;
  if (patch.color !== undefined && cur.color === patch.color) return;
  if (patch.width !== undefined && cur.width === patch.width) return;
  var args = { fileIndex: pg.fileIndex, pageInFile: pg.pageInFile, elId: S.borderSel };
  if (patch.color !== undefined) args.color = patch.color;
  if (patch.width !== undefined) args.width = patch.width;
  await ui.rpc("updateBorder", args);
  await ui.afterEdit();
}

export { initBorder, drawBorderOverlay, installBorderDrag, commitBorderStyle, clearBorderSel };
```

- [ ] **Step 5: `styles.css` に枠線オーバーレイの見た目を足す**

`pdf-to-svg/resources/web/styles.css` の `.cover-box .h.ne` の行の直後（`.border-opts input[type="color"]` の前）へ足す。枠線のアクセント色（`--accent`）で、上書き（`--good`）と見分けられるようにする。

```css
.border-box { position: absolute; border: 2px solid var(--accent); background: transparent; cursor: move; border-radius: 3px; box-sizing: border-box; }
.border-box.sel { box-shadow: 0 0 0 3px oklch(0.58 0.105 240 / 0.25); }
.border-box .h { position: absolute; width: 10px; height: 10px; background: #fff; border: 2px solid var(--accent); border-radius: 2px; }
.border-box .h.nw { left: -6px; top: -6px; cursor: nwse-resize; } .border-box .h.se { right: -6px; bottom: -6px; cursor: nwse-resize; }
.border-box .h.ne { right: -6px; top: -6px; cursor: nesw-resize; } .border-box .h.sw { left: -6px; bottom: -6px; cursor: nesw-resize; }
```

- [ ] **Step 6: `app.js` へ配線する**

1. import 行を足す（`cover.js` の import の直後）。

```javascript
import { initBorder, drawBorderOverlay, installBorderDrag, commitBorderStyle, clearBorderSel } from "./border.js";
```

2. `initCover(...)` を呼んでいる箇所を探し（`initFigure` / `initCover` が並んでいる初期化部）、その直後で同じ `deps` を渡して `initBorder` を呼ぶ。

3. `wireStatic` の `installCoverDrag(document.getElementById("trim-stage"));` の直後へ足す。

```javascript
    installBorderDrag(document.getElementById("trim-stage"));
```

4. `render()` の手順 3 ブロック、`mountPage` のコールバックへ足す。

```javascript
      mountPage(document.getElementById("trim-stage"), ed3, true, function () {
        wireTrimStage();
        drawCoverOverlay(document.getElementById("trim-stage"));
        drawBorderOverlay(document.getElementById("trim-stage"));
      });
```

5. ツール切替のハンドラで枠線の選択も解く。

```javascript
        S.elSel = {};
        clearCoverSel();
        clearBorderSel();
        render();
```

6. `installCropDrag` の mousedown で、枠線オーバーレイ上のドラッグを `border.js` へ譲り、空白クリックで選択を解く。既存の cover 用 2 行の隣へ足す。

```javascript
      if (e.target.closest(".cover-box") || e.target.closest(".border-box")) return; // オーバーレイ上の移動・伸縮・選択は cover.js / border.js が扱う
      if (!host.querySelector("svg")) return;
      if (S.tool === "cover") clearCoverSel(); // 上書きの空白クリックは選択解除 (新規追加のラバーバンドへ進む)
      if (S.tool === "border") clearBorderSel(); // 枠線も同様
```

7. 色・太さの入力欄の配線を、選択の有無で書き分ける形へ変える。`wireEditTools` の既存 2 行を次に置き換える。

```javascript
    // 枠線ツールの色・太さ。枠線を選んでいる間、入力欄は選択中の枠線の編集に使う。
    // `input` は未選択のときだけ「次に置く枠線」の値を直接更新する (選択中は触れない —
    // 触れると、選択を解いたあとに置く枠線へ編集中の値が紛れ込む)。確定 (`change`/Enter) は
    // `border.js` の `commitBorderStyle` へ渡し、選択の有無での書き分けもそちら 1 箇所に持たせる。
    var colorInput = document.getElementById("border-color");
    colorInput.addEventListener("input", function () { if (S.borderSel === null) S.borderColor = this.value; });
    colorInput.addEventListener("change", function () { commitBorderStyle({ color: this.value }); });
    var widthInput = document.getElementById("border-width");
    widthInput.addEventListener("input", function () {
      var v = parseFloat(this.value);
      if (!isNaN(v) && v > 0 && S.borderSel === null) S.borderWidth = v;
    });
    widthInput.addEventListener("change", function () {
      var v = parseFloat(this.value);
      if (!isNaN(v) && v > 0) commitBorderStyle({ width: v });
    });
    widthInput.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); this.blur(); } });
```

8. 削除ボタンへ枠線の選択を相乗りさせる。既存の cover の行の直後へ足す。

```javascript
      if (S.coverSel !== null && ids.indexOf(String(S.coverSel)) < 0) ids.push(String(S.coverSel));
      if (S.borderSel !== null && ids.indexOf(String(S.borderSel)) < 0) ids.push(String(S.borderSel));
```

- [ ] **Step 7: E2E が通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -k border -v`
Expected: PASS（新規 3 件）

- [ ] **Step 8: 手順 3 の E2E 全件を確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q`
Expected: PASS（上書きの既存 E2E を含む）

- [ ] **Step 9: コミット**

```bash
git add pdf-to-svg/resources/web/border.js pdf-to-svg/resources/web/state.js pdf-to-svg/resources/web/app.js pdf-to-svg/resources/web/styles.css pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py
git commit -m "$(cat <<'EOF'
feat(pdf-to-svg): 置いた枠線を後から選んで動かし、太さと色を変えられるようにする

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

---

### Task 6: 「選択」タブを廃止し、クリックでの要素選択を全ツール共通にする

**Files:**
- Modify: `pdf-to-svg/resources/web/index.html:166`（`data-tool="select"` のボタンを削除）
- Modify: `pdf-to-svg/resources/web/state.js`（`tool` の既定を `null` へ、`resetPhaseUi`）
- Modify: `pdf-to-svg/resources/web/app.js`（`wireTrimStage` のガード・ツール切替のトグル・ドラッグ直後のクリック無視）
- Modify: `pdf-to-svg/resources/web/styles.css`（`.editor.tool-select` を使っているセレクタの整理）
- Test: `pdf-to-svg/test/test_pdftosvg_state_js.py`、`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`

**Interfaces:**
- Consumes: `S.borderSel`（Task 5）
- Produces: `S.tool: "crop"|"border"|"cover"|null`（`null` = 無選択。ドラッグは効かず、クリックでの要素選択だけができる）
- Produces: `S.dragMoved: boolean`（ドラッグで矩形を引いた直後の click を握り潰すための一時フラグ）

- [ ] **Step 1: 失敗するテストを書く（`state.js` 単体）**

`pdf-to-svg/test/test_pdftosvg_state_js.py` の `RESET` の `m.S.tool = "select";` を次に変える。

```python
  m.S.tool = null; m.S.coverSel = null; m.S.borderSel = null; m.S.elSel = {};
```

`test_transition_resetphaseui_clears_element_and_cover_selection_and_tool` と `test_transition_advancephase_resets_selection_and_tool` を次に変える。

```python
def test_transition_resetphaseui_clears_element_and_cover_selection_and_tool(st):
    js(st, "window.__st.S.elSel = { '0:0': { e1: true } }")
    js(st, "window.__st.S.coverSel = 'c1'")
    js(st, "window.__st.S.borderSel = 'b1'")
    js(st, "window.__st.S.tool = 'cover'")
    js(st, "window.__st.resetPhaseUi()")
    assert js(st, "window.__st.S.elSel") == {}
    assert js(st, "window.__st.S.coverSel") is None
    assert js(st, "window.__st.S.borderSel") is None
    assert js(st, "window.__st.S.tool") is None


def test_transition_advancephase_resets_selection_and_tool(st):
    js(st, "window.__st.S.phase = 3")
    js(st, "window.__st.S.elSel = { '0:0': { e1: true } }")
    js(st, "window.__st.S.coverSel = 'c1'")
    js(st, "window.__st.S.borderSel = 'b1'")
    js(st, "window.__st.S.tool = 'crop'")
    js(st, "window.__st.advancePhase()")
    assert js(st, "window.__st.S.phase") == 4
    assert js(st, "window.__st.S.elSel") == {}
    assert js(st, "window.__st.S.coverSel") is None
    assert js(st, "window.__st.S.borderSel") is None
    assert js(st, "window.__st.S.tool") is None
```

- [ ] **Step 2: 失敗するテストを書く（E2E）**

同ファイルの `_select_visible_text` を次に変える（ツールを押さずにクリックで選べるようになる）。

```python
def _select_visible_text(page):
    """ツールを選ばないまま可視文字を 1 つクリックで選び、青枠 (`.sel-box`) が付くまで待つ。"""
    page.locator("#trim-stage svg [data-el]", has_text="visible text").first.click()
    expect(page.locator("#trim-stage .sel-box")).to_have_count(1)
```

`test_stepbar_back_to_step3_keeps_page_and_resets_tool` の末尾 3 行を次に変える。

```python
    expect(page.locator('.float-tools [data-tool][aria-pressed="true"]')).to_have_count(0)
    expect(page.locator("#cover-opts")).to_be_hidden()
```

さらに 2 件を足す（`test_switching_tool_clears_element_selection` の直後）。

```python
def test_element_click_selection_works_while_a_tool_is_active(e2e_page, ocr_layer_pdf):
    """「選択」タブが無くなっても、どのツール中でもクリックで要素を選んで削除できる。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="crop"]')
    page.locator("#trim-stage svg [data-el]", has_text="visible text").first.click()
    expect(page.locator("#trim-stage .sel-box")).to_have_count(1)
    page.click("#btn-deletesel")
    expect(page.locator("#trim-stage .sel-box")).to_have_count(0)
    expect(page.locator('#trim-stage svg [data-el]', has_text="visible text")).to_have_count(0)


def test_pressing_the_active_tool_again_returns_to_no_tool(e2e_page, ocr_layer_pdf):
    """押下中のタブをもう一度押すと無選択へ戻り、ツール固有の入力欄が消える。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    page.click('[data-tool="border"]')
    expect(page.locator("#border-opts")).to_be_visible()
    page.click('[data-tool="border"]')
    expect(page.locator("#border-opts")).to_be_hidden()
    expect(page.locator('.float-tools [data-tool][aria-pressed="true"]')).to_have_count(0)
```

- [ ] **Step 3: テストを走らせて失敗を確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_state_js.py -k "resetphaseui or advancephase" -v`
Expected: FAIL（`assert 'select' is None`）

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -k "click_selection or active_tool" -v`
Expected: FAIL

- [ ] **Step 4: 「選択」タブを削除する**

`pdf-to-svg/resources/web/index.html` の 166 行目、`data-tool="select"` の `<button>` 1 行をまるごと削除する。残るのは `crop` / `border` / `cover` の 3 つ。

- [ ] **Step 5: ツールの既定を無選択にする**

`pdf-to-svg/resources/web/state.js` の `S` 定義を変える。

```javascript
  tool: null,           // 手順3 ツール (null=無選択 / crop / border / cover)。無選択でもクリックでの要素選択は効く
```

`resetPhaseUi` も変える。

```javascript
function resetPhaseUi() {
  S.elSel = {};
  S.coverSel = null;
  S.borderSel = null;
  S.tool = null;
}
```

コメントの「ツールも『上書き』や『範囲削除』のまま始まってしまう」はそのまま意味が通る。

- [ ] **Step 6: クリックでの要素選択を全ツール共通にする**

`pdf-to-svg/resources/web/app.js` の `wireTrimStage` を次にする。

```javascript
  // 要素のクリック選択の結線。SVG は mountPage で毎回差し替わるため漏れない。
  // ツールを選んでいてもクリックは要素の選択に使う (ドラッグだけがツール固有の操作)。
  // crop/border/cover ドラッグのリスナーは wireStatic で一度だけ張る (多重登録防止)。
  function wireTrimStage() {
    var host = document.getElementById("trim-stage");
    var svgEl = host.querySelector("svg"); if (!svgEl) return;
    svgEl.addEventListener("click", function (e) {
      // ドラッグで矩形を引いた直後にも click は飛ぶ。そのまま拾うと、引き終わった位置の
      // 要素が意図せず選択される (範囲削除の直後に無関係な要素が青枠になる)。
      if (S.dragMoved) { S.dragMoved = false; return; }
      var t = e.target.closest("[data-el]"); if (!t) return;
      var id = t.getAttribute("data-el"); var sel = curElSel();
      if (sel[id]) delete sel[id]; else sel[id] = true;
      drawSelBoxes(host);
    });
  }
```

`installCropDrag` の mousedown 冒頭のガードを、無選択のときはラバーバンドを作らない形へ変え、ドラッグ開始でフラグを落とす。

```javascript
      if (S.phase !== 3 || (S.tool !== "crop" && S.tool !== "border" && S.tool !== "cover")) return;
      if (e.target.closest(".cover-box") || e.target.closest(".border-box")) return; // オーバーレイ上の移動・伸縮・選択は cover.js / border.js が扱う
      if (!host.querySelector("svg")) return;
      S.dragMoved = false;
```

mousemove で移動を記録する（既存の `if (!S.cropDrag) return;` の直後）。

```javascript
      if (!S.cropDrag) return;
      S.dragMoved = true;
```

`S.dragMoved` を `state.js` の `S` へ足す（`cropDrag` の直後）。

```javascript
  dragMoved: false,     // 直前の mouseup がドラッグ由来か (続けて飛ぶ click を握り潰す)
```

- [ ] **Step 7: 押下中のタブの再クリックで無選択へ戻す**

`wireEditTools` のツール切替を次にする。

```javascript
    app.querySelectorAll(".float-tools [data-tool]").forEach(function (b) {
      b.addEventListener("click", function () {
        // 押下中のタブをもう一度押したら無選択へ戻す (ドラッグ操作を止めてクリック選択だけにする)
        S.tool = S.tool === b.dataset.tool ? null : b.dataset.tool;
        // ツールを離れたら要素の選択 (青枠)・上書きの選択 (緑枠)・枠線の選択を解く。残すと複数の枠が
        // 同時に出て、「削除」が画面で選んだつもりの無い側まで消す
        S.elSel = {};
        clearCoverSel();
        clearBorderSel();
        render();
      });
    });
```

- [ ] **Step 8: `tool-select` クラスの扱いを直す**

`render()` の手順 3 ブロックから `ed3.classList.toggle("tool-select", S.tool === "select");` を削除する。`styles.css` の `.editor.tool-select .page-host [data-el] { cursor: pointer; }` は、どのツール中でも要素を指せることを示すため次に変える。

```css
  .editor .page-host [data-el] { cursor: pointer; }
```

この行は `index.html` 冒頭のインラインスタイル（32 行目付近）にある。`.editor.tool-crop` などの `cursor: crosshair` を指定した行より **後** に置くこと（ツール中はドラッグのカーソルを優先したいので、先に `crosshair` を当て、要素の上だけ `pointer` にする）。

- [ ] **Step 9: テストが通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg/test/test_pdftosvg_state_js.py -v`
Expected: PASS

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q`
Expected: PASS（書き換えた既存 3 件と新規 2 件を含む）

- [ ] **Step 10: コミット**

```bash
git add pdf-to-svg/resources/web/index.html pdf-to-svg/resources/web/state.js pdf-to-svg/resources/web/app.js pdf-to-svg/resources/web/styles.css pdf-to-svg/test/test_pdftosvg_state_js.py pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py
git commit -m "$(cat <<'EOF'
feat(pdf-to-svg): 選択タブを廃し、どのツール中でもクリックで要素を選べるようにする

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

---

### Task 7: 何も選んでいない間は削除ボタンを無効にする

**Files:**
- Modify: `pdf-to-svg/resources/web/app.js`（`render()` の手順 3 ブロック）
- Test: `pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py`

**Interfaces:**
- Consumes: `S.elSel` / `S.coverSel` / `S.borderSel`
- Produces: なし

- [ ] **Step 1: 失敗する E2E を書く**

`pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py` の Task 6 で足した 2 件の直後へ足す。

```python
def test_delete_button_is_disabled_until_something_is_selected(e2e_page, ocr_layer_pdf):
    """何も選んでいない間は「削除」ボタンを押せない (押しても何も起きない状態を見た目で示す)。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    expect(page.locator("#btn-deletesel")).to_be_disabled()
    _select_visible_text(page)
    expect(page.locator("#btn-deletesel")).to_be_enabled()
    page.click("#btn-deletesel")
    expect(page.locator("#trim-stage .sel-box")).to_have_count(0)
    expect(page.locator("#btn-deletesel")).to_be_disabled()


def test_delete_button_is_enabled_by_a_border_selection(e2e_page, ocr_layer_pdf):
    """枠線を選んだときも「削除」ボタンが有効になる。"""
    page = e2e_page
    _goto_step3(page, ocr_layer_pdf)
    _place_border(page)
    page.locator("#trim-stage .border-box").click()
    expect(page.locator("#btn-deletesel")).to_be_enabled()
```

- [ ] **Step 2: E2E を走らせて失敗を確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -k delete_button_is -v`
Expected: FAIL（常に enabled）

- [ ] **Step 3: 押下可否を決める関数を 1 本作る**

選択が変わる経路は 3 つ（`render()`・クリック選択・オーバーレイの選択）あり、同じ判定を 3 箇所へ書くと必ずずれる。`pdf-to-svg/resources/web/app.js` の `drawSelBoxes` の直前へ足す。

```javascript
  /** 「削除」ボタンの押下可否を今の選択から決める。要素 (青枠)・上書き (緑枠)・枠線のどれかを
   *  選んでいれば押せる。何も選んでいない間は押しても何も起きないので無効にする (押下可否で
   *  「いま何を選んでいるか」が分かる)。位置は動かさない — 出し入れすると隣のボタンの位置が
   *  ずれて目が迷う。選択が変わる 3 経路 (`render()`・クリック選択・オーバーレイの選択) から呼ぶ。 */
  function syncDeleteButton() {
    var del = document.getElementById("btn-deletesel");
    if (del) del.disabled = !Object.keys(curElSel()).length && S.coverSel === null && S.borderSel === null;
  }
```

- [ ] **Step 4: 3 つの経路から呼ぶ**

1. `render()` の手順 3 ブロック、`co.hidden = S.tool !== "cover";` の直後。

```javascript
      syncDeleteButton();
```

2. `wireTrimStage` の click ハンドラ末尾、`drawSelBoxes(host);` の直後。要素のクリック選択は `drawSelBoxes` だけを呼び、`render()` を通らない。

```javascript
      drawSelBoxes(host);
      syncDeleteButton();
```

3. オーバーレイの選択も `render()` を通らない。`app.js` が `initCover` / `initBorder` へ渡す `deps` へ `syncDeleteButton` を足し、`rect-overlay.js` から `ui` 経由で呼ぶ。`rect-overlay.js` の `opts.onSelect(...)` を呼んでいる 3 箇所（`clearSel` の `opts.onSelect(null);`、`draw` 末尾の `if (cur) opts.onSelect(cur);`、`installDrag` の mouseup のクリック分岐）それぞれの直後へ足す。

```javascript
      if (ui.syncDeleteButton) ui.syncDeleteButton();
```

`clearSel` からも呼ぶのは、選んでいた要素が消えたときにボタンが有効のまま残らないようにするため。


- [ ] **Step 5: E2E が通ることを確認する**

Run: `py -3.13 -m pytest pdf-to-svg -m e2e -q`
Expected: PASS（全件）

- [ ] **Step 6: Python 側も含めて全件を確認する**

Run: `py -3.13 -m pytest pdf-to-svg -q`
Expected: PASS

- [ ] **Step 7: コミット**

```bash
git add pdf-to-svg/resources/web/app.js pdf-to-svg/resources/web/rect-overlay.js pdf-to-svg/resources/web/cover.js pdf-to-svg/resources/web/border.js pdf-to-svg/test/test_pdftosvg_app_flow_e2e.py
git commit -m "$(cat <<'EOF'
feat(pdf-to-svg): 何も選んでいない間は削除ボタンを押せないようにする

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

---

### Task 8: 原稿・画面写真・HTML を実装に合わせる

実装を変えたら、原稿 → HTML 生成 までが 1 セット。

**Files:**
- Modify: `docs/pdf-to-svg/src/設計正典.md`
- Modify: `docs/pdf-to-svg/src/設計書.md`
- Modify: `docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md`
- Modify: `docs/pdf-to-svg/src/操作手順書.md`
- Modify: `docs/pdf-to-svg/_build/capture_screens.py`
- Regenerate: `docs/pdf-to-svg/pdf-to-svg_手引き.html` / `pdf-to-svg_設計.html`、`docs/pdf-to-svg/images/step3*.png`

**Interfaces:**
- Consumes: Task 2〜7 の実装すべて
- Produces: なし

- [ ] **Step 1: 設計正典に枠線の後編集の決めごとを書く**

`docs/pdf-to-svg/src/設計正典.md` の「ドラッグから矩形を作る決定は 1 箇所に置く」の項の直後へ、次の 2 項を足す。

```markdown
- **置いた矩形を後から動かす仕組みは 1 本に持つ**（`rect-overlay.js` の `createRectOverlay`）:
  手順 3 の「上書き」と「枠線」は、置いた矩形を後から選び・動かし・大きさを変える点で同じ
  振る舞いをする。モデルを正とし（表示 SVG から座標を拾わない）、ドラッグ中は箱だけを動かし、
  mouseup の 1 回だけ更新 RPC を送る、という流儀もそろえる。両者で違うのは「どの一覧 RPC を
  引くか」と「選んだとき入力欄に何を映すか」だけなので、それだけを引数で受け取る。複製して
  2 本持つと、片方だけ直した不具合がもう片方に残る（ジッター判定・ページ内クランプ・
  選択中の編集が次に置く値へ漏れない守り、はいずれも後から足した修正である）。
- **後編集の対象は「利用者が置いたもの」に限る**: 枠線は `RectElement.manual_border`、
  手動の上書きは `TextElement.manual_cover` で印を持ち、一覧 RPC（`borderList` / `coverList`）は
  印の付いた未削除の要素だけを返す。PDF 由来の矩形を同じオーバーレイの対象にすると、元の図面の
  罫線を掴んで動かせてしまい、「編集していないところは元のまま」という前提が崩れる。
- **入力欄は「次に置く値」と「選択中の要素の値」を兼ねる**: 上書きの置換語（`#cover-text`）と
  枠線の色・太さ（`#border-color` / `#border-width`）は、未選択なら次に置く値、選択中なら
  選択中の要素の値を編集する。選択中の打鍵で「次に置く値」を書き換えてはならない（選択を
  解いたあとに置く要素へ編集中の値が紛れ込む）。書き分けは確定関数 1 箇所
  （`commitCoverText` / `commitBorderStyle`）に閉じる。
```

- [ ] **Step 2: 設計書のコマンド一覧を直す**

`docs/pdf-to-svg/src/設計書.md` 「7.3 コマンドと Undo」の冒頭段落、「実コマンドは 6 種」を「実コマンドは 7 種」に変え、`UpdateCoverCommand` の説明の後ろへ次を足す。

```markdown
・`UpdateBorderCommand`（利用者が置いた枠線の位置・大きさ・色・太さの変更。`RectElement` は外枠 `bbox` と描画する矩形 `rect` の 2 つを持ち、枠線ではこの 2 つが常に同じ値なので必ず対で書き換える。片方だけ書き換えると書き出しの見た目と範囲削除の交差判定が食い違う）
```

- [ ] **Step 3: 設計書の手順 3 の節を書き換える**

`docs/pdf-to-svg/src/設計書.md` の「- ステップ 3（削除・枠線の編集）:」で始まる箇条書き 1 項を、次で置き換える。

```markdown
- ステップ 3（削除・枠線の編集）: ツールは「範囲削除 / 枠線 / 上書き」の 3 つで、初期状態は無選択。押下中のタブをもう一度押すと無選択へ戻る。**要素のクリック選択はツールに関係なく常に効き**（ドラッグだけがツール固有の操作）、無選択のときはドラッグが何も起こさない。ドラッグで矩形を引いた直後にも `click` は飛ぶため、`S.dragMoved` を立ててその 1 回を握り潰す（握り潰さないと、引き終わった位置の要素が意図せず青枠になる）。3 ツールはいずれも、ドラッグの始点・終点を `geometry.js` の `rectFromDrag`（引いた向きを正規化しページ内へ収め、`MIN_SIZE_PT` 未満なら誤クリックとして捨てる）へ通してから矩形を確定し、それぞれ `deleteRegion` / `addBorder` / `addCover` RPC を呼ぶ（RPC が失敗したら `toast` で通知する）。範囲削除はページ外の矩形でも要素との交差判定にしか使わないため無害、枠線は矩形自体が SVG に残るのでページ内へ収まっている方が正しい（上書きは元々ページ内がサーバ検証の前提）。
- 置いた枠線と上書きは、どちらも `rect-overlay.js` の `createRectOverlay` が作るオーバーレイで後から編集する。一覧 RPC（`borderList` / `coverList`）の返り値をモデルの正とし、角ハンドル 4 つ + 本体の HTML の箱（`.border-box` / `.cover-box`）をページ上へ重ね、角ハンドルのドラッグで伸縮（`resizeFromPointer`）・本体のドラッグで移動（いずれもページ内へクランプし、`MIN_SIZE_PT` 未満にはしない）、mouseup の 1 回だけ `updateBorder {rect}` / `updateCover {rect}` を送る。結果の矩形が元と実質同じ（`JITTER_EPS_PT` 未満の差）なら送らない（変化の無い 1 段を Undo スタックへ積まないため）。対象は利用者が置いたものに限る（`RectElement.manual_border` / `TextElement.manual_cover` の印があり、未削除のもの）。
- 箱をクリックして選ぶと、枠線なら色・太さの入力欄（`#border-color` / `#border-width`）に、上書きなら置換語の入力欄（`#cover-text`）にその要素の値が入り、`change`（Enter またはフォーカスが外れたとき）で `updateBorder {color|width}` / `updateCover {text}` を送る。選んでいる間は入力欄への打鍵が「次に置く値」（`S.borderColor` / `S.borderWidth` / `S.coverText`）を汚さない。削除は通常の削除ボタン（`#btn-deletesel`）で行い、クリックで選んだ要素（`S.elSel`）・上書きの選択（`S.coverSel`）・枠線の選択（`S.borderSel`）のいずれも同じ `applyDelete` へ載せる。何も選んでいない間はこのボタンを `disabled` にする（位置は動かさない — 出し入れすると隣のボタンの位置がずれて目が迷う）。ツールを切り替えると 3 つの選択をすべて解くため、複数の選択が同時に残ることは無い。ツールボタンの押下表示（`aria-pressed`）は、手順の移動でもツールが戻るため、クリック時ではなく `render()` が `S.tool` から毎回付け直す。
```

- [ ] **Step 4: 設計書の JS モジュール表とフェーズ初期化の説明を直す**

同ファイルの JS モジュール表（`geometry.js` の行がある表）へ 2 行足す。

```markdown
| `rect-overlay.js` | 置いた矩形を HTML の箱で重ね、選択・移動・角ハンドル伸縮させる共通部分。`createRectOverlay(opts)` が `{draw, installDrag, clearSel}` を返す。`opts` で受け取るのは箱の CSS クラス・対象ツール名・一覧 RPC と応答キー・更新 RPC・選択とドラッグ状態の出し入れ・選択が変わったときの入力欄同期の 6 点だけで、それ以外の振る舞い（ページ内クランプ・`MIN_SIZE_PT` 未満の却下・ジッター判定・取得中のページ切替の検知）は共通 |
| `border.js` | 手順 3「枠線」ツールのオーバーレイの枠線固有部分（`borderList` を引き、色・太さの入力欄と同期し、`updateBorder` を送る） |
```

`cover.js` の行の説明も「上書き固有部分（`coverList` を引き、置換語の入力欄と同期し、`updateCover` を送る）」へ直す。

同ファイルの `resetPhaseUi` の説明（「手順を移るとき…要素の選択（`S.elSel`）・上書きの選択（`S.coverSel`）・ツール（`S.tool`）を既定へ戻す」）を、枠線の選択を加えた 4 つへ直し、ツールの既定が「無選択」であることを書く。

- [ ] **Step 5: 仕様一覧の UI 表・RPC 表・テスト表を直す**

`docs/pdf-to-svg/src/PdfToSvg_仕様一覧.md` の UI 表を次に直す。

- 項番 14: ツールの値を `範囲削除 / 枠線 / 上書き` に直し、説明を「編集モード切替（初期は無選択。押下中のタブを再度押すと無選択へ戻る。要素のクリック選択はツールに関係なく常に効く）」にする。
- 項番 15: 説明を「カラーピッカー。枠線を選んでいる間は選択中の枠線の色を変える」にする。
- 項番 16: 説明を「0.5〜20 pt。枠線を選んでいる間は選択中の枠線の太さを変える」にする。
- 項番 17: 説明を「選択要素・選択中の上書き・選択中の枠線の削除。何も選んでいない間は `disabled`」にする。
- 項番 16 と 17 の間へ 1 行足す。

```markdown
| 16.1 | 3. 削除・枠線 | 枠線のオーバーレイ | `.border-box` / `.border-box.sel` | 置いた枠線を箱で重ねる。クリックで選択、本体ドラッグで移動、角ハンドルで伸縮 |
```

RPC 表の項番 17 の説明へ、`borderList` / `updateBorder` を足す。

```markdown
| 17 | RPC | `applyDelete / deleteRegion / restoreElements / addBorder / borderList / updateBorder` | 削除 / 範囲削除 / 削除一覧の行ごとの戻し / 枠線の追加・一覧・変更（いずれも Undo へ push）。矩形を取る `deleteRegion`/`addBorder`/`updateBorder` は `_parse_rect_arg` の 1 本で検査し（数値 4 つの有限性・正の寸法は常に要求）、範囲削除だけはページ外の矩形も許す（`inside_page=False`。矩形自体は成果物に残らず、重なる要素を選ぶだけのため）。枠線はページ内を要求する。太さの範囲検査は `_border_width` を `addBorder` と `updateBorder` が共有する。一覧・変更の対象は `manual_border` の印が付いた未削除の枠線だけ |
```

テスト表の末尾へ 3 行足す（項番は既存の続き）。

```markdown
| 33 | `test_web_rpc.py::test_border_list_returns_manual_borders_only` ほか | 枠線の一覧・変更 RPC（印の付いた未削除の枠線だけを返す、位置・色・太さの変更と Undo、太さだけの変更、無変更の呼び出し・削除済み要素・PDF 由来要素・ページ外の矩形・範囲外の太さの拒否） | 置いた枠線だけを後から安全に編集できる | 未 |
| 34 | `test_pdftosvg_app_flow_e2e.py::test_border_overlay_resize_and_width_change` ほか | 枠線オーバーレイの伸縮・選択して太さ変更・Undo、選択中の編集が次に置く枠線へ漏れないこと、枠線ツールのまま選んだ枠線を削除ボタンで消せること（E2E） | 枠線の後編集が画面で成立する | 未 |
| 35 | `test_pdftosvg_app_flow_e2e.py::test_element_click_selection_works_while_a_tool_is_active` ほか、`test_pdftosvg_state_js.py::test_transition_resetphaseui_*` | 選択タブ廃止後もどのツール中でもクリックで要素を選んで削除できること、押下中のタブの再クリックで無選択へ戻ること、何も選んでいない間は削除ボタンが `disabled` であること（E2E）と、`resetPhaseUi` がツールを無選択へ戻す単体 | 選択タブが無くても削除の導線が成立する | 未 |
```

- [ ] **Step 6: 操作手順書を書き換える**

`docs/pdf-to-svg/src/操作手順書.md` の 5.1 節を次にする。

```markdown
## 5.1 1 か所ずつ消す（クリック → 削除）

1. 消したい部分（文字や線）をクリックします。青い枠が付きます。
2. **「削除」** ボタンを押します。選んだ部分が消えます。

クリックでの選択は、どのツールを選んでいるときでも使えます。何も選んでいない間、「削除」ボタンは押せない見た目（薄い色）になります。
```

5.3 節の末尾へ、後編集の説明を足す。

```markdown
置いた枠線は、あとから調整できます。

- **大きさを変える**: 四隅のハンドルをドラッグします。
- **場所を動かす**: 枠線の中を（ハンドル以外を）ドラッグします。
- **色や太さを変える**: 枠線をクリックして選ぶと、色と太さの欄がその枠線の値になります。変えると、選んでいる枠線に反映されます。
- **消す**: 消したい枠線をクリックして選び、**「削除」** ボタンを押します。

いずれの操作も **Ctrl+Z** で取り消せます。何も選んでいない状態で色や太さを変えたときは、「次に引く枠線」の設定が変わります（すでに置いた枠線は変わりません）。
```

5.5 節の「**消す**」の行から「『選択』ツールに切り替えてからでも消せます」を削り、次にする。

```markdown
- **消す**: 消したい上書きをクリックして選び、**「削除」** ボタンを押します。
```

5.5 節末尾の `> [!INFO]` の「ツールは『選択』に戻ります」を「ツールは無選択に戻ります」に直す。

- [ ] **Step 7: 撮影スクリプトを直す**

`docs/pdf-to-svg/_build/capture_screens.py` の枠線撮影の直後にある次の 1 行を削除する（「選択」タブが無くなったため）。

```python
                page.click('[data-tool="select"]')
```

代わりに、押下中の枠線タブをもう一度押して無選択へ戻す。

```python
                page.click('[data-tool="border"]')  # 押下中のタブを再度押して無選択へ戻す
```

- [ ] **Step 8: 画面写真を撮り直す**

Run: `docs\pdf-to-svg\_build\capture_screens.bat`
Expected: `docs/pdf-to-svg/images/` の `step3_edit.png` / `step3b_border.png` / `step3c_region.png` ほかが更新される。差分が出たら「再撮影」としてそのままコミットする。

- [ ] **Step 9: HTML を再生成する**

Run: `py -3.13 docs/_build/build_all.py --project pdf-to-svg`
Expected: `docs/pdf-to-svg/pdf-to-svg_手引き.html` と `pdf-to-svg_設計.html` が更新される

- [ ] **Step 10: 原稿まわりのテストを走らせる**

Run: `py -3.13 -m pytest docs/_build -q`
Expected: PASS

Run: `py -3.13 -m pytest scripts -q`
Expected: PASS（コメント規約検査）

- [ ] **Step 11: コミット**

```bash
git add docs/pdf-to-svg docs/_build
git commit -m "$(cat <<'EOF'
docs(pdf-to-svg): 枠線の後編集と選択タブの廃止を原稿へ反映し画面写真と HTML を再生成する

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01Fb9pRs7bT2W39zLG5Srsju
EOF
)"
```

---

## 完了の確認

すべてのタスクを終えたら、pre-push フックと同じ順で通しておく。

```
py -3.13 -m pytest scripts
py -3.13 -m pytest docs/_build
py -3.13 -m pytest pdf-to-svg
py -3.13 -m pytest graph-editor
py -3.13 -m pytest pdf-to-svg -m e2e
py -3.13 -m pytest graph-editor -m e2e
```

さらに、実際のアプリを起動して手で触り、次の 4 点を確かめる。

1. 枠線を引いて、後から選んで動かし、太さを変えて、消せる。
2. ツールのタブが「範囲削除 / 枠線 / 上書き」の 3 つで、最初はどれも押されていない。
3. どのツール中でも、要素をクリックして「削除」で消せる。何も選んでいない間はボタンが薄い。
4. 手順 1 のグレースケールの説明文が「切り出し、」で改行している。
