# -*- coding: utf-8 -*-
"""教练任期与 BP 指纹数据门禁。

检查 assets/coach_data.js：
  - 教练 / 队-赛季 / 任期 / 排除项数量与 coverage 一致；
  - 任期日期、来源、置信度、队-赛季唯一性；
  - 大场 / 小局 / 完整 BP 三层胜负可复算，BP 指纹与证据行合法；
  - 教练生涯汇总等于各任期之和，排除项不混入；
  - 完整 BP 局去重后不超过教练-战队 BP 样本。

用法：
    python check_coach_data.py              # 有 SEVERE → exit 1
    python check_coach_data.py --warn-only  # 只报告，不阻断

报告：../02-KPL实时胜率预测系统/reports/coach_quality.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

SITE = Path(__file__).resolve().parent
SOURCE = SITE / "assets" / "coach_data.js"
REPORT = SITE.parent / "02-KPL实时胜率预测系统" / "reports" / "coach_quality.json"
CN = timezone(timedelta(hours=8))
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_js(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    m = re.search(r"window\.KPL_COACH_DATA\s*=\s*(\{.*\})\s*;?\s*$", text, re.S)
    if not m:
        raise ValueError("coach_data.js 无法解析")
    return json.loads(m.group(1))


def is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


class Audit:
    def __init__(self) -> None:
        self.errors: list[dict] = []
        self.warnings: list[dict] = []
        self.counts = Counter()

    def severe(self, code: str, detail: str, **extra) -> None:
        self.errors.append({"code": code, "detail": detail, **extra})

    def warn(self, code: str, detail: str, **extra) -> None:
        self.warnings.append({"code": code, "detail": detail, **extra})

    def check(self, cond: bool, code: str, detail: str, **extra) -> None:
        if not cond:
            self.severe(code, detail, **extra)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--warn-only", action="store_true")
    args = ap.parse_args()
    a = Audit()
    data = load_js(SOURCE)
    heroes = data.get("heroes") or []
    H = len(heroes)
    tenures = data.get("tenures") or []
    coaches = data.get("coaches") or []
    exclusions = data.get("exclusions") or []
    coverage = data.get("coverage") or {}
    a.counts.update({"heroes": H, "coaches": len(coaches), "tenures": len(tenures), "exclusions": len(exclusions)})

    a.check(H > 0, "heroes.empty", "heroes 为空")
    a.check(bool(tenures), "tenures.empty", "tenures 为空")
    a.check(bool(coaches), "coaches.empty", "coaches 为空")
    a.check(data.get("sourceMode"), "source.mode", "缺少 sourceMode")
    a.check(coverage.get("teamSeasons") == len({(t.get("team"), t.get("league")) for t in tenures}),
            "coverage.teamSeasons", "coverage.teamSeasons 与去重队-赛季不一致")
    a.check(coverage.get("tenures") == len(tenures), "coverage.tenures", "coverage.tenures 与 tenures 不一致")
    a.check(coverage.get("coaches") == len(coaches), "coverage.coaches", "coverage.coaches 与 coaches 不一致")
    a.check(coverage.get("excludedTeamSeasons") == len(exclusions), "coverage.excluded", "排除数与 exclusions 不一致")
    a.check(coverage.get("bpSamples") == sum(t.get("bp", {}).get("games", 0) for t in tenures),
            "coverage.bpSamples", "BP 样本合计不一致")
    a.check(0 < coverage.get("bpGames", 0) <= coverage.get("bpSamples", 0),
            "coverage.bpGames", "去重 BP 局数异常")
    a.check(coverage.get("start") and coverage.get("end"), "coverage.dates", "缺少覆盖起止")

    coach_by_id = {}
    for c in coaches:
        cid = str(c.get("id") or "")
        a.check(bool(cid), "coach.id", "教练 id 为空")
        a.check(cid not in coach_by_id, "coach.duplicate", f"教练重复：{cid}")
        coach_by_id[cid] = c
        a.check(bool(c.get("name")), "coach.name", f"{cid} 缺少 name")
        for key in ("series", "seriesWins", "games", "gameWins", "bpGames", "bpWins"):
            a.check(is_num(c.get(key)) and c[key] >= 0, "coach.career", f"{cid}.{key} 非法")
        a.check(0 <= c.get("seriesWins", 0) <= c.get("series", 0), "coach.seriesWins", f"{cid} 大场胜场越界")
        a.check(0 <= c.get("gameWins", 0) <= c.get("games", 0), "coach.gameWins", f"{cid} 小局胜场越界")
        a.check(0 <= c.get("bpWins", 0) <= c.get("bpGames", 0), "coach.bpWins", f"{cid} BP 胜场越界")
        a.check(isinstance(c.get("tenures"), list) and c["tenures"], "coach.tenures", f"{cid} 没有任期")
        a.check(isinstance(c.get("teams"), list) and c["teams"], "coach.teams", f"{cid} 没有战队")

    for c in coaches:
        for r in c.get("similar") or []:
            a.check(r.get("id") in coach_by_id, "coach.similarId", f"{c['id']} 相似教练缺失：{r.get('id')}")
            a.check(is_num(r.get("similarity")) and 0 <= r["similarity"] <= 100, "coach.similarity", f"{c['id']} 相似度越界")

    tenure_by_id = {}
    team_seasons = {}
    for t in tenures:
        tid = str(t.get("id") or "")
        a.check(bool(tid), "tenure.id", " tenure id 为空")
        a.check(tid not in tenure_by_id, "tenure.duplicate", f"任期重复：{tid}")
        tenure_by_id[tid] = t
        key = (t.get("team"), t.get("league"))
        team_seasons.setdefault(key, []).append((t.get("validFrom"), t.get("validTo"), tid))
        cid = str(t.get("coachId") or "")
        a.check(cid in coach_by_id, "tenure.coach", f"{tid} 教练不在索引：{cid}")
        a.check(t.get("coach") == (coach_by_id.get(cid) or {}).get("name"), "tenure.coachName", f"{tid} 教练名不一致")
        a.check(is_num(t.get("validFrom")) or DATE_RE.match(str(t.get("validFrom"))), "tenure.from", f"{tid} 起始日期非法")
        a.check(is_num(t.get("validTo")) or DATE_RE.match(str(t.get("validTo"))), "tenure.to", f"{tid} 结束日期非法")
        if DATE_RE.match(str(t.get("validFrom"))) and DATE_RE.match(str(t.get("validTo"))):
            a.check(t["validFrom"] <= t["validTo"], "tenure.order", f"{tid} 任期起止倒置")
        src = str(t.get("sourceUrl") or "")
        a.check(src.startswith("https://"), "tenure.source", f"{tid} 缺少可追溯来源")
        a.check(bool(t.get("verifiedAt")), "tenure.verified", f"{tid} 缺少 verifiedAt")
        a.check(t.get("confidence") in ("high", "medium", "low"), "tenure.confidence", f"{tid} 置信度非法")
        for layer in ("series", "games", "bp"):
            st = t.get(layer) or {}
            a.check(is_num(st.get("games")) and st.get("games") >= 0, "tenure.layerGames", f"{tid}.{layer}.games 非法")
            a.check(is_num(st.get("wins")) and 0 <= st.get("wins", -1) <= st.get("games", 0), "tenure.layerWins", f"{tid}.{layer}.wins 越界")
            if st.get("games"):
                a.check(st.get("wr") is not None and 0 <= st["wr"] <= 100, "tenure.layerWr", f"{tid}.{layer}.wr 越界")
        b = t.get("bp") or {}
        a.check(b.get("picks") == b.get("games", 0) * 5, "bp.picks", f"{tid} 选用手位不是 5×局数")
        a.check(b.get("bans") == b.get("games", 0) * 5, "bp.bans", f"{tid} 禁用手位不是 5×局数")
        a.check(b.get("oppBans") == b.get("games", 0) * 5, "bp.oppBans", f"{tid} 对手禁用不是 5×局数")
        a.check(b.get("uniquePicks", 0) <= b.get("picks", 0), "bp.uniquePicks", f"{tid} 选用英雄数超过手位")
        a.check(b.get("uniqueBans", 0) <= b.get("bans", 0), "bp.uniqueBans", f"{tid} 禁用英雄数超过手位")
        a.check(b.get("effectiveHeroes") is None or (is_num(b.get("effectiveHeroes")) and b["effectiveHeroes"] >= 1),
                "bp.effective", f"{tid} 有效英雄数异常")
        a.check(b.get("topShare") is None or (is_num(b.get("topShare")) and 0 <= b["topShare"] <= 100),
                "bp.topShare", f"{tid} 最高占比异常")
        if b.get("topPick") is not None:
            a.check(is_num(b["topPick"]) and 0 <= b["topPick"] < H, "bp.topPick", f"{tid} 最高英雄索引越界")
        for r in b.get("topPicks") or []:
            a.check(0 <= r.get("i", -1) < H, "bp.topPickIndex", f"{tid} topPicks 索引越界")
            a.check(is_num(r.get("p")) and r["p"] > 0 and r["p"] <= b.get("picks", 0), "bp.topPickP", f"{tid} topPicks 次数异常")
            a.check(r.get("win") is None or 0 <= r["win"] <= 100, "bp.topPickWin", f"{tid} topPicks 胜率异常")
            a.check(r.get("lift") is None or r["lift"] >= 0, "bp.topPickLift", f"{tid} topPicks Lift 异常")
        for key in ("topBans", "topAgainst"):
            for r in b.get(key) or []:
                a.check(0 <= r.get("i", -1) < H, f"bp.{key}Index", f"{tid} {key} 索引越界")
                a.check(is_num(r.get("n")) and r["n"] > 0, f"bp.{key}N", f"{tid} {key} 次数异常")
                a.check(r.get("rate") is None or 0 <= r["rate"] <= 100, f"bp.{key}Rate", f"{tid} {key} 比例异常")
        for r in b.get("combos") or []:
            a.check(0 <= r.get("a", -1) < H and 0 <= r.get("b", -1) < H, "bp.comboIndex", f"{tid} 组合索引越界")
            a.check(r.get("a") != r.get("b"), "bp.comboSame", f"{tid} 组合英雄相同")
            a.check(is_num(r.get("n")) and r["n"] > 0, "bp.comboN", f"{tid} 组合次数异常")
            a.check(r.get("win") is None or 0 <= r["win"] <= 100, "bp.comboWin", f"{tid} 组合胜率异常")
        ev = t.get("evidence") or []
        a.check(len(ev) <= 30, "evidence.count", f"{tid} 证据超过 30")
        for r in ev:
            if not isinstance(r, list) or len(r) != 10:
                a.severe("evidence.shape", f"{tid} 证据字段数异常")
                continue
            date, match_id, stage, opp, side, win, picks, bans, opp_picks, opp_bans = r
            a.check(bool(DATE_RE.match(str(date))), "evidence.date", f"{tid} 证据日期非法：{date}")
            a.check(bool(match_id), "evidence.match", f"{tid} 证据缺比赛")
            a.check(side in (1, 2), "evidence.side", f"{tid} 证据阵营非法")
            a.check(win in (0, 1), "evidence.win", f"{tid} 证据赛果非法")
            for key, arr in (("picks", picks), ("bans", bans), ("oppPicks", opp_picks), ("oppBans", opp_bans)):
                a.check(isinstance(arr, list) and len(arr) == 5, f"evidence.{key}", f"{tid} 证据 {key} 不是 5")
                a.check(all(is_num(i) and 0 <= i < H for i in (arr if isinstance(arr, list) else [])),
                        f"evidence.{key}Index", f"{tid} 证据 {key} 索引越界")
            if isinstance(picks, list) and isinstance(bans, list) and isinstance(opp_picks, list) and isinstance(opp_bans, list):
                a.check(len(set(picks + bans + opp_picks + opp_bans)) == 20, "evidence.unique", f"{tid} 证据 20 手不唯一")

    for c in coaches:
        rows = [tenure_by_id[tid] for tid in c.get("tenures", []) if tid in tenure_by_id]
        a.check(len(rows) == len(c.get("tenures", [])), "coach.tenureRefs", f"{c['id']} 任期引用缺失")
        for key, layer in (("series", "series"), ("seriesWins", "series"), ("games", "games"), ("gameWins", "games"), ("bpGames", "bp"), ("bpWins", "bp")):
            total = sum((r.get(layer) or {}).get("games" if key in ("series", "games", "bpGames") else "wins", 0) for r in rows) if key in ("series", "games", "bpGames") else sum((r.get(layer) or {}).get("wins", 0) for r in rows)
            a.check(total == c.get(key, 0), "coach.sum", f"{c['id']}.{key} {c.get(key)} != {total}")
        a.check(sorted(set(r.get("team") for r in rows)) == sorted(set(c.get("teams") or [])), "coach.teams", f"{c['id']} 战队列表不一致")

    for key, spans in team_seasons.items():
        spans = sorted(spans)
        for (s1, e1, id1), (s2, e2, id2) in zip(spans, spans[1:]):
            # 并列主教练（同起始日期、同队同赛季）允许重叠。
            if e1 and s2 and e1 >= s2 and s1 != s2:
                a.warn("tenure.overlap", f"{key} 任期区间重叠：{id1} / {id2}")

    for r in exclusions:
        a.check(bool(r.get("team")) and bool(r.get("league")), "exclusion.id", "排除项缺少队/赛事")
        a.check(bool(r.get("reason")), "exclusion.reason", f"排除项 {r.get('team')} 缺少原因")

    report = {
        "generatedAt": datetime.now(CN).strftime("%Y-%m-%d %H:%M:%S"),
        "source": str(SOURCE),
        "counts": dict(a.counts),
        "coverage": coverage,
        "severe": a.errors,
        "warnings": a.warnings,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"coaches {len(coaches)} | tenures {len(tenures)} | excluded {len(exclusions)} | heroes {H}", flush=True)
    print(f"coverage {coverage}", flush=True)
    print(f"SEVERE {len(a.errors)} | WARN {len(a.warnings)}", flush=True)
    for row in a.errors[:8]:
        print(f"  SEVERE [{row['code']}] {row['detail']}", flush=True)
    for row in a.warnings[:8]:
        print(f"  WARN   [{row['code']}] {row['detail']}", flush=True)
    print(f"report: {REPORT}", flush=True)
    if a.errors and not args.warn_only:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
