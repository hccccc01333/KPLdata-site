# -*- coding: utf-8 -*-
"""生成胜率沙盘数据 assets/sandbox.js。

输入：
  assets/replay/*.json                      212 局逐分钟回放（曲线 / 金差 / 资源 / 事件）
  data/realtime/backtest_v9_report.json     V12 独立 test 段指标与最差对局
  data/realtime/predictions/*.csv           直播预测档案（用于校准形态，非 test）
  data/realtime/replay_cache/*.json         V12 重放缓存（优先复用，避免重复推理）
  assets/predict.js                         站点已有的直播统计（分时点命中率等）

沙盘的 p 统一来自 V12 重放：先用 replay_cache；未覆盖的局用当前模型补齐，
写入 .sandbox_v12_cache.json（按模型 mtime 失效）。首次补齐较慢，之后走缓存。
不重新训练模型；重新预测仅发生在缓存未覆盖的局。

输出：
  assets/sandbox.js  KPL_SANDBOX = {...}
    - surface   分钟 × 金差网格：历史同状态胜率 / V12 均值 / 样本数 / Wilson 区间
    - battles   212 局压缩后的曲线、事件、结果（每局标注 src=v12/none）
    - calibration 直播档案可靠性分箱
    - model     test 指标、分阶段、翻盘局、最差对局
运行：
  python build_sandbox_data.py
"""
from __future__ import annotations

import csv
import json
import math
import sys
import warnings
from bisect import bisect_right
from collections import deque
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
REALTIME = PROJ / "data" / "realtime"
REPLAY_DIR = SITE / "assets" / "replay"
PRED_DIR = REALTIME / "predictions"
REPLAY_CACHE_DIR = REALTIME / "replay_cache"
V12_CACHE_PATH = SITE / ".sandbox_v12_cache.json"
MODEL_PATH = PROJ / "output" / "models" / "v9_official_platform.joblib"

MINUTE_EDGES = [0, 4, 8, 12, 16, 20, 24, 40]
GOLD_EDGES = [-20000, -12000, -8000, -5000, -3000, -1000, 1000, 3000, 5000, 8000, 12000, 20000]
MINUTE_LABELS = ["0–4", "4–8", "8–12", "12–16", "16–20", "20–24", "24+"]
GOLD_LABELS = ["落后 2 万以上", "落后 1.2~2 万", "落后 0.8~1.2 万", "落后 0.5~0.8 万",
               "落后 0.3~0.5 万", "落后 0.1~0.3 万", "基本持平（±0.1 万）",
               "领先 0.1~0.3 万", "领先 0.3~0.5 万", "领先 0.5~0.8 万",
               "领先 0.8~1.2 万", "领先 1.2 万以上"]
PRIOR_STRENGTH = 4.0
PRIOR_MEAN = 0.5


