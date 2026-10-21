# KPL 数据中心 · 官网

KPL 赛事数据产品站点（纯静态）：赛程比分、战队 / 选手 / 英雄数据、BP 分析、逐局复盘、实时胜率、预测公开统计、精选对局、系列赛研究、荣誉与纪录。

- 数据来源：腾讯 KPL 官方公开接口（赛程 / 对局 / 局内快照）；个人搭建的赛事数据产品，**非官方、与腾讯无关联**
- 技术：纯静态 HTML + 原生 JS，无框架、无构建步骤；数据由 Python 脚本离线生成为 `assets/*.js`
- 实时链路：比赛日 1 秒粒度采集快照，实时页 30 秒刷新（胜率曲线 / 指标 / 趋势外推预测），逐局自动归档
- 当前视觉：V5.5「竞技媒体白」——浅色页面、白色卡片、深色赛事头图、品牌红强调
- 部署：Cloudflare Workers 主站，推送到仓库即自动发布（见「发布」）；GitHub Pages 国内镜像在数据更新后自动同步
- 在线地址：主站 <https://kpldata-site.hccccc01333.workers.dev> · 国内镜像 <https://hccccc01333.github.io/KPLdata-site/>（主站的 `workers.dev` 域名在国内被 DNS 污染，国内访问请用镜像）

## 数据规模

<!-- STATS:BEGIN -->
| 项 | 数量 | 说明 |
|---|---|---|
| 赛事 | 33 个 | 2019–2026，含季前赛 / 常规赛 / 季后赛 / 总决赛 |
| 比赛（大场） | 2,888 场 | `assets/schedule_all.js`，全历史赛程与比分 |
| 对局（小局） | 11,128 局 | `assets/games/*.json`，33 个分片，按需加载 |
| 逐帧回放 | 212 局（63 场） | `assets/replay/*.json`，有分钟级快照的局；**精选对局与分时命中率只在这 212 局里算** |
| 搜索索引 | 3,589 条 | 战队 / 选手 / 英雄 / 全部比赛，首次输入时懒加载 |

> 覆盖边界要讲清楚：赛程比分是全历史的，但**逐分钟胜率只覆盖 212 局**。
> 所以「精选对局」「分时点命中率」的分母是 212，不是 11,128 —— 页面上写的样本量都指这个口径。
<!-- STATS:END -->

> 上面的数字由 `sync_readme_stats.py` 读 `assets/*.js` 索引自动生成（构建链最后一步调用），勿手工改。

## 当前状态

- 站点已从「多页面数据展示」收敛为 **V5.5 数据产品**：32 个页面 + 404，21 个离线构建脚本。
- 数据正确性（2026-10-21）：系列赛 / 战队 Elo 已按真实战队身份重算；选手深挖逐局胜负改用 `battle_winner_team`；资源指标 `kill_big_dragon_num` 已去重；`check_series_consistency.py` 作为发布门禁。
- 胜率沙盘已上线：212 局概率地形、同状态历史检索、What-if 与 V12 模型体检；数据由 `build_sandbox_data.py` 生成。
- BP 赛事演播室已上线：真实比赛逐手选禁回放、双方最终阵容、系列赛前几局英雄使用，支持深链与三档响应式。
- 仍在开发：V5 P2 其余项（今日观赛助手 / 本命英雄对局助手 / honors-v2 剩余项）。
- 已知限制：部分历史系列赛缺官方胜负或逐局不完整；分钟级复盘只覆盖 212 局；模型测试集只有 20 局，不能当作稳定预测服务。

## 页面（32 个 + 404）

| 模块 | 页面 |
|---|---|
| 首页与赛程 | `index.html`、`schedule.html`、`bracket.html`（赛事进程）、`updates.html`（更新日志） |
| 比赛与复盘 | `match.html`（复盘工作台 / 分享深链）、`game.html`（单局战报）、`picks.html`（精选对局）、`comeback.html`（翻盘路径） |
| 战队 | `teams.html`、`team.html`（能力雷达 / 系列赛画像 / 冠军墙）、`h2h.html` |
| 选手 | `players.html`、`player.html`（能力雷达 / 关键局 / 打法画像 / 搭档对位） |
| 英雄 | `heroes.html`、`hero.html`、`combos.html` |
| 深度分析 | `bp.html`、`bp-studio.html`（真实比赛 BP 演播室）、`sandbox.html`（胜率沙盘 / 同状态检索 / 模型体检）、`series.html`（首局转化 / 决胜局 / 让二追三 / Elo）、`honors.html`、`records.html`、`stage.html`、`predict.html`（含赛前预测挑战）、`find.html`（按终局条件找局）、`simulator.html`、`query.html` |
| 对比工具 | `compare.html`、`compare-team.html`、`compare-player.html`、`compare-lane.html` |
| 说明 | `about.html`、`404.html` |

