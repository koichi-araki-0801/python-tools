@echo off
chcp 65001 >nul
rem 依存(PyYAML / markdown-it-py / python-frontmatter)を用意してから build_all.py を実行する。
rem オフライン時は 2 つ上(ワークスペース直下)の python-wheelhouse から --no-index で導入する。
rem pip へ渡す前に requirements の形式を検査する(オプション行・直 URL・ローカルパスを拒否)。
rem --no-index は requirements 内の --find-links や直 URL 参照を止めないので省略できない。
call "%~dp0..\..\scripts\check-requirements.bat" -Path "%~dp0requirements.txt"
if errorlevel 1 exit /b 1
rem py -3.13 を使う(本リポの前提。裸の python は WindowsApps の未導入エイリアスに化ける端末がある)。
if exist "%~dp0..\..\python-wheelhouse\" (
  py -3.13 -m pip install -q --no-index --find-links "%~dp0..\..\python-wheelhouse" -r "%~dp0requirements.txt"
) else (
  py -3.13 -m pip install -q -r "%~dp0requirements.txt"
)
rem 同梱の build_all.py を実行（引数はそのまま転送）。全原稿から閲覧用 HTML（手引き/設計）を一括生成する。
py -3.13 "%~dp0build_all.py" %*
exit /b %ERRORLEVEL%
