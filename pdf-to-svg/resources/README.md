# resources/

ビルド時に同梱される任意リソース。

- `icons/app.ico` — アプリアイコン（あれば .exe に埋め込まれる）

このフォルダが存在すれば PyInstaller が `resources/` ごとバンドルする
（`packaging/pdftosvg.spec` の `datas`）。
