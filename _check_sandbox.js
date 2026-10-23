// 胜率沙盘专项浏览器验收：真实 Edge（CDP），检查渲染、交互、响应式。
// 用法：先 python -m http.server 8777，再 node _check_sandbox.js [http://127.0.0.1:8777]
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9338;
const BASE = (process.argv[2] || "http://127.0.0.1:8777").replace(/\/$/, "") + "/";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
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
    "--user-data-dir=" + require("os").tmpdir() + "\\kpl-edge-sandbox",
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
      if (t) errors.push("console.error: " + String(t).slice(0, 140));
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
  async function visit(url, settle = 1800) {
    errors = [];
    await send("Page.navigate", { url });
    for (let i = 0; i < 50; i++) {
      await sleep(200);
      if (await evaluate("document.readyState === 'complete'")) break;
    }
    await sleep(settle);
    const unhandled = await evaluate("window.__kplUnhandled || []");
    return errors.concat(Array.isArray(unhandled) ? unhandled : []);
  }

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Network.setCacheDisabled", { cacheDisabled: true });
  await send("Page.addScriptToEvaluateOnNewDocument", {
    source: `
      window.__kplUnhandled = [];
      window.addEventListener("unhandledrejection", function (e) {
        var r = e.reason;
        window.__kplUnhandled.push("unhandledrejection: " + ((r && r.message) || String(r)));
      });
      window.addEventListener("error", function (e) {
        window.__kplUnhandled.push("window.error: " + (e.message || ""));
      });
    `,
  });

  console.log("=== 胜率沙盘：渲染与交互 ===");
  let errs = await visit(BASE + "sandbox.html");
  check("页面无 JS 异常", errs.length === 0, errs.slice(0, 3).join(" | "));

  const base = await evaluate(`(function(){
    return {
      cells: document.querySelectorAll('#sbSurface svg rect.sb-cell').length,
      stats: document.querySelectorAll('#sbState .sb-stat').length,
      whatif: document.querySelectorAll('#sbWhatIf input[type=range]').length,
      phases: document.querySelectorAll('#sbPhases .sb-phase').length,
      worst: document.querySelectorAll('#sbWorst .sb-worst-row').length,
      analogs: document.querySelectorAll('#sbAnalog .sb-analog-row').length,
      brier: (document.querySelector('#sbKpiBrier')||{}).textContent,
      coverage: (document.querySelector('#sbKpiCoverage')||{}).textContent,
      curve: document.querySelectorAll('#sbCurve svg path').length,
      overflow: document.documentElement.scrollWidth - window.innerWidth
    };
  })()`);
  check("概率地形 77 个网格", base && base.cells === 77, base && base.cells);
  check("状态卡 4 个状态指标", base && base.stats === 4, base && base.stats);
  check("What-if 4 个滑杆", base && base.whatif === 4, base && base.whatif);
  check("模型体检 4 个阶段卡", base && base.phases === 4, base && base.phases);
  check("最差对局表已渲染", base && base.worst >= 5, base && base.worst);
  check("同状态历史样例已渲染", base && base.analogs >= 3, base && base.analogs);
  check("V12 曲线已渲染", base && base.curve >= 1, base && base.curve);
  check("KPI Brier = 0.177", base && base.brier === "0.177", base && base.brier);
  check("KPI 覆盖 = 212 局", base && base.coverage === "212 局", base && base.coverage);
  check("1440px 无横向溢出", base && base.overflow <= 1, base && base.overflow + "px");

  // 模式切换
  const mode = await evaluate(`(function(){
    var btn = document.querySelector('#sbMode button[data-mode="model"]');
    if (!btn) return null;
    btn.click();
    var on = btn.classList.contains('on');
    var cells = document.querySelectorAll('#sbSurface svg rect.sb-cell').length;
    return { on: on, cells: cells, legend: (document.querySelector('#sbLegend')||{}).textContent.slice(0,20) };
  })()`);
  check("切换到 V12 概率模式", mode && mode.on === true && mode.cells === 77, mode && (mode.cells + " 格"));

  // 时间滑杆
  const scrub = await evaluate(`(function(){
    var s = document.querySelector('#sbMinute');
    var before = (document.querySelector('#sbMinuteLabel')||{}).textContent;
    s.value = s.max;
    s.dispatchEvent(new Event('input', {bubbles:true}));
    var after = (document.querySelector('#sbMinuteLabel')||{}).textContent;
    return { before: before, after: after, hist: !!document.querySelector('#sbState .sb-hist'),
             p: (document.querySelector('#sbState .sb-state-top .p')||{}).textContent };
  })()`);
  check("时间滑杆改变当前分钟", scrub && scrub.before !== scrub.after, scrub && (scrub.before + " → " + scrub.after));
  check("拖动后状态卡仍有同状态历史", scrub && scrub.hist === true, scrub && scrub.hist);
  check("拖动后胜率数字存在", scrub && /%/.test(scrub.p || ""), scrub && scrub.p);

  // What-if
  const whatif = await evaluate(`(function(){
    var s = document.querySelector('#wiGd');
    s.value = 2;
    s.dispatchEvent(new Event('input', {bubbles:true}));
    return { lab: (document.querySelector('#wiGdV')||{}).textContent,
             out: (document.querySelector('#wiOut')||{}).textContent,
             chips: document.querySelectorAll('#wiChips .sb-chip').length };
  })()`);
  check("What-if 经济滑杆生效", whatif && /2\s*千|2k/.test(whatif.lab), whatif && whatif.lab);
  check("What-if 输出前后对比", whatif && /→/.test(whatif.out), whatif && whatif.out.slice(0, 60));
  check("What-if 4 个杠杆 chip", whatif && whatif.chips === 4, whatif && whatif.chips);

  // 点击同状态样例
  const jump = await evaluate(`(function(){
    var row = document.querySelector('#sbAnalog .sb-analog-row');
    if (!row) return null;
    var bi = row.getAttribute('data-bi');
    row.click();
    return { bi: bi, sel: (document.querySelector('#sbBattle')||{}).value,
             meta: (document.querySelector('#sbCurveMeta')||{}).textContent };
  })()`);
  check("点击同状态样例可跳转对局", jump && jump.sel === jump.bi, jump && (jump.bi + " / " + jump.sel));
  check("跳转后曲线标题更新", jump && /G\d+/.test(jump.meta || ""), jump && jump.meta);

  // 随机一局
  const random = await evaluate(`(function(){
    var before = (document.querySelector('#sbCurveMeta')||{}).textContent;
    document.querySelector('#sbRandom').click();
    var after = (document.querySelector('#sbCurveMeta')||{}).textContent;
    return { before: before, after: after, cells: document.querySelectorAll('#sbSurface svg rect.sb-cell').length };
  })()`);
  check("随机一局可重绘", random && random.cells === 77, random && random.after);
  check("随机后页面无异常", errors.length === 0, errors.slice(0, 3).join(" | "));

  console.log("\n=== 响应式 390 / 768 / 1440 ===");
  for (const w of [390, 768, 1440]) {
    await send("Emulation.setDeviceMetricsOverride", { width: w, height: 900, deviceScaleFactor: 1, mobile: w < 500 });
    const e = await visit(BASE + "sandbox.html");
    const m = await evaluate(`(function(){
      var de = document.documentElement;
      return { over: de.scrollWidth - window.innerWidth,
               cells: document.querySelectorAll('#sbSurface svg rect.sb-cell').length,
               state: !!document.querySelector('#sbState .sb-hist'),
               whatif: document.querySelectorAll('#sbWhatIf input[type=range]').length,
               header: (document.getElementById('siteHeader')||{}).getBoundingClientRect().height };
    })()`);
    check(w + "px 无 JS 异常", e.length === 0, e.slice(0, 2).join(" | "));
    check(w + "px 无横向溢出", m && m.over <= 1, m && m.over + "px");
    check(w + "px 地形与状态卡可见", m && m.cells === 77 && m.state === true, m && (m.cells + " 格"));
    check(w + "px What-if 滑杆可用", m && m.whatif === 4, m && m.whatif);
    check(w + "px 导航渲染", m && m.header > 0, m && m.header);
    if (w === 390) {
      const ms = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
      if (ms.result && ms.result.data) {
        const out = path.join(__dirname, "assets", "shots", "sandbox_mobile.png");
        fs.writeFileSync(out, Buffer.from(ms.result.data, "base64"));
        console.log("SHOT " + out);
      }
      const mm = await send("Page.getLayoutMetrics");
      const mcs = (mm.result && mm.result.cssContentSize) || { height: 2000 };
      const mf = await send("Page.captureScreenshot", {
        format: "png", captureBeyondViewport: true,
        clip: { x: 0, y: 0, width: 390, height: Math.min(mcs.height, 9000), scale: 1 }
      });
      if (mf.result && mf.result.data) {
        const out = path.join(__dirname, "assets", "shots", "sandbox_mobile_full.png");
        fs.writeFileSync(out, Buffer.from(mf.result.data, "base64"));
        console.log("SHOT " + out + " (" + Math.round(mcs.height) + "px)");
      }
    }
  }

  // 桌面截图（页面较长，截首屏 + 主图区域）
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await visit(BASE + "sandbox.html", 2200);
  const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  if (shot.result && shot.result.data) {
    const out = path.join(__dirname, "assets", "shots", "sandbox.png");
    fs.writeFileSync(out, Buffer.from(shot.result.data, "base64"));
    console.log("SHOT " + out);
  }
  const metrics = await send("Page.getLayoutMetrics");
  const cs = (metrics.result && metrics.result.cssContentSize) || { width: 1440, height: 2000 };
  const full = await send("Page.captureScreenshot", {
    format: "png", captureBeyondViewport: true,
    clip: { x: 0, y: 0, width: 1440, height: Math.min(cs.height, 5200), scale: 1 }
  });
  if (full.result && full.result.data) {
    const out = path.join(__dirname, "assets", "shots", "sandbox_full.png");
    fs.writeFileSync(out, Buffer.from(full.result.data, "base64"));
    console.log("SHOT " + out + " (" + Math.round(cs.height) + "px)");
  }
  await send("Emulation.clearDeviceMetricsOverride");

  console.log("\n=== " + (bad === 0 ? "全部通过" : bad + " 项失败") + " ===");
  if (bad) console.log("失败项：" + fail.join(" | "));
  proc.kill();
  process.exit(bad ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(1); });
