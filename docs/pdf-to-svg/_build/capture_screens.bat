@echo off
chcp 65001 >nul
rem 同梱の capture_screens.py を実行（引数はそのまま転送）。PdfToSvg の操作手順書向けスクショ取得。
python "%~dp0capture_screens.py" %*
exit /b %ERRORLEVEL%
