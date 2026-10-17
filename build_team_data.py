# -*- coding: utf-8 -*-
"""生成战队资料数据 assets/team_data.js（V4 阶段二 · 完整战队详情页）。

为什么单独建：站点现有的 `details.teams` 只覆盖当前赛季 Top 18 战队的英雄池，
而英雄/选手/比赛页会把「全部 83 支战队」都链到战队详情；没有这份数据，
历史战队点进来就没有阵容与常用英雄，等于半个空页。

数据源：../02-KPL实时胜率预测系统/data/history/<league>/matches/*.json
        （每局 battle_player_list 里有 team_name / player_name / hero_name / camp，
          win_camp 给胜负，因此可聚合"战队 × 英雄"与"战队 × 选手"）
输出：
  KPL_TEAM_DATA = {team: {h: [[hero, games, wins]...12], h26: [...当前赛季...],
                          p: [[player, games, wins, pos]...10]}}
用法：python build_team_data.py
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
OUT = SITE / "assets" / "team_data.js"
CURRENT_LEAGUES = {"20260004", "20260003", "20260002"}   # 当前赛季（年度总决赛 / 夏季赛 / 挑战者杯）
TOP_HEROES = 12
TOP_PLAYERS = 10
MIN_HERO_GAMES = 3


def main() -> None:
    t0 = time.time()
    hero_stats: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    hero_stats_cur: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    player_stats: dict[str, dict[str, dict]] = defaultdict(dict)
    n_battles = 0

    for lg_dir in sorted(p for p in HIST.iterdir() if p.is_dir()):
        lid = lg_dir.name
        mdir = lg_dir / "matches"
        if not mdir.is_dir():
            continue
        is_cur = lid in CURRENT_LEAGUES
        for f in mdir.glob("*.json"):
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for det in obj.get("battles") or []:
                if not isinstance(det, dict):
                    continue
                win_camp = det.get("win_camp")
                if win_camp not in (1, 2):
                    continue
                camps = {1: str((det.get("camp1") or {}).get("team_name") or ""),
                         2: str((det.get("camp2") or {}).get("team_name") or "")}
                if not camps[1] or not camps[2]:
                    continue
                n_battles += 1
                for p in det.get("battle_player_list") or []:
                    if not isinstance(p, dict):
                        continue
                    camp = int(p.get("camp") or 0)
                    team = str(p.get("team_name") or camps.get(camp) or "")
                    hero = str(p.get("hero_name") or "")
                    name = str(p.get("player_name") or p.get("actual_player_name") or "")
                    if not team or not hero:
                        continue
                    won = 1 if camp == win_camp else 0
                    h = hero_stats[team][hero]
                    h[0] += 1
                    h[1] += won
                    if is_cur:
                        c = hero_stats_cur[team][hero]
                        c[0] += 1
                        c[1] += won
                    if name:
                        pv = player_stats[team].get(name)
                        if pv is None:
                            pos = str(p.get("position_desc") or p.get("position") or "").strip()
                            pv = {"g": 0, "w": 0, "pos": pos}
                            player_stats[team][name] = pv
                        pv["g"] += 1
                        pv["w"] += won
                        if not pv.get("pos"):
                            pos = str(p.get("position_desc") or p.get("position") or "").strip()
                            if pos:
                                pv["pos"] = pos

    data = {}
    for team, heroes in hero_stats.items():
        rows = [[h, g, w] for h, (g, w) in heroes.items() if g >= MIN_HERO_GAMES]
        rows.sort(key=lambda r: (-r[1], -r[2]))
        cur = [[h, g, w] for h, (g, w) in (hero_stats_cur.get(team) or {}).items() if g >= 1]
        cur.sort(key=lambda r: (-r[1], -r[2]))
        pl = [[n, v["g"], v["w"], v.get("pos") or ""] for n, v in player_stats.get(team, {}).items()]
        pl.sort(key=lambda r: -r[1])
        data[team] = {"h": rows[:TOP_HEROES], "h26": cur[:TOP_HEROES], "p": pl[:TOP_PLAYERS]}

    OUT.write_text("KPL_TEAM_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    print(f"team_data.js: {len(data)} 支战队 · {n_battles} 局 · {OUT.stat().st_size / 1024:.0f} KB · {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
