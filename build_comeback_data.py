# -*- coding: utf-8 -*-
"""翻盘路径研究所 · 数据构建（V5 阶段5 剩项5）。

只用**已经生成好的**复盘数据包（assets/replay/*.json），不重放模型、不补缺失帧。
每条结论都能指着具体一局（比赛链接 + 第几局 + 最低胜率出现在哪一分钟）。

两个必须讲清楚的边界：
  1) 全量赛程里只有约 200 局有分钟级快照（约 2%），页面必须标注样本范围；
  2) 胜率序列分两类：live=直播当时写下的预测（可信），replay=赛后重放（波动大，只列举不统计）；
  3) 开局 1–3 分钟模型缺少对线期特征，会外推出 0.98 / 0.02 这种极端先验值。
     把这段算进"翻盘"会造出一堆"1 分钟就 2% 胜率"的假结论，
     所以低点统计从第 WINDOW_MIN 分钟起算（口径写进页面）。

输出：assets/comeback.js
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

SITE = Path(__file__).resolve().parent
REPLAY_DIR = SITE / "assets" / "replay"
GAMES_INDEX = SITE / "assets" / "games" / "index.js"
OUT_PATH = SITE / "assets" / "comeback.js"

WINDOW_MIN = 8.0                                  # 低点统计窗口起点（分钟）
COMEBACK_LINE = 0.25                              # 胜方一度低于该胜率，算"翻盘"
BINS = [(0.0, 0.10, "0–10%"), (0.10, 0.20, "10–20%"), (0.20, 0.35, "20–35%"), (0.35, 1.01, "35% 以上")]
LOW_BUCKETS = [(8, 12, "8–12 分"), (12, 16, "12–16 分"), (16, 20, "16–20 分"), (20, 999, "20 分后")]
LIST_LIMIT = 24


def jload_js(path: Path, default):
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text[text.index("=") + 1:].rstrip().rstrip(";"))
    except Exception:
        return default


def winner_series(battle: dict) -> list[tuple[float, float]]:
    """「最终胜方视角」的 (分钟, 胜率) 序列，只取 WINDOW_MIN 之后的采样点。"""
    win = int(battle.get("win") or 0)
    if win not in (1, 2):
        return []
    out = []
    for f in battle.get("frames") or []:
        p = f.get("p")
        m = float(f.get("m") or 0)
        if p is None or m < WINDOW_MIN:
            continue
        out.append((m, float(p) if win == 1 else 1.0 - float(p)))
    return out


def main() -> None:
    t0 = time.time()
    total_battles = 0
    try:
        gindex = jload_js(GAMES_INDEX, {})
        total_battles = sum(len((v or {}).get("b") or []) for v in gindex.values())
    except Exception:
        total_battles = 0

    files = sorted(p for p in REPLAY_DIR.glob("*.json") if p.name[0].isdigit())
    battles = 0
    live = 0
    replay = 0
    too_early = 0
    per_bin = [0] * len(BINS)
    per_low = [0] * len(LOW_BUCKETS)
    comebacks = []
    lows = []

    for fp in files:
        try:
            pkg = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        mid = str(pkg.get("matchId") or "")
        for b in pkg.get("battles") or []:
            ser = winner_series(b)
            if len(ser) < 2:
                too_early += 1
                continue
            battles += 1
            if b.get("src") == "live":
                live += 1
            else:
                replay += 1
            low_m, low_p = min(ser, key=lambda x: x[1])
            lows.append(low_p)
            for i, (lo, hi, _) in enumerate(BINS):
                if lo <= low_p < hi:
                    per_bin[i] += 1
                    break
            for i, (lo, hi, _) in enumerate(LOW_BUCKETS):
                if lo <= low_m < hi:
                    per_low[i] += 1
                    break
            if low_p < COMEBACK_LINE:
                win = int(b.get("win") or 0)
                comebacks.append({
                    "mid": mid,
                    "battleId": str(b.get("battleId") or ""),
                    "seq": int(b.get("seq") or 0),
                    "date": str(pkg.get("date") or ""),
                    "t1": str(b.get("t1") or pkg.get("t1") or ""),
                    "t2": str(b.get("t2") or pkg.get("t2") or ""),
                    "winner": str(b.get("t1") if win == 1 else (b.get("t2") or "")),
                    "loser": str(b.get("t2") if win == 1 else (b.get("t1") or "")),
                    "lowP": round(low_p, 3),
                    "lowMin": round(low_m, 1),
                    "dur": round(float(b.get("dur") or 0), 1),
                    "src": str(b.get("src") or ""),
                })

    comebacks.sort(key=lambda x: (x["lowP"], x["lowMin"]))

    med = sorted(lows)[len(lows) // 2] if lows else 0
    data = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "meta": {
            "battles": battles,
            "live": live,
            "replay": replay,
            "tooEarly": too_early,
            "totalBattles": total_battles,
            "coverPct": round(battles / total_battles * 100, 1) if total_battles else None,
            "windowMin": int(WINDOW_MIN),
            "comebackLine": int(COMEBACK_LINE * 100),
            "bins": [b[2] for b in BINS],
            "lowBuckets": [b[2] for b in LOW_BUCKETS],
            "listLimit": LIST_LIMIT,
            "note": ("样本＝站内已生成分钟级复盘、且第 " + str(int(WINDOW_MIN)) + " 分钟后仍有胜率采样的对局（"
                     + str(battles) + " 局 / 全量 " + str(total_battles) + " 局，覆盖率 "
                     + str(round(battles / total_battles * 100, 1) if total_battles else 0) + "%）。其中直播期真实预测 "
                     + str(live) + " 局、赛后重放 " + str(replay) + " 局（重放局曲线波动大，仅列举、不参与统计）；另有 "
                     + str(too_early) + " 局在第 " + str(int(WINDOW_MIN)) + " 分钟后已无采样，未计入。"
                     "口径：胜方视角胜率，低点从第 " + str(int(WINDOW_MIN)) + " 分钟起算——开局 1–3 分钟模型缺对线期特征时会外推极端先验值，"
                     "把那段算进来会得出假的翻盘结论。"),
        },
        "bins": [[BINS[i][2], per_bin[i]] for i in range(len(BINS))],
        "lowBuckets": [[LOW_BUCKETS[i][2], per_low[i]] for i in range(len(LOW_BUCKETS))],
        "stats": {
            "comebackCount": len(comebacks),
            "comebackRate": round(len(comebacks) / battles * 100, 1) if battles else 0,
            "deepest": round(min(lows), 3) if lows else None,
            "medianLow": round(med, 3) if lows else None,
        },
        "comebacks": comebacks[:LIST_LIMIT],
    }
    OUT_PATH.write_text("KPL_COMEBACK = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                        encoding="utf-8")
    print(f"comeback: {battles} 局（live {live} / replay {replay}）· 翻盘 {len(comebacks)} 局 · "
          f"全量 {total_battles} 局 · {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
