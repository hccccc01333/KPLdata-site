# -*- coding: utf-8 -*-
"""预测统计：直播预测档案（逐局命中）+ 模型回测指标 → assets/predict.js。

数据源：
  data/realtime/predictions/<battle>.csv   直播逐帧预测（monitor 实时写的）
  data/realtime/site_live_history.json     归档局（重放曲线）
  data/realtime/backtest_v9_report.json    历史回测（holdout 分阶段）
运行：python build_predict_data.py
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
REALTIME = PROJ / "data" / "realtime"


def jload(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_pred_csv(bid: str):
    """直播逐帧预测的最后置信值 + 帧数。"""
    path = REALTIME / "predictions" / f"{bid}.csv"
    if not path.exists():
        return None
    last_prob = None
    n = 0
    win_camp = 0
    last_gd = None
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    p = float(row.get("camp1_win_prob") or "")
                except (TypeError, ValueError):
                    continue
                if p != p:
                    continue
                last_prob = p
                n += 1
                try:
                    last_gd = int(float(row.get("gold_diff") or 0))
                except (TypeError, ValueError):
                    pass
                try:
                    wc = int(float(row.get("win_camp") or 0))
                    if wc in (1, 2):
                        win_camp = wc
                except (TypeError, ValueError):
                    pass
    except OSError:
        return None
    if last_prob is None:
        return None
    return {"lastProb": round(last_prob, 3), "frames": n, "winCamp": win_camp, "lastGd": last_gd}


def main() -> None:
    hist = jload(REALTIME / "site_live_history.json", {}) or {}
    backtest = jload(REALTIME / "backtest_v9_report.json", {}) or {}

    archived = []
    for bid, v in hist.items():
        csv_info = read_pred_csv(bid)
        win = int(v.get("win") or 0)
        t1, t2 = str(v.get("t1") or ""), str(v.get("t2") or "")
        # 优先用直播 CSV 的最后预测；无则用归档重放的收尾概率
        if csv_info and csv_info["lastProb"] is not None:
            prob = csv_info["lastProb"]
            frames = csv_info["frames"]
        else:
            pts = v.get("pts") or []
            prob = float(pts[-1][1]) if pts else None
            frames = len(pts)
        if prob is None or win not in (1, 2):
            continue
        pred_side = 1 if prob >= 0.5 else 2
        archived.append({
            "date": str(v.get("date") or ""),
            "matchId": str(v.get("matchId") or ""),
            "battleId": bid,
            "seq": int(v.get("seq") or 0),
            "t1": t1, "t2": t2, "win": win,
            "prob": round(prob, 3),
            "frames": frames,
            "hit": 1 if pred_side == win else 0,
            "tier": str(v.get("tier") or ""),
        })
    archived.sort(key=lambda x: (x["date"], x["matchId"], x["seq"]))

    hits = sum(a["hit"] for a in archived)
    accuracy = {
        "n": len(archived),
        "hits": hits,
        "rate": round(hits / len(archived), 3) if archived else 0,
    }

    hr = backtest.get("holdout_real") or {}
    phases = {}
    for ph in ("early", "mid", "late", "all"):
        m = hr.get(ph) or {}
        if m:
            phases[ph] = {
                "n": int(m.get("n") or 0),
                "acc": round(float(m.get("accuracy") or 0), 3),
                "brier": round(float(m.get("brier") or 0), 4),
            }
    gates = backtest.get("gates") or {}

    data = {
        "updatedAt": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
        "archived": archived,
        "accuracy": accuracy,
        "backtest": {
            "version": str(backtest.get("version") or ""),
            "trainedAt": str(backtest.get("trained_at") or "")[:10],
            "holdoutN": len(backtest.get("holdout_battles") or []),
            "phases": phases,
            "gatesPassed": bool(gates.get("passed")),
        },
    }
    path = SITE / "assets" / "predict.js"
    path.write_text("KPL_PREDICT = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                    encoding="utf-8")
    print(f"predict.js: {path.stat().st_size/1024:.1f} KB | archived={len(archived)} hits={hits} "
          f"({accuracy['rate']*100:.0f}%) | holdout phases={list(phases)}")


if __name__ == "__main__":
    main()
