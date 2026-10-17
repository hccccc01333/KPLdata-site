# -*- coding: utf-8 -*-
"""生成全站搜索索引 assets/search.js（统一搜索 · 深链覆盖全历史）。

来源（都在本站 assets/ 里，不依赖 02 仓库）：
  seasons.js        全部赛事的战队 / 选手 / 英雄聚合
  players_detail.js 选手资料（485 人，含只打历史赛季的选手）
  schedule_all.js   2019–2026 全部 2,884 场比赛

输出：KPL_SEARCH = [{k, n, s, h, i?}]  k=类型 n=名称 s=副标题 h=深链 i=图标
运行：python build_search_index.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
ASSETS = SITE / "assets"
OUT = ASSETS / "search.js"


def jload_js(path: Path):
    text = path.read_text(encoding="utf-8")
    body = text[text.index("=") + 1:].rstrip().rstrip(";")
    return json.loads(body)


def main() -> None:
    seasons = jload_js(ASSETS / "seasons.js")
    players_detail = jload_js(ASSETS / "players_detail.js")
    schedule = jload_js(ASSETS / "schedule_all.js")
    scopes = seasons.get("scopes") or {}
    allscope = scopes.get("all") or {}

    items: list[dict] = []
    seen: set[str] = set()

    def add(kind: str, name: str, sub: str, href: str, icon: str = "") -> None:
        key = f"{kind}|{name}|{href}"
        if key in seen or not name:
            return
        seen.add(key)
        row = {"k": kind, "n": name, "s": sub, "h": href}
        if icon:
            row["i"] = icon
        items.append(row)

    # 战队（全部赛事聚合，83 支 → 直达战队详情页 team.html）
    for t in allscope.get("teams") or []:
        name = str(t.get("team", ""))
        add("战队", name, f"{t.get('matches', 0)} 场 · 单局胜率 {round(float(t.get('wr') or 0) * 100, 1)}%",
            "team.html?id=" + name, t.get("icon", ""))

    # 选手：选手资料全量（含历史选手）+ 聚合榜里的（取并集）
    names = {}
    for name, v in players_detail.items():
        if isinstance(v, dict) and v.get("games") is not None:
            names[name] = (v.get("team", ""), v.get("icon", ""), v.get("games", 0))
    for p in allscope.get("players") or []:
        names.setdefault(p.get("name", ""), (p.get("team", ""), p.get("icon", ""), p.get("games", 0)))
    for name, (team, icon, games) in names.items():
        if not name:
            continue
        add("选手", name, f"{team} · {games} 局", "player.html?id=" + name, icon)

    # 英雄（133 个，全部赛事）
    for h in allscope.get("heroes") or []:
        add("英雄", h.get("name", ""), f"{h.get('games', 0)} 局 · 胜率 {round(float(h.get('wr') or 0) * 100, 1)}%",
            "hero.html?id=" + str(h.get("name", "")), h.get("icon", ""))

    # 比赛（2019–2026 全部，直接深链到比赛页）
    for m in schedule:
        mid = str(m.get("matchId") or "")
        if not mid:
            continue
        add("比赛", f"{m.get('team1', '')} vs {m.get('team2', '')}",
            f"{m.get('date', '')} · {m.get('leagueName', '')}{(' · ' + m['stage']) if m.get('stage') else ''}",
            "match.html?id=" + mid, m.get("icon1", ""))

    payload = "KPL_SEARCH = " + json.dumps(items, ensure_ascii=False, separators=(",", ":")) + ";\n"
    OUT.write_text(payload, encoding="utf-8")
    by_kind: dict[str, int] = {}
    for it in items:
        by_kind[it["k"]] = by_kind.get(it["k"], 0) + 1
    print(f"search.js: {len(items)} 条 · {by_kind} · {OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
