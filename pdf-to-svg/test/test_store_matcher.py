"""`dictionary.store.DictionaryStore` の単体テスト。

追加・引き当て (正規化込みの `lookup`)・`upsert`・無効化・JSON 取り込みの往復と、
**壊れた辞書ファイルで起動不能にならないこと**、および
**読めなかった/他者更新された辞書を上書きで消さないこと** (ネットワークドライブ共有
運用のゲート) を確認する。
"""
import pytest

import dictionary.store as store_module
from dictionary.store import DictionaryStore


def make_store(tmp_path):
    return DictionaryStore(tmp_path / "d.json")


def test_add_and_lookup(tmp_path):
    s = make_store(tmp_path)
    s.add("Sales", "売上")
    assert s.lookup("Sales") == "売上"
    s.close()


def test_lookup_normalizes_fullwidth(tmp_path):
    s = make_store(tmp_path)
    s.add("ABC", "エービーシー")
    # 全角で引いても一致する
    assert s.lookup("ＡＢＣ") == "エービーシー"
    s.close()


def test_upsert_updates_existing(tmp_path):
    s = make_store(tmp_path)
    s.add("Qty", "数量")
    s.upsert("Qty", "個数")
    assert s.lookup("Qty") == "個数"
    assert len(s.all()) == 1
    s.close()


def test_disabled_not_matched(tmp_path):
    s = make_store(tmp_path)
    s.add("Total", "合計", enabled=False)
    assert s.lookup("Total") is None
    s.close()


def test_json_roundtrip(tmp_path):
    # 実体ファイルは共有 JSON と同形式なので、それを直接 import 元にできる。
    s = make_store(tmp_path)
    s.add("A", "あ")
    s.add("B", "い")
    s2 = DictionaryStore(tmp_path / "d2.json")
    n = s2.import_json(tmp_path / "d.json")
    assert (n.imported, n.skipped) == (2, 0)
    assert s2.lookup("A") == "あ"
    s.close()
    s2.close()


def test_lookup_wrap_matches_joined_entries_only(tmp_path):
    """`lookup_wrap` は連結由来 (joined=True) エントリのみ引く。`lookup` は両方引く。"""
    s = make_store(tmp_path)
    s.add("商品名称", "Product", joined=True)
    s.add("備考", "Note")  # 手入力相当 (非連結)
    assert s.lookup_wrap("商品名称") == "Product"
    assert s.lookup_wrap("備考") is None       # 非連結エントリは連結照合に使わない
    assert s.lookup("備考") == "Note"          # 単独照合では従来どおり引ける
    s.close()


def test_joined_flag_persists_roundtrip(tmp_path):
    """joined フラグは実体ファイルの再読込・import の双方で保持される。"""
    s = make_store(tmp_path)
    s.add("商品名称", "Product", joined=True)
    # 実体ファイルの再読込 (同パスで開き直し)
    s2 = DictionaryStore(tmp_path / "d.json")
    assert s2.lookup_wrap("商品名称") == "Product"
    # 実体ファイル (共有 JSON と同形式) を別ストアへ import しても保持
    s3 = DictionaryStore(tmp_path / "d3.json")
    s3.import_json(tmp_path / "d.json")
    assert s3.lookup_wrap("商品名称") == "Product"
    s.close()
    s2.close()
    s3.close()


def test_legacy_json_without_joined_key(tmp_path):
    """旧形式 (joined キー無し) の JSON は非連結として読める (後方互換)。"""
    legacy = tmp_path / "legacy.json"
    legacy.write_text(
        '[{"source": "Total", "target": "合計", "enabled": true}]', encoding="utf-8"
    )
    s = DictionaryStore(legacy)
    assert s.lookup("Total") == "合計"
    assert s.lookup_wrap("Total") is None  # 連結照合の対象にはならない
    s.close()


# ── 壊れた辞書ファイルで起動不能にしない ──────────────────────────────────

def test_broken_entry_is_skipped_instead_of_crashing_startup(tmp_path):
    """リストに dict 以外が混ざっても `__init__` を例外 (AttributeError) で抜けない。

    `console=False` の exe では例外が画面に出ないため、例外を抜けさせると辞書 1 要素の
    型崩れが「何も起きず起動しない」恒久 DoS になる。辞書はメール・共有フォルダ経由で
    配られる外部由来の入力なので、壊れた要素は捨てて起動を通す。
    """
    path = tmp_path / "d.json"
    path.write_text(
        '["oops", {"source": "A", "target": "\\u3042"}, 42, null,'
        ' {"source": 5, "target": "x"}, {"source": "B", "target": 9}]',
        encoding="utf-8",
    )

    s = DictionaryStore(path)

    assert s.lookup("A") == "あ"
    assert len(s.all()) == 1
    # 黙って消さない: 捨てた件数を利用者へ返す経路 (`rpc_dictList` → `app.js`)。
    assert s.load_skipped == 5
    assert s.load_failed is False
    s.close()


