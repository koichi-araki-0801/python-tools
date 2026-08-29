@echo off
chcp 65001 >nul
rem 同梱の capture_screens.py を py -3.13 で実行する（引数はそのまま転送）。PdfToSvg の操作手順書向けスクショ取得。
py -3.13 "%~dp0capture_screens.py" %*
exit /b %ERRORLEVEL%
