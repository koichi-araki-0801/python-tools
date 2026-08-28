# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec。

ビルド:  pyinstaller packaging/pdftosvg.spec
出力:    dist/PdfToSvg/PdfToSvg.exe   (onedir)

方針:
- onedir (起動が速く AV 誤検知が少ない)。配布は dist/PdfToSvg/ フォルダごとコピー。
- UI は OS 標準の Edge をアプリモードで開くため Qt ランタイムは同梱しない (軽量)。
"""
import os
from PyInstaller.utils.hooks import collect_dynamic_libs

block_cipher = None

# SPECPATH は PyInstaller が注入する spec ファイルのあるディレクトリ。
# これを基準にすることで、どこから pyinstaller を起動しても同じ結果になる。
ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
RESOURCES = os.path.join(ROOT, "resources")

# 任意リソース (存在すれば同梱)
datas = []
if os.path.isdir(RESOURCES):
    datas.append((RESOURCES, "resources"))

# 同梱フォント (本プロジェクトの fonts/)。BIZ UDPGothic (TTF) / Noto Serif JP を
# config.font_dir() が frozen 時に _MEIPASS/fonts として解決するため fonts 配下へ展開。
FONTS = os.path.join(ROOT, "fonts")
if os.path.isdir(FONTS):
    datas.append((FONTS, "fonts"))

# PyMuPDF のネイティブライブラリを確実に同梱
binaries = collect_dynamic_libs("fitz")

# UI は OS 標準の Edge を「アプリモード」で開いて描画する (web.server + resources/web)。
# PySide6 / QtWebEngine は実行時に一切使わないため明示的に除外し、Qt ランタイム
# (QtWebEngineProcess.exe / *.pak / locales / ICU / 各 Qt DLL) の同梱を防ぐ。
# これで配布サイズが従来比 ~120〜150MB 縮む。tkinter も未使用。
excludes = [
    "PySide6",
    "shiboken6",
    "tkinter",
]

a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PdfToSvg",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI アプリなのでコンソール非表示
    icon=os.path.join(RESOURCES, "icons", "app.ico")
    if os.path.exists(os.path.join(RESOURCES, "icons", "app.ico"))
    else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PdfToSvg",
)
