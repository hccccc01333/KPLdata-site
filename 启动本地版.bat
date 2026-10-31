@echo off
chcp 65001 >nul
title 峡谷有数 · 本地专业版
cd /d "%~dp0"
where python >nul 2>nul && (python server.py) || (py -3 server.py)
pause
