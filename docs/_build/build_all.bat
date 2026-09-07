@echo off
chcp 65001 >nul
rem 依存(PyYAML / markdown-it-py / python-frontmatter)を用意してから build_all.py を実行する。
rem pip へ渡す前に requirements の形式を検査する(オプション行・直 URL・ローカルパスを拒否)。
call "%~dp0..\..\scripts\check-requirements.bat" -Path "%~dp0requirements.txt"
if errorlevel 1 exit /b 1
rem py -3.13 を使う(本リポの前提。裸の python は WindowsApps の未導入エイリアスに化ける端末がある)。
py -3.13 -m pip install -q -r "%~dp0requirements.txt"
rem 同梱の build_all.py を実行（引数はそのまま転送）。全原稿から閲覧用 HTML（手引き/設計）を一括生成する。
py -3.13 "%~dp0build_all.py" %*
exit /b %ERRORLEVEL%
