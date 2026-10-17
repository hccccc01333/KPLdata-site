# -*- coding: utf-8 -*-
"""精选对局索引（V4 阶段四）：把"值得看的局"用可核对的规则筛出来。

规则（全部写在 picks.html 页面上，可复核）：
  翻盘局  收官胜方在某个时刻的胜率 <= 20%
  拉锯局  时长 >= 18 分钟
  波动局  任意 3 个连续采样点内胜率变化 >= 35pp
  资源战  结构性事件（推塔/暴君/主宰/风暴）>= 12 个
输出：assets/picks.js = KPL_PICKS = {updatedAt, rules, rows:[...]}
用法：python build_picks.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
REPLAY = SITE / "assets" / "replay"
OUT = SITE / "assets" / "picks.js"

# 阈值按 202 局的分位数定：每个标签只保留 15–25% 的分位，避免"人人都精选"
MIN_PROB = 0.10          # 翻盘：收官胜方曾低到 10% 以下（p10≈0.02 / p25≈0.16）
LONG_MIN = 20            # 拉锯：>=20 分钟（p75≈17.7）
SWING_PP = 0.55          # 波动：3 个采样点内 >=55pp（p75≈0.54）
EVENTS_MIN = 16          # 资源战：结构性事件数（p75≈14）


def analyze(b: dict) -> dict | None:
    frames = b.get("frames") or []
    if len(frames) < 5:
        return None
    win = int(b.get("win") or 0)
    if win not in (1, 2):
        return None
    # 统一到"收官胜方"视角：p_win = 胜方的胜率
    def p_win(f):
        p = f.get("p")
        if p is None:
            return None
        return p if win == 1 else 1 - p

    seq = [(f.get("m") or 0, p_win(f)) for f in frames if p_win(f) is not None]
    tags: list[dict] = []

    # 翻盘：胜方在【第 6 分钟之后】且【经济落后 >= 3000】时胜率仍 <= MIN_PROB
    # 只看概率会被早期低置信采样骗到（第 2 分钟 2% 但金差只有 +225 不是翻盘）；
    # 必须同时满足"时间够晚 + 经济真的落后"，才算可核对的翻盘局。
    candidates = []
    for f in frames:
        m = float(f.get("m") or 0)
        p = p_win(f)
        if p is None or m < 6:
            continue
        gd = int(f.get("gd") or 0)
        gd_win = gd if win == 1 else -gd
        if gd_win > -3000:
            continue
        if p <= MIN_PROB:
            candidates.append((p, m, gd_win))
    worst_pick = None
    if candidates:
        p_w, m_w, gd_w = min(candidates, key=lambda x: x[0])
        worst_pick = (p_w, m_w, gd_w)
        tags.append({"k": "comeback", "label": "翻盘局",
                     "note": f"第 {m_w:.0f} 分钟胜率仅 {p_w * 100:.0f}%，经济落后 {abs(gd_w):,}"})

    # 拉锯
    dur = float(b.get("dur") or 0)
    if dur >= LONG_MIN:
        tags.append({"k": "long", "label": "拉锯局", "note": f"时长 {dur:.0f} 分钟"})

    # 波动：3 个采样点内 >= SWING_PP
    swing_best = (0.0, None, None)
    for i in range(len(seq) - 2):
        d = abs(seq[i + 2][1] - seq[i][1])
        if d > swing_best[0]:
            swing_best = (d, seq[i][0], seq[i + 2][0])
    if swing_best[0] >= SWING_PP:
        tags.append({"k": "swing", "label": "波动局",
                     "note": f"{swing_best[1]:.0f}–{swing_best[2]:.0f} 分钟内胜率变化 {swing_best[0] * 100:.0f}pp"})

    # 资源战
    ev = len(b.get("events") or [])
    if ev >= EVENTS_MIN:
        tags.append({"k": "events", "label": "资源战", "note": f"结构性事件 {ev} 个"})

    if not tags:
        return None
    score = 0.0
    for t in tags:
        score += {"comeback": 4.0, "long": 1.5, "swing": 2.5, "events": 1.0}.get(t["k"], 1.0)
    score += swing_best[0] * 4 + dur / 12 + ev / 20
    return {
        "battleId": b.get("battleId"), "seq": int(b.get("seq") or 0),
        "dur": round(dur, 1), "win": win, "t1": b.get("t1"), "t2": b.get("t2"),
        "winner": b.get("t1") if win == 1 else b.get("t2"),
        # 最低胜率点：只记"满足翻盘条件"的那一个（第 6 分钟后 + 经济落后 3000+），
        # 这样卡片上的"最低胜率 X%"和翻盘标签是同一件事，不会一个标签两种口径
        "swing": round(swing_best[0], 3),
        "minProb": round(worst_pick[0], 3) if worst_pick else None,
        "minMinute": round(worst_pick[1], 1) if worst_pick else None,
        "events": ev,
        "tags": tags,
        "score": round(score, 2),
    }


def main() -> None:
    t0 = time.time()
    index = {}
    idx_path = REPLAY / "index.js"
    if idx_path.exists():
        raw = idx_path.read_text(encoding="utf-8")
        index = json.loads(raw[raw.index("=") + 1:].rstrip().rstrip(";"))

    rows = []
    total_battles = 0
    for mid, meta in index.items():
        pkg_path = REPLAY / f"{mid}.json"
        if not pkg_path.exists():
            continue
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for b in pkg.get("battles") or []:
            total_battles += 1
            r = analyze(b)
            if not r:
                continue
            r["matchId"] = mid
            r["date"] = str(meta.get("date") or "")
            rows.append(r)

    rows.sort(key=lambda r: (-r["score"], r["date"]))
    payload = {
        "updatedAt": time.strftime("%Y-%m-%d %H:%M:%S"),
        "rules": [
            {"k": "comeback", "label": "翻盘局",
             "rule": f"第 6 分钟之后、经济落后 ≥3,000 时，收官胜方胜率仍 ≤ {int(MIN_PROB * 100)}%"},
            {"k": "long", "label": "拉锯局", "rule": f"时长 ≥ {LONG_MIN} 分钟"},
            {"k": "swing", "label": "波动局", "rule": f"任意 3 个采样点内胜率变化 ≥ {int(SWING_PP * 100)}pp"},
            {"k": "events", "label": "资源战", "rule": f"结构性事件（推塔/暴君/主宰/风暴）≥ {EVENTS_MIN} 个"},
        ],
        "totalBattles": total_battles,
        "picked": min(len(rows), 48),
        "rows": rows[:48],
    }
    OUT.write_text("KPL_PICKS = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    by_tag = {}
    for r in rows:
        for t in r["tags"]:
            by_tag[t["k"]] = by_tag.get(t["k"], 0) + 1
    print(f"picks.js: {len(payload['rows'])} 条精选 / {len(rows)} 局达标 · {by_tag} · "
          f"{OUT.stat().st_size / 1024:.0f} KB · {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
