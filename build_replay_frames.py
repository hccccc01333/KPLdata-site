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
import sys
import time
from pathlib import Path

import pandas as pd

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
sys.path.insert(0, str(PROJ / "scripts"))

from kpl_official_core import (  # noqa: E402
    PREDICTION_DIR,
    RAW_DIR,
    _replay_v11_timeline,
    detect_events,
    load_battle_jsons,
)

OUT_DIR = SITE / "assets" / "replay"
INDEX_PATH = OUT_DIR / "index.js"
MANIFEST_PATH = OUT_DIR / ".manifest.json"
ANALYSIS = PROJ / "data" / "analysis" / "battles.csv"
MIN_FRAMES = 6
MAX_FRAMES = 40
POS_COUNT = 5


def jload(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _pos_golds(snap: dict, camp: int) -> list[int]:
    """该阵营五人的金币（按选手名排序，保证跨帧同一顺序）。"""
    ps = sorted(
        [p for p in (snap.get("players") or []) if int(p.get("camp") or 0) == camp],
        key=lambda p: str(p.get("player_name") or p.get("actual_player_name") or ""),
    )
    out = []
    for p in ps[:POS_COUNT]:
        try:
            out.append(int(float(p.get("gold") or 0)))
        except (TypeError, ValueError):
            out.append(0)
    while len(out) < POS_COUNT:
        out.append(0)
    return out


def build_battle(battle_id: str, meta: dict) -> dict | None:
    snap_dir = RAW_DIR / battle_id
    if not snap_dir.is_dir():
        return None
    snaps = load_battle_jsons(snap_dir)
    if len(snaps) < MIN_FRAMES:
        return None

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

    # 每帧字段：同分钟取最后一帧
    by_bin: dict[int, dict] = {}
    for s in snaps:
        try:
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
            "g": [_pos_golds(s, 1), _pos_golds(s, 2)],
        })
    if len(frames) < MIN_FRAMES:
        return None
    if len(frames) > MAX_FRAMES:  # 控制体积：等距抽样，保底首末帧
        step = len(frames) / MAX_FRAMES
        picked = [frames[int(i * step)] for i in range(MAX_FRAMES)]
        picked[-1] = frames[-1]
        frames = picked

    names = []
    pcamp = []
    seen_players = sorted(
        [p for p in (last.get("players") or []) if int(p.get("camp") or 0) in (1, 2)],
        key=lambda p: (int(p.get("camp") or 0), str(p.get("player_name") or p.get("actual_player_name") or "")),
    )
    for p in seen_players[: POS_COUNT * 2]:
        names.append(str(p.get("player_name") or p.get("actual_player_name") or ""))
        pcamp.append(int(p.get("camp") or 0))

    events = []
    seen_ev = set()
    for e in detect_events(snaps):
        if int(e.get("weight") or 0) < 3:      # 只保留结构性事件（推塔/远古资源/一血）
            continue
        m = round(float(e.get("minute") or 0), 1)
        label = str(e.get("label") or "")
        key = (m, label)
        if key in seen_ev:
            continue
        seen_ev.add(key)
        events.append({"m": m, "l": label, "t": str(e.get("type") or "")})
    events.sort(key=lambda e: e["m"])

    return {
        "battleId": battle_id,
        "src": source,          # live = 直播时真实预测；replay = 赛后重放
        "seq": int(meta.get("game_no") or 0),
        "win": win,
        "dur": round(float(last.get("minute") or 0), 1),
        "t1": c1, "t2": c2,
        "names": names, "pcamp": pcamp,
        "frames": frames,
        "events": events,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略缓存全量重建")
    args = ap.parse_args()

    t0 = time.time()
    if not ANALYSIS.exists():
        print(f"缺少分析表 {ANALYSIS}，先跑 02 仓库的 build_history_dataset.py")
        return
    df = pd.read_csv(ANALYSIS)
    df = df[df["has_timeline"].astype(bool)]
    if df.empty:
        print("分析表里没有带分钟级曲线的对局")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {} if args.force else jload(MANIFEST_PATH, {})
    rebuilt = 0
    built_battles = 0
    index: dict[str, dict] = {}
    by_match: dict[str, list[dict]] = {}
    for _, row in df.iterrows():
        by_match.setdefault(str(row["match_id"]), []).append(row.to_dict())

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
                sig = f"{int(snap_dir.stat().st_mtime)}:{len(list(snap_dir.glob('*.json')))}"
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
        index[match_id] = {"lg": lg, "date": date, "t1": out["t1"], "t2": out["t2"],
                           "b": [b["battleId"] for b in payload_battles]}

    INDEX_PATH.write_text("KPL_REPLAY_INDEX = " + json.dumps(index, ensure_ascii=False, separators=(",", ":")) + ";\n",
                          encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    total_kb = sum(p.stat().st_size for p in OUT_DIR.glob("*.json")) / 1024
    print(f"replay: {len(index)} 场 / {built_battles} 局 · 本次重建 {rebuilt} 局 · "
          f"{total_kb:.0f} KB · {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
