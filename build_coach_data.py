# -*- coding: utf-8 -*-
"""教练任期与 BP 指纹数据。

输入：
  ../02-KPL实时胜率预测系统/data/meta/coach_tenures.csv
  ../02-KPL实时胜率预测系统/data/meta/coach_tenure_exclusions.csv
  ../02-KPL实时胜率预测系统/data/history/**/matches/*.json
  assets/team_bp/index.js + shard_*.js

输出：
  assets/coach_data.js   KPL_COACH_DATA

口径：
  - 任期来自 Liquipedia 赛季名单（社区整理，非官方任免公告），并按公告日期拆分中途换帅；
  - 大场 / 小局胜率来自站内逐局赛果，按任期日期过滤；
  - BP 指纹只使用完整 20 手 BP 局，按任期日期过滤；
  - 相似度用「选用分布 + 禁用分布」的余弦相似度合成，只作风格描述；
  - 不把多个角色当作独立胜利累加，不做换帅因果判断。

运行：python build_coach_data.py
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
META = PROJ / "data" / "meta"
BP_DIR = SITE / "assets" / "team_bp"
OUT = SITE / "assets" / "coach_data.js"
CN = timezone(timedelta(hours=8))
SIM_MIN_BP = 20


def load_js(path: Path, var: str) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"window\." + re.escape(var) + r"\s*=\s*(\{.*\})\s*;?\s*$", text, re.S)
    if not m:
        raise SystemExit(f"{path.name} 结构无法解析")
    return json.loads(m.group(1))


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_leagues() -> dict:
    out = {}
    for row in json.loads((HIST / "leagues.json").read_text(encoding="utf-8")):
        lid = str(row.get("league_id"))
        out[lid] = {
            "id": lid,
            "name": str(row.get("league_name") or lid),
            "start": str(row.get("start_time") or "")[:10],
            "end": str(row.get("end_time") or "")[:10],
        }
    return out


def match_rows() -> list[dict]:
    """解析站内比赛为大场 / 小局记录，小局按每局自己的 camp 队名结算。"""
    rows = []
    files = sorted(HIST.glob("*/matches/*.json"))
    for idx, f in enumerate(files, 1):
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        m = obj.get("match") or {}
        lid = str(m.get("league_id") or f.parent.parent.name)
        date = str(m.get("start_time") or "")[:10]
        t1 = str((m.get("camp1") or {}).get("team_name") or "").strip()
        t2 = str((m.get("camp2") or {}).get("team_name") or "").strip()
        if not t1 or not t2:
            continue
        try:
            wc = int(m.get("win_camp") or 0)
        except (TypeError, ValueError):
            wc = 0
        games = []
        for b in obj.get("battles") or []:
            bt1 = str((b.get("camp1") or {}).get("team_name") or "").strip()
            bt2 = str((b.get("camp2") or {}).get("team_name") or "").strip()
            try:
                bw = int(b.get("win_camp") or 0)
            except (TypeError, ValueError):
                bw = 0
            if bt1 and bt2 and bw in (1, 2):
                games.append({"t1": bt1, "t2": bt2, "win": bw})
        rows.append({"lid": lid, "date": date, "t1": t1, "t2": t2, "win": wc, "games": games})
        if idx % 600 == 0:
            print(f"  matches {idx}/{len(files)}", flush=True)
    return rows


def in_range(date: str, start: str, end: str) -> bool:
    if not date:
        return True
    if start and date < start:
        return False
    if end and date > end:
        return False
    return True


def series_stats(matches: list[dict], lid: str, team: str, start: str, end: str) -> dict:
    series = series_wins = games = game_wins = 0
    for m in matches:
        if m["lid"] != lid or team not in (m["t1"], m["t2"]) or not in_range(m["date"], start, end):
            continue
        camp = 1 if team == m["t1"] else 2
        if m["win"] in (1, 2):
            series += 1
            series_wins += 1 if m["win"] == camp else 0
        for g in m["games"]:
            if team not in (g["t1"], g["t2"]):
                continue
            gcamp = 1 if team == g["t1"] else 2
            games += 1
            game_wins += 1 if g["win"] == gcamp else 0
    return {"series": series, "seriesWins": series_wins, "games": games, "gameWins": game_wins}


def bp_stats(ev: list[list], base: dict, H: int) -> dict:
    picks = bans = opp_bans = opp_picks = 0
    hero = [[0, 0, 0, 0, 0] for _ in range(H)]
    combo = Counter()
    combo_wins = Counter()
    games = len(ev)
    wins = 0
    for r in ev:
        # date, match, league, stage, opponent, side, win, picks, bans, oppPicks, oppBans
        win = 1 if r[6] == 1 else 0
        wins += win
        pk, bn, op, ob = r[7] or [], r[8] or [], r[9] or [], r[10] or []
        picks += len(pk)
        bans += len(bn)
        opp_picks += len(op)
        opp_bans += len(ob)
        for i in pk:
            hero[i][0] += 1
            hero[i][1] += win
        for i in bn:
            hero[i][2] += 1
        for i in op:
            hero[i][3] += 1
        for i in ob:
            hero[i][4] += 1
        for a, b in [(x, y) for x in sorted(pk) for y in sorted(pk) if x < y]:
            combo[(a, b)] += 1
            if win:
                combo_wins[(a, b)] += 1

    def arr(key_idx: int) -> list[int]:
        return (base.get(key_idx) or [0] * H) if isinstance(base.get(key_idx), list) else [0] * H

    base_pick = arr("pick")
    base_pickwins = arr("pickWins")
    base_total_pick = base.get("picks") or 0
    top_picks = []
    for i, row in sorted(enumerate(hero), key=lambda x: (-x[1][0], -sum(x[1][1:]), x[0]))[:10]:
        p, pw, b, ob, op = row
        if p <= 0:
            continue
        rate = p / picks * 100 if picks else None
        base_rate = base_pick[i] / base_total_pick * 100 if base_total_pick else None
        top_picks.append({
            "i": i, "p": p, "pw": pw,
            "win": round(pw / p * 100, 1) if p else None,
            "rate": round(rate, 1) if rate is not None else None,
            "baseRate": round(base_rate, 1) if base_rate is not None else None,
            "lift": round(rate / base_rate, 2) if rate and base_rate else None,
            "baseWin": round(base_pickwins[i] / base_pick[i] * 100, 1) if base_pick[i] else None,
        })
    top_bans = [
        {"i": i, "n": row[2], "rate": round(row[2] / bans * 100, 1) if bans else None}
        for i, row in sorted(enumerate(hero), key=lambda x: (-x[1][2], -x[1][3], x[0]))[:10]
        if row[2] > 0
    ]
    top_against = [
        {"i": i, "n": row[3], "rate": round(row[3] / opp_bans * 100, 1) if opp_bans else None}
        for i, row in sorted(enumerate(hero), key=lambda x: (-x[1][3], -x[1][2], x[0]))[:10]
        if row[3] > 0
    ]
    pick_counts = {i: row[0] for i, row in enumerate(hero)}
    combos = []
    for (a, b), n in combo.most_common(8):
        pa, pb = pick_counts.get(a, 0), pick_counts.get(b, 0)
        rate = n / games * 100 if games else None
        exp = (pa / games) * (pb / games) * 100 if games and pa and pb else None
        combos.append({
            "a": a, "b": b, "n": n,
            "win": round(combo_wins[(a, b)] / n * 100, 1) if n else None,
            "rate": round(rate, 1) if rate is not None else None,
            "lift": round(rate / exp, 2) if rate is not None and exp else None,
        })
    used = [row[0] for row in hero if row[0] > 0]
    return {
        "games": games,
        "wins": wins,
        "wr": round(wins / games * 100, 1) if games else None,
        "picks": picks,
        "bans": bans,
        "oppBans": opp_bans,
        "uniquePicks": len(used),
        "uniqueBans": sum(1 for row in hero if row[2] > 0),
        "effectiveHeroes": round(1 / sum((p / picks) ** 2 for p in used), 1) if picks else None,
        "topShare": round(max(used) / picks * 100, 1) if used and picks else None,
        "topPick": max(used, key=lambda i: hero[i][0]) if used else None,
        "topBans": top_bans,
        "topAgainst": top_against,
        "topPicks": top_picks,
        "combos": combos,
    }


def cosine(a: list[int], b: list[int]) -> float | None:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if not na or not nb:
        return None
    return dot / (na * nb)


def main() -> None:
    leagues = load_leagues()
    tenures = read_csv(META / "coach_tenures.csv")
    exclusions = read_csv(META / "coach_tenure_exclusions.csv")
    bp_index = load_js(BP_DIR / "index.js", "KPL_TEAM_BP_INDEX")
    heroes = bp_index.get("heroes") or []
    H = len(heroes)
    bp_teams = {str(t.get("name")): t for t in bp_index.get("teams") or []}
    baselines = bp_index.get("baselines") or {}
    bp_shards = {}
    for f in sorted(BP_DIR.glob("shard_*.js")):
        bp_shards.update(load_js(f, "KPL_TEAM_BP_SHARD"))
    matches = match_rows()

    out_rows = []
    problems = []
    bp_game_keys = set()
    coach_vec = {}

    for row in tenures:
        lid = str(row.get("league_id") or "")
        team = str(row.get("team") or "")
        start = str(row.get("valid_from") or "")[:10]
        end = str(row.get("valid_to") or "")[:10]
        if lid not in leagues or team not in bp_teams:
            problems.append(f"{team}/{lid}: 缺少赛事或战队数据")
            continue
        if not start or not end or start > end:
            problems.append(f"{team}/{lid}: 任期日期异常 {start} → {end}")
            continue
        lg = leagues[lid]
        meta = bp_teams[team]
        shard = bp_shards.get(team) or {}
        ev_all = [r for r in (shard.get("evidence") or []) if str(r[2]) == lid and in_range(r[0], start, end)]
        if not ev_all:
            problems.append(f"{team}/{lid}: 任期内没有完整 BP 证据")
            continue
        base = baselines.get(lid) or baselines.get("all") or {}
        st = series_stats(matches, lid, team, start, end)
        bp = bp_stats(ev_all, base, H)
        coach = str(row.get("coach_name") or "")
        cid = str(row.get("coach_id") or coach.lower().replace(" ", ""))
        vec = coach_vec.setdefault(cid, {"pick": [0] * H, "ban": [0] * H, "bpGames": 0})
        for r in ev_all:
            for i in r[7] or []:
                vec["pick"][i] += 1
            for i in r[8] or []:
                vec["ban"][i] += 1
            all_hands = tuple(sorted((r[7] or []) + (r[8] or []) + (r[9] or []) + (r[10] or [])))
            bp_game_keys.add((r[1], r[0], all_hands))
        vec["bpGames"] += bp["games"]
        ev = sorted(
            [[r[0], r[1], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10]] for r in ev_all],
            key=lambda r: (r[0], r[1]), reverse=True,
        )
        out_rows.append({
            "id": f"{lid}|{team}|{cid}|{start}",
            "coachId": cid,
            "coach": coach,
            "team": team,
            "teamIcon": meta.get("icon") or shard.get("icon") or "",
            "league": lid,
            "leagueName": lg["name"],
            "seasonName": row.get("season_name") or lg["name"],
            "role": row.get("role") or "head_coach",
            "validFrom": start,
            "validTo": end,
            "sourceUrl": row.get("source_url") or "",
            "sourceType": row.get("source_type") or "",
            "confidence": row.get("confidence") or "medium",
            "verifiedAt": row.get("verified_at") or "",
            "note": row.get("note") or "",
            "series": {
                "games": st["series"], "wins": st["seriesWins"],
                "wr": round(st["seriesWins"] / st["series"] * 100, 1) if st["series"] else None,
            },
            "games": {
                "games": st["games"], "wins": st["gameWins"],
                "wr": round(st["gameWins"] / st["games"] * 100, 1) if st["games"] else None,
            },
            "bp": bp,
            "evidence": ev[:30],
        })
        print(f"  {team} {lg['name']} · {coach} {start}→{end} | series {st['series']} | BP {bp['games']}", flush=True)

    coaches = {}
    for r in out_rows:
        c = coaches.setdefault(r["coachId"], {
            "id": r["coachId"], "name": r["coach"], "teams": [], "tenures": [],
            "series": 0, "seriesWins": 0, "games": 0, "gameWins": 0, "bpGames": 0, "bpWins": 0,
        })
        c["teams"].append(r["team"])
        c["tenures"].append(r["id"])
        c["series"] += r["series"]["games"]
        c["seriesWins"] += r["series"]["wins"]
        c["games"] += r["games"]["games"]
        c["gameWins"] += r["games"]["wins"]
        c["bpGames"] += r["bp"]["games"]
        c["bpWins"] += r["bp"]["wins"]
    for c in coaches.values():
        c["teams"] = sorted(set(c["teams"]))
        c["seriesWr"] = round(c["seriesWins"] / c["series"] * 100, 1) if c["series"] else None
        c["gameWr"] = round(c["gameWins"] / c["games"] * 100, 1) if c["games"] else None
        c["bpWr"] = round(c["bpWins"] / c["bpGames"] * 100, 1) if c["bpGames"] else None
        vec = coach_vec.get(c["id"]) or {"pick": [0] * H, "ban": [0] * H}
        c["pickVec"] = vec["pick"]
        c["banVec"] = vec["ban"]

    # 相似教练：选用分布 + 禁用分布的余弦相似度，合成后输出 top 6。
    ids = [cid for cid, c in coaches.items() if c["bpGames"] >= SIM_MIN_BP]
    for cid in ids:
        c = coaches[cid]
        sims = []
        for oid in ids:
            if oid == cid:
                continue
            o = coaches[oid]
            ps = cosine(c["pickVec"], o["pickVec"])
            bs = cosine(c["banVec"], o["banVec"])
            if ps is None or bs is None:
                continue
            sims.append({
                "id": oid, "name": o["name"], "teams": o["teams"], "bpGames": o["bpGames"],
                "series": o["series"], "seriesWr": o["seriesWr"],
                "pickSim": round(ps * 100, 1), "banSim": round(bs * 100, 1),
                "similarity": round((0.6 * ps + 0.4 * bs) * 100, 1),
            })
        c["similar"] = sorted(sims, key=lambda x: (-x["similarity"], -x["bpGames"]))[:6]

    coach_list = sorted(coaches.values(), key=lambda c: (-c["bpGames"], -c["series"], c["name"]))
    unique_team_seasons = len({(r["team"], r["league"]) for r in out_rows})
    data = {
        "generatedAt": datetime.now(CN).strftime("%Y-%m-%d %H:%M"),
        "sourceMode": "Liquipedia 赛季名单（社区整理），部分任期按公告日期拆分",
        "coverage": {
            "seasons": len({r["league"] for r in out_rows}),
            "teamSeasons": unique_team_seasons,
            "tenures": len(out_rows),
            "excludedTeamSeasons": len(exclusions),
            "coaches": len(coaches),
            "bpGames": len(bp_game_keys),
            "bpSamples": sum(r["bp"]["games"] for r in out_rows),
            "series": sum(r["series"]["games"] for r in out_rows),
            "start": min((r["validFrom"] for r in out_rows if r["validFrom"]), default=""),
            "end": max((r["validTo"] for r in out_rows if r["validTo"]), default=""),
        },
        "leagues": [{"id": lid, "name": lg["name"], "year": int(lid[:4]) if lid[:4].isdigit() else 0}
                    for lid, lg in sorted(leagues.items()) if any(r["league"] == lid for r in out_rows)],
        "heroes": heroes,
        "coaches": coach_list,
        "tenures": out_rows,
        "exclusions": [
            {"team": r.get("team"), "league": r.get("league_id"), "seasonName": r.get("season_name"),
             "coach": r.get("coach_name"), "reason": r.get("exclude_reason"), "sourceUrl": r.get("source_url")}
            for r in exclusions
        ],
        "problems": problems,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("window.KPL_COACH_DATA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"coaches {len(coach_list)} | tenures {len(out_rows)} | unique team-seasons {unique_team_seasons} | excluded {len(exclusions)} | problems {len(problems)}", flush=True)
    print(f"coverage {data['coverage']}", flush=True)
    print(f"size {OUT.stat().st_size/1024:.1f} KB | saved {OUT}", flush=True)
    if problems:
        for p in problems[:10]:
            print("WARN", p, flush=True)


if __name__ == "__main__":
    main()
