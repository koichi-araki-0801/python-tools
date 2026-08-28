"""Web UI レイヤ: ローカル HTTP サーバ上のフロントエンドと Python バックエンドの橋渡し。

- `server`     : ローカル HTTP サーバ (静的配信 + /rpc + /upload + ライフサイクル)。
- `rpc_methods`: RPC メソッドの実体 (既存 engine/dictionary/export を薄く包む)。
- `loader`     : アップロードされた PDF バイト列を `Document` へ (temp 経由)。
- `commands`   : 編集操作のコマンド群 (redo/undo を持つ素の Python クラス)。
- `undo_stack` : Qt 非依存の Undo/Redo スタック (マクロ畳み対応)。
"""
