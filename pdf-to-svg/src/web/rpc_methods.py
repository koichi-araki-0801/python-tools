"""RPC メソッドの実体。

``WebSession`` が複数 PDF・辞書・Undo スタックを保持し、各 ``rpc_*`` 関数が
既存の engine/dictionary/export を薄く包んで JSON 化可能な dict を返す。
ファイルダイアログやスレッドを要する重い処理 (読み込み・書き出し) は Bridge 側で
扱い、ここには「純粋に状態を読む / モデルを更新する」メソッドだけを置く
(→ Qt を起動せずユニットテスト可能)。
"""
from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from dictionary import apply as dict_apply
from dictionary.store import DictionaryStore
from export.svg_exporter import page_to_svg
from model import fonts
from model.document import Document, Page
from model.elements import DictMatch, Rect, RectElement, TextElement, sanitize_color

_log = logging.getLogger("pdftosvg")
from web.commands import (
    AddElementCommand,
    DeleteCommand,
    ReplaceTextCommand,
    RestoreCommand,
    RevertDictMatchCommand,
)


class WebSession:
    """Web UI 1 セッション分の状態。"""

    def __init__(self, store: DictionaryStore, undo):
        self.store = store
        self.undo = undo  # QUndoStack (test では push() を持つ任意オブジェクト可)
        self.docs: List[Document] = []
        # クリック取り込み (dictSuggest) で折返し 2 行を連結するか。既定 OFF で、
        # チェックボックス ON のときだけ連結候補を返す (連結由来はエントリへ記録)。
        self.suggest_join: bool = False

    # ---- 参照ヘルパ ----
    def doc(self, file_index: int) -> Document:
        return self.docs[file_index]

    def page(self, file_index: int, page_in_file: int) -> Page:
        return self.docs[file_index].pages[page_in_file]

    def all_pages(self):
        """(fileIndex, pageInFile, Page) を順に列挙。"""
        for fi, d in enumerate(self.docs):
            for pi, pg in enumerate(d.pages):
                yield fi, pi, pg


# ---- 状態のスナップショット ----

def _page_has_replacements(page: Page, store: DictionaryStore) -> bool:
    """手順 2 で「要確認」にするか。置換済みが 1 件でもあるか、未適用の候補 (戻した箇所・
    まだ当てていない箇所) が残るページ。候補も数えるのは、箇所単位で戻したページが一覧から
    消えて再び置換できなくなるのを避けるため。"""
    if any(
        isinstance(e, TextElement) and not e.deleted and e.dict_match is not None
        for e in page.elements
    ):
        return True
    return dict_apply.has_replacement_candidate(page, store)


def _human_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


def _file_size_str(doc: Document) -> str:
    # アップロード経由では実パスが無いので loader が付与した byte_size を使う。
    # 実パス読み込みの doc は getsize でフォールバックする。
    n = getattr(doc, "byte_size", None)
    if n is None:
        try:
            n = os.path.getsize(doc.source_path)
        except OSError:
            return ""
    return _human_size(n)


def rpc_state(s: WebSession, _args: dict) -> dict:
    """ファイル・ページ一覧と、各ページの初期レビュー要否 (changed) を返す。"""
    files = []
    pages = []
    changed2: List[bool] = []
    changed3: List[bool] = []
    for fi, d in enumerate(s.docs):
        files.append(
            {
                "id": fi,
                "name": Path(d.source_path).name,
                "pages": len(d.pages),
                "size": _file_size_str(d),
            }
        )
        for pi, pg in enumerate(d.pages):
            pages.append({"fileIndex": fi, "pageInFile": pi})
            # 手順2: 辞書置換が当たったページは「要確認」。
            changed2.append(_page_has_replacements(pg, s.store))
            # 手順3: トリミングは全ページが対象 (各ページを見て確認/スキップ)。
            changed3.append(True)
    total = len(pages)
    # suggestJoin は state には含めない (クライアントの読者は
    # files/pages/total/changed2/changed3 のみ。辞書設定は dictList 側ペイロードが正)。
    return {
        "files": files,
        "pages": pages,
        "changed2": changed2,
        "changed3": changed3,
        "total": total,
        # 要素数の資源上限に当たって抽出を打ち切ったページ数 (`engine/pdf_engine.py`)。
        # 欠落を無言にしないための通知経路で、`app.js` の `reloadState` が出す。
        "truncated": sum(1 for d in s.docs for pg in d.pages if pg.truncated),
        # 背景を生成できなかったスキャンページ数 (`engine/pdf_engine.py` の
        # `_render_background` が `None` を返した分 = ラスタ上限・文書予算の超過)。
        # このページは白紙同然で書き出されるので、`truncated` と同じ経路で必ず伝える。
        # モデルに印を持たせず導出するのは、状態が 2 か所へ分かれて食い違うのを避けるため。
        "noBackground": sum(
            1 for d in s.docs for pg in d.pages if pg.is_scanned and pg.background is None
        ),
    }


