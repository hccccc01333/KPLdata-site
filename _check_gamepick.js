// 针对性验收：
//   1. game.html 资源页签：只有 主宰 / 黑暗暴君 两张小图，纵轴是个位数计数（修复后不再出现成百上千）
//   2. game.html 分路页签：有复盘名单的局渲染 5 张「同位置对位」小图（修复 esc 未定义导致的整块空白）
//   3. match.html 已结束多局比赛：先弹「要进入哪一局」选择弹窗；点卡片跳单局；Esc/关闭回落整场概览并挂复盘
//   4. 分享深链 ?g=3 不弹窗，直接落到对应局
// 用法：python -m http.server 8777 后 node _check_gamepick.js [http://127.0.0.1:8777]
const { spawn } = require("child_process");

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9337;
const BASE = (process.argv[2] || "http://127.0.0.1:8777").replace(/\/$/, "") + "/";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let bad = 0;
const check = (name, ok, extra) => {
  if (!ok) bad++;
  console.log((ok ? "PASS " : "FAIL ") + name + (extra !== undefined && extra !== "" ? "  → " + extra : ""));
};

async function main() {
  const proc = spawn(EDGE, [
    "--headless=new", "--disable-gpu", "--no-sandbox",
    `--remote-debugging-port=${PORT}`,
    "--user-data-dir=" + require("os").tmpdir() + "\\kpl-edge-gamepick",
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
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  const send = (method, params) => new Promise((res) => {
    const myId = ++id; pending.set(myId, res);
    ws.send(JSON.stringify({ id: myId, method, params }));
  });
  const evaluate = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true });
    if (r.result && r.result.exceptionDetails) {
      const d = r.result.exceptionDetails;
      return { __err: (d.exception && d.exception.description) || d.text || "eval error" };
    }
    return r.result && r.result.result ? r.result.result.value : undefined;
  };

  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Network.setCacheDisabled", { cacheDisabled: true });
  await send("Page.addScriptToEvaluateOnNewDocument", {
    source: `
      window.__kplUnhandled = [];
      window.addEventListener("unhandledrejection", function (e) {
        var r = e.reason; window.__kplUnhandled.push("unhandledrejection: " + ((r && r.message) || String(r)));
      });
      window.addEventListener("error", function (e) {
        window.__kplUnhandled.push("window.error: " + (e.message || ""));
      });
    `,
  });

  async function visit(url, settle = 1600) {
    errors = [];
    await send("Page.navigate", { url: BASE + url });
    for (let i = 0; i < 40; i++) {
      await sleep(200);
      const ready = await evaluate("document.readyState");
      if (ready === "complete") break;
    }
    await sleep(settle);
    return errors;
  }

  /* ---- 1+2：game.html 资源 / 分路 ---- */
  let err = await visit("game.html?id=48251408_47_1793364935", 2200);
  check("game.html 无未捕获异常", err.length === 0, err.join(" | "));

  await evaluate(`document.querySelector('#curveTabsTeam [data-t="res"]').click()`);
  await sleep(600);
  const res = await evaluate(`(function(){
    var titles = Array.from(document.querySelectorAll('#curveChart .rp-sm-t')).map(function(x){return x.textContent.trim();});
    var ticks = Array.from(document.querySelectorAll('#curveChart svg text')).map(function(t){return t.textContent;});
    var nums = ticks.map(function(s){ var m = s.match(/^(\\d+(?:\\.\\d+)?)$/); return m ? Number(m[1]) : null; }).filter(function(v){return v!==null;});
    return { titles: titles, maxTick: nums.length ? Math.max.apply(null, nums) : null, tickCount: nums.length };
  })()`);
  check("资源图只有 2 张（主宰 / 黑暗暴君）", res && res.titles && res.titles.length === 2, JSON.stringify(res && res.titles));
  check("资源图标题正确", !!res && !!res.titles && res.titles.indexOf("主宰") >= 0 && res.titles.indexOf("黑暗暴君") >= 0, "");
  check("资源图纵轴为个位数整数计数", !!res && res.maxTick !== null && res.maxTick <= 12, "maxTick=" + (res && res.maxTick));

  await evaluate(`document.querySelector('#curveTabsLane [data-t="player"]').click()`);
  await sleep(700);
  const lane = await evaluate(`(function(){
    var titles = Array.from(document.querySelectorAll('#curveChart .rp-sm-t')).map(function(x){return x.textContent.trim();});
    var paths = document.querySelectorAll('#curveChart svg path').length;
    return { n: titles.length, withVs: titles.filter(function(t){return t.indexOf(' vs ')>=0;}).length, paths: paths, first: titles[0] || '' };
  })()`);
  check("分路经济渲染 5 张同位置对位小图", !!lane && lane.n === 5 && lane.withVs === 5, "n=" + (lane && lane.n) + " withVs=" + (lane && lane.withVs));
  check("分路小图实际画出曲线", !!lane && lane.paths > 0, "paths=" + (lane && lane.paths));

  await evaluate(`document.querySelector('#curveTabsLane [data-t="dmg"]').click()`);
  await sleep(700);
  const dmg = await evaluate(`document.querySelectorAll('#curveChart .rp-sm').length`);
  check("分路输出渲染 5 张小图", dmg === 5, "n=" + dmg);
  err = await visit("game.html?id=48251408_47_1793364935", 1200);
  check("game.html 复检无异常（含分路切换后）", err.length === 0, err.join(" | "));

  /* ---- 3：match.html 对局选择弹窗 ---- */
  err = await visit("match.html?id=2026103001", 2000);
  check("match.html 无未捕获异常", err.length === 0, err.join(" | "));
  const modal = await evaluate(`(function(){
    var m = document.getElementById('gselModal');
    if (!m) return { on: false };
    return { on: true, cards: m.querySelectorAll('.gsel-card').length,
             head: (m.querySelector('h3')||{}).textContent || '',
             sub: (m.querySelector('.gsel-sub')||{}).textContent || '' };
  })()`);
  check("已结束多局比赛先弹对局选择弹窗", !!modal && modal.on === true, "");
  check("弹窗卡片数 = 6 局", !!modal && modal.cards === 6, "cards=" + (modal && modal.cards));
  check("弹窗含比分与两队", !!modal && /上海EDG\.M/.test(modal.sub || "") && /杭州LGD\.NBW/.test(modal.sub || ""), modal && modal.sub);

  // 点第一张卡 → 跳转到对应单局页
  const firstBid = await evaluate(`document.querySelector('#gselModal .gsel-card').getAttribute('data-bid')`);
  await evaluate(`document.querySelector('#gselModal .gsel-card').click()`);
  await sleep(1200);
  const url1 = await send("Runtime.evaluate", { expression: "location.href", returnByValue: true });
  const href1 = url1.result.result.value;
  check("点卡片跳转到单局复盘空间", typeof href1 === "string" && href1.indexOf("game.html?id=" + firstBid) >= 0, href1);

  // 再开一次：Esc 关闭 → 弹窗消失 → 整场概览挂上复盘工作台
  await visit("match.html?id=2026103001", 1600);
  await evaluate(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))`);
  await sleep(400);
  const afterEsc = await evaluate(`(function(){
    return { modalGone: !document.getElementById('gselModal'),
             workbench: !!document.getElementById('replayWorkbench') && document.getElementById('replayWorkbench').children.length > 0 };
  })()`);
  check("Esc 关闭后回落整场概览并挂默认复盘", !!afterEsc && afterEsc.modalGone && afterEsc.workbench, JSON.stringify(afterEsc));

  /* ---- 4：分享深链不弹窗 ---- */
  await visit("match.html?id=2026062603&g=3&m=13", 1800);
  const deep = await evaluate(`({ modal: !!document.getElementById('gselModal'), rp: !!document.getElementById('rpRange') })`);
  check("分享深链 ?g=3 不弹窗且直接进复盘", !!deep && deep.modal === false && deep.rp === true, JSON.stringify(deep));

  await send("Browser.close").catch(() => {});
  proc.kill();
  console.log(bad === 0 ? "=== 全部通过 ===" : "=== " + bad + " 项失败 ===");
  process.exit(bad === 0 ? 0 : 1);
}

main().catch((e) => { console.log("FAIL 脚本异常", e); process.exit(1); });
