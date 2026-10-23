// 线上部署验收：关键资源可访问 + 无旧缓存造成的脚本/数据版本错配
//
// 为什么单独一个脚本：部署命令退出 0 只代表"上传完成"，不代表线上真的换了版本。
// 这一层只做四件事：
//   1. 关键资源都拿得到（200 + 正确 content-type）
//   2. index.html 里所有 ?v= 是同一个号（混号 = 浏览器拿到一半新一半旧）
//   3. 线上 data.js 的模型口径与仓库一致（V12 / holdoutN=20），且已删除的资源真的 404
//   4. 线上首页结构确实是新版（有 focusHero，没有 dome / slides / todayStrip）
//
// 传输层：先试 Node fetch；拿不到就用 Edge（CDP）在页面里 fetch。
//   本机沙箱的 http_proxy 不放行 workers.dev，Node fetch / curl 一律 502，
//   但 Edge 走系统网络能直连——所以浏览器兜底不是可选优化，是必需。
//
// 用法：
//   node _check_deploy.js                                  // 默认线上域名
//   node _check_deploy.js https://xxx.workers.dev          // 指定环境
//   node _check_deploy.js http://127.0.0.1:8777            // 也可以打本地
const { spawn, spawnSync } = require("child_process");

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9355;
const BASE = (process.argv[2] || "https://kpldata-site.hccccc01333.workers.dev").replace(/\/$/, "");
const TIMEOUT_MS = 25000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let bad = 0;
const fail = [];
const check = (name, ok, extra) => {
  if (!ok) { bad++; fail.push(name); }
  console.log((ok ? "PASS " : "FAIL ") + name + (extra !== undefined && extra !== "" ? "  → " + extra : ""));
};

// ---- 传输层 A：Node fetch（不读 http_proxy）----
async function viaFetch(url, wantBody) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
  try {
    const r = await fetch(url, { redirect: "follow", signal: ctl.signal });
    return { status: r.status, ct: r.headers.get("content-type") || "",
             body: wantBody ? await r.text() : "", via: "node-fetch" };
  } finally { clearTimeout(timer); }
}

// ---- 传输层 B：curl（带代理）----
function viaCurl(url, wantBody) {
  const proxy = process.env.https_proxy || process.env.HTTPS_PROXY ||
                process.env.http_proxy || process.env.HTTP_PROXY || "";
  for (const bin of ["curl", "D:/Git/mingw64/bin/curl.exe", "C:/Windows/System32/curl.exe"]) {
    const args = ["-sS", "-L", "--max-time", String(Math.round(TIMEOUT_MS / 1000)),
                  "-w", "\n__STATUS__%{http_code}|%{content_type}", url];
    if (proxy) args.unshift("-x", proxy);
    const r = spawnSync(bin, args, { encoding: "utf8", maxBuffer: 64 * 1024 * 1024, windowsHide: true });
    if (r.error || r.status === null) continue;
    const out = String(r.stdout || "");
    const m = out.match(/__STATUS__(\d+)\|(.*)$/);
    return { status: m ? Number(m[1]) : (r.status === 0 ? 200 : 0),
             ct: m ? m[2] : "", body: wantBody ? (m ? out.slice(0, m.index) : out) : "",
             via: "curl" + (proxy ? "(proxy)" : "") };
  }
  return null;
}

// ---- 传输层 C：Edge（CDP）在页面上下文里 fetch ----
let _edge = null;
async function edgeSession() {
  if (_edge) return _edge;
  const proc = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-sandbox",
    `--remote-debugging-port=${PORT}`,
    "--user-data-dir=" + require("os").tmpdir() + "\\kpl-edge-deploy", "about:blank"],
    { stdio: "ignore" });
  let target = null;
  for (let i = 0; i < 60; i++) {
    await sleep(250);
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      target = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (target) break;
    } catch (e) {}
  }
  if (!target) { proc.kill(); return null; }
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0; const pending = new Map();
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  const send = (method, params) => new Promise((res) => {
    const myId = ++id; pending.set(myId, res);
    ws.send(JSON.stringify({ id: myId, method, params }));
  });
  await send("Page.enable");
  await send("Runtime.enable");
  // 先落到目标源，页面内 fetch 才是同源，不会被 CORS 挡
  await send("Page.navigate", { url: BASE + "/index.html" });
  for (let i = 0; i < 40; i++) {
    await sleep(250);
    const r = await send("Runtime.evaluate", { expression: "document.readyState", returnByValue: true });
    if (r.result && r.result.result && r.result.result.value === "complete") break;
  }
  _edge = { proc, ws, send };
  return _edge;
}

