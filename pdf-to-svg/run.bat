@echo off
chcp 65001 >nul
rem pushd にする理由: cmd.exe は UNC パスをカレントディレクトリにできず、`cd /d` は
rem 黙って C:\Windows のまま続行して後続の相対パス実行 (run.py) が即死する。
rem pushd は UNC を一時ドライブレターへ自動マップする。
pushd "%~dp0" || (
    echo [エラー] フォルダへ移動できません: %~dp0
    pause
    exit /b 1
)
title PdfToSvg 起動

rem py -3.13 を使う(本リポの前提。裸の python は WindowsApps の未導入エイリアスに
rem 化ける端末があるため、他の入口スクリプト(build.bat 等)と同じく py -3.13 を明示する)。
echo PdfToSvg を起動します...
py -3.13 run.py

if errorlevel 1 (
    echo.
    echo [エラー] 起動に失敗しました。
    echo 依存が未導入の場合は scripts\build.bat を一度実行してください。
    pause
)
