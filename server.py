#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""峡谷有数 · 本地工作台

一条命令把整个数据台跑在自己电脑上：
    python server.py
  → 首次启动自动把 assets 里的全量数据导入 SQLite（只读查询用）
  → 常驻进程提供 /api 查询接口；「数据查询」页新增 SQL 页签
  → 静态站原样可用，浏览器打开即完整体验

零第三方依赖：只用 Python 标准库（3.9+）。
"""
import argparse
import json
import os
import re
import sqlite3
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(ROOT, ".cache")
DB_PATH = os.path.join(CACHE_DIR, "kpldata.db")
ASSETS = os.path.join(ROOT, "assets")

# ---------------------------------------------------------------------------
# 数据导入：assets/*.js 是 "NAME = {json};" 形态，取第一个 = 之后的 JSON 即可
# ---------------------------------------------------------------------------

def load_js_json(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    i = text.find("=")
    if i < 0:
        raise ValueError("no assignment in " + path)
    body = text[i + 1:].strip()
    if body.endswith(";"):
        body = body[:-1].rstrip()
    return json.loads(body)


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


SCHEMA = """
CREATE TABLE schedule (
  matchId TEXT PRIMARY KEY, leagueId TEXT, leagueName TEXT, year INTEGER,
  stage TEXT, date TEXT, time TEXT, team1 TEXT, team2 TEXT,
  score1 INTEGER, score2 INTEGER, bo INTEGER, st INTEGER
);
CREATE TABLE battles (
  battleId TEXT PRIMARY KEY, matchId TEXT, leagueId TEXT, seq INTEGER,
  dur REAL, win INTEGER, t1 TEXT, t2 TEXT, k1 INTEGER, k2 INTEGER,
  g1 INTEGER, g2 INTEGER
);
CREATE TABLE battle_players (
  battleId TEXT, camp INTEGER, name TEXT, hero TEXT,
  k INTEGER, d INTEGER, a INTEGER, gold INTEGER,
  dmgShare REAL, tankShare REAL, mvp INTEGER
);
CREATE TABLE pts_live (
  battleId TEXT, m REAL, winProb REAL,
  gold1 INTEGER, gold2 INTEGER, kill1 INTEGER, kill2 INTEGER,
  tower1 INTEGER, tower2 INTEGER, lord1 INTEGER, lord2 INTEGER,
  dark1 INTEGER, dark2 INTEGER
);
CREATE TABLE frames (
  battleId TEXT, matchId TEXT, m REAL, winProb REAL, goldDiff INTEGER,
  kill1 INTEGER, kill2 INTEGER, tower1 INTEGER, tower2 INTEGER
);
CREATE TABLE battle_events (
  battleId TEXT, m REAL, label TEXT, type TEXT
);
CREATE TABLE coaches (
  coach TEXT, team TEXT, leagueId TEXT, seasonName TEXT,
  role TEXT, validFrom TEXT, validTo TEXT, sourceType TEXT, note TEXT
);
CREATE TABLE coach_stats (
  coach TEXT PRIMARY KEY, series INTEGER, seriesWins INTEGER,
  games INTEGER, gameWins INTEGER, bpGames INTEGER, bpWins INTEGER
);
CREATE INDEX idx_battles_match ON battles(matchId);
CREATE INDEX idx_players_battle ON battle_players(battleId);
CREATE INDEX idx_players_name ON battle_players(name);
CREATE INDEX idx_players_hero ON battle_players(hero);
CREATE INDEX idx_pts_battle ON pts_live(battleId);
CREATE INDEX idx_frames_battle ON frames(battleId);
CREATE INDEX idx_events_battle ON battle_events(battleId);
CREATE INDEX idx_schedule_date ON schedule(date);
CREATE UNIQUE INDEX idx_pts_bm ON pts_live(battleId, m);
CREATE TABLE live_battles (
  battleId TEXT PRIMARY KEY, matchId TEXT, date TEXT, seq INTEGER,
  t1 TEXT, t2 TEXT, win INTEGER, score1 INTEGER, score2 INTEGER,
  namesJson TEXT, updated TEXT
);

