// 智能找局验收：Edge CDP
const { spawn } = require("child_process");
const os = require("os");
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9344;
const BASE = (process.argv[2] || "http://127.0.0.1:8780").replace(/\/$/, "");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let bad = 0;
const check = (n, ok, x) => { if (!ok) bad++; console.log((ok ? "PASS " : "FAIL ") + n + (x !== undefined ? "  → " + x : "")); };

async function main() {
  const proc = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-sandbox", `--remote-debugging-port=${PORT}`,
    "--user-data-dir=" + os.tmpdir() + "\\kpl-find-check", "about:blank"], { stdio: "ignore" });
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
  async function waitFor(expr, ms = 30000) { const t = Date.now(); while (Date.now() - t < ms) { if (await ev(expr)) return true; await sleep(200); } return false; }

  await send("Page.enable"); await send("Runtime.enable"); await send("Network.enable"); await send("Network.setCacheDisabled", { cacheDisabled: true });
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 950, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: BASE + "/find.html" });
  await sleep(2500);
  const ready = await waitFor("document.querySelectorAll('#findBody tr').length > 0 && !/正在加载/.test(document.querySelector('#fCount').textContent)", 30000);
  check("找局页加载索引并出结果", ready, await ev("document.querySelector('#fCount').textContent"));

  const base = await ev(`(function(){var t=document.querySelector('#findBody');return {rows:t.querySelectorAll('tr').length, text:t.textContent.slice(0,80), link:(t.querySelector('a[href*="game.html?id="]')||{}).getAttribute('href')||''};})()`);
  check("结果含对局深链", base && /game\.html\?id=/.test(base.link), base && base.link.slice(0, 60));
  check("无 JS 异常", errors.length === 0, errors.join(" | "));

  await ev(`(function(){var y=document.querySelector('#fYear');y.value='2026';y.dispatchEvent(new Event('change',{bubbles:true}));var t=document.querySelector('#fTeam');t.value='重庆狼队';t.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await sleep(700);
  const filtered = await ev(`(function(){
    var rows=[].slice.call(document.querySelectorAll('#findBody tr')).filter(function(r){return r.children.length>=8});
    var ok=rows.slice(0,12).every(function(r){return /重庆狼队/.test(r.children[2].textContent)});
    return {n:rows.length, ok:ok, count:document.querySelector('#fCount').textContent, url:location.search};
  })()`);
  check("年份+战队筛选生效且行内容匹配", filtered && filtered.n > 0 && filtered.ok, filtered && (filtered.n + " 行 · " + filtered.count));
  check("筛选条件写入 URL", filtered && /year=2026/.test(filtered.url) && /team=/.test(filtered.url), filtered && filtered.url);

  await ev(`(function(){var w=document.querySelector('#fWinner');w.value='重庆狼队';w.dispatchEvent(new Event('change',{bubbles:true}));var d=document.querySelector('#fDurMin');d.value='15';d.dispatchEvent(new Event('input',{bubbles:true}));})()`);
  await sleep(700);
  const strong = await ev(`(function(){
    var rows=[].slice.call(document.querySelectorAll('#findBody tr')).filter(function(r){return r.children.length>=8});
    var okWin=rows.every(function(r){return r.children[5].textContent.trim()==='重庆狼队'});
    var okDur=rows.every(function(r){return parseInt(r.children[4].textContent,10)>=15});
    return {n:rows.length, okWin:okWin, okDur:okDur};
  })()`);
  check("胜方+时长条件同时生效", strong && strong.n > 0 && strong.okWin && strong.okDur,
    strong && (strong.n + " 行 / 胜方 " + strong.okWin + " / 时长 " + strong.okDur));

  await ev(`(function(){var b=document.querySelector('#fBp');b.value='full';b.dispatchEvent(new Event('change',{bubbles:true}));})()`);
  await sleep(600);
  const bp = await ev(`(function(){
    var rows=[].slice.call(document.querySelectorAll('#findBody tr')).filter(function(r){return r.children.length>=8});
    return {n:rows.length, ok:rows.every(function(r){return r.children[6].textContent.trim()==='完整 BP'})};
  })()`);
  check("完整 BP 条件生效", bp && bp.n > 0 && bp.ok, bp && (bp.n + " 行 / " + bp.ok));

  // 带参数的深链
  await send("Page.navigate", { url: BASE + "/find.html?year=2026&team=%E9%87%8D%E5%BA%86%E7%8B%BC%E9%98%9F&bp=full" });
  await sleep(2200);
  await waitFor("document.querySelectorAll('#findBody tr').length > 0", 30000);
  const deep = await ev(`(function(){return {year:document.querySelector('#fYear').value,team:document.querySelector('#fTeam').value,bp:document.querySelector('#fBp').value,count:document.querySelector('#fCount').textContent};})()`);
  check("筛选参数深链可回填", deep && deep.year === "2026" && deep.team === "重庆狼队" && deep.bp === "full", deep && JSON.stringify(deep));

  await ev(`(function(){window.scrollTo(0,0);})()`);
  const overflow = await ev(`(function(){return {sw:document.documentElement.scrollWidth,iw:window.innerWidth};})()`);
  check("桌面端无页面横向溢出", overflow && overflow.sw <= overflow.iw + 1, overflow && (overflow.sw + "/" + overflow.iw));

  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await sleep(600);
  const mob = await ev(`(function(){return {sw:document.documentElement.scrollWidth,iw:window.innerWidth,rows:document.querySelectorAll('#findBody tr').length};})()`);
  check("390px 页面无横向溢出且结果仍在", mob && mob.sw <= mob.iw + 1 && mob.rows > 0, mob && (mob.sw + "/" + mob.iw + " · " + mob.rows + " 行"));

  // 查询页入口 + 导航入口
  await send("Page.navigate", { url: BASE + "/query.html" });
  await sleep(1500);
  const link = await ev(`(!!document.querySelector('a[href="find.html"]'))`);
  check("查询页有智能找局入口", !!link);
  await send("Page.navigate", { url: BASE + "/find.html" });
  await sleep(2500);
  await waitFor("!!document.querySelector('#siteNav a[href=\"find.html\"]')", 15000);
  const navDump = await ev(`(function(){var n=document.getElementById('siteNav');return {has:!!n,links:n?[].slice.call(n.querySelectorAll('a')).map(function(a){return a.getAttribute('href')}):[],header:(document.getElementById('siteHeader').textContent||'').slice(0,60)};})()`);
  console.log("NAVDUMP", JSON.stringify(navDump).slice(0, 800));
  const nav = await ev(`(!!document.querySelector('#siteNav a[href="find.html"]'))`);
  check("六入口导航含智能找局", !!nav);

  console.log(bad ? "FAILED " + bad : "ALL PASS");
  proc.kill(); process.exit(bad ? 1 : 0);
}
main().catch((e) => { console.log("FAIL " + e.stack); process.exit(1); });
