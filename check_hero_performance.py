# -*- coding: utf-8 -*-
"""英雄表现工作台数据门禁。

检查 assets/hero_perf/index.js 与 shard_*.js 的发布契约：
  - 索引、分片、选手集合一一对应，分片无缺失/重复；
  - 选手、英雄、联赛三层局数/系列赛/胜负能逐层复算；
  - 证据行的日期、比赛、英雄、联赛可追溯，且没有重复证据；
  - P50/P75/P90 百分位在 0–100，基准池达到最小样本，分位与基准线成对出现；
  - 缺失的伤害/经济不落成 0，参团率不超出 0–100。

用法：
    python check_hero_performance.py              # 有 SEVERE → exit 1
    python check_hero_performance.py --warn-only  # 只报告，不阻断

报告：../02-KPL实时胜率预测系统/reports/hero_performance_quality.json
"""

from __future__ import annotations

import argparse
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
OUT = SITE / "assets" / "hero_perf"
REPORT = SITE.parent / "02-KPL实时胜率预测系统" / "reports" / "hero_performance_quality.json"
CN = timezone(timedelta(hours=8))
P_KEYS = ("kda", "dmg", "gold", "part", "surv")
MIN_PLAYER_GAMES = 20
MIN_POOL_PLAYERS = 3
MIN_POOL_GAMES = 20
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_js(path: Path, var: str) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"window\." + re.escape(var) + r"\s*=\s*(\{.*\})\s*;?\s*$", text, re.S)
    if not m:
        raise ValueError(f"{path.name} 无法解析")
    return json.loads(m.group(1))


def num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