-- 视图：把常问口径固化，SQL 页签示例直接引用
CREATE VIEW v_player_game AS
SELECT b.battleId, b.matchId, s.date, s.leagueName, s.year,
       p.camp, p.name, p.hero, p.k, p.d, p.a, p.gold,
       p.dmgShare, p.tankShare, p.mvp,
       b.win, b.t1, b.t2
FROM battle_players p
JOIN battles b ON b.battleId = p.battleId
LEFT JOIN schedule s ON s.matchId = b.matchId;

CREATE VIEW v_team_season AS
SELECT year, leagueName, team1 AS team, COUNT(*) AS matches,
       SUM(CASE WHEN score1 > score2 THEN 1 ELSE 0 END) AS wins,
       SUM(CASE WHEN score1 < score2 THEN 1 ELSE 0 END) AS losses,
       SUM(score1) AS scoreFor, SUM(score2) AS scoreAgainst
FROM schedule WHERE score1 IS NOT NULL GROUP BY year, leagueName, team1
UNION ALL
SELECT year, leagueName, team2 AS team, COUNT(*) AS matches,
       SUM(CASE WHEN score2 > score1 THEN 1 ELSE 0 END) AS wins,
       SUM(CASE WHEN score2 < score1 THEN 1 ELSE 0 END) AS losses,
       SUM(score2) AS scoreFor, SUM(score1) AS scoreAgainst
FROM schedule WHERE score2 IS NOT NULL GROUP BY year, leagueName, team2;

