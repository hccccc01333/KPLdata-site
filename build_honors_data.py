# -*- coding: utf-8 -*-
"""荣誉中心（一期）：周榜 / 月榜 五路最佳选手 + 本周最佳战队。

口径（页面必须原样展示，不得改造）：
  数据来源   data/history/{league}/matches/*.json —— 2019–2026 全部已完赛对局
  时间窗     周 = 北京时间周一至周日（ISO 周）；月 = 自然月；跨午夜按赛事归属日期
  分路       对抗路 / 打野 / 中路 / 发育路 / 游走（按 position_desc 归位，禁止按选手名排序）
  评分       分路内六项稳健标准分（median / MAD）按固定评分卡加权 → 综合分（50 ≈ 该分路当期中位）
             KDA / 分均经济 / 分均输出 / 分均承伤 / 参团率 / MVP 率；**不含团队胜率**，避免强队垄断
  不确定性   按「大场」成组 bootstrap（同场 10 人相关，不可独立重采样）：胜者命中率 + 综合分 95% 区间
  阈值       周榜 ≥4 局 / ≥2 大场；月榜 ≥12 局 / ≥4 大场；数据完整率 ≥0.9；样本不足只出候选榜，不强行颁奖
  **边界**   这是"固定评分卡 + 当期表现"的榜单，不是「真实实力」；未做历史回测验证（后续阶段）
输出：assets/honors.js —— window.KPL_HONORS = {...}
用法：python build_honors_data.py
"""
from __future__ import annotations

import json
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
OUT = SITE / "assets" / "honors.js"

CN_TZ = timezone(timedelta(hours=8))
ALG_VERSION = "honors-v1"

LANES = ["对抗路", "打野", "中路", "发育路", "游走"]
DIMS = ["kda", "gpm", "dpm", "bhpm", "part", "mvpRate"]
DIM_CN = {"kda": "KDA", "gpm": "分均经济", "dpm": "分均输出",
          "bhpm": "分均承伤", "part": "参团率", "mvpRate": "MVP 率"}

# 固定评分卡：每行权重和 = 1（分路不同 → 评价维度权重不同）
WEIGHTS = {
    "对抗路": {"kda": .20, "gpm": .10, "dpm": .20, "bhpm": .25, "part": .10, "mvpRate": .15},
    "打野":   {"kda": .22, "gpm": .18, "dpm": .18, "bhpm": .17, "part": .15, "mvpRate": .10},
    "中路":   {"kda": .20, "gpm": .18, "dpm": .27, "bhpm": .12, "part": .13, "mvpRate": .10},
    "发育路": {"kda": .20, "gpm": .25, "dpm": .30, "bhpm": .08, "part": .07, "mvpRate": .10},
    "游走":   {"kda": .18, "gpm": .06, "dpm": .12, "bhpm": .28, "part": .26, "mvpRate": .10},
}
TEAM_W = {"oppAdj": .45, "marginMap": .30, "stab": .25}

THRESH = {"week": {"minGames": 4, "minMatches": 2},
          "month": {"minGames": 12, "minMatches": 4}}
COMPLETENESS_MIN = 0.90
TEAM_MIN = {"week": {"minMatches": 2, "minGames": 5},
            "month": {"minMatches": 4, "minGames": 12}}
BOOT_ITERS = 120
BOOT_SEED = 20261019
BOARD_MAX = 5
TEAM_BOARD_MAX = 5
GOLD_STD_REF = 8000.0     # 金差波动的归一化参考（元）
SCORE_PER_Z = 12.0        # 综合分 = 50 + 12 × 综合标准分


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
    """就地写入 z_<dim>（分路/当期样本内稳健标准分）。"""
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


def pct_ci(sorted_zs: list[float]) -> list[int]:
    n = len(sorted_zs)
    return [score100(sorted_zs[int(0.025 * (n - 1))]), score100(sorted_zs[int(0.975 * (n - 1))])]


