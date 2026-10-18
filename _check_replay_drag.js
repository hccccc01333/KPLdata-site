// 真实浏览器交互检查：连续拖拽时滑块节点是否保持同一个
// 用 Edge headless + CDP（Node 22 自带 WebSocket），不依赖 jsdom。
// 判据：连续 12 次 input 事件后，document.getElementById('rpRange') 必须始终是同一个节点；
// 旧版每次 input 都重写 el.innerHTML，这个检查会全红。
const { spawn } = require("child_process");
const fs = require("fs");

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9333;
const URL = process.argv[2] || "http://127.0.0.1:8777/match.html?id=2026062603&g=3&m=13";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  const proc = spawn(EDGE, [
    "--headless=new", "--disable-gpu", "--no-sandbox",
    `--remote-debugging-port=${PORT}`,
    "--user-data-dir=" + process.cwd() + "\\.edge-tmp",
    URL,
  ], { stdio: "ignore" });

  let targets = null;
  for (let i = 0; i < 40; i++) {
    await sleep(250);
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await r.json();
      const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (page) { targets = page; break; }
    } catch (e) { /* 还没起来 */ }
  }
  if (!targets) { console.log("FAIL 无法连接 CDP"); proc.kill(); process.exit(1); }

  const ws = new WebSocket(targets.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let id = 0;
  const pending = new Map();
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  };
  const send = (method, params) => new Promise((res) => {
    const myId = ++id;
    pending.set(myId, res);
    ws.send(JSON.stringify({ id: myId, method, params }));
  });

  const evaluate = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result && r.result.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails));
    return r.result && r.result.result ? r.result.result.value : undefined;
  };

  // 等工作台渲染出来
  let ready = false;
  for (let i = 0; i < 40; i++) {
    ready = await evaluate("!!document.getElementById('rpRange')");
    if (ready) break;
    await sleep(250);
  }

  let bad = 0;
  const check = (name, ok, extra) => {
    if (!ok) bad++;
    console.log((ok ? "PASS " : "FAIL ") + name + (extra !== undefined ? "  → " + extra : ""));
  };
  check("工作台渲染出滑块", ready);

  if (ready) {
    const res = await evaluate(`(function(){
      var first = document.getElementById('rpRange');
      var same = [], labels = [], max = Number(first.max);
      var n = Math.min(12, max);
      for (var i = 0; i <= n; i++) {
        first.value = String(i);
        first.dispatchEvent(new Event('input', { bubbles: true }));
        same.push(document.getElementById('rpRange') === first);
        var t = document.getElementById('rpTime');
        labels.push(t ? t.textContent.trim() : '');
      }
      return {
        same: same,
        labels: labels,
        panels: document.querySelectorAll('#rpGrid .rp-panel').length,
        chartHasSvg: !!document.querySelector('#rpChart svg'),
        evOn: document.querySelectorAll('.rp-ev.on').length,
        sliderCount: document.querySelectorAll('#rpRange').length
      };
    })()`);

    check("12 次 input 后滑块仍是同一个节点", res.same.every(Boolean),
      res.same.filter(Boolean).length + "/" + res.same.length);
    check("页面里始终只有一个滑块", res.sliderCount === 1, res.sliderCount);
    check("时间标签随拖动变化", new Set(res.labels).size > 1,
      res.labels.slice(0, 4).join(" | "));
    check("三块面板仍在", res.panels === 3, res.panels);
    check("图表 SVG 仍在", res.chartHasSvg);
    check("事件高亮有且仅有若干个", res.evOn >= 1, res.evOn);

    // 键盘：ArrowRight 应推进一帧且不丢焦点
    const kb = await evaluate(`(function(){
      var r = document.getElementById('rpRange');
      r.focus();
      var before = r.value;
      r.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
      var after = document.getElementById('rpRange');
      return { before: before, after: after.value, sameNode: after === r, focused: document.activeElement === after };
    })()`);
    check("ArrowRight 推进一帧", Number(kb.after) === Number(kb.before) + 1, kb.before + " → " + kb.after);
    check("键盘后仍是同一节点且保持焦点", kb.sameNode && kb.focused);
  }

  ws.close();
  proc.kill();
  await sleep(300);
  try { fs.rmSync(process.cwd() + "\\.edge-tmp", { recursive: true, force: true }); } catch (e) {}
  process.exit(bad ? 1 : 0);
}

main().catch((e) => { console.log("FAIL 运行异常:", e.message); process.exit(1); });