async function viaEdge(url, wantBody) {
  const s = await edgeSession();
  if (!s) return null;
  const expr = `(async function(){
    try {
      var r = await fetch(${JSON.stringify(url)}, { redirect: "follow" });
      var body = ${wantBody ? "await r.text()" : '""'};
      return { status: r.status, ct: r.headers.get("content-type") || "", body: body };
    } catch (e) { return { status: 0, ct: "", body: "", err: String(e) }; }
  })()`;
  const r = await s.send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
  const v = r.result && r.result.result && r.result.result.value;
  if (!v) return null;
  return { status: v.status, ct: v.ct, body: v.body || "", via: "edge(cdp)", err: v.err };
}

async function get(url, wantBody) {
  try {
    const r = await viaFetch(url, wantBody);
    if (r.status > 0) return r;
  } catch (e) {}
  const c = viaCurl(url, wantBody);
  if (c && c.status > 0) return c;
  const e = await viaEdge(url, wantBody);
  if (e) return e;
  return { status: 0, ct: "", body: "", via: "unreachable" };
}

const CORE_PAGES = [
  "schedule.html",
  "bracket.html",
  "bracket-forecast.html",
  "forecast.html",
  "sandbox.html",
  "predict.html",
];

const KEY_ASSETS = [
  ["index.html", "text/html"],
  ["assets/style.css", "css"],
  ["assets/pages.css", "css"],
  ["assets/data.js", "javascript"],
  ["assets/details.js", "javascript"],
  ["assets/common.js", "javascript"],
  ["assets/replay.js", "javascript"],
  ["assets/replay/index.js", "javascript"],
  ["assets/picks.js", "javascript"],
  ["assets/search.js", "javascript"],
  ["assets/live.js", "javascript"],
];

async function main() {
  console.log("=== 线上部署验收：" + BASE + " ===");
  const first = await get(BASE + "/index.html", true);
  if (first.status === 0) {
    console.log("FAIL 站点不可达（Node fetch / curl / Edge 三种传输层均失败）");
    process.exit(1);
  }
  console.log("（传输层：" + first.via + "）\n");

  console.log("=== 关键资源可访问 ===");
  for (const [path, ctHint] of KEY_ASSETS) {
    const r = await get(BASE + "/" + path, false);
    check(path + " 200", r.status === 200, r.status);
    check(path + " content-type 正确", r.status === 200 && r.ct.toLowerCase().includes(ctHint), r.ct || "(空)");
  }

  console.log("\n=== 核心页面可访问 ===");
  for (const path of CORE_PAGES) {
    const r = await get(BASE + "/" + path, false);
    check(path + " 200", r.status === 200, r.status);
  }

  console.log("\n=== 版本一致性（防新旧缓存混用）===");
  const versions = [...new Set((first.body.match(/\?v=(\d+)/g) || []))];
  check("index.html 资源版本号唯一", versions.length <= 1, versions.join(", ") || "(无 ?v=)");

  console.log("\n=== 线上数据版本与仓库一致 ===");
  const data = await get(BASE + "/assets/data.js", true);
  const mv = (data.body.match(/"version"\s*:\s*"([^"]+)"/) || [])[1];
  const hn = (data.body.match(/"holdoutN"\s*:\s*(\d+)/) || [])[1];
  const gen = (data.body.match(/"generatedAt"\s*:\s*"([^"]+)"/) || [])[1];
  check("线上 data.js 模型版本 = V12", mv === "V12", mv || "(取不到)");
  check("线上 data.js holdout 局数 = 20", hn === "20", hn || "(取不到)");
  check("线上 data.js 生成时间在 3 天内", (() => {
    if (!gen) return false;
    const d = new Date(String(gen).replace(" ", "T"));
    return !isNaN(d.getTime()) && (Date.now() - d.getTime()) < 3 * 86400 * 1000;
  })(), gen || "(取不到)");

  console.log("\n=== 已删除资源不应再被提供 ===");
  for (const p of ["assets/hero3d.js", "assets/vendor/three.module.min.js"]) {
    const r = await get(BASE + "/" + p, false);
    check(p + " 已下线（404）", r.status === 404, r.status);
  }

  console.log("\n=== 首页结构（线上确实是新版）===");
  check("线上首页含赛事焦点容器", first.body.includes("focusHero"));
  check("线上首页已无 #dome 穹顶", !/\bid=["']dome["']/.test(first.body));
  check("线上首页已无 #todayStrip 残留", !/todayStrip/.test(first.body));
  check("线上首页已无轮播容器", !/\bid=["']slides["']/.test(first.body));

  if (_edge) { try { _edge.ws.close(); _edge.proc.kill(); } catch (e) {} }

  console.log("\n" + (bad ? "=== 失败 " + bad + " 项 ===" : "=== 全部通过 ==="));
  if (bad) console.log("失败项：" + fail.join(" / "));
  process.exit(bad ? 1 : 0);
}

main().catch((e) => { console.log("FAIL 运行异常:", e.message); process.exit(1); });
