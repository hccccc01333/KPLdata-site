# -*- coding: utf-8 -*-
"""赛前实力评级校准：走步 Elo → 系列赛胜率 → 按赛季滚动的无截距概率校准。

2026-10 升级：
- Elo 配置与 build_deep_data.py 保持一致：K=40、年度向 1500 回归 25%、
  去掉局分差（MOV）加成、把 BO1 也纳入评级更新；
- 校准按赛季滚动：每个赛季的 α 只用该赛季之前的完整赛季拟合；
- 评估用走步口径（2025+ 每场只用此前赛季的 α），避免“用未来校准未来”。

为什么不做复杂模型：离线对比显示「Elo + 滚动校准」仍是稳定、可解释的基线；
挑战者 LR 的额外特征在 2026 有小幅提升，但优势处于显著性边缘，暂不进入
生产概率，只作为赛前模拟页的挑战者对照。

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

ELO_K = 40
ELO_SEASON_REGRESS = 0.25
CALIB_MIN_BO = 3
TEST_START_YEAR = 2025
MIN_CALIB_ROWS = 80
DEFAULT_ALPHA = 0.5


def logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def sig(x):
    return 1 / (1 + math.exp(-x))


def series_win(p, bo):
    if bo <= 1:
        return p
    m = (bo + 1) // 2
    return sum(math.comb(m - 1 + k, k) * (p ** m) * ((1 - p) ** k) for k in range(m))


def fit_alpha(rows):
    if len(rows) < MIN_CALIB_ROWS:
        return None
    xs = [logit(r["ps"]) for r in rows]
    ys = [r["y"] for r in rows]

    def loss(a):
        return sum((sig(a * x) - y) ** 2 for x, y in zip(xs, ys)) / len(ys)

    res = minimize_scalar(loss, bounds=(0.1, 1.5), method="bounded")
    return float(res.x)


def main():
    # 所有已结算大场都参与 Elo 更新（包括 BO1），与 build_deep_data.py 保持一致；
    # 只有「完整 BO3+」进入校准与评估。
    all_rows = []
    for f in sorted(HIST.glob("*/matches/*.json")):
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        res = summarize_match(o, fallback_id=f.stem)
        if not res or not res.resolved:
            continue
        all_rows.append({
            "mid": res.match_id,
            "d": res.date[:10],
            "year": int(res.date[:4]),
            "bo": int(res.bo),
            "t1": res.team1,
            "t2": res.team2,
            "y": 1 if res.winner == res.team1 else 0,
            "complete": bool(res.battle_complete),
        })
    all_rows.sort(key=lambda x: (x["d"], x["mid"]))

    elo = {}
    elo_last_year = {}
    for r in all_rows:
        year = r["year"]
        for team in (r["t1"], r["t2"]):
            if elo_last_year.get(team) not in (None, year):
                elo[team] = 1500.0 + (elo.get(team, 1500.0) - 1500.0) * (1.0 - ELO_SEASON_REGRESS)
            elo_last_year[team] = year

        ra = elo.get(r["t1"], 1500.0)
        rb = elo.get(r["t2"], 1500.0)
        pg = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        r["pg"] = pg
        r["ps"] = series_win(pg, r["bo"]) if r["bo"] >= CALIB_MIN_BO else pg

        sa = 1.0 if r["y"] == 1 else 0.0
        k = ELO_K * (1.0 + (0.25 if r["bo"] >= 7 else 0.0))
        elo[r["t1"]] = ra + k * (sa - pg)
        elo[r["t2"]] = rb + k * ((1 - sa) - (1 - pg))

    target = [r for r in all_rows if r["complete"] and r["bo"] >= CALIB_MIN_BO]
    if not target:
        raise SystemExit("没有可用于校准的完整 BO3+ 大场")

    years = sorted({r["year"] for r in target})
    alpha_by_year = {}
    alpha_train_n = {}
    for year in years:
        prior = [r for r in target if r["year"] == year - 1]
        if len(prior) < MIN_CALIB_ROWS:
            prior = [r for r in target if r["year"] < year]
        alpha = fit_alpha(prior)
        if alpha is None:
            alpha = DEFAULT_ALPHA
        alpha_by_year[str(year)] = round(alpha, 4)
        alpha_train_n[str(year)] = len(prior)

    latest_year = years[-1]
    latest_alpha = alpha_by_year[str(latest_year)]

    def metrics(sub):
        if not sub:
            return None
        calibrated, raw, ys = [], [], []
        for r in sub:
            a = alpha_by_year.get(str(r["year"]), DEFAULT_ALPHA)
            raw.append(r["ps"])
            calibrated.append(sig(a * logit(r["ps"])))
            ys.append(r["y"])
        hit = sum(1 for x, v in zip(calibrated, ys) if (x >= 0.5) == (v == 1))
        br = sum((x - v) ** 2 for x, v in zip(calibrated, ys)) / len(sub)
        ll = -sum(math.log(max(x, 1e-9)) if v else math.log(max(1 - x, 1e-9))
                  for x, v in zip(calibrated, ys)) / len(sub)
        raw_hit = sum(1 for x, v in zip(raw, ys) if (x >= 0.5) == (v == 1))
        raw_br = sum((x - v) ** 2 for x, v in zip(raw, ys)) / len(sub)
        return {
            "n": len(sub),
            "acc": round(hit / len(sub), 4),
            "brier": round(br, 4),
            "logloss": round(ll, 4),
            "rawAcc": round(raw_hit / len(sub), 4),
            "rawBrier": round(raw_br, 4),
        }

    test = [r for r in target if r["year"] >= TEST_START_YEAR]
    by_bo = {}
    for bo in sorted({r["bo"] for r in test}):
        by_bo[str(bo)] = metrics([r for r in test if r["bo"] == bo])

    # all 用走步口径；首个赛季没有 prior，只作参考。
    all_scored = [r for r in target if r["year"] > years[0]]

    data = {
        "generatedAt": __import__("time").strftime("%Y-%m-%d %H:%M"),
        "alpha": latest_alpha,
        "alphaBySeason": alpha_by_year,
        "alphaTrainN": alpha_train_n,
        "currentSeason": latest_year,
        "split": "rolling",
        "trainN": alpha_train_n[str(latest_year)],
        "test": metrics(test),
        "all": metrics(all_scored),
        "byBo": by_bo,
        "elo": {
            "k": ELO_K,
            "seasonRegress": ELO_SEASON_REGRESS,
            "mov": False,
            "includeBo1": True,
        },
        "note": (
            "α 按赛季滚动：每个赛季只用此前一个完整赛季（不足则扩展到更早赛季）拟合；"
            "无截距校准，保持胜负判断不变，只收缩概率幅度。"
        ),
    }

    path = SITE / "assets" / "prematch_calib.js"
    path.write_text(
        "KPL_PRE_CALIB = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";",
        encoding="utf-8",
    )
    print(f"prematch_calib.js: current α={latest_alpha:.3f} | train {data['trainN']} | "
          f"test {data['test']} | byBO {list(by_bo)}")
    print(f"α by season: {alpha_by_year}")


if __name__ == "__main__":
    main()
