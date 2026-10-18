# KPL 数据中心 · 官网

KPL 赛事数据产品站点（纯静态）：赛程比分、战队 / 选手 / 英雄数据、BP 分析、逐局复盘、实时胜率、预测公开统计、精选对局索引。

- 数据来源：腾讯 KPL 官方公开接口（赛程 / 对局 / 局内快照），个人搭建的赛事数据产品，**非官方、与腾讯无关联**
- 技术：纯静态 HTML + 原生 JS，无框架、无构建步骤；数据由 Python 脚本离线生成为 `assets/*.js`
- 实时链路：比赛日 1 秒粒度采集快照，实时页 30 秒刷新（胜率曲线 / 指标 / 趋势外推预测），逐局自动归档
- 部署：静态托管，推送到仓库即自动发布（见「发布」）

## 数据规模

<!-- STATS:BEGIN -->
| 项 | 数量 | 说明 |
|---|---|---|
| 赛事 | 33 个 | 2019–2026，含季前赛 / 常规赛 / 季后赛 / 总决赛 |
| 比赛（大场） | 2,888 场 | `assets/schedule_all.js`，全历史赛程与比分 |
| 对局（小局） | 11,126 局 | `assets/games/*.json`，33 个分片，按需加载 |
| 逐帧回放 | 211 局（62 场） | `assets/replay/*.json`，有分钟级快照的局；**精选对局与分时命中率只在这 211 局里算** |
| 搜索索引 | 3,589 条 | 战队 / 选手 / 英雄 / 全部比赛，首次输入时懒加载 |

> 覆盖边界要讲清楚：赛程比分是全历史的，但**逐分钟胜率只覆盖 211 局**。
> 所以「精选对局」「分时点命中率」的分母是 211，不是 11,126 —— 页面上写的样本量都指这个口径。
<!-- STATS:END -->

> 上面的数字由 `sync_readme_stats.py` 读 `assets/*.js` 索引自动生成（构建链最后一步调用），勿手工改。

## 页面（20 个 + 404）

| 页面 | 文件 | 能力 |
|---|---|---|
| 首页 | `index.html` | 赛程 / 焦点战 / 精选复盘入口 / 数据完整度徽标 |
| 赛程中心 | `schedule.html` | 按赛事与赛段浏览、赛季之最画廊、复盘入口 |
| 比赛详情 | `match.html` | 复盘工作台（统一时间轴）、BP、胜率曲线、分享深链 `?id=&g=&m=` |
| 对局详情 | `game.html` | 单局战报、BP 看板、分路经济、选手面板 |
| 精选对局 | `picks.html` | 4 条可复核规则筛出的翻盘 / 拉锯 / 波动 / 资源战，卡片直达关键分钟 |
| 战队 / 战队详情 | `teams.html` `team.html` | 积分榜（Wilson CI）、风格雷达、英雄池、H2H、赛季走势 |
| 选手 / 选手详情 | `players.html` `player.html` | 位置榜、能力雷达、常用英雄、同位置对比 |
| 英雄 / 英雄详情 | `heroes.html` `hero.html` | 出场 × 胜率散点、出装铭文、克制关系 |
| 英雄组合 | `combos.html` | 双人 / 三人组合胜率与样本量 |
| BP 分析 | `bp.html` | 全维度 BP 交叉（战队 / 对手 / 赛段 / 阵营 / 局序） |
| 交手记录 | `h2h.html` | 两队历史交手与分位对位 |
| 预测与准确率 | `predict.html` | 直播预测逐局命中、分时点命中率（8′ / 12′ / 16′）、模型卡 |
| 赛段对比 | `stage.html` | 任选两个赛段对比（如 `?a=2025&b=2026`） |
| 数据查询 | `query.html` | 多维筛选与导出 |
| 对比工具 | `compare.html` | 战队 / 选手同屏对比 |
| 大场模拟 | `simulator.html` | 阵容假设 → 单局 p → BO 大场胜率（解析 · iid 假设） |
| 数据说明 | `about.html` | 口径、来源分级、已知局限 |
| 404 | `404.html` | 兜底页 |

## 构建脚本（12 个）

数据全部离线生成，页面只读 `assets/*.js`。

| 脚本 | 产物 | 说明 |
|---|---|---|
| `build_data.py` | `data.js` | 站点主数据（赛程 / 焦点战 / 榜单 / 覆盖率） |
| `build_history_data.py` | `schedule_all.js` 等 | 2019–2026 全历史回补聚合 |
| `build_game_details.py` | `games/*.json` `details.js` | 局级详情分片 + 全局索引 + 装备图标 |
| `build_replay_frames.py` | `replay/*.json` | 单局复盘时间轴（只覆盖有分钟级快照的局） |
| `build_picks.py` | `picks.js` | 精选对局索引（4 条规则，阈值取分位数） |
| `build_predict_data.py` | `predict.js` | 预测档案 + 分时点命中率 + 回测指标 |
| `build_team_data.py` | `team_data.js` | 战队详情页数据 |
| `build_player_details.py` | `players_detail.js` | 选手常用英雄 / 赛季趋势 / 最近比赛 |
| `build_bp_data.py` | `bp.js` | BP 全维度交叉明细 |
| `build_equip_data.py` | `equips.js` | 英雄出装与召唤师技能聚合 |
| `build_search_index.py` | `search.js` | 全站搜索索引（挂在 `build_game_details.py` 末尾自动刷新） |
| `sync_readme_stats.py` | 改写 `README.md` | 把「数据规模」统计与 `assets/*.js` 索引对齐，构建链最后一步调用 |

## 目录

```
*.html                 20 个页面 + 404（纯静态，无构建步骤）
assets/style.css       设计系统（配色 / 字体 / 动效）
assets/pages.css       页面级样式
assets/common.js       导航 / 页脚 / 搜索 / 深链工具
assets/data.js         站点主数据（各 build_*.py 产物同目录）
assets/games/          逐局详情分片，按需加载
assets/replay/         复盘时间轴数据包
build_*.py             数据生成脚本（读 ../02-KPL实时胜率预测系统）
.assetsignore          部署排除项（不发布 .git / .wrangler / 构建脚本）
DESIGN.md              设计规范
```

数据由本地赛事数据仓（采集 + 模型，`../02-KPL实时胜率预测系统`）生成后推送本仓库。数据仅用于学习研究，请勿再分发。

## 发布

```bat
publish.bat "更新说明"    # 提交并推送，托管平台自动重新部署
```
