@echo off
chcp 65001 >nul
rem 同梱の scripts\setup_dev.py を py -3.13 で実行する(引数はそのまま転送)。
py -3.13 "%~dp0scripts\setup_dev.py" %*
exit /b %ERRORLEVEL%