class Audit:
    def __init__(self) -> None:
        self.errors: list[dict] = []
        self.warnings: list[dict] = []
        self.counts = Counter()

    def severe(self, code: str, detail: str, **extra) -> None:
        self.errors.append({"code": code, "detail": detail, **extra})

    def warn(self, code: str, detail: str, **extra) -> None:
        self.warnings.append({"code": code, "detail": detail, **extra})

    def check(self, cond: bool, code: str, detail: str, **extra) -> None:
        if not cond:
            self.severe(code, detail, **extra)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warn-only", action="store_true")
    args = ap.parse_args()

    a = Audit()
    index_path = OUT / "index.js"
    if not index_path.exists():
        raise SystemExit(f"缺少 {index_path}")
    index = load_js(index_path, "KPL_HERO_PERF_INDEX")
    players = index.get("players") or []
    leagues = {str(x.get("id")): x for x in (index.get("leagues") or []) if isinstance(x, dict)}
    coverage = index.get("coverage") or {}
    a.counts["players"] = len(players)
    a.counts["leagues"] = len(leagues)
    a.counts["coverageGames"] = coverage.get("games", 0)
    a.counts["coverageSeries"] = coverage.get("series", 0)

    a.check(bool(players), "index.empty", "index.players 为空")
    a.check(coverage.get("players") == len(players), "coverage.players", "coverage.players 与索引选手数不一致")
    a.check(bool(coverage.get("start")) and bool(coverage.get("end")), "coverage.dates", "coverage 缺少起止日期")
    a.check(coverage.get("games", 0) > 0 and coverage.get("series", 0) > 0, "coverage.sample", "coverage 局数/系列赛为 0")

    by_name = {}
    for p in players:
        name = str(p.get("name") or "")
        a.check(bool(name), "index.playerName", "选手名为空")
        a.check(name not in by_name, "index.duplicatePlayer", f"选手重复：{name}")
        by_name[name] = p
        a.check(isinstance(p.get("games"), int) and p["games"] >= MIN_PLAYER_GAMES,
                "index.playerGames", f"{name} 低于 {MIN_PLAYER_GAMES} 局")
        a.check(isinstance(p.get("shard"), int) and 0 <= p["shard"] < 16,
                "index.shard", f"{name} 分片号越界：{p.get('shard')}")
        a.check(isinstance(p.get("heroes"), int) and p["heroes"] > 0,
                "index.heroes", f"{name} 英雄数为 0")

    shard_players = set()
    shard_files = sorted(OUT.glob("shard_*.js"))
    a.check(len(shard_files) == 16, "shard.count", f"分片数 {len(shard_files)}，应为 16")
    for path in shard_files:
        m = re.search(r"shard_(\d+)\.js$", path.name)
        if not m:
            a.severe("shard.name", f"无法识别分片文件名：{path.name}")
            continue
        shard_no = int(m.group(1))
        a.check(0 <= shard_no < 16, "shard.number", f"分片号越界：{shard_no}")
        data = load_js(path, "KPL_HERO_PERF_SHARD")
        a.check(isinstance(data, dict), "shard.shape", f"{path.name} 不是对象")
        for name, obj in data.items():
            a.counts["loadedPlayers"] += 1
            a.check(name not in shard_players, "shard.duplicate", f"{name} 出现在多个分片")
            shard_players.add(name)
            meta = by_name.get(name)
            a.check(meta is not None, "shard.unknownPlayer", f"{path.name} 含索引外选手 {name}")
            if meta:
                a.check(meta.get("shard") == shard_no, "shard.mismatch",
                        f"{name} 索引分片 {meta.get('shard')} != {shard_no}")
                a.check(meta.get("games") == obj.get("games"), "shard.games",
                        f"{name} 索引局数 {meta.get('games')} != 数据 {obj.get('games')}")
                a.check(meta.get("heroes") == len(obj.get("heroes") or []), "shard.heroCount",
                        f"{name} 索引英雄数与数据不一致")
            audit_player(a, name, obj, leagues)

    a.check(shard_players == set(by_name), "shard.coverage",
            f"分片选手 {len(shard_players)} 与索引 {len(by_name)} 不一致")

    report = {
        "generatedAt": datetime.now(CN).strftime("%Y-%m-%d %H:%M:%S"),
        "generatedFrom": str(OUT),
        "counts": dict(a.counts),
        "coverage": coverage,
        "severe": a.errors,
        "warnings": a.warnings,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"players {a.counts['players']} | loaded {a.counts['loadedPlayers']} | "
        f"hero rows {a.counts['heroRows']} | evidence {a.counts['evidenceRows']} | "
        f"bench {a.counts['benchRows']} | P {a.counts['pValues']}",
        flush=True,
    )
    print(f"coverage {coverage}", flush=True)
    print(f"SEVERE {len(a.errors)} | WARN {len(a.warnings)}", flush=True)
    for row in a.errors[:8]:
        print(f"  SEVERE [{row['code']}] {row['detail']}", flush=True)
    for row in a.warnings[:8]:
        print(f"  WARN   [{row['code']}] {row['detail']}", flush=True)
    print(f"report: {REPORT}", flush=True)
    if a.errors and not args.warn_only:
        raise SystemExit(1)


