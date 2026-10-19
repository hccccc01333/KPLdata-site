# -*- coding: utf-8 -*-
"""英雄成长曲线（8 / 12 / 16 分钟） · 数据构建（V5 阶段5 剩项7）。

数据链：
  assets/replay/<matchId>.json  → 分路序名单 names（0-4 = camp1，5-9 = camp2，按 对抗路→游走）
                                 + frames[].g[camp][lane] 分钟经济
  assets/games/<lg>.json        → 选手 → 英雄（按 局内选手名 对齐）
两者按 battleId + 选手名 join，全部 200 余局都能对上。

硬边界（必须原样带到页面）：
  · 只有约 200 局有分钟级快照，约占全量 2%，曲线**不代表全量英雄强度**；
  · 只有样本 ≥ MIN_GAMES 次出场的英雄才输出，样本不足的英雄在页面上显式说明「不展示」；
  · 8/12/16 分钟取**最近**的采样点，与目标分钟相差 > MAX_GAP 分钟则不计入该点。

输出：assets/hero_growth.js
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

SITE = Path(__file__).resolve().parent
REPLAY_DIR = SITE / "assets" / "replay"
GAMES_DIR = SITE / "assets" / "games"
GAMES_INDEX = GAMES_DIR / "index.js"
OUT_PATH = SITE / "assets" / "hero_growth.js"

TARGETS = (8, 12, 16)
MAX_GAP = 2.0
MIN_GAMES = 5
LANES = ["对抗路", "打野", "中路", "发育路", "游走"]


def jload_js(path: Path, default):
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text[text.index("=") + 1:].rstrip().rstrip(";"))
    except Exception:
        return default


def main() -> None:
    t0 = time.time()
    total_battles = 0
    gindex = jload_js(GAMES_INDEX, {})
    total_battles = sum(len((v or {}).get("b") or []) for v in gindex.values())

    game_cache: dict[str, dict] = {}
    acc: dict[str, dict] = defaultdict(lambda: {
        "n": 0,
        "sum": {t: 0.0 for t in TARGETS},
        "cnt": {t: 0 for t in TARGETS},
        "lanes": Counter(),
    })
    battles = 0
    appearances = 0

    files = sorted(p for p in REPLAY_DIR.glob("*.json") if p.name[0].isdigit())
    for fp in files:
        try:
            pkg = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        lg = str(pkg.get("lg") or "")
        if lg not in game_cache:
            gpath = GAMES_DIR / f"{lg}.json"
            game_cache[lg] = json.loads(gpath.read_text(encoding="utf-8")) if gpath.exists() else {}
        gm = game_cache[lg]
        for b in pkg.get("battles") or []:
            names = b.get("names") or []
            frames = b.get("frames") or []
            if len(names) != 10 or not frames:
                continue
            pack = gm.get(str(b.get("battleId") or "")) or {}
            players = pack.get("players") or []
            if not players:
                continue
            hero_of = {str(p.get("n") or ""): str(p.get("h") or "") for p in players}
            battles += 1
            for camp in (1, 2):
                for lane in range(5):
                    nm = names[lane] if camp == 1 else names[lane + 5]
                    hero = hero_of.get(nm) or ""
                    if not hero:
                        continue
                    got = {}
                    for t in TARGETS:
                        best = None
                        for f in frames:
                            m = float(f.get("m") or 0)
                            g = f.get("g") or []
                            row = g[camp - 1] if len(g) >= camp else []
                            if lane >= len(row) or row[lane] is None:
                                continue
                            d = abs(m - t)
                            if d <= MAX_GAP and (best is None or d < best[0]):
                                best = (d, float(row[lane]))
                        if best is not None:
                            got[t] = best[1]
                    if not got:
                        continue
                    appearances += 1
                    e = acc[hero]
                    e["n"] += 1
                    e["lanes"][LANES[lane]] += 1
                    for t, v in got.items():
                        e["sum"][t] += v
                        e["cnt"][t] += 1

    heroes = {}
    for hero, e in acc.items():
        if e["n"] < MIN_GAMES:
            continue
        g = []
        for t in TARGETS:
            g.append(round(e["sum"][t] / e["cnt"][t]) if e["cnt"][t] else None)
        if all(v is None for v in g):
            continue
        heroes[hero] = {
            "n": e["n"],
            "g": g,
            "lanes": dict(e["lanes"].most_common(3)),
        }

    data = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "meta": {
            "targets": list(TARGETS),
            "battles": battles,
            "appearances": appearances,
            "totalBattles": total_battles,
            "coverPct": round(battles / total_battles * 100, 1) if total_battles else None,
            "minGames": MIN_GAMES,
            "maxGap": MAX_GAP,
            "note": ("样本＝站内已生成分钟级快照的对局（" + str(battles) + " 局 / 全量 " + str(total_battles) +
                     " 局），8/12/16 分钟取最近采样点（±" + str(int(MAX_GAP)) + " 分钟内）。"
                     "样本量不足 " + str(MIN_GAMES) + " 次出场的英雄不展示，避免用几局数据下结论。"),
        },
        "heroes": heroes,
    }
    OUT_PATH.write_text("KPL_HERO_GROWTH = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                        encoding="utf-8")
    print(f"hero-growth: {battles} 局 · 出场样本 {appearances} · 达标英雄 {len(heroes)} 个 · "
          f"{time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
