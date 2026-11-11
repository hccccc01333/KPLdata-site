# -*- coding: utf-8 -*-
"""BP 数据 v5：全维度紧凑明细，支持 14 / 16 / 18 / 20 手四种 BP 赛制。

输出：assets/bp.js
  KPL_BP = { template, templates, heroes, leagues, stages, games, prior, priors,
             totalBattles, totalBattlesByFormat }
  games 行: [year, leagueId, stage, t1, t2, gameNo, winCamp, "act,camp,hidx;...", fmt]
  - 14 手：2016 赛季（每边 2 ban + 10 pick）
  - 16 手：2017 赛季（每边 3 ban + 10 pick）
  - 18 手：2018–2024 旧赛制（每边 4 ban + 10 pick）
  - 20 手：2024 年度总决赛起的现赛制（每边 5 ban + 10 pick）
运行：python build_bp_data.py
"""
from __future__ import annotations

import csv
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

FORMATS = ("14", "16", "18", "20")

# 玩加历史赛事 → 年份 / 站点赛事 ID / BP 手数
LEGACY_EVENTS = {
    "414": ("2016", "20160001", "14"),
    "416": ("2017", "20170001", "16"),
    "533": ("2017", "20170002", "16"),
    "592": ("2018", "20180001", "18"),
    "704": ("2018", "20180002", "18"),
    "793": ("2019", "20190001", "18"),
    "866": ("2019", "20190004", "18"),
}
LEGACY_LEAGUE_NAMES = {
    "20160001": "2016KPL秋季赛", "20170001": "2017KPL春季赛",
    "20170002": "2017KPL秋季赛", "20180001": "2018KPL春季赛",
    "20180002": "2018KPL秋季赛",
}
LEGACY_PREFIX = PROJ / "data" / "external" / "wanplus"

