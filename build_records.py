# -*- coding: utf-8 -*-
"""赛事纪录（最系列）：对局 / 选手 / 战队 / 系列赛的极值榜 → assets/records.js

范围：全部赛事 + 每年 + 比赛数 ≥30 的赛事
指标：13 类，每类保留最高 6 条与最低 6 条
运行：python build_records.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
HIST = PROJ / "data" / "history"
CN = timezone(timedelta(hours=8))
KEEP = 5
MIN_LEAGUE_MATCHES = 30


def num(v, default=0.0):
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def team_of(battle: dict, camp: int) -> str:
    return str((battle.get(f"camp{camp}") or {}).get("team_name") or "")


def secs(dur) -> float:
    v = num(dur)
    if v > 100000:
        return v / 1000.0
    if v > 1000:
        return v
    return 0.0


def main() -> None:
    files = sorted(HIST.glob("*/matches/*.json"))
    league_matches = Counter()
    for f in files:
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        lid = str((o.get("match") or {}).get("league_id") or "")
        if lid and (o.get("battles") or []):
            league_matches[lid] += 1
    good_leagues = {k for k, v in league_matches.items() if v >= MIN_LEAGUE_MATCHES}

    scopes = defaultdict(lambda: defaultdict(lambda: {"max": [], "min": []}))

    def push(scope_ids, metric, row):
        for sid in scope_ids:
            cell = scopes[sid][metric]
            cell["max"].append(row)
            cell["max"].sort(key=lambda r: r["v"], reverse=True)
            del cell["max"][KEEP:]
            cell["min"].append(row)
            cell["min"].sort(key=lambda r: r["v"])
            del cell["min"][KEEP:]

    games = 0
    for f in files:
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        m = o.get("match") or {}
        raw_bs = [b for b in (o.get("battles") or []) if b.get("win_camp") in (1, 2)]
        if not raw_bs:
            continue
        # 同一局号可能重复出现：优先保留有选手数据的那条
        by_seq = {}
        for b in raw_bs:
            seq = int(b.get("battle_seq") or 0)
            if seq <= 0:
                continue
            if seq not in by_seq or len(b.get("battle_player_list") or []) > len(by_seq[seq].get("battle_player_list") or []):
                by_seq[seq] = b
        bs = [by_seq[k] for k in sorted(by_seq)]
        if not bs:
            continue
        t1, t2 = team_of(bs[0], 1), team_of(bs[0], 2)
        if not t1 or not t2:
            continue
        mid = str(m.get("match_id") or f.stem)
        lid = str(m.get("league_id") or "")
        date = str(m.get("start_time") or "")[:10]
        year = date[:4]
        if not year.isdigit():
            continue
        scope_ids = ["all", year]
        if lid in good_leagues:
            scope_ids.append(lid)

        wins = Counter(int(b["win_camp"]) for b in bs)
        bo = int(m.get("bo") or 0)
        need = bo // 2 + 1 if bo > 0 else 0
        tie = wins[1] == wins[2]
        # 只有「完整且官方赛制明确」的系列赛才参与系列纪录；对局纪录不受影响
        series_ok = (not tie) and bo >= 3 and max(wins.values()) == need and len(bs) >= need
        win_camp = 0
        if not tie:
            win_camp = 1 if wins[1] > wins[2] else 2
        winner = (t1 if win_camp == 1 else t2) if win_camp else ""
        score = f"{wins[win_camp]}:{wins[3 - win_camp]}" if win_camp else f"{wins[1]}:{wins[2]}"

        if series_ok:
            total_sec = 0.0
            dur_ok = True
            for b in bs:
                d_sec = secs(b.get("game_duration"))
                if not (360 <= d_sec <= 2700):
                    dur_ok = False
                    break
                total_sec += d_sec
            if dur_ok and total_sec > 0:
                push(scope_ids, "series_dur", {
                    "v": round(total_sec / 60, 1), "d": date, "mid": mid,
                    "t1": t1, "t2": t2, "w": winner, "score": score, "bo": bo,
                })
            push(scope_ids, "series_margin", {
                "v": abs(wins[1] - wins[2]), "d": date, "mid": mid,
                "t1": t1, "t2": t2, "w": winner, "score": score, "bo": bo,
            })
            push(scope_ids, "series_games", {
                "v": len(bs), "d": date, "mid": mid,
                "t1": t1, "t2": t2, "w": winner, "score": score, "bo": bo,
            })

        for b in bs:
            games += 1
            bt1, bt2 = team_of(b, 1), team_of(b, 2)
            if not bt1 or not bt2:
                continue
            dur = secs(b.get("game_duration"))
            seq = int(b.get("battle_seq") or 0)
            bid = str(b.get("battle_id") or "")
            if not bid:
                continue
            plist = b.get("battle_player_list") or []
            kills = {1: 0, 2: 0}
            gold = {1: 0.0, 2: 0.0}
            for p in plist:
                camp = int(p.get("camp") or 0)
                if camp in (1, 2):
                    kills[camp] += int(num(p.get("kill_num")))
                    gold[camp] += num(p.get("gold"))

            if 360 <= dur <= 2700:
                push(scope_ids, "game_dur", {
                    "v": round(dur / 60, 1), "d": date, "mid": mid, "bid": bid,
                    "t1": bt1, "t2": bt2, "score": score, "g": seq,
                })
            k_camp = 1 if kills[1] >= kills[2] else 2
            push(scope_ids, "game_kills", {
                "v": kills[k_camp], "d": date, "mid": mid, "bid": bid,
                "team": bt1 if k_camp == 1 else bt2,
                "opp": bt2 if k_camp == 1 else bt1,
                "t1": bt1, "t2": bt2, "g": seq,
            })
            deaths = {1: 0, 2: 0}
            for p in plist:
                camp = int(p.get("camp") or 0)
                if camp in (1, 2):
                    deaths[camp] += int(num(p.get("death_num")))
            d_camp = 1 if deaths[1] >= deaths[2] else 2
            push(scope_ids, "team_deaths", {
                "v": deaths[d_camp], "d": date, "mid": mid, "bid": bid,
                "team": bt1 if d_camp == 1 else bt2,
                "opp": bt2 if d_camp == 1 else bt1,
                "t1": bt1, "t2": bt2, "g": seq,
            })
            km = abs(kills[1] - kills[2])
            k_camp2 = 1 if kills[1] >= kills[2] else 2
            push(scope_ids, "game_kill_margin", {
                "v": km, "d": date, "mid": mid, "bid": bid,
                "team": bt1 if k_camp2 == 1 else bt2,
                "opp": bt2 if k_camp2 == 1 else bt1,
                "t1": bt1, "t2": bt2, "g": seq,
            })
            gold_ok = gold[1] >= 20000 and gold[2] >= 20000
            if gold_ok:
                g_camp2 = 1 if gold[1] >= gold[2] else 2
                push(scope_ids, "team_gold", {
                    "v": int(gold[g_camp2]), "d": date, "mid": mid, "bid": bid,
                    "team": bt1 if g_camp2 == 1 else bt2,
                    "opp": bt2 if g_camp2 == 1 else bt1,
                    "t1": bt1, "t2": bt2, "g": seq,
                })
                gdiff = abs(gold[1] - gold[2])
                g_camp = 1 if gold[1] >= gold[2] else 2
                push(scope_ids, "game_gdiff", {
                    "v": int(gdiff), "d": date, "mid": mid, "bid": bid,
                    "team": bt1 if g_camp == 1 else bt2,
                    "opp": bt2 if g_camp == 1 else bt1,
                    "t1": bt1, "t2": bt2, "g": seq,
                })

            for p in plist:
                name = str(p.get("player_name") or p.get("actual_player_name") or "").strip()
                if not name:
                    continue
                camp = int(p.get("camp") or 0)
                if camp not in (1, 2):
                    continue
                hero = str(p.get("hero_name") or "")
                team = str(p.get("team_name") or (bt1 if camp == 1 else bt2))
                opp = bt2 if camp == 1 else bt1
                won = 1 if camp == win_camp else 0
                base = {"d": date, "mid": mid, "bid": bid, "p": name, "h": hero,
                        "team": team, "opp": opp, "g": seq, "w": won}
                k = int(num(p.get("kill_num")))
                d_ = int(num(p.get("death_num")))
                a = int(num(p.get("assist_num")))
                g = num(p.get("gold"))
                hurt = num(p.get("hurt_total"))
                push(scope_ids, "p_kills", dict(base, v=k))
                push(scope_ids, "p_deaths", dict(base, v=d_))
                push(scope_ids, "p_assists", dict(base, v=a))
                push(scope_ids, "p_ka", dict(base, v=k + a))
                if 2000 <= g <= 60000:
                    push(scope_ids, "p_gold", dict(base, v=int(g)))
                push(scope_ids, "p_dmg_abs", dict(base, v=int(hurt)))
                dv = p.get("hurt_total_rate")
                if dv not in (None, ""):
                    push(scope_ids, "p_dmg", dict(base, v=round(num(dv) * 100, 1)))
                pv = p.get("participation_rate")
                if pv not in (None, ""):
                    push(scope_ids, "p_part", dict(base, v=round(num(pv), 1)))
                bv = p.get("be_hurt_total_rate")
                if bv not in (None, ""):
                    push(scope_ids, "p_tank", dict(base, v=round(num(bv) * 100, 1)))
                mv = p.get("mvp_score")
                if mv not in (None, ""):
                    push(scope_ids, "p_mvp", dict(base, v=round(num(mv), 1)))
                gpm = int(g / (dur / 60)) if dur > 0 else 0
                if 200 <= gpm <= 1200:
                    push(scope_ids, "p_gpm", dict(base, v=gpm))
                # 主题纪录：空砍 / 尽力 / 躺赢 / 零阵亡
                if not won:
                    push(scope_ids, "p_empty_star", dict(base, v=k))
                    if dv not in (None, ""):
                        push(scope_ids, "p_carry_loss", dict(base, v=round(num(dv) * 100, 1)))
                else:
                    push(scope_ids, "p_lucky_win", dict(base, v=d_))
                if d_ == 0:
                    push(scope_ids, "p_perfect", dict(base, v=k, d=0))

    # 输出
    out = {}
    for sid, metrics in scopes.items():
        out[sid] = {}
        for metric, cell in metrics.items():
            def clean(rows):
                seen = set()
                res = []
                for r in rows:
                    key = (r.get("mid"), r.get("bid"), r.get("p") or r.get("team"), r.get("v"))
                    if key in seen:
                        continue
                    seen.add(key)
                    res.append(r)
                return res
            out[sid][metric] = {"max": clean(cell["max"])[:4], "min": clean(cell["min"])[:4]}

    data = {
        "generatedAt": datetime.now(CN).strftime("%Y-%m-%d %H:%M"),
        "games": games,
        "scopes": out,
    }
    path = SITE / "assets" / "records.js"
    path.write_text("KPL_RECORDS = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                    encoding="utf-8")
    print(f"records.js: {path.stat().st_size/1024:.0f} KB | scopes {len(out)} | games {games}")


if __name__ == "__main__":
    main()
