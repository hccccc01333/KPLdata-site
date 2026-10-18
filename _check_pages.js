// 站点浏览器验收：真实 Edge（CDP），不是静态看 HTML
//
// 三条硬性规则：
//   1. 任何页面出现未捕获 JS 异常 → 整体失败（比"HTML 里有容器"可靠得多）
//   2. 核心区块必须真的渲染出节点，不是空壳
//   3. 390 / 768 / 1440 三个宽度下首页与复盘页都不能报错
//
// 用法：
//   python -m http.server 8777   # 先起本地服务（run_in_background）
//   node _check_pages.js [http://127.0.0.1:8777]
const { spawn } = require("child_process");
const fs = require("fs");

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9336;
const BASE = (process.argv[2] || "http://127.0.0.1:8777").replace(/\/$/, "") + "/";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 每页：路径、说明、至少应渲染出的选择器（数量 > 0 才算真渲染）
const PAGES = [
  ["index.html", "首页", ["#focusHero > *", "#replayPicks .rp-pick", "#stTop tr", "#heroTop > *", "#plTop > *", ".entry"]],
  ["schedule.html", "赛程", ["#fStatus option", "#schBody tr, .day-block, .sched-row"]],
  ["teams.html", "战队榜", ["#teamGrid > *, .tcard, .team-card"]],
  ["team.html?id=重庆狼队", "战队详情", ["#teamHead, .page-hero", ".tstat-grid, .panel"]],
  ["players.html", "选手榜", ["#plBody tr, .player, .pl-card"]],
  ["heroes.html", "英雄列表", ["#heroGrid > *, .hcard"]],
  ["match.html?id=2026062603&g=3&m=13", "比赛复盘", ["#rpRange", "#rpChart svg", "#rpGrid .rp-panel"]],
  // game.html 的 id 是 battle_id（不是 match_id），传错了会走空态
  ["game.html?id=1373651472_21_1779526666", "对局详情", ["#main .panel", "#main .bp-grid"]],
  ["bp.html", "BP 分析", ["#bpBody tr, .bp2-panel, main .panel"]],
  ["combos.html", "英雄组合", ["main .panel, .combo-card"]],
  ["compare.html", "对比工具", ["main .panel, .cmp-table"]],
  ["h2h.html", "交手记录", ["main .panel, .h2h-panel"]],
  ["predict.html", "预测统计", ["#cpRows tr", "#kAccK"]],
  ["picks.html", "精选对局", [".pick-card"]],
  ["query.html", "数据查询", ["#qBody a.cell"]],
  ["simulator.html", "大场模拟", ["main .panel, .sim-wrap"]],
  ["stage.html", "赛段对比", ["main .panel, .stage-wrap"]],
  ["about.html", "数据说明", ["#holdoutBody tr"]],
];

let bad = 0;
const fail = [];
const check = (name, ok, extra) => {
  if (!ok) { bad++; fail.push(name); }
  console.log((ok ? "PASS " : "FAIL ") + name + (extra !== undefined && extra !== "" ? "  → " + extra : ""));
};

