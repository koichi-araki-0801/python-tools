# -*- coding: utf-8 -*-
"""offline 重量物バンドルの分離署名に使う Ed25519 鍵ペアを 1 回だけ生成する(公開担当者用)。

秘密鍵はユーザープロファイル配下(既定 `%USERPROFILE%\\.python-tools-signing`)へ、公開鍵は
リポジトリの `offline/bundle-signing.pub.pem` へ書き出す。公開鍵は `offline/` フォルダごと
手渡しで配布先へ運ばれ、setup(次タスク)側の唯一の真正性の根拠になる。

既存の鍵がある場合は上書きしない(`--force` で明示的に置き換える)。鍵を作り直すと過去に
公開した署名は検証できなくなるため、置き換え時は重量物の再公開が必要になる。

鍵形式は Ed25519-PEM(`cryptography`)を使う。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

import bundle_common  # noqa: E402

DEFAULT_PRIVATE_KEY_PATH = (
    Path(os.environ.get("USERPROFILE", str(Path.home())))
    / ".python-tools-signing"
    / "bundle-signing.key.pem"
)
DEFAULT_PUBLIC_KEY_PATH = _HERE / "bundle-signing.pub.pem"


def _restrict_to_owner(path: Path) -> None:
    """秘密鍵の ACL を所有者のみへ切り詰める(継承を切って現ユーザーだけを残す)。

    Windows 専用(`icacls`)。失敗したら例外を送出し、呼び出し側で鍵ファイルを削除させる
    (権限を絞れなかった秘密鍵を「生成成功」として残さない。fail closed)。
    """
    domain = os.environ.get("USERDOMAIN", "")
    name = os.environ.get("USERNAME", "")
    if not name:
        raise RuntimeError("USERNAME 環境変数が取得できません(ACL 設定に必要)。")
    account = f"{domain}\\{name}" if domain else name
    result = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{account}:F"],
        capture_output=True,
        # `icacls` は既定でロケール依存のコードページ (日本語 Windows では cp932) で出力する
        # (UTF-8 化する `chcp` 等を挟んでいない)。`text=True` かつ `encoding` 未指定のまま
        # (= プロセスのデフォルトロケールで decode) にしておくのが正しい選択であり、他の
        # subprocess 呼び出しと同じ規約(`encoding="utf-8"` 明示)へ揃えてはならない
        # (揃えると `result.stderr` の日本語エラーメッセージが文字化け/デコード例外になる。M-3)。
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"icacls による ACL 設定に失敗しました: {result.stderr.strip()}")


def create_signing_key_pair(
    private_key_path: Path, public_key_path: Path, *, force: bool = False
) -> None:
    """鍵ペアを生成し、`private_key_path` / `public_key_path` へ書き出す。"""
    for p in (private_key_path, public_key_path):
        if p.is_file() and not force:
            raise RuntimeError(
                f"既に鍵があります: {p}(置き換えるなら --force。過去の署名は検証できなくなります)"
            )

    private_key_dir = private_key_path.parent
    private_key_dir.mkdir(parents=True, exist_ok=True)
    # ディレクトリ側の ACL も所有者のみへ絞る(M-2)。ファイル単体の ACL だけを絞っても、
    # 同ディレクトリへ他ユーザーが書き込める状態が残っていれば、鍵ファイルの置き換え
    # (すり替え)自体は防げない。ここが失敗したら、まだ鍵材料を何も生成・書き込みしていない
    # 段階なので中止するだけでよい(削除すべき生成物が無い)。
    _restrict_to_owner(private_key_dir)

    private_pem, public_pem = bundle_common.generate_signing_key_pair()

    # 秘密鍵の内容は「ACL を絞った後」にしか書かない(M-2)。既定 ACL のまま内容を書いてから
    # 絞ると、書き込み〜ACL 確定までの間だけ既定 ACL で内容が読める窓ができる。先に空ファイル
    # を作って ACL を確定させ(空ファイルが既定 ACL で一瞬存在する窓は残るが、そこに秘密鍵の
    # 内容は無い)、その後で内容を書く。
    private_key_path.touch(exist_ok=True)
    try:
        _restrict_to_owner(private_key_path)
        private_key_path.write_bytes(private_pem)
    except Exception:
        private_key_path.unlink(missing_ok=True)
        raise

    public_key_path.write_bytes(public_pem)


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--private-key-path",
        type=Path,
        default=DEFAULT_PRIVATE_KEY_PATH,
        help=f"秘密鍵(Ed25519 PEM)の出力先(既定 {DEFAULT_PRIVATE_KEY_PATH})",
    )
    parser.add_argument(
        "--public-key-path",
        type=Path,
        default=DEFAULT_PUBLIC_KEY_PATH,
        help=f"公開鍵(Ed25519 PEM)の出力先(既定 {DEFAULT_PUBLIC_KEY_PATH})",
    )
    parser.add_argument("--force", action="store_true", help="既存の鍵ファイルを上書きする")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        create_signing_key_pair(args.private_key_path, args.public_key_path, force=args.force)
    except RuntimeError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    print(f"[OK] 秘密鍵: {args.private_key_path}(バックアップは各自で。リポジトリへは絶対に入れない)")
    print(f"[OK] 公開鍵: {args.public_key_path}(このファイルをコミットし、offline/ ごと配布先へ運ぶ)")
    print("次に offline\\publish-bundle.bat を引数なしで実行し、署名付きで重量物を公開してください。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
