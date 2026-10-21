// 赛前预测挑战验收：Edge CDP，本地/线上均可
const { spawn } = require("child_process");
const os = require("os");
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9343;
const BASE = (process.argv[2] || "http://127.0.0.1:8780").replace(/\/$/, "");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let bad = 0;
const check = (n, ok, x) => { if (!ok) bad++; console.log((ok ? "PASS " : "FAIL ") + n + (x ? "  → " + x : "")); };

async function main() {
  const proc = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-sandbox", `--remote-debugging-port=${PORT}`,
    "--user-data-dir=" + os.tmpdir() + "\\kpl-challenge-check", "about:blank"], { stdio: "ignore" });
  let target = null;
  for (let i = 0; i < 80; i++) {
    await sleep(250);
    try { const l = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); target = l.find((t) => t.type === "page" && t.webSocketDebuggerUrl); if (target) break; } catch (e) {}
  }
  if (!target) { console.log("FAIL CDP"); proc.kill(); process.exit(1); }
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0; const pending = new Map(); let errors = [];
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.method === "Runtime.exceptionThrown") errors.push(((m.params.exceptionDetails.exception || {}).description || m.params.exceptionDetails.text || "").split("\n")[0]);
    if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push("console.error");
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  const send = (method, params) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }); return r.result && r.result.result ? r.result.result.value : undefined; };
  async function waitFor(expr, ms = 20000) { const t = Date.now(); while (Date.now() - t < ms) { if (await ev(expr)) return true; await sleep(200); } return false; }

  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Network.setCacheDisabled", { cacheDisabled: true });
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 950, deviceScaleFactor: 1, mobile: false });
  await ev("localStorage.removeItem('kpl_predict_challenge_v1')");
  await send("Page.navigate", { url: BASE + "/predict.html" });
  await sleep(2500);
  await ev("document.querySelector('#challengeBlock').scrollIntoView({block:'center'})");
  const loaded = await waitFor("document.querySelectorAll('#chList .ch-row').length > 0 && !!window.KPL_SCHEDULE_ALL", 25000);
  check("滚动到挑战区后赛程加载并渲染", loaded, await ev("document.querySelectorAll('#chList .ch-row').length"));

  const ui = await ev(`(function(){
    return {stats:document.querySelector('#chStats').textContent,
            rows:document.querySelectorAll('#chList .ch-row').length,
            picks:document.querySelectorAll('#chList .ch-pick').length,
            upcoming:document.querySelectorAll('#chList .ch-pick').length>0};
  })()`);
  check("挑战区有可选项", ui && ui.picks >= 2, ui && (ui.rows + " 行 / " + ui.picks + " 个选择"));
  check("无 JS 异常", errors.length === 0, errors.join(" | "));

  const first = await ev(`(function(){var b=document.querySelector('#chList .ch-pick');if(!b)return null;var r={mid:b.getAttribute('data-mid'),team:b.getAttribute('data-team')};b.click();return r;})()`);
  const afterPick = await ev(`(function(){
    var s=JSON.parse(localStorage.getItem('kpl_predict_challenge_v1')||'{}');
    var on=document.querySelectorAll('#chList .ch-pick.on').length;
    return {on:on, stored:!!(s.picks&&s.picks['${first && first.mid}']), txt:document.querySelector('#chList .ch-state').textContent};
  })()`);
  check("点队名写入 localStorage 并高亮", afterPick && afterPick.on === 1 && afterPick.stored, afterPick && (afterPick.txt || ""));

  await send("Page.navigate", { url: BASE + "/predict.html" });
  await sleep(2200);
  await ev("document.querySelector('#challengeBlock').scrollIntoView({block:'center'})");
  await waitFor("document.querySelectorAll('#chList .ch-row').length > 0", 20000);
  const persisted = await ev(`document.querySelectorAll('#chList .ch-pick.on').length`);
  check("刷新后选择仍在", persisted === 1, persisted);

  const done = await ev(`(function(){
    var S=(window.KPL_SCHEDULE_ALL||[]).filter(function(r){return r.done && r.score1!=null && r.score2!=null;})
      .sort(function(a,b){return (b.date+'').localeCompare(a.date+'')});
    if(!S.length) return null;
    var r=S[0], w=Number(r.score1)>Number(r.score2)?r.team1:r.team2;
    localStorage.setItem('kpl_predict_challenge_v1', JSON.stringify({picks:{[String(r.matchId)]:{pick:w,at:new Date().toISOString()}}}));
    return {mid:r.matchId,winner:w,date:r.date};
  })()`);
  await send("Page.navigate", { url: BASE + "/predict.html" });
  await sleep(2200);
  await ev("document.querySelector('#challengeBlock').scrollIntoView({block:'center'})");
  await waitFor("document.querySelectorAll('#chList .ch-row').length > 0", 20000);
  const settled = await ev(`(function(){
    var t=document.querySelector('#chStats').textContent;
    var good=document.querySelectorAll('#chList .ch-state.good').length;
    return {stats:t,good:good};
  })()`);
  check("已完赛选择自动结算为命中", settled && /100%/.test(settled.stats) && settled.good >= 1, settled && settled.stats);
  check("结算后无 JS 异常", errors.length === 0, errors.join(" | "));

  await ev("localStorage.removeItem('kpl_predict_challenge_v1')");
  console.log(bad ? "FAILED " + bad : "ALL PASS");
  proc.kill(); process.exit(bad ? 1 : 0);
}
main().catch((e) => { console.log("FAIL " + e.stack); process.exit(1); });
