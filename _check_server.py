# -*- coding: utf-8 -*-
"""本地工作台 server.py 验收：起真实进程，打真实接口。

用法：
    python _check_server.py
    python _check_server.py http://127.0.0.1:8123   # 服务已在跑时直接验收
"""
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8199
BASE = None
bad = 0


def check(name, ok, extra=""):
    global bad
    if not ok:
        bad += 1
    print(("PASS " if ok else "FAIL ") + name + (("  → " + str(extra)) if extra != "" else ""))


def get(path, method="GET", body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def jget(path, method="GET", body=None):
    code, raw = get(path, method, body)
    try:
        return code, json.loads(raw)
    except Exception:
        return code, {"raw": raw.decode("utf-8", "ignore")}


def main():
    global BASE
    proc = None
    if len(sys.argv) > 1:
        BASE = sys.argv[1].rstrip("/")
    else:
        BASE = "http://127.0.0.1:%d" % PORT
        proc = subprocess.Popen([sys.executable, os.path.join(HERE, "server.py"),
                                 "--port", str(PORT), "--no-browser"],
                                cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        up = False
        for _ in range(240):
            time.sleep(0.5)
            try:
                code, d = jget("/api/health")
                if d.get("ok") and d.get("ready"):
                    up = True
                    break
            except Exception:
                pass
        if not up:
            print("FAIL 服务未在 60s 内就绪")
            proc.kill()
            sys.exit(1)

    try:
        code, st = jget("/api/status")
        check("/api/status 可用", code == 200 and st.get("ok") is not False)
        check("状态含版本与数据库大小（本地工作台）", st.get("version") == "V6.10.0" and "本地工作台" in (st.get("service") or "") and st.get("dbMB", 0) > 0,
              "%s / %sMB" % (st.get("version"), st.get("dbMB")))
        c = st.get("counts", {})
        check("全量数据已入库（schedule ≥ 1000 / battles ≥ 5000 / players ≥ 25000）",
              c.get("schedule", 0) >= 3400 and c.get("battles", 0) >= 5000 and c.get("battle_players", 0) >= 25000,
              json.dumps({k: c.get(k) for k in ("schedule", "battles", "battle_players", "frames", "coaches")}))
        check("数据范围从 2019 开始", (st.get("dateRange") or ["x"])[0].startswith("2016"), st.get("dateRange"))
        check("分钟归档已入库（pts_live ≥ 3500 行）", c.get("pts_live", 0) >= 3500, "pts_live=" + str(c.get("pts_live")))
        check("逐分钟承伤已入库（minute_players ≥ 40000 行）", c.get("minute_players", 0) >= 40000,
              "minute_players=" + str(c.get("minute_players")))
        code, q = jget("/api/query", "POST",
                       {"sql": "SELECT COUNT(*) AS n FROM minute_players WHERE tank > 0"})
        check("承伤数值真实存在", code == 200 and q.get("ok") and q["rows"][0][0] > 30000, q.get("rows"))
        code, sch = jget("/api/schema")
        names = {t["name"]: t["type"] for t in sch.get("tables", [])}
        check("视图就位（v_player_game / v_team_season / v_player_season / v_hero_pick）",
              all(names.get(v) == "view" for v in ("v_player_game", "v_team_season", "v_player_season", "v_hero_pick")),
              sorted(k for k in names if k.startswith("v_")))
        code, q = jget("/api/query", "POST", {"sql": "SELECT COUNT(*) AS n FROM v_player_season"})
        check("视图可查询", code == 200 and q.get("ok") and q["rows"][0][0] > 100, q.get("rows"))
        code, lv = jget("/api/live")
        check("/api/live 实时快照", code == 200 and lv.get("ok") and isinstance(lv.get("battles"), list),
              "battles=" + str(len(lv.get("battles") or [])))

        code, q = jget("/api/query", "POST", {"sql": "SELECT COUNT(*) AS n FROM battle_players"})
        check("SQL 控制台可查询", code == 200 and q.get("ok") and q["rows"][0][0] == c.get("battle_players"),
              q.get("rowCount"))
        code, q = jget("/api/query", "POST",
                       {"sql": "SELECT name, COUNT(*) n FROM battle_players GROUP BY name ORDER BY n DESC LIMIT 3"})
        check("聚合查询可用", code == 200 and q.get("ok") and len(q.get("rows") or []) == 3,
              q.get("rows"))

        code, q = jget("/api/query", "POST", {"sql": "DELETE FROM battles"})
        check("写入被拒绝（只读护栏）", code == 400 and not q.get("ok"), q.get("error"))
        code, q = jget("/api/query", "POST", {"sql": "PRAGMA table_info(battles)"})
        check("PRAGMA 被拒绝", code == 400 and not q.get("ok"), q.get("error"))
        code, q = jget("/api/query", "POST", {"sql": "SELECT 1; DROP TABLE battles"})
        check("多语句被拒绝", code == 400 and not q.get("ok"), q.get("error"))
        code, q = jget("/api/query", "POST", {"sql": "SELECT * FROM battles"})
        check("battle 表仍然完好", code == 200 and q.get("ok"), "")

        code, s = jget("/api/search?q=%E9%87%8D%E5%BA%86")  # "重庆"
        kinds = {r["kind"] for r in s.get("results", [])}
        check("全局搜索命中战队", code == 200 and "战队" in kinds, list(kinds))

        code, b = jget("/api/battle/not-exists-xyz")
        check("未知对局返回空对象", code == 200 and b.get("battle") is None, "")

        code, raw = get("/")
        check("静态站首页由 server 提供", code == 200 and "KPL赛研" in raw.decode("utf-8", "ignore"))
        check("HTML 注入本地徽标", b"local-badge.js" in raw)
        code, raw = get("/query.html?m=sql")
        qhtml = raw.decode("utf-8", "ignore")
        check("SQL 控制台已并入数据查询页", code == 200 and "sqlPanel" in qhtml and "python server.py" in qhtml)
        code, raw = get("/api/status")
        check("API JSON 正常返回", code == 200)
    finally:
        if proc:
            proc.kill()

    print("=== %s ===" % ("全部通过" if bad == 0 else "%d 项失败" % bad))
    sys.exit(0 if bad == 0 else 1)


if __name__ == "__main__":
    main()
