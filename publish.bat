@echo off
rem 一键发布：提交全部改动并推送（托管平台自动重新部署）
cd /d "%~dp0"
set MSG=%~1
if "%MSG%"=="" set MSG=data update %date% %time%
git add -A
git -c user.name="hccccc01333" -c user.email="hccccc01333@users.noreply.github.com" commit -m "%MSG%"
git push
echo [OK] pushed: %MSG%
