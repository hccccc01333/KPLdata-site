# -*- coding: utf-8 -*-
"""深挖数据：系列赛（BO）规律 / 战队 Elo 强度 / 选手关键局表现 → assets/deep.js

数据源：../02-KPL实时胜率预测系统/data/history/<league>/matches/<match>.json

口径（P0 修正）：KPL 的 camp1/camp2 是**每一小局**的蓝/红方，同一战队可以换边。
因此所有胜负都必须先落回本局 camp 队名，再按战队身份累计；不能拿一个阵营序号
贯穿整个系列赛。统一实现见 kpl_series.py。

输出：
  KPL_DEEP = {
    generatedAt, matches, battles, coverage,
    series: { byBo:[...], reverseSweeps:[...], decBoard:[...] },
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

from kpl_series import SeriesResult, battle_winner_team, summarize_match, team_name_of

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


def main() -> None:
    files = sorted(HIST.glob("*/matches/*.json"))
    teams: dict[str, dict] = {}
    players: dict[str, dict] = {}
    elo: dict[str, float] = defaultdict(lambda: 1500.0)
    matches = []          # 供 Elo / 表单按时间排序
    battles_n = 0
    diag = Counter()

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

    def note_icon(team: str, result: SeriesResult) -> None:
        rec = T(team)
        if rec["icon"]:
            return
        for b in result.battles:
            for pl in b.get("battle_player_list") or []:
                if not isinstance(pl, dict):
                    continue
                if str(pl.get("team_name") or "") != team:
                    continue
                if pl.get("team_icon"):
                    rec["icon"] = str(pl["team_icon"])
                    return

    for f in files:
        diag["files"] += 1
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            diag["bad_json"] += 1
            continue

        res = summarize_match(o, fallback_id=f.stem)
        if res is None:
            diag["no_battles"] += 1
            continue
        T(res.team1); T(res.team2)
        note_icon(res.team1, res)
        note_icon(res.team2, res)
        if res.side_switches:
            diag["side_switch_series"] += 1
        if res.official_conflict:
            diag["official_conflict"] += 1
        for err in res.errors:
            diag[f"error_{err}"] += 1

        # 局级战绩与选手逐局胜负：即使大场缺官方结果，只要有逐局胜方就照实计入。
        battles_n += len(res.battles)
        for battle_winner in res.battle_winners:
            if battle_winner not in (res.team1, res.team2):
                continue
            other = res.team2 if battle_winner == res.team1 else res.team1
            wt, lt = T(battle_winner), T(other)
            wt["gameN"] += 1; wt["gameW"] += 1
            lt["gameN"] += 1

        # 选手累计：won 按「该选手所属战队 == 本局胜方战队」计算，
        # 而不是「该选手 camp == 系列赛胜方 camp」。
        dec_battle = res.decisive_battle
        for bt in res.battles:
            is_dec = bt is dec_battle
            bw = battle_winner_team(bt)
            if not bw:
                continue
            for p in bt.get("battle_player_list") or []:
                if not isinstance(p, dict):
                    continue
                name = str(p.get("player_name") or p.get("actual_player_name") or "").strip()
                if not name:
                    continue
                camp = int(num(p.get("camp"), 0))
                if camp not in (1, 2):
                    continue
                team = str(p.get("team_name") or "").strip() or team_name_of(bt, camp)
                if team not in (res.team1, res.team2):
                    continue
                won = 1 if team == bw else 0
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
                if team:
                    rec["team"] = team
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

        if not res.resolved:
            diag["unresolved"] += 1
            continue

        diag["resolved"] += 1
        diag[f"source_{res.source}"] += 1

        winner, loser = res.winner, res.loser
        a, b2 = T(winner), T(loser)
        a["seriesN"] += 1; a["seriesW"] += 1
        b2["seriesN"] += 1

        a["bo"][res.bo]["n"] += 1; a["bo"][res.bo]["w"] += 1
        b2["bo"][res.bo]["n"] += 1

        # 首局转化 / 先丢一局翻盘
        if res.first_game:
            first = res.first_game
            other = res.team2 if first == res.team1 else res.team1
            ft = T(first)
            ft["fgN"] += 1
            if first == winner:
                ft["fgW"] += 1
            fb = T(other)
            fb["cbN"] += 1
            if other == winner:
                fb["cbW"] += 1

        # 让二追三/四：先统计 0:2 落后的机会，再统计兑现次数。
        # 前两局由同一队拿下时，落后的是另一队（不是 winners[0]）。
        if (res.battle_complete and res.bo >= 5 and len(res.battle_winners) >= 3
                and res.battle_winners[0] == res.battle_winners[1]):
            front = res.battle_winners[0]
            behind = res.team2 if front == res.team1 else res.team1
            bt = T(behind)
            bt["rsN"] += 1
            if behind == winner:
                bt["rsW"] += 1

        # 决胜局
        if res.decisive:
            T(winner)["decN"] += 1; T(winner)["decW"] += 1
            T(loser)["decN"] += 1

        w_games, l_games = res.score if winner == res.team1 else (res.score[1], res.score[0])
        matches.append({
            "mid": res.match_id, "lid": res.league_id, "date": res.date, "bo": res.bo,
            "stage": res.stage, "t1": res.team1, "t2": res.team2,
            "winner": winner, "loser": loser,
            "wins": w_games, "losses": l_games,
            "complete": res.battle_complete, "source": res.source,
            "wentDistance": res.decisive, "first": res.first_game,
            "revSweep": res.reverse_sweep,
        })

    # ---------------- Elo（按时间顺序，系列赛级 + 局分差加成） ----------------
    matches.sort(key=lambda x: (x["date"], x["mid"]))
    for x in matches:
        T(x["winner"])["form"].append("W")
        T(x["loser"])["form"].append("L")
        ra, rb = elo[x["t1"]], elo[x["t2"]]
        ea = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        sa = 1.0 if x["winner"] == x["t1"] else 0.0
        margin = abs(x["wins"] - x["losses"])
        if margin <= 0:
            margin = 1
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
            "bo5": dict(t["bo"].get(5, {"n": 0, "w": 0})),
            "bo7": dict(t["bo"].get(7, {"n": 0, "w": 0})),
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
        first_rows = [x for x in rows if x["first"]]
        fw = sum(1 for x in first_rows if x["first"] == x["winner"])
        first_n = len(first_rows)
        first_conv = fw / first_n if first_n else 0.0
        complete_rows = [x for x in rows if x.get("complete")]
        dist = Counter(x["wins"] + x["losses"] for x in complete_rows)
        by_bo.append({
            "bo": bo, "n": n,
            "firstConv": round(first_conv, 3), "comeback": round(1.0 - first_conv, 3),
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

    coverage = {
        "files": diag["files"],
        "resolvedSeries": diag["resolved"],
        "officialFallback": diag["source_official"],
        "unresolved": diag["unresolved"],
        "sideSwitchSeries": diag["side_switch_series"],
        "officialConflicts": diag["official_conflict"],
        "battles": battles_n,
    }
    data = {
        "generatedAt": datetime.now(CN).strftime("%Y-%m-%d %H:%M"),
        "matches": len(matches), "battles": battles_n, "coverage": coverage,
        "series": {"byBo": by_bo, "reverseSweeps": rev[:40], "decBoard": dec_board},
        "teams": out_teams,
        "players": out_players,
    }
    path = SITE / "assets" / "deep.js"
    path.write_text("KPL_DEEP = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                    encoding="utf-8")
    print(f"deep.js: {path.stat().st_size/1024:.0f} KB | series {len(matches)} | teams {len(out_teams)} | players {len(out_players)}")
    print(f"  coverage: {coverage}")
    for row in by_bo:
        print(f"  BO{row['bo']}: n={row['n']} 首局转化={row['firstConv']*100:.1f}% 翻盘={row['comeback']*100:.1f}% "
              f"打到决胜局={row['distance']*100:.1f}%")


if __name__ == "__main__":
    main()
