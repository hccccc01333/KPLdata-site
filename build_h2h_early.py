# -*- coding: utf-8 -*-
"""把 2016–2018 外部补充集整理成交手记录页可用的「史料行」 → assets/h2h_early.js

数据源：../02-KPL实时胜率预测系统/data/external/history_2016_2018/matches.csv
口径与 records 页一致：只取 quality_flag == ok 的场次（576 场）；
no_games / score_mismatch 的 8 场不进入页面（与 build_records.py 的 excluded 列表一致）。

队名处理：
  - 只在「沿革明确」的旧名上映射到现在队名（AG超玩会→成都AG超玩会、QGhappy→重庆狼队…），
    避免把不同战队误并成一支。
  - 无明确沿革的旧队（AS仙阁 / MU / VgHow / sViper…）保留原名，作为独立史料队伍。

2016–2018 没有站点比赛详情页：行内带原始来源 url，h2h 列表按「史料 ↗」外链。

运行：python build_h2h_early.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
SRC = PROJ / "data" / "external" / "history_2016_2018" / "matches.csv"
OUT = SITE / "assets" / "h2h_early.js"

# 只映射有明确沿革的旧队名（与 scripts/build_legacy_game_dataset.py 的口径一致）
ALIASES = {
    "AG超玩会": "成都AG超玩会",
    "QGhappy": "重庆狼队",
    "重庆QGhappy": "重庆狼队",
    "X-QUEST": "广州TTG",
    "GK": "佛山DRG",
    "JC": "深圳DYG",
    "HERO电子竞技俱乐部": "南通Hero久竞",
    "Hero久竞俱乐部": "南通Hero久竞",
    "EDG.M电子竞技俱乐部": "上海EDG.M",
    "RNG.M电子竞技俱乐部": "上海RNG.M",
    "Rogue Warriors Esports Club": "济南RW侠",
    "Ts": "北京WB",
    "YTG": "KSG",
}


def norm(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip())


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"缺少 2016–2018 补充集：{SRC}")

    rows = []
    aliased = 0
    skipped = 0
    with SRC.open(encoding="utf-8-sig", newline="") as f:
        for m in csv.DictReader(f):
            if m.get("quality_flag") != "ok":
                skipped += 1
                continue
            try:
                year = int(m["year"])
                score1, score2 = int(m["score1"]), int(m["score2"])
                bo = int(float(m["bo"] or 0))
            except (TypeError, ValueError):
                skipped += 1
                continue
            t1, t2 = norm(m.get("team1")), norm(m.get("team2"))
            c1, c2 = ALIASES.get(t1, t1), ALIASES.get(t2, t2)
            aliased += int(c1 != t1) + int(c2 != t2)
            start = str(m.get("start_time") or "")
            rows.append({
                "matchId": str(m.get("match_id") or ""),
                "leagueName": str(m.get("season") or ""),
                "year": year,
                "stage": str(m.get("stage") or ""),
                "date": str(m.get("date") or start[:10]),
                "time": start[11:16],
                "team1": c1,
                "team2": c2,
                "score1": score1, "score2": score2, "bo": bo,
                "done": True, "hasDetail": False,
                "url": str(m.get("url") or ""),
            })

    rows.sort(key=lambda r: (r["date"], r["time"], r["matchId"]))
    OUT.write_text(
        "KPL_H2H_EARLY = " + json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )

    by_year: dict[int, int] = {}
    for r in rows:
        by_year[r["year"]] = by_year.get(r["year"], 0) + 1
    names = sorted({r["team1"] for r in rows} | {r["team2"] for r in rows})
    print("h2h_early.js: {} 场 · {} KB · 队名映射 {} 次 · 跳过 {} 场".format(
        len(rows), OUT.stat().st_size // 1024, aliased, skipped))
    print("按年份: " + " / ".join(f"{y} {n}" for y, n in sorted(by_year.items())))
    print(f"队伍: {len(names)} 支")


if __name__ == "__main__":
    main()
