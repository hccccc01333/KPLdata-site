@echo off
setlocal enabledelayedexpansion
rem 一键发布：git 提交推送（代码备份 + 触发托管构建）→ wrangler 部署（主通道）
rem 任何一步失败立即中止，避免"仓库版本"和"线上版本"对不上。
rem
rem 用法：
rem   publish.bat "提交说明"       提交 + 推送 + 部署（日常）
rem   publish.bat --deploy-only    只部署，不动 git（代码已推送、只想更新线上时用）
rem
rem 为什么不用 git add -A：
rem   2026-10-18 曾因为 -A 把浏览器临时 profile（.edge-tmp3，291 个文件）提交进公开仓库。
rem   这里只暂存「已跟踪文件的改动」+ 生成目录 assets/，其余未跟踪文件一律先拦下来。
cd /d "%~dp0"

set MSG=%~1
if "%MSG%"=="" set MSG=data update %date% %time%

rem ---- 0) 发布前数据质量门禁：任何一项失败都不允许提交/部署 ----
python check_data_quality.py
if errorlevel 1 (
  echo [!] 数据质量检查未通过，已中止发布。
  exit /b 1
)
python check_series_consistency.py
if errorlevel 1 (
  echo [!] 系列赛口径检查未通过，已中止发布。
  exit /b 1
)
echo [0/2] data quality passed

rem ---- 0.5) 仅部署模式：跳过 git，直接部署 ----
if /i "%MSG%"=="--deploy-only" goto deploy

rem ---- 1) 选择性暂存 ----
git add -u
if exist assets git add assets
rem 事件 Worker 与部署配置是站点代码，必须随代码提交，不能只留在本地
if exist worker.js git add worker.js
if exist wrangler.toml git add wrangler.toml
if exist .assetsignore git add .assetsignore

rem ---- 2) 未跟踪文件检查（拦住缓存 / 临时目录 / 陌生文件）----
set TMPF=%TEMP%\kpl_publish_status.txt
set TMPU=%TEMP%\kpl_publish_untracked.txt
git status --porcelain > "%TMPF%"
findstr /b "??" "%TMPF%" > "%TMPU%"
set USIZE=0
for %%A in ("%TMPU%") do set USIZE=%%~zA
if not "%USIZE%"=="0" (
  echo [!] 有未跟踪文件未纳入本次提交：
  type "%TMPU%"
  echo.
  echo     要提交就手动 git add 后重跑；不要提交就加进 .gitignore。
  del "%TMPF%" "%TMPU%" 2>nul
  exit /b 2
)
del "%TMPF%" "%TMPU%" 2>nul

rem ---- 3) 提交 ----
git -c user.name="hccccc01333" -c user.email="hccccc01333@users.noreply.github.com" commit -m "%MSG%"
if errorlevel 1 echo [i] 没有可提交的改动，继续推送已有提交

rem ---- 4) 推送：失败就中止，不再往下部署 ----
git push
if errorlevel 1 (
  echo [!] git push 失败，已中止部署（避免线上与仓库版本不一致）
  exit /b 1
)
echo [1/2] git pushed

rem ---- 5) 部署 ----
:deploy
call npx --yes wrangler@latest deploy
if errorlevel 1 (
  echo [!] wrangler 部署失败（首次使用请先在本目录运行: npx wrangler login）
  echo     注意：代码已推送，但线上可能仍是旧版本。
  exit /b 1
)
echo [2/2] deployed to Cloudflare
echo.
echo 提示：部署命令成功只代表上传完成，请再用浏览器打开线上域名核对首页与复盘深链。
endlocal