def rpc_pageSvg(s: WebSession, args: dict) -> dict:
    pg = s.page(args["fileIndex"], args["pageInFile"])
    return {
        "svg": page_to_svg(pg, annotate=True),
        "width": pg.width_pt,
        "height": pg.height_pt,
    }


def rpc_planPage(s: WebSession, args: dict) -> dict:
    """確認一覧の行。置換済み (`applied`) と未適用の候補 (`pending` = 戻した箇所・まだ
    当てていない箇所) を要素の出現順に混ぜて返す。UI はこの順で通し番号を振り、ページ上の
    番号マーカーと対応させる。"""
    pg = s.page(args["fileIndex"], args["pageInFile"])
    pending = {rep.element.id: rep for rep in dict_apply.plan_replacements(pg, s.store)}
    changes = []
    for el in pg.elements:
        if not isinstance(el, TextElement) or el.deleted:
            continue
        loc = "ヘッダ" if el.is_header else "本文"
        if el.dict_match is not None:
            changes.append(
                {
                    "elId": el.id,
                    "source": el.dict_match.source,
                    "target": el.dict_match.target,
                    "loc": loc,
                    # 置換語が収め先の箱幅を超え圧縮表示される恐れ (簡易推定)。
                    "warning": fonts.is_width_overflow(el.text, el.font_size, el.bbox.w),
                    "state": "applied",
                }
            )
        elif el.id in pending:
            rep = pending[el.id]
            changes.append(
                {
                    "elId": el.id,
                    "source": rep.source,
                    "target": rep.target,
                    "loc": loc,
                    "warning": rep.warning is not None,
                    "state": "pending",
                }
            )
    return {"changes": changes}


_KIND_LABEL = {
    "text": "文字",
    "line": "罫線",
    "rect": "矩形",
    "path": "図形",
    "image": "画像",
}


def rpc_removedList(s: WebSession, args: dict) -> dict:
    pg = s.page(args["fileIndex"], args["pageInFile"])
    # 辞書の折返し畳み込みで隠した後続行は利用者が削除したものではない。ここで戻せると
    # 連結済みテキストの下に旧 2 行目が再表示され、箇所単位の戻し (dict_revert) と食い違う。
    folded = set()
    for el in pg.elements:
        if isinstance(el, TextElement) and not el.deleted and el.dict_revert is not None:
            folded.update(el.dict_revert.extra_ids)
    removed = []
    for el in pg.elements:
        if not el.deleted or el.id in folded:
            continue
        label = _KIND_LABEL.get(el.kind, "要素")
        if isinstance(el, TextElement):
            snippet = el.text.strip()[:16]
            label = f"文字「{snippet}」" if snippet else "文字"
        removed.append({"elId": el.id, "kind": el.kind, "label": label})
    return {"removed": removed}


# ---- 辞書 ----

def _dict_payload(s: WebSession) -> dict:
    return {
        "entries": [
            {"id": m.id, "source": m.source_raw, "target": m.target,
             "enabled": m.enabled, "joined": m.joined}
            for m in s.store.all()
        ],
        "suggestJoin": s.suggest_join,
        # 起動時に辞書ファイルから捨てた件数 / 丸ごと読めなかったか。壊れた要素を黙って
        # 消さず利用者へ通知するための経路 (`app.js` が 1 度だけトーストで出す)。
        "loadSkipped": s.store.load_skipped,
        "loadFailed": s.store.load_failed,
    }


def rpc_dictList(s: WebSession, _args: dict) -> dict:
    return _dict_payload(s)


