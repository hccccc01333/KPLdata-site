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
  // 线上访问受网络与 307（/match.html → /match）影响，固定 settle 不可靠：轮询到条件成立为止
  async function waitFor(expr, timeout = 15000, every = 300) {
    const t0 = Date.now();
    for (;;) {
      const v = await evaluate(expr);
      if (v && !v.__err) return v;
      if (Date.now() - t0 > timeout) return v;
      await sleep(every);
    }
  }

  /* ---- 1+2：game.html 资源 / 分路 ---- */
  let err = await visit("game.html?id=48251408_47_1793364935", 400);
  check("game.html 无未捕获异常", err.length === 0, err.join(" | "));

  const score = await waitFor(`document.querySelectorAll('#curveScore .cs-k').length || null`, 15000) || 0;
  check("终局记分牌渲染（两队各 5 项指标）", score === 10, "chips=" + score);

  await waitFor(`!!document.querySelector('#curveTabsTeam [data-t="res"]')`);
  await evaluate(`document.querySelector('#curveTabsTeam [data-t="res"]').click()`);
  await waitFor(`document.querySelectorAll('#curveChart .res-dot').length > 0`);
  await sleep(400);
  const res = await evaluate(`(function(){
    var labels = Array.from(document.querySelectorAll('#curveChart .res-tl text')).map(function(t){return t.textContent.trim();});
    return { dots: document.querySelectorAll('#curveChart .res-dot').length,
             hasLord: labels.indexOf('主宰') >= 0, hasDark: labels.indexOf('黑暗暴君') >= 0 };
  })()`);
  check("中立资源为点状时间轴（主宰 / 黑暗暴君两行）", !!res && res.hasLord && res.hasDark && res.dots > 0,
    "dots=" + (res && res.dots));

  await evaluate(`document.querySelector('#curveTabsTeam [data-t="gd"]').click()`);
  await waitFor(`document.querySelectorAll('#curveChart svg rect').length > 0`);
  await sleep(300);
  const bars = await evaluate(`document.querySelectorAll('#curveChart svg rect').length`);
  check("经济差动力为逐分钟柱状图", bars >= 8, "rects=" + bars);

  await evaluate(`document.querySelector('#curveTabsLane [data-t="lane"]').click()`);
  await waitFor(`document.querySelectorAll('#curveChart .duel-chip').length > 0`);
  await sleep(300);
  const lane = await evaluate(`(function(){
    var chips = Array.from(document.querySelectorAll('#curveChart .duel-chip')).map(function(c){return c.textContent.trim();});
    var lanes = ['对抗路','打野','中路','发育路','游走'];
    var head = (document.getElementById('duelHead')||{}).textContent || '';
    return { chips: chips.length, lanes: lanes.filter(function(l){return chips.some(function(c){return c.indexOf(l)===0;});}).length,
             headOk: /VS/.test(head), leadPaths: document.querySelectorAll('#duelLead svg path').length };
  })()`);
  check("分路对位为五路决斗卡", !!lane && lane.chips === 5 && lane.lanes === 5, "chips=" + (lane && lane.chips));
  check("决斗视图含双方与领先差大图", !!lane && lane.headOk && lane.leadPaths > 0, "paths=" + (lane && lane.leadPaths));
  // 切到输出口径，决斗视图应重绘
  await evaluate(`document.querySelector('#duelMetric [data-m="dmg"]').click()`);
  await sleep(400);
  const dmg = await evaluate(`(function(){
    var head = (document.getElementById('duelHead')||{}).textContent || '';
    return { headOk: /VS/.test(head), paths: document.querySelectorAll('#duelLead svg path').length };
  })()`);
  check("输出口径决斗视图重绘", !!dmg && dmg.headOk && dmg.paths > 0, "paths=" + (dmg && dmg.paths));
  // 点对抗路芯片，决斗视图应切换
  await evaluate(`document.querySelector('#curveChart .duel-chip[data-i="0"]').click()`);
  await sleep(400);
  const chip0 = await evaluate(`(document.getElementById('duelHead')||{}).textContent || ''`);
  check("点击分路芯片切换对位", (chip0 || "").length > 4, String(chip0).slice(0, 30));
  const bfly = await waitFor(`(function(){
    var rows = Array.from(document.querySelectorAll('#duelBfly .bf-lb')).map(function(x){return x.textContent.trim();});
    return rows.length ? { rows: rows.length, hasTank: rows.indexOf('承受占比') >= 0, hasKda: rows.indexOf('K / D / A') >= 0,
             bars: document.querySelectorAll('#duelBfly .bf-cell i').length } : null;
  })()`, 20000) || { rows: 0, bars: 0 };
  check("终局贡献蝶形图（含承伤占比 / 参团率 / KDA）", !!bfly && bfly.rows === 5 && bfly.hasTank && bfly.hasKda && bfly.bars === 8,
    "rows=" + (bfly && bfly.rows) + " bars=" + (bfly && bfly.bars));
  err = await visit("game.html?id=48251408_47_1793364935", 600);
  check("game.html 复检无异常（含分路切换后）", err.length === 0, err.join(" | "));

  /* ---- 3：match.html 对局选择弹窗 ---- */
  err = await visit("match.html?id=2026103001", 300);
  check("match.html 无未捕获异常", err.length === 0, err.join(" | "));
  const modal = await waitFor(`(function(){
    var m = document.getElementById('gselModal');
    if (!m) return null;
    return { on: true, cards: m.querySelectorAll('.gsel-card').length,
             head: (m.querySelector('h3')||{}).textContent || '',
             sub: (m.querySelector('.gsel-sub')||{}).textContent || '' };
  })()`) || { on: false };
  check("已结束多局比赛先弹对局选择弹窗", !!modal && modal.on === true, "");
  check("弹窗卡片数 = 6 局", !!modal && modal.cards === 6, "cards=" + (modal && modal.cards));
  check("弹窗含比分与两队", !!modal && /上海EDG\.M/.test(modal.sub || "") && /杭州LGD\.NBW/.test(modal.sub || ""), modal && modal.sub);

  // 点第一张卡 → 跳转到对应单局页（线上 pretty URL 会把 /game.html 归一成 /game，两种都算过）
  await waitFor(`!!document.querySelector('#gselModal .gsel-card')`);
  const firstBid = await evaluate(`document.querySelector('#gselModal .gsel-card').getAttribute('data-bid')`);
  await evaluate(`document.querySelector('#gselModal .gsel-card').click()`);
  const href1 = await waitFor(`(/\\/game(\\.html)?\\?/.test(location.pathname + location.search) || location.href.indexOf('game.html?id=') >= 0) && location.href.indexOf('id=${firstBid}') >= 0 ? location.href : null`, 15000) || "";
  check("点卡片跳转到单局复盘空间", typeof href1 === "string" && href1.indexOf(firstBid) >= 0 && /\/game(\.html)?\?/.test(href1), String(href1));

  // 再开一次：Esc 关闭 → 弹窗消失 → 整场概览挂上复盘工作台
  await visit("match.html?id=2026103001", 300);
  await waitFor(`!!document.getElementById('gselModal')`);
  await evaluate(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))`);
  const afterEsc = await waitFor(`(function(){
    return !document.getElementById('gselModal') &&
           !!document.getElementById('replayWorkbench') && document.getElementById('replayWorkbench').children.length > 0
      ? { modalGone: true, workbench: true } : null;
  })()`) || { modalGone: false, workbench: false };
  check("Esc 关闭后回落整场概览并挂默认复盘", !!afterEsc && afterEsc.modalGone && afterEsc.workbench, JSON.stringify(afterEsc));

  /* ---- 4：分享深链不弹窗 ---- */
  await visit("match.html?id=2026062603&g=3&m=13", 300);
  const deep = await waitFor(`document.getElementById('rpRange') ? { modal: !!document.getElementById('gselModal'), rp: true } : null`, 15000)
    || { modal: null, rp: false };
  check("分享深链 ?g=3 不弹窗且直接进复盘", !!deep && deep.modal === false && deep.rp === true, JSON.stringify(deep));

  await send("Browser.close").catch(() => {});
  proc.kill();
  console.log(bad === 0 ? "=== 全部通过 ===" : "=== " + bad + " 项失败 ===");
  process.exit(bad === 0 ? 0 : 1);
}

main().catch((e) => { console.log("FAIL 脚本异常", e); process.exit(1); });
