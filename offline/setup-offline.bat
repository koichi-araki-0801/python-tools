@echo off
chcp 65001 >nul
rem 同梱の setup_offline.py を py -3.13 で実行する(引数はそのまま転送)。
py -3.13 "%~dp0setup_offline.py" %*
exit /b %ERRORLEVEL%
