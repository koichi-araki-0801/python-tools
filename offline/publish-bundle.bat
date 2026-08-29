@echo off
chcp 65001 >nul
rem 同梱の publish_bundle.py を py -3.13 で実行する(引数はそのまま転送)。
py -3.13 "%~dp0publish_bundle.py" %*
exit /b %ERRORLEVEL%
