# -*- coding: utf-8 -*-
"""聚合英雄出装与召唤师技能（来自全历史回补的 BriefEquipList）。

输出：assets/equips.js —— KPL_EQUIPS = { 英雄名: {games, sum:[{name,icon,n,rate}], first:[...], summon:[...]} }
运行：python build_equip_data.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"


def main() -> None:
    hero_games = defaultdict(int)
    equip_cnt = defaultdict(lambda: defaultdict(lambda: {"n": 0, "icon": ""}))
    first_cnt = defaultdict(lambda: defaultdict(lambda: {"n": 0, "icon": ""}))
    summon_cnt = defaultdict(lambda: defaultdict(lambda: {"n": 0, "icon": ""}))

    n_files = 0
    for lg_dir in sorted(HIST.iterdir()):
        mdir = lg_dir / "matches"
        if not mdir.is_dir():
            continue
        for f in mdir.glob("*.json"):
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            n_files += 1
            for det in obj.get("battles") or []:
                if not isinstance(det, dict):
                    continue
                for p in det.get("battle_player_list") or []:
                    if not isinstance(p, dict):
                        continue
                    hn = str(p.get("hero_name") or "").strip()
                    if not hn:
                        continue
                    hero_games[hn] += 1
                    eqs = p.get("BriefEquipList") or []
                    if isinstance(eqs, list):
                        for i, e in enumerate(eqs[:8]):
                            if not isinstance(e, dict):
                                continue
                            name = str(e.get("equip_name") or "").strip()
                            if not name:
                                continue
                            icon = str(e.get("equip_icon") or "")
                            slot = equip_cnt[hn][name]
                            slot["n"] += 1
                            if icon and not slot["icon"]:
                                slot["icon"] = icon
                            if i == 0:
                                fs = first_cnt[hn][name]
                                fs["n"] += 1
                                if icon and not fs["icon"]:
                                    fs["icon"] = icon
                    sa = p.get("SummonerAbilityInfo")
                    if isinstance(sa, dict):
                        sname = str(sa.get("summoner_ability_name") or "").strip()
                        if sname:
                            s = summon_cnt[hn][sname]
                            s["n"] += 1
                            if sa.get("summoner_ability_icon") and not s["icon"]:
                                s["icon"] = str(sa["summoner_ability_icon"])
        print(f"scanned {lg_dir.name}: {n_files} matches total", flush=True)

    out = {}
    for hn, g in hero_games.items():
        if g < 5:
            continue
        def top(d, k):
            arr = sorted(d.items(), key=lambda kv: -kv[1]["n"])[:k]
            return [{"name": name, "icon": v["icon"], "n": v["n"],
                     "rate": round(v["n"] / g, 3)} for name, v in arr if v["n"] >= 2]
        out[hn] = {
            "games": g,
            "sum": top(equip_cnt[hn], 10),
            "first": top(first_cnt[hn], 4),
            "summon": top(summon_cnt[hn], 3),
        }
    path = SITE / "assets" / "equips.js"
    path.write_text("KPL_EQUIPS = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n",
                    encoding="utf-8")
    print(f"\nequips.js: {path.stat().st_size/1024:.0f} KB | heroes with equip data: {len(out)}")


if __name__ == "__main__":
    main()
