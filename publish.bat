@echo off
rem 一键发布：git 推送（代码备份/触发 CF 部署）+ wrangler 直接部署（主通道）
cd /d "%~dp0"
set MSG=%~1
if "%MSG%"=="" set MSG=data update %date% %time%
git add -A
git -c user.name="hccccc01333" -c user.email="hccccc01333@users.noreply.github.com" commit -m "%MSG%"
git push
echo [1/2] git pushed
call npx --yes wrangler@latest deploy
if errorlevel 1 (
  echo [!] wrangler 部署失败（首次使用请先在本目录运行: npx wrangler login）
) else (
  echo [2/2] deployed to Cloudflare
)
