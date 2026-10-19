# -*- coding: utf-8 -*-
"""深挖数据：系列赛（BO）规律 / 战队 Elo 强度 / 选手关键局表现 → assets/deep.js

数据源：../02-KPL实时胜率预测系统/data/history/<league>/matches/<match>.json
       （逐局数据；battle 级 camp 顺序才是权威口径）

输出：
  KPL_DEEP = {
    generatedAt, matches, battles,
    series: { byBo:[...], reverseSweeps:[...], longest:[...] },
    teams:  {队名: {elo, rank, ...系列赛画像}},
    players:{选手: {关键局/稳定性}}
  }

运行：python build_deep_data.py
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
CN = timezone(timedelta(hours=8))
MIN_PLAYER_GAMES = 40      # 进入关键局榜单的最低出场
MIN_DEC_GAMES = 8          # 关键局样本门槛
ELO_K = 22


def num(v, default=0.0):
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def team_of(battle: dict, camp: int) -> str:
    return str((battle.get(f"camp{camp}") or {}).get("team_name") or "")


def main() -> None:
    files = sorted(HIST.glob("*/matches/*.json"))
    teams: dict[str, dict] = {}
    players: dict[str, dict] = {}
    elo: dict[str, float] = defaultdict(lambda: 1500.0)
    matches = []          # 供 Elo / 表单按时间排序
    battles_n = 0

    def T(name: str) -> dict:
        if name not in teams:
            teams[name] = {
                "team": name, "icon": "", "seriesN": 0, "seriesW": 0,
                "gameN": 0, "gameW": 0, "fgN": 0, "fgW": 0,
                "decN": 0, "decW": 0, "cbN": 0, "cbW": 0, "rsN": 0, "rsW": 0,
                "bo": defaultdict(lambda: {"n": 0, "w": 0}),
                "form": [], "opps": [], "eloHist": [],
            }
        return teams[name]

    def P(name: str) -> dict:
        if name not in players:
            players[name] = {
                "name": name, "team": "", "pos": "", "icon": "",
                "g": 0, "w": 0, "k": 0, "d": 0, "a": 0, "dmg": 0.0, "dmgN": 0, "part": 0.0, "partN": 0,
                "decN": 0, "decW": 0, "decK": 0, "decD": 0, "decA": 0,
                "decDmg": 0.0, "decDmgN": 0, "kdaSamples": [], "dmgSamples": [],
                "decKdas": [], "decDmgs": [],
            }
        return players[name]

    for f in files:
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        m = o.get("match") or {}
        bs = [b for b in (o.get("battles") or []) if b.get("win_camp") in (1, 2)]
        if not bs:
            continue
        bs.sort(key=lambda b: int(b.get("battle_seq") or 0))
        t1, t2 = team_of(bs[0], 1), team_of(bs[0], 2)
        if not t1 or not t2:
            continue
        wins = Counter()
        for b in bs:
            wins[int(b["win_camp"])] += 1
        bo = int(m.get("bo") or 0) or (len(bs) * 2 - 1)
        need = (bo // 2) + 1
        tie = wins[1] == wins[2]
        complete = (not tie) and max(wins.values()) == need
        mw = int(m.get("win_camp") or 0)
        c1m = str((m.get("camp1") or {}).get("team_name") or "")
        c2m = str((m.get("camp2") or {}).get("team_name") or "")
        if complete:
            win_camp = 1 if wins[1] > wins[2] else 2
            winner, loser = (t1, t2) if win_camp == 1 else (t2, t1)
        elif mw in (1, 2) and c1m and c2m:
            # 逐局数据不完整（早年缺局/缺决胜局）：用官方大场胜负兜底，局分不参与统计
            win_camp = mw
            winner = c1m if mw == 1 else c2m
            loser = c2m if mw == 1 else c1m
            if winner not in (t1, t2):
                continue
        else:
            continue
        loser_camp = 2 if win_camp == 1 else 1
        g_w = wins[win_camp] if complete else 0
        g_l = wins[loser_camp] if complete else 0
        date = str(m.get("start_time") or "")
        mid = str(m.get("match_id") or f.stem)
        lid = str(m.get("league_id") or "")
        stage = str(m.get("match_stage_name") or "")

        a, b2 = T(winner), T(loser)
        a["seriesN"] += 1; a["seriesW"] += 1
        b2["seriesN"] += 1
        if not a["icon"]:
            for bt in bs:
                for pl in bt.get("battle_player_list") or []:
                    if str(pl.get("team_name") or "") == winner and pl.get("team_icon"):
                        a["icon"] = str(pl["team_icon"]); break
                if a["icon"]:
                    break
        if not b2["icon"]:
            for bt in bs:
                for pl in bt.get("battle_player_list") or []:
                    if str(pl.get("team_name") or "") == loser and pl.get("team_icon"):
                        b2["icon"] = str(pl["team_icon"]); break
                if b2["icon"]:
                    break
        a["gameN"] += g_w; a["gameW"] += g_w
        b2["gameN"] += g_l; b2["gameW"] += g_l
        a["bo"][bo]["n"] += 1; a["bo"][bo]["w"] += 1
        b2["bo"][bo]["n"] += 1
        a["form"].append("W"); b2["form"].append("L")

        first_camp = int(bs[0]["win_camp"])
        first_team = t1 if first_camp == 1 else t2
        ft = T(first_team)
        ft["fgN"] += 1
        if first_team == winner:
            ft["fgW"] += 1
        # 先丢一局的一方（翻盘统计）
        fb_team = t2 if first_camp == 1 else t1
        fb = T(fb_team)
        fb["cbN"] += 1
        if fb_team == winner:
            fb["cbW"] += 1
        # 让二追 N（BO5 及以上，且逐局完整）
        rs_sweep = False
        if complete and len(bs) >= 3 and bo >= 5:
            g1 = int(bs[0]["win_camp"]); g2 = int(bs[1]["win_camp"])
            if g1 == g2:
                behind_team = t2 if g1 == 1 else t1
                T(behind_team)["rsN"] += 1
                if behind_team == winner:
                    T(behind_team)["rsW"] += 1
                    rs_sweep = True
        # 决胜局
        went_distance = complete and bo >= 3 and g_w == need and g_l == need - 1
        if went_distance:
            T(winner)["decN"] += 1; T(winner)["decW"] += 1
            T(loser)["decN"] += 1

        # 选手累计
        for bi, bt in enumerate(bs):
            is_dec = went_distance and bi == len(bs) - 1
            for p in bt.get("battle_player_list") or []:
                name = str(p.get("player_name") or p.get("actual_player_name") or "").strip()
                if not name:
                    continue
                camp = int(p.get("camp") or 0)
                if camp not in (1, 2):
                    continue
                won = 1 if camp == win_camp else 0
                k = int(num(p.get("kill_num"))); d = int(num(p.get("death_num"))); asst = int(num(p.get("assist_num")))
                dmg = None
                dv = p.get("hurt_total_rate")
                if dv not in (None, ""):
                    try:
                        dmg = float(dv) * 100
                    except (TypeError, ValueError):
                        dmg = None
                part = p.get("participation_rate")
                try:
                    part = float(part)
                except (TypeError, ValueError):
                    part = None
                rec = P(name)
                rec["g"] += 1; rec["w"] += won
                rec["k"] += k; rec["d"] += d; rec["a"] += asst
                if p.get("team_name"):
                    rec["team"] = str(p["team_name"])
                if p.get("position_desc"):
                    rec["pos"] = str(p["position_desc"])
                if p.get("player_icon"):
                    rec["icon"] = str(p["player_icon"])
                kda = (k + asst) / max(1, d)
                rec["kdaSamples"].append(kda)
                if dmg is not None:
                    rec["dmg"] += dmg; rec["dmgN"] += 1
                    rec["dmgSamples"].append(dmg)
                if part is not None:
                    rec["part"] += part; rec["partN"] += 1
                if is_dec:
                    rec["decN"] += 1; rec["decW"] += won
                    rec["decK"] += k; rec["decD"] += d; rec["decA"] += asst
                    rec["decKdas"].append(kda)
                    if dmg is not None:
                        rec["decDmg"] += dmg; rec["decDmgN"] += 1
                        rec["decDmgs"].append(dmg)

        matches.append({
            "mid": mid, "lid": lid, "date": date, "bo": bo, "stage": stage,
            "t1": t1, "t2": t2, "winner": winner, "loser": loser,
            "wins": g_w, "losses": g_l, "complete": complete,
            "wentDistance": went_distance, "first": first_team, "revSweep": rs_sweep,
        })

    # ---------------- Elo（按时间顺序，系列赛级 + 局分差加成） ----------------
    matches.sort(key=lambda x: (x["date"], x["mid"]))
    for x in matches:
        ra, rb = elo[x["t1"]], elo[x["t2"]]
        ea = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        sa = 1.0 if x["winner"] == x["t1"] else 0.0
        margin = abs(x["wins"] - x["losses"]) if x.get("complete") else 1
        mov = min(2.0, 1.0 + 0.35 * max(0, margin - 1))
        k = ELO_K * (1.0 + (0.25 if x["bo"] >= 7 else 0.0)) * mov
        elo[x["t1"]] = ra + k * (sa - ea)
        elo[x["t2"]] = rb + k * ((1 - sa) - (1 - ea))
        T(x["t1"])["opps"].append(elo[x["t2"]])
        T(x["t2"])["opps"].append(elo[x["t1"]])

    ranked = sorted(teams.values(), key=lambda t: -elo[t["team"]])
    for i, t in enumerate(ranked, 1):
        t["rank"] = i
        t["elo"] = round(elo[t["team"]])

    # ---------------- 汇总输出 ----------------
    out_teams = {}
    for name, t in teams.items():
        form = "".join(t["form"][-10:])
        sos = sum(t["opps"][-60:]) / max(1, len(t["opps"][-60:]))
        out_teams[name] = {
            "team": name, "icon": t["icon"], "elo": t["elo"], "rank": t["rank"],
            "seriesN": t["seriesN"], "seriesW": t["seriesW"],
            "gameN": t["gameN"], "gameW": t["gameW"],
            "fgN": t["fgN"], "fgW": t["fgW"],
            "decN": t["decN"], "decW": t["decW"],
            "cbN": t["cbN"], "cbW": t["cbW"],
            "rsN": t["rsN"], "rsW": t["rsW"],
            "bo5": dict(t["bo"].get(5, {})), "bo7": dict(t["bo"].get(7, {})),
            "sos": round(sos), "form": form,
        }

    out_players = {}
    for name, p in players.items():
        g = p["g"]
        if g < MIN_PLAYER_GAMES:
            continue
        kda = (p["k"] + p["a"]) / max(1, p["d"])
        dmg = p["dmg"] / p["dmgN"] if p["dmgN"] else None
        part = p["part"] / p["partN"] if p["partN"] else None
        # 波动率（变异系数）：标准差 / 均值，越小越稳
        def cv(arr):
            if len(arr) < 5:
                return None
            mu = sum(arr) / len(arr)
            if abs(mu) < 1e-9:
                return None
            sd = math.sqrt(sum((x - mu) ** 2 for x in arr) / len(arr))
            return sd / abs(mu)
        dec_n = p["decN"]
        dec_kda = ((p["decK"] + p["decA"]) / max(1, p["decD"])) if dec_n else None
        dec_dmg = (p["decDmg"] / p["decDmgN"]) if p["decDmgN"] else None
        out_players[name] = {
            "name": name, "team": p["team"], "pos": p["pos"], "icon": p["icon"],
            "g": g, "w": p["w"], "kda": round(kda, 2), "dmg": round(dmg, 1) if dmg is not None else None,
            "part": round(part, 1) if part is not None else None,
            "cvKda": round(cv(p["kdaSamples"]) or 0, 3) if cv(p["kdaSamples"]) is not None else None,
            "cvDmg": round(cv(p["dmgSamples"]) or 0, 3) if cv(p["dmgSamples"]) is not None else None,
            "decN": dec_n, "decW": p["decW"],
            "decKda": round(dec_kda, 2) if dec_kda is not None else None,
            "decDmg": round(dec_dmg, 1) if dec_dmg is not None else None,
            "decDmgN": p["decDmgN"],
        }

    by_bo = []
    for bo in (1, 3, 5, 7, 9):
        rows = [x for x in matches if x["bo"] == bo]
        if not rows:
            continue
        n = len(rows)
        fw = sum(1 for x in rows if x["first"] == x["winner"])
        cb = n - fw
        complete_rows = [x for x in rows if x.get("complete")]
        dist = Counter(x["wins"] + x["losses"] for x in complete_rows)
        by_bo.append({
            "bo": bo, "n": n,
            "firstConv": round(fw / n, 3), "comeback": round(cb / n, 3),
            "distance": round(sum(1 for x in rows if x["wentDistance"]) / n, 3),
            "avgGames": round(sum(x["wins"] + x["losses"] for x in complete_rows) / len(complete_rows), 2) if complete_rows else 0,
            "dist": {str(k): v for k, v in sorted(dist.items())},
        })

    rev = [
        {"mid": x["mid"], "date": x["date"][:10], "t1": x["t1"], "t2": x["t2"],
         "winner": x["winner"], "score": f'{x["wins"]}:{x["losses"]}', "bo": x["bo"]}
        for x in matches if x["revSweep"]
    ]
    rev.sort(key=lambda r: r["date"], reverse=True)

    # 决胜局/翻盘榜单：只保留样本足够的队
    dec_board = sorted(
        [v for v in out_teams.values() if v["decN"] >= 10],
        key=lambda v: -(v["decW"] / max(1, v["decN"])),
    )

    data = {
        "generatedAt": datetime.now(CN).strftime("%Y-%m-%d %H:%M"),
        "matches": len(matches), "battles": battles_n,
        "series": {"byBo": by_bo, "reverseSweeps": rev[:40], "decBoard": dec_board},
        "teams": out_teams,
        "players": out_players,
    }
    path = SITE / "assets" / "deep.js"
    path.write_text("KPL_DEEP = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                    encoding="utf-8")
    print(f"deep.js: {path.stat().st_size/1024:.0f} KB | series {len(matches)} | teams {len(out_teams)} | players {len(out_players)}")
    for row in by_bo:
        print(f"  BO{row['bo']}: n={row['n']} 首局转化={row['firstConv']*100:.1f}% 翻盘={row['comeback']*100:.1f}% "
              f"打到决胜局={row['distance']*100:.1f}%")


if __name__ == "__main__":
    main()
