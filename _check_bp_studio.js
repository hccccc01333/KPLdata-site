// BP 赛事演播室浏览器验收（真实 Edge / CDP）
// 用法：python -m http.server 8778  (在站点目录)  →  node _check_bp_studio.js http://127.0.0.1:8778
const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const vm = require("vm");

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9341;
const BASE = (process.argv[2] || "http://127.0.0.1:8778").replace(/\/$/, "") + "/";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let bad = 0;
const fail = [];
const check = (name, ok, extra) => {
  if (!ok) { bad++; fail.push(name); }
  console.log((ok ? "PASS " : "FAIL ") + name + (extra !== undefined && extra !== "" ? "  → " + extra : ""));
};

// ---- 原始数据 oracle：直接读站点自身的索引/分片，避免“页面自己说自己对” ----
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync("assets/games/index.js", "utf8"), ctx);
vm.runInContext(fs.readFileSync("assets/schedule_all.js", "utf8"), ctx);
const IDX = ctx.KPL_GAME_INDEX;
const SCHEDULE = ctx.KPL_SCHEDULE_ALL;
const SCHED_BY_ID = Object.fromEntries(SCHEDULE.map((r) => [String(r.matchId), r]));

function oracle(mid, seq) {
  const rec = IDX[String(mid)];
  if (!rec) throw Error("索引里没有 " + mid);
  const battles = JSON.parse(fs.readFileSync("assets/games/" + rec.lg + ".json", "utf8"));
  const row = rec.b.find((r) => Number(r[1]) === Number(seq));
  if (!row) throw Error("比赛 " + mid + " 没有第 " + seq + " 局");
  const battle = battles[String(row[0])];
  if (!battle) throw Error("分片里没有 " + row[0]);
  return { rec, row, battle, bid: String(row[0]), schedule: SCHED_BY_ID[String(mid)] || {} };
}

const CASES = [
  { mid: "2026091201", seq: 6, label: "2026 夏决 BO7 第 6 局" },
  { mid: "2026090601", seq: 1, label: "2026 季后赛 BO7 第 1 局" },
  { mid: "2026090301", seq: 4, label: "2026 季后赛 BO7 第 4 局" },
];
const heroOf = (t) => String(t || "").split(" · ")[0];

