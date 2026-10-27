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
  - 仅纳入赛季内主教练唯一、来源可追溯的战队-赛季；
  - 任期按赛事起止日期，来源为 Liquipedia 赛季名单（社区整理，非官方任免公告）；
  - 大场 / 小局胜率来自站内逐局赛果；BP 指纹只使用完整 20 手 BP 局；
  - 中途换帅 / 角色不明确的队-赛季不进入 BP 归属，只在“未纳入”说明中统计；
  - 不把多个角色当作独立胜利累加，不做换帅因果判断。

运行：python build_coach_data.py
"""

from __future__ import annotations

import csv
import json
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


def series_rows() -> dict[tuple[str, str], dict]:
    """按 (赛事, 战队) 聚合站内大场 / 小局赛果。"""
    out = {}
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
        for team, opp, camp in ((t1, t2, 1), (t2, t1, 2)):
            st = out.setdefault((lid, team), {"series": 0, "seriesWins": 0, "games": 0, "gameWins": 0, "matches": []})
            if wc in (1, 2):
                st["series"] += 1
                st["seriesWins"] += 1 if wc == camp else 0
                st["matches"].append(m.get("match_id") or f.stem)
        # 小局可能换边：必须按每局自己的 camp1 / camp2 队名结算，不能沿用大场阵营。
        for b in obj.get("battles") or []:
            bt1 = str((b.get("camp1") or {}).get("team_name") or "").strip()
            bt2 = str((b.get("camp2") or {}).get("team_name") or "").strip()
            try:
                bw = int(b.get("win_camp") or 0)
            except (TypeError, ValueError):
                bw = 0
            if bw not in (1, 2):
                continue
            for team, camp in ((bt1, 1), (bt2, 2)):
                if team not in (t1, t2):
                    continue
                st = out.setdefault((lid, team), {"series": 0, "seriesWins": 0, "games": 0, "gameWins": 0, "matches": []})
                st["games"] += 1
                st["gameWins"] += 1 if bw == camp else 0
        if idx % 600 == 0:
            print(f"  series {idx}/{len(files)}", flush=True)
    return out


def main() -> None:
    leagues = load_leagues()
    tenures = read_csv(META / "coach_tenures.csv")
    exclusions = read_csv(META / "coach_tenure_exclusions.csv")
    bp_index = load_js(BP_DIR / "index.js", "KPL_TEAM_BP_INDEX")
    heroes = bp_index.get("heroes") or []
    bp_teams = {str(t.get("name")): t for t in bp_index.get("teams") or []}
    baselines = bp_index.get("baselines") or {}
    bp_shards = {}
    for f in sorted(BP_DIR.glob("shard_*.js")):
        bp_shards.update(load_js(f, "KPL_TEAM_BP_SHARD"))
    results = series_rows()

    out_rows = []
    problems = []
    bp_game_keys = set()
    for row in tenures:
        lid = str(row.get("league_id") or "")
        team = str(row.get("team") or "")
        if lid not in leagues or team not in bp_teams:
            problems.append(f"{team}/{lid}: 缺少赛事或战队数据")
            continue
        lg = leagues[lid]
        meta = bp_teams[team]
        shard = bp_shards.get(team) or {}
        bp_scope = (shard.get("scopes") or {}).get(lid)
        if not bp_scope:
            problems.append(f"{team}/{lid}: 缺少完整 BP 范围")
            continue
        base = baselines.get(lid) or baselines.get("all") or {}
        hm = {}
        for rec in bp_scope.get("heroes") or []:
            hm[rec[0]] = rec
        picks = bp_scope.get("picks") or 0
        bans = bp_scope.get("bans") or 0
        opp_bans = bp_scope.get("oppBans") or 0
        top_picks = []
        for i, p, pw, b, ob, op in sorted(hm.values(), key=lambda r: (-r[1], -(r[2] + r[3] + r[4] + r[5]), r[0]))[:10]:
            if p <= 0:
                continue
            bpick = (base.get("pick") or [0] * len(heroes))[i]
            bwin = (base.get("pickWins") or [0] * len(heroes))[i]
            pr = p / picks * 100 if picks else None
            bpr = bpick / (base.get("picks") or 1) * 100 if base.get("picks") else None
            top_picks.append({
                "i": i,
                "p": p,
                "pw": pw,
                "win": round(pw / p * 100, 1) if p else None,
                "rate": round(pr, 1) if pr is not None else None,
                "baseRate": round(bpr, 1) if bpr is not None else None,
                "lift": round(pr / bpr, 2) if pr is not None and bpr else None,
                "baseWin": round(bwin / bpick * 100, 1) if bpick else None,
            })
        top_bans = []
        for i, p, pw, b, ob, op in sorted(hm.values(), key=lambda r: (-r[3], -r[4], r[0]))[:10]:
            if b <= 0:
                continue
            top_bans.append({"i": i, "n": b, "rate": round(b / bans * 100, 1) if bans else None})
        top_against = []
        for i, p, pw, b, ob, op in sorted(hm.values(), key=lambda r: (-r[4], -r[3], r[0]))[:10]:
            if ob <= 0:
                continue
            top_against.append({"i": i, "n": ob, "rate": round(ob / opp_bans * 100, 1) if opp_bans else None})
        pick_counts = {r[0]: r[1] for r in (bp_scope.get("heroes") or [])}
        combos = []
        for a, b, n, cw in (bp_scope.get("combos") or [])[:8]:
            pa = pick_counts.get(a, 0)
            pb = pick_counts.get(b, 0)
            rate = n / bp_scope["games"] * 100 if bp_scope.get("games") else None
            exp = (pa / bp_scope["games"]) * (pb / bp_scope["games"]) * 100 if bp_scope.get("games") and pa and pb else None
            combos.append({
                "a": a, "b": b, "n": n, "win": round(cw / n * 100, 1) if n else None,
                "rate": round(rate, 1) if rate is not None else None,
                "lift": round(rate / exp, 2) if rate is not None and exp else None,
            })
        ev = []
        for r in (shard.get("evidence") or []):
            if str(r[2]) != lid:
                continue
            # date, match, stage, opponent, side, win, picks, bans, oppPicks, oppBans
            ev.append([r[0], r[1], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10]])
        for r in (shard.get("evidence") or []):
            if str(r[2]) != lid:
                continue
            all_hands = tuple(sorted((r[7] or []) + (r[8] or []) + (r[9] or []) + (r[10] or [])))
            bp_game_keys.add((r[1], r[0], all_hands))
        ev.sort(key=lambda r: (r[0], r[1]), reverse=True)
        st = results.get((lid, team)) or {}
        coach = str(row.get("coach_name") or "")
        out_rows.append({
            "id": f"{lid}|{team}|{row.get('coach_id')}",
            "coachId": row.get("coach_id"),
            "coach": coach,
            "team": team,
            "teamIcon": meta.get("icon") or shard.get("icon") or "",
            "league": lid,
            "leagueName": lg["name"],
            "seasonName": row.get("season_name") or lg["name"],
            "role": row.get("role") or "head_coach",
            "validFrom": lg["start"],
            "validTo": lg["end"],
            "sourceUrl": row.get("source_url") or "",
            "sourceType": row.get("source_type") or "",
            "confidence": row.get("confidence") or "medium",
            "verifiedAt": row.get("verified_at") or "",
            "note": row.get("note") or "",
            "series": {
                "games": st.get("series", 0),
                "wins": st.get("seriesWins", 0),
                "wr": round(st.get("seriesWins", 0) / st["series"] * 100, 1) if st.get("series") else None,
            },
            "games": {
                "games": st.get("games", 0),
                "wins": st.get("gameWins", 0),
                "wr": round(st.get("gameWins", 0) / st["games"] * 100, 1) if st.get("games") else None,
            },
            "bp": {
                "games": bp_scope.get("games", 0),
                "wins": bp_scope.get("wins", 0),
                "wr": round(bp_scope.get("wins", 0) / bp_scope["games"] * 100, 1) if bp_scope.get("games") else None,
                "picks": picks,
                "bans": bans,
                "oppBans": opp_bans,
                "uniquePicks": sum(1 for r in hm.values() if r[1] > 0),
                "uniqueBans": sum(1 for r in hm.values() if r[2] > 0),
                "effectiveHeroes": round(1 / sum((r[1] / picks) ** 2 for r in hm.values() if r[1] > 0), 1) if picks else None,
                "topShare": round(max((r[1] for r in hm.values()), default=0) / picks * 100, 1) if picks else None,
                "topPick": max(hm.values(), key=lambda r: r[1])[0] if hm and picks else None,
                "topBans": top_bans,
                "topAgainst": top_against,
                "topPicks": top_picks,
                "combos": combos,
            },
            "evidence": ev[:30],
        })
        print(f"  {team} {lg['name']} · {coach} | series {st.get('series',0)} | BP {bp_scope.get('games',0)}", flush=True)

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

    coach_list = sorted(coaches.values(), key=lambda c: (-c["bpGames"], -c["series"], c["name"]))
    data = {
        "generatedAt": datetime.now(CN).strftime("%Y-%m-%d %H:%M"),
        "sourceMode": "赛季名单（Liquipedia，社区整理）",
        "coverage": {
            "seasons": len({r["league"] for r in out_rows}),
            "teamSeasons": len(out_rows),
            "excludedTeamSeasons": len(exclusions),
            "coaches": len(coaches),
            "bpGames": len(bp_game_keys),
            "bpSamples": sum(r["bp"]["games"] for r in out_rows),
            "series": sum(r["series"]["games"] for r in out_rows),
            "start": min((r["validFrom"] for r in out_rows if r["validFrom"]), default=""),
            "end": max((r["validTo"] for r in out_rows if r["validTo"]), default=""),
        },
        "leagues": [{"id": lid, "name": lg["name"], "year": int(lid[:4]) if lid[:4].isdigit() else 0} for lid, lg in sorted(leagues.items()) if any(r["league"] == lid for r in out_rows)],
        "heroes": heroes,
        "coaches": coach_list,
        "tenures": out_rows,
        "exclusions": [
            {
                "team": r.get("team"), "league": r.get("league_id"), "seasonName": r.get("season_name"),
                "coach": r.get("coach_name"), "reason": r.get("exclude_reason"), "sourceUrl": r.get("source_url"),
            }
            for r in exclusions
        ],
        "problems": problems,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("window.KPL_COACH_DATA=" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"coaches {len(coach_list)} | tenures {len(out_rows)} | excluded {len(exclusions)} | problems {len(problems)}", flush=True)
    print(f"coverage {data['coverage']}", flush=True)
    print(f"size {OUT.stat().st_size/1024:.1f} KB | saved {OUT}", flush=True)
    if problems:
        for p in problems[:10]:
            print("WARN", p, flush=True)


if __name__ == "__main__":
    main()
