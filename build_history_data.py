# -*- coding: utf-8 -*-
"""把全历史回补数据（data/history，2019–2026）聚合成站点数据。

输出：
  assets/seasons.js      KPL.seasons —— 赛季索引 + 各范围（全部/年份/联赛）的战队/选手/英雄聚合
  assets/schedule_all.js KPL.scheduleAll —— 全量赛程（2748 场，含赛段/比分/状态）

数据源：../02-KPL实时胜率预测系统/data/history/<league_id>/matches/<match_id>.json
运行：python build_history_data.py
"""
from __future__ import annotations

import itertools
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
ASSETS = SITE / "assets"

TYPE_CN = {
    "kpl": "职业联赛",
    "world_champion_cup": "世界冠军杯",
    "winter_champion_cup": "冬冠/挑战者杯",
}

STAGE_CN = {
    "regular_season": "常规赛",
    "playoff": "季后赛",
    "group_phase": "小组赛",
    "cgs1": "常规赛·第 1 轮",
    "cgs2": "常规赛·第 2 轮",
    "cgs3": "常规赛·第 3 轮",
    "kws": "卡位赛",
    "jhs": "季后赛",
    "js": "总决赛",
    "lts": "擂台赛",
    "zjs": "总决赛",
    "dbtts": "单败淘汰赛",
    "sbtts": "双败淘汰赛",
    "kpl_select": "选拔赛",
    "select": "季前赛",
    "other_select": "选拔赛",
}