def test_unparsable_file_is_reported_rather_than_silently_empty(tmp_path):
    """壊れた JSON は空辞書で起動しつつ「読めなかった」を伝える (辞書消失に見せない)。"""
    path = tmp_path / "d.json"
    path.write_text("{ this is not json", encoding="utf-8")

    s = DictionaryStore(path)

    assert s.all() == []
    assert s.load_failed is True
    s.close()


def test_missing_file_is_not_reported_as_a_failure(tmp_path):
    """初回起動 (ファイル未作成) は異常ではない (通知を出さない)。"""
    s = DictionaryStore(tmp_path / "not-created-yet.json")
    assert s.load_failed is False and s.load_skipped == 0
    s.close()


def test_import_reports_skipped_broken_entries(tmp_path):
    """取り込みでも壊れた要素は捨てて件数を返す (画面が件数を出す)。"""
    src = tmp_path / "shared.json"
    src.write_text('[{"source": "A", "target": "あ"}, "oops", {"target": "空"}]',
                   encoding="utf-8")
    s = DictionaryStore(tmp_path / "d.json")

    result = s.import_json(src)

    assert (result.imported, result.skipped) == (1, 2)
    s.close()


# ── ネットワークドライブ共有運用のゲート: 読めない/古い状態からの全件上書きを止める ──

def test_transient_read_failure_blocks_saving(tmp_path, monkeypatch):
    """瞬断等で読めなかった辞書は `load_failed` を立て、保存 (全件書き直し) を拒む。

    `Path.exists()` はドライブ未接続系の OSError を握りつぶして False を返すため、
    それを信じると「ファイル無し」と誤判定 → 空辞書で起動 → 次の保存で本物を空上書き、
    という無音のデータ消失になる。読みを直接試みて不在と不明を区別する。
    """
    path = tmp_path / "d.json"
    path.write_text('[{"source": "A", "target": "\\u3042"}]', encoding="utf-8")

    def deny(_path):
        raise PermissionError(13, "share is not reachable")

    monkeypatch.setattr(store_module, "_read_text_limited", deny)
    s = DictionaryStore(path)
    assert s.load_failed is True

    with pytest.raises(ValueError, match="保存しません"):
        s.add("B", "い")

    # 本物のファイルは無傷 (空で上書きされていない)
    assert "A" in path.read_text(encoding="utf-8")
    s.close()


def test_concurrent_update_by_another_user_is_not_overwritten(tmp_path):
    """別プロセス (共有フォルダの他利用者) がファイルを更新していたら保存を拒む。

    保存は全件のシリアライズなので、古い状態からの保存は相手の追加を丸ごと消す
    (last-writer-wins)。ファイル状態 (mtime, size) の照合で検出し、相手の変更を残す。
    """
    path = tmp_path / "d.json"
    s1 = DictionaryStore(path)
    s1.add("A", "あ")

    s2 = DictionaryStore(path)   # この時点の状態を記憶
    s1.add("B", "い")            # 他利用者に相当する更新

    with pytest.raises(ValueError, match="他の利用者"):
        s2.add("C", "う")

    # 相手 (s1) の追加が残っている (s2 の古い全量で上書きされていない)
    text = path.read_text(encoding="utf-8")
    assert "B" in text and "C" not in text
    s1.close()
    s2.close()


def test_deleted_file_is_not_recreated_from_memory(tmp_path):
    """読んだはずのファイルが消えていたら、メモリ内容での復活書き込みをしない。"""
    path = tmp_path / "d.json"
    s = DictionaryStore(path)
    s.add("A", "あ")

    path.unlink()  # 他利用者の削除・移動に相当

    with pytest.raises(ValueError, match="見つかりません"):
        s.add("B", "い")
    assert not path.exists()
    s.close()


def test_upsert_updates_joined(tmp_path):
    """連結取り込みで登録し直すと既存エントリの joined も更新される。"""
    s = make_store(tmp_path)
    s.add("商品名称", "Product")  # まず手入力 (非連結)
    assert s.lookup_wrap("商品名称") is None
    s.upsert("商品名称", "Product", joined=True)
    assert s.lookup_wrap("商品名称") == "Product"
    assert len(s.all()) == 1
    s.close()