# 早期赛制：首轮 ban 后接 6 选，再 4 选；2016 每边 2 ban，2017 每边 3 ban。
LEGACY_TEMPLATES = {
    "14": [(0, 1), (0, 2), (0, 1), (0, 2),
           (1, 1), (1, 2), (1, 2), (1, 1), (1, 1), (1, 2),
           (1, 2), (1, 1), (1, 1), (1, 2)],
    "16": [(0, 1), (0, 2), (0, 1), (0, 2), (0, 1), (0, 2),
           (1, 1), (1, 2), (1, 2), (1, 1), (1, 1), (1, 2),
           (1, 2), (1, 1), (1, 1), (1, 2)],
    "18": [(0, 1), (0, 2), (0, 1), (0, 2),
           (1, 1), (1, 2), (1, 2), (1, 1), (1, 1), (1, 2),
           (0, 2), (0, 1), (0, 2), (0, 1),
           (1, 2), (1, 1), (1, 1), (1, 2)],
}


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def legacy_games(
    event_id: str, year: str, lid: str, fmt: str, match_key: str = "match_id"
) -> tuple[list[list], dict]:
    """把玩加历史局转成 [year, lid, stage, t1, t2, gameNo, winCamp, hands, fmt]。"""
    base = LEGACY_PREFIX / f"event_{event_id}"
    if not (base / "games.csv").exists():
        return [], {}
    matches = {str(r[match_key]): r for r in read_csv(base / "matches.csv")}
    games = read_csv(base / "games.csv")
    players: dict[str, list[dict]] = {}
    for row in read_csv(base / "player_stats.csv"):
        players.setdefault(str(row["game_id"]), []).append(row)
    bans: dict[str, list[dict]] = {}
    for row in read_csv(base / "bans.csv"):
        bans.setdefault(str(row["game_id"]), []).append(row)

    template = LEGACY_TEMPLATES[fmt]
    out: list[list] = []
    heroes: dict[str, int] = {}
    for game in games:
        gid = str(game["game_id"])
        prows = players.get(gid, [])
        brows = bans.get(gid, [])
        if len(prows) != 10:
            continue
        picks = {1: [], 2: []}
        for row in prows:
            side = _int(row.get("side"))
            if side in picks and row.get("hero_name"):
                picks[side].append((_int(row.get("pick_order")), str(row["hero_name"]).strip()))
        bans_by_side = {1: [], 2: []}
        for row in brows:
            side = _int(row.get("side"))
            if side in bans_by_side and row.get("hero_name"):
                bans_by_side[side].append((_int(row.get("ban_order")), str(row["hero_name"]).strip()))
        for side in (1, 2):
            picks[side].sort()
            bans_by_side[side].sort()
        if any(len(picks[s]) != 5 for s in (1, 2)):
            continue
        if any(len(bans_by_side[s]) != sum(1 for a, c in template if a == 0 and c == s) for s in (1, 2)):
            continue

        pi = {1: 0, 2: 0}
        bi = {1: 0, 2: 0}
        hands = []
        seen = set()
        ok = True
        for act, camp in template:
            if act == 0:
                idx = bi[camp]
                bi[camp] += 1
                if idx >= len(bans_by_side[camp]):
                    ok = False
                    break
                hero = bans_by_side[camp][idx][1]
            else:
                idx = pi[camp]
                pi[camp] += 1
                if idx >= len(picks[camp]):
                    ok = False
                    break
                hero = picks[camp][idx][1]
            if not hero or hero in seen:
                ok = False
                break
            seen.add(hero)
            hands.append([act, camp, hero])
        if not ok or len(hands) != len(template):
            continue

        win_camp = _int(game.get("winner_side"))
        if win_camp not in (1, 2):
            winner = str(game.get("winner") or "")
            win_camp = 1 if winner and winner == str(game.get("team1") or "") else 2
        mid = str(game[match_key])
        meta = matches.get(mid, {})
        out.append([
            year, lid, str(meta.get("stage") or game.get("stage") or ""),
            str(game.get("team1") or ""), str(game.get("team2") or ""),
            _int(game.get("game_no")), win_camp, hands, fmt,
        ])
        for _, _, hero in hands:
            heroes[hero] = heroes.get(hero, 0) + 1
    return out, heroes