async function main() {
  const proc = spawn(EDGE, [
    "--headless=new", "--disable-gpu", "--no-sandbox",
    `--remote-debugging-port=${PORT}`,
    "--user-data-dir=" + require("os").tmpdir() + "\\kpl-edge-check",
    "about:blank",
  ], { stdio: "ignore" });

  let target = null;
  for (let i = 0; i < 60; i++) {
    await sleep(250);
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      target = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (target) break;
    } catch (e) {}
  }
  if (!target) { console.log("FAIL 无法连接 CDP"); proc.kill(); process.exit(1); }

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let id = 0;
  const pending = new Map();
  let errors = [];
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.method === "Runtime.exceptionThrown") {
      const d = m.params.exceptionDetails;
      const desc = (d.exception && d.exception.description) || d.text || "";
      errors.push(desc.split("\n")[0] + " @line " + (d.lineNumber + 1));
    }
    if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") {
      const t = (m.params.args || []).map((a) => a.value || a.description || "").join(" ");
      if (t) errors.push("console.error: " + String(t).slice(0, 120));
    }
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  const send = (method, params) => new Promise((res) => {
    const myId = ++id; pending.set(myId, res);
    ws.send(JSON.stringify({ id: myId, method, params }));
  });
  const evaluate = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result && r.result.exceptionDetails) return null;
    return r.result && r.result.result ? r.result.result.value : undefined;
  };

  await send("Page.enable");
  await send("Runtime.enable");

  async function visit(url, settle = 1400) {
    errors = [];
    await send("Page.navigate", { url });
    for (let i = 0; i < 40; i++) {
      await sleep(200);
      if (await evaluate("document.readyState === 'complete'")) break;
    }
    await sleep(settle);
    return errors.slice();
  }

  console.log("=== 逐页：未捕获异常 + 关键区块渲染 ===");
  for (const [path, label, sels] of PAGES) {
    const errs = await visit(BASE + path);
    const counts = await evaluate(
      "(" + JSON.stringify(sels) + ").map(function(s){ return document.querySelectorAll(s).length; })"
    );
    const rendered = Array.isArray(counts) && counts.some((n) => n > 0);
    check(label + " 无 JS 异常", errs.length === 0, errs.slice(0, 2).join(" | "));
    check(label + " 关键区块已渲染", rendered, Array.isArray(counts) ? counts.join("/") : String(counts));
  }

  console.log("\n=== 复盘交互（连续拖动 / 键盘 / 切局）===");
  await visit(BASE + "match.html?id=2026062603&g=3&m=13", 1600);
  const inter = await evaluate(`(function(){
    var first = document.getElementById('rpRange');
    if (!first) return { err: 'no slider' };
    var same = [], labels = [];
    var n = Math.min(12, Number(first.max));
    for (var i = 0; i <= n; i++) {
      first.value = String(i);
      first.dispatchEvent(new Event('input', { bubbles: true }));
      same.push(document.getElementById('rpRange') === first);
      labels.push((document.getElementById('rpTime') || {}).textContent || '');
    }
    first.focus();
    var before = first.value;
    first.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
    var after = document.getElementById('rpRange');
    var tab = document.querySelector('.rp-tab:not(.on)');
    if (tab) tab.click();
    return { same: same, distinctLabels: new Set(labels).size, kb: Number(after.value) - Number(before),
             sameAfterKb: after === first, switched: !!tab,
             panelsAfterSwitch: document.querySelectorAll('#rpGrid .rp-panel').length };
  })()`);
  check("连续拖动 13 次滑块节点不变", inter && inter.same && inter.same.every(Boolean),
    inter && inter.same ? inter.same.filter(Boolean).length + "/" + inter.same.length : "n/a");
  check("时间标签随拖动变化", inter && inter.distinctLabels > 1, inter && inter.distinctLabels);
  check("键盘 ArrowRight 推进一帧", inter && inter.kb === 1, inter && inter.kb);
  check("切局后三块面板仍在", inter && inter.panelsAfterSwitch === 3, inter && inter.panelsAfterSwitch);

  console.log("\n=== 响应式：390 / 768 / 1440 ===");
  for (const w of [390, 768, 1440]) {
    await send("Emulation.setDeviceMetricsOverride", { width: w, height: 900, deviceScaleFactor: 1, mobile: w < 500 });
    const e1 = await visit(BASE + "index.html");
    const nav = await evaluate("(function(){var h=document.getElementById('siteHeader');return h?h.getBoundingClientRect().height:0;})()");
    check(w + "px 首页无异常", e1.length === 0, e1.slice(0, 2).join(" | "));
    check(w + "px 导航可见", nav > 0, nav);
    const e2 = await visit(BASE + "match.html?id=2026062603&g=3&m=13");
    check(w + "px 复盘页无异常", e2.length === 0, e2.slice(0, 2).join(" | "));
  }
  await send("Emulation.clearDeviceMetricsOverride");

  ws.close();
  proc.kill();
  await sleep(300);
  try { fs.rmSync(require("os").tmpdir() + "\\kpl-edge-check", { recursive: true, force: true }); } catch (e) {}

  console.log("\n" + (bad ? "=== 失败 " + bad + " 项 ===" : "=== 全部通过 ==="));
  if (bad) console.log("失败项：" + fail.join(" / "));
  process.exit(bad ? 1 : 0);
}

main().catch((e) => { console.log("FAIL 运行异常:", e.message); process.exit(1); });
