# -*- coding: utf-8 -*-
"""赛前实力评级校准：走步 Elo → 系列赛胜率 → 无截距概率校准。

为什么不做复杂模型：修正系列赛胜方口径后，走步回测显示 Elo 是唯一稳定
跑赢基线的信号；状态、交手、首发、英雄环境等特征在独立测试集上没有
提升准确率。因此最终模型保持「实力评级 + 概率校准」，其余作为赛前情报。

输出：assets/prematch_calib.js
运行：python build_prematch_calib.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from scipy.optimize import minimize_scalar

from kpl_series import summarize_match

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
ELO_K = 22
SPLIT = "2025-01-01"


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sig(x):
    return 1 / (1 + math.exp(-x))


def series_win(p, bo):
    m = (bo + 1) // 2
    return sum(math.comb(m - 1 + k, k) * (p ** m) * ((1 - p) ** k) for k in range(m))


def main():
    rows = []
    for f in sorted(HIST.glob("*/matches/*.json")):
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        res = summarize_match(o, fallback_id=f.stem)
        if not res or not res.resolved or not res.battle_complete or res.bo < 3:
            continue
        rows.append({
            "d": res.date[:10], "bo": res.bo,
            "t1": res.team1, "t2": res.team2,
            "y": 1 if res.winner == res.team1 else 0,
            "score": res.score,
        })
    rows.sort(key=lambda x: x["d"])

    elo = {}
    for r in rows:
        a, b = r["t1"], r["t2"]
        ra = elo.get(a, 1500.0)
        rb = elo.get(b, 1500.0)
        pg = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        r["pg"] = pg
        r["ps"] = series_win(pg, r["bo"])
        sa = 1.0 if r["y"] == 1 else 0.0
        ea = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        margin = abs(r["score"][0] - r["score"][1])
        mov = min(2.0, 1.0 + 0.35 * max(0, margin - 1))
        k = ELO_K * (1.0 + (0.25 if r["bo"] >= 7 else 0.0)) * mov
        elo[a] = ra + k * (sa - ea)
        elo[b] = rb + k * ((1 - sa) - (1 - ea))

    train = [r for r in rows if r["d"] < SPLIT]
    test = [r for r in rows if r["d"] >= SPLIT]

    Lf = [logit(r["ps"]) for r in train]
    yf = [r["y"] for r in train]

    def loss(a):
        return sum((sig(a * x) - y) ** 2 for x, y in zip(Lf, yf)) / len(Lf)

    res = minimize_scalar(loss, bounds=(0.1, 1.2), method="bounded")
    alpha = float(res.x)

    def metrics(sub):
        if not sub:
            return None
        p = [sig(alpha * logit(r["ps"])) for r in sub]
        y = [r["y"] for r in sub]
        hit = sum(1 for x, v in zip(p, y) if (x >= 0.5) == (v == 1))
        br = sum((x - v) ** 2 for x, v in zip(p, y)) / len(sub)
        ll = -sum(math.log(max(x, 1e-9)) if v else math.log(max(1 - x, 1e-9))
                  for x, v in zip(p, y)) / len(sub)
        raw = [r["ps"] for r in sub]
        raw_hit = sum(1 for x, v in zip(raw, y) if (x >= 0.5) == (v == 1))
        raw_br = sum((x - v) ** 2 for x, v in zip(raw, y)) / len(sub)
        return {"n": len(sub), "acc": round(hit / len(sub), 4),
                "brier": round(br, 4), "logloss": round(ll, 4),
                "rawAcc": round(raw_hit / len(sub), 4),
                "rawBrier": round(raw_br, 4)}

    by_bo = {}
    for bo in sorted({r["bo"] for r in test}):
        by_bo[str(bo)] = metrics([r for r in test if r["bo"] == bo])

    data = {
        "generatedAt": __import__("time").strftime("%Y-%m-%d %H:%M"),
        "alpha": round(alpha, 4),
        "split": SPLIT,
        "trainN": len(train),
        "test": metrics(test),
        "all": metrics(rows),
        "byBo": by_bo,
        "note": "无截距校准：保持胜负判断不变，只收缩概率幅度。",
    }
    path = SITE / "assets" / "prematch_calib.js"
    path.write_text("KPL_PRE_CALIB = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";",
                    encoding="utf-8")
    print(f"prematch_calib.js: alpha={alpha:.3f} | train {len(train)} | "
          f"test {data['test']} | byBO {list(by_bo)}")


if __name__ == "__main__":
    main()
