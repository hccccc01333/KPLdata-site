# -*- coding: utf-8 -*-
"""系列赛一致性门禁：用原始逐局数据独立复算，校验 assets/deep.js 是否可信。

检查三件事：
  1. 原始数据层：每局胜方必须落回本局 camp 队名；完整系列赛的逐局比分必须与官方大场比分一致；
  2. 聚合层：deep.js 的系列赛/战队/选手胜负必须与独立复算完全一致；
  3. 覆盖层：换边、官方兜底、重复局号、串场小局等异常必须被显式统计，而不是静默算错。

任何 SEVERE 都以退出码 1 结束（可接入发布门禁）；--warn-only 只报告不阻断。
报告：../02-KPL实时胜率预测系统/reports/series_quality_report.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
DEEP = SITE / "assets" / "deep.js"
PLAYER_DEEP = SITE / "assets" / "player_deep.js"
REPORT = PROJ / "reports" / "series_quality_report.json"
CN = timezone(timedelta(hours=8))


def int0(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def team_of(obj: dict, camp: int) -> str:
    data = obj.get(f"camp{camp}")
    if not isinstance(data, dict):
        return ""
    name = str(data.get("team_name") or "").strip()
    return "" if name in ("", "待定") else name


def winner_of(battle: dict) -> str:
    wc = int0(battle.get("win_camp"))
    return team_of(battle, wc) if wc in (1, 2) else ""


def battle_ts(battle: dict) -> int:
    tail = str(battle.get("battle_id") or "").rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def load_asset(path: Path, var: str):
    if not path.exists():
        return None
    txt = path.read_text(encoding="utf-8").strip()
    for pre in (f"window.{var} =", f"window.{var}=", f"{var} =", f"{var}="):
        if txt.startswith(pre):
            txt = txt[len(pre):].strip()
            break
    if txt.endswith(";"):
        txt = txt[:-1]
    return json.loads(txt)


class Report:
    def __init__(self):
        self.issues: list[dict] = []
        self.counts = Counter()

    def add(self, severity: str, rule: str, detail: str, sample=None):
        self.issues.append({"severity": severity, "rule": rule, "detail": detail,
                            "sample": sample or []})
        self.counts[severity] += 1

    def severe(self, rule, detail, sample=None):
        self.add("SEVERE", rule, detail, sample)

    def warn(self, rule, detail, sample=None):
        self.add("WARN", rule, detail, sample)


def audit_history(rep: Report) -> dict:
    teams = defaultdict(lambda: {
        "seriesN": 0, "seriesW": 0, "gameN": 0, "gameW": 0,
        "fgN": 0, "fgW": 0, "decN": 0, "decW": 0, "cbN": 0, "cbW": 0,
        "rsN": 0, "rsW": 0, "bo": defaultdict(lambda: {"n": 0, "w": 0}),
        "form": [], "series": [],
    })
    players = defaultdict(lambda: {
        "g": 0, "w": 0, "decN": 0, "decW": 0,
        "k": 0, "d": 0, "a": 0, "dmg": 0.0, "dmgN": 0,
        "decK": 0, "decD": 0, "decA": 0, "decDmg": 0.0, "decDmgN": 0,
    })
    by_bo = defaultdict(lambda: {
        "n": 0, "firstN": 0, "firstW": 0, "distance": 0,
        "complete": 0, "games": Counter(),
    })
    rows = []            # 供按时间排序的表单
    reverse = []
    matches = battles = 0
    fallback = side_switch = unresolved = 0
    cross_team = duplicate_seq = 0
    official_conflict = 0
    files_scanned = 0

    for f in sorted(HIST.glob("*/matches/*.json")):
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            rep.warn("历史文件不可解析", f"{f.name} 读取失败")
            continue
        m = obj.get("match") if isinstance(obj, dict) else None
        if not isinstance(m, dict):
            continue
        raw = [b for b in (obj.get("battles") or [])
               if isinstance(b, dict) and int0(b.get("win_camp")) in (1, 2)]
        if not raw:
            continue
        files_scanned += 1

        official_teams = {team_of(m, 1), team_of(m, 2)} - {""}
        if len(official_teams) != 2:
            official_teams = set()

        candidates = []
        for b in raw:
            ts = {team_of(b, 1), team_of(b, 2)}
            if len(ts) != 2:
                cross_team += 1
                continue
            if official_teams and ts != official_teams:
                cross_team += 1
                continue
            wc = int0(b.get("win_camp"))
            if team_of(b, wc) not in ts:
                cross_team += 1
                continue
            candidates.append(b)

        candidates.sort(key=lambda b: (
            int0(b.get("battle_seq")), battle_ts(b), -len(b.get("battle_player_list") or []),
        ))
        bs, seen_bid, seen_seq = [], set(), set()
        for b in candidates:
            bid = str(b.get("battle_id") or "")
            if bid:
                if bid in seen_bid:
                    continue
                seen_bid.add(bid)
            seq = int0(b.get("battle_seq"))
            if seq in seen_seq:
                duplicate_seq += 1
            seen_seq.add(seq)
            bs.append(b)
        if not bs:
            unresolved += 1
            continue

        t1, t2 = team_of(bs[0], 1), team_of(bs[0], 2)
        if not t1 or not t2 or t1 == t2:
            unresolved += 1
            continue
        allowed = {t1, t2}
        bs = [b for b in bs if {team_of(b, 1), team_of(b, 2)} == allowed]
        if not bs:
            unresolved += 1
            continue

        winners = [winner_of(b) for b in bs]
        wins = Counter(w for w in winners if w in allowed)
        bo = int0(m.get("bo")) or max(1, 2 * len(bs) - 1)
        need = bo // 2 + 1
        complete = max(wins.values()) == need
        battle_score = (wins[t1], wins[t2])

        mw = int0(m.get("win_camp"))
        official_winner = team_of(m, mw) if mw in (1, 2) else ""
        if official_winner not in allowed:
            official_winner = ""
        official_score = None
        if official_winner:
            s1 = int0((m.get("camp1") or {}).get("score"))
            s2 = int0((m.get("camp2") or {}).get("score"))
            if s1 + s2 > 0:
                by_team = {team_of(m, 1): s1, team_of(m, 2): s2}
                official_score = (by_team.get(t1, 0), by_team.get(t2, 0))

        decisive = (
            complete and len(bs) >= 3
            and ((battle_score[0] == need and battle_score[1] == need - 1)
                 or (battle_score[1] == need and battle_score[0] == need - 1))
        )

        # 局级与选手级统计不依赖大场是否可结算：只要有逐局胜方就照实计入。
        battles += len(bs)
        if any(team_of(b, 1) != t1 for b in bs):
            side_switch += 1
        for bw in winners:
            if bw not in allowed:
                continue
            other = t2 if bw == t1 else t1
            teams[bw]["gameN"] += 1; teams[bw]["gameW"] += 1
            teams[other]["gameN"] += 1
        for i, bt in enumerate(bs):
            is_dec = decisive and i == len(bs) - 1
            bw = winners[i]
            if bw not in allowed:
                continue
            for p in bt.get("battle_player_list") or []:
                if not isinstance(p, dict):
                    continue
                name = str(p.get("player_name") or p.get("actual_player_name") or "").strip()
                camp = int0(p.get("camp"))
                if not name or camp not in (1, 2):
                    continue
                team = str(p.get("team_name") or "").strip() or team_of(bt, camp)
                if team not in allowed:
                    continue
                won = 1 if team == bw else 0
                k = int0(p.get("kill_num")); d = int0(p.get("death_num")); a = int0(p.get("assist_num"))
                rec = players[name]
                rec["g"] += 1; rec["w"] += won
                rec["k"] += k; rec["d"] += d; rec["a"] += a
                dv = p.get("hurt_total_rate")
                if dv not in (None, ""):
                    try:
                        dmg = float(dv) * 100
                    except (TypeError, ValueError):
                        dmg = None
                    if dmg is not None:
                        rec["dmg"] += dmg; rec["dmgN"] += 1
                if is_dec:
                    rec["decN"] += 1; rec["decW"] += won
                    rec["decK"] += k; rec["decD"] += d; rec["decA"] += a
                    if dv not in (None, ""):
                        try:
                            ddm = float(dv) * 100
                        except (TypeError, ValueError):
                            ddm = None
                        if ddm is not None:
                            rec["decDmg"] += ddm; rec["decDmgN"] += 1

        if complete:
            winner = t1 if wins[t1] == need else t2
            loser = t2 if winner == t1 else t1
            score = battle_score
            source = "battles"
            if official_winner and official_winner != winner:
                official_conflict += 1
                rep.severe("逐局胜方与官方大场胜方冲突",
                           f"{f.name}：逐局 {winner} / 官方 {official_winner}", [str(m.get("match_id") or f.stem)])
            if official_score is not None and official_score != battle_score:
                official_conflict += 1
                rep.severe("逐局比分与官方大场比分冲突",
                           f"{f.name}：逐局 {battle_score} / 官方 {official_score}", [str(m.get("match_id") or f.stem)])
        elif official_winner:
            winner = official_winner
            loser = t2 if winner == t1 else t1
            score = official_score if official_score is not None else battle_score
            source = "official"
            fallback += 1
        else:
            unresolved += 1
            continue

        matches += 1
        tw, tl = teams[winner], teams[loser]
        tw["seriesN"] += 1; tw["seriesW"] += 1
        tl["seriesN"] += 1
        tw["bo"][bo]["n"] += 1; tw["bo"][bo]["w"] += 1
        tl["bo"][bo]["n"] += 1

        first = winners[0] if winners else ""
        if first in allowed:
            other = t2 if first == t1 else t1
            teams[first]["fgN"] += 1
            by_bo[bo]["firstN"] += 1
            if first == winner:
                teams[first]["fgW"] += 1
                by_bo[bo]["firstW"] += 1
            teams[other]["cbN"] += 1
            if other == winner:
                teams[other]["cbW"] += 1

        if decisive:
            tw["decN"] += 1; tw["decW"] += 1
            tl["decN"] += 1
            by_bo[bo]["distance"] += 1

        rev_sweep = (
            complete and bo >= 5 and len(winners) >= 3
            and winners[0] == winners[1] and winner != winners[0]
        )
        if complete and bo >= 5 and len(winners) >= 3 and winners[0] == winners[1]:
            front = winners[0]
            behind = t2 if front == t1 else t1
            teams[behind]["rsN"] += 1
            if behind == winner:
                teams[behind]["rsW"] += 1
        if rev_sweep:
            w_games, l_games = score if winner == t1 else (score[1], score[0])
            reverse.append({
                "mid": str(m.get("match_id") or f.stem),
                "date": str(m.get("start_time") or "")[:10],
                "t1": t1, "t2": t2, "winner": winner,
                "score": f"{w_games}:{l_games}", "bo": bo,
            })

        by_bo[bo]["n"] += 1
        if complete:
            by_bo[bo]["complete"] += 1
            by_bo[bo]["games"][score[0] + score[1]] += 1

        rows.append((str(m.get("start_time") or ""), str(m.get("match_id") or f.stem), winner, loser))

    rows.sort(key=lambda x: (x[0], x[1]))
    for _date, _mid, winner, loser in rows:
        teams[winner]["series"].append("W")
        teams[loser]["series"].append("L")

    expected_teams = {}
    for name, t in teams.items():
        expected_teams[name] = {
            "seriesN": t["seriesN"], "seriesW": t["seriesW"],
            "gameN": t["gameN"], "gameW": t["gameW"],
            "fgN": t["fgN"], "fgW": t["fgW"],
            "decN": t["decN"], "decW": t["decW"],
            "cbN": t["cbN"], "cbW": t["cbW"],
            "rsN": t["rsN"], "rsW": t["rsW"],
            "bo5": dict(t["bo"].get(5, {"n": 0, "w": 0})),
            "bo7": dict(t["bo"].get(7, {"n": 0, "w": 0})),
            "form": "".join(t["series"][-10:]),
        }

    expected_players = {}
    for name, p in players.items():
        if p["g"] < 40:
            continue
        expected_players[name] = {
            "g": p["g"], "w": p["w"], "decN": p["decN"], "decW": p["decW"],
            "kda": round((p["k"] + p["a"]) / max(1, p["d"]), 2),
            "dmg": round(p["dmg"] / p["dmgN"], 1) if p["dmgN"] else None,
            "decKda": round((p["decK"] + p["decA"]) / max(1, p["decD"]), 2) if p["decN"] else None,
            "decDmg": round(p["decDmg"] / p["decDmgN"], 1) if p["decDmgN"] else None,
        }

    expected_by_bo = {}
    for bo, r in by_bo.items():
        n = r["n"]
        first_conv = r["firstW"] / r["firstN"] if r["firstN"] else 0.0
        expected_by_bo[bo] = {
            "n": n,
            "firstConv": round(first_conv, 3),
            "comeback": round(1.0 - first_conv, 3),
            "distance": round(r["distance"] / n, 3) if n else 0,
            "avgGames": round(sum(k * v for k, v in r["games"].items()) / r["complete"], 2) if r["complete"] else 0,
            "dist": {str(k): v for k, v in sorted(r["games"].items())},
        }

    reverse.sort(key=lambda x: x["date"], reverse=True)
    return {
        "filesScanned": files_scanned,
        "matches": matches,
        "battles": battles,
        "sideSwitchSeries": side_switch,
        "officialFallback": fallback,
        "officialConflicts": official_conflict,
        "unresolved": unresolved,
        "crossTeamBattles": cross_team,
        "duplicateSeq": duplicate_seq,
        "teams": expected_teams,
        "players": expected_players,
        "byBo": expected_by_bo,
        "reverseSweeps": reverse,
    }


def compare_deep(rep: Report, exp: dict, deep: dict) -> None:
    if not isinstance(deep, dict):
        rep.severe("deep.js 不可解析", "assets/deep.js 不是有效的 KPL_DEEP 对象")
        return
    if deep.get("matches") != exp["matches"]:
        rep.severe("系列赛总数不一致", f"deep.js={deep.get('matches')} / 复算={exp['matches']}")
    if deep.get("battles") != exp["battles"]:
        rep.severe("小局总数不一致", f"deep.js={deep.get('battles')} / 复算={exp['battles']}")

    cov = deep.get("coverage") or {}
    for key, want in (("resolvedSeries", exp["matches"]), ("officialFallback", exp["officialFallback"]),
                      ("unresolved", exp["unresolved"]), ("sideSwitchSeries", exp["sideSwitchSeries"]),
                      ("battles", exp["battles"])):
        if cov.get(key) != want:
            rep.severe("覆盖率字段不一致", f"coverage.{key}: deep.js={cov.get(key)} / 复算={want}")

    # ---- 战队 ----
    got_teams = deep.get("teams") or {}
    exp_teams = exp["teams"]
    for name in sorted(set(exp_teams) - set(got_teams)):
        rep.severe("deep.js 缺少战队", f"战队 {name} 在复算中存在但 deep.js 缺失")
    for name in sorted(set(got_teams) - set(exp_teams)):
        rep.severe("deep.js 多出战队", f"战队 {name} 在复算中不存在")
    fields = ("seriesN", "seriesW", "gameN", "gameW", "fgN", "fgW",
              "decN", "decW", "cbN", "cbW", "rsN", "rsW", "form")
    for name in sorted(set(exp_teams) & set(got_teams)):
        for f in fields:
            if got_teams[name].get(f) != exp_teams[name][f]:
                rep.severe("战队战绩不一致",
                           f"{name}.{f}: deep.js={got_teams[name].get(f)} / 复算={exp_teams[name][f]}")
        for f in ("bo5", "bo7"):
            if (got_teams[name].get(f) or {}) != exp_teams[name][f]:
                rep.severe("战队 BO 战绩不一致",
                           f"{name}.{f}: deep.js={got_teams[name].get(f)} / 复算={exp_teams[name][f]}")

    # ---- 选手 ----
    got_players = deep.get("players") or {}
    exp_players = exp["players"]
    for name in sorted(set(exp_players) - set(got_players)):
        rep.severe("deep.js 缺少选手", f"选手 {name} 在复算中存在但 deep.js 缺失")
    for name in sorted(set(got_players) - set(exp_players)):
        rep.severe("deep.js 多出选手", f"选手 {name} 的出场数不足门槛或不存在")
    for name in sorted(set(exp_players) & set(got_players)):
        a, b = got_players[name], exp_players[name]
        for f in ("g", "w", "decN", "decW"):
            if a.get(f) != b[f]:
                rep.severe("选手胜负不一致",
                           f"{name}.{f}: deep.js={a.get(f)} / 复算={b[f]}")
        for f, tol in (("kda", 0.011), ("dmg", 0.11), ("decKda", 0.011), ("decDmg", 0.11)):
            av, bv = a.get(f), b[f]
            if av is None or bv is None:
                if av != bv:
                    rep.severe("选手指标缺失不一致", f"{name}.{f}: deep.js={av} / 复算={bv}")
            elif abs(av - bv) > tol:
                rep.severe("选手指标不一致", f"{name}.{f}: deep.js={av} / 复算={bv}")

    # ---- 系列赛规律 ----
    got_bo = {r.get("bo"): r for r in ((deep.get("series") or {}).get("byBo") or [])}
    for bo, want in sorted(exp["byBo"].items()):
        row = got_bo.get(bo)
        if row is None:
            rep.severe("byBo 缺少分项", f"BO{bo} 在 deep.js 中缺失")
            continue
        for f, tol in (("n", 0), ("firstConv", 0.0015), ("comeback", 0.0015),
                       ("distance", 0.0015), ("avgGames", 0.011)):
            val = row.get(f)
            if val is None or abs(val - want[f]) > tol:
                rep.severe("byBo 指标不一致", f"BO{bo}.{f}: deep.js={val} / 复算={want[f]}")
        if (row.get("dist") or {}) != want["dist"]:
            rep.severe("byBo 局数分布不一致", f"BO{bo}.dist: deep.js={row.get('dist')} / 复算={want['dist']}")

    got_rev = ((deep.get("series") or {}).get("reverseSweeps") or [])
    want_rev = exp["reverseSweeps"][:40]
    if len(got_rev) != len(want_rev):
        rep.severe("让二追三列表长度不一致", f"deep.js={len(got_rev)} / 复算={len(want_rev)}")
    for i, (a, b) in enumerate(zip(got_rev, want_rev)):
        for f in ("mid", "winner", "score", "bo"):
            if a.get(f) != b[f]:
                rep.severe("让二追三记录不一致",
                           f"第 {i + 1} 条.{f}: deep.js={a.get(f)} / 复算={b[f]}")


def compare_player_deep(rep: Report, exp: dict) -> None:
    """player_deep.js 尚未修复时只告警，不阻断系列赛门禁。"""
    try:
        pd = load_asset(PLAYER_DEEP, "KPL_PLAYER_DEEP")
    except Exception as e:
        rep.warn("player_deep.js 不可解析", str(e))
        return
    if not isinstance(pd, dict):
        return
    got = pd.get("players") or {}
    bad = []
    for name, row in got.items():
        want = exp["players"].get(name)
        if not want:
            continue
        if row.get("g") != want["g"] or row.get("w") != want["w"]:
            bad.append((name, row.get("g"), want["g"], row.get("w"), want["w"]))
    if bad:
        rep.warn("player_deep 仍按阵营累计逐局胜负",
                 f"player_deep.js 有 {len(bad)} 名选手的 g/w 与逐局战队口径不一致（等待选手侧修复）",
                 [f"{x[0]} g {x[1]}→{x[2]} w {x[3]}→{x[4]}" for x in bad[:8]])


def main() -> int:
    warn_only = "--warn-only" in sys.argv
    rep = Report()

    exp = audit_history(rep)
    if exp["crossTeamBattles"]:
        rep.warn("原始数据含串场小局", f"已剔除 {exp['crossTeamBattles']} 局队名不属于该大场的小局")
    if exp["duplicateSeq"]:
        rep.warn("原始数据含重复局号", f"{exp['duplicateSeq']} 局出现重复 battle_seq（已按 battle_id 保留并继续统计）")
    if exp["unresolved"]:
        rep.warn("无法结算的系列赛", f"{exp['unresolved']} 个系列赛缺少逐局胜方或官方胜负，未计入 deep.js")
    if exp["officialFallback"]:
        rep.warn("系列赛使用官方兜底", f"{exp['officialFallback']} 个系列赛逐局不完整，胜方采用官方大场结果")
    try:
        deep = load_asset(DEEP, "KPL_DEEP")
    except Exception as e:
        rep.severe("deep.js 不可解析", str(e))
        deep = None
    if deep is None:
        rep.severe("deep.js 缺失", "请先运行 build_deep_data.py")
    else:
        compare_deep(rep, exp, deep)
    compare_player_deep(rep, exp)

    report = {
        "generatedAt": datetime.now(CN).strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "SEVERE": rep.counts["SEVERE"], "WARN": rep.counts["WARN"],
            "matches": exp["matches"], "battles": exp["battles"],
            "sideSwitchSeries": exp["sideSwitchSeries"],
            "officialFallback": exp["officialFallback"],
            "unresolved": exp["unresolved"],
            "crossTeamBattles": exp["crossTeamBattles"],
            "duplicateSeq": exp["duplicateSeq"],
        },
        "issues": rep.issues,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"系列赛一致性：SEVERE {rep.counts['SEVERE']} · WARN {rep.counts['WARN']} · "
          f"{exp['matches']} 个系列赛 / {exp['battles']} 局 / 换边 {exp['sideSwitchSeries']} 场 / "
          f"官方兜底 {exp['officialFallback']} 场")
    for it in rep.issues[:30]:
        print(f"  [{it['severity']}] {it['rule']} —— {it['detail']}")
    if len(rep.issues) > 30:
        print(f"  ... 其余 {len(rep.issues) - 30} 条见报告")
    print(f"报告：{REPORT}")

    if rep.counts["SEVERE"] and not warn_only:
        print("[!] 系列赛口径存在严重不一致，已阻断发布。")
        return 1
    print("[OK] 系列赛口径一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
