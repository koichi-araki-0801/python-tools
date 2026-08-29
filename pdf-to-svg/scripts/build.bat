@echo off
chcp 65001 >nul
rem 同梱の build.py を py -3.13 で実行する(引数はそのまま転送。例: build.bat clean)。
py -3.13 "%~dp0build.py" %*
exit /b %ERRORLEVEL%