def audit_player(a: Audit, name: str, obj: dict, leagues: dict) -> None:
    heroes = obj.get("heroes") or []
    evidence = obj.get("seriesRows") or []
    a.check(isinstance(heroes, list) and heroes, "player.heroes", f"{name} 没有英雄行")
    a.check(isinstance(evidence, list) and evidence, "player.evidence", f"{name} 没有证据行")
    a.check(num(obj.get("games")) and obj["games"] >= MIN_PLAYER_GAMES, "player.games", f"{name} 局数异常")
    a.check(isinstance(obj.get("series"), int) and obj["series"] >= 1, "player.series", f"{name} 系列赛数异常")

    hero_games = sum(int(h.get("games") or 0) for h in heroes)
    a.check(hero_games == obj.get("games"), "player.gamesSum",
            f"{name} 英雄局数合计 {hero_games} != 选手局数 {obj.get('games')}")
    ev_games = sum(int(r[7] or 0) for r in evidence if isinstance(r, list) and len(r) == 15)
    a.check(ev_games == obj.get("games"), "player.evidenceGames",
            f"{name} 证据局数合计 {ev_games} != 选手局数 {obj.get('games')}")

    match_ids = set()
    ev_keys = set()
    hero_names = set()
    for i, h in enumerate(heroes):
        a.counts["heroRows"] += 1
        hero = str(h.get("hero") or "")
        hero_names.add(hero)
        a.check(bool(hero), "hero.name", f"{name} 第 {i + 1} 个英雄名为空")
        a.check(num(h.get("series")) and h["series"] >= 1, "hero.series", f"{name}/{hero} 系列赛数异常")
        a.check(num(h.get("games")) and h["games"] >= 1, "hero.games", f"{name}/{hero} 局数异常")
        a.check(num(h.get("wins")) and 0 <= h["wins"] <= h["games"], "hero.wins",
                f"{name}/{hero} 胜负与局数不一致")
        a.check(num(h.get("wr")) and 0 <= h["wr"] <= 100, "hero.wr", f"{name}/{hero} 胜率越界")
        for key in ("kda", "dmgMin", "goldMin", "part", "deathsMin"):
            v = h.get(key)
            a.check(v is None or (num(v) and v >= 0), "hero.metric", f"{name}/{hero} {key} 非法：{v}")
        if h.get("part") is not None:
            a.check(0 <= h["part"] <= 100, "hero.part", f"{name}/{hero} 参团率越界：{h['part']}")

        league_rows = h.get("leagues") or []
        a.check(isinstance(league_rows, list) and league_rows, "hero.leagues", f"{name}/{hero} 没有赛事行")
        seen_leagues = set()
        league_games = league_series = league_wins = 0
        for lr in league_rows:
            lid = str(lr.get("league") or "")
            a.check(lid in leagues, "league.unknown", f"{name}/{hero} 未知赛事 {lid}")
            a.check(lid not in seen_leagues, "league.duplicate", f"{name}/{hero} 赛事重复 {lid}")
            seen_leagues.add(lid)
            league_games += int(lr.get("games") or 0)
            league_series += int(lr.get("series") or 0)
            league_wins += int(lr.get("wins") or 0)
            a.check(num(lr.get("series")) and lr["series"] >= 1, "league.series",
                    f"{name}/{hero}/{lid} 系列赛数异常")
            a.check(num(lr.get("games")) and lr["games"] >= 1, "league.games",
                    f"{name}/{hero}/{lid} 局数异常")
            a.check(num(lr.get("wins")) and 0 <= lr["wins"] <= lr["games"], "league.wins",
                    f"{name}/{hero}/{lid} 胜负与局数不一致")
            a.check(num(lr.get("wr")) and 0 <= lr["wr"] <= 100, "league.wr",
                    f"{name}/{hero}/{lid} 胜率越界")
            for key in ("kda", "dmgMin", "goldMin", "part", "deathsMin"):
                v = lr.get(key)
                a.check(v is None or (num(v) and v >= 0), "league.metric",
                        f"{name}/{hero}/{lid} {key} 非法：{v}")
            if lr.get("part") is not None:
                a.check(0 <= lr["part"] <= 100, "league.part",
                        f"{name}/{hero}/{lid} 参团率越界：{lr['part']}")
            audit_bench(a, f"{name}/{hero}/{lid}", lr.get("bench"), total_row=False)
        a.check(league_games == h["games"], "hero.gamesSum",
                f"{name}/{hero} 赛事局数 {league_games} != 英雄局数 {h['games']}")
        a.check(league_series == h["series"], "hero.seriesSum",
                f"{name}/{hero} 赛事系列赛 {league_series} != 英雄系列赛 {h['series']}")
        a.check(league_wins == h["wins"], "hero.winsSum",
                f"{name}/{hero} 赛事胜场 {league_wins} != 英雄胜场 {h['wins']}")
        audit_bench(a, f"{name}/{hero}", h.get("bench"), total_row=True)

    for r in evidence:
        a.counts["evidenceRows"] += 1
        if not isinstance(r, list) or len(r) != 15:
            a.severe("evidence.shape", f"{name} 证据行字段数不是 15")
            continue
        date, match_id, league, stage, opponent, team, hero, games, wins, series_win, kda, dmg, gold, part, surv = r
        a.check(bool(DATE_RE.match(str(date))), "evidence.date", f"{name} 证据日期非法：{date}")
        a.check(bool(match_id), "evidence.match", f"{name} 证据缺比赛 ID")
        a.check(str(league) in leagues, "evidence.league", f"{name} 证据未知赛事：{league}")
        a.check(hero in hero_names, "evidence.hero", f"{name} 证据英雄不在英雄行：{hero}")
        a.check(num(games) and games >= 1, "evidence.games", f"{name} 证据局数异常：{games}")
        a.check(num(wins) and 0 <= wins <= games, "evidence.wins", f"{name} 证据胜负异常：{wins}/{games}")
        a.check(series_win in (0, 1), "evidence.seriesWin", f"{name} 系列赛胜负非 0/1：{series_win}")
        a.check(dmg is None or (num(dmg) and dmg >= 0), "evidence.dmg", f"{name} 证据伤害非法：{dmg}")
        a.check(gold is None or (num(gold) and gold >= 0), "evidence.gold", f"{name} 证据经济非法：{gold}")
        a.check(part is None or (num(part) and 0 <= part <= 100), "evidence.part", f"{name} 证据参团率非法：{part}")
        match_ids.add(str(match_id))
        key = (str(match_id), str(hero))
        a.check(key not in ev_keys, "evidence.duplicate", f"{name} 重复证据 {key}")
        ev_keys.add(key)

    a.check(len(match_ids) == obj.get("series"), "player.seriesSum",
            f"{name} 证据比赛数 {len(match_ids)} != 选手系列赛 {obj.get('series')}")