def jload(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def jload_js(path: Path, default=None):
    try:
        text = path.read_text(encoding="utf-8")
        return json.loads(text[text.index("=") + 1:].rstrip().rstrip(";"))
    except Exception:
        return default


def r3(value):
    if value is None:
        return None
    try:
        if math.isnan(float(value)):
            return None
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def rint(value):
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def wilson(wins: int, n: int, z: float = 1.96):
    if n <= 0:
        return None, None
    p = wins / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return round(max(0.0, center - half), 3), round(min(1.0, center + half), 3)


def objective_diff(frame: dict) -> int:
    """把双方资源数组压成一个可比较的资源差（暴君/黑暗暴君/主宰/风暴龙王）。"""
    o = frame.get("o") or [[0, 0, 0, 0], [0, 0, 0, 0]]
    weights = (2, 4, 3, 6)
    try:
        return int(round(sum((int(o[0][i]) - int(o[1][i])) * weights[i] for i in range(4))))
    except (IndexError, TypeError, ValueError):
        return 0


def nearest_p(pairs, minute, max_gap: float = 1.5):
    """在一组 (minute, p) 里找最接近当前帧的 V12 概率；超出 max_gap 视为缺失。"""
    best = None
    best_d = max_gap + 1e-9
    for m, p in pairs or []:
        d = abs(float(m) - float(minute))
        if d < best_d:
            best_d = d
            best = p
    return best


def load_replay_cache():
    """读取 core 仓库已有的 V12 重放缓存：replay_cache/<battle>.json 的 row.pairs[2]。"""
    out = {}
    if not REPLAY_CACHE_DIR.is_dir():
        return out
    backtest = jload(REALTIME / "backtest_v9_report.json", {}) or {}
    expected_version = str(backtest.get("version") or "")
    for path in REPLAY_CACHE_DIR.glob("*.json"):
        data = jload(path, {}) or {}
        fp = str(data.get("fp") or "")
        # 模型换版后旧重放缓存不能继续冒充当前模型；宁可重算，也不混版本。
        if expected_version and not fp.startswith(expected_version + "|"):
            continue
        row = data.get("row") or {}
        bid = str(row.get("battle_id") or path.stem)
        pairs = []
        for pair in row.get("pairs") or []:
            try:
                minute = float(pair[0])
                p = float(pair[2])
            except (IndexError, TypeError, ValueError):
                continue
            if 0.0 <= p <= 1.0:
                pairs.append((minute, p))
        if pairs:
            out[bid] = pairs
    return out


def load_local_v12_cache(model_mtime: float):
    """本地补齐缓存：只保存 replay_cache 没覆盖的局，按模型文件 mtime 失效。"""
    data = jload(V12_CACHE_PATH, {}) or {}
    try:
        if int(data.get("modelMtime") or -1) != int(model_mtime):
            return {}
    except (TypeError, ValueError):
        return {}
    out = {}
    for bid, pairs in (data.get("battles") or {}).items():
        clean = []
        for pair in pairs or []:
            try:
                clean.append((float(pair[0]), float(pair[1])))
            except (IndexError, TypeError, ValueError):
                continue
        if clean:
            out[str(bid)] = clean
    return out


def save_local_v12_cache(model_mtime: float, computed: dict):
    if not computed:
        return
    # 关键：只写“这次新补的局”会覆盖上一次缓存，导致下次又把旧局全部重算。
    merged = dict(load_local_v12_cache(model_mtime))
    merged.update(computed)
    save = {
        "modelMtime": int(model_mtime),
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "battles": {bid: [[m, p] for m, p in pairs] for bid, pairs in merged.items()},
    }
    V12_CACHE_PATH.write_text(json.dumps(save, ensure_ascii=False, separators=(",", ":")),
                              encoding="utf-8")


def compute_missing_v12(battles, v12_map):
    """用当前 V12 模型补齐缓存未覆盖的局；一次重放后写入本地缓存。"""
    need = []
    for b in battles:
        pairs = v12_map.get(b["id"]) or []
        matched = sum(1 for f in b["frames"] if nearest_p(pairs, f[0]) is not None)
        if matched < max(1, int(len(b["frames"]) * 0.7)):
            need.append(b)
    if not need:
        return v12_map
    print(f"[sandbox] V12 重放补齐 {len(need)} 局（首次会慢，之后走缓存）...")
    sys.path.insert(0, str(PROJ / "scripts"))
    warnings.filterwarnings("ignore", message="Trying to unpickle estimator")
    try:
        import kpl_official_core as core
        artifact = core.load_model()
    except Exception as exc:
        print(f"[warn] 无法加载 V12，保留现有概率：{exc}")
        return v12_map
    if not artifact:
        print("[warn] 没有模型产物，保留现有概率")
        return v12_map
    computed = {}
    for idx, b in enumerate(need, 1):
        battle_dir, _ = core._resolve_battle_snapshot_dir(b["id"])
        if battle_dir is None:
            continue
        snaps = core.load_battle_jsons(battle_dir)
        if not snaps:
            continue
        history = deque(maxlen=40)
        seen = set()
        pairs = []
        for snap in snaps:
            minute_bin = max(int(snap.get("minute_bin") or snap.get("minute") or 1), 1)
            history.append(snap)
            if minute_bin in seen:
                continue
            seen.add(minute_bin)
            try:
                p, _, _ = core.predict_probability(artifact, snap, list(history))
            except Exception:
                continue
            pairs.append((round(float(snap.get("minute") or minute_bin), 1), round(float(p), 3)))
        if pairs:
            computed[b["id"]] = pairs
            v12_map[b["id"]] = pairs
        if idx % 5 == 0 or idx == len(need):
            print(f"[sandbox]   {idx}/{len(need)} ...")
    save_local_v12_cache(MODEL_PATH.stat().st_mtime if MODEL_PATH.exists() else 0, computed)
    return v12_map


def apply_v12(battles, v12_map):
    """把沙盘使用的 p 统一替换为 V12 重放；缺失帧留空，不拿直播旧模型顶替。"""
    for b in battles:
        pairs = v12_map.get(b["id"]) or []
        matched = 0
        for f in b["frames"]:
            p = nearest_p(pairs, f[0])
            if p is None:
                f[1] = None
            else:
                f[1] = round(float(p), 3)
                matched += 1
        b["src"] = "v12" if matched else "none"
        b["v12Frames"] = matched
    return battles


def load_replay():
    battles = []
    for path in sorted(REPLAY_DIR.glob("*.json")):
        if path.name.startswith("."):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        mid = str(data.get("matchId") or path.stem)
        date = str(data.get("date") or "")
        for b in data.get("battles") or []:
            try:
                win = int(b.get("win") or 0)
            except (TypeError, ValueError):
                win = 0
            if win not in (1, 2):
                continue
            frames = []
            for fr in b.get("frames") or []:
                try:
                    minute = round(float(fr.get("m") or 0), 1)
                except (TypeError, ValueError):
                    continue
                p = fr.get("p")
                try:
                    p = None if p is None else round(float(p), 3)
                except (TypeError, ValueError):
                    p = None
                try:
                    gd = rint(fr.get("gd"))
                    k = fr.get("k") or [0, 0]
                    t = fr.get("t") or [0, 0]
                    kd = rint(k[0]) - rint(k[1])
                    td = rint(t[0]) - rint(t[1])
                except (IndexError, TypeError, ValueError):
                    gd = kd = td = 0
                frames.append([minute, p, gd, kd, td, objective_diff(fr)])
            if not frames or not any(f[1] is not None for f in frames):
                continue
            events = []
            for ev in b.get("events") or []:
                try:
                    em = round(float(ev.get("m") or 0), 1)
                except (TypeError, ValueError):
                    continue
                events.append([em, str(ev.get("t") or ""), str(ev.get("l") or "")])
            battles.append({
                "id": str(b.get("battleId") or ""),
                "mid": mid,
                "date": date,
                "t1": str(b.get("t1") or data.get("t1") or ""),
                "t2": str(b.get("t2") or data.get("t2") or ""),
                "seq": rint(b.get("seq")),
                "win": win,
                "dur": round(float(b.get("dur") or 0), 1),
                "src": str(b.get("src") or ""),
                "frames": frames,
                "events": events,
            })
    battles.sort(key=lambda x: (x["date"], x["mid"], x["seq"]), reverse=True)
    return battles


def build_matches(battles):
    matches = []
    index = {}
    for i, b in enumerate(battles):
        m = index.get(b["mid"])
        if m is None:
            m = {"id": b["mid"], "date": b["date"], "t1": b["t1"], "t2": b["t2"], "battles": []}
            index[b["mid"]] = m
            matches.append(m)
        m["battles"].append(i)
    return matches


def build_surface(battles):
    cells = []
    for mi in range(len(MINUTE_EDGES) - 1):
        for gi in range(len(GOLD_EDGES) - 1):
            cells.append({"mi": mi, "gi": gi, "n": 0, "wins": 0, "sumP": 0.0})
    for b in battles:
        label = 1 if b["win"] == 1 else 0
        for f in b["frames"]:
            p = f[1]
            if p is None:
                continue
            mi = clamp(bisect_right(MINUTE_EDGES, f[0]) - 1, 0, len(MINUTE_EDGES) - 2)
            gi = clamp(bisect_right(GOLD_EDGES, f[2]) - 1, 0, len(GOLD_EDGES) - 2)
            c = cells[mi * (len(GOLD_EDGES) - 1) + gi]
            c["n"] += 1
            c["wins"] += label
            c["sumP"] += float(p)
    out = []
    for c in cells:
        n = c["n"]
        if n == 0:
            out.append({"mi": c["mi"], "gi": c["gi"], "n": 0, "obs": None, "hist": None,
                        "lo": None, "hi": None, "model": None})
            continue
        wins = c["wins"]
        obs = wins / n
        hist = (wins + PRIOR_STRENGTH * PRIOR_MEAN) / (n + PRIOR_STRENGTH)
        lo, hi = wilson(wins, n)
        out.append({
            "mi": c["mi"], "gi": c["gi"], "n": n,
            "obs": round(obs, 3), "hist": round(hist, 3),
            "lo": lo, "hi": hi,
            "model": round(c["sumP"] / n, 3),
        })
    return {
        "minuteEdges": MINUTE_EDGES,
        "goldEdges": GOLD_EDGES,
        "minuteLabels": MINUTE_LABELS,
        "goldLabels": GOLD_LABELS,
        "cells": out,
    }


def build_calibration():
    bins = [{"lo": i / 10.0, "hi": (i + 1) / 10.0, "pairs": []} for i in range(10)]
    n_battles = 0
    n_points = 0
    if not PRED_DIR.exists():
        return {"bins": [], "nBattles": 0, "nPoints": 0, "ece": None, "note": "无直播预测档案"}
    for path in sorted(PRED_DIR.glob("*.csv")):
        p_by_minute = {}
        win = 0
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    try:
                        p = float(row.get("camp1_win_prob") or "")
                    except (TypeError, ValueError):
                        continue
                    if not (0.0 <= p <= 1.0):
                        continue
                    try:
                        m = int(float(row.get("minute") or ""))
                    except (TypeError, ValueError):
                        continue
                    try:
                        wc = int(float(row.get("win_camp") or 0))
                    except (TypeError, ValueError):
                        wc = 0
                    if wc in (1, 2):
                        win = wc
                    p_by_minute[m] = p
        except OSError:
            continue
        if win not in (1, 2) or not p_by_minute:
            continue
        n_battles += 1
        for m, p in p_by_minute.items():
            idx = min(int(p * 10), 9)
            bins[idx]["pairs"].append((p, 1 if win == 1 else 0))
            n_points += 1
    out = []
    ece = 0.0
    for b in bins:
        pairs = b["pairs"]
        n = len(pairs)
        if n == 0:
            out.append({"lo": b["lo"], "hi": b["hi"], "n": 0, "meanP": None, "obs": None})
            continue
        mean_p = sum(p for p, _ in pairs) / n
        obs = sum(y for _, y in pairs) / n
        ece += (n / n_points) * abs(obs - mean_p)
        out.append({
            "lo": b["lo"], "hi": b["hi"], "n": n,
            "meanP": round(mean_p, 3), "obs": round(obs, 3),
        })
    return {
        "bins": out,
        "nBattles": n_battles,
        "nPoints": n_points,
        "ece": round(ece, 3) if n_points else None,
        "note": "直播档案，不是独立 test；同一局相邻帧高度相关，只用于观察校准形态。",
    }


def enrich_battle(b, by_id):
    src = by_id.get(str(b.get("battle_id") or ""))
    return {
        "id": str(b.get("battle_id") or ""),
        "brier": r3(b.get("brier")),
        "acc": r3(b.get("acc")),
        "isComeback": bool(b.get("is_comeback")),
        "t1": (src or {}).get("t1", ""),
        "t2": (src or {}).get("t2", ""),
        "date": (src or {}).get("date", ""),
        "seq": (src or {}).get("seq", 0),
        "mid": (src or {}).get("mid", ""),
        "nPoints": rint((src or {}).get("n_points")) if src else 0,
    }


def analog_rate(states, s, exclude):
    """同状态历史胜率（与前端相同的距离权重），用于挑一个“模型与历史不打架”的默认帧。"""
    rows = []
    for bi, fi, b, f in states:
        if bi == exclude:
            continue
        dist = (abs(f[0] - s[0]) / 4 * 1.1 + abs(f[2] - s[2]) / 3000
                + abs(f[3] - s[3]) / 3 * 0.45 + abs(f[4] - s[4]) / 2.5 * 0.65
                + abs(f[5] - s[5]) / 6 * 0.5)
        rows.append((dist, b))
    rows.sort(key=lambda x: x[0])
    top = rows[:40]
    if not top:
        return None
    return sum(1 for _, b in top if b["win"] == 1) / len(top)


def choose_default(battles):
    """默认展示一局：有摆动但不要一帧翻转，且 V12 与同状态历史不要差太多。"""
    states = []
    for bi, b in enumerate(battles):
        for fi, f in enumerate(b["frames"]):
            if f[1] is not None:
                states.append((bi, fi, b, f))
    best = (-1e9, 0, 0)
    for bi, b in enumerate(battles):
        ps = [(f[0], f[1]) for f in b["frames"] if f[1] is not None]
        if len(ps) < 8:
            continue
        vals = [p for _, p in ps]
        swing = max(vals) - min(vals)
        jumps = max((abs(vals[j] - vals[j - 1]) for j in range(1, len(vals))), default=0.0)
        if swing < 0.45:
            continue
        for fi, f in enumerate(b["frames"]):
            if f[1] is None or not (9 <= f[0] <= 16) or not (0.3 <= f[1] <= 0.7):
                continue
            hr = analog_rate(states, (f[0], f[1], f[2], f[3], f[4], f[5]), bi)
            if hr is None:
                continue
            gap = abs(f[1] - hr)
            if gap > 0.22:
                continue
            score = 0.55 * swing - 0.15 * jumps - 1.2 * gap - 0.25 * abs(f[1] - 0.5)
            if score > best[0]:
                best = (score, bi, fi)
    if best[0] <= -1e9:
        return 0, 0
    return best[1], best[2]


def build_model(battles):
    backtest = jload(REALTIME / "backtest_v9_report.json", {}) or {}
    by_id = {b["id"]: b for b in battles}
    hr = backtest.get("holdout_real") or {}
    headline = backtest.get("headline") or {}
    phases = {}
    for ph in ("early", "mid", "late", "all"):
        m = hr.get(ph) or {}
        if not m:
            continue
        phases[ph] = {
            "n": rint(m.get("n")),
            "brier": r3(m.get("brier")),
            "acc": r3(m.get("accuracy") if m.get("accuracy") is not None else m.get("direction_acc")),
            "ece": r3(m.get("ece")),
            "auc": r3(m.get("auc")),
        }
    comeback = {}
    for ph, m in (backtest.get("comeback_metrics") or {}).items():
        comeback[ph] = {
            "n": rint(m.get("n")),
            "brier": r3(m.get("brier")),
            "acc": r3(m.get("accuracy") if m.get("accuracy") is not None else m.get("direction_acc")),
            "ece": r3(m.get("ece")),
        }
    holdout = []
    for pb in backtest.get("per_battle") or []:
        row = enrich_battle({
            "battle_id": pb.get("battle_id"),
            "brier": pb.get("brier"),
            "acc": pb.get("acc"),
            "is_comeback": pb.get("is_comeback"),
        }, by_id)
        row["nPoints"] = rint(pb.get("n_points"))
        holdout.append(row)
    holdout.sort(key=lambda x: (x["brier"] if x["brier"] is not None else 0), reverse=True)
    worst = [enrich_battle(w, by_id) for w in (backtest.get("worst_battles") or [])]
    bad = backtest.get("bad_battle")
    bad_row = None
    if bad:
        bad_row = enrich_battle({
            "battle_id": bad.get("battle_id"),
            "brier": bad.get("brier"),
            "acc": bad.get("acc"),
            "is_comeback": (bad.get("swing") or {}).get("comeback"),
        }, by_id)
        bad_row["lateDirAcc"] = r3(bad.get("late_dir_acc"))
        bad_row["goldGuardHits"] = rint(bad.get("gold_guard_hits"))
    live = jload_js(SITE / "assets" / "predict.js", {}) or {}
    return {
        "version": str(backtest.get("version") or "V12"),
        "trainedAt": str(backtest.get("trained_at") or "")[:10],
        "testN": len(backtest.get("holdout_battles") or []),
        "testFrames": rint((hr.get("all") or {}).get("n")),
        "brier": r3((hr.get("all") or {}).get("brier")),
        "ece": r3((hr.get("all") or {}).get("ece") or headline.get("all_ece")),
        "acc": r3((hr.get("all") or {}).get("accuracy") if (hr.get("all") or {}).get("accuracy") is not None
                  else (hr.get("all") or {}).get("direction_acc")),
        "gatesPassed": bool((backtest.get("gates") or {}).get("passed")),
        "headline": {
            "worstAcc": r3(headline.get("worst_acc")),
            "comebackAcc": r3(headline.get("comeback_acc")),
            "badBattleAcc": r3(headline.get("bad_battle_acc")),
        },
        "phases": phases,
        "comeback": comeback,
        "holdout": holdout,
        "worst": worst,
        "badBattle": bad_row,
        "live": {
            "accuracy": live.get("accuracy"),
            "checkpoints": live.get("checkpoints") or [],
            "lastFrame": live.get("lastFrame"),
            "replayVsLive": live.get("replayVsLive"),
        },
    }


def main() -> None:
    battles = load_replay()
    if not battles:
        raise SystemExit("没有可用的回放数据，先运行 build_replay_frames.py")

    # 回放数据里的 p 可能是比赛当时旧模型写的；沙盘统一改用 V12 重放。
    model_mtime = MODEL_PATH.stat().st_mtime if MODEL_PATH.exists() else 0.0
    v12_map = load_replay_cache()
    v12_map.update(load_local_v12_cache(model_mtime))
    v12_map = compute_missing_v12(battles, v12_map)
    battles = apply_v12(battles, v12_map)

    matches = build_matches(battles)
    surface = build_surface(battles)
    calibration = build_calibration()
    model = build_model(battles)

    # 默认展示：有摆动、但不是一帧翻转，且 V12 与同状态历史不要差太多。
    default_battle, default_frame = choose_default(battles)

    n_with_p = sum(1 for b in battles for f in b["frames"] if f[1] is not None)
    n_v12_battles = sum(1 for b in battles if b.get("src") == "v12")
    games_index = jload_js(SITE / "assets" / "games" / "index.js", {}) or {}
    history_battles = sum(len(v.get("b") or []) for v in games_index.values()) or 11131
    replay_share = len(battles) / max(history_battles, 1)
    data = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "defaultBattle": default_battle,
        "defaultFrame": default_frame,
        "coverage": {
            "replayBattles": len(battles),
            "replayMatches": len(matches),
            "replayFrames": n_with_p,
            "v12Battles": n_v12_battles,
            "v12Frames": n_with_p,
            "historyBattles": history_battles,
            "replayShare": round(replay_share, 4),
        },
        "model": model,
        "surface": surface,
        "calibration": calibration,
        "matches": matches,
        "battles": battles,
        "notes": [
            f"不是每局都能查历史：全部 {history_battles:,} 局里只有 {len(battles)} 局有逐分钟记录（约 {replay_share:.0%}）。所以这里说的是这 {len(battles)} 局，不是全部比赛。",
            "页面上的模型判断都用当前 V12 重新算过；比赛当时旧模型写下的判断没有混进来。",
            "模型只在 20 局没见过的比赛上考过试，而且其中 5 局来自同一场七局四胜的比赛；样本不大，别把 71.8% 当成“每场都能猜对”。",
            "最容易错的是“前 8 分钟落后、最后却翻盘”的局：模型基本会猜反。",
            "直播记录不是考试卷；同一局前后几分钟很像，所以可靠性图只能用来看大致趋势。",
            "历史对比只能说明“以前类似局面怎样”，不能说明“拿到这条龙就一定会赢”。",
        ],
        "techNotes": [
            "Beta(4,4) 平滑 + Wilson 95% 置信区间；样本为 0 的格子不伪造颜色。",
            "同状态检索：分钟 / 金差 / 击杀 / 推塔 / 资源距离加权，取最相近 40 个状态；这是描述性统计，不是因果估计。",
            "V12 test：20 局 / 298 帧；Brier 0.177、ECE 0.183、方向准确率 71.8%。",
            "曲线与地图统一使用 V12 重放：优先复用 replay_cache，未覆盖的局用当前模型补齐；直播旧模型概率不混入。",
            "What-if 用调整后的状态重新做同状态检索，不是 V12 在假设状态上的精确输出。",
        ],
    }
    out = SITE / "assets" / "sandbox.js"
    out.write_text("KPL_SANDBOX = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
                   encoding="utf-8")
    print(f"[ok] {out.name}: {out.stat().st_size / 1024:.0f} KB")
    print(f"     battles={len(battles)} matches={len(matches)} v12_battles={n_v12_battles} "
          f"frames_with_p={n_with_p}")
    print(f"     surface cells={len(surface['cells'])} "
          f"calib_battles={calibration['nBattles']} calib_points={calibration['nPoints']}")
    print(f"     default battle={battles[default_battle]['id']} "
          f"{battles[default_battle]['t1']} vs {battles[default_battle]['t2']}")


if __name__ == "__main__":
    main()
