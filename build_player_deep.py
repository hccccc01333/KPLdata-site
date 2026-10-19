# -*- coding: utf-8 -*-
"""选手深挖：位置内标准化 + 对手强度校正 + 稳定性 + 关键局 + 英雄池 + 打法相似度。

数据源：../02-KPL实时胜率预测系统/data/history/<league>/matches/<match>.json

算法口径（全部写进页面说明，避免黑箱）：
  1. 每局指标先做「同位置 z-score」——不同分路职责不同，绝对数不可横向比；
  2. 综合表现 = KDA / 输出占比 / 经济占比 / 参团率 / 承伤占比 / 生存（死亡数反向）六项 z 的均值；
  3. 稳定性 = 综合表现的标准差（越小越稳），同时给出 P10 下限与 P90 上限；
  4. 关键局增量 = 系列赛打满的最后一局 vs 常规局的综合表现差；
  5. 对手校正 = 用开赛前的队伍实力分（Elo）算期望胜率，实际胜率减期望；
  6. 英雄池熵 = 英雄使用分布的归一化香农熵（越高越不依赖单一英雄）；
  7. 打法相似度 = 同位置内八维特征向量的余弦相似度。

输出：assets/player_deep.js → KPL_PLAYER_DEEP = {generatedAt, players:{...}}
运行：python build_player_deep.py
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
CN = timezone(timedelta(hours=8))
MIN_GAMES = 40
ELO_K = 22
POS_FALLBACK = "未知"


def num(v, default=0.0):
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def team_of(battle: dict, camp: int) -> str:
    return str((battle.get(f"camp{camp}") or {}).get("team_name") or "")


def pct_rank(sorted_vals: list[float], v: float) -> float:
    """在数组中的百分位（0-100）。"""
    if not sorted_vals:
        return 50.0
    lo, hi = 0, len(sorted_vals)
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_vals[mid] < v:
            lo = mid + 1
        else:
            hi = mid
    return lo / len(sorted_vals) * 100.0


def main() -> None:
    files = sorted(HIST.glob("*/matches/*.json"))
    matches = []      # (date, mid, t1, t2, win_camp, bo, battles)
    raw = []          # 每局每名选手的紧凑记录
    skipped = 0

    for f in files:
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        m = o.get("match") or {}
        bs = [b for b in (o.get("battles") or []) if b.get("win_camp") in (1, 2)]
        if not bs:
            continue
        bs.sort(key=lambda b: int(b.get("battle_seq") or 0))
        t1, t2 = team_of(bs[0], 1), team_of(bs[0], 2)
        if not t1 or not t2:
            continue
        wins = Counter(int(b["win_camp"]) for b in bs)
        if wins[1] == wins[2]:
            continue
        win_camp = 1 if wins[1] > wins[2] else 2
        bo = int(m.get("bo") or 0) or (len(bs) * 2 - 1)
        date = str(m.get("start_time") or "")
        mid = str(m.get("match_id") or f.stem)
        need = (bo // 2) + 1
        complete = max(wins.values()) == need
        dec_seq = -1
        if complete and bo >= 3 and wins[win_camp] == need and wins[3 - win_camp] == need - 1 and len(bs) == bo:
            dec_seq = int(bs[-1].get("battle_seq") or 0)

        matches.append((date, mid, t1, t2, win_camp, bo))

        for b in bs:
            bt1, bt2 = team_of(b, 1), team_of(b, 2)
            if not bt1 or not bt2:
                bt1, bt2 = t1, t2
            plist = b.get("battle_player_list") or []
            gold_by_camp = {1: 0.0, 2: 0.0}
            for p in plist:
                camp = int(p.get("camp") or 0)
                if camp in (1, 2):
                    gold_by_camp[camp] += num(p.get("gold"))
            dur_raw = num(b.get("game_duration"))
            dur_min = dur_raw / 60000.0 if dur_raw > 100000 else (dur_raw / 60.0 if dur_raw > 1000 else 0)
            if dur_min <= 0 or dur_min > 60:
                dur_min = None
            is_dec = bool(dec_seq and int(b.get("battle_seq") or 0) == dec_seq)
            for p in plist:
                name = str(p.get("player_name") or p.get("actual_player_name") or "").strip()
                if not name:
                    continue
                camp = int(p.get("camp") or 0)
                if camp not in (1, 2):
                    continue
                k = int(num(p.get("kill_num"))); d = int(num(p.get("death_num"))); a = int(num(p.get("assist_num")))
                dmg = num(p.get("hurt_total_rate")) * 100 if p.get("hurt_total_rate") not in (None, "") else None
                tank = num(p.get("be_hurt_total_rate")) * 100 if p.get("be_hurt_total_rate") not in (None, "") else None
                part = num(p.get("participation_rate")) if p.get("participation_rate") not in (None, "") else None
                gold = num(p.get("gold"))
                gs = gold / gold_by_camp[camp] * 100 if gold_by_camp[camp] > 0 else None
                gpm = gold / dur_min if dur_min else None
                dpm = num(p.get("hurt_total")) / dur_min if dur_min else None
                pos = str(p.get("position_desc") or POS_FALLBACK).strip() or POS_FALLBACK
                raw.append((
                    name, pos, str(p.get("team_name") or (bt1 if camp == 1 else bt2)),
                    str(p.get("player_icon") or ""), mid, date, is_dec,
                    1 if camp == win_camp else 0, k, d, a, dmg, tank, part, gs, gpm, dpm,
                    str(p.get("hero_name") or ""),
                ))

    # ---------------- Elo：按时间累计，取开赛前实力分作为对手强度 ----------------
    matches.sort(key=lambda x: (x[0], x[1]))
    elo = defaultdict(lambda: 1500.0)
    elo_at = {}
    for date, mid, t1, t2, win_camp, bo in matches:
        ra, rb = elo[t1], elo[t2]
        elo_at[mid] = {t1: ra, t2: rb}
        ea = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        sa = 1.0 if win_camp == 1 else 0.0
        margin = 1
        k = ELO_K * (1.0 + (0.25 if bo >= 7 else 0.0))
        elo[t1] = ra + k * (sa - ea)
        elo[t2] = rb + k * ((1 - sa) - (1 - ea))

    # ---------------- 位置基线 ----------------
    METRICS = ("kda", "dmg", "gold", "part", "tank", "death")
    acc = defaultdict(lambda: {m: [0.0, 0.0, 0] for m in METRICS})  # 均值/方差累计

    def metric_of(r):
        (_, _, _, _, _, _, _, _, k, d, a, dmg, tank, part, gs, gpm, dpm, _) = r
        return {
            "kda": (k + a) / max(1, d),
            "dmg": dmg, "gold": gs, "part": part, "tank": tank,
            "death": d,
        }

    for r in raw:
        mv = metric_of(r)
        pos = r[1]
        for m in METRICS:
            v = mv[m]
            if v is None:
                continue
            cell = acc[pos][m]
            cell[0] += v; cell[1] += v * v; cell[2] += 1
    base = {}
    for pos, ms in acc.items():
        base[pos] = {}
        for m, (s, ss, n) in ms.items():
            mu = s / n if n else 0.0
            var = max(0.0, ss / n - mu * mu) if n else 1.0
            base[pos][m] = (mu, math.sqrt(var) if var > 1e-9 else 1.0)

    # ---------------- 逐局综合表现 ----------------
    def zget(pos, m, v, sign=1.0):
        if v is None:
            return None
        mu, sd = base.get(pos, base.get(POS_FALLBACK, {})).get(m, (0.0, 1.0))
        return sign * (v - mu) / sd

    per_player = defaultdict(list)   # name -> [(composite, won, dec, date, mid, pos)]
    heroes = defaultdict(Counter)
    meta = {}
    for r in raw:
        (name, pos, team, icon, mid, date, is_dec, won, k, d, a, dmg, tank, part, gs, gpm, dpm, hero) = r
        mv = metric_of(r)
        zs = [
            zget(pos, "kda", mv["kda"]),
            zget(pos, "dmg", mv["dmg"]),
            zget(pos, "gold", mv["gold"]),
            zget(pos, "part", mv["part"]),
            zget(pos, "tank", mv["tank"]),
            zget(pos, "death", mv["death"], -1.0),
        ]
        zs = [z for z in zs if z is not None]
        if not zs:
            continue
        comp = sum(zs) / len(zs)
        per_player[name].append((comp, won, 1 if is_dec else 0, date, mid, pos, team))
        if hero:
            heroes[name][hero] += 1
        cur = meta.get(name)
        if not cur or date > cur.get("last", ""):
            meta[name] = {"team": team, "pos": pos, "icon": icon or (cur or {}).get("icon", ""), "last": date}
        elif cur and icon and not cur.get("icon"):
            cur["icon"] = icon

    # ---------------- 选手汇总 ----------------
    pos_perf = defaultdict(list)
    pos_stab = defaultdict(list)
    pos_clutch = defaultdict(list)
    tmp = {}
    for name, rows in per_player.items():
        if len(rows) < MIN_GAMES:
            continue
        rows.sort(key=lambda x: (x[3], x[4]))
        vals = [x[0] for x in rows]
        n = len(vals)
        mu = sum(vals) / n
        sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / n)
        srt = sorted(vals)
        p10 = srt[max(0, int(n * 0.10) - 1)]
        p90 = srt[min(n - 1, int(n * 0.90))]
        dec = [x[0] for x in rows if x[2]]
        clutch = (sum(dec) / len(dec) - mu) if len(dec) >= 8 else None
        mpos = meta.get(name, {}).get("pos", POS_FALLBACK)
        last30 = vals[-30:]
        # 线性回归斜率（近 30 局，按局序）
        slope = 0.0
        if len(last30) >= 10:
            xs = list(range(len(last30)))
            xm = sum(xs) / len(xs); ym = sum(last30) / len(last30)
            den = sum((x - xm) ** 2 for x in xs)
            if den:
                slope = sum((x - xm) * (y - ym) for x, y in zip(xs, last30)) / den
        wins = sum(x[1] for x in rows)
        form_rows = rows[-30:]
        # 对手校正：Elo 期望胜率
        exp_sum = 0.0; exp_n = 0
        for x in rows:
            e = elo_at.get(x[4])
            if not e:
                continue
            team_game = x[6]
            my = e.get(team_game)
            opp = next((v for k, v in e.items() if k != team_game), None)
            if my is not None and opp is not None:
                exp_sum += 1.0 / (1.0 + 10 ** ((opp - my) / 400.0))
                exp_n += 1
        exp_wr = exp_sum / exp_n if exp_n else None
        hero_cnt = heroes[name]
        total_hero = sum(hero_cnt.values()) or 1
        ent = -sum((c / total_hero) * math.log(c / total_hero) for c in hero_cnt.values()) / math.log(max(2, len(hero_cnt)))
        pos_perf[mpos].append(mu)
        pos_stab[mpos].append(sd)
        if clutch is not None:
            pos_clutch[mpos].append(clutch)
        tmp[name] = {
            "name": name, "team": meta.get(name, {}).get("team", ""), "pos": mpos,
            "icon": meta.get(name, {}).get("icon", ""),
            "g": n, "w": wins, "perf": mu, "sd": sd, "p10": p10, "p90": p90,
            "clutch": clutch, "decN": len(dec),
            "formWR": sum(x[1] for x in form_rows) / len(form_rows) if form_rows else 0,
            "formZ": sum(x[0] for x in form_rows) / len(form_rows) if form_rows else 0,
            "slope": slope,
            "oppAdj": (wins / n - exp_wr) * 100 if exp_wr is not None else None,
            "heroEnt": ent, "poolN": len(hero_cnt),
            "spark": [round(v, 2) for v in vals[-30:]],
            "date": rows[-1][3],
        }

    pos_hero = defaultdict(list)
    pos_opp = defaultdict(list)
    pos_ceil = defaultdict(list)
    pos_form = defaultdict(list)
    for name, d in tmp.items():
        pos_hero[d["pos"]].append(d["heroEnt"])
        if d["oppAdj"] is not None:
            pos_opp[d["pos"]].append(d["oppAdj"])
        pos_ceil[d["pos"]].append(d["p90"])
        pos_form[d["pos"]].append(d["formZ"])

    out = {}
    for name, d in tmp.items():
        pp = pos_perf[d["pos"]]
        ps = pos_stab[d["pos"]]
        pc = pos_clutch.get(d["pos"], [])
        perf_pct = pct_rank(sorted(pp), d["perf"])
        stab_pct = 100.0 - pct_rank(sorted(ps), d["sd"])   # 波动越小分位越高
        clutch_pct = pct_rank(sorted(pc), d["clutch"]) if d["clutch"] is not None else None
        hero_pct = pct_rank(sorted(pos_hero[d["pos"]]), d["heroEnt"])
        opp_pct = pct_rank(sorted(pos_opp[d["pos"]]), d["oppAdj"]) if d["oppAdj"] is not None else None
        ceil_pct = pct_rank(sorted(pos_ceil[d["pos"]]), d["p90"])
        form_pct = pct_rank(sorted(pos_form[d["pos"]]), d["formZ"])
        tags = []
        if d["perf"] >= 0.5:
            tags.append("表现上乘")
        if d["p90"] >= 1.2:
            tags.append("上限很高")
        if stab_pct >= 75:
            tags.append("发挥稳定")
        if clutch_pct is not None and clutch_pct >= 75:
            tags.append("关键局强")
        if d["oppAdj"] is not None and d["oppAdj"] >= 3:
            tags.append("硬仗型")
        if hero_pct >= 70 and d["poolN"] >= 10:
            tags.append("英雄池深")
        if d["slope"] >= 0.015:
            tags.append("状态上行")
        out[name] = {
            "name": name, "team": d["team"], "pos": d["pos"], "icon": d["icon"],
            "g": d["g"], "w": d["w"],
            "perf": round(perf_pct, 1),
            "stab": round(stab_pct, 1),
            "clutch": round(clutch_pct, 1) if clutch_pct is not None else None,
            "heroPct": round(hero_pct, 1), "oppPct": round(opp_pct, 1) if opp_pct is not None else None,
            "ceilPct": round(ceil_pct, 1), "formPct": round(form_pct, 1),
            "clutchDelta": round(d["clutch"], 2) if d["clutch"] is not None else None,
            "floor": round(d["p10"], 2), "ceil": round(d["p90"], 2),
            "formWR": round(d["formWR"], 3), "formZ": round(d["formZ"], 2),
            "slope": round(d["slope"], 4),
            "oppAdj": round(d["oppAdj"], 1) if d["oppAdj"] is not None else None,
            "heroEnt": round(d["heroEnt"], 3), "poolN": d["poolN"],
            "decN": d["decN"],
            "spark": d["spark"],
            "tags": tags[:5],
        }

    # ---------------- 打法相似度（同位置余弦） ----------------
    raw_feats = {}
    for name, d in out.items():
        raw_feats[name] = [
            d["perf"], d["stab"], d["clutch"] if d["clutch"] is not None else 50.0,
            d["heroPct"], d["formPct"], d["ceilPct"],
        ]
    # 全局 z-score：消除量纲，避免余弦被正向均值主导（否则人人 0.99）
    k = 6
    means = [sum(v[i] for v in raw_feats.values()) / len(raw_feats) for i in range(k)]
    sds = []
    for i in range(k):
        var = sum((v[i] - means[i]) ** 2 for v in raw_feats.values()) / len(raw_feats)
        sds.append(math.sqrt(var) if var > 1e-9 else 1.0)
    feats = {}
    for name, v in raw_feats.items():
        feats[name] = [(v[i] - means[i]) / sds[i] for i in range(k)]
    by_pos = defaultdict(list)
    for name, d in out.items():
        if d["g"] >= 100:
            by_pos[d["pos"]].append(name)

    def dist_sim(a, b):
        d2 = sum((x - y) ** 2 for x, y in zip(a, b)) / len(a)
        return 1.0 / (1.0 + math.sqrt(d2))

    for name, d in out.items():
        cands = [(other, dist_sim(feats[name], feats[other])) for other in by_pos.get(d["pos"], []) if other != name]
        cands.sort(key=lambda x: -x[1])
        d["similar"] = [{"name": n, "sim": round(s, 3)} for n, s in cands[:4]]

    data = {
        "generatedAt": datetime.now(CN).strftime("%Y-%m-%d %H:%M"),
        "games": len(raw),
        "players": out,
    }
    path = SITE / "assets" / "player_deep.js"
    path.write_text("KPL_PLAYER_DEEP = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                    encoding="utf-8")
    print(f"player_deep.js: {path.stat().st_size/1024:.0f} KB | players {len(out)} | games {len(raw)}")


if __name__ == "__main__":
    main()
