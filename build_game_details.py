# -*- coding: utf-8 -*-
"""生成局级数据：每局详情分片（按联赛拆分，页面按需加载）+ 全局索引 + 装备图标表。

输出：
  assets/games/index.js        KPL_GAME_INDEX = {matchId: {lg, b: [[battleId, seq, durMin, winCamp], ...]}}
  assets/games/<league_id>.json  {battleId: 局详情}
  assets/equip_icons.js        KPL_EQUIP_ICONS = {装备名: icon}

运行：python build_game_details.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
GAMES = SITE / "assets" / "games"


def jload(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def slim_battle(det: dict, match: dict) -> dict | None:
    wc = det.get("win_camp")
    st = int(det.get("status") or 0)
    live = 0
    if wc not in (1, 2):
        if st == 1:
            wc = 0
            live = 1
        else:
            return None
    c1 = det.get("camp1") or {}
    c2 = det.get("camp2") or {}
    players = []
    for p in det.get("battle_player_list") or []:
        if not isinstance(p, dict):
            continue
        equips = []
        for e in (p.get("BriefEquipList") or [])[:6]:
            if isinstance(e, dict) and e.get("equip_name"):
                equips.append(str(e["equip_name"]))
        sa = p.get("SummonerAbilityInfo") or {}
        try:
            dmg = round(float(p.get("hurt_total_rate") or 0) * 100, 1)
            bh = round(float(p.get("be_hurt_total_rate") or 0) * 100, 1)
        except (TypeError, ValueError):
            dmg = bh = 0
        players.append({
            "c": int(p.get("camp") or 0),
            "h": str(p.get("hero_name") or ""),
            "n": str(p.get("player_name") or p.get("actual_player_name") or ""),
            "pi": str(p.get("player_icon") or ""),
            "k": int(p.get("kill_num") or 0), "d": int(p.get("death_num") or 0),
            "a": int(p.get("assist_num") or 0),
            "g": int(float(p.get("gold") or 0)),
            "dmg": dmg, "bh": bh,
            "mvp": 1 if str(p.get("is_mvp")) in ("1", "True", "true") else 0,
            "eq": equips,
            "sa": str(sa.get("summoner_ability_name") or ""),
            "sai": str(sa.get("summoner_ability_icon") or ""),
        })
    bp = []
    for b in det.get("bp_list") or []:
        if not isinstance(b, dict):
            continue
        bp.append([int(b.get("camp") or 0), 0 if str(b.get("is_ban_or_pick")) in ("0", 0) else 1,
                   str(b.get("hero_name") or "")])
    vids = det.get("video_list") or []
    video = ""
    if vids and isinstance(vids[0], dict):
        video = str(vids[0].get("video_url") or "")
    return {
        "match": str(match.get("match_id") or ""),
        "seq": int(det.get("battle_seq") or 0),
        "win": wc,
        "live": live,
        "dur": round(float(det.get("game_duration") or 0) / 60000),
        "t1": str(c1.get("team_name") or ""), "i1": str(c1.get("team_icon") or ""),
        "t2": str(c2.get("team_name") or ""), "i2": str(c2.get("team_icon") or ""),
        "k1": int(c1.get("kill_num") or 0), "k2": int(c2.get("kill_num") or 0),
        "g1": int(c1.get("gold") or 0), "g2": int(c2.get("gold") or 0),
        "players": players,
        "bp": bp,
        "video": video,
    }


def main() -> None:
    GAMES.mkdir(parents=True, exist_ok=True)
    index: dict[str, dict] = {}
    equip_icons: dict[str, str] = {}
    n_games = 0

    for lg_dir in sorted(HIST.iterdir()):
        mdir = lg_dir / "matches"
        if not mdir.is_dir():
            continue
        lid = lg_dir.name
        league_games: dict[str, dict] = {}
        for f in sorted(mdir.glob("*.json")):
            obj = jload(f)
            if not obj:
                continue
            match = obj.get("match") or {}
            mid = str(match.get("match_id") or f.stem)
            rows = []
            for det in obj.get("battles") or []:
                if not isinstance(det, dict):
                    continue
                slim = slim_battle(det, match)
                if slim is None:
                    continue
                bid = str(det.get("battle_id") or "")
                if not bid:
                    continue
                league_games[bid] = slim
                rows.append([bid, slim["seq"], slim["dur"], slim["win"]])
                # 收集装备图标
                for p in det.get("battle_player_list") or []:
                    if not isinstance(p, dict):
                        continue
                    for e in (p.get("BriefEquipList") or [])[:6]:
                        if isinstance(e, dict) and e.get("equip_name") and e.get("equip_icon"):
                            equip_icons.setdefault(str(e["equip_name"]), str(e["equip_icon"]))
                n_games += 1
            if rows:
                index[mid] = {"lg": lid, "b": rows}
        out = GAMES / f"{lid}.json"
        out.write_text(json.dumps(league_games, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"{lid}: {len(league_games)} games -> {out.stat().st_size/1024:.0f} KB", flush=True)

    idx_path = GAMES / "index.js"
    idx_path.write_text("KPL_GAME_INDEX = " + json.dumps(index, ensure_ascii=False, separators=(",", ":")) + ";\n",
                        encoding="utf-8")
    eq_path = SITE / "assets" / "equip_icons.js"
    eq_path.write_text("KPL_EQUIP_ICONS = " + json.dumps(equip_icons, ensure_ascii=False, separators=(",", ":")) + ";\n",
                       encoding="utf-8")
    print(f"\nindex.js: {idx_path.stat().st_size/1024:.0f} KB | equip_icons.js: {eq_path.stat().st_size/1024:.0f} KB")
    print(f"matches: {len(index)} | games: {n_games} | equips: {len(equip_icons)}")


if __name__ == "__main__":
    main()
