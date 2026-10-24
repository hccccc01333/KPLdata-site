# -*- coding: utf-8 -*-
"""把 README 的「数据规模」统计与已生成的 assets/*.js 索引对齐。

为什么需要它：README 里的场次 / 局数 / 回放样本是手工写的，一有新数据就过期
（2026-10-18 就出现过 README 写 59 场 / 202 局、实际索引已 61 场 / 209 局）。
本脚本只读构建产物、重写 README 里带标记的区块，数字不再手工维护。

数据源（全部是 build_*.py 的产物，不读原始数据）：
  assets/schedule_all.js   全历史赛程（大场）
  assets/seasons.js        赛季 / 赛事目录
  assets/games/index.js    逐局详情索引（小局）
  assets/replay/index.js   逐帧回放索引（场 / 局）
  assets/search.js         全站搜索索引

README 中自动维护的区域用 `<!-- STATS:BEGIN -->` / `<!-- STATS:END -->` 包裹，
本脚本只重写该区域，其余文本不动。标记缺失时直接报错退出（不猜）。

运行：python sync_readme_stats.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
ASSETS = SITE / "assets"
README = SITE / "README.md"

BEGIN = "<!-- STATS:BEGIN -->"
END = "<!-- STATS:END -->"


def load_js(path: Path):
    """读 `NAME = <json>;` 形式的资产文件并解析出 JSON。"""
    text = path.read_text(encoding="utf-8")
    return json.loads(text[text.index("=") + 1:].strip().rstrip(";").strip())


def main() -> None:
    schedule = load_js(ASSETS / "schedule_all.js")
    seasons = load_js(ASSETS / "seasons.js")
    search = load_js(ASSETS / "search.js")
    games_index = load_js(ASSETS / "games" / "index.js")
    replay_index = load_js(ASSETS / "replay" / "index.js")

    leagues = len(seasons.get("leagues") or [])
    matches = len(schedule)
    battles = sum(len(v.get("b") or []) for v in games_index.values())
    shards = len(list((ASSETS / "games").glob("*.json")))
    replay_matches = len(replay_index)
    replay_battles = sum(len(v.get("b") or []) for v in replay_index.values())
    search_n = len(search)

    block = "\n".join([
        BEGIN,
        "| 项 | 数量 | 说明 |",
        "|---|---|---|",
        f"| 赛事 | {leagues} 个 | 2019–2026，含季前赛 / 常规赛 / 季后赛 / 总决赛 |",
        f"| 比赛（大场） | {matches:,} 场 | `assets/schedule_all.js`，全历史赛程与比分 |",
        f"| 对局（小局） | {battles:,} 局 | `assets/games/*.json`，{shards} 个分片，按需加载 |",
        f"| 逐帧回放 | {replay_battles} 局（{replay_matches} 场） | `assets/replay/*.json`，"
        f"有分钟级快照的局；**精选对局与分时命中率只在这 {replay_battles} 局里算** |",
        f"| 搜索索引 | {search_n:,} 条 | 战队 / 选手 / 英雄 / 全部比赛，首次输入时懒加载 |",
        "",
        f"> 覆盖边界要讲清楚：赛程比分是全历史的，但**逐分钟胜率只覆盖 {replay_battles} 局**。",
        f"> 所以「精选对局」「分时点命中率」的分母是 {replay_battles}，不是 {battles:,} —— 页面上写的样本量都指这个口径。",
        END,
    ])

    text = README.read_text(encoding="utf-8")
    start = text.find(BEGIN)
    end = text.find(END)
    if start == -1 or end == -1:
        raise SystemExit(f"README 缺少 {BEGIN} / {END} 标记，无法自动同步")
    end += len(END)
    README.write_text(text[:start] + block + text[end:], encoding="utf-8")

    # 站点 UI 的“全历史总量”单一来源：与上面的 README 数字同一次构建写入，
    # 页面不再各自从 schedule/seasons/games 里挑一个口径。
    totals = {
        "leagues": leagues,
        "matches": matches,
        "battles": battles,
        "replayMatches": replay_matches,
        "replayBattles": replay_battles,
        "search": search_n,
    }
    (ASSETS / "site_totals.js").write_text(
        "window.KPL_TOTALS = " + json.dumps(totals, ensure_ascii=False) + ";\n",
        encoding="utf-8")

    print(f"README 数据规模已同步：赛事 {leagues} · 大场 {matches} · 小局 {battles} · "
          f"回放 {replay_matches} 场/{replay_battles} 局 · 搜索 {search_n}")


if __name__ == "__main__":
    main()