def main() -> None:
    leagues_meta = {}
    try:
        for lg in json.loads((HIST / "leagues.json").read_text(encoding="utf-8")):
            leagues_meta[str(lg["league_id"])] = str(lg.get("league_name") or "")
    except Exception:
        pass

    state = {
        fmt: {"template": Counter(), "prior": [Counter() for _ in range(int(fmt))],
              "games": [], "n": 0}
        for fmt in FORMATS
    }
    hero_count = Counter()

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
                if len(bp) not in (18, 20):
                    continue
                fmt = str(len(bp))
                picks = sum(1 for x in bp if str(x.get("is_ban_or_pick")) in ("1", True, "true"))
                if picks < 10:
                    continue
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
                st = state[fmt]
                st["template"][seq] += 1

                hands = []
                ok = True
                for k, x in enumerate(bp):
                    hn = str(x.get("hero_name") or "").strip()
                    camp = int(x.get("camp") or 0)
                    if not hn or camp not in (1, 2):
                        ok = False
                        break
                    is_ban = 0 if str(x.get("is_ban_or_pick")) in ("0", 0) else 1
                    st["prior"][k][hn] += 1
                    hero_count[hn] += 1
                    hands.append([is_ban, camp, hn])
                if not ok or len(hands) != len(bp):
                    continue
                st["games"].append([year, lid, stage, t1, t2, game_no, win_camp, hands, fmt])
                st["n"] += 1
        print(f"scanned {lid}: 18={state['18']['n']} 20={state['20']['n']}", flush=True)

    # 2016–2019 官方接口没有 BP：用玩加历史局补 14 / 16 / 18 手赛制
    for event_id, (year, lid, fmt) in LEGACY_EVENTS.items():
        rows, _ = legacy_games(event_id, year, lid, fmt)
        total_games = sum(
            _int(r.get("game_count")) for r in
            read_csv(LEGACY_PREFIX / f"event_{event_id}" / "matches.csv")
        )
        if total_games and len(rows) < total_games * 0.8:
            print(f"legacy {event_id}: 仅 {len(rows)}/{total_games} 局，跳过不完整赛事", flush=True)
            continue
        st = state[fmt]
        for year_, lid_, stage, t1, t2, gno, wc, hands, f in rows:
            st["template"][tuple((a, c) for a, c, _ in hands)] += 1
            for k, (a, c, h) in enumerate(hands):
                st["prior"][k][h] += 1
                hero_count[h] += 1
            st["games"].append([year_, lid_, stage, t1, t2, gno, wc, hands, f])
            st["n"] += 1
        if rows:
            leagues_meta.setdefault(lid, LEGACY_LEAGUE_NAMES.get(lid, lid))
        print(f"legacy {event_id}: fmt={fmt} games={len(rows)}", flush=True)

    # 2018 秋玩加补集：10 场完整 BP（ScoreGG 缺局的场次）
    sup_rows, _ = legacy_games("704/supplement", "2018", "20180002", "18", "scoregg_match_id")
    st = state["18"]
    for year_, lid_, stage, t1, t2, gno, wc, hands, f in sup_rows:
        st["template"][tuple((a, c) for a, c, _ in hands)] += 1
        for k, (a, c, h) in enumerate(hands):
            st["prior"][k][h] += 1
            hero_count[h] += 1
        st["games"].append([year_, lid_, stage, t1, t2, gno, wc, hands, f])
        st["n"] += 1
    print(f"legacy 704/supplement: fmt=18 games={len(sup_rows)}", flush=True)

    for lid, name in LEGACY_LEAGUE_NAMES.items():
        leagues_meta.setdefault(lid, name)

    hero_list = [h for h, _ in hero_count.most_common()]
    hero_idx = {h: i for i, h in enumerate(hero_list)}

    games_out = []
    used_leagues = {}
    for fmt in FORMATS:
        for year, lid, stage, t1, t2, gno, wc, hands, f in state[fmt]["games"]:
            encoded = ";".join(f"{a},{c},{hero_idx[h]}" for a, c, h in hands)
            games_out.append([year, lid, stage, t1, t2, gno, wc, encoded, f])
            used_leagues[lid] = leagues_meta.get(lid, lid)

    templates, priors = {}, {}
    for fmt in FORMATS:
        if not state[fmt]["n"]:
            continue
        tpl, tpl_n = state[fmt]["template"].most_common(1)[0]
        templates[fmt] = [[a, c] for a, c in tpl]
        prior_out = []
        for counter in state[fmt]["prior"]:
            total = sum(counter.values()) or 1
            prior_out.append([[h, c, round(c / total, 4)] for h, c in counter.most_common(TOP_PRIOR)])
        priors[fmt] = prior_out
        print(f"template {fmt}: votes {tpl_n}/{state[fmt]['n']}", flush=True)

    total = sum(state[f]["n"] for f in FORMATS)
    data = {
        "template": templates.get("20") or templates.get("18"),
        "templates": templates,
        "heroes": hero_list,
        "leagues": used_leagues,
        "games": games_out,
        "prior": priors.get("20") or priors.get("18"),
        "priors": priors,
        "totalBattles": total,
        "totalBattlesByFormat": {f: state[f]["n"] for f in FORMATS},
    }
    path = SITE / "assets" / "bp.js"
    path.write_text("KPL_BP = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                    encoding="utf-8")
    by_fmt = ", ".join(f"{f}={state[f]['n']}" for f in FORMATS)
    print(f"\nbp.js: {path.stat().st_size/1024:.0f} KB | games: {len(games_out)} "
          f"({by_fmt}) | leagues: {len(used_leagues)}")


if __name__ == "__main__":
    main()
