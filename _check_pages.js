// 用 Edge headless + CDP 在真实浏览器里核对三个页面的渲染结果
const { spawn } = require("child_process");
const fs = require("fs");

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9334;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function connect() {
  for (let i = 0; i < 60; i++) {
    await sleep(250);
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (page) return page;
    } catch (e) {}
  }
  return null;
}

async function main() {
  const proc = spawn(EDGE, [
    "--headless=new", "--disable-gpu", "--no-sandbox",
    `--remote-debugging-port=${PORT}`,
    "--user-data-dir=" + process.cwd() + "\\.edge-tmp2",
    "about:blank",
  ], { stdio: "ignore" });

  const target = await connect();
  if (!target) { console.log("FAIL 无法连接 CDP"); proc.kill(); process.exit(1); }

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0;
  const pending = new Map();
  const errors = [];
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.method === "Runtime.exceptionThrown") {
      const d = m.params.exceptionDetails;
      const desc = (d.exception && d.exception.description) || d.text || "";
      errors.push(desc.split("\n")[0] + " @line " + (d.lineNumber + 1) + " " + (d.url || "").split("/").pop());
    }
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  const send = (method, params) => new Promise((res) => {
    const myId = ++id; pending.set(myId, res);
    ws.send(JSON.stringify({ id: myId, method, params }));
  });
  const evaluate = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result && r.result.exceptionDetails) return { __err: r.result.exceptionDetails.text };
    return r.result && r.result.result ? r.result.result.value : undefined;
  };

  async function goto(url, readyExpr) {
    await send("Page.enable");
    await send("Runtime.enable");
    await send("Page.navigate", { url });
    for (let i = 0; i < 60; i++) {
      await sleep(250);
      if (await evaluate(readyExpr)) return true;
    }
    return false;
  }

  let bad = 0;
  const check = (name, ok, extra) => {
    if (!ok) bad++;
    console.log((ok ? "PASS " : "FAIL ") + name + (extra !== undefined ? "  → " + extra : ""));
  };

  const BASE = "http://127.0.0.1:8777/";

  // --- 首页：复盘覆盖数从索引现算 ---
  const okIdx = await goto(BASE + "index.html",
    "(function(){var s=document.getElementById('slides');return !!(window.KPL_REPLAY_INDEX && s && s.innerHTML.length>0);})()");
  check("首页加载出轮播", okIdx);
  const idx = await evaluate(`(function(){
    var idx = window.KPL_REPLAY_INDEX || {};
    var keys = Object.keys(idx);
    var b = keys.reduce(function(s,k){return s + ((idx[k].b||[]).length);}, 0);
    var txt = (document.querySelector('.carousel') || {}).textContent || '';
    var sl = document.getElementById('slides');
    return { matches: keys.length, battles: b, has59: txt.indexOf('59 场') >= 0,
             has202: txt.indexOf('202 局') >= 0, has14: txt.indexOf('14 场') >= 0,
             slidesLen: sl ? sl.innerHTML.length : -1,
             slidesText: sl ? sl.textContent.slice(0, 160) : '' };
  })()`);
  check("索引里 59 场 / 202 局", idx.matches === 59 && idx.battles === 202, idx.matches + "/" + idx.battles);
  check("轮播文案用上了真实数字", idx.has59 && idx.has202, JSON.stringify(idx).slice(0, 220));
  if (errors.length) console.log("  首页 JS 异常：" + errors.slice(0, 3).join(" || "));

  // 首页其它区块：一个 null 就能打断整个内联脚本，所以每块都验一遍
  const blocks = await evaluate(`(function(){
    var q = function(s){ return document.querySelectorAll(s).length; };
    return { replay: q('#replayPicks .rp-pick'), standings: q('#stTop tr'),
             heroes: q('#heroTop > *'), players: q('#plTop > *'),
             upcoming: q('#upcomingList > *'), recent: q('#recentList > *') };
  })()`);
  check("精选复盘卡片已渲染", blocks.replay > 0, blocks.replay);
  check("战队榜已渲染", blocks.standings > 0, blocks.standings);
  check("热门英雄已渲染", blocks.heroes > 0, blocks.heroes);
  check("选手榜已渲染", blocks.players > 0, blocks.players);
  check("即将开赛已渲染", blocks.upcoming > 0, blocks.upcoming);
  check("最新结果已渲染", blocks.recent > 0, blocks.recent);
  check("轮播不再出现「14 场」", !idx.has14);

  // --- 赛程：状态筛选三态 ---
  const okSch = await goto(BASE + "schedule.html", "!!document.getElementById('fStatus')");
  check("赛程页加载", okSch);
  const sch = await evaluate(`(function(){
    var sel = document.getElementById('fStatus');
    var opts = Array.prototype.map.call(sel.options, function(o){ return o.textContent.trim(); });
    return { opts: opts };
  })()`);
  check("状态筛选含「进行中」", (sch.opts || []).indexOf("进行中") >= 0, (sch.opts || []).join(" / "));
  check("状态筛选三态齐全", ["进行中", "未开始", "已结束"].every(function (x) { return (sch.opts || []).indexOf(x) >= 0; }));

  // --- 查询：战队行直接进详情页 ---
  const okQ = await goto(BASE + "query.html", "!!document.querySelector('#qBody a.cell')");
  check("查询页加载出结果", okQ);
  const q = await evaluate(`(function(){
    var a = document.querySelector('#qBody a.cell');
    return a ? a.getAttribute('href') : '';
  })()`);
  check("战队行链接指向 team.html?id=", /^team\.html\?id=/.test(q || ""), q);

  ws.close();
  proc.kill();
  await sleep(300);
  try { fs.rmSync(process.cwd() + "\\.edge-tmp2", { recursive: true, force: true }); } catch (e) {}
  process.exit(bad ? 1 : 0);
}

main().catch((e) => { console.log("FAIL 运行异常:", e.message); process.exit(1); });
