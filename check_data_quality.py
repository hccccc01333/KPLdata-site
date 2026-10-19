"""数据发布质量门槛（V5 · 全站 UI 与数据可信度专项）

在「生成资产之后、部署之前」运行：把同一类数据缺陷拦在发布前，而不是等用户在某张卡片上
看到一个假的 0。任何一条 SEVERE 规则触发都会以退出码 1 结束（阻断发布），并写出异常报告。

用法：
    python check_data_quality.py            # 检查 + 写报告；有严重问题 → exit 1
    python check_data_quality.py --warn-only  # 只看报告，不阻断（排查用）

检查对象：assets/seasons.js / players_detail.js / honors.js（发布给前端的真实资产）
报告位置：../02-KPL实时胜率预测系统/reports/data_quality_report.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
PROJ = SITE.parent / "02-KPL实时胜率预测系统"
ASSETS = SITE / "assets"
REPORT_DIR = PROJ / "reports"
CN_TZ = timezone(timedelta(hours=8))

# 荣誉榜选手条目必须齐备的指标字段（页面会逐个渲染成数值）
HONOR_PLAYER_FIELDS = ("name", "team", "g", "m", "wr", "kda", "gpm", "dpm", "bhpm", "part", "mvp", "score")
HONOR_TEAM_FIELDS = ("team", "g", "m", "gw", "gl", "wr", "oppAdj", "stab", "score")

# 「输出占比 / 参团率」本应为正；大面积恰为 0 说明字段缺失后被当成了 0
ZERO_METRICS = ("dmg", "part")
ZERO_SEVERE_RATIO = 1.0     # 该范围全部选手都是 0 → 口径整体失效
ZERO_WARN_RATIO = 0.5       # 过半为 0 → 需要人工复核
ZERO_MIN_SAMPLE = 8         # 样本太少不做比例判断


def load_asset(fname: str, var: str):
    """读取 `VAR = {...};` 形式的资产文件并解析为 JSON。"""
    p = ASSETS / fname
    if not p.exists():
        return None
    txt = p.read_text(encoding="utf-8")
    for pre in (f"window.{var} =", f"window.{var}=", f"{var} =", f"{var}="):
        if txt.lstrip().startswith(pre):
            txt = txt.lstrip()[len(pre):]
            break
    txt = txt.strip()
    if txt.endswith(";"):
        txt = txt[:-1]
    return json.loads(txt)


class Report:
    def __init__(self):
        self.issues: list[dict] = []
        self.counts = Counter()

    def add(self, severity: str, rule: str, detail: str, sample=None):
        self.issues.append({"severity": severity, "rule": rule, "detail": detail,
                            "sample": sample or []})
        self.counts[severity] += 1

    def severe(self, rule, detail, sample=None):
        self.add("SEVERE", rule, detail, sample)

    def warn(self, rule, detail, sample=None):
        self.add("WARN", rule, detail, sample)


def check_missing_as_zero(rep: Report, seasons: dict, players: dict, honors: dict):
    """规则 1：指标缺失 / 不应为 0 的指标大面积恰为 0。"""
    for sid, sc in (seasons or {}).get("scopes", {}).items():
        ps = sc.get("players") or []
        if len(ps) < ZERO_MIN_SAMPLE:
            continue
        for metric in ZERO_METRICS:
            nulls = [p for p in ps if p.get(metric) is None]
            if nulls:
                rep.severe("缺失值被当作 0 / 显示为数值",
                           f"范围 {sid} 有 {len(nulls)}/{len(ps)} 名选手的「{metric}」字段缺失",
                           [p.get("name") for p in nulls[:8]])
                continue
            zeros = [p for p in ps if p.get(metric) == 0]
            if not zeros:
                continue
            ratio = len(zeros) / len(ps)
            if ratio >= ZERO_SEVERE_RATIO:
                rep.severe("指标全零（口径失效）",
                           f"范围 {sid} 的 {len(ps)} 名选手「{metric}」全部恰好为 0",
                           [p.get("name") for p in zeros[:8]])
            elif ratio > ZERO_WARN_RATIO:
                rep.warn("指标异常偏零",
                         f"范围 {sid} 有 {len(zeros)}/{len(ps)} 名选手「{metric}」恰好为 0",
                         [p.get("name") for p in zeros[:8]])

    # 明细选手：有胜率却没有有效局数
    for name, pl in (players or {}).items():
        if pl.get("wr") is not None and not (pl.get("games") or 0):
            rep.severe("无有效局数却显示胜率",
                       f"选手 {name} 的 games={pl.get('games')}，却带有 wr={pl.get('wr')}")


def check_honor_fields(rep: Report, honors: dict):
    """规则 2：荣誉榜条目字段缺失（页面会把缺失渲染成 0.0 / 0）。"""
    if not honors:
        return
    for kind in ("weeks", "months"):
        for period in honors.get(kind) or []:
            pid = period.get("id")
            for ln, res in (period.get("lanes") or {}).items():
                board = (res or {}).get("board") or []
                for i, c in enumerate(board):
                    miss = [f for f in HONOR_PLAYER_FIELDS if c.get(f) is None]
                    if miss:
                        rep.severe("荣誉榜候选字段缺失",
                                   f"{kind} {pid} {ln} 第 {i + 1} 名「{c.get('name')}」缺字段 {miss}")
                    if not (c.get("g") or 0):
                        rep.severe("荣誉榜无有效局数却上榜",
                                   f"{kind} {pid} {ln}「{c.get('name')}」g={c.get('g')}")
                    if i == 0 and res.get("boot") and c.get("t1") is None:
                        rep.warn("榜首缺少稳定性估计", f"{kind} {pid} {ln} boot=true 但无 t1 / ci")
            team = period.get("team") or {}
            for i, t in enumerate(team.get("board") or []):
                miss = [f for f in HONOR_TEAM_FIELDS if t.get(f) is None]
                if miss:
                    rep.severe("荣誉榜战队候选字段缺失",
                               f"{kind} {pid} 战队第 {i + 1} 名「{t.get('team')}」缺字段 {miss}")
                if not (t.get("g") or 0):
                    rep.severe("荣誉榜战队无有效局数却上榜",
                               f"{kind} {pid}「{t.get('team')}」g={t.get('g')}")


def check_cross_page(rep: Report, seasons: dict, players: dict):
    """规则 3：同一选手、同一口径（全部赛事）在两个页面应得到同一数值。"""
    allsc = ((seasons or {}).get("scopes") or {}).get("all") or {}
    if not allsc.get("players") or not players:
        return
    compared = 0
    for p in allsc["players"]:
        q = players.get(p.get("name"))
        if not q:
            continue
        compared += 1
        for key, tol in (("games", 0), ("kda", 0.02), ("wr", 0.002), ("part", 0.2), ("dmg", 0.2)):
            a, b = p.get(key), q.get(key)
            if a is None or b is None:
                continue
            if abs(a - b) > tol:
                rep.severe("跨页面同口径数值不一致",
                           f"选手 {p.get('name')} 的「{key}」：seasons={a} / player_detail={b}")
    rep.counts["cross_page_compared"] = compared


def main() -> int:
    warn_only = "--warn-only" in sys.argv
    rep = Report()

    seasons = load_asset("seasons.js", "KPL_SEASONS")
    players = load_asset("players_detail.js", "KPL_PLAYERS")
    honors = load_asset("honors.js", "KPL_HONORS")

    for nm, obj in (("seasons.js", seasons), ("players_detail.js", players), ("honors.js", honors)):
        if obj is None:
            rep.severe("资产缺失或不可解析", f"{nm} 不存在 / 无法解析为 JSON")

    check_missing_as_zero(rep, seasons, players, honors)
    check_honor_fields(rep, honors)
    check_cross_page(rep, seasons, players)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "generatedAt": datetime.now(CN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "assets": {k: (ASSETS / k).stat().st_size for k in ("seasons.js", "players_detail.js", "honors.js")
                   if (ASSETS / k).exists()},
        "summary": {"SEVERE": rep.counts["SEVERE"], "WARN": rep.counts["WARN"],
                    "crossPageCompared": rep.counts["cross_page_compared"]},
        "issues": rep.issues,
    }
    (REPORT_DIR / "data_quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"数据质量检查：SEVERE {rep.counts['SEVERE']} · WARN {rep.counts['WARN']} · "
          f"跨页面比对 {rep.counts['cross_page_compared']} 人")
    for it in rep.issues:
        print(f"  [{it['severity']}] {it['rule']} —— {it['detail']}")
    print(f"报告：{REPORT_DIR / 'data_quality_report.json'}")

    if rep.counts["SEVERE"] and not warn_only:
        print("[!] 存在严重规则触发，已阻断发布。修复后重跑。")
        return 1
    print("[OK] 未触发阻断规则。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