def load_leagues() -> dict[str, str]:
    try:
        rows = json.loads((HIST / "leagues.json").read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {str(r.get("league_id")): str(r.get("league_name") or "") for r in rows}


def date_of(match: dict) -> date | None:
    st = str(match.get("start_time") or "")
    if len(st) >= 10 and st[4] == "-" and st[7] == "-":
        try:
            return date(int(st[:4]), int(st[5:7]), int(st[8:10]))
        except ValueError:
            return None
    return None


def week_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def bounds_of(key: str) -> tuple[date, date]:
    if "-W" in key:
        y, w = key.split("-W")
        mon = date.fromisocalendar(int(y), int(w), 1)
        return mon, mon + timedelta(days=6)
    y, m = key.split("-")
    first = date(int(y), int(m), 1)
    nxt = date(int(y) + 1, 1, 1) if int(m) == 12 else date(int(y), int(m) + 1, 1)
    return first, nxt - timedelta(days=1)


# --------------------------------------------------------------------------
# 扫描：一次遍历历史 JSON，按 周 / 月 分桶（选手按「大场」预聚合，供 bootstrap 快速加权）
# --------------------------------------------------------------------------
def new_bucket() -> dict:
    return {"games": 0, "mids": set(), "lanes": {ln: {} for ln in LANES},
            "teams": {}, "lids": Counter()}


def scan() -> tuple[dict, dict, dict[str, str], Counter]:
    leagues = load_leagues()
    W: dict[str, dict] = {}
    M: dict[str, dict] = {}
    stats = Counter()
    t0 = time.time()

    for lg in sorted(HIST.iterdir()):
        mdir = lg / "matches"
        if not mdir.is_dir():
            continue
        lid = lg.name
        for f in sorted(mdir.glob("*.json")):
            stats["matchfiles"] += 1
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                stats["badfile"] += 1
                continue
            match = obj.get("match") or {}
            d = date_of(match)
            if d is None:
                stats["nodate"] += 1
                continue
            mid = str(match.get("match_id") or f.stem)
            keys = [(W, week_key(d)), (M, month_key(d))]

            for b in obj.get("battles") or []:
                if not isinstance(b, dict):
                    continue
                wc = b.get("win_camp")
                if wc not in (1, 2):
                    continue
                dur = num(b.get("game_duration")) / 60000.0     # ms → min
                c1, c2 = (b.get("camp1") or {}), (b.get("camp2") or {})
                t1, t2 = str(c1.get("team_name") or ""), str(c2.get("team_name") or "")
                g1, g2 = num(c1.get("gold")), num(c2.get("gold"))
                i1, i2 = str(c1.get("team_icon") or ""), str(c2.get("team_icon") or "")
                stats["battles"] += 1

                for store, key in keys:
                    bucket = store.setdefault(key, new_bucket())
                    bucket["games"] += 1
                    bucket["mids"].add(mid)
                    bucket["lids"][lid] += 1
                    # 战队：同一大场的多局都计入；键为 (大场, 对手)
                    for camp, team, tic, gold, ogold, oteam in (
                        (1, t1, i1, g1, g2, t2), (2, t2, i2, g2, g1, t1),
                    ):
                        if not team or team == "待定":
                            continue
                        rec = bucket["teams"].setdefault(team, {"mid": {}, "tic": ""})
                        if tic and not rec["tic"]:
                            rec["tic"] = tic
                        mm = rec["mid"].setdefault((mid, oteam), {"gw": 0, "gl": 0, "gd": []})
                        won = (camp == wc)
                        mm["gw"] += 1 if won else 0
                        mm["gl"] += 0 if won else 1
                        mm["gd"].append(gold - ogold)

                for p in b.get("battle_player_list") or []:
                    if not isinstance(p, dict):
                        continue
                    ln = str(p.get("position_desc") or "").strip()
                    if ln not in LANES:
                        continue                    # 无分路 → 无法归位，不参与分路榜
                    name = str(p.get("player_name") or p.get("actual_player_name") or "").strip()
                    if not name:
                        continue
                    camp = int(num(p.get("camp")))
                    if camp not in (1, 2):
                        continue
                    gold, part = num(p.get("gold")), num(p.get("participation_rate"))
                    valid = (gold > 0 and dur > 0 and part > 0)
                    if not valid:
                        stats["invalid"] += 1
                    for store, key in keys:
                        bucket = store.setdefault(key, new_bucket())
                        pl = bucket["lanes"][ln].setdefault(
                            name, {"bymid": {}, "ntotal": 0, "nvalid": 0, "team": "", "tic": "", "pic": ""})
                        if not pl["team"]:
                            pl["team"] = str(p.get("team_name") or "")
                            pl["tic"] = str(p.get("team_icon") or "")
                            pl["pic"] = str(p.get("player_icon") or "")
                        pl["ntotal"] += 1
                        if valid:
                            pl["nvalid"] += 1
                            dd = pl["bymid"].setdefault(mid, [0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
                            dd[0] += 1
                            dd[1] += gold
                            dd[2] += dur
                            dd[3] += num(p.get("hurt_to_hero_total"))
                            dd[4] += num(p.get("be_hurt_by_hero_total"))
                            dd[5] += num(p.get("kda"))
                            dd[6] += part
                            dd[7] += 1.0 if (num(p.get("is_mvp")) or num(p.get("is_lose_mvp"))) else 0.0
                            dd[8] += 1.0 if camp == wc else 0.0

    print(f"扫描：{stats['matchfiles']} 场 / {stats['battles']} 局 / "
          f"{len(W)} 周 / {len(M)} 月 · {time.time() - t0:.1f}s")
    return W, M, leagues, stats


# --------------------------------------------------------------------------
# 选手评分
# --------------------------------------------------------------------------
def metrics(pl: dict, counts=None) -> dict | None:
    tot = gold = dur = dmg = tank = kda = part = mvp = wins = 0.0
    m = 0
    bymid = pl["bymid"]
    for mid, d in bymid.items():
        w = 1.0 if counts is None else counts.get(mid, 0.0)
        if not w:
            continue
        m += 1
        tot += d[0] * w
        gold += d[1] * w; dur += d[2] * w; dmg += d[3] * w; tank += d[4] * w
        kda += d[5] * w; part += d[6] * w; mvp += d[7] * w; wins += d[8] * w
    if tot <= 0 or dur <= 0:
        return None
    return {
        "g": tot, "m": m, "wr": wins / tot,
        "kda": kda / tot, "gpm": gold / dur, "dpm": dmg / dur, "bhpm": tank / dur,
        "part": part / tot, "mvpRate": mvp / tot, "mvp": mvp,
    }


def gates(pl: dict, mm: dict, kind: str) -> bool:
    t = THRESH[kind]
    return (mm["g"] >= t["minGames"] and mm["m"] + 0.5 >= t["minMatches"]
            and pl["ntotal"] > 0 and pl["nvalid"] / pl["ntotal"] >= COMPLETENESS_MIN)


def full_item(name, mm, meta, score, extra=None) -> dict:
    it = {"name": name, "team": meta["team"], "tic": meta["tic"], "pic": meta["pic"],
          "g": int(round(mm["g"])), "m": mm["m"], "wr": round(mm["wr"], 3),
          "kda": round(mm["kda"], 2), "gpm": round(mm["gpm"]), "dpm": round(mm["dpm"]),
          "bhpm": round(mm["bhpm"]), "part": round(mm["part"], 1), "mvp": int(mm["mvp"]),
          "score": score}
    if extra:
        it.update(extra)
    return it


def slim_item(name, mm, meta, score) -> dict:
    return {"name": name, "team": meta["team"], "tic": meta["tic"],
            "g": int(round(mm["g"])), "m": mm["m"], "wr": round(mm["wr"], 3), "score": score}


def compute_lane(players: dict[str, dict], ln: str, kind: str):
    entries = []
    for name, pl in players.items():
        mm = metrics(pl)
        if mm:
            entries.append((name, mm, pl))
    if not entries:
        return None

    zs = [dict(mm) for _, mm, _ in entries]
    names = [n for n, _, _ in entries]
    for e, n in zip(zs, names):
        e["name"] = n
    robust_z_map(zs, DIMS)
    wd = WEIGHTS[ln]
    for e in zs:
        e["z"] = sum(wd[d] * e["z_" + d] for d in DIMS)
        e["score"] = score100(e["z"])
    zmap = {e["name"]: e for e in zs}

    elig = [(n, mm, pl) for n, mm, pl in entries if gates(pl, mm, kind)]
    elig.sort(key=lambda t: -zmap[t[0]]["z"])

    # 按大场成组 bootstrap
    boots: dict[str, dict] = {}
    boot_used = 0
    mids_all = sorted({mid for pl in players.values() for mid in pl["bymid"]})
    if len(mids_all) >= 3 and len(elig) >= 3:
        rnd = random.Random(BOOT_SEED + LANES.index(ln) * 17)
        n = len(mids_all)
        top1 = Counter()
        samples: dict[str, list[float]] = defaultdict(list)
        for _ in range(BOOT_ITERS):
            counts = Counter(rnd.choices(mids_all, k=n))
            sub = []
            for name, _mm, pl in elig:
                mm = metrics(pl, counts)
                if mm and mm["g"] > 0:
                    mm["name"] = name
                    sub.append(mm)
            if len(sub) < 3:
                continue
            robust_z_map(sub, DIMS)
            for e in sub:
                e["z"] = sum(wd[d] * e["z_" + d] for d in DIMS)
            boot_used += 1
            sub.sort(key=lambda e: -e["z"])
            top1[sub[0]["name"]] += 1
            for e in sub:
                samples[e["name"]].append(e["z"])
        for name, zl in samples.items():
            zl.sort()
            boots[name] = {"top1": round(top1[name] / boot_used, 3) if boot_used else 0.0,
                           "ci": pct_ci(zl)}

    board = []
    for i, (name, mm, pl) in enumerate(elig[:BOARD_MAX]):
        sc = zmap[name]["score"]
        extra = {"z": round(zmap[name]["z"], 2)}
        b = boots.get(name)
        if b:
            extra["t1"] = b["top1"]
            extra["ci"] = b["ci"]
        board.append(full_item(name, mm, pl, sc, extra) if i == 0 else slim_item(name, mm, pl, sc))

    t = THRESH[kind]
    note = None if boots else ("样本不足，仅候选" if not elig else "样本太少，未做稳定性估计")
    return {"n": len(elig), "board": board, "note": note, "boot": bool(boots),
            "bootIters": boot_used, "minGames": t["minGames"], "minMatches": t["minMatches"]}


# --------------------------------------------------------------------------
# 战队评分（独立模型：对手强度校正胜率 / 局分优势 / 稳定性；当期队内稳健标准化）
# --------------------------------------------------------------------------
def team_components(rows, counts=None):
    wr_of = {}
    for r in rows:
        gw = gl = 0.0
        for (mid, _o), mm in r["mid"].items():
            w = 1.0 if counts is None else counts.get(mid, 0.0)
            if not w:
                continue
            gw += mm["gw"] * w
            gl += mm["gl"] * w
        if gw + gl > 0:
            wr_of[r["team"]] = gw / (gw + gl)
    out = []
    for r in rows:
        gw = gl = opp = g1 = g2 = gn = 0.0
        seen = set()
        for (mid, o), mm in r["mid"].items():
            w = 1.0 if counts is None else counts.get(mid, 0.0)
            if not w:
                continue
            gw += mm["gw"] * w
            gl += mm["gl"] * w
            seen.add(mid)
            os_ = wr_of.get(o, 0.5)
            won = mm["gw"] > mm["gl"]
            opp += (os_ if won else 1 - os_) * w
            for x in mm["gd"]:
                g1 += x * w
                g2 += x * x * w
                gn += w
        g = gw + gl
        if g <= 0:
            continue
        mean = g1 / gn if gn else 0.0
        var = max(0.0, (g2 / gn - mean * mean)) if gn else 0.0
        sd = var ** 0.5
        out.append({"team": r["team"], "tic": r["tic"], "g": g, "m": len(seen),
                    "gw": gw, "gl": gl, "wr": gw / g, "oppAdj": opp / g,
                    "marginMap": 0.5 + (gw - gl) / g / 2,
                    "stab": 1 - min(1.0, sd / GOLD_STD_REF)})
    return out


def team_scored(rows, counts=None):
    comps = team_components(rows, counts)
    tmin = TEAM_MIN["week"]
    elig = [c for c in comps if c["m"] >= 1 and c["g"] > 0]
    if len(elig) < 2:
        return comps, []
    robust_z_map(elig, ["oppAdj", "marginMap", "stab"])
    for e in elig:
        z = sum(TEAM_W[d] * e["z_" + d] for d in TEAM_W)
        e["z"] = z
        e["score"] = score100(z)
    return comps, elig


def compute_team(bucket: dict, kind: str):
    rows = [{"team": team, "tic": rec["tic"], "mid": rec["mid"]}
            for team, rec in bucket["teams"].items()]
    if not rows:
        return None
    tmin = TEAM_MIN[kind]
    _comps, elig = team_scored(rows)
    elig = [e for e in elig if e["m"] >= tmin["minMatches"] and e["g"] >= tmin["minGames"]]
    elig.sort(key=lambda e: -e["score"])

    boots: dict[str, dict] = {}
    boot_used = 0
    mids_all = sorted(bucket["mids"])
    if len(mids_all) >= 3 and len(elig) >= 3:
        rnd = random.Random(BOOT_SEED + 991)
        n = len(mids_all)
        top1 = Counter()
        samples: dict[str, list[float]] = defaultdict(list)
        for _ in range(BOOT_ITERS):
            counts = Counter(rnd.choices(mids_all, k=n))
            _c, sub = team_scored(rows, counts)
            sub = [e for e in sub if e["m"] >= tmin["minMatches"] and e["g"] >= tmin["minGames"]]
            if len(sub) < 3:
                continue
            boot_used += 1
            sub.sort(key=lambda e: -e["score"])
            top1[sub[0]["team"]] += 1
            for e in sub:
                samples[e["team"]].append(e["score"])
        for team, sl in samples.items():
            sl.sort()
            boots[team] = {"top1": round(top1[team] / boot_used, 3) if boot_used else 0.0,
                           "ci": [int(sl[int(0.025 * (len(sl) - 1))]), int(sl[int(0.975 * (len(sl) - 1))])]}

    board = []
    for i, e in enumerate(elig[:TEAM_BOARD_MAX]):
        item = {"team": e["team"], "tic": e["tic"], "g": int(round(e["g"])), "m": e["m"],
                "gw": int(round(e["gw"])), "gl": int(round(e["gl"])), "wr": round(e["wr"], 3),
                "oppAdj": round(e["oppAdj"], 3), "stab": round(e["stab"], 3), "score": e["score"]}
        b = boots.get(e["team"])
        if b:
            item["t1"] = b["top1"]
            item["ci"] = b["ci"]
        if i > 0:                        # 候选只留必要字段
            item = {k: item[k] for k in ("team", "tic", "g", "m", "gw", "gl", "score") if k in item}
        board.append(item)
    note = None if elig else "样本不足，仅候选"
    return {"n": len(elig), "board": board, "note": note, "boot": bool(boots),
            "minMatches": tmin["minMatches"], "minGames": tmin["minGames"]}


# --------------------------------------------------------------------------
def period_label(key: str) -> str:
    if "-W" in key:
        y, w = key.split("-W")
        return f"{y} 年第 {int(w)} 周"
    y, m = key.split("-")
    return f"{y} 年 {int(m)} 月"


def build_periods(store: dict, kind: str, leagues: dict[str, str], today: date, stats: Counter):
    out = []
    for key, bucket in store.items():
        if bucket["games"] < 2:
            continue
        start, end = bounds_of(key)
        lid = bucket["lids"].most_common(1)[0][0] if bucket["lids"] else ""
        lanes = {}
        for ln in LANES:
            res = compute_lane(bucket["lanes"][ln], ln, kind)
            if res and res["board"]:
                lanes[ln] = res
        team = compute_team(bucket, kind)
        if not lanes and not team:
            continue
        out.append({
            "id": key, "label": period_label(key),
            "start": start.isoformat(), "end": end.isoformat(),
            "ongoing": end >= today, "season": leagues.get(lid, ""),
            "games": bucket["games"], "matches": len(bucket["mids"]),
            "lanes": lanes, "team": team,
        })
        stats["periods_" + kind] += 1
    out.sort(key=lambda p: p["start"], reverse=True)
    return out


def main() -> None:
    t0 = time.time()
    today = datetime.now(CN_TZ).date()
    W, M, leagues, stats = scan()

    weeks = build_periods(W, "week", leagues, today, stats)
    months = build_periods(M, "month", leagues, today, stats)

    def latest_of(ps):
        for p in ps:
            if not p["ongoing"]:
                return p["id"]
        return ps[0]["id"] if ps else None

    out = {
        "meta": {
            "builtAt": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M"),
            "algorithmVersion": ALG_VERSION,
            "laneOrder": LANES, "dims": DIMS, "dimCN": DIM_CN,
            "thresholds": {"week": THRESH["week"], "month": THRESH["month"],
                           "completeness": COMPLETENESS_MIN, "team": TEAM_MIN},
            "formula": {
                "weights": WEIGHTS,
                "teamWeights": TEAM_W,
                "robustZ": "z = (x − median) / (1.4826 × MAD)，分母取该分路当期全部有数据选手",
                "score": "综合分 = clamp(50 + 12 × Σ w·z, 0, 100)，50 ≈ 该分路当期中位",
                "team": "战队三项分量（对手强度校正胜率 / 局分优势 / 稳定性）在当期队内稳健标准化后加权",
                "bootstrap": f"按大场成组重采样 {BOOT_ITERS} 次 → 胜者命中率 + 综合分 95% 区间",
            },
            "source": "data/history 官方接口，2019–2026 全部已完赛对局",
            "coverage": {"matchFiles": stats["matchfiles"], "battles": stats["battles"],
                         "weeks": len(weeks), "months": len(months)},
            "note": "固定评分卡 + 当期表现榜，可复算；不是「真实实力」，历史回测验证留待后续阶段。",
        },
        "latest": {"week": latest_of(weeks), "month": latest_of(months)},
        "weeks": weeks, "months": months,
    }
    OUT.write_text("window.KPL_HONORS = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    print(f"honors.js: {len(weeks)} 周 · {len(months)} 月 · {OUT.stat().st_size / 1024:.0f} KB · {time.time() - t0:.1f}s")

    for p in weeks[:2]:
        print(f"  {p['id']} {p['label']} · {p['season']} · {p['matches']} 大场 / {p['games']} 局"
              f"{' · 进行中' if p['ongoing'] else ''}")
        for ln in LANES:
            r = p["lanes"].get(ln)
            if not r or not r["board"]:
                print(f"    {ln}: 无有效样本")
                continue
            w = r["board"][0]
            t1 = f" · top1 {w['t1']:.0%} · CI {w['ci']}" if "t1" in w else ""
            print(f"    {ln}: {w['name']}（{w['team']}）{w['score']} 分 · {w['g']} 局 / {w['m']} 场 · "
                  f"KDA {w['kda']} · 分均经济 {w['gpm']}{t1}")
        if p.get("team") and p["team"]["board"]:
            tw = p["team"]["board"][0]
            print(f"    战队: {tw['team']} {tw['score']} 分 · 局 {tw['gw']}-{tw['gl']} · "
                  f"对手校正 {tw['oppAdj']} · 稳定 {tw['stab']}")


if __name__ == "__main__":
    main()
