# -*- coding: utf-8 -*-
"""战队 BP 风格与效果数据。

输出：
  assets/team_bp/index.js          KPL_TEAM_BP_INDEX
  assets/team_bp/shard_0..7.js     KPL_TEAM_BP_SHARD

口径：
  - 只纳入双方各 5 选 / 5 禁、共 20 手完整 BP 的有效小局；
  - 选用与禁用分开：禁用不进入英雄胜率分母；
  - 战队风格与赛果分开：偏好不等于擅长，胜率只是赛果描述；
  - BP 顺序/首抢/后手暂不输出，避免把未核验的规则变体当成结论；
  - 同赛事基准使用该赛事全部完整 BP 局，基准池不混入 2019–2024 缺手数据。

运行：python build_team_bp.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from itertools import combinations
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
OUT = SITE / "assets" / "team_bp"
CN = timezone(timedelta(hours=8))
SHARDS = 8
MIN_EFFECT_GAMES = 10
MIN_COMBO_GAMES = 2
MAX_COMBOS = 40

STAGE_CN = {
    "regular_season": "常规赛", "playoff": "季后赛", "group_phase": "小组赛",
    "cgs1": "常规赛·第 1 轮", "cgs2": "常规赛·第 2 轮", "cgs3": "常规赛·第 3 轮",
    "kws": "卡位赛", "jhs": "季后赛", "js": "总决赛", "lts": "擂台赛", "zjs": "总决赛",
    "dbtts": "单败淘汰赛", "sbtts": "双败淘汰赛", "kpl_select": "选拔赛",
    "select": "季前赛", "other_select": "选拔赛", "tws": "突围赛", "fjs": "附加赛",
}


def load_js(path: Path, var: str) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"window\." + re.escape(var) + r"\s*=\s*(\{.*\})\s*;?\s*$", text, re.S)
    if not m:
        m = re.search(re.escape(var) + r"\s*=\s*(\{.*\})\s*;?\s*$", text, re.S)
    if not m:
        raise SystemExit(f"{path.name} 结构无法解析")
    return json.loads(m.group(1))


def pct_rank(sorted_vals: list[float], v: float) -> float | None:
    if len(sorted_vals) < 2:
        return None
    below = 0
    for x in sorted_vals:
        if x < v:
            below += 1
        else:
            break
    return min(100.0, below / (len(sorted_vals) - 1) * 100)


def main() -> None:
    seasons = load_js(SITE / "assets" / "seasons.js", "KPL_SEASONS")
    scope_all = (seasons.get("scopes") or {}).get("all") or {}
    team_icon = {str(t.get("team") or ""): str(t.get("icon") or "") for t in scope_all.get("teams") or []}
    hero_icon = {str(h.get("name") or ""): str(h.get("icon") or "") for h in scope_all.get("heroes") or []}

    leagues_meta = {}
    try:
        for lg in json.loads((HIST / "leagues.json").read_text(encoding="utf-8")):
            leagues_meta[str(lg.get("league_id"))] = {
                "id": str(lg.get("league_id")),
                "name": str(lg.get("league_name") or lg.get("league_id")),
                "year": int(str(lg.get("start_time") or "0")[:4] or 0),
            }
    except Exception:
        pass

    games = []
    skipped = Counter()
    scanned_battles = 0
    hero_counts = Counter()
    files = sorted(HIST.glob("*/matches/*.json"))
    print(f"history files: {len(files)}", flush=True)

    for idx, f in enumerate(files, 1):
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            skipped["unreadable_file"] += 1
            continue
        match = obj.get("match") or {}
        lid = str(match.get("league_id") or f.parent.parent.name)
        date = str(match.get("start_time") or "")[:10]
        stage_raw = str(match.get("match_stage_name") or "")
        stage = STAGE_CN.get(stage_raw, stage_raw)
        match_id = str(match.get("match_id") or f.stem)
        for b in obj.get("battles") or []:
            scanned_battles += 1
            bp = b.get("bp_list") or []
            if len(bp) != 20:
                skipped["incomplete_bp"] += 1
                continue
            t1 = str((b.get("camp1") or {}).get("team_name") or "").strip()
            t2 = str((b.get("camp2") or {}).get("team_name") or "").strip()
            if not t1 or not t2 or t1 == t2:
                skipped["bad_teams"] += 1
                continue
            try:
                win_camp = int(b.get("win_camp") or 0)
            except (TypeError, ValueError):
                win_camp = 0
            if win_camp not in (1, 2):
                skipped["no_winner"] += 1
                continue
            hands = []
            ok = True
            for x in bp:
                hero = str(x.get("hero_name") or "").strip()
                try:
                    camp = int(x.get("camp") or 0)
                    act = 0 if str(x.get("is_ban_or_pick")) in ("0", 0) else 1
                except (TypeError, ValueError):
                    ok = False
                    break
                if not hero or camp not in (1, 2):
                    ok = False
                    break
                hands.append([act, camp, hero])
            if not ok or len({h for _, _, h in hands}) != 20:
                skipped["bad_hands"] += 1
                continue
            by_camp = {
                c: {
                    "picks": [h for a, cc, h in hands if cc == c and a == 1],
                    "bans": [h for a, cc, h in hands if cc == c and a == 0],
                }
                for c in (1, 2)
            }
            if any(len(by_camp[c]["picks"]) != 5 or len(by_camp[c]["bans"]) != 5 for c in (1, 2)):
                skipped["bad_counts"] += 1
                continue
            for h in {h for _, _, h in hands}:
                hero_counts[h] += 1
            games.append(
                {
                    "match": match_id,
                    "date": date,
                    "league": lid,
                    "stage": stage,
                    "t1": t1,
                    "t2": t2,
                    "win": win_camp,
                    "hands": hands,
                }
            )
        if idx % 500 == 0:
            print(f"  parse {idx}/{len(files)} | complete BP {len(games)}", flush=True)

    if not games:
        raise SystemExit("没有可用的完整 BP 局")

    hero_list = [h for h, _ in hero_counts.most_common()]
    hero_idx = {h: i for i, h in enumerate(hero_list)}
    H = len(hero_list)
    leagues_used = sorted({g["league"] for g in games})
    teams = sorted({g["t1"] for g in games} | {g["t2"] for g in games})
    dates = sorted(g["date"] for g in games if g["date"])
    print(f"complete BP: {len(games)} games | {len(teams)} teams | {len(leagues_used)} leagues | {H} heroes", flush=True)
    print(f"skipped: {dict(skipped)} | scanned battles: {scanned_battles}", flush=True)

    # 基准池：全部 / 每个赛事，按英雄聚合选用、选用胜场与禁用。
    baselines = {}
    for scope in ["all"] + leagues_used:
        base = {
            "games": 0,
            "picks": 0,
            "bans": 0,
            "pick": [0] * H,
            "pickWins": [0] * H,
            "ban": [0] * H,
        }
        for g in games:
            if scope != "all" and g["league"] != scope:
                continue
            base["games"] += 1
            for c in (1, 2):
                win = 1 if g["win"] == c else 0
                for h in [h for a, cc, h in g["hands"] if cc == c and a == 1]:
                    i = hero_idx[h]
                    base["picks"] += 1
                    base["pick"][i] += 1
                    base["pickWins"][i] += win
                for h in [h for a, cc, h in g["hands"] if cc == c and a == 0]:
                    base["bans"] += 1
                    base["ban"][hero_idx[h]] += 1
        baselines[scope] = base
    print(f"baselines: {len(baselines)} scopes", flush=True)

    team_games = defaultdict(list)
    for g in games:
        team_games[g["t1"]].append((g, 1, g["t2"]))
        team_games[g["t2"]].append((g, 2, g["t1"]))

    def new_scope() -> dict:
        return {
            "games": 0,
            "wins": 0,
            "picks": 0,
            "bans": 0,
            "oppBans": 0,
            "heroes": defaultdict(lambda: [0, 0, 0, 0, 0]),
            "combos": Counter(),
            "comboWins": Counter(),
        }

    scope_ids = ["all"] + leagues_used
    team_stats = {}
    team_evidence = defaultdict(list)
    for team, rows in team_games.items():
        stats = {scope: new_scope() for scope in scope_ids}
        for g, camp, opp in rows:
            win = 1 if g["win"] == camp else 0
            picks = [hero_idx[h] for a, c, h in g["hands"] if c == camp and a == 1]
            bans = [hero_idx[h] for a, c, h in g["hands"] if c == camp and a == 0]
            opp_picks = [hero_idx[h] for a, c, h in g["hands"] if c != camp and a == 1]
            opp_bans = [hero_idx[h] for a, c, h in g["hands"] if c != camp and a == 0]
            team_evidence[team].append(
                [g["date"], g["match"], g["league"], g["stage"], opp, camp, win, picks, bans, opp_picks, opp_bans]
            )
            for scope in ("all", g["league"]):
                st = stats[scope]
                st["games"] += 1
                st["wins"] += win
                st["picks"] += len(picks)
                st["bans"] += len(bans)
                st["oppBans"] += len(opp_bans)
                for i in picks:
                    st["heroes"][i][0] += 1
                    st["heroes"][i][1] += win
                for i in bans:
                    st["heroes"][i][2] += 1
                for i in opp_bans:
                    st["heroes"][i][3] += 1
                for i in opp_picks:
                    st["heroes"][i][4] += 1
                for a, b in combinations(sorted(picks), 2):
                    st["combos"][(a, b)] += 1
                    if win:
                        st["comboWins"][(a, b)] += 1
        team_stats[team] = stats

    # 胜率分位：只对样本 >= 10 局的战队计算，避免 2 局样本决定排名。
    rank_meta = {}
    for scope in scope_ids:
        eligible = [
            (team, stats[scope]["wins"] / stats[scope]["games"] * 100)
            for team, stats in team_stats.items()
            if stats[scope]["games"] >= MIN_EFFECT_GAMES
        ]
        vals = sorted(v for _, v in eligible)
        for team, wr in eligible:
            rank_meta[(scope, team)] = {
                "pct": round(pct_rank(vals, wr)) if len(vals) > 1 else None,
                "rankN": len(vals),
            }

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("shard_*.js"):
        old.unlink()
    shards = [{} for _ in range(SHARDS)]
    index_teams = []
    for team in sorted(team_games, key=lambda t: (-team_stats[t]["all"]["games"], t)):
        stats = team_stats[team]
        shard = int(hashlib.md5(team.encode("utf-8")).hexdigest(), 16) % SHARDS
        out_scopes = {}
        for scope in scope_ids:
            st = stats[scope]
            if not st["games"]:
                continue
            out_scopes[scope] = {
                "games": st["games"],
                "wins": st["wins"],
                "picks": st["picks"],
                "bans": st["bans"],
                "oppBans": st["oppBans"],
                "heroes": [
                    [int(i), int(v[0]), int(v[1]), int(v[2]), int(v[3]), int(v[4])]
                    for i, v in sorted(st["heroes"].items())
                ],
                "combos": [
                    [int(a), int(b), int(n), int(st["comboWins"].get((a, b), 0))]
                    for (a, b), n in st["combos"].most_common(MAX_COMBOS)
                    if n >= MIN_COMBO_GAMES
                ],
            }
        ev = sorted(team_evidence[team], key=lambda r: (r[0], r[1]), reverse=True)
        shards[shard][team] = {
            "name": team,
            "icon": team_icon.get(team, ""),
            "games": stats["all"]["games"],
            "wins": stats["all"]["wins"],
            "scopes": out_scopes,
            "evidence": ev,
        }
        leagues_for_team = [s for s in leagues_used if stats[s]["games"] > 0]
        scopes_out = {}
        for scope in scope_ids:
            st = stats[scope]
            if not st["games"]:
                continue
            rank = rank_meta.get((scope, team), {})
            scopes_out[scope] = {
                "games": st["games"],
                "wins": st["wins"],
                "wr": round(st["wins"] / st["games"] * 100, 1),
                "pct": rank.get("pct"),
                "rankN": rank.get("rankN", 0),
            }
        index_teams.append(
            {
                "name": team,
                "icon": team_icon.get(team, ""),
                "games": stats["all"]["games"],
                "shard": shard,
                "leagues": leagues_for_team,
                "scopes": scopes_out,
            }
        )

    for i, shard in enumerate(shards):
        body = "window.KPL_TEAM_BP_SHARD=" + json.dumps(shard, ensure_ascii=False, separators=(",", ":")) + ";\n"
        (OUT / f"shard_{i}.js").write_text(body, encoding="utf-8")

    index = {
        "generatedAt": datetime.now(CN).strftime("%Y-%m-%d %H:%M"),
        "coverage": {
            "start": dates[0] if dates else "",
            "end": dates[-1] if dates else "",
            "games": len(games),
            "series": len({g["match"] for g in games}),
            "leagues": len(leagues_used),
            "teams": len(teams),
            "teams10": sum(1 for t in teams if team_stats[t]["all"]["games"] >= MIN_EFFECT_GAMES),
            "scannedBattles": scanned_battles,
            "skipped": dict(skipped),
            "orderSupported": False,
        },
        "leagues": [leagues_meta.get(lid, {"id": lid, "name": lid, "year": int(lid[:4]) if lid[:4].isdigit() else 0}) for lid in leagues_used],
        "heroes": [{"name": h, "icon": hero_icon.get(h, "")} for h in hero_list],
        "baselines": baselines,
        "teams": index_teams,
    }
    (OUT / "index.js").write_text(
        "window.KPL_TEAM_BP_INDEX=" + json.dumps(index, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    total_size = sum(p.stat().st_size for p in OUT.glob("*.js"))
    print(f"coverage: {index['coverage']}", flush=True)
    print(f"shards: {SHARDS} | size: {total_size/1024/1024:.2f} MB", flush=True)
    print(f"saved: {OUT}", flush=True)


if __name__ == "__main__":
    main()
