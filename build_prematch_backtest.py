# -*- coding: utf-8 -*-
"""赛前模型走步回测：只用该场之前的数据，逐场预测大场胜方与比分。

特征与线上模拟器一致（不含首发强度：历史首发无法在赛前可靠还原）：
  实力评级 40% / 当前联赛战绩 15% / 近 10 场 12% / 交手 8% / BO 赛制经验 10%
输出：assets/prematch_backtest.js
运行：python build_prematch_backtest.py
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
ELO_K = 22
W = {"elo": 0.40, "scope": 0.15, "form": 0.12, "h2h": 0.08, "bo": 0.10}


def num(v, default=0.0):
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def team_of(battle: dict, camp: int) -> str:
    return str((battle.get(f"camp{camp}") or {}).get("team_name") or "")


def logit(p: float) -> float:
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def smooth(w: float, g: float) -> float:
    return (w + 2.0) / (g + 4.0)


def series_win(p: float, bo: int) -> float:
    m = (bo + 1) // 2
    s = 0.0
    for k in range(m):
        s += math.comb(m - 1 + k, k) * (p ** m) * ((1 - p) ** k)
    return s


def series_dist(p1: float, pm: float, pdec: float, m: int) -> float:
    probs = {(0, 0): 1.0}
    terminal = defaultdict(float)
    for _ in range(2 * m - 1):
        nxt = defaultdict(float)
        for (i, j), pr in probs.items():
            if i == m or j == m:
                terminal[(i, j)] += pr
                continue
            if i == 0 and j == 0:
                p = p1
            elif i == m - 1 and j == m - 1:
                p = pdec
            else:
                p = pm
            nxt[(i + 1, j)] += pr * p
            nxt[(i, j + 1)] += pr * (1 - p)
        probs = nxt
    for (i, j), pr in probs.items():
        terminal[(i, j)] += pr
    return sum(pr for (i, j), pr in terminal.items() if i == m)


def main() -> None:
    files = sorted(HIST.glob("*/matches/*.json"))
    matches = []
    for f in files:
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        m = o.get("match") or {}
        raw_bs = [b for b in (o.get("battles") or []) if b.get("win_camp") in (1, 2)]
        if not raw_bs:
            continue
        by_seq = {}
        for b in raw_bs:
            seq = int(b.get("battle_seq") or 0)
            if seq > 0 and seq not in by_seq:
                by_seq[seq] = b
        bs = [by_seq[k] for k in sorted(by_seq)]
        if not bs:
            continue
        t1, t2 = team_of(bs[0], 1), team_of(bs[0], 2)
        if not t1 or not t2:
            continue
        wins = Counter(int(b["win_camp"]) for b in bs)
        if wins[1] == wins[2]:
            continue
        bo = int(m.get("bo") or 0)
        if bo < 3:
            continue
        need = bo // 2 + 1
        if max(wins.values()) != need:
            continue
        win_camp = 1 if wins[1] > wins[2] else 2
        date = str(m.get("start_time") or "")[:10]
        lid = str(m.get("league_id") or "")
        mid = str(m.get("match_id") or f.stem)
        g1_camp = int(bs[0]["win_camp"])
        went_dist = wins[win_camp] == need and wins[3 - win_camp] == need - 1 and len(bs) == bo
        matches.append({
            "date": date, "mid": mid, "lid": lid, "bo": bo, "t1": t1, "t2": t2,
            "win_camp": win_camp, "g1_camp": g1_camp, "went": went_dist, "bs": bs,
            "score": (wins[win_camp], wins[3 - win_camp]),
        })

    matches.sort(key=lambda x: (x["date"], x["mid"]))
    elo = defaultdict(lambda: 1500.0)
    form = defaultdict(list)
    h2h = defaultdict(lambda: [0, 0])          # pair -> [t1 wins, n]
    league = defaultdict(lambda: defaultdict(lambda: [0, 0]))  # lid -> team -> [w,g]
    borec = defaultdict(lambda: defaultdict(lambda: [0, 0]))   # team -> bo -> [w,n]
    first = defaultdict(lambda: [0, 0])        # team -> [won_g1, series]
    dec = defaultdict(lambda: [0, 0])          # team -> [won_dec, n_dec]

    rows = []
    for x in matches:
        a, b, lid, bo = x["t1"], x["t2"], x["lid"], x["bo"]
        comps = []
        ra, rb = elo[a], elo[b]
        comps.append(("elo", 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0)), W["elo"]))

        la, lb = league[lid][a], league[lid][b]
        if la[1] >= 10 and lb[1] >= 10:
            comps.append(("scope", sig(logit(smooth(la[0], la[1])) - logit(smooth(lb[0], lb[1]))), W["scope"]))

        fa, fb = form[a][-10:], form[b][-10:]
        if len(fa) >= 4 and len(fb) >= 4:
            comps.append(("form", sig(logit(smooth(sum(fa), len(fa))) - logit(smooth(sum(fb), len(fb)))), W["form"]))

        key = tuple(sorted((a, b)))
        h = h2h[key]
        if h[1] >= 3:
            aw = h[0] if key[0] == a else h[1] - h[0]
            comps.append(("h2h", (aw + 2.0) / (h[1] + 4.0), W["h2h"]))

        ba, bb = borec[a][bo], borec[b][bo]
        if ba[1] >= 5 and bb[1] >= 5:
            comps.append(("bo", smooth(ba[0], ba[1]) / (smooth(ba[0], ba[1]) + smooth(bb[0], bb[1])), W["bo"]))

        wsum = sum(c[2] for c in comps) or 1.0
        p = sig(sum(c[2] * logit(c[1]) for c in comps) / wsum)
        p = min(max(p, 0.02), 0.98)

        # 首局 / 决胜局修正
        fa1, fb1 = first[a], first[b]
        p1 = p
        if fa1[1] >= 10 and fb1[1] >= 10:
            d = logit(smooth(fa1[0], fa1[1])) - logit(smooth(fb1[0], fb1[1]))
            p1 = sig(logit(p) + 0.30 * d)
        da, db = dec[a], dec[b]
        pdec = p
        if da[1] >= 10 and db[1] >= 10:
            d = logit(smooth(da[0], da[1])) - logit(smooth(db[0], db[1]))
            pdec = sig(logit(p) + 0.30 * d)
        m = (bo + 1) // 2
        ps = series_dist(p1, p, pdec, m)

        y = 1 if x["win_camp"] == 1 else 0
        ps_elo = series_win(1.0 / (1.0 + 10 ** ((rb - ra) / 400.0)), bo)
        rows.append({"d": x["date"], "bo": bo, "ps": ps, "y": y, "elo": ps_elo,
                     "p": p, "p1": p1, "pdec": pdec,
                     "comps": {k: v for k, v, _ in comps}})

        # ---- 更新状态（严格用本场结果，且在本场预测之后）----
        sa = 1.0 if x["win_camp"] == 1 else 0.0
        ea = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        margin = abs(x["score"][0] - x["score"][1])
        mov = min(2.0, 1.0 + 0.35 * max(0, margin - 1))
        k = ELO_K * (1.0 + (0.25 if bo >= 7 else 0.0)) * mov
        elo[a] = ra + k * (sa - ea)
        elo[b] = rb + k * ((1 - sa) - (1 - ea))

        form[a].append(1 if x["win_camp"] == 1 else 0)
        form[b].append(0 if x["win_camp"] == 1 else 1)
        form[a] = form[a][-10:]
        form[b] = form[b][-10:]

        h2h[key][1] += 1
        if (key[0] == a and x["win_camp"] == 1) or (key[0] == b and x["win_camp"] == 2):
            h2h[key][0] += 1

        borec[a][bo][1] += 1
        borec[b][bo][1] += 1
        if x["win_camp"] == 1:
            borec[a][bo][0] += 1
        else:
            borec[b][bo][0] += 1

        g1_winner = a if x["g1_camp"] == 1 else b
        first[a][1] += 1
        first[b][1] += 1
        first[g1_winner][0] += 1

        if x["went"]:
            dec[a][1] += 1
            dec[b][1] += 1
            if x["win_camp"] == 1:
                dec[a][0] += 1
            else:
                dec[b][0] += 1

        for bt in x["bs"]:
            bw = int(bt["win_camp"])
            bt1, bt2 = team_of(bt, 1), team_of(bt, 2)
            if not bt1 or not bt2:
                continue
            league[lid][bt1][1] += 1
            league[lid][bt2][1] += 1
            if bw == 1:
                league[lid][bt1][0] += 1
            else:
                league[lid][bt2][0] += 1

    # ---------------- 走步校准 + 权重寻优 ----------------
    import numpy as np
    KEYS = ("elo", "scope", "form", "h2h", "bo")
    SPLIT = "2025-01-01"
    train = [r for r in rows if r["d"] < SPLIT]
    test = [r for r in rows if r["d"] >= SPLIT]

    def combine(weights, lam, bias, row):
        avail = [(k, row["comps"][k]) for k in KEYS if k in row.get("comps", {})]
        if not avail:
            return 0.5
        wsum = sum(weights[k] for k, _ in avail) or 1.0
        L = sum(weights[k] * logit(p0) for k, p0 in avail) / wsum
        return sig(lam * L + bias)

    tuned = None
    if len(train) >= 200:
        X = np.array([[logit(r["comps"][k]) if k in r["comps"] else 0.0 for k in KEYS] for r in train])
        M = np.array([[1.0 if k in r["comps"] else 0.0 for k in KEYS] for r in train])
        yv = np.array([r["y"] for r in train], dtype=float)
        grid = np.arange(0.0, 1.01, 0.1)
        best = (9.9, None)
        for w1 in np.arange(0.2, 0.81, 0.05):
            for w2 in np.arange(0.1, 0.81, 0.05):
                if w1 + w2 > 0.95: continue
                for w3 in np.arange(0.05, 0.51, 0.05):
                    if w1 + w2 + w3 > 0.95: continue
                    for w4 in np.arange(0.05, 0.31, 0.05):
                        if w1 + w2 + w3 + w4 > 0.95: continue
                        w5 = 1.0 - w1 - w2 - w3 - w4
                        if w5 < 0.05: continue
                        w = np.array([w1, w2, w3, w4, w5])
                        mask = M @ w
                        raw = (X @ w) / np.where(mask > 1e-9, mask, 1.0)
                        for lam in (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
                            for bias in (-0.1, 0.0, 0.1):
                                pv = 1.0 / (1.0 + np.exp(-(lam * raw + bias)))
                                brier = float(np.mean((pv - yv) ** 2))
                                if brier < best[0]:
                                    best = (brier, (w, lam, bias))
        w, lam, bias = best[1]
        wd = {k: round(float(w[i]), 3) for i, k in enumerate(KEYS)}
        tuned = {"weights": wd, "lam": lam, "bias": bias, "trainN": len(train)}

        def metrics(sub, lam2, bias2, weights):
            if not sub:
                return None
            ps = [combine(weights, lam2, bias2, r) for r in sub]
            ser = [series_win(p0, r["bo"]) for p0, r in zip(ps, sub)]
            hit = sum(1 for s, r in zip(ser, sub) if (s >= 0.5) == (r["y"] == 1))
            br = sum((s - r["y"]) ** 2 for s, r in zip(ser, sub)) / len(sub)
            ll2 = -sum(math.log(max(s, 1e-9)) if r["y"] else math.log(max(1 - s, 1e-9))
                       for s, r in zip(ser, sub)) / len(sub)
            return {"n": len(sub), "acc": round(hit / len(sub), 4),
                    "brier": round(br, 4), "logloss": round(ll2, 4)}

        tuned["test"] = metrics(test, lam, bias, wd)
        tuned["testElo"] = None
        if test:
            ser = [series_win(r["elo"], r["bo"]) for r in test]
            hit = sum(1 for s, r in zip(ser, test) if (s >= 0.5) == (r["y"] == 1))
            br = sum((s - r["y"]) ** 2 for s, r in zip(ser, test)) / len(test)
            tuned["testElo"] = {"n": len(test), "acc": round(hit / len(test), 4), "brier": round(br, 4)}
        tuned["trainBrier"] = round(best[0], 4)

    n = len(rows)
    hits = sum(1 for r in rows if (r["ps"] >= 0.5) == (r["y"] == 1))
    brier = sum((r["ps"] - r["y"]) ** 2 for r in rows) / n
    ll = -sum(math.log(max(r["ps"], 1e-9)) if r["y"] else math.log(max(1 - r["ps"], 1e-9)) for r in rows) / n
    base_hits = sum(1 for r in rows if (r["elo"] >= 0.5) == (r["y"] == 1))
    base_brier = sum((r["elo"] - r["y"]) ** 2 for r in rows) / n

    by_bo = {}
    for bo in sorted({r["bo"] for r in rows}):
        sub = [r for r in rows if r["bo"] == bo]
        by_bo[str(bo)] = {
            "n": len(sub),
            "acc": round(sum(1 for r in sub if (r["ps"] >= 0.5) == (r["y"] == 1)) / len(sub), 4),
            "brier": round(sum((r["ps"] - r["y"]) ** 2 for r in sub) / len(sub), 4),
        }

    bins = []
    for lo, hi in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)):
        sub = [r for r in rows if lo <= r["ps"] < hi]
        if not sub:
            continue
        bins.append({
            "range": f"{int(lo*100)}-{int(min(hi,1)*100)}%",
            "n": len(sub),
            "pred": round(sum(r["ps"] for r in sub) / len(sub), 3),
            "actual": round(sum(r["y"] for r in sub) / len(sub), 3),
        })

    data = {
        "generatedAt": datetime.now(CN).strftime("%Y-%m-%d %H:%M"),
        "n": n,
        "from": rows[0]["d"] if rows else "",
        "to": rows[-1]["d"] if rows else "",
        "acc": round(hits / n, 4),
        "brier": round(brier, 4),
        "logloss": round(ll, 4),
        "baseline": {"acc": round(base_hits / n, 4), "brier": round(base_brier, 4)},
        "byBo": by_bo,
        "calibration": bins,
        "tuned": tuned,
    }
    path = SITE / "assets" / "prematch_backtest.js"
    path.write_text("KPL_PRE_BACKTEST = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";",
                    encoding="utf-8")
    print(f"prematch_backtest.js: {n} matches | acc {data['acc']*100:.1f}% (Elo {data['baseline']['acc']*100:.1f}%) "
          f"| Brier {data['brier']} (Elo {data['baseline']['brier']})")


if __name__ == "__main__":
    main()
