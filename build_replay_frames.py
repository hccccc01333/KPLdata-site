# -*- coding: utf-8 -*-
"""生成单局复盘时间轴数据包（V4 阶段二 · 复盘工作台）。

对每一局（只覆盖有分钟级快照的局）压缩出：
  frames[]  逐分钟：模型胜率 / 金差 / 击杀 / 推塔 / 资源 / 双方五人经济
  events[]  关键事件（一血 / 推塔 / 暴君 / 黑暗暴君 / 主宰 / 风暴龙王）
输出：
  assets/replay/index.js        {matchId: {lg, date, b: [battleId, ...]}}  有无复盘数据
  assets/replay/<matchId>.json  {matchId, t1, t2, battles: [...]}          按需加载（一场一个包）
用法：
  python build_replay_frames.py           增量（默认）
  python build_replay_frames.py --force   全量重建
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
sys.path.insert(0, str(PROJ / "scripts"))

from kpl_official_core import (  # noqa: E402
    PLAYER_LANE_ORDER,
    PREDICTION_DIR,
    RAW_DIR,
    _replay_v11_timeline,
    detect_events,
    load_battle_jsons,
)

OUT_DIR = SITE / "assets" / "replay"
INDEX_PATH = OUT_DIR / "index.js"
MANIFEST_PATH = OUT_DIR / ".manifest.json"
# 数据源不再依赖 02 仓库每天重建的分析表：直接用站点自己的"场次→局"索引 + 全部赛程，
# 这样当天刚打完的局也能立刻复盘（分析表是日更的，会滞后一天）。
GAMES_INDEX = SITE / "assets" / "games" / "index.js"
SCHEDULE_ALL = SITE / "assets" / "schedule_all.js"
MIN_FRAMES = 6
MAX_FRAMES = 40
POS_COUNT = 5
# battle_player_list.position 官方数字编码（见 kpl_official_core.POSITIONS）：
# 2 中路 / 4 游走 / 5 打野 / 6 对抗路 / 7 发育路；输出位序取官方对位行序
# PLAYER_LANE_ORDER = [对抗, 打野, 中路, 发育, 游走]，即索引 0..4。
POS_ORDINAL = {pid: i for i, pid in enumerate(PLAYER_LANE_ORDER)}
# 编码缺失时的文字兜底
POS_DESC_ORDER = {"对抗路": 0, "打野": 1, "中路": 2, "发育路": 3, "游走": 4}

CAMP_DIR = PROJ / "data" / "external" / "camp_battles"
BUILD_VERSION = "v3-camp-events"
# 中立资源：刷新窗口按 4/10/20 分钟口径；buff 时长是事件金差窗口的可配置默认值。
# 各资源刷新间隔不同（暴君 3 分钟、主宰/黑暗暴君 5 分钟、风暴龙王不刷新）。
NEUTRAL_BUFFS = {
    "tyrant": {"name": "暴君", "spawn_min": 4, "respawn_min": 3, "duration_sec": 90},
    "lord": {"name": "主宰/暗影主宰", "spawn_min": 4, "respawn_min": 5, "duration_sec": 90},
    "dark_tyrant": {"name": "黑暗暴君", "spawn_min": 10, "respawn_min": 5, "duration_sec": 90},
    "storm": {"name": "风暴龙王", "spawn_min": 20, "respawn_min": 0, "duration_sec": 90},
}


def jload(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


# 中立资源表可由 data/meta/neutral_buffs.json 覆盖（刷新窗口/buff 时长可配）。
_buff_cfg = jload(PROJ / "data" / "meta" / "neutral_buffs.json", {})
if _buff_cfg.get("resources"):
    NEUTRAL_BUFFS = _buff_cfg["resources"]


def jload_js(path: Path):
    """读站点里的 `X = {...};` 形式的 JS 数据文件。"""
    text = path.read_text(encoding="utf-8")
    return json.loads(text[text.index("=") + 1:].rstrip().rstrip(";"))


def _pos_ordinal(p: dict) -> int:
    """分路序（对抗路→打野→中路→发育路→游走）。优先用官方数字编码，缺失时退回文字。"""
    try:
        ordv = int(p.get("position"))
    except (TypeError, ValueError):
        ordv = -1
    if ordv in POS_ORDINAL:
        return POS_ORDINAL[ordv]
    return POS_DESC_ORDER.get(str(p.get("position_desc") or "").strip(), POS_COUNT)


def _roster(snaps: list[dict]) -> dict[int, list[str]]:
    """整局固化的五人名单（按分路序）。取全部帧的并集，避免某帧缺人导致曲线跨帧错位。

    分路编码重复（个别对局的原始数据异常，如 ADC 被标成游走）时，用该选手的
    末次经济降序破平：游走位通常经济最低，破平后可把高经济者让回缺失的发育路。
    """
    agg: dict[int, dict[str, list]] = {1: {}, 2: {}}
    for s in snaps:
        for p in (s.get("players") or []):
            try:
                camp = int(p.get("camp") or 0)
            except (TypeError, ValueError):
                camp = 0
            if camp not in (1, 2):
                continue
            name = str(p.get("player_name") or p.get("actual_player_name") or "")
            if not name:
                continue
            try:
                gold = int(float(p.get("gold") or 0))
            except (TypeError, ValueError):
                gold = 0
            rec = agg[camp].setdefault(name, [_pos_ordinal(p), 0])
            rec[1] = gold
    return {
        camp: sorted(agg[camp], key=lambda n: (agg[camp][n][0], -agg[camp][n][1], n))[:POS_COUNT]
        for camp in (1, 2)
    }


def _pos_golds(snap: dict, camp: int, roster: list[str]) -> list[int]:
    """按分路序取该阵营五人金币：索引 i 恒对应 roster[i]，缺人补 0，不会跨帧漂移。"""
    gold: dict[str, int] = {}
    for p in (snap.get("players") or []):
        try:
            if int(p.get("camp") or 0) != camp:
                continue
        except (TypeError, ValueError):
            continue
        name = str(p.get("player_name") or p.get("actual_player_name") or "")
        if not name:
            continue
        try:
            gold[name] = int(float(p.get("gold") or 0))
        except (TypeError, ValueError):
            gold[name] = 0
    out = [gold.get(n, 0) for n in roster]
    while len(out) < POS_COUNT:
        out.append(0)
    return out


def load_camp_index() -> dict[tuple[str, str], Path]:
    """(match_id, game_seq) -> 营地战报 JSON。"""
    cov = jload(CAMP_DIR / "_coverage.json", {})
    mid2match = {
        str(r.get("m_id")): str(r.get("match_id"))
        for r in (cov.get("matches") or [])
    }
    out: dict[tuple[str, str], Path] = {}
    for p in CAMP_DIR.glob("[0-9]*_*.json"):
        m = re.match(r"^(\d+)_(\d+)\.json$", p.name)
        if not m:
            continue
        match_id = mid2match.get(m.group(1))
        if match_id:
            out[(match_id, m.group(2))] = p
    return out


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    if not xs:
        return 0.0
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    for i in range(1, len(xs)):
        if x <= xs[i]:
            x0, x1 = xs[i - 1], xs[i]
            if x1 == x0:
                return float(ys[i])
            t = (x - x0) / (x1 - x0)
            return float(ys[i - 1]) + (float(ys[i]) - float(ys[i - 1])) * t
    return float(ys[-1])


def _gd_at(points: list[dict], m: float) -> float:
    return _interp([p["m"] for p in points], [p["gd"] for p in points], m)


def _local_gold_curve(frames: list[dict]) -> list[dict]:
    points = [{"m": 0, "gd": 0, "src": "anchor"}]
    for f in frames:
        points.append({"m": round(float(f["m"]), 2), "gd": int(f["gd"]), "src": "live"})
    return points


def _camp_gold_curve(camp: dict, frames: list[dict]):
    """把营地 20–30 秒金差网格校准到本地分钟锚点。

    营地数组没有时间戳，按“整局等分”落到时间轴；偏移量在本地分钟锚点之间
    分段线性插值，保证锚点处严格等于本地采集，锚点之间才使用营地形状。
    """
    g1 = [int(x) for x in (camp.get("camp1GoldArr") or [])]
    g2 = [int(x) for x in (camp.get("camp2GoldArr") or [])]
    n = min(len(g1), len(g2))
    if n < 4 or len(frames) < 2:
        return [], [], {}
    duration = float(frames[-1]["m"])
    times = [duration * i / (n - 1) for i in range(n)]
    raw = [g1[i] - g2[i] for i in range(n)]

    lm = [0.0] + [float(f["m"]) for f in frames]
    lg = [0.0] + [float(f["gd"]) for f in frames]
    # 锚点处的偏移：本地锚点 - 营地插值
    anchor_offsets = [_interp(lm, lg, m) - _interp(times, raw, m) for m in lm]
    corrected = [
        round(raw[i] + _interp(lm, anchor_offsets, t))
        for i, t in enumerate(times)
    ]

    points = _local_gold_curve(frames)
    for t, v in zip(times, corrected):
        if min(abs(t - float(f["m"])) for f in frames) < 0.12:
            continue
        points.append({"m": round(t, 2), "gd": int(v), "src": "camp"})
    points.sort(key=lambda p: (p["m"], 0 if p["src"] == "live" else 1))
    out, seen = [], {}
    for p in points:
        key = round(p["m"], 2)
        if key in seen:
            if p["src"] == "live":
                out[seen[key]] = p
            continue
        seen[key] = len(out)
        out.append(p)
    return out, times, {1: g1, 2: g2}


def _camp_events(camp: dict, t1: str, t2: str) -> list[dict]:
    if not camp:
        return []
    hero = {str(p.get("playerId")): str(p.get("heroName") or "") for p in (camp.get("matchInfo") or [])}
    ppi = {str(p.get("playerID")): p for p in ((camp.get("reportData") or {}).get("playerPosInfo") or [])}
    out: list[dict] = []

    # 死亡/复活：deathPosArr + revivePosArr
    for pb in camp.get("playBaseInfoArr") or []:
        pid = str(pb.get("playID") or "")
        camp_no = str(pb.get("acntCamp") or "")
        team = t1 if camp_no == "1" else t2
        deaths, revives = [], []
        for d in pb.get("deathPosArr") or []:
            try:
                deaths.append(int(float(d.get("time"))))
            except (TypeError, ValueError):
                pass
        for r in (ppi.get(pid) or {}).get("revivePosArr") or []:
            if isinstance(r, (list, tuple)) and len(r) >= 3:
                try:
                    revives.append(int(float(r[2])))
                except (TypeError, ValueError):
                    pass
        deaths.sort(); revives.sort(); used: set[int] = set()
        for dt in deaths:
            rt = next((r for r in revives if r > dt and r not in used), None)
            if rt is not None:
                used.add(rt)
            h = hero.get(pid, "?")
            out.append({
                "m": round(dt / 60.0, 2),
                "l": "死亡 · " + h + "（" + team + "）",
                "t": "death", "team": team, "camp": camp_no, "hero": h,
                "respawn_sec": (rt - dt) if rt is not None else None,
                "censored": 0 if rt is not None else 1,
                "src": "camp",
            })

    # 击杀（只取 isKeyEvent=1，避免 45 条击杀刷屏）/ 推塔
    first_kill = None
    for e in camp.get("keyEventArr") or []:
        dd = e.get("dtData") or {}
        try:
            m = float(dd.get("killTime") or 0) / 1000.0 / 60.0
        except (TypeError, ValueError):
            continue
        typ = str(dd.get("dtType") or "")
        camp_no = str(dd.get("dtCamp") or "")
        team = t1 if camp_no == "1" else t2
        if typ == "1":
            if first_kill is None or m < first_kill[0]:
                first_kill = (m, team)
            continue
        elif typ == "2":
            out.append({"m": round(m, 2), "l": "推塔 · " + team, "t": "tower",
                        "team": team, "src": "camp"})
    if first_kill:
        out.append({"m": round(first_kill[0], 2), "l": "一血 · " + first_kill[1],
                    "t": "first_blood", "team": first_kill[1], "src": "camp"})
    return out


def _merge_events(local_events: list[dict], camp_events: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[tuple] = set()
    camp_has_fb = any(e.get("t") == "first_blood" for e in camp_events)

    def add(e: dict):
        key = (str(e.get("t")), round(float(e.get("m") or 0), 1), str(e.get("l")))
        if key in seen:
            return
        seen.add(key)
        out.append(e)

    for e in local_events:
        if camp_has_fb and e.get("t") == "first_blood":
            continue
        add(dict(e, src="live"))
    for e in camp_events:
        if e.get("t") == "tower" and any(
            x.get("t") == "tower" and x.get("team") == e.get("team")
            and abs(float(x.get("m") or 0) - float(e.get("m") or 0)) < 0.6
            for x in out
        ):
            continue
        add(dict(e))
    out.sort(key=lambda e: (float(e.get("m") or 0), str(e.get("t"))))
    return out


def _attach_impact(events: list[dict], gold_curve: list[dict], duration: float,
                   team_times: list[float], team_gold: dict) -> None:
    for e in events:
        m = float(e.get("m") or 0)
        typ = str(e.get("t") or "")
        if typ == "death":
            if e.get("respawn_sec"):
                window = int(e.get("respawn_sec"))
            else:
                window = max(0, int((duration - m) * 60))
        elif typ in NEUTRAL_BUFFS:
            window = int(NEUTRAL_BUFFS[typ]["duration_sec"])
        else:
            window = 60
        end = min(duration, m + window / 60.0)
        g0, g1 = _gd_at(gold_curve, m), _gd_at(gold_curve, end)
        e["window_sec"] = window
        e["g0"] = round(g0)
        e["g1"] = round(g1)
        e["dgd"] = round(g1 - g0)
        e["impact_basis"] = "observed"
        e["key"] = 1 if (typ in ("death", "first_blood", "tyrant", "dark_tyrant", "lord", "storm")
                         or abs(e["dgd"]) >= 300) else 0
        if typ in NEUTRAL_BUFFS:
            cfg = NEUTRAL_BUFFS[typ]
            e["buff_window_sec"] = cfg["duration_sec"]
            e["buff_spawn_min"] = cfg["spawn_min"]
            e["buff_respawn_min"] = cfg["respawn_min"]
            e["buff_note"] = "buff 时长按版本表可配"
        if typ == "death":
            camp_no = str(e.get("camp") or "")
            if e.get("censored"):
                e["lost_farm_est"] = 0
                e["loss_basis"] = "终局未复活"
            elif camp_no in ("1", "2") and team_times and team_gold.get(int(camp_no)):
                arr = team_gold[int(camp_no)]
                before = max(0.0, m - 2.0)
                g_before = _interp(team_times, arr, before)
                g_now = _interp(team_times, arr, m)
                rate = (g_now - g_before) / max(1.0, (m - before) * 60.0)
                e["lost_farm_est"] = round(max(0.0, rate * window * 0.2))
                e["loss_basis"] = "队伍金速×复活×20%"


def build_battle(battle_id: str, meta: dict) -> dict | None:
    snap_dir = RAW_DIR / battle_id
    if not snap_dir.is_dir():
        return None
    snaps = load_battle_jsons(snap_dir)
    if len(snaps) < MIN_FRAMES:
        return None
    camp_path = meta.get("camp_path")
    camp = jload(Path(camp_path), {}) if camp_path else {}

    # 模型胜率（camp1 视角），按分钟归并
    # 口径优先级：直播时真实写下的 predictions CSV > 赛后重放（重放在回补局上波动很大，
    # 只能当参考；CSV 才是"当时模型说的话"，复盘页面必须优先用它）。
    prob_by_bin: dict[int, float] = {}
    low_bin: set[int] = set()
    source = "replay"
    csv_path = PREDICTION_DIR / f"{battle_id}.csv"
    if csv_path.exists():
        try:
            pred = pd.read_csv(csv_path)
            for _, r in pred.iterrows():
                v = r.get("camp1_win_prob")
                m = r.get("minute")
                if pd.isna(v) or pd.isna(m):
                    continue
                b = int(float(m)) or 1
                prob_by_bin[b] = round(float(v), 3)
            if prob_by_bin:
                source = "live"
        except (OSError, pd.errors.ParserError):
            pass
    if not prob_by_bin:
        try:
            tl = _replay_v11_timeline(battle_id)
            if tl is not None and len(tl):
                for _, r in tl.iterrows():
                    b = int(r.get("minute_bin") or 0)
                    v = r.get("camp1_win_prob")
                    if b and pd.notna(v):
                        prob_by_bin[b] = round(float(v), 3)
                    if b and bool(r.get("low_confidence")):
                        low_bin.add(b)
        except Exception:
            prob_by_bin = {}

    # 每帧字段：同分钟取最后一帧。
    # status=2 是官方终局摘要，不是普通局内帧：它的推塔/资源字段会切换成另一套
    # 语义（例如 G1 从 9:5 变成 6:6），混进时间轴会造成累计值回退。
    # 胜方仍从终局快照/Index 取；时间轴只保留 status=1 的实时快照。
    by_bin: dict[int, dict] = {}
    for s in snaps:
        try:
            if int(s.get("status") or 0) == 2:
                continue
            mb = int(s.get("minute_bin") or 0) or int(float(s.get("minute") or 0)) or 1
        except (TypeError, ValueError):
            continue
        by_bin[mb] = s

    last = snaps[-1]
    c1 = str(last.get("camp1_team") or meta.get("team1") or "")
    c2 = str(last.get("camp2_team") or meta.get("team2") or "")
    win = int(last.get("win_camp") or 0)
    if win not in (1, 2):
        # 快照最后一帧可能还是进行中（status=1），退回用分析表里的胜方队名
        winner = str(meta.get("winner") or "")
        win = 1 if winner == c1 else 2 if winner == c2 else 0

    # 五人经济按分路序固化：索引 i 在整个时间轴上恒对应同一名选手
    roster = _roster(snaps)

    frames = []
    for mb in sorted(by_bin):
        s = by_bin[mb]
        try:
            minute = round(float(s.get("minute") or mb), 1)
        except (TypeError, ValueError):
            minute = float(mb)
        frames.append({
            "m": minute,
            "p": prob_by_bin.get(mb),
            "lc": 1 if mb in low_bin else 0,
            "gd": int(s.get("camp1_gold") or 0) - int(s.get("camp2_gold") or 0),
            "k": [int(s.get("camp1_kill") or 0), int(s.get("camp2_kill") or 0)],
            "t": [int(s.get("camp1_tower") or 0), int(s.get("camp2_tower") or 0)],
            "o": [
                [int(s.get("camp1_tyrant") or 0), int(s.get("camp1_dark_tyrant") or 0),
                 int(s.get("camp1_lord") or 0), int(s.get("camp1_storm") or 0)],
                [int(s.get("camp2_tyrant") or 0), int(s.get("camp2_dark_tyrant") or 0),
                 int(s.get("camp2_lord") or 0), int(s.get("camp2_storm") or 0)],
            ],
            "g": [_pos_golds(s, 1, roster[1]), _pos_golds(s, 2, roster[2])],
        })
    if len(frames) < MIN_FRAMES:
        return None
    if len(frames) > MAX_FRAMES:  # 控制体积：等距抽样，保底首末帧
        step = len(frames) / MAX_FRAMES
        picked = [frames[int(i * step)] for i in range(MAX_FRAMES)]
        picked[-1] = frames[-1]
        frames = picked

    # names 与 frames[].g 共用同一份分路序名单：names[0..4]=阵营1、names[5..9]=阵营2
    names = (roster[1] + [""] * (POS_COUNT - len(roster[1]))
             + roster[2] + [""] * (POS_COUNT - len(roster[2])))
    pcamp = [1] * POS_COUNT + [2] * POS_COUNT

    gold_curve, camp_times, camp_team_gold = _camp_gold_curve(camp, frames)
    if not gold_curve:
        gold_curve = _local_gold_curve(frames)
    if not camp_times:
        camp_times = [0.0] + [float(f["m"]) for f in frames]
        camp_team_gold = {
            1: [0] + [sum(f["g"][0]) for f in frames],
            2: [0] + [sum(f["g"][1]) for f in frames],
        }

    local_events = []
    for e in detect_events(snaps):
        if int(e.get("weight") or 0) < 2:      # 一血/暴君也保留；只丢弃纯噪声
            continue
        m = round(float(e.get("minute") or 0), 1)
        label = str(e.get("label") or "")
        local_events.append({
            "m": m, "l": label, "t": str(e.get("type") or ""),
            "team": str(e.get("team") or ""),
        })
    events = _merge_events(local_events, _camp_events(camp, c1, c2))
    _attach_impact(events, gold_curve, float(frames[-1]["m"]), camp_times, camp_team_gold)

    return {
        "battleId": battle_id,
        "src": source,          # live = 直播时真实预测；replay = 赛后重放
        "seq": int(meta.get("game_no") or 0),
        "win": win,
        "dur": round(float(last.get("minute") or 0), 1),
        "t1": c1, "t2": c2,
        "names": names, "pcamp": pcamp,
        "frames": frames,
        "gold_curve": gold_curve,
        "gold_src": "camp+local" if any(p.get("src") == "camp" for p in gold_curve) else "local",
        "events": events,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略缓存全量重建")
    args = ap.parse_args()

    t0 = time.time()
    if not GAMES_INDEX.exists():
        print(f"缺少 {GAMES_INDEX}，先跑 build_game_details.py")
        return
    game_index = jload_js(GAMES_INDEX)                 # {matchId: {lg, b: [[bid, seq, dur, winCamp, winTeam]]}}
    sched = {str(r.get("matchId")): r for r in jload_js(SCHEDULE_ALL)}
    camp_index = load_camp_index()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {} if args.force else jload(MANIFEST_PATH, {})
    rebuilt = 0
    built_battles = 0
    index: dict[str, dict] = {}
    by_match: dict[str, list[dict]] = {}
    for mid, entry in game_index.items():
        rows = []
        for row in (entry.get("b") or []):
            bid = str(row[0])
            if not (RAW_DIR / bid).is_dir():
                continue
            meta = sched.get(str(mid)) or {}
            parts = bid.split("_")
            camp_path = camp_index.get((str(mid), parts[2])) if len(parts) == 3 else None
            rows.append({
                "battle_id": bid,
                "match_id": str(mid),
                "camp_path": camp_path,
                "game_no": int(row[1] or 0),
                "win_camp": int(row[3] or 0),
                "winner": str(row[4] or ""),
                "team1": str(meta.get("team1") or ""),
                "team2": str(meta.get("team2") or ""),
                "date": str(meta.get("date") or ""),
                "league_id": str(entry.get("lg") or meta.get("leagueId") or ""),
            })
        if rows:
            by_match.setdefault(str(mid), []).extend(rows)
    if not by_match:
        print("没有任何局具备分钟级快照")
        return

    for match_id, rows in sorted(by_match.items()):
        rows.sort(key=lambda r: int(r.get("game_no") or 0))
        lg = str(rows[0].get("league_id") or "")
        date = str(rows[0].get("date") or "")
        payload_battles = []
        sig_parts = []
        for r in rows:
            bid = str(r["battle_id"])
            snap_dir = RAW_DIR / bid
            try:
                camp_mtime = 0
                if r.get("camp_path"):
                    camp_mtime = int(Path(r["camp_path"]).stat().st_mtime)
                sig = f"{BUILD_VERSION}:{int(snap_dir.stat().st_mtime)}:{len(list(snap_dir.glob('*.json')))}:{camp_mtime}"
            except OSError:
                continue
            sig_parts.append(f"{bid}={sig}")
            cache = manifest.get(bid)
            if cache and cache.get("sig") == sig and not args.force:
                built_battles += 1
                continue
            built = build_battle(bid, r)
            if not built:
                manifest[bid] = {"sig": sig, "miss": 1}
                continue
            rebuilt += 1
            built_battles += 1
            manifest[bid] = {"sig": sig, "match": match_id, "data": built}
        # 逐局数据从 manifest 取（跨增量复用）
        for r in rows:
            bid = str(r["battle_id"])
            item = manifest.get(bid) or {}
            if item.get("data") and not item.get("miss"):
                payload_battles.append(item["data"])
        if not payload_battles:
            continue
        payload_battles.sort(key=lambda b: b["seq"])
        out = {
            "matchId": match_id, "lg": lg, "date": date,
            "t1": str(rows[0].get("team1") or ""), "t2": str(rows[0].get("team2") or ""),
            "battles": payload_battles,
        }
        (OUT_DIR / f"{match_id}.json").write_text(
            json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        index[match_id] = {
            "lg": lg, "date": date, "t1": out["t1"], "t2": out["t2"],
            "b": [b["battleId"] for b in payload_battles],
            # 是否有模型胜率（徽标"模型估算"）：帧里出现过非空概率即算有
            "p": [1 if any(fr.get("p") is not None for fr in b["frames"]) else 0 for b in payload_battles],
        }

    INDEX_PATH.write_text("KPL_REPLAY_INDEX = " + json.dumps(index, ensure_ascii=False, separators=(",", ":")) + ";\n",
                          encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # ---- 数据完整度徽标索引（按大场聚合，供首页/赛程/比赛页在点进去之前就能判断） ----
    # bit0 比分 · bit1 完整BP · bit2 选手明细 · bit3 分钟级曲线 · bit4 模型估算
    coverage = {}
    try:
        gindex = jload_js(GAMES_INDEX)
    except Exception:
        gindex = {}
    for mid, entry in gindex.items():
        mask = 0
        for row in entry.get("b") or []:
            flags = int(row[5] or 0) if len(row) > 5 else 0
            if flags & 1:
                mask |= 2
            if flags & 2:
                mask |= 4
        if entry.get("b"):
            mask |= 1
        rp = index.get(str(mid))
        if rp:
            mask |= 8
            if any(rp.get("p") or []):
                mask |= 16
        coverage[str(mid)] = mask
    (SITE / "assets" / "coverage.js").write_text(
        "KPL_COVERAGE = " + json.dumps(coverage, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8")

    total_kb = sum(p.stat().st_size for p in OUT_DIR.glob("*.json")) / 1024
    print(f"replay: {len(index)} 场 / {built_battles} 局 · 本次重建 {rebuilt} 局 · "
          f"{total_kb:.0f} KB · coverage {len(coverage)} 场 · {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
