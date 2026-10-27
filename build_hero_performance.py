# -*- coding: utf-8 -*-
"""逐系列赛选手 × 英雄表现数据。

输出：
  assets/hero_perf/index.js          KPL_HERO_PERF_INDEX
  assets/hero_perf/shard_0..15.js    KPL_HERO_PERF_SHARD

口径：
  - 有效小局：已结束、两队队名完整、battle_id 去重（复用 kpl_series）；
  - 系列赛：一次 BO 对抗；选手 × 英雄 × 系列赛为一条证据行；
  - 选手英雄聚合：按系列赛聚合，不把单局当选手样本；
  - 基准：同位置 + 同英雄 + 同赛事，排除当前选手；池不足 3 人/20 局时
    显式回退到同位置 + 同英雄全历史；仍不足则标记基准不足；
  - P50/P75/P90 为描述性参考，不是官方评级。

运行：python build_hero_performance.py
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

from kpl_series import summarize_match, battle_winner_team, team_name_of

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
OUT = SITE / "assets" / "hero_perf"
CN = timezone(timedelta(hours=8))

SHARDS = 16
MIN_PLAYER_GAMES = 20
POOL_ROW_MIN_GAMES = 5
MIN_POOL_PLAYERS = 3
MIN_POOL_GAMES = 20
VALID_POS = {"对抗路", "打野", "中路", "发育路", "游走"}


def num(v, default=None):
    try:
        x = float(v)
        if not math.isfinite(x):
            return default
        return x
    except (TypeError, ValueError):
        return default


def int0(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def load_players() -> dict:
    text = (SITE / "assets" / "players_detail.js").read_text(encoding="utf-8")
    m = re.search(r"=\s*(\{.*\})\s*;?\s*$", text, re.S)
    if not m:
        raise SystemExit("players_detail.js 结构无法解析")
    return json.loads(m.group(1))


def load_leagues() -> dict:
    path = HIST / "leagues.json"
    if not path.exists():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {str(r.get("league_id")): r for r in rows if isinstance(r, dict)}


def pct_ref(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def pct_rank(sorted_vals: list[float], v: float | None) -> float | None:
    if v is None or not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return 50.0
    below = 0
    for x in sorted_vals:
        if x < v:
            below += 1
        else:
            break
    return min(100.0, below / (len(sorted_vals) - 1) * 100)


def ratio(a: float, b: float) -> float | None:
    return a / b if b > 0 else None


def rnd(v: float | None, digits: int) -> float | None:
    return None if v is None else round(v, digits)


def metrics_of(row: dict) -> dict[str, float | None]:
    games = max(1, row["games"])
    minutes = max(0.01, row["minutes"])
    return {
        "kda": (row["kills"] + row["assists"]) / max(1, row["deaths"]),
        # 分均伤害 / 经济只除以“该字段有效”的出场分钟；缺失局不按 0 摊薄。
        "dmg": ratio(row["hurt"], row["dmg_minutes"]),
        "gold": ratio(row["gold"], row["gold_minutes"]),
        "part": ratio(row["part_sum"], row["part_games"]),
        "surv": row["deaths"] / minutes,
        "wr": row["wins"] / games * 100,
    }


def bench_for(target: dict, group: list[dict]) -> dict | None:
    target_player = target.get("_player")
    others = [
        r for r in group
        if r is not target and (not target_player or r.get("_player") != target_player)
    ]
    pool_games = sum(r["games"] for r in others)
    if len(others) < MIN_POOL_PLAYERS or pool_games < MIN_POOL_GAMES:
        return None
    p = {}
    ref = {}
    for key, lower_better in (("kda", False), ("dmg", False), ("gold", False), ("part", False), ("surv", True)):
        vals = sorted(r["m"][key] for r in others if r["m"].get(key) is not None)
        if len(vals) < MIN_POOL_PLAYERS:
            p[key] = None
            ref[key] = None
            continue
        rank = pct_rank(vals, target["m"].get(key))
        if rank is not None and lower_better:
            rank = 100 - rank
        p[key] = None if rank is None else round(rank)
        ref[key] = [round(pct_ref(vals, 0.5), 1), round(pct_ref(vals, 0.75), 1), round(pct_ref(vals, 0.90), 1)]
    wins = sum(r["wins"] for r in others)
    games = sum(r["games"] for r in others)
    return {
        "p": p,
        "ref": ref,
        "poolPlayers": len(others),
        "poolGames": pool_games,
        "leagueWr": round(wins / max(1, games) * 100, 1),
        "leagueGames": games,
    }


def main() -> None:
    players_meta = load_players()
    leagues = load_leagues()
    files = sorted(HIST.glob("*/matches/*.json"))
    print(f"history files: {len(files)} | players: {len(players_meta)}", flush=True)

    # key: (player, match_id, hero) -> series evidence
    series: dict[tuple[str, str, str], dict] = {}
    metric_issues = Counter()
    for idx, f in enumerate(files, 1):
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        res = summarize_match(obj, fallback_id=f.stem)
        if res is None:
            continue
        teams = {res.team1, res.team2}
        for b in res.battles:
            winner = battle_winner_team(b)
            duration = num(b.get("game_duration"), 0) / 60000.0
            if duration <= 0:
                continue
            players = b.get("battle_player_list") or []
            team_kills = Counter()
            for pl in players:
                team_kills[str(pl.get("team_name") or "").strip()] += int0(pl.get("kill_num"))
            for pl in players:
                name = str(pl.get("player_name") or pl.get("actual_player_name") or "").strip()
                if not name or name not in players_meta:
                    continue
                team = str(pl.get("team_name") or "").strip()
                if team not in teams:
                    continue
                hero = str(pl.get("hero_name") or "").strip()
                if not hero:
                    continue
                pos = str(pl.get("position_desc") or "").strip()
                if pos not in VALID_POS:
                    pos = str((players_meta.get(name) or {}).get("pos") or "未知")
                key = (name, res.match_id, hero)
                row = series.get(key)
                if row is None:
                    row = {
                        "player": name,
                        "matchId": res.match_id,
                        "league": res.league_id,
                        "leagueName": str((leagues.get(str(res.league_id)) or {}).get("league_name") or res.league_id),
                        "year": int(str(res.date)[:4]) if str(res.date)[:4].isdigit() else 0,
                        "date": str(res.date)[:10],
                        "stage": str(res.stage or ""),
                        "team": team,
                        "opponent": res.team2 if team == res.team1 else res.team1,
                        "hero": hero,
                        "heroId": str(pl.get("hero_id") or ""),
                        "heroIcon": str(pl.get("hero_icon") or ""),
                        "pos": pos,
                        "games": 0,
                        "wins": 0,
                        "kills": 0,
                        "deaths": 0,
                        "assists": 0,
                        "gold": 0.0,
                        "hurt": 0.0,
                        "part_sum": 0.0,
                        "minutes": 0.0,
                        "dmg_minutes": 0.0,
                        "gold_minutes": 0.0,
                        "part_games": 0,
                        "seriesWin": 1 if res.winner == team else 0,
                        "seriesScore": list(res.score),
                        "battleIds": [],
                    }
                    series[key] = row
                row["games"] += 1
                row["wins"] += 1 if winner == team else 0
                row["kills"] += int0(pl.get("kill_num"))
                row["deaths"] += int0(pl.get("death_num"))
                row["assists"] += int0(pl.get("assist_num"))
                # 源数据里伤害 / 经济为 0 基本是字段缺失，不按真实 0 计入；
                # 参团率 0 在队内有击杀时是有效事实，队内 0 击杀时无定义。
                hurt = num(pl.get("hurt_total"))
                if hurt is not None and hurt > 0:
                    row["hurt"] += hurt
                    row["dmg_minutes"] += duration
                else:
                    metric_issues["hurt_invalid"] += 1
                gold = num(pl.get("gold"))
                if gold is not None and gold > 0:
                    row["gold"] += gold
                    row["gold_minutes"] += duration
                else:
                    metric_issues["gold_invalid"] += 1
                part = num(pl.get("participation_rate"))
                if part is not None and team_kills.get(team, 0) > 0:
                    row["part_sum"] += part
                    row["part_games"] += 1
                else:
                    metric_issues["part_undefined"] += 1
                row["minutes"] += duration
                bid = str(b.get("battle_id") or "")
                if bid:
                    row["battleIds"].append(bid)
        if idx % 300 == 0:
            print(f"  parse {idx}/{len(files)} | series rows {len(series)}", flush=True)

    # player -> hero -> league aggregates
    by_player: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(dict))
    for row in series.values():
        row["m"] = metrics_of(row)
        player = row["player"]
        hero = row["hero"]
        league = str(row["league"])
        bucket = {
            "hero": hero,
            "heroId": row["heroId"],
            "heroIcon": row["heroIcon"],
            "pos": row["pos"],
            "league": league,
            "leagueName": row["leagueName"],
            "year": row["year"],
            "series": 0,
            "games": 0,
            "wins": 0,
            "kills": 0,
            "deaths": 0,
            "assists": 0,
            "gold": 0.0,
            "hurt": 0.0,
            "part_sum": 0.0,
            "minutes": 0.0,
            "dmg_minutes": 0.0,
            "gold_minutes": 0.0,
            "part_games": 0,
            "_rows": [],
        }
        target = by_player[player][hero].setdefault("leagues", {}).setdefault(league, bucket)
        target["series"] += 1
        target["games"] += row["games"]
        target["wins"] += row["wins"]
        target["kills"] += row["kills"]
        target["deaths"] += row["deaths"]
        target["assists"] += row["assists"]
        target["gold"] += row["gold"]
        target["hurt"] += row["hurt"]
        target["part_sum"] += row["part_sum"]
        target["minutes"] += row["minutes"]
        target["dmg_minutes"] += row["dmg_minutes"]
        target["gold_minutes"] += row["gold_minutes"]
        target["part_games"] += row["part_games"]
        target["_rows"].append(row)

    # build pool rows (player-hero-league), with metrics
    pool_rows = []
    for player, heroes in by_player.items():
        meta = players_meta.get(player) or {}
        for hero, hero_obj in heroes.items():
            for league, row in hero_obj.get("leagues", {}).items():
                if row["games"] < POOL_ROW_MIN_GAMES or row["pos"] not in VALID_POS:
                    continue
                row["m"] = metrics_of(row)
                row["_player"] = player
                row["_hero"] = hero
                pool_rows.append(row)
    print(f"hero-league rows: {sum(len(h.get('leagues', {})) for hs in by_player.values() for h in hs.values())} | pool rows: {len(pool_rows)}", flush=True)

    groups = defaultdict(list)
    for row in pool_rows:
        groups[(row["pos"], row["_hero"], row["league"])].append(row)
    groups_all = defaultdict(list)
    for row in pool_rows:
        groups_all[(row["pos"], row["_hero"])].append(row)

    # attach bench to league rows
    for (pos, hero, league), group in groups.items():
        for row in group:
            bench = bench_for(row, group)
            if bench:
                bench["scope"] = "same-league"
            else:
                bench = bench_for(row, groups_all[(pos, hero)])
                if bench:
                    bench["scope"] = "all-leagues"
            row["bench"] = bench

    # build player output
    out_players = {}
    total_pool_all = []
    for player, heroes in by_player.items():
        meta = players_meta.get(player) or {}
        hero_rows = []
        total_series = set()
        total_games = 0
        for hero, hero_obj in heroes.items():
            leagues_rows = []
            agg = {
                "hero": hero,
                "heroId": "",
                "heroIcon": "",
                "pos": "",
                "series": 0,
                "games": 0,
                "wins": 0,
                "kills": 0,
                "deaths": 0,
                "assists": 0,
                "gold": 0.0,
                "hurt": 0.0,
                "part_sum": 0.0,
                "minutes": 0.0,
                "dmg_minutes": 0.0,
                "gold_minutes": 0.0,
                "part_games": 0,
            }
            for league, row in sorted(hero_obj.get("leagues", {}).items(), key=lambda kv: (-kv[1]["games"], kv[0])):
                m = row.get("m") or metrics_of(row)
                league_row = {
                    "league": league,
                    "leagueName": row["leagueName"],
                    "year": row["year"],
                    "pos": row["pos"],
                    "series": row["series"],
                    "games": row["games"],
                    "wins": row["wins"],
                    "wr": round(m["wr"], 1),
                    "kda": round(m["kda"], 2),
                    "dmgMin": rnd(m["dmg"], 1),
                    "goldMin": rnd(m["gold"], 1),
                    "part": rnd(m["part"], 1),
                    "deathsMin": round(m["surv"], 3),
                    "bench": row.get("bench"),
                }
                leagues_rows.append(league_row)
                for k in (
                    "series", "games", "wins", "kills", "deaths", "assists",
                    "gold", "hurt", "part_sum", "minutes", "dmg_minutes", "gold_minutes", "part_games",
                ):
                    agg[k] += row[k]
                if not agg["heroId"] and row["heroId"]:
                    agg["heroId"] = row["heroId"]
                if not agg["heroIcon"] and row["heroIcon"]:
                    agg["heroIcon"] = row["heroIcon"]
                if row["pos"] in VALID_POS:
                    agg["pos"] = row["pos"]
                for sr in row.get("_rows", []):
                    total_series.add(sr["matchId"])
                total_games += row["games"]
            m = metrics_of(agg)
            total_row = {
                "hero": hero,
                "heroId": agg["heroId"],
                "heroIcon": agg["heroIcon"],
                "pos": agg["pos"],
                "series": agg["series"],
                "games": agg["games"],
                "wins": agg["wins"],
                "wr": round(m["wr"], 1),
                "kda": round(m["kda"], 2),
                "dmgMin": rnd(m["dmg"], 1),
                "goldMin": rnd(m["gold"], 1),
                "part": rnd(m["part"], 1),
                "deathsMin": round(m["surv"], 3),
                "bench": None,
                "leagues": leagues_rows,
            }
            if total_row["games"] >= POOL_ROW_MIN_GAMES and total_row["pos"] in VALID_POS:
                total_pool_all.append(
                    {
                        "_player": player,
                        "hero": hero,
                        "pos": total_row["pos"],
                        "games": total_row["games"],
                        "wins": total_row["wins"],
                        "m": m,
                    }
                )
            hero_rows.append(total_row)

        hero_rows.sort(key=lambda r: (-r["games"], -r["series"], r["hero"]))
        rows_out = []
        for row in hero_rows:
            rows_out.append(row)
        # series evidence, only for this player
        ev = []
        for row in series.values():
            if row["player"] != player:
                continue
            ev.append(
                [
                    row["date"],
                    row["matchId"],
                    str(row["league"]),
                    row["stage"],
                    row["opponent"],
                    row["team"],
                    row["hero"],
                    row["games"],
                    row["wins"],
                    int(row["seriesWin"]),
                    round(row["m"]["kda"], 2),
                    rnd(row["m"]["dmg"], 1),
                    rnd(row["m"]["gold"], 1),
                    rnd(row["m"]["part"], 1),
                    round(row["m"]["surv"], 3),
                ]
            )
        ev.sort(key=lambda r: (r[0], r[1]), reverse=True)
        out_players[player] = {
            "name": player,
            "team": str(meta.get("team") or ""),
            "pos": str(meta.get("pos") or ""),
            "icon": str(meta.get("icon") or ""),
            "teamIcon": str(meta.get("teamIcon") or ""),
            "games": total_games,
            "series": len(total_series),
            "heroes": rows_out,
            "seriesRows": ev,
        }

    # 全局“选手×英雄”总池：用于“全部赛事”口径的基准
    total_groups = defaultdict(list)
    for row in total_pool_all:
        total_groups[(row["pos"], row["hero"])].append(row)
    for player, obj in out_players.items():
        for row in obj["heroes"]:
            group = total_groups.get((row["pos"], row["hero"])) or []
            target = next((r for r in group if r["_player"] == player), None)
            if target is not None:
                bench = bench_for(target, group)
                if bench:
                    bench["scope"] = "all-leagues"
                row["bench"] = bench

    # index + shards
    all_battles = {bid for row in series.values() for bid in row["battleIds"]}
    all_matches = {row["matchId"] for row in series.values()}
    all_dates = sorted(row["date"] for row in series.values() if row["date"])
    coverage = {
        "start": all_dates[0] if all_dates else "",
        "end": all_dates[-1] if all_dates else "",
        "players": 0,
        "games": len(all_battles),
        "series": len(all_matches),
        "leagues": len({str(row["league"]) for row in series.values()}),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("shard_*.js"):
        old.unlink()
    shards = [{} for _ in range(SHARDS)]
    index_players = []
    for player, obj in sorted(out_players.items(), key=lambda kv: -kv[1]["games"]):
        if obj["games"] < MIN_PLAYER_GAMES:
            continue
        shard = int(hashlib.md5(player.encode("utf-8")).hexdigest(), 16) % SHARDS
        shards[shard][player] = obj
        index_players.append(
            {
                "name": player,
                "team": obj["team"],
                "pos": obj["pos"],
                "games": obj["games"],
                "series": obj["series"],
                "heroes": len(obj["heroes"]),
                "shard": shard,
                "icon": obj["icon"],
                "teamIcon": obj["teamIcon"],
            }
        )

    for i, shard in enumerate(shards):
        body = "window.KPL_HERO_PERF_SHARD=" + json.dumps(shard, ensure_ascii=False, separators=(",", ":")) + ";\n"
        (OUT / f"shard_{i}.js").write_text(body, encoding="utf-8")

    coverage["players"] = len(index_players)
    index = {
        "generatedAt": datetime.now(CN).strftime("%Y-%m-%d %H:%M"),
        "coverage": coverage,
        "leagues": sorted(
            [
                {"id": str(k), "name": str(v.get("league_name") or k), "year": int(str(v.get("start_time") or "0")[:4] or 0)}
                for k, v in leagues.items()
            ],
            key=lambda x: (-x["year"], x["id"]),
        ),
        "players": index_players,
    }
    (OUT / "index.js").write_text(
        "window.KPL_HERO_PERF_INDEX=" + json.dumps(index, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    total_size = sum(p.stat().st_size for p in OUT.glob("*.js"))
    print(f"metric issues: {dict(metric_issues)}", flush=True)
    print(f"coverage: {coverage}", flush=True)
    print(f"players: {len(index_players)} | shards: {SHARDS} | size: {total_size/1024/1024:.1f} MB", flush=True)
    print(f"saved: {OUT}", flush=True)


if __name__ == "__main__":
    main()
