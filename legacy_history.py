# -*- coding: utf-8 -*-
"""2016–2018 外部历史补充集：构建时合并进 seasons.js / schedule_all.js。

数据来自 data/legacy_h2016.json（由主项目 tools/export_legacy_history.py 从
wanplus / scoregg 补充集生成；仓库自带该文件，构建不依赖主项目）。

被 build_history_data.py 在写出资产前调用；也可单独运行以修复被旧构建覆盖的资产：
    python legacy_history.py

口径：legacy 赛事无逐局 BP；scoregg 2017–2018 无选手经济 / 伤害；相关页面按缺失展示。
"""
import json
from pathlib import Path

SITE = Path(__file__).resolve().parent
PAYLOAD = SITE / "data" / "legacy_h2016.json"


def load_payload():
    if not PAYLOAD.is_file():
        return None
    try:
        return json.loads(PAYLOAD.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover
        print(f"[legacy] payload 读取失败: {e}")
        return None


def merge(seasons: dict, schedule_all: list) -> "tuple[dict, list]":
    """把 legacy 并入 seasons dict 与 schedule 行列表；无 payload 时原样返回。"""
    payload = load_payload()
    if not payload:
        print("[legacy] 未找到 data/legacy_h2016.json，跳过 2016–2018 合并")
        return seasons, schedule_all

    legacy_ids = {r["matchId"] for r in payload.get("schedule") or []}
    schedule_all = [r for r in schedule_all if str(r.get("matchId")) not in legacy_ids]
    schedule_all.extend(payload.get("schedule") or [])
    schedule_all.sort(key=lambda r: (r.get("date") or "", str(r.get("matchId"))))

    years = set(seasons.get("years") or []) | {int(y) for y in payload.get("scopes", {}) if str(y).isdigit() and len(str(y)) == 4}
    seasons["years"] = sorted(years)

    league_ids = {l["id"] for l in payload.get("leagues") or []}
    leagues = [l for l in (seasons.get("leagues") or []) if str(l.get("id")) not in league_ids]
    leagues.extend(payload.get("leagues") or [])
    leagues.sort(key=lambda l: (int(str(l.get("year") or 0)), str(l.get("id"))))
    seasons["leagues"] = leagues

    scopes = seasons.get("scopes") or {}
    for key, sc in (payload.get("scopes") or {}).items():
        scopes[key] = sc
    seasons["scopes"] = scopes

    print(f"[legacy] 合并完成: 赛事 {len(payload.get('leagues') or [])} | "
          f"大场 {len(payload.get('schedule') or [])} | schedule 共 {len(schedule_all)} 行")
    return seasons, schedule_all


if __name__ == "__main__":
    ASSETS = SITE / "assets"

    def load_js(path: Path, var: str):
        text = path.read_text(encoding="utf-8")
        i = text.find("=")
        return text[: i + 1], json.loads(text[i + 1:].strip().rstrip(";").rstrip())

    p1, seasons = load_js(ASSETS / "seasons.js", "KPL_SEASONS")
    p2, schedule = load_js(ASSETS / "schedule_all.js", "KPL_SCHEDULE_ALL")
    seasons, schedule = merge(seasons, schedule)
    (ASSETS / "seasons.js").write_text(p1 + json.dumps(seasons, ensure_ascii=False, separators=(",", ":")) + ";", encoding="utf-8")
    (ASSETS / "schedule_all.js").write_text(p2 + json.dumps(schedule, ensure_ascii=False, separators=(",", ":")) + ";", encoding="utf-8")
    print(f"seasons.js / schedule_all.js 已修复（{len(schedule)} 行）")
