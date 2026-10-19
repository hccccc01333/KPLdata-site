# -*- coding: utf-8 -*-
"""聚合选手详情：常用英雄 / 赛季趋势 / 最近比赛。

输出：assets/players_detail.js —— KPL_PLAYERS = {选手名: {...}}
运行：python build_player_details.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
MIN_GAMES = 15
MAX_PLAYERS = 500


def jload(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def num_or_none(v):
    """缺失/不可解析 → None（缺失 ≠ 0）；真实 0 原样返回 0.0。"""
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float("inf"), float("-inf")):
        return None
    return x


def main() -> None:
    acc: dict[str, dict] = {}

    def get(name: str) -> dict:
        if name not in acc:
            acc[name] = {
                "games": 0, "wins": 0, "k": 0, "d": 0, "a": 0, "mvp": 0,
                "part_sum": 0.0, "part_n": 0, "gold": 0,
                "dmg_sum": 0.0, "dmg_n": 0,
                "icon": "", "team": "", "teamIcon": "", "pos_sum": defaultdict(int),
                "heroes": defaultdict(lambda: [0, 0, 0, 0, 0]),
                "years": defaultdict(lambda: [0, 0, 0, 0, 0]),
                "recent": [],
            }
        return acc[name]

    n = 0
    for lg_dir in sorted(HIST.iterdir()):
        mdir = lg_dir / "matches"
        if not mdir.is_dir():
            continue
        for f in sorted(mdir.glob("*.json")):
            obj = jload(f)
            if not obj:
                continue
            match = obj.get("match") or {}
            date = str(match.get("start_time") or "")[:10]
            year = int(date[:4]) if date[:4].isdigit() else 0
            mid = str(match.get("match_id") or "")
            for det in obj.get("battles") or []:
                if not isinstance(det, dict) or det.get("win_camp") not in (1, 2):
                    continue
                wc = det["win_camp"]
                bid = str(det.get("battle_id") or "")
                n += 1
                for p in det.get("battle_player_list") or []:
                    if not isinstance(p, dict):
                        continue
                    name = str(p.get("player_name") or p.get("actual_player_name") or "").strip()
                    if not name:
                        continue
                    camp = int(p.get("camp") or 0)
                    won = 1 if camp == wc else 0
                    k = int(p.get("kill_num") or 0)
                    d = int(p.get("death_num") or 0)
                    a = int(p.get("assist_num") or 0)
                    row = get(name)
                    row["games"] += 1
                    row["wins"] += won
                    row["k"] += k
                    row["d"] += d
                    row["a"] += a
                    row["mvp"] += 1 if str(p.get("is_mvp")) in ("1", "True", "true") else 0
                    pv = num_or_none(p.get("participation_rate"))
                    if pv is not None:
                        row["part_sum"] += pv
                        row["part_n"] += 1
                    # 输出占比：接口给的是 0~1 小数，统一按百分数口径存；缺失的局不进分母
                    dv = num_or_none(p.get("hurt_total_rate"))
                    if dv is not None:
                        row["dmg_sum"] += dv
                        row["dmg_n"] += 1
                    row["gold"] += int(float(p.get("gold") or 0))
                    if p.get("player_icon"):
                        row["icon"] = str(p["player_icon"])
                    if p.get("team_name"):
                        row["team"] = str(p["team_name"])
                    if p.get("team_icon"):
                        row["teamIcon"] = str(p["team_icon"])
                    pos = str(p.get("position_desc") or "").strip()
                    if pos:
                        row["pos_sum"][pos] += 1
                    hn = str(p.get("hero_name") or "").strip()
                    if hn:
                        h = row["heroes"][hn]
                        h[0] += 1
                        h[1] += won
                        h[2] += k
                        h[3] += d
                        h[4] += a
                    if year:
                        y = row["years"][year]
                        y[0] += 1
                        y[1] += won
                        y[2] += k
                        y[3] += d
                        y[4] += a
                    # 最近比赛（同队/对手/英雄）
                    opp = ""
                    oicon = ""
                    for oc in (1, 2):
                        if oc == camp:
                            continue
                        od = det.get(f"camp{oc}") or {}
                        opp = str(od.get("team_name") or "")
                        oicon = str(od.get("team_icon") or "")
                    row["recent"].append([date, mid, bid, str(p.get("team_name") or ""), opp,
                                          hn, won, k, d, a])
    print(f"scanned {n} games, {len(acc)} players", flush=True)

    # 组装
    rows = {k: v for k, v in acc.items() if v["games"] >= MIN_GAMES}
    ordered = sorted(rows.items(), key=lambda kv: -kv[1]["games"])[:MAX_PLAYERS]
    out = {}
    for name, row in ordered:
        g = row["games"]
        d = max(1, row["d"])
        heroes = sorted(row["heroes"].items(), key=lambda kv: -kv[1][0])[:14]
        years = sorted(row["years"].items())
        recent = sorted(row["recent"], key=lambda r: (r[0], r[2]), reverse=True)[:10]
        pos = max(row["pos_sum"].items(), key=lambda kv: kv[1])[0] if row["pos_sum"] else ""
        out[name] = {
            "games": g, "wins": row["wins"],
            "wr": round(row["wins"] / g, 3),
            "kda": round((row["k"] + row["a"]) / d, 2),
            "mvp": row["mvp"],
            "part": round(row["part_sum"] / row["part_n"], 1) if row["part_n"] else None,
            "partN": row["part_n"],
            "dmg": round(row["dmg_sum"] / row["dmg_n"] * 100, 1) if row["dmg_n"] else None,
            "dmgN": row["dmg_n"],
            "gold": round(row["gold"] / g),
            "pos": pos, "team": row["team"], "teamIcon": row["teamIcon"], "icon": row["icon"],
            "heroes": [[h, v[0], round(v[1] / v[0], 3) if v[0] else 0,
                        round((v[2] + v[4]) / max(1, v[3]), 2)] for h, v in heroes],
            "poolN": len(row["heroes"]),
            "years": [[y, v[0], round(v[1] / v[0], 3) if v[0] else 0,
                       round((v[2] + v[4]) / max(1, v[3]), 2)] for y, v in years],
            "recent": recent,
        }
    path = SITE / "assets" / "players_detail.js"
    path.write_text("KPL_PLAYERS = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n",
                    encoding="utf-8")
    print(f"players_detail.js: {path.stat().st_size/1024:.0f} KB | players: {len(out)}")


if __name__ == "__main__":
    main()