async function main() {
  const proc = spawn(EDGE, [
    "--headless=new", "--disable-gpu", "--no-sandbox",
    `--remote-debugging-port=${PORT}`,
    "--user-data-dir=" + os.tmpdir() + "\\kpl-bp-studio-check",
    "about:blank",
  ], { stdio: "ignore" });

  let target = null;
  for (let i = 0; i < 80; i++) {
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
      if (t) errors.push("console.error: " + String(t).slice(0, 160));
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
  await send("Network.enable");
  await send("Network.setCacheDisabled", { cacheDisabled: true });
  await send("Page.addScriptToEvaluateOnNewDocument", {
    source: `
      window.__kplUnhandled = [];
      window.addEventListener("unhandledrejection", function (e) {
        var r = e.reason;
        window.__kplUnhandled.push("unhandledrejection: " + ((r && r.message) || String(r)));
      });
      window.addEventListener("error", function (e) { window.__kplUnhandled.push("window.error: " + (e.message || "")); });
    `,
  });

  async function viewport(width, height) {
    await send("Emulation.setDeviceMetricsOverride", {
      width, height, deviceScaleFactor: 1, mobile: width < 600,
    });
  }

  async function visit(path, width = 1440, height = 1000, settle = 1800) {
    errors = [];
    await viewport(width, height);
    await send("Page.navigate", { url: BASE + path });
    await sleep(settle);
    const unhandled = await evaluate("window.__kplUnhandled || []");
    if (Array.isArray(unhandled)) errors.push(...unhandled);
  }

  const actionOracle = (battle) => (battle.bp || []).map((b, i) =>
    "第 " + (i + 1) + " 手，" + (Number(b[0]) === 1 ? "蓝方" : "红方") +
    (Number(b[1]) === 1 ? "选用" : "禁用") + String(b[2] || ""));

  // ---- 1. 三场真实 BO7：数据对账 + 交互 + 三档响应式 ----
  for (const c of CASES) {
    const { battle, bid, schedule } = oracle(c.mid, c.seq);
    const expectActions = actionOracle(battle);
    const picks = (camp) => battle.bp.filter((x) => Number(x[0]) === camp && Number(x[1]) === 1).map((x) => String(x[2]));
    const bans = (camp) => battle.bp.filter((x) => Number(x[0]) === camp && Number(x[1]) === 0).map((x) => String(x[2]));

    console.log(`\n=== ${c.label}（${c.mid} / 第 ${c.seq} 局）===`);
    await visit(`bp-studio.html?match=${c.mid}&g=${c.seq}`, 1440, 1000, 2000);

    // 外部图床（英雄/战队图标）可能比页面脚本慢，等 complete 再断言，最多 6 秒
    await evaluate(`new Promise(function(res){
      var imgs = Array.prototype.slice.call(document.querySelectorAll('#blueLineup img, #redLineup img, #blueBans img, #redBans img, #logoBlue, #logoRed'));
      var timer = setTimeout(res, 6000);
      (function poll(){
        if (imgs.every(function(i){ return i.complete; })) { clearTimeout(timer); res(); }
        else setTimeout(poll, 150);
      })();
    })`);

    const head = await evaluate(`(function(){
      var q=function(s){return document.querySelector(s)};
      return {
        ctx:(q("#matchContext")||{}).textContent||"",
        date:(q("#matchDate")||{}).textContent||"",
        blue:(q("#nameBlue")||{}).textContent||"",
        red:(q("#nameRed")||{}).textContent||"",
        blueScore:(q("#blueSeries")||{}).textContent||"",
        redScore:(q("#redSeries")||{}).textContent||"",
        seriesNote:(q("#seriesNote")||{}).textContent||"",
        chip:(q("#stateChip")||{}).textContent||"",
        hint:(q("#winHint")||{}).textContent||"",
        dataHint:(q("#dataHint")||{}).textContent||"",
        step:(q("#stepText")||{}).textContent||"",
        blueCount:(q("#bluePickCount")||{}).textContent||"",
        redCount:(q("#redPickCount")||{}).textContent||"",
        actions:document.querySelectorAll("#bpActions .studio-action").length,
        blueCards:document.querySelectorAll("#blueLineup .studio-card.filled").length,
        redCards:document.querySelectorAll("#redLineup .studio-card.filled").length,
        blueBans:document.querySelectorAll("#blueBans .studio-ban").length,
        redBans:document.querySelectorAll("#redBans .studio-ban").length,
        blueBanTitles:Array.prototype.map.call(document.querySelectorAll("#blueBans .studio-ban"),function(x){return x.title}),
        redBanTitles:Array.prototype.map.call(document.querySelectorAll("#redBans .studio-ban"),function(x){return x.title}),
        blueCardTitles:Array.prototype.map.call(document.querySelectorAll("#blueLineup .studio-card.filled"),function(x){return x.title}),
        redCardTitles:Array.prototype.map.call(document.querySelectorAll("#redLineup .studio-card.filled"),function(x){return x.title}),
        prior:(q("#priorLabel")||{}).textContent||"",
        prevTeams:document.querySelectorAll("#previousPicks .studio-prev-team").length,
        stats:document.querySelectorAll("#postStats .studio-stat").length,
        detail:(q("#detailLink")||{}).getAttribute("href")||"",
        gameLink:(q("#gameLink")||{}).getAttribute("href")||"",
        feedback:(q("#studioFeedback")||{}).textContent||"",
        labels:Array.prototype.map.call(document.querySelectorAll("#bpActions .studio-action"),function(x){return x.getAttribute("aria-label")||""}),
        imgs:Array.prototype.map.call(document.querySelectorAll("#blueLineup img, #redLineup img, #blueBans img, #redBans img, #logoBlue, #logoRed"),function(x){return {src:x.getAttribute("src")||"",w:x.naturalWidth,h:x.naturalHeight}}),
      };
    })()`);

    check("页面无 JS 异常", errors.length === 0, errors.join(" | "));
    check("赛事上下文正确", head && /2026.*夏季赛/.test(head.ctx) && head.ctx.includes(schedule.stage || ""),
      head && head.ctx);
    check("蓝红双方队名与原始数据一致",
      head && [head.blue, head.red].sort().join("|") === [battle.t1, battle.t2].sort().join("|"),
      head && (head.blue + " vs " + head.red + " / 期望 " + battle.t1 + " vs " + battle.t2));
    check("大场比分已显示且与赛程一致",
      head && head.seriesNote === "最终大场比分" && Number(head.blueScore) + Number(head.redScore) === Number(schedule.score1) + Number(schedule.score2),
      head && (head.blueScore + " : " + head.redScore + " / 赛程 " + schedule.score1 + " : " + schedule.score2));
    check("BP 动作数与原始数据一致", head && head.actions === battle.bp.length, head && (head.actions + " / " + battle.bp.length));
    check("逐手动作顺序与英雄完全对账", head && JSON.stringify(head.labels) === JSON.stringify(expectActions),
      head && (head.labels.length === expectActions.length ? "首个不一致：" + (head.labels.find((x, i) => x !== expectActions[i]) || "无") : "长度不符"));
    check("蓝色方最终阵容 5 人", head && head.blueCards === 5 && head.blueCount === "5 / 5 已选", head && head.blueCount);
    check("红色方最终阵容 5 人", head && head.redCards === 5 && head.redCount === "5 / 5 已选", head && head.redCount);
    check("蓝色方阵容英雄与原始数据一致", head && JSON.stringify(head.blueCardTitles.map(heroOf)) === JSON.stringify(picks(1).slice(0, 5)), head && head.blueCardTitles.map(heroOf).join(","));
    check("红色方阵容英雄与原始数据一致", head && JSON.stringify(head.redCardTitles.map(heroOf)) === JSON.stringify(picks(2).slice(0, 5)), head && head.redCardTitles.map(heroOf).join(","));
    check("双方 Ban 位与原始数据一致",
      head && JSON.stringify(head.blueBanTitles) === JSON.stringify(bans(1)) && JSON.stringify(head.redBanTitles) === JSON.stringify(bans(2)),
      head && ("蓝 " + head.blueBanTitles.join(",") + " / 红 " + head.redBanTitles.join(",")));
    check("默认进入最终阵容", head && head.step === battle.bp.length + " / " + battle.bp.length, head && head.step);
    check("前几局英雄使用有记录", head && head.prior === "此前 " + (c.seq - 1) + " 局" && head.prevTeams === 2,
      head && (head.prior + " / " + head.prevTeams + " 队"));
    check("赛后三项统计已渲染", head && head.stats === 3, head && head.stats);
    check("深链指向正确的比赛与对局",
      head && head.detail === "match.html?id=" + c.mid && head.gameLink === "game.html?id=" + bid,
      head && (head.detail + " | " + head.gameLink));
    check("反馈条不是错误态", head && !/失败/.test(head.feedback), head && head.feedback.slice(0, 40));
    const imgBad = head ? head.imgs.filter((x) => x.src && x.w === 0) : [];
    check("英雄/战队图标全部加载", imgBad.length === 0, imgBad.slice(0, 3).map((x) => x.src).join(" | "));

    // 交互：逐手回放 / 步进 / 滑块 / 深链
    await evaluate(`document.querySelector("#draftMode").click()`);
    const draft0 = await evaluate(`(function(){return {step:document.querySelector("#stepText").textContent, cards:document.querySelectorAll(".studio-card.filled").length, count:document.querySelector("#bluePickCount").textContent};})()`);
    check("切到逐手回放后回到第 0 手", draft0 && draft0.step === "0 / " + battle.bp.length && draft0.cards === 0 && draft0.count === "0 / 5 已选",
      draft0 && (draft0.step + " / " + draft0.cards));

    // 逐手推进 5 步
    for (let i = 0; i < 5; i++) await evaluate(`document.querySelector("#nextBtn").click()`);
    const step5 = await evaluate(`(function(){
      return {step:document.querySelector("#stepText").textContent,
              cards:document.querySelectorAll(".studio-card.filled").length,
              url:location.search};
    })()`);
    const picksAt5 = battle.bp.slice(0, 5).filter((x) => Number(x[1]) === 1).length;
    check("步进 5 手后状态正确", step5 && step5.step === "5 / " + battle.bp.length && step5.cards === picksAt5,
      step5 && (step5.step + " / 卡片 " + step5.cards + " / 期望 " + picksAt5));
    check("回放深链写入 step/mode", step5 && /step=5/.test(step5.url) && /mode=draft/.test(step5.url), step5 && step5.url);

    await evaluate(`(function(){var r=document.querySelector("#stepRange");r.value="10";r.dispatchEvent(new Event("input",{bubbles:true}));})()`);
    const slider = await evaluate(`document.querySelector("#stepText").textContent`);
    check("滑块跳到第 10 手", slider === "10 / " + battle.bp.length, slider);

    await evaluate(`document.querySelector('#bpActions button[data-step="3"]').click()`);
    const clickStep = await evaluate(`document.querySelector("#stepText").textContent`);
    check("点时间线跳到第 3 手", clickStep === "3 / " + battle.bp.length, clickStep);
    await evaluate(`document.querySelector("#prevBtn").click()`);
    const prev = await evaluate(`document.querySelector("#stepText").textContent`);
    check("上一手回退到第 2 手", prev === "2 / " + battle.bp.length, prev);
    await evaluate(`document.querySelector("#startBtn").click()`);
    const start = await evaluate(`document.querySelector("#stepText").textContent`);
    check("回到开始为第 0 手", start === "0 / " + battle.bp.length, start);
    await evaluate(`document.querySelector("#endBtn").click()`);
    const end = await evaluate(`document.querySelector("#stepText").textContent`);
    check("跳回最终阵容", end === battle.bp.length + " / " + battle.bp.length, end);

    // 播放/暂停
    await evaluate(`(function(){var s=document.querySelector("#speedSelect");s.value="600";s.dispatchEvent(new Event("change",{bubbles:true}));document.querySelector("#draftMode").click();document.querySelector("#playBtn").click();})()`);
    await sleep(1000);
    const playing = await evaluate(`document.querySelector("#stepText").textContent`);
    await evaluate(`document.querySelector("#playBtn").click()`);
    check("自动播放能推进且可暂停", playing && Number(playing.split(" ")[0]) > 0, playing);

    // 切到本场第 1 局
    await evaluate(`(function(){var s=document.querySelector("#gameSelect");s.selectedIndex=0;s.dispatchEvent(new Event("change",{bubbles:true}));})()`);
    await sleep(1600);
    const g1 = await evaluate(`(function(){return {step:document.querySelector("#stepText").textContent, actions:document.querySelectorAll("#bpActions .studio-action").length, ctx:document.querySelector("#matchContext").textContent};})()`);
    const o1 = oracle(c.mid, 1);
    check("对局切换后重新载入且回到最终阵容", g1 && g1.step === o1.battle.bp.length + " / " + o1.battle.bp.length && g1.actions === o1.battle.bp.length,
      g1 && (g1.step + " / " + g1.actions));

    // 搜索
    await evaluate(`(function(){var i=document.querySelector("#matchQuery");i.value="狼队";i.dispatchEvent(new Event("input",{bubbles:true}));})()`);
    await sleep(500);
    const search = await evaluate(`(function(){var o=Array.prototype.map.call(document.querySelectorAll("#matchSelect option"),function(x){return x.textContent});return {n:o.length, all:o.every(function(t){return t.indexOf("狼队")>=0})};})()`);
    check("搜索狼队后结果全部命中", search && search.n > 0 && search.all, search && (search.n + " 条 / all=" + search.all));

    // 响应式：375 / 768
    for (const w of [768, 390]) {
      await visit(`bp-studio.html?match=${c.mid}&g=${c.seq}`, w, 900, 1800);
      const lay = await evaluate(`(function(){
        var d=document.documentElement, b=document.body;
        var r=function(s){var e=document.querySelector(s);if(!e)return null;var x=e.getBoundingClientRect();return {l:x.left,r:x.right,w:x.width}};
        return {sw:Math.max(d.scrollWidth,b.scrollWidth), iw:window.innerWidth,
                arena:r(".studio-arena"), work:r(".studio-workbench"), filters:r(".studio-filters"),
                actions:document.querySelectorAll("#bpActions .studio-action").length,
                cards:document.querySelectorAll("#blueLineup .studio-card.filled, #redLineup .studio-card.filled").length};
      })()`);
      check(`${w}px 无横向溢出`, lay && lay.sw <= lay.iw + 1, lay && (lay.sw + " / " + lay.iw));
      check(`${w}px 主区块仍在视口内`, lay && lay.arena && lay.arena.l >= -1 && lay.arena.r <= lay.iw + 1 && lay.work && lay.work.r <= lay.iw + 1,
        lay && (JSON.stringify(lay.arena) + " " + JSON.stringify(lay.work)));
      check(`${w}px BP 与阵容正常渲染`, lay && lay.actions === battle.bp.length && lay.cards === 10, lay && (lay.actions + " 手 / " + lay.cards + " 卡"));
      check(`${w}px 无 JS 异常`, errors.length === 0, errors.join(" | "));
    }
  }

  // ---- 2. 入口链接 ----
  console.log("\n=== 入口链接 ===");
  await visit("bp.html", 1440, 1000, 1600);
  const bpLink = await evaluate(`(function(){var a=document.querySelector('a[href="bp-studio.html"]');return a?{href:a.getAttribute("href"),text:a.textContent.trim()}:null;})()`);
  check("BP 分析页有演播室入口", !!bpLink, bpLink && bpLink.text);

  const g7 = CASES[0];
  const o7 = oracle(g7.mid, g7.seq);
  await visit("game.html?id=" + o7.bid, 1440, 1000, 2200);
  const gameLink = await evaluate(`(function(){var a=document.querySelector('a[href*="bp-studio.html?match="]');return a?{href:a.getAttribute("href"),text:a.textContent.trim()}:null;})()`);
  check("对局详情有带 match/g 的演播室入口",
    !!gameLink && gameLink.href.includes("match=" + g7.mid) && gameLink.href.includes("g=" + g7.seq),
    gameLink && gameLink.href);

  // ---- 3. 无效参数回退 ----
  await visit("bp-studio.html?match=999999999&g=99", 1440, 1000, 1800);
  const fallback = await evaluate(`(function(){return {ctx:document.querySelector("#matchContext").textContent, actions:document.querySelectorAll("#bpActions .studio-action").length, fb:document.querySelector("#studioFeedback").textContent};})()`);
  check("无效 match/g 回退到最近一场而不是报错", fallback && fallback.actions > 0 && !/失败/.test(fallback.fb),
    fallback && (fallback.ctx + " / " + fallback.actions));

  // ---- 4. 请求没有完整 BP 的小局：不静默换局 ----
  await visit("bp-studio.html?match=2026091201&g=7", 1440, 1000, 2000);
  const partial = await evaluate(`(function(){
    return {fb:document.querySelector("#studioFeedback").textContent,
            actions:document.querySelectorAll("#bpActions .studio-action").length,
            step:document.querySelector("#stepText").textContent,
            url:location.search,
            game:document.querySelector("#gameSelect").value};
  })()`);
  check("请求无完整 BP 的第 7 局时明确提示并展示可用局",
    partial && /第 7 局没有完整 BP/.test(partial.fb) && /已展示第 \d+ 局/.test(partial.fb) && partial.actions > 0,
    partial && partial.fb.slice(0, 80));
  check("回退后的深链与下拉框指向真实展示的小局",
    partial && /g=\d+/.test(partial.url) && !/g=7/.test(partial.url) && !!partial.game,
    partial && (partial.url + " / " + partial.game));

  console.log("\n" + (bad ? "FAILED " + bad + " 项：" + fail.join("；") : "ALL PASS"));
  proc.kill();
  process.exit(bad ? 1 : 0);
}

main().catch((e) => { console.log("FAIL 脚本异常：" + e.stack); process.exit(1); });
