# -*- coding: utf-8 -*-
"""生成 峡谷有数官网的站点数据（assets/data.js）与截图拷贝。

数据源：../02-KPL实时胜率预测系统（本地分析表 / 归档 / 快照 / 训练状态）。
运行：python build_data.py  （无网络请求，全部读取本地文件）
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
sys.path.insert(0, str(PROJ / "scripts"))

from kpl_official_core import (  # noqa: E402
    _replay_v11_timeline,
    aggregate_bp_meta,
    build_hero_matchups,
    build_hero_pool,
    build_phase_attribution,
    build_proxy_standings,
    build_season_honors,
    classify_battle_swing,
    detect_events,
    load_battle_bp,
    load_battle_jsons,
    RAW_DIR,
)

LEAGUE_NAMES = {
    "20260001": "2026 春季赛",
    "20260002": "2026 挑战者杯",
    "20260003": "2026 夏季赛",
    "20260004": "2026 年度总决赛",
}
FEATURED_BATTLE = "954221072_5_1785503975"  # 2026-07-31 大场第 3 局（翻盘名局）


def jload(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


_VERSION_TAG = re.compile(r"估算\s*[·・\-]?\s*V\d+")


def clean_ui_text(text) -> str:
    """面向用户的文案不出现内部模型版本号。"""
    return _VERSION_TAG.sub("估算", str(text))


def clean_cards(cards) -> list:
    out = []
    for c in cards or []:
        c = dict(c)
        for k, v in c.items():
            if isinstance(v, str):
                c[k] = clean_ui_text(v)
        out.append(c)
    return out


def public_model_name(raw) -> str:
    raw = str(raw or "")
    if "EarlyRF" in raw and "MidRF" in raw:
        return "分阶段集成模型（早期 EarlyRF + 中期 MidRF）"
    return re.sub(r"V\d+\s*", "", raw).strip() or "分阶段集成模型"


def tier_of(wr: float) -> str:
    return "S" if wr >= 0.55 else "A" if wr >= 0.50 else "B" if wr >= 0.45 else "C"


def main() -> None:
    assets = SITE / "assets"
    (assets / "shots").mkdir(parents=True, exist_ok=True)

    archive = pd.read_csv(PROJ / "data/realtime/schedule_archive.csv",
                          dtype={"league_id": str, "match_id": str}).fillna("")
    matches = pd.read_csv(PROJ / "data/analysis/matches.csv")
    battles = pd.read_csv(PROJ / "data/analysis/battles.csv")
    teams_tbl = pd.read_csv(PROJ / "data/analysis/teams.csv")
    players = pd.read_csv(PROJ / "data/processed/players.csv")
    train = jload(PROJ / "data/realtime/train_status.json", {})
    backtest = jload(PROJ / "data/realtime/backtest_v9_report.json", {})
    catalog = jload(PROJ / "data/realtime/datasets/catalog.json", {})

    # ---------- 图标 ----------
    team_icons: dict[str, str] = {}
    hero_icons: dict[str, str] = {}
    if not players.empty:
        ti = players.dropna(subset=["team_icon"])[["team_name", "team_icon"]].drop_duplicates()
        team_icons = {str(a): str(b) for a, b in zip(ti["team_name"], ti["team_icon"]) if str(b).startswith("http")}
        hi = players.dropna(subset=["hero_icon"])[["hero_name", "hero_icon"]].drop_duplicates(subset=["hero_name"])
        hero_icons = {str(a): str(b) for a, b in zip(hi["hero_name"], hi["hero_icon"]) if str(b).startswith("http")}

    # ---------- 分场比分 ----------
    _sched_cache: dict = {}

    def _sched_scores(league_id) -> dict:
        lid = str(league_id or "")
        if lid in _sched_cache:
            return _sched_cache[lid]
        mp = {}
        f = PROJ / "data" / "history" / lid / "schedule.json"
        if f.exists():
            for mm in (jload(f, []) or []):
                if not isinstance(mm, dict) or int(mm.get("status") or 0) != 2:
                    continue
                c1, c2 = mm.get("camp1") or {}, mm.get("camp2") or {}
                try:
                    s1, s2 = int(c1.get("score") or 0), int(c2.get("score") or 0)
                except (TypeError, ValueError):
                    continue
                mp[str(mm.get("match_id"))] = (s1, s2, str(c1.get("team_name") or ""))
        _sched_cache[lid] = mp
        return mp

    def score_for(match_id: str, league_id=None, team1: str = None) -> tuple[int, int, int]:
        # 1) 官方赛程档案比分（最权威；与页面 team1/team2 同源）
        for lid in ([league_id] if league_id else []) + ["20260004", "20260003", "20260002"]:
            mp = _sched_scores(lid) if lid else {}
            if str(match_id) in mp:
                s1, s2, c1name = mp[str(match_id)]
                if team1 and c1name and c1name != str(team1):
                    s1, s2 = s2, s1
                return (s1, s2, s1 + s2)
        # 2) 兜底：实时快照统计
        sub = battles[battles["match_id"].astype(str) == str(match_id)]
        if sub.empty:
            return (-1, -1, 0)
        w1 = int((sub["winner"] == sub["team1"].iloc[0]).sum())
        w2 = int((sub["winner"] == sub["team2"].iloc[0]).sum())
        return (w1, w2, len(sub))

    def match_row(r) -> dict:
        w1, w2, n = score_for(str(r["match_id"]), r.get("league_id"), r.get("team1"))
        return {
            "matchId": str(r["match_id"]),
            "leagueId": str(r.get("league_id") or ""),
            "date": str(r["date"]),
            "time": str(r["start_time"])[11:16],
            "team1": str(r["team1"]),
            "team2": str(r["team2"]),
            "icon1": team_icons.get(str(r["team1"]), ""),
            "icon2": team_icons.get(str(r["team2"]), ""),
            "score1": w1,
            "score2": w2,
            "battles": n,
            "status": str(r.get("status_text") or ""),
        }

    # 用近期联赛的官方赛程给状态保鲜（archive 可能滞后；watch 会持续刷新 schedule.json）
    fresh_status = {}
    for _lid in ["20260004", "20260003", "20260002"]:
        for _m in (jload(PROJ / "data" / "history" / _lid / "schedule.json", []) or []):
            if not isinstance(_m, dict):
                continue
            _st = int(_m.get("status") or 0)
            fresh_status[str(_m.get("match_id"))] = (
                "已结束" if _st == 2 else ("进行中" if _st == 1 else "未开始"))
    if fresh_status:
        archive = archive.copy()
        archive["status_text"] = [
            fresh_status.get(str(mid), st)
            for mid, st in zip(archive["match_id"].astype(str), archive["status_text"])
        ]

    finished = archive[archive["status_text"] == "已结束"].sort_values("start_time")
    recent_all = [match_row(r) for _, r in finished.iloc[::-1].iterrows()]
    recent = recent_all[:12]
    upcoming = [match_row(r) for _, r in
                archive[archive["status_text"] == "未开始"].sort_values("start_time").head(9).iterrows()]
    ticker = [f"{m['team1']} {m['score1']}:{m['score2']} {m['team2']}" for m in recent_all[:8]
              if m["score1"] >= 0] or [f"{m['team1']} vs {m['team2']}" for m in recent_all[:8]]

    # ---------- 完整赛程表（全部归档场次） ----------
    schedule_all = [match_row(r) for _, r in
                    archive.sort_values("start_time", ascending=False).iterrows()]

    # ---------- 积分榜（全量） ----------
    standings = build_proxy_standings(teams_tbl)
    st_rows = []
    for _, r in standings.iterrows():
        st_rows.append({
            "rank": int(r["rank"]),
            "team": str(r["team"]),
            "icon": team_icons.get(str(r["team"]), ""),
            "wins": int(r["wins"]), "losses": int(r["losses"]), "games": int(r["games"]),
            "winRate": float(r["win_rate"]),
            "ciLo": float(r["wilson_lo"]), "ciHi": float(r["wilson_hi"]),
            "goldDiff": float(r["avg_gold_diff"]),
        })

    # ---------- 选手榜（≥8 局，按 KDA） ----------
    players_top = []
    if not players.empty:
        pl = players.copy()
        for c in ("kda", "participation_rate", "mvp_score"):
            pl[c] = pd.to_numeric(pl.get(c), errors="coerce")
        pl["is_mvp"] = pd.to_numeric(pl.get("is_mvp"), errors="coerce").fillna(0).astype(int)
        g = pl.groupby(["player_name", "team_name"], as_index=False).agg(
            games=("battle_id", "size"), kda=("kda", "mean"),
            part=("participation_rate", "mean"), mvp=("is_mvp", "sum"),
            pos=("position_desc", "first"), icon=("player_icon", "first"))
        g = g[g["games"] >= 8].sort_values(["kda", "games"], ascending=False).head(30)
        for _, r in g.iterrows():
            players_top.append({
                "name": str(r["player_name"]), "team": str(r["team_name"]),
                "icon": str(r["icon"]) if str(r["icon"]).startswith("http") else "",
                "teamIcon": team_icons.get(str(r["team_name"]), ""),
                "pos": str(r["pos"]), "games": int(r["games"]),
                "kda": float(r["kda"]), "part": float(r["part"]), "mvp": int(r["mvp"]),
            })

    # ---------- 英雄图鉴（按出场，Top 24） ----------
    meta = aggregate_bp_meta()
    heroes_meta = meta.get("heroes") or {}
    heroes = []
    for name, h in heroes_meta.items():
        pick = h.get("pick") or {}
        win = h.get("win") or {}
        ban = h.get("ban") or {}
        heroes.append({
            "name": str(name), "icon": hero_icons.get(str(name), ""),
            "games": int(pick.get("k") or 0), "pickRate": float(pick.get("rate") or 0),
            "wr": float(win.get("rate") or 0), "ciLo": float(win.get("ci_low") or 0),
            "ciHi": float(win.get("ci_high") or 0), "banRate": float(ban.get("rate") or 0),
        })
    heroes.sort(key=lambda x: (-x["games"], -x["wr"]))
    heroes = heroes[:24]
    for h in heroes:
        h["tier"] = tier_of(h["wr"])

    # ---------- 同位置对位（中路 / 发育路，Top 6） ----------
    matchups = {}
    for pos in ("中路", "发育路"):
        mu = build_hero_matchups(pos)
        rows = []
        for r in (mu.get("rows") or [])[:6]:
            rows.append({
                "blue": r["hero_blue"], "red": r["hero_red"],
                "blueIcon": hero_icons.get(r["hero_blue"], ""), "redIcon": hero_icons.get(r["hero_red"], ""),
                "n": int(r["n"]), "wr": float(r["wr"]),
                "ciLo": float(r["ci_low"]), "ciHi": float(r["ci_high"]),
            })
        matchups[pos] = rows

    # ---------- 名局复盘（翻盘局曲线 + 阶段 + 归因卡） ----------
    featured = None
    row = battles[battles["battle_id"].astype(str) == FEATURED_BATTLE]
    if not row.empty:
        r = row.iloc[0]
        snaps = load_battle_jsons(RAW_DIR / FEATURED_BATTLE)
        win_camp = 2 if str(r["winner"]) == str(r["team2"]) else 1
        swing = classify_battle_swing(snaps, win_camp)
        tl = _replay_v11_timeline(FEATURED_BATTLE)
        timeline = [
            {"m": float(m), "p": float(p), "gd": float(g)}
            for m, p, g in zip(tl["minute"], tl["camp1_win_prob"], tl["gold_diff"])
            if pd.notna(p)
        ]
        events = [
            {"m": float(e["minute"]), "label": str(e["label"]), "type": str(e["type"])}
            for e in detect_events(snaps)
        ][:60]
        att = build_phase_attribution(FEATURED_BATTLE)
        w1, w2, _n = score_for(str(r["match_id"]), r.get("league_id"), r.get("team1"))
        featured = {
            "battleId": FEATURED_BATTLE,
            "date": str(r["date"]), "gameNo": int(r["game_no"]),
            "team1": str(r["team1"]), "team2": str(r["team2"]),
            "icon1": team_icons.get(str(r["team1"]), ""), "icon2": team_icons.get(str(r["team2"]), ""),
            "winner": str(r["winner"]), "score1": w1, "score2": w2,
            "duration": float(r["duration_min"] or 0),
            "comeback": bool(swing.get("comeback")),
            "timeline": timeline,
            "events": events,
            "phases": att.get("phases") or [],
            "cards": clean_cards(att.get("cards")),
        }

    # ---------- 比赛详情（有复盘曲线的最近 14 场大场，含关键局 BP / 曲线 / 归因） ----------
    def battle_detail(bid: str) -> dict | None:
        bd = battles[battles["battle_id"].astype(str) == bid]
        if bd.empty:
            return None
        r = bd.iloc[0]
        snaps = load_battle_jsons(RAW_DIR / bid)
        if not snaps:
            return None
        tl = _replay_v11_timeline(bid)
        timeline = [{"m": float(m), "p": float(p), "gd": float(g)}
                    for m, p, g in zip(tl["minute"], tl["camp1_win_prob"], tl["gold_diff"]) if pd.notna(p)]
        win_camp = 1 if str(r["winner"]) == str(r["team1"]) else 2
        att = build_phase_attribution(bid)
        events = [{"m": float(e["minute"]), "label": str(e["label"]), "type": str(e["type"])}
                  for e in detect_events(snaps)][:60]
        bp = load_battle_bp(bid)
        steps = bp.get("steps") or []

        def camp_bp(camp: int) -> dict:
            picks = [{"name": str(s["hero_name"]), "icon": hero_icons.get(str(s["hero_name"]), "")}
                     for s in steps if s.get("action") == "pick" and int(s.get("camp") or 0) == camp]
            bans = [{"name": str(s["hero_name"]), "icon": hero_icons.get(str(s["hero_name"]), "")}
                    for s in steps if s.get("action") == "ban" and int(s.get("camp") or 0) == camp]
            return {"picks": picks, "bans": bans}

        swing = classify_battle_swing(snaps, win_camp)
        return {
            "battleId": bid, "gameNo": int(r["game_no"]), "winner": str(r["winner"]),
            "duration": float(r["duration_min"] or 0), "goldDiff": float(r["gold_diff"] or 0),
            "comeback": bool(swing.get("comeback")), "hasTimeline": bool(r["has_timeline"]),
            "timeline": timeline, "events": events,
            "phases": att.get("phases") or [], "cards": clean_cards(att.get("cards")),
            "bp": {"camp1": camp_bp(1), "camp2": camp_bp(2)},
        }

    match_details = []
    cand_matches = (battles[battles["has_timeline"].astype(bool)]
                    .groupby("match_id")["date"].first().reset_index()
                    .sort_values("date", ascending=False).head(14))
    for _, mr in cand_matches.iterrows():
        mid = str(mr["match_id"])
        sub = battles[battles["match_id"].astype(str) == mid]
        if sub.empty:
            continue
        t1, t2 = str(sub["team1"].iloc[0]), str(sub["team2"].iloc[0])
        w1, w2, _w_n = score_for(mid, sub["league_id"].iloc[0] if "league_id" in sub.columns else None, t1)
        tl_sub = sub[sub["has_timeline"].astype(bool)]
        key_row, best_rank = None, -1.0
        for _, r in tl_sub.iterrows():
            snaps = load_battle_jsons(RAW_DIR / str(r["battle_id"]))
            wc = 1 if str(r["winner"]) == t1 else 2
            cb = bool(classify_battle_swing(snaps, wc).get("comeback")) if snaps else False
            rank = (2.0 if cb else 1.0) * 1000 + float(r["duration_min"] or 0)
            if rank > best_rank:
                best_rank, key_row = rank, r
        if key_row is None:
            continue
        key_detail = battle_detail(str(key_row["battle_id"]))
        if key_detail is None:
            continue
        match_details.append({
            "matchId": mid, "date": str(mr["date"]),
            "leagueId": str(sub["league_id"].iloc[0]) if "league_id" in sub.columns else "",
            "team1": t1, "team2": t2,
            "icon1": team_icons.get(t1, ""), "icon2": team_icons.get(t2, ""),
            "score1": w1, "score2": w2,
            "battles": [{"gameNo": int(r["game_no"]), "winner": str(r["winner"]),
                         "duration": float(r["duration_min"] or 0), "hasTl": bool(r["has_timeline"])}
                        for _, r in sub.sort_values("game_no").iterrows()],
            "key": key_detail,
        })

    # ---------- 战队详情（积分 + 英雄池） ----------
    team_details = []
    for _, s in standings.head(18).iterrows():
        tn = str(s["team"])
        pool = build_hero_pool(tn, "team")
        heroes_pool = []
        if pool.get("state") == "ok":
            for x in (pool.get("rows") or [])[:8]:
                heroes_pool.append({
                    "name": x["hero"], "icon": hero_icons.get(x["hero"], ""),
                    "games": x["games"],
                    "wr": None if x["wr"] is None else round(x["wr"], 3),
                    "stale": bool(x["stale"]),
                })
        team_details.append({
            "team": tn, "icon": team_icons.get(tn, ""),
            "rank": int(s["rank"]), "wins": int(s["wins"]), "losses": int(s["losses"]),
            "games": int(s["games"]), "winRate": float(s["win_rate"]),
            "ciLo": float(s["wilson_lo"]), "ciHi": float(s["wilson_hi"]),
            "goldDiff": float(s["avg_gold_diff"]),
            "pool": heroes_pool,
            "poolSize": (pool.get("breadth") or {}).get("pool_size") if pool.get("state") == "ok" else None,
            "poolHhi": (pool.get("breadth") or {}).get("hhi") if pool.get("state") == "ok" else None,
        })

    # ---------- 英雄详情（产品页数据：使用榜 / 战队 / 近期对局 / 组合 / 对位） ----------
    hero_by_name = {h["name"]: h for h in heroes}
    pl_rows = []
    if not players.empty:
        pl = players.copy()
        pl["_win"] = None
        win_lookup = {}
        for _, r in battles.iterrows():
            w = str(r.get("winner") or "").strip()
            if w:
                win_lookup[str(r.get("battle_id"))] = (w, str(r.get("date") or ""),
                                                       str(r.get("match_id") or ""),
                                                       str(r.get("team1") or ""), str(r.get("team2") or ""))
        for _, r in pl.iterrows():
            key = str(r.get("battle_id"))
            w = win_lookup.get(key)
            if not w:
                continue
            pl_rows.append({
                "hero": str(r.get("hero_name") or ""),
                "player": str(r.get("player_name") or ""),
                "team": str(r.get("team_name") or ""),
                "ts": int(key.rsplit("_", 1)[-1]) if key.rsplit("_", 1)[-1].isdigit() else 0,
                "won": 1 if w[0] == str(r.get("team_name")) else 0,
                "date": w[1], "matchId": w[2],
                "opp": w[4] if w[3] == str(r.get("team_name")) else w[3],
            })
    pl_df = pd.DataFrame(pl_rows)
    lineup3 = meta.get("lineup_3") or {}
    mu_cache = {pos: (build_hero_matchups(pos).get("rows") or []) for pos in ("中路", "发育路")}

    def hero_detail(h: dict) -> dict:
        name = h["name"]
        sub = pl_df[pl_df["hero"] == name] if not pl_df.empty else pd.DataFrame()
        pl_top, tm_top, recent = [], [], []
        if not sub.empty:
            g1 = sub.groupby(["player", "team"], as_index=False).agg(games=("won", "size"), wins=("won", "sum"))
            g1 = g1[g1["games"] >= 2].sort_values(["games", "wins"], ascending=False).head(6)
            for _, r in g1.iterrows():
                pl_top.append({"player": str(r["player"]), "team": str(r["team"]),
                               "games": int(r["games"]), "wins": int(r["wins"]),
                               "teamIcon": team_icons.get(str(r["team"]), ""),
                               "wr": round(r["wins"] / r["games"], 3)})
            g2 = sub.groupby("team", as_index=False).agg(games=("won", "size"), wins=("won", "sum"))
            g2 = g2.sort_values(["games", "wins"], ascending=False).head(5)
            for _, r in g2.iterrows():
                tm_top.append({"team": str(r["team"]), "games": int(r["games"]), "wins": int(r["wins"]),
                               "teamIcon": team_icons.get(str(r["team"]), ""),
                               "wr": round(r["wins"] / r["games"], 3)})
            for _, r in sub.sort_values("ts", ascending=False).head(8).iterrows():
                recent.append({"date": str(r["date"]), "matchId": str(r["matchId"]),
                               "player": str(r["player"]), "team": str(r["team"]),
                               "opp": str(r["opp"]), "won": bool(r["won"])})
        trios = []
        for key, val in sorted(lineup3.items(), key=lambda kv: -int((kv[1] or {}).get("n", 0))):
            if name in key:
                n = int(val.get("n") or 0)
                if n >= 2:
                    trios.append({"combo": " / ".join(sorted(key)), "n": n,
                                  "wr": round(int(val.get("wins") or 0) / n, 3)})
            if len(trios) >= 4:
                break
        mus = []
        for pos in ("中路", "发育路"):
            for r in mu_cache[pos]:
                if r["hero_blue"] == name or r["hero_red"] == name:
                    side = "blue" if r["hero_blue"] == name else "red"
                    wr = r["wr"] if side == "blue" else 1 - r["wr"]
                    mus.append({"pos": pos, "vs": r["hero_red"] if side == "blue" else r["hero_blue"],
                                "vsIcon": hero_icons.get(r["hero_red"] if side == "blue" else r["hero_blue"], ""),
                                "side": side, "n": int(r["n"]), "wr": round(wr, 3),
                                "insufficient": bool(r["insufficient"])})
        mus.sort(key=lambda x: -x["n"])
        return {"name": name, "icon": h["icon"], "games": h["games"], "pickRate": h["pickRate"],
                "wr": h["wr"], "ciLo": h["ciLo"], "ciHi": h["ciHi"], "banRate": h["banRate"],
                "tier": h["tier"], "players": pl_top, "teams": tm_top, "recent": recent,
                "trios": trios, "matchups": mus[:6]}

    hero_details = [hero_detail(h) for h in heroes[:30]]

    # ---------- 战队详情补充：选手名单 ----------
    for t in team_details:
        members = []
        if not pl_df.empty:
            msub = pl_df[pl_df["team"] == t["team"]]
            gm = msub.groupby("player", as_index=False).agg(games=("won", "size"), wins=("won", "sum"))
            gm = gm.sort_values(["games"], ascending=False).head(8)
            for _, r in gm.iterrows():
                members.append({"player": str(r["player"]), "games": int(r["games"]),
                                "wins": int(r["wins"]), "wr": round(r["wins"] / max(1, r["games"]), 3)})
        t["members"] = members

    # ---------- 采集覆盖分布（按日期） ----------
    cov = []
    if not battles.empty:
        b = battles.copy()
        b["_tl"] = b["has_timeline"].astype(bool)
        grp = b.groupby("date", as_index=False).agg(total=("battle_id", "size"), collected=("_tl", "sum"))
        grp = grp.sort_values("date")
        cov = [{"date": str(x["date"]), "total": int(x["total"]), "collected": int(x["collected"])}
               for _, x in grp.iterrows()]

    # ---------- 规模与模型 ----------
    snap_dirs = len([p for p in (PROJ / "data/realtime/raw_snapshots").iterdir() if p.is_dir()])
    stats = {
        "matches": int(len(matches)), "battles": int(len(battles)),
        "snapshotDirs": int(snap_dirs), "playerRows": int(len(players)),
        "clean": int((catalog.get("stats") or {}).get("clean") or 0),
        "quarantine": int((catalog.get("stats") or {}).get("quarantine") or 0),
        "heroes": int(len(heroes_meta)), "events": int(len(pd.read_csv(PROJ / "data/analysis/events.csv"))),
    }
    # 口径对比（V12 三段隔离）：old = 旧口径（最近 8 局，且这 8 局同时被用来拟合校准器）；
    # new = 新口径（最近 20 局 test 段，训练与校准都没碰过）。
    # 注意这不是"模型变强/变弱"，是"考卷换了"——同一样本对照见 sameSample。
    _old_protocol = {"early (≤8′)": 0.117, "mid (9–15′)": 0.129, "late (16′+)": 0.231, "all": 0.143}
    _new_protocol = {
        "early (≤8′)": float(train.get("holdout_early_brier") or 0),
        "mid (9–15′)": float(train.get("holdout_mid_brier") or 0),
        "late (16′+)": float(train.get("holdout_late_brier") or 0),
        "all": float(train.get("holdout_real_brier") or 0),
    }
    # AUC 有两个口径，站点只能发布「独立测试」那个，训练诊断分不得混入：
    #   test  = backtest_v9_report.json 的 holdout_real.all.auc（test 段 20 局 / 298 帧，训练与校准都没碰过）
    #   diag  = train_status.json 的 auc（train 段内模型选型诊断分，非能力指标——它是在模型见过的数据上算的）
    test_auc = float((((backtest.get("holdout_real") or {}).get("all") or {}).get("auc")) or 0)
    diag_auc = float(train.get("auc") or 0)
    model = {
        "version": str(train.get("version") or "V11"),
        "name": public_model_name(train.get("model_name")),
        "trainedAt": str(train.get("trained_at") or ""),
        "holdoutAll": float(train.get("holdout_real_brier") or 0),
        "holdoutEarly": float(train.get("holdout_early_brier") or 0),
        "holdoutMid": float(train.get("holdout_mid_brier") or 0),
        "holdoutLate": float(train.get("holdout_late_brier") or 0),
        # 独立测试段（holdout）局数：取 backtest 报告里真实的 holdout 对局列表长度。
        # 曾误读 train_status.json 的 holdout_n_battles —— V12 训练状态已不再写这个键，
        # 结果站点「数据说明」页会显示「新口径：最近 0 局」，是错的。与 build_predict_data.py 口径保持一致。
        "holdoutN": len(backtest.get("holdout_battles") or []),
        "split": train.get("split") or {},
        "auc": round(test_auc, 4),
        "aucScope": "独立测试段（test 20 局 / 298 帧，训练与校准均未接触）",
        "trainDiagAuc": round(diag_auc, 4),
        "trainDiagAucScope": "训练段内诊断分（模型选型用，非能力指标；test 集不参与）",
        "compare": [
            {"phase": k, "old": _old_protocol[k], "new": round(_new_protocol[k], 4)}
            for k in ("early (≤8′)", "mid (9–15′)", "late (16′+)", "all")
        ],
        # 同一样本对照：把新模型放回旧的 8 局上重算，用来证明"数字变了不是模型退步"
        "sameSample": {"old": 0.143, "new": 0.135, "n": 8},
    }

    league_id = str(archive.sort_values("start_time")["league_id"].iloc[-1]) if not archive.empty else "20260004"
    data = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "season": LEAGUE_NAMES.get(league_id, "2026 赛季"),
        "stats": stats, "model": model,
        "recent": recent, "upcoming": upcoming, "ticker": ticker,
        "schedule": schedule_all,
        "standings": st_rows,
        "players": players_top,
        "heroes": heroes,
        "matchups": matchups,
        "featured": featured,
        "coverage": cov,
        "honors": [],
    }
    honors = build_season_honors()
    for c in honors.get("cards", []):
        hero = c["entries"][0] if c["entries"] else None
        if not hero:
            continue
        data["honors"].append({
            "ruleId": c["rule_id"], "title": c["title"],
            "names": "、".join(e["name"] for e in c["entries"]),
            "value": hero["value_text"], "n": hero["n"], "detail": hero["detail"],
            "tie": bool(c["tie"]),
        })

    out = SITE / "assets" / "data.js"
    out.write_text("window.SITE_DATA = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n",
                   encoding="utf-8")
    print(f"data.js -> {out}")
    print(f"  recent={len(recent)} upcoming={len(upcoming)} standings={len(st_rows)} "
          f"players={len(players_top)} heroes={len(heroes)} honors={len(data['honors'])} "
          f"coverage_days={len(cov)} featured={'ok' if featured else 'MISS'}"
          f" timeline={len(featured['timeline']) if featured else 0}")

    det_out = SITE / "assets" / "details.js"
    det_out.write_text(
        "window.SITE_DETAILS = " + json.dumps(
            {"generatedAt": data["generatedAt"], "matches": match_details,
             "teams": team_details, "heroes": hero_details},
            ensure_ascii=False, indent=1) + ";\n",
        encoding="utf-8")
    print(f"details.js -> {det_out}  (matches={len(match_details)} teams={len(team_details)} heroes={len(hero_details)})")

    shots_src = PROJ / "docs" / "showcase"
    names = ["01-schedule.png", "02-live.png", "03-replay.png", "03b-replay-players.png",
             "03c-replay-attribution.png", "04-teams.png", "05-players.png", "06-heroes.png",
             "07-ops.png", "08-sim.png"]
    copied = sum(1 for n in names if (shots_src / n).exists() and
                 (shutil.copy2(shots_src / n, assets / "shots" / n) or True))
    print(f"shots copied: {copied}/{len(names)}")


if __name__ == "__main__":
    main()