def rpc_dictAdd(s: WebSession, args: dict) -> dict:
    src = (args.get("source") or "").strip()
    tgt = (args.get("target") or "").strip()
    if src:
        # joined はクリック取り込みが連結候補を返したときにフロントが立てる
        # (連結照合の対象にするかの記録。手入力は常に False)。
        s.store.upsert(src, tgt, joined=bool(args.get("joined", False)))
    return _dict_payload(s)


def rpc_dictDelete(s: WebSession, args: dict) -> dict:
    s.store.delete(int(args["id"]))
    return _dict_payload(s)


def rpc_dictSuggest(s: WebSession, args: dict) -> dict:
    """クリックした文字要素から辞書「元の語」候補を返す。

    `suggest_join` が ON のとき、折返しで複数行に分かれた 1 文 (セル) はマッチャと
    同じ束ね方で連結した文字列を返すため、クリック 1 回で文全体を取り込める。
    `joined` は連結したかの印で、フロントが登録時にエントリの連結由来として渡し返す。
    OFF・単独行は当該行の文字列。
    対象が無ければ空文字 (クライアントはクリック行の textContent にフォールバック)。
    """
    pg = s.page(int(args["fileIndex"]), int(args["pageInFile"]))
    el = _find_text_element(pg, int(args["elId"]))
    if el is None:
        return {"source": "", "joined": False}
    source, joined = dict_apply.joined_candidate(pg, el, join_wrapped=s.suggest_join)
    return {"source": source, "joined": joined}


def rpc_setSuggestJoin(s: WebSession, args: dict) -> dict:
    s.suggest_join = bool(args.get("value", False))
    return {"suggestJoin": s.suggest_join}




def _apply_plans(s: WebSession, plans) -> dict:
    """plans を 1 Undo マクロで適用し {count, warnings} を返す (全ファイル/1ページ共有)。"""
    if not plans:
        return {"count": 0, "warnings": 0}
    warnings = 0
    s.undo.beginMacro()
    for rep in plans:
        s.undo.push(
            ReplaceTextCommand(
                rep.element, rep.target,
                DictMatch(source=rep.source, target=rep.target),
                new_bbox=rep.new_bbox,
                wrap_align=rep.align,
                baseline_y=rep.baseline_y,
                extras=rep.extras,
            )
        )
        if rep.extras:  # 折返しヘッダの 2 行目以降を描画から除外
            s.undo.push(DeleteCommand(rep.extras))
        if rep.warning:  # 置換語が元幅を超え圧縮表示される恐れ
            warnings += 1
            _log.warning("辞書置換 幅超過: %r → %r (%s)", rep.source, rep.target, rep.warning)
    s.undo.endMacro()
    return {"count": len(plans), "warnings": warnings}


def rpc_reapplyDict(s: WebSession, _args: dict) -> dict:
    """全ファイル・全ページに辞書を再適用 (Undo 可・1 マクロ)。置換件数を返す。"""
    plans = []
    for _fi, _pi, pg in s.all_pages():
        dict_apply.detect_headers(pg)  # 確認一覧の「ヘッダ/本文」表示 (loc) 用
        plans.extend(dict_apply.plan_replacements(pg, s.store))
    return _apply_plans(s, plans)


def rpc_reapplyDictPage(s: WebSession, args: dict) -> dict:
    """指定ページにのみ辞書を再適用 (Undo 可・1 マクロ)。置換件数を返す。"""
    pg = s.page(int(args["fileIndex"]), int(args["pageInFile"]))
    dict_apply.detect_headers(pg)  # 確認一覧の「ヘッダ/本文」表示 (loc) 用
    plans = dict_apply.plan_replacements(pg, s.store)
    return _apply_plans(s, plans)


def _find_text_element(pg: Page, el_id: int) -> Optional[TextElement]:
    return next(
        (e for e in pg.elements if e.id == el_id and isinstance(e, TextElement) and not e.deleted),
        None,
    )


def rpc_revertDictMatch(s: WebSession, args: dict) -> dict:
    """辞書置換を 1 箇所だけ置換前へ戻す (Undo 可)。復元情報が無ければ no-op。
    戻しはその場限りで、次の再適用ではまた置換される (恒久除外のフラグは持たない)。"""
    pg = s.page(int(args["fileIndex"]), int(args["pageInFile"]))
    el = _find_text_element(pg, int(args["elId"]))
    if el is None or el.dict_revert is None:
        return {"reverted": False}
    ids = set(el.dict_revert.extra_ids)
    extras = [e for e in pg.elements if e.id in ids and isinstance(e, TextElement)]
    s.undo.push(RevertDictMatchCommand(el, extras))
    return {"reverted": True}


