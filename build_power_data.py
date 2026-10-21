# -*- coding: utf-8 -*-
"""战队战力体系（阶段 3）：多维战力分 + 三基准能力雷达 + 冠军墙。

口径（页面必须原样展示，不得改造）：
  数据来源   data/history/{league}/matches/*.json —— 2019–2026 全部已完赛对局
  基准范围   全部年份 / 各年份 / 各联赛（与站点「数据范围」选择器完全一致）
  合格门槛   各范围自适应：优先取「能让 ≥6 支战队入选」的最高门槛（10局/3场 → 6局/2场 → …）
  战力分     七项分量在「同一基准范围内的合格战队」之间做稳健标准分（median / MAD）后加权：
             赛程校正胜率 / 局分优势 / 场均金差 / 场均击杀差 / 场均推塔差 / 场均资源差 / 稳定性
             综合分 = clamp(50 + 12 × Σ w·z, 0, 100)，50 ≈ 该范围战队中位
  能力雷达   六维（胜率 / 局分 / 经济 / 对抗 / 推进 / 资源）各取该战队在同一基准范围内的百分位 0–100
             **同一战队在三基准下雷达可直接对比**（赛事 vs 年度 vs 历史）
  冠军墙     取各联赛最后一场已完赛对局（= 决赛）的真实 冠军 / 亚军 / 大比分 / 日期 / matchId
  边界       **这是"多维战力分"，不是"真实实力"**；未做历史回测验证；赛程校正仅用当期内胜率近似
输出：assets/power.js —— window.KPL_POWER = {...}
用法：python build_power_data.py
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
OUT = SITE / "assets" / "power.js"

CN_TZ = timezone(timedelta(hours=8))
ALG_VERSION = "power-v1"

# 战力分七分量（键即输出字段名）；权重和 = 1
WEIGHTS = {"adjWR": .30, "mm": .14, "gold": .16, "kill": .10, "tower": .10, "res": .10, "stab": .10}
WEIGHT_CN = {"adjWR": "赛程校正胜率", "mm": "局分优势", "gold": "场均金差",
             "kill": "场均击杀差", "tower": "场均推塔差", "res": "场均资源差", "stab": "稳定性"}

# 能力雷达六维（键即输出字段名），全部"越高越好" → 直接取百分位
DIMS = ["wr", "mm", "gold", "kill", "tower", "res"]
DIM_CN = {"wr": "胜率", "mm": "局分", "gold": "经济", "kill": "对抗", "tower": "推进", "res": "资源"}

# 合格门槛阶梯（局数, 大场数）；取能让 ≥MIN_TEAMS 支战队入选的最高一档
STEPS = ((30, 10), (15, 5), (10, 3), (6, 2), (4, 2), (2, 1))
MIN_TEAMS = 6            # 生成战力分所需的最少合格战队数
MIN_SCORE_TEAMS = 4
SCORE_PER_Z = 12.0
GOLD_STD_REF = 8000.0     # 金差波动的归一化参考（元）
RADAR_FLOOR = 4           # 雷达分位下限，避免完全压平
CORRUPT_GOLD = 200000.0   # 单方经济 > 此值视为脏数据（原始接口偶发溢出）
GD_WINSOR = 15000.0       # 单局金差缩尾上限，抑制极端翻盘/脏数据对均值的影响

# kill_big_dragon_num 疑似是先知主宰 + 暗影主宰合计（见 docs/数据字典.md），
# 与两个分项同时相加会把资源差放大，因此只保留分项。
DRAGON_FIELDS = ("kill_dark_tyrant_num", "kill_tyrant_num",
                 "kill_prophet_dragon_num", "kill_shadow_dragon_num", "kill_storm_dragon_king_num")


# --------------------------------------------------------------------------
def num(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if x == x and abs(x) != float("inf") else 0.0


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


def median(xs):
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def mad(xs):
    if not xs:
        return 0.0
    m = median(xs)
    return median([abs(x - m) for x in xs])


def robust_z_map(entries: list[dict], dims: list[str]) -> None:
    """就地写入 z_<dim>（同基准范围内稳健标准分）。"""
    for dim in dims:
        xs = [e[dim] for e in entries]
        med, sc = median(xs), 1.4826 * mad(xs)
        if sc < 1e-9:
            for e in entries:
                e["z_" + dim] = 0.0
        else:
            for e in entries:
                e["z_" + dim] = (e[dim] - med) / sc


def score100(z: float) -> int:
    return clamp(round(50.0 + SCORE_PER_Z * z), 0, 100)


def pct_rank(v: float, xs: list[float]) -> int:
    """v 在 xs 中的百分位（0–100），xs 需已排序。"""
    n = len(xs)
    if n < 2:
        return 50
    below = 0
    for x in xs:
        if x < v:
            below += 1
        else:
            break
    return clamp(round(below / (n - 1) * 100), RADAR_FLOOR, 100)


def dragons(c: dict) -> float:
    return sum(num(c.get(k)) for k in DRAGON_FIELDS)


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


# --------------------------------------------------------------------------
def new_team() -> dict:
    return {"g": 0, "gw": 0, "gl": 0, "gdsum": 0.0, "gd2": 0.0,
            "k": 0.0, "ko": 0.0, "tw": 0.0, "two": 0.0, "dr": 0.0, "dro": 0.0,
            "dur": 0.0, "tic": "", "mid": {}}


def scan() -> tuple[dict, Counter, dict]:
    """一次遍历全部历史对局，按 全部 / 年份 / 联赛 三个基准同时聚合战队。

    同时按 build_history_data.py 完全相同的规则（同日取最后一次遍历到的场次）提取各联赛冠军，
    保证冠军墙与站点既有 facts（KPL_SEASONS.leagues）一致。
    """
    scopes: dict[str, dict] = {}
    champs: dict[str, dict] = {}
    stats = Counter()
    t0 = time.time()

    def bucket(sid: str) -> dict:
        sc = scopes.get(sid)
        if sc is None:
            sc = scopes[sid] = {"teams": {}}
        return sc

    for lg in sorted(HIST.iterdir()):
        mdir = lg / "matches"
        if not mdir.is_dir():
            continue
        lid = lg.name
        year = lid[:4]
        sids = ("all", year, lid)
        ch = champs.setdefault(lid, {"date": ""})
        for f in sorted(mdir.glob("*.json")):
            stats["matchfiles"] += 1
            obj = load_json(f)
            if obj is None:
                stats["badfile"] += 1
                continue
            match = obj.get("match") or {}
            mid = str(match.get("match_id") or f.stem)
            mwc = match.get("win_camp")
            mdate = str(match.get("start_time") or "")[:10]
            if mwc in (1, 2) and mdate >= ch["date"]:
                c1m, c2m = (match.get("camp1") or {}), (match.get("camp2") or {})
                w_camp, l_camp = (c1m, c2m) if mwc == 1 else (c2m, c1m)
                ch.update({
                    "date": mdate, "champion": str(w_camp.get("team_name") or ""),
                    "runner": str(l_camp.get("team_name") or ""),
                    "s1": int(num(c1m.get("score"))), "s2": int(num(c2m.get("score"))),
                    "matchId": mid,
                    "stage": str(match.get("match_stage_desc") or match.get("match_stage_name") or ""),
                })
            for b in obj.get("battles") or []:
                if not isinstance(b, dict):
                    continue
                wc = b.get("win_camp")
                if wc not in (1, 2):
                    continue
                c1, c2 = (b.get("camp1") or {}), (b.get("camp2") or {})
                t1, t2 = str(c1.get("team_name") or ""), str(c2.get("team_name") or "")
                if not t1 or not t2 or t1 == "待定" or t2 == "待定":
                    stats["nodata"] += 1
                    continue
                stats["battles"] += 1
                dur = num(b.get("game_duration")) / 60000.0
                g1, g2 = num(c1.get("gold")), num(c2.get("gold"))
                corrupt = g1 > CORRUPT_GOLD or g2 > CORRUPT_GOLD
                if corrupt:
                    stats["corrupt"] += 1
                for sid in sids:
                    teams = bucket(sid)["teams"]
                    for camp, team, tic, mine, opp in (
                        (1, t1, str(c1.get("team_icon") or ""), c1, c2),
                        (2, t2, str(c2.get("team_icon") or ""), c2, c1),
                    ):
                        rec = teams.get(team)
                        if rec is None:
                            rec = teams[team] = new_team()
                        if tic and not rec["tic"]:
                            rec["tic"] = tic
                        won = (camp == wc)
                        rec["g"] += 1
                        rec["gw"] += 1 if won else 0
                        rec["gl"] += 0 if won else 1
                        oteam = str(opp.get("team_name") or "")
                        key = (mid, oteam)
                        mm = rec["mid"].get(key)
                        if mm is None:
                            mm = rec["mid"][key] = {"gw": 0, "gl": 0}
                        mm["gw"] += 1 if won else 0
                        mm["gl"] += 0 if won else 1
                        if corrupt:
                            continue          # 脏局只保留胜负，不污染数值分量
                        gd = clamp(num(mine.get("gold")) - num(opp.get("gold")), -GD_WINSOR, GD_WINSOR)
                        rec["gdsum"] += gd
                        rec["gd2"] += gd * gd
                        rec["k"] += num(mine.get("kill_num"))
                        rec["ko"] += num(opp.get("kill_num"))
                        rec["tw"] += num(mine.get("push_tower_num"))
                        rec["two"] += num(opp.get("push_tower_num"))
                        rec["dr"] += dragons(mine)
                        rec["dro"] += dragons(opp)
                        rec["dur"] += dur

    print(f"扫描：{stats['matchfiles']} 场 / {stats['battles']} 局 / {stats['corrupt']} 脏局 / "
          f"{len(scopes)} 个范围 · {time.time() - t0:.1f}s")
    return scopes, stats, champs


# --------------------------------------------------------------------------
def comp_rows(teams: dict[str, dict]) -> list[dict]:
    """把战队累计量转成七分量原始值（赛程校正 = 胜率 + (0.5 − 对手当期平均胜率)）。"""
    wr_of = {}
    for team, r in teams.items():
        g = r["gw"] + r["gl"]
        if g:
            wr_of[team] = r["gw"] / g

    out = []
    for team, r in teams.items():
        g = r["gw"] + r["gl"]
        if g <= 0:
            continue
        opp_sum = 0.0
        for (_mid, o) in r["mid"]:
            opp_sum += wr_of.get(o, 0.5)
        avg_opp = opp_sum / len(r["mid"]) if r["mid"] else 0.5
        mw = sum(1 for mm in r["mid"].values() if mm["gw"] > mm["gl"])
        wr = r["gw"] / g
        gold_mean = r["gdsum"] / g
        var = max(0.0, r["gd2"] / g - gold_mean * gold_mean)
        out.append({
            "team": team, "tic": r["tic"], "g": g, "m": len(r["mid"]),
            "mw": mw, "ml": len(r["mid"]) - mw,
            "gw": r["gw"], "gl": r["gl"], "wr": wr,
            "adjWR": clamp(wr + (0.5 - avg_opp), 0.0, 1.0),
            "mm": 0.5 + (r["gw"] - r["gl"]) / g / 2,
            "gold": gold_mean,
            "kill": (r["k"] - r["ko"]) / g,
            "tower": (r["tw"] - r["two"]) / g,
            "res": (r["dr"] - r["dro"]) / g,
            "dur": r["dur"] / g,
            "stab": 1.0 / (1.0 + (var ** 0.5) / GOLD_STD_REF),
        })
    return out


def pick_threshold(rows: list[dict]) -> tuple[int, int]:
    for gmin, mmin in STEPS:
        if sum(1 for r in rows if r["g"] >= gmin and r["m"] >= mmin) >= MIN_TEAMS:
            return gmin, mmin
    return STEPS[-1]


def score_scope(teams: dict[str, dict]) -> dict:
    rows = comp_rows(teams)
    if not rows:
        return {"n": 0, "threshold": {"g": STEPS[0][0], "m": STEPS[0][1]}, "teams": []}

    gmin, mmin = pick_threshold(rows)
    elig = [r for r in rows if r["g"] >= gmin and r["m"] >= mmin]
    threshold = {"g": gmin, "m": mmin}

    scored = []
    if len(elig) >= MIN_SCORE_TEAMS:
        z_dims = list(WEIGHTS.keys())
        robust_z_map(elig, z_dims)
        for e in elig:
            e["z"] = sum(WEIGHTS[d] * e["z_" + d] for d in z_dims)
            e["score"] = score100(e["z"])
        pools = {d: sorted(e[d] for e in elig) for d in DIMS}
        for e in elig:
            e["r"] = [pct_rank(e[d], pools[d]) for d in DIMS]
        elig.sort(key=lambda e: (-e["score"], -e["g"]))
        scored = elig

    elig_ids = {id(e) for e in scored}
    rest = [r for r in rows if id(r) not in elig_ids]
    rest.sort(key=lambda r: (-r["wr"], -r["g"]))

    def pack(e: dict, is_scored: bool) -> dict:
        row = {"t": e["team"], "ic": e["tic"], "g": int(round(e["g"])), "m": e["m"],
               "mw": int(e["mw"]), "ml": int(e["ml"]),
               "gw": int(round(e["gw"])), "gl": int(round(e["gl"])), "wr": round(e["wr"], 3),
               "adjWR": round(e["adjWR"], 3), "mm": round(e["mm"], 3),
               "gold": round(e["gold"]), "kill": round(e["kill"], 2),
               "tower": round(e["tower"], 2), "res": round(e["res"], 2), "dur": round(e["dur"], 1)}
        if is_scored:
            row["score"] = e["score"]
            row["z"] = round(e["z"], 2)
            row["r"] = e["r"]
        return row

    return {"n": len(scored), "threshold": threshold,
            "teams": [pack(e, True) for e in scored] + [pack(e, False) for e in rest]}


def build_champions(league_meta: list[dict], scopes: dict, champs: dict) -> list[dict]:
    out = []
    for lg in league_meta:
        lid = str(lg.get("league_id") or "")
        ch = champs.get(lid) or {}
        has_champ = bool(ch.get("champion")) and bool(ch.get("date"))
        finished = int(lg.get("status") or 0) == 2 and has_champ
        row = {
            "id": lid, "name": str(lg.get("league_name") or ""),
            "year": int(lid[:4]) if lid[:4].isdigit() else 0,
            "type": str(lg.get("league_type") or ""),
            "start": str(lg.get("start_time") or "")[:10],
            "end": str(lg.get("end_time") or "")[:10],
            "finished": bool(finished),
            "champion": "", "runner": "", "s1": 0, "s2": 0,
            "date": "", "matchId": "", "stage": "", "leader": "",
        }
        teams = (scopes.get(lid) or {}).get("teams") or []
        lead = teams[0] if teams and teams[0].get("score") is not None else None
        if finished:
            row.update({
                "champion": ch["champion"], "runner": ch.get("runner", ""),
                "s1": int(ch.get("s1") or 0), "s2": int(ch.get("s2") or 0),
                "date": ch["date"], "matchId": ch.get("matchId", ""), "stage": ch.get("stage", ""),
            })
        elif lead:
            row["leader"] = lead["t"]
        out.append(row)
    out.sort(key=lambda r: r["id"], reverse=True)
    return out


# --------------------------------------------------------------------------
def main() -> None:
    t0 = time.time()
    league_meta = load_json(HIST / "leagues.json", []) or []
    if not league_meta:
        raise SystemExit("leagues.json 不存在，请先运行 backfill_league_history.py")

    scopes, stats, champs = scan()

    years = sorted({str(l.get("league_id"))[:4] for l in league_meta})

    out_scopes = {}
    total_scored = 0
    for sid, sc in scopes.items():
        res = score_scope(sc["teams"])
        total_scored += res["n"]
        out_scopes[sid] = res
    for sid in ["all"] + years:
        out_scopes.setdefault(sid, {"n": 0, "threshold": {"g": STEPS[0][0], "m": STEPS[0][1]}, "teams": []})

    champions = build_champions(league_meta, out_scopes, champs)

    out = {
        "meta": {
            "builtAt": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M"),
            "algorithmVersion": ALG_VERSION,
            "dims": DIMS, "dimCN": DIM_CN,
            "weights": WEIGHTS, "weightCN": WEIGHT_CN,
            "steps": [list(s) for s in STEPS], "minTeams": MIN_TEAMS,
            "formula": {
                "power": "综合分 = clamp(50 + 12 × Σ w·z, 0, 100)；z = (x − median) / (1.4826 × MAD)，分母取同基准范围内全部合格战队",
                "radar": "每维 = 该战队原始值在同基准范围内合格战队中的百分位（0–100），故三基准可直接对比",
                "adjWR": "赛程校正胜率 = 胜率 + (0.5 − 对手当期平均胜率)，奖励「赢下强敌」而非「输给强敌」",
                "stab": f"稳定性 = 1 / (1 + 金差标准差 / {int(GOLD_STD_REF)})（连续化，避免饱和堆积）",
                "trim": f"单局金差缩尾至 ±{int(GD_WINSOR)}；单方经济 > {int(CORRUPT_GOLD)} 的脏局只计胜负",
            },
            "source": "data/history 官方接口，2019–2026 全部已完赛对局",
            "coverage": {"matchFiles": stats["matchfiles"], "battles": stats["battles"],
                         "corruptBattles": stats["corrupt"], "scopes": len(out_scopes),
                         "leagues": len(champions), "scoredRows": total_scored},
            "note": "多维战力分（非「真实实力」），未做历史回测验证；赛程校正仅用当期内胜率近似，留待后续阶段。",
        },
        "scopes": out_scopes,
        "champions": champions,
    }
    OUT.write_text("window.KPL_POWER = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    print(f"power.js: {len(out_scopes)} 范围 · {len(champions)} 联赛冠军 · "
          f"{OUT.stat().st_size / 1024:.0f} KB · {time.time() - t0:.1f}s")

    allsc = out_scopes["all"]
    print(f"\n历史基准（all）合格门槛 ≥{allsc['threshold']['g']}局/≥{allsc['threshold']['m']}场"
          f" · {allsc['n']} 支 · 战力分 Top 8：")
    for i, r in enumerate(allsc["teams"][:8]):
        print(f"  {i + 1:>2}. {r['t']:<8} {r['score']:>3} 分 · {r['gw']}-{r['gl']} 局 · 校正胜率 {r['adjWR']}"
              f" · 金差 {r['gold']:+} · 推塔差 {r['tower']:+.2f} · 资源差 {r['res']:+.2f} · 雷达 {r['r']}")
    print("\n冠军墙抽样：")
    for c in champions[:3]:
        if c["finished"]:
            print(f"  {c['name']}: 冠军 {c['champion']} {c['s1']}:{c['s2']} {c['runner']} · {c['date']} · {c['matchId']}")
        else:
            print(f"  {c['name']}: 进行中 · 领先 {c['leader'] or '—'}")


if __name__ == "__main__":
    main()
