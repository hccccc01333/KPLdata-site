// 截图目视验收：数据曲线各页签渲染效果
const { spawn } = require("child_process");
const fs = require("fs");
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const PORT = 9338;
const BASE = (process.argv[2] || "http://127.0.0.1:8777").replace(/\/$/, "") + "/";
const OUT = process.argv[3] || "_shots";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function main() {
  fs.mkdirSync(OUT, { recursive: true });
  const proc = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-sandbox",
    `--remote-debugging-port=${PORT}`, "--user-data-dir=" + require("os").tmpdir() + "\kpl-edge-shot",
    "--window-size=1500,2400", "about:blank"], { stdio: "ignore" });
  let target = null;
  for (let i = 0; i < 60; i++) {
    await sleep(250);
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      target = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (target) break;
    } catch (e) {}
  }
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0; const pending = new Map();
  ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
  const send = (method, params) => new Promise((res) => { const myId = ++id; pending.set(myId, res); ws.send(JSON.stringify({ id: myId, method, params })); });
  const evaluate = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
    return r.result && r.result.result ? r.result.result.value : undefined;
  };
  await send("Page.enable"); await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 2200, deviceScaleFactor: 1, mobile: false });
  const SHOTS = [
    ["win", "curveTabsTeam"], ["gd", "curveTabsTeam"], ["res", "curveTabsTeam"], ["lane", "curveTabsLane"]
  ];
  await send("Page.navigate", { url: BASE + "game.html?id=48251408_47_1793364935&theme=dark" });
  await sleep(4000);
  for (const [tab, grp] of SHOTS) {
    await evaluate(`document.querySelector('#${grp} [data-t="${tab}"]').click()`);
    await sleep(1200);
    // 滚到数据曲线面板
    await evaluate(`document.querySelectorAll('.panel').forEach(function(p){ if (p.querySelector('#curveChart')) p.scrollIntoView(); })`);
    await sleep(300);
    const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { x: 0, y: await evaluate(`(function(){var p=document.getElementById('curveChart').closest('.panel'); return p.getBoundingClientRect().top + window.scrollY - 10;})()`), width: 1440, height: 1250, scale: 1 } });
    fs.writeFileSync(OUT + "/curve_" + tab + ".png", Buffer.from(shot.result.data, "base64"));
    console.log("saved", tab);
  }
  proc.kill();
}
main().catch((e) => { console.error(e); process.exit(1); });
