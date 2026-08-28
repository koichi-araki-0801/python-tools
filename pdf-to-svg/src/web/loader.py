"""アップロードされた PDF バイト列を `Document` へ変換する。

ブラウザ (File System Access API) で選んだ PDF は `/upload` でバイト列として
届く。一方コアの `pdf_engine.py` の `load_document` は実ファイルパスを前提
(`fitz.open(path)`) とする。コアを一切変更しないため、受信バイトを一時ファイルへ
書き出してから `load_document` を呼び、表示名 (=書き出し時の stem) だけを
`source_path` に上書きする。`load_document` は `with` で fitz を閉じるので
直後の `unlink` は Windows でも成功する。
"""
from __future__ import annotations

import os
import tempfile

from engine.pdf_engine import load_document
from model.document import Document


def load_document_bytes(name: str, data: bytes) -> Document:
    """受信バイト `data` を temp 経由で `load_document` に渡し `Document` を返す。

    表示名 `name` を `source_path` へ、バイト長を `byte_size` へ載せ替える。
    """
    fd, tmp = tempfile.mkstemp(suffix=".pdf", prefix="pdftosvg-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        doc = load_document(tmp)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    # source_path は実パスではなく「元の表示名」。書き出しファイル名の stem に使う。
    doc.source_path = name
    # ファイルカードのサイズ表示用にバイト長を保持 (実パスが無く getsize できないため)。
    doc.byte_size = len(data)  # type: ignore[attr-defined]
    return doc