def rpc_applyDictMatch(s: WebSession, args: dict) -> dict:
    """指定要素 1 件だけ辞書を当てる (Undo 可・1 マクロ)。候補でなければ no-op。"""
    pg = s.page(int(args["fileIndex"]), int(args["pageInFile"]))
    el_id = int(args["elId"])
    plans = [rep for rep in dict_apply.plan_replacements(pg, s.store) if rep.element.id == el_id]
    return _apply_plans(s, plans)


# ---- 編集 ----

def rpc_applyDelete(s: WebSession, args: dict) -> dict:
    pg = s.page(args["fileIndex"], args["pageInFile"])
    ids = set(int(i) for i in args.get("elIds", []))
    els = [e for e in pg.elements if e.id in ids and not e.deleted]
    if els:
        s.undo.push(DeleteCommand(els))
    return {}


def rpc_restoreElements(s: WebSession, args: dict) -> dict:
    """削除一覧の行ごとの「戻す」。指定要素だけを再表示する (Undo 可)。

    グローバルな ``undo`` は直近 1 件しか戻せず、複数回に分けて削除した後や別ページで
    削除した後に押すと無関係な操作を取り消す。要素 id で対象を固定する。
    """
    pg = s.page(args["fileIndex"], args["pageInFile"])
    ids = set(int(i) for i in args.get("elIds", []))
    els = [e for e in pg.elements if e.id in ids and e.deleted]
    if els:
        s.undo.push(RestoreCommand(els))
    return {}


def _bbox_hits(bbox: Rect, rect: Rect) -> bool:
    """要素 bbox が矩形 rect に重なるか。ゼロ寸法 (罫線/点) は内包判定で拾う。"""
    if bbox.w == 0 and bbox.h == 0:
        return rect.x <= bbox.x <= rect.x1 and rect.y <= bbox.y <= rect.y1
    return bbox.intersects(rect)


def rpc_deleteRegion(s: WebSession, args: dict) -> dict:
    """ドラッグした矩形に重なる live 要素をまとめて削除する (範囲削除)。"""
    pg = s.page(args["fileIndex"], args["pageInFile"])
    r = args["rect"]
    rect = Rect(float(r["x"]), float(r["y"]), float(r["w"]), float(r["h"]))
    els = [e for e in pg.live_elements() if _bbox_hits(e.bbox, rect)]
    if els:
        s.undo.push(DeleteCommand(els))
    return {}


def rpc_removeFile(s: WebSession, args: dict) -> dict:
    """追加済み PDF を 1 つ一覧から取り除く。Undo 履歴は旧 doc の要素を参照する
    ため無効化する (アップロードと同方針)。クライアントは直後に state を取り直す。"""
    fi = int(args["fileIndex"])
    if 0 <= fi < len(s.docs):
        s.undo.clear()
        s.docs.pop(fi)
    return {}


def rpc_addBorder(s: WebSession, args: dict) -> dict:
    """ドラッグした矩形に塗りなしの枠線 (RectElement) を 1 つ追加する (Undo 可)。"""
    pg = s.page(args["fileIndex"], args["pageInFile"])
    r = args["rect"]
    rect = Rect(float(r["x"]), float(r["y"]), float(r["w"]), float(r["h"]))
    # 外部由来の色は必ず ``sanitize_color`` を通す (入口)。出口の ``_paint`` にも同じ検証が
    # あるのは、入口だけだと別の入口が生えたときに漏れるため。``width`` も範囲を見る —
    # ``float()`` は ``inf`` / ``nan`` を通し、``_fmt`` がそれを書いて SVG が壊れる。
    color = sanitize_color(args.get("color") or "#000000")
    width = float(args.get("width") or 1.0)
    if not math.isfinite(width) or not (0 < width <= 100):
        raise ValueError(f"width must be a finite number in (0, 100]: {width!r}")
    z = max((e.z for e in pg.elements), default=0) + 1
    el = RectElement(
        bbox=rect, z=z, rect=rect, stroke=color, fill=None, stroke_width=width
    )
    s.undo.push(AddElementCommand(pg, el))
    return {}


def rpc_undo(s: WebSession, _args: dict) -> dict:
    if s.undo.canUndo():
        s.undo.undo()
    return {}


