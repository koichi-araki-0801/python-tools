@echo off
chcp 65001 >nul
rem 同梱の check_requirements.py を py -3.13 で実行する(引数はそのまま転送)。
rem 旧名 check-requirements.bat を維持する。docs\_build\build_all.bat:7 が
rem -Path 引数付きの旧形式で呼ぶ既存互換のため、この名前とインターフェースを変えない。
py -3.13 "%~dp0check_requirements.py" %*
exit /b %ERRORLEVEL%
