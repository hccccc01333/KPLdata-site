# -*- coding: utf-8 -*-
"""BP 数据 v3：全维度紧凑明细（战队/对手/年份/赛事/赛段/局序/阵营/赛果 全交叉）。

输出：assets/bp.js
  KPL_BP = { template, heroes, leagues, stages, games, prior, totalBattles }
  games 行: [year, leagueId, stage, t1, t2, gameNo, winCamp, "act,camp,hidx;..."]
运行：python build_bp_data.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
TOP_PRIOR = 30

STAGE_CN = {
    "regular_season": "常规赛", "playoff": "季后赛", "group_phase": "小组赛",
    "cgs1": "常规赛·第 1 轮", "cgs2": "常规赛·第 2 轮", "cgs3": "常规赛·第 3 轮",
    "kws": "卡位赛", "jhs": "季后赛", "js": "总决赛", "lts": "擂台赛", "zjs": "总决赛",
    "dbtts": "单败淘汰赛", "sbtts": "双败淘汰赛", "kpl_select": "选拔赛",
    "select": "季前赛", "other_select": "选拔赛",
}


def main() -> None:
    leagues_meta = {}
    try:
        for lg in json.loads((HIST / "leagues.json").read_text(encoding="utf-8")):
            leagues_meta[str(lg["league_id"])] = str(lg.get("league_name") or "")
    except Exception:
        pass

    template = Counter()
    hero_count = Counter()
    prior = [Counter() for _ in range(20)]
    games = []
    n_ok = 0

    for lg_dir in sorted(HIST.iterdir()):
        mdir = lg_dir / "matches"
        if not mdir.is_dir():
            continue
        lid = lg_dir.name
        for f in sorted(mdir.glob("*.json")):
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            match = obj.get("match") or {}
            year = str(match.get("start_time") or "")[:4]
            if not year.isdigit():
                year = ""
            stage = STAGE_CN.get(str(match.get("match_stage_name") or ""),
                                  str(match.get("match_stage_name") or ""))
            for det in obj.get("battles") or []:
                if not isinstance(det, dict):
                    continue
                bp = det.get("bp_list") or []
                if len(bp) < 20:
                    continue
                bp = bp[:20]
                t1 = str((det.get("camp1") or {}).get("team_name") or "")
                t2 = str((det.get("camp2") or {}).get("team_name") or "")
                if not t1 or not t2:
                    continue
                game_no = int(det.get("battle_seq") or 0)
                win_camp = int(det.get("win_camp") or 0)
                seq = tuple(
                    (0 if str(x.get("is_ban_or_pick")) in ("0", 0) else 1, int(x.get("camp") or 0))
                    for x in bp
                )
                template[seq] += 1

                hands = []
                ok = True
                for k, x in enumerate(bp):
                    hn = str(x.get("hero_name") or "").strip()
                    camp = int(x.get("camp") or 0)
                    if not hn or camp not in (1, 2):
                        ok = False
                        break
                    is_ban = 0 if str(x.get("is_ban_or_pick")) in ("0", 0) else 1
                    prior[k][hn] += 1
                    hero_count[hn] += 1
                    hands.append([is_ban, camp, hn])
                if not ok or len(hands) != 20:
                    continue
                games.append([year, lid, stage, t1, t2, game_no, win_camp, hands])
                n_ok += 1
        print(f"scanned {lid}: {n_ok} battles", flush=True)

    tpl, tpl_n = template.most_common(1)[0]
    print(f"template votes: {tpl_n}/{n_ok}")

    hero_list = [h for h, _ in hero_count.most_common()]
    hero_idx = {h: i for i, h in enumerate(hero_list)}

    games_out = []
    for year, lid, stage, t1, t2, gno, wc, hands in games:
        encoded = ";".join(f"{a},{c},{hero_idx[h]}" for a, c, h in hands)
        games_out.append([year, lid, stage, t1, t2, gno, wc, encoded])

    prior_out = []
    for k, counter in enumerate(prior):
        total = sum(counter.values()) or 1
        prior_out.append([[h, c, round(c / total, 4)] for h, c in counter.most_common(TOP_PRIOR)])

    used_leagues = {}
    for g in games_out:
        used_leagues[g[1]] = leagues_meta.get(g[1], g[1])

    data = {
        "template": [[a, c] for a, c in tpl],
        "heroes": hero_list,
        "leagues": used_leagues,
        "games": games_out,
        "prior": prior_out,
        "totalBattles": n_ok,
    }
    path = SITE / "assets" / "bp.js"
    path.write_text("KPL_BP = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                    encoding="utf-8")
    print(f"\nbp.js: {path.stat().st_size/1024:.0f} KB | games: {len(games_out)} | leagues: {len(used_leagues)}")


if __name__ == "__main__":
    main()