def rpc_redo(s: WebSession, _args: dict) -> dict:
    if s.undo.canRedo():
        s.undo.redo()
    return {}


# ---- 書き出し (SVG 文字列を返す。ファイル保存はブラウザの FSA が行う) ----

def rpc_exportSvg(s: WebSession, args: dict) -> dict:
    """指定ページの SVG 文字列と推奨ファイル名を返す (annotate なし=書き出し用・従来出力と一致)。"""
    fi = int(args["fileIndex"])
    pi = int(args["pageInFile"])
    d = s.doc(fi)
    stem = Path(d.source_path).stem
    return {"svg": page_to_svg(d.pages[pi]), "name": f"{stem}_p{pi + 1}.svg"}


# ---- ZIP 集約 (複数 SVG の一括保存) ----

def rpc_zipEntries(_s: WebSession, args: dict) -> dict:
    """``{name, text}`` のリストを ZIP 1 本へ固め base64 で返す。

    複数 SVG を個別ダウンロードすると N 回の保存が走り、Edge の連続ダウンロード確認にも
    阻まれるため、標準ライブラリ ``zipfile`` でサーバ側集約する (追加依存なし)。進捗表示の
    ため SVG 変換自体はクライアントが ``exportSvg`` をページごとに呼び、集めた結果だけを
    ここへ渡す (ローカル HTTP なので往復コストは無視できる)。
    """
    entries = args.get("entries") or []
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for e in entries:
            zf.writestr(str(e["name"]), str(e["text"]))
    return {
        "zipBase64": base64.b64encode(buf.getvalue()).decode("ascii"),
        "count": len(entries),
    }


# ---- 辞書 JSON (文字列ベース。ファイル保存/読込はブラウザの FSA が行う) ----

def rpc_dictJson(s: WebSession, _args: dict) -> dict:
    """現在の辞書を共有用 JSON 文字列 (実体ファイルと同形式) で返す。"""
    data = [
        {"source": m.source_raw, "target": m.target, "enabled": m.enabled,
         "joined": m.joined}
        for m in s.store.all()
    ]
    return {"json": json.dumps(data, ensure_ascii=False, indent=2), "count": len(data)}


def rpc_dictImportJson(s: WebSession, args: dict) -> dict:
    """JSON 文字列から辞書を取り込む。取り込み件数・捨てた件数と一覧を返す。

    件数上限を超える取り込みは `import_json` が `ValueError` を投げ、dispatch 経由で
    `{ok:false, error}` として利用者へ出る (黙って一部だけ取り込まない)。
    """
    text = args.get("json") or ""
    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        result = s.store.import_json(Path(tmp))
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    payload = _dict_payload(s)
    payload["imported"] = result.imported
    payload["skipped"] = result.skipped
    return payload


# メソッド名 → 関数。load (アップロード) は server.py が、ファイル保存はブラウザが扱う。
HANDLERS: Dict[str, Callable[[WebSession, dict], dict]] = {
    "state": rpc_state,
    "pageSvg": rpc_pageSvg,
    "planPage": rpc_planPage,
    "removedList": rpc_removedList,
    "dictList": rpc_dictList,
    "dictAdd": rpc_dictAdd,
    "dictDelete": rpc_dictDelete,
    "dictSuggest": rpc_dictSuggest,
    "dictJson": rpc_dictJson,
    "dictImportJson": rpc_dictImportJson,
    "exportSvg": rpc_exportSvg,
    "zipEntries": rpc_zipEntries,
    "setSuggestJoin": rpc_setSuggestJoin,
    "reapplyDict": rpc_reapplyDict,
    "reapplyDictPage": rpc_reapplyDictPage,
    "revertDictMatch": rpc_revertDictMatch,
    "applyDictMatch": rpc_applyDictMatch,
    "applyDelete": rpc_applyDelete,
    "restoreElements": rpc_restoreElements,
    "deleteRegion": rpc_deleteRegion,
    "removeFile": rpc_removeFile,
    "addBorder": rpc_addBorder,
    "undo": rpc_undo,
    "redo": rpc_redo,
}


def dispatch(session: WebSession, method: str, args: Optional[dict]) -> dict:
    """純粋メソッドを実行して結果 dict を返す。未知メソッドは KeyError。"""
    handler = HANDLERS[method]
    return handler(session, args or {})