CREATE VIEW v_player_season AS
SELECT name, year, COUNT(*) AS games,
       SUM(k) AS kills, SUM(d) AS deaths, SUM(a) AS assists,
       SUM(mvp) AS mvp,
       ROUND(AVG(dmgShare), 1) AS dmgShareAvg,
       ROUND(AVG(tankShare), 1) AS tankShareAvg,
       ROUND(SUM(CASE WHEN (camp = 1 AND win = 1) OR (camp = 2 AND win = 2) THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS winRate
FROM v_player_game GROUP BY name, year;

CREATE VIEW v_hero_pick AS
SELECT p.hero, s.year, COUNT(*) AS picks,
       SUM(CASE WHEN (p.camp = 1 AND b.win = 1) OR (p.camp = 2 AND b.win = 2) THEN 1 ELSE 0 END) AS wins
FROM battle_players p
JOIN battles b ON b.battleId = p.battleId
LEFT JOIN schedule s ON s.matchId = b.matchId
GROUP BY p.hero, s.year;
"""


def build_db(log=print):
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = DB_PATH + ".building"
    if os.path.exists(tmp):
        os.remove(tmp)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    t0 = time.time()

    # 赛程（2019–2026 全量）
    sched = load_js_json(os.path.join(ASSETS, "schedule_all.js"))
    con.executemany(
        "INSERT OR REPLACE INTO schedule VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r.get("matchId"), r.get("leagueId"), r.get("leagueName"), r.get("year"),
          r.get("stage"), r.get("date"), r.get("time"), r.get("team1"), r.get("team2"),
          r.get("score1"), r.get("score2"), r.get("bo"), r.get("st")) for r in sched])
    log("  schedule: %d rows" % len(sched))

    # 逐局 + 选手（assets/games/2019xxxx.json …）
    n_b, n_p = 0, 0
    gdir = os.path.join(ASSETS, "games")
    for fn in sorted(os.listdir(gdir)):
        if not fn.endswith(".json"):
            continue
        lg = fn[:-5]
        games = load_json(os.path.join(gdir, fn))
        for bid, b in games.items():
            con.execute("INSERT OR REPLACE INTO battles VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (bid, b.get("match"), lg, b.get("seq"), b.get("dur"), b.get("win"),
                         b.get("t1"), b.get("t2"), b.get("k1"), b.get("k2"), b.get("g1"), b.get("g2")))
            n_b += 1
            for p in (b.get("players") or []):
                con.execute("INSERT INTO battle_players VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (bid, p.get("c"), p.get("n"), p.get("h"), p.get("k"), p.get("d"),
                             p.get("a"), p.get("g"), p.get("dmg"), p.get("bh"), p.get("mvp")))
                n_p += 1
    log("  battles: %d rows, players: %d rows" % (n_b, n_p))

    # 直播分钟序列（live.js 的 matches + history）+ 历史归档分片（live_hist/，247 局 3,535 行）
    n_pts = 0
    try:
        live = load_js_json(os.path.join(ASSETS, "live.js"))
        entries = list((live.get("matches") or [])) + list((live.get("history") or []))
    except Exception as e:
        log("  live.js skipped: %s" % e)
        entries = []
    hdir = os.path.join(ASSETS, "live_hist")
    if os.path.isdir(hdir):
        for fn in sorted(os.listdir(hdir)):
            if not fn.endswith(".js"):
                continue
            try:
                entries.extend(load_js_json(os.path.join(hdir, fn)))
            except Exception:
                pass
    for m in entries:
        rows = m.get("pts") or []
        if rows:
            con.execute("INSERT OR REPLACE INTO live_battles VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (m.get("battleId"), m.get("matchId"), m.get("date"), m.get("seq"),
                         m.get("t1"), m.get("t2"), m.get("win"), m.get("score1"), m.get("score2"),
                         json.dumps(m.get("names") or [], ensure_ascii=False), m.get("updated")))
            for r in rows:
                con.execute("INSERT OR IGNORE INTO pts_live VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (m.get("battleId"), r[0], r[1], r[2], r[3], r[4], r[5],
                             r[6], r[7], r[8], r[9], r[10], r[11]))
                n_pts += 1
    log("  pts_live: %d rows (含归档 %d 局)" % (n_pts, len(entries)))

    # 复盘包逐帧 + 事件（assets/replay/<matchId>.json）
    n_f, n_e = 0, 0
    rdir = os.path.join(ASSETS, "replay")
    for fn in sorted(os.listdir(rdir)):
        if not (fn.endswith(".json") and re.match(r"^\d{10}\.json$", fn)):
            continue
        mid = fn[:-5]
        for b in (load_json(os.path.join(rdir, fn)).get("battles") or []):
            for f in (b.get("frames") or []):
                k = f.get("k") or [0, 0]
                t = f.get("t") or [0, 0]
                con.execute("INSERT INTO frames VALUES (?,?,?,?,?,?,?,?,?)",
                            (b.get("battleId"), mid, f.get("m"), f.get("p"), f.get("gd"),
                             k[0], k[1], t[0], t[1]))
                n_f += 1
            for e in (b.get("events") or []):
                con.execute("INSERT INTO battle_events VALUES (?,?,?,?)",
                            (b.get("battleId"), e.get("m"), e.get("l"), e.get("t")))
                n_e += 1
    log("  frames: %d rows, events: %d rows" % (n_f, n_e))

    # 教练任期与生涯统计（coach_data.js）
    coach = load_js_json(os.path.join(ASSETS, "coach_data.js"))
    tenures = []
    for t in (coach.get("tenures") or []):
        tenures.append((t.get("coach"), t.get("team"), t.get("league"), t.get("seasonName"),
                        t.get("role"), t.get("validFrom"), t.get("validTo"),
                        t.get("sourceType"), t.get("note")))
    con.executemany("INSERT INTO coaches VALUES (?,?,?,?,?,?,?,?,?)", tenures)
    stats = []
    for c in (coach.get("coaches") or []):
        stats.append((c.get("name"), c.get("series"), c.get("seriesWins"), c.get("games"),
                      c.get("gameWins"), c.get("bpGames"), c.get("bpWins")))
    con.executemany("INSERT OR REPLACE INTO coach_stats VALUES (?,?,?,?,?,?,?)", stats)
    log("  coaches: %d tenures, %d coaches" % (len(tenures), len(stats)))

    con.commit()
    con.execute("VACUUM")
    con.close()
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    os.rename(tmp, DB_PATH)
    log("  done in %.1fs → %s (%.1f MB)" % (time.time() - t0, DB_PATH, os.path.getsize(DB_PATH) / 1048576))


def db_is_stale():
    if not os.path.exists(DB_PATH):
        return True
    dbmt = os.path.getmtime(DB_PATH)
    for root, _dirs, files in os.walk(ASSETS):
        for fn in files:
            try:
                if os.path.getmtime(os.path.join(root, fn)) > dbmt:
                    return True
            except OSError:
                pass
    return False


def ro_connect():
    con = sqlite3.connect("file:%s?mode=ro" % DB_PATH.replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row
    return con


def table_counts():
    con = ro_connect()
    out = {}
    for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        out[name] = con.execute("SELECT COUNT(*) FROM \"%s\"" % name).fetchone()[0]
    con.close()
    return out


# ---------------------------------------------------------------------------
# /api/query 安全护栏：只读连接 + 单语句 + 关键字黑名单 + 步数超时 + 行数截断
# ---------------------------------------------------------------------------

DENY_RE = re.compile(
    r"\b(pragma|attach|detach|insert|update|delete|drop|create|alter|vacuum|reindex|begin|commit|rollback|replace\s+into)\b",
    re.IGNORECASE)
MAX_ROWS = 2000
QUERY_TIMEOUT = 6.0


def run_query(sql):
    sql = (sql or "").strip()
    while sql.endswith(";"):
        sql = sql[:-1].rstrip()
    if not sql:
        raise ValueError("SQL 为空")
    if not re.match(r"^(select|with)\b", sql, re.IGNORECASE):
        raise ValueError("只允许 SELECT / WITH 查询")
    if DENY_RE.search(sql):
        raise ValueError("检测到禁用的关键字（只读查询）")
    con = ro_connect()
    deadline = time.time() + QUERY_TIMEOUT

    def guard():
        return 1 if time.time() > deadline else 0

    con.set_progress_handler(guard, 20000)
    try:
        t0 = time.time()
        cur = con.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(MAX_ROWS + 1)
        truncated = len(rows) > MAX_ROWS
        rows = rows[:MAX_ROWS]
        return {"columns": cols, "rows": [list(r) for r in rows],
                "rowCount": len(rows), "truncated": truncated,
                "ms": round((time.time() - t0) * 1000)}
    finally:
        con.close()


# ---------------------------------------------------------------------------
# HTTP：静态站 + /api + HTML 注入本地徽标
# ---------------------------------------------------------------------------

MIME = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
        ".svg": "image/svg+xml", ".ico": "image/x-icon", ".webp": "image/webp",
        ".woff": "font/woff", ".woff2": "font/woff2", ".mp4": "video/mp4", ".txt": "text/plain; charset=utf-8"}

BADGE_TAG = '<script src="/local-badge.js"></script>'.encode("utf-8")

# 服务状态：建库在后台线程跑，静态站先起来，API 就绪前返回 503
STATE = {"ready": False, "building": False}
LIVE_LOCK = threading.Lock()
LIVE_STATE = {"updatedAt": None, "health": None, "battles": []}


def refresh_live_state():
    """读 assets/live.js 到内存：比赛日 02 管线更新 live.js 后，这里 15s 内感知。"""
    try:
        live = load_js_json(os.path.join(ASSETS, "live.js"))
        ms = list(live.get("matches") or [])
        hs = list(live.get("history") or [])
        battles = [{
            "battleId": m.get("battleId"), "matchId": m.get("matchId"), "seq": m.get("seq"),
            "t1": m.get("t1"), "t2": m.get("t2"), "minute": m.get("minute"),
            "st": (m.get("pts") or []) and 1 or 0,
        } for m in ms + hs]
        with LIVE_LOCK:
            LIVE_STATE.clear()
            LIVE_STATE.update({
                "updatedAt": live.get("updatedAt"),
                "health": live.get("health"),
                "battles": battles,
            })
        return True
    except Exception:
        return False


def live_sync_loop():
    refresh_live_state()
    last_src = None
    while True:
        try:
            src = os.path.getmtime(os.path.join(ASSETS, "live.js"))
            if last_src is not None and src != last_src:
                refresh_live_state()
            last_src = src
        except OSError:
            pass
        time.sleep(15)


class Handler(BaseHTTPRequestHandler):
    server_version = "KPLDataLocal/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # 安静模式，进度走启动横幅

    # -- 基础 --
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _static(self, upath):
        path = unquote(urlparse(upath).path)
        if path in ("/", ""):
            path = "/index.html"
        fs = os.path.normpath(os.path.join(ROOT, path.lstrip("/")))
        if not fs.startswith(ROOT) or not os.path.isfile(fs):
            p404 = os.path.join(ROOT, "404.html")
            if os.path.isfile(p404):
                with open(p404, "rb") as f:
                    self._send(404, f.read(), "text/html; charset=utf-8")
            else:
                self._send(404, b"404", "text/plain")
            return
        ext = os.path.splitext(fs)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        with open(fs, "rb") as f:
            body = f.read()
        # HTML 注入本地徽标：托管静态站上该脚本自动静默，不影响线上
        if ext == ".html" and b"</body>" in body:
            body = body.replace(b"</body>", BADGE_TAG + b"</body>", 1)
        self._send(200, body, ctype)

    # -- 路由 --
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        try:
            if p == "/api/health":
                return self._json({"ok": True, "service": "kpldata-local",
                                   "ready": STATE["ready"], "building": STATE["building"]})
            if p == "/api/live/stream":
                return self.api_live_stream()
            if p == "/api/live":
                with LIVE_LOCK:
                    return self._json({"ok": True, **LIVE_STATE})
            if not STATE["ready"]:
                return self._json({"ok": False, "building": True,
                                   "error": "数据库构建中，静态页可正常浏览；查询 API 数秒后就绪"}, 503)
            if p == "/api/status":
                return self._json(self.api_status())
            if p == "/api/schema":
                return self._json(self.api_schema())
            if p == "/api/query":
                q = parse_qs(u.query)
                try:
                    return self._json({"ok": True, **run_query((q.get("sql") or [""])[0])})
                except Exception as e:
                    return self._json({"ok": False, "error": str(e)}, 400)
            if p == "/api/search":
                q = parse_qs(u.query)
                return self._json({"ok": True, **self.api_search((q.get("q") or [""])[0])})
            if p.startswith("/api/battle/"):
                return self._json({"ok": True, **self.api_battle(p.rsplit("/", 1)[1])})
            return self._static(p)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 500)

    def do_POST(self):
        if urlparse(self.path).path != "/api/query":
            return self._json({"ok": False, "error": "not found"}, 404)
        if not STATE["ready"]:
            return self._json({"ok": False, "building": True, "error": "数据库构建中，请稍候"}, 503)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n) or b"{}")
            return self._json({"ok": True, **run_query(payload.get("sql") or "")})
        except Exception as e:
            return self._json({"ok": False, "error": str(e)}, 400)

    def api_live_stream(self):
        """SSE：每 5 秒推一次实时快照摘要，断连自动结束。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            for _ in range(720):  # 最长 1 小时，断连即止
                with LIVE_LOCK:
                    payload = json.dumps(LIVE_STATE, ensure_ascii=False)
                self.wfile.write(b"data: " + payload.encode("utf-8") + b"\n\n")
                self.wfile.flush()
                time.sleep(5)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    # -- API 实现 --
    def api_status(self):
        counts = table_counts() if STATE["ready"] else {}
        rng = [None, None]
        if STATE["ready"]:
            con = ro_connect()
            rng = con.execute("SELECT MIN(date), MAX(date) FROM schedule").fetchone()
            con.close()
        site = {}
        try:
            site = load_js_json(os.path.join(ASSETS, "data.js"))
        except Exception:
            pass
        return {
            "service": "峡谷有数 · 本地工作台",
            "version": "V6.9.0",
            "ready": STATE["ready"],
            "db": os.path.basename(DB_PATH),
            "dbMB": round(os.path.getsize(DB_PATH) / 1048576, 1) if os.path.exists(DB_PATH) else 0,
            "builtAt": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(DB_PATH))) if os.path.exists(DB_PATH) else None,
            "dateRange": [rng[0], rng[1]],
            "counts": counts,
            "siteStats": (site.get("stats") or {}),
        }

    def api_schema(self):
        con = ro_connect()
        tables = []
        for (name, typ, sql) in con.execute(
                "SELECT name, type, sql FROM sqlite_master WHERE type IN ('table','view') ORDER BY type, name"):
            cols = [r[1] for r in con.execute("PRAGMA table_info(\"%s\")" % name)]
            n = con.execute("SELECT COUNT(*) FROM \"%s\"" % name).fetchone()[0]
            tables.append({"name": name, "type": typ, "columns": cols, "rows": n, "ddl": sql})
        con.close()
        return {"tables": tables}

    def api_search(self, kw):
        kw = (kw or "").strip()
        if not kw:
            return {"results": []}
        like = "%" + kw + "%"
        con = ro_connect()
        out = []
        for (name, n) in con.execute(
                "SELECT name, COUNT(*) n FROM battle_players WHERE name LIKE ? GROUP BY name ORDER BY n DESC LIMIT 8", (like,)):
            out.append({"kind": "选手", "name": name, "detail": "%d 局出场" % n})
        for (name, n) in con.execute(
                "SELECT hero, COUNT(*) n FROM battle_players WHERE hero LIKE ? GROUP BY hero ORDER BY n DESC LIMIT 8", (like,)):
            out.append({"kind": "英雄", "name": name, "detail": "%d 局选用" % n})
        seen = set()
        for col in ("team1", "team2"):
            for (name,) in con.execute(
                    "SELECT DISTINCT %s FROM schedule WHERE %s LIKE ? LIMIT 6" % (col, col), (like,)):
                if name not in seen:
                    seen.add(name)
                    out.append({"kind": "战队", "name": name, "detail": ""})
        for (name,) in con.execute(
                "SELECT DISTINCT coach FROM coaches WHERE coach LIKE ? LIMIT 6", (like,)):
            out.append({"kind": "教练", "name": name, "detail": ""})
        con.close()
        return {"results": out[:30]}

    def api_battle(self, bid):
        con = ro_connect()
        b = con.execute("SELECT * FROM battles WHERE battleId=?", (bid,)).fetchone()
        if not b:
            con.close()
            return {"battle": None}
        players = [dict(r) for r in con.execute(
            "SELECT * FROM battle_players WHERE battleId=? ORDER BY camp, rowid", (bid,))]
        pts = con.execute("SELECT COUNT(*) FROM pts_live WHERE battleId=?", (bid,)).fetchone()[0]
        fr = con.execute("SELECT COUNT(*) FROM frames WHERE battleId=?", (bid,)).fetchone()[0]
        evs = [dict(r) for r in con.execute(
            "SELECT m, label, type FROM battle_events WHERE battleId=? ORDER BY m", (bid,))]
        con.close()
        return {"battle": dict(b), "players": players,
                "minuteRows": pts, "frameRows": fr, "events": evs}


# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="峡谷有数 · 本地工作台")
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true", help="启动后不自动打开浏览器")
    ap.add_argument("--rebuild", action="store_true", help="强制重建本地数据库")
    args = ap.parse_args()

    print("=" * 56)
    print("  峡谷有数 · 本地工作台 (V6.9.0)")
    print("=" * 56)

    def warmup():
        STATE["building"] = True
        try:
            if args.rebuild or db_is_stale():
                why = "--rebuild" if args.rebuild else "数据比缓存新"
                print("[%s] 后台建立本地数据库（约 10-30 秒，期间站点可浏览）…" % why)
                build_db()
                print("[done] 数据库就绪，查询 API 已可用")
            else:
                print("[cache] 本地数据库已是最新: %s" % DB_PATH)
            STATE["ready"] = True
        except Exception as e:
            print("[error] 建库失败:", e)
        finally:
            STATE["building"] = False

    threading.Thread(target=warmup, daemon=True).start()
    threading.Thread(target=live_sync_loop, daemon=True).start()

    url = "http://%s:%d" % (args.host, args.port)
    print()
    print("  站点首页      %s/" % url)
    print("  SQL 控制台    %s/query.html?m=sql" % url)
    print("  数据接口      %s/api/status" % url)
    print("  实时推送(SSE) %s/api/live/stream" % url)
    print()
    print("  Ctrl+C 停止。数据只读：所有查询跑在本地 SQLite 上。")
    print("  比赛日实时：跑 02 项目监视器采集，本服务每 15s 感知 live.js 更新。")
    print("-" * 56)

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url + "/query.html?m=sql")).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
