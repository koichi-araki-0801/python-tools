"""辞書の永続化 (JSON ファイル)。

exe と同じフォルダの `data/dictionary.json` に保存する (config 側でパス決定)。
人が直接開いて編集・差分管理・共有できる形式 ``[{"source","target","enabled","joined"}]``
(``joined`` は折返し連結由来の印。旧形式のキー無しは False として読む)。
SQLite からの移行: バックエンドのみ差し替え、公開 API は据え置き
(`add/upsert/delete/all/lookup/import_json/close`)。

実装方針: 起動時にファイルを読み込みメモリ上で操作し、変更のたびにアトミック保存する。
単一ユーザーのデスクトップ用途のため、これで十分かつ堅牢。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .normalize import normalize

# 辞書エントリ数の上限。取り込みは 1 ファイルで数十万件を投げ込めるうえ、エントリ数は
# 以後の全操作 (正規化・索引再構築・全文保存) の係数になるため、入口で頭を押さえる。
# 実運用の辞書は数百〜数千語で、上限は 1 桁以上の余裕がある。
MAX_DICT_ENTRIES = 20_000

# 読み込む辞書ファイルの上限バイト数。件数上限は**パースした後**にしか効かないので、
# 巨大ファイルを丸ごとメモリへ載せる段階を止めるには別途バイト数で見る必要がある
# (`MAX_DICT_ENTRIES` 件を素直に書き出しても 2 MB 程度で、32 MiB は十分な余裕)。
MAX_DICT_FILE_BYTES = 32 * 1024 * 1024


def _read_text_limited(path: Path) -> str:
    """`MAX_DICT_FILE_BYTES` を超えるファイルは**読まずに** `ValueError`。

    件数上限はパースの後にしか効かないので、載せる前にバイト数で足切りする。
    """
    size = path.stat().st_size
    if size > MAX_DICT_FILE_BYTES:
        raise ValueError(
            f"辞書ファイルが大きすぎます ({size} バイト / 上限 {MAX_DICT_FILE_BYTES} バイト)"
        )
    return path.read_text(encoding="utf-8")


# `os.replace` の共有違反リトライの待ち秒列。ネットワークドライブ上の辞書は、別クライアント
# (ウイルス対策・エクスプローラのプレビュー・バックアップ) が宛先を開いている一瞬だけ
# rename が PermissionError になる。恒久エラー (ACL 拒否) と事前に区別できないため、
# 短い待ちで数回だけやり直し、それでも駄目なら例外で諦める (無限に固まらせない)。
_REPLACE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4)


def _replace_with_retry(src: str, dst: Path) -> None:
    """`os.replace` を一時的な共有違反 (`PermissionError`) のリトライ付きで行う。"""
    for delay in _REPLACE_RETRY_DELAYS:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            time.sleep(delay)
    os.replace(src, dst)


@dataclass
class ImportResult:
    """`import_json` の結果。取り込めた件数と、壊れていて捨てた件数。

    捨てた件数を返すのは「黙って消さない」ため (`docs/pdf-to-svg/src/設計正典.md`
    のセキュリティ節と同じ作法)。呼び出し側は利用者へ件数を見せること。
    """

    imported: int
    skipped: int


@dataclass
class Mapping:
    """辞書 1 エントリ。`source_raw` は入力原文、`target` は置換後、`enabled` で適用可否。

    `joined` は「元の語が折返し 2 行の連結取り込み由来か」の記録。一括適用の連結照合
    (`lookup_wrap`) はこのフラグ付きエントリにのみ一致させ、単独行で登録した語が
    偶然連結形と一致して意図せず 2 行を畳む事故を防ぐ。
    """

    id: int
    source_raw: str
    target: str
    enabled: bool = True
    joined: bool = False


class DictionaryStore:
    """JSON ファイルを正典とするインメモリ辞書ストア (CRUD + 正規化 lookup)。"""

    def __init__(self, json_path: Path):
        self.path = Path(json_path)
        self._mappings: List[Mapping] = []
        self._next_id = 1
        self._index: Dict[str, Mapping] = {}  # source_norm -> Mapping (enabled のみ)
        # source_norm -> Mapping (enabled 問わず・先勝ち)。`_find_by_norm` が引く索引で、
        # `upsert` を O(1) にするために持つ (`_index` は enabled 限定なので upsert の
        # 同一性判定には使えない)。
        self._norm_index: Dict[str, Mapping] = {}
        # 読み込み時に壊れていて捨てたエントリ数と、ファイルを丸ごと読めなかったか。
        # UI が起動後に通知する (`rpc_methods._dict_payload` → `app.js`)。実体は `_load` が入れる。
        self.load_skipped = 0
        self.load_failed = False
        # 最後にこのプロセスが読んだ/書いたときのファイル状態 (st_mtime_ns, st_size)。
        # 共有フォルダの辞書を複数人で使うときの lost-update 検出に使う (`_save` 参照)。
        # None は「不明」= 検査しない (ファイル不在の新規や、状態取得に失敗した直後)。
        self._disk_state: "Tuple[int, int] | None" = None
        self._load()

    def close(self) -> None:
        """API 互換のため残す。変更のたびに保存済みなので no-op。"""

    # ── 読み込み / 保存 ──
    def _load(self) -> None:
        """JSON ファイルを読み込み `_mappings` を復元する (壊れていても起動は止めない)。

        **要素 1 個の型崩れで起動不能にしない**のが要件である。リストの中に dict 以外が
        1 つ混じるだけで `item.get` が `AttributeError` を投げ、それが `__init__` を突き抜けると
        `console=False` の exe は**何も表示されず起動不能**になる。辞書はメールや
        共有フォルダ経由で配られる = 外部由来の入力なので、壊れた要素は捨てて起動を通し、
        捨てた件数を `load_skipped` に残して UI へ通知する (黙って消さない)。
        """
        self._mappings = []
        self._next_id = 1
        self.load_skipped = 0
        self.load_failed = False
        self._disk_state = None
        # `Path.exists()` で在否を先に見ない: Windows の `exists()` はドライブ未接続・
        # 共有瞬断系の OSError を握りつぶして False を返すため、ネットワークドライブ上の
        # 辞書が一瞬読めないだけで「無い」と誤判定される。その後の保存が本物の辞書を
        # 空で上書きする無音のデータ消失になるので、読みを直接試みて
        # `FileNotFoundError` (真の不在) とそれ以外 (不明 = `load_failed`) を区別する。
        data = None
        text = ""
        missing = False
        try:
            text = _read_text_limited(self.path)
            st = self.path.stat()
            self._disk_state = (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            missing = True  # 真の新規。空辞書で開始してよい
        except (OSError, ValueError):
            # 読めない (瞬断・権限・文字コード破損・上限超過)。利用者から見れば辞書の
            # 消失なので伝える。`_save` はこのフラグが立っている間は保存を拒む。
            self.load_failed = True
        else:
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                data = None  # 壊れていても起動を止めない
        if not missing and not isinstance(data, list):
            # ファイルはあるのに 1 件も読めない = 辞書の消失に見える。空辞書として
            # 黙って通さず「読めなかった」を伝える (中身が空のファイルは除く)。
            self.load_failed = self.load_failed or text.strip() != ""
        if isinstance(data, list):
            for item in data:
                entry = self._entry_from_json(item)
                if entry is None:
                    self.load_skipped += 1
                    continue
                if len(self._mappings) >= MAX_DICT_ENTRIES:
                    # 上限超過分は読まない (読めば以後の全操作がその件数に比例して重くなる)。
                    # 起動は通し、落とした件数だけ伝える。
                    self.load_skipped += 1
                    continue
                src, target, enabled, joined = entry
                self._mappings.append(
                    Mapping(
                        id=self._next_id, source_raw=src, target=target,
                        enabled=enabled, joined=joined,
                    )
                )
                self._next_id += 1
        self._rebuild_index()

    @staticmethod
    def _entry_from_json(item: object) -> "tuple[str, str, bool, bool] | None":
        """JSON の 1 要素を `(source, target, enabled, joined)` へ検証する (不正なら None)。

        `_load` と `import_json` が同じ検証を通るよう 1 箇所に置く。`source`/`target` は
        文字列であることまで見る: 数値や null が入ると `normalize()` の `.strip()` が
        後段で落ち、壊れる場所が読み込みから照合へずれるだけで直らないため。
        旧形式 (`joined` キー無し) は非連結として読む (後方互換)。
        """
        if not isinstance(item, dict):
            return None
        src = item.get("source")
        target = item.get("target", "")
        if not isinstance(src, str) or not src.strip():
            return None
        if not isinstance(target, str):
            return None
        return src, target, bool(item.get("enabled", True)), bool(item.get("joined", False))

    def _rebuild_index(self) -> None:
        """lookup 用 (enabled のみ・後勝ち) と同一性判定用 (全件・先勝ち) の索引を作り直す。

        後者 (`_norm_index`) は `_find_by_norm` が引く索引で、全件線形走査だと
        取り込み N 件が O(N^2) 回の `normalize` を呼ぶことになる。
        """
        self._index = {}
        self._norm_index = {}
        for m in self._mappings:
            key = normalize(m.source_raw)
            if m.enabled:
                # 後勝ち: 同一正規化キーが複数あれば最後の有効分を採用
                self._index[key] = m
            # 先勝ち: `_find_by_norm` は同一正規化キーの「最初の一致」を返す契約
            self._norm_index.setdefault(key, m)

    def _save(self) -> None:
        """全 `_mappings` を JSON へアトミック保存する (temp → `os.replace`)。

        保存は**全件の書き直し**なので、読めていない/古い状態からの保存は他の内容を
        丸ごと消す。それを防ぐゲートが 2 つある:

        - `load_failed` の間は保存しない (読めなかった辞書を空で上書きしない)。
        - 前回読み書き時とファイル状態が変わっていたら保存しない (共有フォルダの辞書を
          複数人で使ったときの lost-update 検出。stat とファイル差し替えの間に隙間が
          残るベストエフォートだが、「黙って相手の追加を消す」既定よりは良い)。
        """
        if self.load_failed:
            raise ValueError(
                "辞書ファイルを読み込めていないため保存しません (保存すると読めなかった"
                f"内容を上書きして消してしまいます)。ファイルの状態を確認してから"
                f"アプリを再起動してください: {self.path}"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._check_lost_update()
        data = [
            {"source": m.source_raw, "target": m.target, "enabled": m.enabled,
             "joined": m.joined}
            for m in self._mappings
        ]
        text = json.dumps(data, ensure_ascii=False, indent=2)
        # アトミック書き込み (temp → replace) で破損を防ぐ。ネットワークドライブでは
        # 書き込みがクライアント側キャッシュに乗ったまま rename が先行しうるため、
        # close 前に fsync してサーバまで届いた状態で差し替える。
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            _replace_with_retry(tmp, self.path)
        except BaseException:
            # 後始末の失敗で元の例外を隠さない (共有では remove 自体も失敗しうる)。
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        self._remember_disk_state()

    def _check_lost_update(self) -> None:
        """前回読み書き時からファイルが他者に更新されていたら `ValueError` で保存を止める。

        `_disk_state` が None (状態不明) のときは検査しない: 偽陽性で保存を永久に
        塞ぐより、稀な同時新規作成の取りこぼしを許す側へ倒す。
        """
        if self._disk_state is None:
            return
        try:
            st = self.path.stat()
        except FileNotFoundError:
            # 読んだはずのファイルが消えている = 他者が削除/改名した。上書きで復活させず伝える。
            raise ValueError(
                "辞書ファイルが見つかりません (他の利用者が削除・移動した可能性があります)。"
                f"アプリを再起動して状態を確認してください: {self.path}"
            )
        except OSError as exc:
            raise ValueError(
                f"辞書ファイルの状態を確認できないため保存しません: {exc}"
            ) from exc
        if (st.st_mtime_ns, st.st_size) != self._disk_state:
            raise ValueError(
                "辞書ファイルが他の利用者によって更新されています。このまま保存すると"
                "相手の変更を消してしまうため保存しません。アプリを再起動して最新の辞書を"
                "読み直してください。"
            )

    def _remember_disk_state(self) -> None:
        """保存直後のファイル状態を記録する (取得できなければ「不明」= 次回は検査しない)。"""
        try:
            st = self.path.stat()
            self._disk_state = (st.st_mtime_ns, st.st_size)
        except OSError:
            self._disk_state = None

    def _find_by_norm(self, source_raw: str) -> Optional[Mapping]:
        """`source_raw` の正規化キーに一致する最初の `Mapping` を返す (無ければ None)。"""
        return self._norm_index.get(normalize(source_raw))

    # ── CRUD ──
    def add(
        self, source_raw: str, target: str, enabled: bool = True, joined: bool = False
    ) -> int:
        """新規エントリを追加し採番した `id` を返す。上限超過は `ValueError`。"""
        if len(self._mappings) >= MAX_DICT_ENTRIES:
            raise ValueError(
                f"辞書の登録件数が上限 ({MAX_DICT_ENTRIES} 件) に達しています。"
                "不要な語を削除してください。"
            )
        m = Mapping(
            id=self._next_id, source_raw=source_raw, target=target,
            enabled=enabled, joined=joined,
        )
        self._next_id += 1
        self._mappings.append(m)
        self._rebuild_index()
        self._save()
        return m.id

    def upsert(self, source_raw: str, target: str, joined: bool = False) -> int:
        """同じ正規化キーがあれば target と joined を更新、無ければ追加。"""
        existing = self._find_by_norm(source_raw)
        if existing is not None:
            existing.target = target
            existing.source_raw = source_raw
            existing.joined = joined
            self._rebuild_index()
            self._save()
            return existing.id
        return self.add(source_raw, target, joined=joined)

    def delete(self, mid: int) -> None:
        """`id` が `mid` のエントリを削除する。"""
        self._mappings = [m for m in self._mappings if m.id != mid]
        self._rebuild_index()
        self._save()

    def all(self) -> List[Mapping]:
        """全エントリを `source_raw` 昇順のコピーで返す (内部状態は不変)。"""
        return sorted(
            (
                Mapping(m.id, m.source_raw, m.target, m.enabled, m.joined)
                for m in self._mappings
            ),
            key=lambda m: m.source_raw,
        )

    def lookup(self, text: str) -> Optional[str]:
        """正規化キー一致で target を返す (enabled のみ)。"""
        m = self._index.get(normalize(text))
        return m.target if m is not None else None

    def lookup_wrap(self, text: str) -> Optional[str]:
        """連結由来 (`joined=True`) エントリに限って target を返す (enabled のみ)。

        折返し 2 行の連結照合専用。単独行として登録した語が偶然連結形と一致しても
        ここでは引かず、意図して連結取り込みした語だけが 2 行畳み込みの対象になる。
        """
        m = self._index.get(normalize(text))
        return m.target if (m is not None and m.joined) else None

    # ── JSON 入力 (共有用。実体ファイルと同形式。書き出しは rpc_dictJson が文字列で返す) ──
    def import_json(self, path: Path) -> ImportResult:
        """`path` の JSON をまとめて取り込み、取り込み件数と捨てた件数を返す。

        **1 件ごとに `upsert` を呼ばない**のが要点である。`upsert` は 1 回ごとに
        索引の全再構築と**辞書全文の書き直し**を行うため、N 件の取り込みが O(N^2) の
        `normalize` 呼び出しと sum(i) バイトの書き込みになる。実測不要の構造で、
        8 MiB の JSON (約 26 万件) で数時間・テラバイト級の書き込みになる。しかも
        `/rpc` は `server.lock` を握ったまま走るのでアプリ全体が固まる。
        よって「全件をメモリ上で適用 → `_rebuild_index` 1 回 → `_save` 1 回」に畳む。

        上限 (`MAX_DICT_ENTRIES`) を超える取り込みは**何も変更せずに** `ValueError`。
        途中まで書いた辞書を残さないため、判定は適用前に済ませる。
        """
        try:
            data = json.loads(_read_text_limited(Path(path)))
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            raise ValueError(f"辞書ファイルを読み込めません: {exc}") from exc

        # ① 検証だけを先に回す (壊れた要素はここで捨て、件数を数える)。
        skipped = 0
        pending: List[tuple[str, str, bool]] = []
        for item in data if isinstance(data, list) else []:
            entry = self._entry_from_json(item)
            if entry is None:
                skipped += 1
                continue
            src, target, _enabled, joined = entry
            pending.append((src.strip(), target.strip(), joined))

        # ② 適用後の件数を先に見積もって上限を判定する (新規キーだけが増える)。
        added_keys = set()
        for src, _t, _j in pending:
            key = normalize(src)
            if key not in self._norm_index:
                added_keys.add(key)
        if len(self._mappings) + len(added_keys) > MAX_DICT_ENTRIES:
            raise ValueError(
                f"辞書エントリが多すぎます (取り込み後 "
                f"{len(self._mappings) + len(added_keys)} 件 / 上限 {MAX_DICT_ENTRIES} 件)。"
            )

        # ③ メモリ上だけで適用する (保存・索引再構築は最後に 1 回)。
        for src, target, joined in pending:
            key = normalize(src)
            existing = self._norm_index.get(key)
            if existing is not None:
                existing.target = target
                existing.source_raw = src
                existing.joined = joined
                continue
            m = Mapping(
                id=self._next_id, source_raw=src, target=target, joined=joined,
            )
            self._next_id += 1
            self._mappings.append(m)
            self._norm_index[key] = m
        self._rebuild_index()
        self._save()
        return ImportResult(imported=len(pending), skipped=skipped)
