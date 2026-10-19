# -*- coding: utf-8 -*-
"""职业哥同款 · 英雄 → 选手 → 出装 / 召唤师技能 / 代表对局 的联合数据。

口径（页面必须原样展示，不得改造）：
  数据来源   官方赛事接口，data/history/{league}/matches/*.json，全部 2019–2026 已完赛对局
  统计粒度   选手 × 英雄（同一名选手在不同赛事、不同战队时期合并计一）
  出装       该选手使用该英雄时，每局 6 件成品装的出场率（分母 = 该选手该英雄的局数）
  首件       装备栏第 1 格
  代表对局   优先取"胜局"，再按该局 KDA 降序，最多 3 局；只能点开站内真实对局
  最低样本   英雄累计 >= MIN_HERO_GAMES 局；选手用该英雄 >= MIN_PLAYER_GAMES 局
  **边界**   这是职业实战记录，不是排位上分推荐（职业赛与排位赛的英雄/装备/协同环境不同）

输出：assets/pro_hero.js —— KPL_PRO = {meta, eq:{装备名:图标}, su:{技能名:图标}, heroes:{英雄:{n, players:[...]}}}
用法：python build_pro_hero.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
OUT = SITE / "assets" / "pro_hero.js"

MIN_HERO_GAMES = 5        # 英雄累计样本门槛
MIN_PLAYER_GAMES = 3      # 选手-英雄样本门槛
MAX_PLAYERS = 8           # 每个英雄最多展示的选手数
MAX_EQUIPS = 5            # 每人最多展示的装备数
MAX_FIRST = 3
MAX_SUMMON = 2
MAX_REPS = 3
CN_TZ = timezone(timedelta(hours=8))


def num(v) -> float:
    """宽松数值转换：非数值一律记 0，避免脏数据污染均值。"""
    try:
        out = float(v)
    except (TypeError, ValueError):
        return 0.0
    return out if out == out and abs(out) != float("inf") else 0.0


def date_of(match: dict) -> str:
    """赛程归属日期（北京时区）。支持 ISO 文本与时间戳两种 start_time。"""
    st = str(match.get("start_time") or "")
    mm = re.search(r"(\d{4})-(\d{2})-(\d{2})", st)
    if mm:
        return f"{mm.group(1)}-{mm.group(2)}-{mm.group(3)}"
    try:
        v = float(st)
        if v > 1e11:
            v /= 1000.0
        return datetime.fromtimestamp(v, CN_TZ).strftime("%Y-%m-%d")
    except Exception:
        return ""


def main() -> None:
    t0 = time.time()
    # hero -> player -> 聚合
    agg: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {
        "g": 0, "w": 0, "kda": 0.0, "gold": 0, "mvp": 0,
        "pos": defaultdict(int), "team": defaultdict(int),
        "eq": defaultdict(int), "fe": defaultdict(int), "su": defaultdict(int),
        "reps": [],
    }))
    hero_games: dict[str, int] = defaultdict(int)
    icons_eq: dict[str, str] = {}
    icons_su: dict[str, str] = {}
    n_match = n_battle = 0

    for lg_dir in sorted(HIST.iterdir()):
        mdir = lg_dir / "matches"
        if not mdir.is_dir():
            continue
        for f in sorted(mdir.glob("*.json")):
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            match = obj.get("match") or {}
            mid = str(match.get("match_id") or f.stem)
            date = date_of(match)
            battles = [b for b in (obj.get("battles") or []) if isinstance(b, dict)]
            if not battles:
                continue
            n_match += 1
            for b in battles:
                plist = [p for p in (b.get("battle_player_list") or []) if isinstance(p, dict)]
                if len(plist) < 10:
                    continue          # 阵容不完整，不参与统计
                n_battle += 1
                win_camp = int(b.get("win_camp") or 0)
                c1 = str((b.get("camp1") or {}).get("team_name") or "").strip()
                c2 = str((b.get("camp2") or {}).get("team_name") or "").strip()
                bid = str(b.get("battle_id") or "")
                for p in plist:
                    hero = str(p.get("hero_name") or "").strip()
                    name = str(p.get("player_name") or p.get("actual_player_name") or "").strip()
                    if not hero or not name:
                        continue
                    try:
                        camp = int(p.get("camp") or 0)
                    except (TypeError, ValueError):
                        camp = 0
                    if camp not in (1, 2):
                        continue
                    won = 1 if camp == win_camp else 0
                    hero_games[hero] += 1
                    rec = agg[hero][name]
                    rec["g"] += 1
                    rec["w"] += won
                    rec["kda"] += num(p.get("kda"))
                    rec["gold"] += int(num(p.get("gold")))
                    if num(p.get("is_mvp")) or num(p.get("is_lose_mvp")):
                        rec["mvp"] += 1
                    pos = str(p.get("position_desc") or "").strip()
                    if pos:
                        rec["pos"][pos] += 1
                    tm = str(p.get("team_name") or "").strip()
                    if tm:
                        rec["team"][tm] += 1

                    eqs = p.get("BriefEquipList")
                    if isinstance(eqs, list):
                        for i, e in enumerate(eqs[:6]):
                            if not isinstance(e, dict):
                                continue
                            en = str(e.get("equip_name") or "").strip()
                            if not en:
                                continue
                            ec = str(e.get("equip_icon") or "")
                            if ec and en not in icons_eq:
                                icons_eq[en] = ec
                            rec["eq"][en] += 1
                            if i == 0:
                                rec["fe"][en] += 1
                    sa = p.get("SummonerAbilityInfo")
                    if isinstance(sa, dict):
                        sn = str(sa.get("summoner_ability_name") or "").strip()
                        if sn:
                            sc = str(sa.get("summoner_ability_icon") or "")
                            if sc and sn not in icons_su:
                                icons_su[sn] = sc
                            rec["su"][sn] += 1

                    if bid:
                        rec["reps"].append({
                            "b": bid, "m": mid, "d": date,
                            "vs": c1 if camp == 2 else c2,
                            "r": won,
                            "k": round(num(p.get("kda")), 2),
                        })

    def top_counts(d: dict, k: int) -> list[tuple[str, int]]:
        return sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:k]

    heroes: dict[str, dict] = {}
    for hero, by_player in agg.items():
        total = hero_games.get(hero, 0)
        if total < MIN_HERO_GAMES:
            continue
        rows = []
        for name, rec in by_player.items():
            g = rec["g"]
            if g < MIN_PLAYER_GAMES:
                continue
            eq_top = top_counts(rec["eq"], MAX_EQUIPS)
            fe_top = top_counts(rec["fe"], MAX_FIRST)
            su_top = top_counts(rec["su"], MAX_SUMMON)
            # 代表对局：胜局优先，其次 KDA 高
            reps = sorted(rec["reps"], key=lambda r: (-int(r["r"]), -float(r["k"]), r["d"]))[:MAX_REPS]
            pos = top_counts(rec["pos"], 1)
            team = top_counts(rec["team"], 1)
            rows.append({
                "n": name,
                "t": team[0][0] if team else "",
                "pos": pos[0][0] if pos else "",
                "g": g, "w": rec["w"],
                "kda": round(rec["kda"] / g, 2),
                "gold": round(rec["gold"] / g),
                "mvp": rec["mvp"],
                "eq": [e for e, _ in eq_top],
                "eqr": [round(c * 100 / g) for _, c in eq_top],
                "fe": [e for e, _ in fe_top],
                "su": [e for e, _ in su_top],
                "reps": reps,
            })
        if not rows:
            continue
        rows.sort(key=lambda r: (-r["g"], -r["kda"]))
        heroes[hero] = {"n": total, "players": rows[:MAX_PLAYERS]}

    out = {
        "meta": {
            "builtAt": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M"),
            "matches": n_match,
            "battles": n_battle,
            "heroes": len(heroes),
            "minHeroGames": MIN_HERO_GAMES,
            "minPlayerGames": MIN_PLAYER_GAMES,
            "note": "职业实战记录，不是排位上分推荐；出装百分比为该选手使用该英雄时的出场率",
        },
        "eq": icons_eq,
        "su": icons_su,
        "heroes": heroes,
    }
    OUT.write_text("KPL_PRO = " + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"pro_hero: {len(heroes)} 英雄 · {n_battle} 局 / {n_match} 场 · {kb:.0f} KB · "
          f"装备图标 {len(icons_eq)} · {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
