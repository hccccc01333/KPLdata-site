# -*- coding: utf-8 -*-
"""战队 BP 风格数据门禁。

检查 assets/team_bp/index.js 与 shard_*.js：
  - 索引 / 分片 / 战队集合一致，分片号正确；
  - 每个范围 5 选 + 5 禁 = 10 手，选用 / 禁用 / 对手动作能复算；
  - 英雄五状态互斥且不超过总局数，组合与证据可追溯；
  - 基准池的选用 / 禁用总数与局数一致，Lift 分母不为 0；
  - 胜率分位只对 ≥10 局战队计算。

用法：
    python check_team_bp.py              # 有 SEVERE → exit 1
    python check_team_bp.py --warn-only  # 只报告，不阻断

报告：../02-KPL实时胜率预测系统/reports/team_bp_quality.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
OUT = SITE / "assets" / "team_bp"
REPORT = SITE.parent / "02-KPL实时胜率预测系统" / "reports" / "team_bp_quality.json"
CN = timezone(timedelta(hours=8))
MIN_GAMES = 10
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_js(path: Path, var: str) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"window\." + re.escape(var) + r"\s*=\s*(\{.*\})\s*;?\s*$", text, re.S)
    if not m:
        raise ValueError(f"{path.name} 无法解析")
    return json.loads(m.group(1))


def is_num(v) -> bool:
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
    index = load_js(index_path, "KPL_TEAM_BP_INDEX")
    heroes = index.get("heroes") or []
    H = len(heroes)
    leagues = {str(x.get("id")): x for x in (index.get("leagues") or []) if isinstance(x, dict)}
    coverage = index.get("coverage") or {}
    baselines = index.get("baselines") or {}
    teams = index.get("teams") or []
    a.counts["heroes"] = H
    a.counts["leagues"] = len(leagues)
    a.counts["teams"] = len(teams)
    a.counts["coverageGames"] = coverage.get("games", 0)

    a.check(H > 0, "index.heroes", "heroes 为空")
    a.check(len(leagues) > 0, "index.leagues", "leagues 为空")
    a.check(bool(teams), "index.teams", "teams 为空")
    a.check(coverage.get("orderSupported") is False, "coverage.order", "BP 顺序未核验时必须关闭顺序分析")
    a.check(coverage.get("games", 0) > 0, "coverage.games", "coverage.games 为 0")
    a.check(coverage.get("teams10", 0) > 0, "coverage.teams10", "没有 ≥10 局战队")
    a.check(len(coverage.get("skipped") or {}) >= 0, "coverage.skipped", "缺少 skipped 统计")

    scope_ids = ["all"] + list(leagues)
    for scope in scope_ids:
        base = baselines.get(scope)
        a.check(isinstance(base, dict), "baseline.missing", f"缺少基准 {scope}")
        if not isinstance(base, dict):
            continue
        games = base.get("games", 0)
        a.check(is_num(games) and games > 0, "baseline.games", f"{scope} 基准局数为 0")
        a.check(base.get("picks") == games * 10, "baseline.picks", f"{scope} 选用总数 {base.get('picks')} != {games * 10}")
        a.check(base.get("bans") == games * 10, "baseline.bans", f"{scope} 禁用总数 {base.get('bans')} != {games * 10}")
        for key in ("pick", "pickWins", "ban"):
            arr = base.get(key)
            a.check(isinstance(arr, list) and len(arr) == H, "baseline.length", f"{scope}.{key} 长度不是 {H}")
            if isinstance(arr, list):
                a.check(all(is_num(x) and x >= 0 for x in arr), "baseline.value", f"{scope}.{key} 有非法值")
        if sum(base.get("pick") or []) != base.get("picks"):
            a.severe("baseline.pickSum", f"{scope} 英雄选用合计不等于总选用")
        if sum(base.get("ban") or []) != base.get("bans"):
            a.severe("baseline.banSum", f"{scope} 英雄禁用合计不等于总禁用")
        if any((base.get("pickWins") or [0]*H)[i] > (base.get("pick") or [0]*H)[i] for i in range(H)):
            a.severe("baseline.wins", f"{scope} 英雄胜场大于选用场次")
    all_base = baselines.get("all") or {}
    a.check(all_base.get("games") == coverage.get("games"), "baseline.coverageGames",
            "全部赛事基准局数与 coverage 不一致")
    a.check(sum((baselines.get(s) or {}).get("games", 0) for s in leagues) == coverage.get("games"),
            "baseline.leagueGames", "各赛事基准局数合计不等于全部局数")
    a.check(sum((baselines.get(s) or {}).get("picks", 0) for s in leagues) == all_base.get("picks"),
            "baseline.leaguePicks", "各赛事基准选用合计不等于全部选用")
    a.check(sum((baselines.get(s) or {}).get("bans", 0) for s in leagues) == all_base.get("bans"),
            "baseline.leagueBans", "各赛事基准禁用合计不等于全部禁用")
    a.check(coverage.get("teams10") == sum(1 for t in teams if (t.get("games") or 0) >= MIN_GAMES),
            "coverage.teams10", "coverage.teams10 与索引战队样本不一致")

    shard_files = sorted(OUT.glob("shard_*.js"))
    a.check(len(shard_files) == 8, "shard.count", f"分片数 {len(shard_files)}，应为 8")
    all_teams = set()
    index_by_name = {str(t.get("name")): t for t in teams}
    total_evidence = 0
    for path in shard_files:
        m = re.search(r"shard_(\d+)\.js$", path.name)
        if not m:
            a.severe("shard.name", f"分片文件名无法识别：{path.name}")
            continue
        shard_no = int(m.group(1))
        data = load_js(path, "KPL_TEAM_BP_SHARD")
        for name, obj in data.items():
            a.counts["loadedTeams"] += 1
            a.check(name not in all_teams, "shard.duplicate", f"战队重复：{name}")
            all_teams.add(name)
            meta = index_by_name.get(name)
            a.check(meta is not None, "shard.unknown", f"分片含索引外战队 {name}")
            if meta:
                a.check(meta.get("shard") == shard_no, "shard.number", f"{name} 分片号不一致")
                a.check(meta.get("games") == obj.get("games"), "shard.games", f"{name} 局数不一致")
            audit_team(a, name, obj, H, leagues, meta)
            total_evidence += len(obj.get("evidence") or [])

    a.check(all_teams == set(index_by_name), "shard.coverage",
            f"分片战队 {len(all_teams)} 与索引 {len(index_by_name)} 不一致")
    a.check(total_evidence == coverage.get("games", 0) * 2, "evidence.total",
            f"证据总数 {total_evidence} != 2 × {coverage.get('games')}")

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
    print(f"teams {len(teams)} | loaded {a.counts['loadedTeams']} | evidence {total_evidence} | heroes {H}", flush=True)
    print(f"coverage {coverage}", flush=True)
    print(f"SEVERE {len(a.errors)} | WARN {len(a.warnings)}", flush=True)
    for row in a.errors[:8]:
        print(f"  SEVERE [{row['code']}] {row['detail']}", flush=True)
    for row in a.warnings[:8]:
        print(f"  WARN   [{row['code']}] {row['detail']}", flush=True)
    print(f"report: {REPORT}", flush=True)
    if a.errors and not args.warn_only:
        raise SystemExit(1)


def audit_team(a: Audit, name: str, obj: dict, H: int, leagues: dict, meta: dict | None) -> None:
    games = obj.get("games")
    wins = obj.get("wins")
    a.counts["teamGames"] += int(games or 0)
    a.check(is_num(games) and games > 0, "team.games", f"{name} 局数异常")
    a.check(is_num(wins) and 0 <= wins <= games, "team.wins", f"{name} 胜负异常")
    scopes = obj.get("scopes") or {}
    a.check("all" in scopes, "team.all", f"{name} 缺少 all 范围")
    a.check(set(scopes) - {"all"} <= set(leagues), "team.scope", f"{name} 含未知赛事范围")
    if meta:
        a.check(set((meta.get("scopes") or {})) == set(scopes), "meta.scope", f"{name} 索引范围与数据不一致")
        a.check(set(meta.get("leagues") or []) == set(scopes) - {"all"}, "meta.leagues", f"{name} 赛事列表不一致")
    total_league_games = 0
    total_league_wins = 0
    for scope, st in scopes.items():
        g = st.get("games", 0)
        w = st.get("wins", 0)
        picks = st.get("picks", 0)
        bans = st.get("bans", 0)
        opp_bans = st.get("oppBans", 0)
        if scope != "all":
            total_league_games += g
            total_league_wins += w
        a.check(is_num(g) and g > 0, "scope.games", f"{name}/{scope} 局数为 0")
        a.check(is_num(w) and 0 <= w <= g, "scope.wins", f"{name}/{scope} 胜负异常")
        a.check(picks == g * 5, "scope.picks", f"{name}/{scope} 选用 {picks} != {g * 5}")
        a.check(bans == g * 5, "scope.bans", f"{name}/{scope} 禁用 {bans} != {g * 5}")
        a.check(opp_bans == g * 5, "scope.oppBans", f"{name}/{scope} 对手禁用 {opp_bans} != {g * 5}")
        rows = st.get("heroes") or []
        a.check(isinstance(rows, list) and rows, "scope.heroes", f"{name}/{scope} 没有英雄行")
        seen = set()
        sum_p = sum_pw = sum_b = sum_ob = sum_op = 0
        for r in rows:
            if not isinstance(r, list) or len(r) != 6:
                a.severe("scope.row", f"{name}/{scope} 英雄行字段数异常")
                continue
            i, p, pw, b, ob, op = r
            a.check(is_num(i) and 0 <= i < H, "scope.heroIndex", f"{name}/{scope} 英雄索引越界：{i}")
            a.check(i not in seen, "scope.heroDuplicate", f"{name}/{scope} 英雄重复：{i}")
            seen.add(i)
            for key, val in (("pick", p), ("pickWins", pw), ("ban", b), ("oppBan", ob), ("oppPick", op)):
                a.check(is_num(val) and val >= 0, "scope.metric", f"{name}/{scope}/{i} {key} 非法：{val}")
            a.check(pw <= p, "scope.pickWins", f"{name}/{scope}/{i} 选用胜场大于选用")
            a.check(p + b + ob + op <= g, "scope.states", f"{name}/{scope}/{i} 五状态超过局数")
            sum_p += p
            sum_pw += pw
            sum_b += b
            sum_ob += ob
            sum_op += op
        a.check(sum_p == picks, "scope.pickSum", f"{name}/{scope} 英雄选用合计 {sum_p} != {picks}")
        a.check(sum_b == bans, "scope.banSum", f"{name}/{scope} 英雄禁用合计 {sum_b} != {bans}")
        a.check(sum_ob == opp_bans, "scope.oppBanSum", f"{name}/{scope} 对手禁用合计 {sum_ob} != {opp_bans}")
        a.check(sum_op == g * 5, "scope.oppPickSum", f"{name}/{scope} 对手选用合计 {sum_op} != {g * 5}")
        a.check(sum_pw == w * 5, "scope.winPickSum", f"{name}/{scope} 选用胜场合计 {sum_pw} != 胜场×5")
        combos = st.get("combos") or []
        cseen = set()
        for c in combos:
            if not isinstance(c, list) or len(c) != 4:
                a.severe("combo.shape", f"{name}/{scope} 组合字段数异常")
                continue
            x, y, n, cw = c
            a.check(is_num(x) and is_num(y) and 0 <= x < H and 0 <= y < H and x < y,
                    "combo.index", f"{name}/{scope} 组合索引异常：{x},{y}")
            a.check(n >= 2 and n <= g, "combo.count", f"{name}/{scope} 组合次数异常：{n}")
            a.check(cw <= n, "combo.wins", f"{name}/{scope} 组合胜场大于次数")
            a.check((x, y) not in cseen, "combo.duplicate", f"{name}/{scope} 组合重复：{x},{y}")
            cseen.add((x, y))
        if meta:
            sm = (meta.get("scopes") or {}).get(scope) or {}
            a.check(sm.get("games") == g and sm.get("wins") == w, "meta.games", f"{name}/{scope} 索引局数/胜场不一致")
            a.check(isinstance(sm.get("wr"), (int, float)) and 0 <= sm["wr"] <= 100, "meta.wr", f"{name}/{scope} 胜率越界")
            a.check(sm.get("pct") is None or (is_num(sm.get("pct")) and 0 <= sm["pct"] <= 100),
                    "meta.pct", f"{name}/{scope} 分位越界")
            a.check(sm.get("rankN") == 0 or (is_num(sm.get("rankN")) and sm["rankN"] >= 2),
                    "meta.rankN", f"{name}/{scope} 分位样本异常")
            if g < MIN_GAMES:
                a.check(sm.get("pct") is None, "meta.smallPct", f"{name}/{scope} 小样本仍输出分位")
    a.check(total_league_games == games, "team.scopeGames", f"{name} 赛事局数合计 != 全部局数")
    a.check(total_league_wins == wins, "team.scopeWins", f"{name} 赛事胜场合计 != 全部胜场")

    ev = obj.get("evidence") or []
    a.check(len(ev) == games, "evidence.count", f"{name} 证据 {len(ev)} != 局数 {games}")
    for r in ev:
        if not isinstance(r, list) or len(r) != 11:
            a.severe("evidence.shape", f"{name} 证据字段数异常")
            continue
        date, match_id, lid, stage, opp, side, win, picks, bans, opp_picks, opp_bans = r
        a.check(bool(DATE_RE.match(str(date))), "evidence.date", f"{name} 证据日期非法：{date}")
        a.check(bool(match_id), "evidence.match", f"{name} 证据缺比赛")
        a.check(str(lid) in leagues, "evidence.league", f"{name} 证据未知赛事：{lid}")
        a.check(side in (1, 2), "evidence.side", f"{name} 阵营非法：{side}")
        a.check(win in (0, 1), "evidence.win", f"{name} 赛果非法：{win}")
        a.check(isinstance(picks, list) and len(picks) == 5, "evidence.picks", f"{name} 我方选用不是 5")
        a.check(isinstance(bans, list) and len(bans) == 5, "evidence.bans", f"{name} 我方禁用不是 5")
        a.check(isinstance(opp_picks, list) and len(opp_picks) == 5, "evidence.oppPicks", f"{name} 对手选用不是 5")
        a.check(isinstance(opp_bans, list) and len(opp_bans) == 5, "evidence.oppBans", f"{name} 对手禁用不是 5")
        all_hands = picks + bans + opp_picks + opp_bans
        a.check(len(set(all_hands)) == 20, "evidence.unique", f"{name} 证据 20 手不唯一")
        a.check(all(is_num(i) and 0 <= i < H for i in all_hands), "evidence.index", f"{name} 证据英雄索引越界")


if __name__ == "__main__":
    main()