def jload(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def tier_of(wr: float) -> str:
    return "S" if wr >= 0.55 else "A" if wr >= 0.50 else "B" if wr >= 0.45 else "C"


def pct_num(x: float) -> float:
    return round(float(x), 3)


class Acc:
    """单范围累计器。"""

    def __init__(self):
        self.team = defaultdict(lambda: {"m": 0, "mw": 0, "ml": 0, "g": 0, "gw": 0, "gl": 0,
                                         "gold": 0, "kd": 0, "icon": "", "last": ""})
        self.player = defaultdict(lambda: {"g": 0, "w": 0, "k": 0, "d": 0, "a": 0, "mvp": 0,
                                           "part_sum": 0.0, "dmg_sum": 0.0, "gold": 0,
                                           "icon": "", "team": "", "teamIcon": "",
                                           "pos_sum": defaultdict(int), "last": ""})
        self.hero = defaultdict(lambda: {"g": 0, "w": 0, "ban": 0, "icon": "",
                                         "k": 0, "d": 0, "a": 0, "dmg_sum": 0.0,
                                         "bh_sum": 0.0, "gold": 0, "by": {}})
        self.combo2 = defaultdict(lambda: {"n": 0, "w": 0, "last": None})
        self.combo3 = defaultdict(lambda: {"n": 0, "w": 0, "last": None})
        self.totals = {"matches": 0, "battles": 0}

    def add_battle(self, match: dict, det: dict) -> None:
        win_camp = det.get("win_camp")
        if win_camp not in (1, 2):
            return
        self.totals["battles"] += 1
        date = str(match.get("start_time") or "")[:10]
        # 队伍级（局）
        for camp in (1, 2):
            c = det.get(f"camp{camp}") or {}
            name = str(c.get("team_name") or "").strip()
            if not name:
                continue
            t = self.team[name]
            t["g"] += 1
            t["gw"] += 1 if camp == win_camp else 0
            t["gl"] += 0 if camp == win_camp else 1
            if c.get("team_icon"):
                t["icon"] = str(c["team_icon"])
            t["last"] = max(t["last"], date)
            if "by" not in t:
                t["by"] = {}
            yk = date[:4]
            if yk:
                b = t["by"].setdefault(yk, [0, 0])
                b[0] += 1
                b[1] += 1 if camp == win_camp else 0
        # 金差与击杀差（以 camp1 视角）
        c1 = det.get("camp1") or {}
        c2 = det.get("camp2") or {}
        if c1.get("team_name") and c2.get("team_name"):
            gd = int(c1.get("gold") or 0) - int(c2.get("gold") or 0)
            kd = int(c1.get("kill_num") or 0) - int(c2.get("kill_num") or 0)
            self.team[str(c1["team_name"])]["gold"] += gd
            self.team[str(c2["team_name"])]["gold"] += -gd
            self.team[str(c1["team_name"])]["kd"] += kd
            self.team[str(c2["team_name"])]["kd"] += -kd
        # 选手级 + 同队英雄收集（供组合挖掘）
        camp_heroes: dict[int, list[str]] = {1: [], 2: []}
        for p in det.get("battle_player_list") or []:
            if not isinstance(p, dict):
                continue
            name = str(p.get("player_name") or p.get("actual_player_name") or "").strip()
            camp = int(p.get("camp") or 0)
            hn = str(p.get("hero_name") or "").strip()
            if hn and camp in (1, 2):
                camp_heroes[camp].append(hn)
            if not name:
                continue
            pl = self.player[name]
            pl["g"] += 1
            pl["w"] += 1 if camp == win_camp else 0
            pl["k"] += int(p.get("kill_num") or 0)
            pl["d"] += int(p.get("death_num") or 0)
            pl["a"] += int(p.get("assist_num") or 0)
            pl["mvp"] += 1 if str(p.get("is_mvp")) in ("1", "True", "true") else 0
            try:
                pl["part_sum"] += float(p.get("participation_rate") or 0)
                pl["dmg_sum"] += float(p.get("hurt_total_rate") or 0)
            except (TypeError, ValueError):
                pass
            pl["gold"] += int(float(p.get("gold") or 0))
            if p.get("player_icon"):
                pl["icon"] = str(p["player_icon"])
            if p.get("team_name"):
                pl["team"] = str(p["team_name"])
            if p.get("team_icon"):
                pl["teamIcon"] = str(p["team_icon"])
            pos = str(p.get("position_desc") or "").strip()
            if pos:
                pl["pos_sum"][pos] += 1
            pl["last"] = max(pl["last"], date)
            # 英雄出场与数据
            if hn:
                h = self.hero[hn]
                h["g"] += 1
                h["w"] += 1 if camp == win_camp else 0
                if p.get("hero_icon"):
                    h["icon"] = str(p["hero_icon"])
                h["k"] += int(p.get("kill_num") or 0)
                h["d"] += int(p.get("death_num") or 0)
                h["a"] += int(p.get("assist_num") or 0)
                yk2 = date[:4]
                if yk2:
                    hb2 = h["by"].setdefault(yk2, [0, 0, 0])
                    hb2[0] += 1
                    hb2[1] += 1 if camp == win_camp else 0
                try:
                    h["dmg_sum"] += float(p.get("hurt_total_rate") or 0)
                    h["bh_sum"] += float(p.get("be_hurt_total_rate") or 0)
                except (TypeError, ValueError):
                    pass
                h["gold"] += int(float(p.get("gold") or 0))
        # 同队组合挖掘（双人 / 三人）+ 记录最近一次出场
        bid = str(det.get("battle_id") or "")
        for camp in (1, 2):
            heroes_c = sorted(set(camp_heroes[camp]))
            if len(heroes_c) < 2:
                continue
            won = 1 if camp == win_camp else 0
            tname = str((det.get(f"camp{camp}") or {}).get("team_name") or "")
            key = (date, bid)
            for combo in itertools.combinations(heroes_c, 2):
                c = self.combo2[combo]
                c["n"] += 1
                c["w"] += won
                if c["last"] is None or key > (c["last"][0], c["last"][1]):
                    c["last"] = [date, bid, tname, won]
            if len(heroes_c) >= 3:
                for combo in itertools.combinations(heroes_c, 3):
                    c = self.combo3[combo]
                    c["n"] += 1
                    c["w"] += won
                    if c["last"] is None or key > (c["last"][0], c["last"][1]):
                        c["last"] = [date, bid, tname, won]
        # 禁用
        for b in det.get("bp_list") or []:
            if not isinstance(b, dict):
                continue
            if str(b.get("is_ban_or_pick")) in ("0", 0):
                hn = str(b.get("hero_name") or "").strip()
                if hn:
                    hb = self.hero[hn]
                    hb["ban"] += 1
                    if not hb["icon"] and b.get("hero_icon"):
                        hb["icon"] = str(b["hero_icon"])
                    ykb = date[:4]
                    if ykb:
                        hbb = hb["by"].setdefault(ykb, [0, 0, 0])
                        hbb[2] += 1

    def add_match_result(self, match: dict) -> None:
        c1 = match.get("camp1") or {}
        c2 = match.get("camp2") or {}
        wc = match.get("win_camp")
        n1, n2 = str(c1.get("team_name") or ""), str(c2.get("team_name") or "")
        if not n1 or not n2 or wc not in (1, 2):
            return
        self.totals["matches"] += 1
        for name, won in ((n1, wc == 1), (n2, wc == 2)):
            t = self.team[name]
            t["m"] += 1
            t["mw"] += 1 if won else 0
            t["ml"] += 0 if won else 1

    def dump(self, include_year: bool = False) -> dict:
        teams = []
        for name, t in self.team.items():
            g = t["g"] or 0
            row = {
                "team": name, "icon": t["icon"],
                "matches": t["m"], "mWin": t["mw"], "mLoss": t["ml"],
                "games": g, "wins": t["gw"], "losses": t["gl"],
                "wr": pct_num(t["gw"] / g) if g else 0,
                "goldDiff": round(t["gold"] / g) if g else 0,
                "killDiff": round(t["kd"] / g, 1) if g else 0,
            }
            if include_year and t.get("by"):
                row["by"] = [[int(y), b[0], pct_num(b[1] / b[0]) if b[0] else 0]
                             for y, b in sorted(t["by"].items())]
            teams.append(row)
        teams.sort(key=lambda x: (-x["wr"], -x["games"])) if len(teams) <= 24 else teams.sort(key=lambda x: -x["games"])
        players = []
        for name, p in self.player.items():
            g = p["g"] or 0
            d = p["d"] or 0
            kda = (p["k"] + p["a"]) / max(1, d) if g else 0
            pos = max(p["pos_sum"].items(), key=lambda kv: kv[1])[0] if p["pos_sum"] else ""
            players.append({
                "name": name, "team": p["team"], "teamIcon": p["teamIcon"], "icon": p["icon"],
                "pos": pos, "games": g, "wins": p["w"], "wr": pct_num(p["w"] / g) if g else 0,
                "kda": round(kda, 2), "mvp": p["mvp"],
                "part": round(p["part_sum"] / g, 1) if g else 0,
                "dmg": round(p["dmg_sum"] / g * 100, 1) if g else 0,
                "last": p["last"],
            })
        players.sort(key=lambda x: (-x["games"], -x["kda"]))
        heroes = []
        hero_wr = {}
        for name, h in self.hero.items():
            g = h["g"] or 0
            if g < 3 and h["ban"] < 3:
                continue
            wr = pct_num(h["w"] / g) if g else 0
            hero_wr[name] = wr
            kda = (h["k"] + h["a"]) / max(1, h["d"]) if g else 0
            hrow = {
                "name": name, "icon": h["icon"], "games": g,
                "wins": h["w"], "wr": wr,
                "bans": h["ban"], "tier": tier_of(wr),
                "kda": round(kda, 2),
                "dmg": round(h["dmg_sum"] / g * 100, 1) if g else 0,
                "bh": round(h["bh_sum"] / g * 100, 1) if g else 0,
                "gold": round(h["gold"] / g) if g else 0,
            }
            if include_year and h.get("by"):
                hrow["by"] = [[int(y), b[0], pct_num(b[1] / b[0]) if b[0] else 0,
                               pct_num(b[2] / (b[0] + b[2])) if (b[0] + b[2]) else 0]
                              for y, b in sorted(h["by"].items()) if b[0] >= 5]
            heroes.append(hrow)
        heroes.sort(key=lambda x: -x["games"])

        def logit(p: float) -> float:
            p = min(max(p, 0.02), 0.98)
            return math.log(p / (1 - p))

        def combo_rows(src, min_n: int, top: int):
            rows = []
            for combo, c in src.items():
                if c["n"] < min_n:
                    continue
                wr = c["w"] / c["n"] if c["n"] else 0
                wrs = [hero_wr.get(h, 0.5) for h in combo]
                exp_logit = sum(logit(w) for w in wrs) / len(wrs)
                exp_wr = 1 / (1 + math.exp(-exp_logit))
                row = {
                    "h": list(combo), "n": c["n"], "w": c["w"],
                    "wr": pct_num(wr),
                    "syn": round(wr - exp_wr, 3),
                }
                if include_year and c.get("last"):
                    row["last"] = [c["last"][0], c["last"][1], c["last"][2], c["last"][3]]
                rows.append(row)
            rows.sort(key=lambda x: -x["n"])
            if len(rows) > top:
                keep = rows[:top]
                # 高协同的小样本组合也保留一部分
                hot = sorted([r for r in rows if r["n"] >= min_n + 4], key=lambda x: -x["syn"])[: top // 3]
                merged = {tuple(r["h"]): r for r in keep + hot}
                rows = sorted(merged.values(), key=lambda x: -x["n"])
            return rows

        return {
            "totals": self.totals,
            "teams": teams,
            "players": players[:100],
            "heroes": heroes[:140],
            "combo2": combo_rows(self.combo2, 12, 160),
            "combo3": combo_rows(self.combo3, 8, 120),
        }


def main() -> None:
    leagues_meta = jload(HIST / "leagues.json") or []
    if not leagues_meta:
        raise SystemExit("leagues.json 不存在，请先运行 backfill_league_history.py")

    acc_all = Acc()
    acc_year: dict[str, Acc] = {}
    acc_league: dict[str, Acc] = {}
    league_rows = []
    schedule_all = []

    for lg in leagues_meta:
        lid = lg["league_id"]
        year = lid[:4]
        schedule = jload(HIST / lid / "schedule.json") or []
        mfiles = sorted((HIST / lid / "matches").glob("*.json"))
        if lid not in acc_league:
            acc_league[lid] = Acc()
        if year not in acc_year:
            acc_year[year] = Acc()
        n_battles = 0
        champ = {"date": "", "winner": "", "runner": "", "finished": False}
        video_map: dict[str, str] = {}
        for f in mfiles:
            obj = jload(f) or {}
            match = obj.get("match") or {}
            battles = obj.get("battles") or []
            mid = str(match.get("match_id") or f.stem)
            for det in battles:
                if not isinstance(det, dict) or det.get("win_camp") not in (1, 2):
                    continue
                acc_all.add_battle(match, det)
                acc_year[year].add_battle(match, det)
                acc_league[lid].add_battle(match, det)
                n_battles += 1
                if mid not in video_map:
                    vl = det.get("video_list") or []
                    if vl and isinstance(vl[0], dict) and vl[0].get("video_url"):
                        video_map[mid] = str(vl[0]["video_url"])
            acc_all.add_match_result(match)
            acc_year[year].add_match_result(match)
            acc_league[lid].add_match_result(match)
            wc_m = int(match.get("win_camp") or 0)
            mdate = str(match.get("start_time") or "")[:10]
            if wc_m in (1, 2):
                c1m, c2m = match.get("camp1") or {}, match.get("camp2") or {}
                wname = str(c1m.get("team_name") if wc_m == 1 else c2m.get("team_name") or "")
                rname = str(c2m.get("team_name") if wc_m == 1 else c1m.get("team_name") or "")
                if mdate >= champ["date"]:
                    champ = {"date": mdate, "winner": wname, "runner": rname,
                             "finished": int(match.get("status") or 0) == 2 or wc_m in (1, 2)}
        # 赛程行：只有含实际局数据的场次才算「可复盘」
        done_ids = set()
        for f in mfiles:
            obj_f = jload(f) or {}
            if obj_f.get("battles"):
                done_ids.add(str((obj_f.get("match") or {}).get("match_id") or f.stem))
        for m in schedule:
            c1 = m.get("camp1") or {}
            c2 = m.get("camp2") or {}
            st = int(m.get("status") or 0)
            wc = m.get("win_camp")
            vids = m.get("match_battle_video_list") or []
            video = ""
            if isinstance(vids, list) and vids and isinstance(vids[0], dict):
                video = str(vids[0].get("video_url") or "")
            if not video:
                video = video_map.get(str(m.get("match_id") or ""), "")
            schedule_all.append({
                "matchId": str(m.get("match_id") or ""),
                "leagueId": lid,
                "leagueName": lg["league_name"],
                "year": int(year),
                "stage": STAGE_CN.get(str(m.get("match_stage_name") or ""), str(m.get("match_stage_name") or "")),
                "date": str(m.get("start_time") or "")[:10],
                "time": str(m.get("start_time") or "")[11:16],
                "team1": str(c1.get("team_name") or ""), "icon1": str(c1.get("team_icon") or ""),
                "team2": str(c2.get("team_name") or ""), "icon2": str(c2.get("team_icon") or ""),
                "score1": int(c1.get("score") or 0), "score2": int(c2.get("score") or 0),
                "bo": int(m.get("bo") or 0),
                "done": st == 2 or wc in (1, 2),
                "st": st,
                "hasDetail": str(m.get("match_id")) in done_ids,
                "video": video,
            })
        league_finished = bool(schedule) and all(
            int(mm.get("status") or 0) == 2 for mm in schedule if mm.get("match_id"))
        league_rows.append({
            "champion": champ["winner"] if league_finished else "",
            "runner": champ["runner"] if league_finished else "",
            "champDate": champ["date"],
            "champLeader": champ["winner"] if not league_finished else "",
            "champFinished": league_finished,
            "id": lid, "name": lg["league_name"], "year": int(year),
            "type": TYPE_CN.get(lg.get("league_type") or "", lg.get("league_type") or ""),
            "start": str(lg.get("start_time") or "")[:10],
            "end": str(lg.get("end_time") or "")[:10],
            "matches": len(schedule),
            "battles": n_battles,
        })
        print(f"{lid} {lg['league_name']}: {len(mfiles)} 场 / {n_battles} 局", flush=True)

    schedule_all.sort(key=lambda r: (r["date"], r["time"]))
    years = sorted({r["year"] for r in league_rows})
    scopes = {"all": acc_all.dump(include_year=True)}
    for y in years:
        scopes[str(y)] = acc_year[str(y)].dump()
    for lid, acc in acc_league.items():
        scopes[lid] = acc.dump()

    seasons = {
        "years": years,
        "leagues": league_rows,
        "scopes": scopes,
    }
    out1 = ASSETS / "seasons.js"
    out1.write_text("KPL_SEASONS = " + json.dumps(seasons, ensure_ascii=False, separators=(",", ":")) + ";\n",
                    encoding="utf-8")
    out2 = ASSETS / "schedule_all.js"
    out2.write_text("KPL_SCHEDULE_ALL = " + json.dumps(schedule_all, ensure_ascii=False, separators=(",", ":")) + ";\n",
                    encoding="utf-8")
    print(f"\nseasons.js: {out1.stat().st_size/1024:.0f} KB | schedule_all.js: {out2.stat().st_size/1024:.0f} KB")
    print(f"scopes: {len(scopes)} | leagues: {len(league_rows)} | schedule rows: {len(schedule_all)}")


if __name__ == "__main__":
    main()