## 构建脚本（21 个）

数据全部离线生成，页面只读 `assets/*.js`。

| 分组 | 脚本 |
|---|---|
| 主数据 | `build_data.py`、`build_history_data.py`、`build_game_details.py`、`build_replay_frames.py`、`build_search_index.py` |
| 比赛与预测 | `build_picks.py`、`build_predict_data.py`、`build_comeback_data.py`、`build_prematch_backtest.py` |
| 战队 / 选手 / 英雄 | `build_team_data.py`、`build_player_details.py`、`build_player_deep.py`、`build_power_data.py`、`build_pro_hero.py`、`build_hero_growth.py`、`build_equip_data.py` |
| BP / 系列赛 / 荣誉 / 纪录 | `build_bp_data.py`、`build_deep_data.py`、`build_honors_data.py`、`build_records.py` |
| 交互 / 模型体检 | `build_sandbox_data.py`（概率地形 / 同状态索引 / 可靠性数据） |

辅助脚本：`sync_readme_stats.py` 把上面的「数据规模」与 `assets/*.js` 索引对齐。

## 质量门禁

发布前必须通过：

```bash
python check_data_quality.py        # 缺失值/假零、跨页面同口径、荣誉字段
python check_series_consistency.py  # deep.js 对原始逐局数据的独立复算 + players_detail 交叉校验
python test_series_logic.py         # 换边/让二追三/官方兜底/重复局号/串场局回归
```

- `check_series_consistency.py` 发现严重不一致时返回退出码 1；比赛日快速链路两项检查都会执行，但加 `--skip-cross-page` 跳过依赖 `players_detail.js` / `player_deep.js` 刷新的跨页比对，避免旧资产误报。
- `publish.bat` 在 git 提交 / 部署前强制执行前两项检查，`--deploy-only` 也不例外。
- 核心仓库的 `scripts/watch_site_data.py` 负责自动重建：构建或门禁失败时不推进 state，保留旧状态并在 5 分钟后自动重试。

浏览器验收：

```bash
python -m http.server 8777
node _check_pages.js http://127.0.0.1:8777   # 全站异常 / 渲染 / 交互 / 响应式
node _check_sandbox.js http://127.0.0.1:8777 # 胜率沙盘专项：地形 / What-if / 响应式
node _regress.js                             # 分层回归总入口
```

## 目录

```text
*.html                 32 个页面 + 404（纯静态，无构建步骤）
assets/v55.css         V5.5 竞技媒体白主题（当前视觉）
assets/style.css       基础样式与旧主题层
assets/pages.css       页面级样式
assets/sandbox.css     胜率沙盘页面样式
assets/common.js       导航 / 页脚 / 搜索 / 深链工具
assets/data.js         站点主数据（各 build_*.py 产物同目录）
assets/sandbox.js      胜率沙盘数据（构建产物）
assets/sandbox_app.js  胜率沙盘交互（手写源码，不走自动数据提交）
assets/games/          逐局详情分片，按需加载
assets/replay/         复盘时间轴数据包
assets/live_hist/      实时预测归档分片
build_*.py             21 个数据生成脚本（读 ../02-KPL实时胜率预测系统）
check_*.py             数据质量门禁
DESIGN.md              设计规范
```

数据由本地赛事数据仓（采集 + 模型，`../02-KPL实时胜率预测系统`）生成后推送本仓库。数据仅用于学习研究，请勿再分发。

## 发布

```bat
publish.bat "更新说明"    # 质量门禁 → 提交 → 推送 → 部署（Cloudflare 主站）
publish.bat --deploy-only # 只部署（仍先跑质量门禁）
```

GitHub Pages 国内镜像由 `.github/workflows/pages.yml` 在 `main` 收到数据更新时自动发布（内置 9 分钟部署间隔闸门，约每 10 分钟一次），只发布 `*.html` 与 `assets/`。需要立即同步时，在 Actions 页手动运行该工作流。

## 声明

本项目为非官方个人项目，与腾讯 / KPL 官方无关联；赛事数据、商标与第三方资源归各自权利人所有。站内模型输出仅用于数据分析展示，不构成预测或投注建议。