def audit_bench(a: Audit, label: str, bench, total_row: bool) -> None:
    if bench is None:
        a.counts["benchMissing"] += 1
        return
    a.counts["benchRows"] += 1
    scope = bench.get("scope")
    allowed = {"all-leagues"} if total_row else {"same-league", "all-leagues"}
    a.check(scope in allowed, "bench.scope", f"{label} 基准范围非法：{scope}")
    a.check(num(bench.get("poolPlayers")) and bench["poolPlayers"] >= MIN_POOL_PLAYERS,
            "bench.players", f"{label} 基准人数 {bench.get('poolPlayers')} < {MIN_POOL_PLAYERS}")
    a.check(num(bench.get("poolGames")) and bench["poolGames"] >= MIN_POOL_GAMES,
            "bench.games", f"{label} 基准局数 {bench.get('poolGames')} < {MIN_POOL_GAMES}")
    a.check(num(bench.get("leagueWr")) and 0 <= bench["leagueWr"] <= 100,
            "bench.leagueWr", f"{label} 同英雄胜率越界：{bench.get('leagueWr')}")
    p = bench.get("p") or {}
    ref = bench.get("ref") or {}
    for key in P_KEYS:
        pv = p.get(key)
        rv = ref.get(key)
        if pv is not None:
            a.counts["pValues"] += 1
            a.check(num(pv) and 0 <= pv <= 100, "bench.p", f"{label}/{key} 分位越界：{pv}")
            a.check(rv is not None, "bench.pair", f"{label}/{key} 有分位但无基准线")
        if rv is not None:
            a.check(isinstance(rv, list) and len(rv) == 3 and all(num(x) for x in rv),
                    "bench.ref", f"{label}/{key} 基准线非法：{rv}")
            if isinstance(rv, list) and len(rv) == 3 and all(num(x) for x in rv):
                a.check(rv[0] <= rv[1] <= rv[2], "bench.refOrder",
                        f"{label}/{key} P50/P75/P90 未递增：{rv}")


if __name__ == "__main__":
    main()
