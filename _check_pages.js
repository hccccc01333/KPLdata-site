// 站点浏览器验收：真实 Edge（CDP），不是静态看 HTML
//
// 三条硬性规则：
//   1. 任何页面出现未捕获 JS 异常或未处理 Promise 拒绝 → 整体失败
//      （比"HTML 里有容器"可靠得多：一个 null 引用就能让整段内联脚本静默停摆）
//   2. 核心区块必须真的渲染出节点，不是空壳
//   3. 390 / 768 / 1440 三个宽度下首页与复盘页都不能报错、不能横向溢出
//
// 用法：
//   python -m http.server 8777   # 先起本地服务（run_in_background）
//   node _check_pages.js [http://127.0.0.1:8777]
//   node _check_pages.js https://kpldata-site.hccccc01333.workers.dev   # 线上验收
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
  ["honors.html", "荣誉中心", ["#lanes .hn-lane", "#team .hn-team, #team .panel", "#boardRows tr"]],
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

  // 在页面脚本执行之前装好兜底监听：unhandledrejection 不会触发 Runtime.exceptionThrown，
  // 但同样会让页面静默停摆，必须单独捕获。
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

  async function visit(url, settle = 1400) {
    errors = [];
    await send("Page.navigate", { url });
    for (let i = 0; i < 40; i++) {
      await sleep(200);
      if (await evaluate("document.readyState === 'complete'")) break;
    }
    await sleep(settle);
    const unhandled = await evaluate("window.__kplUnhandled || []");
    return errors.concat(Array.isArray(unhandled) ? unhandled : []);
  }

  console.log("=== 逐页：未捕获异常 / 未处理 Promise 拒绝 + 关键区块渲染 ===");
  for (const [path, label, sels] of PAGES) {
    const errs = await visit(BASE + path);
    const counts = await evaluate(
      "(" + JSON.stringify(sels) + ").map(function(s){ return document.querySelectorAll(s).length; })"
    );
    const rendered = Array.isArray(counts) && counts.some((n) => n > 0);
    check(label + " 无 JS 异常", errs.length === 0, errs.slice(0, 2).join(" | "));
    check(label + " 关键区块已渲染", rendered, Array.isArray(counts) ? counts.join("/") : String(counts));
  }

  console.log("\n=== 首页构成（C 方案：赛事焦点，无宣传轮播）===");
  await visit(BASE + "index.html", 1600);
  const home = await evaluate(`(function(){
    var q = function(s){ return document.querySelectorAll(s).length; };
    var hero = document.getElementById('focusHero');
    var pickHref = (document.querySelector('#replayPicks a') || {}).getAttribute
      ? document.querySelector('#replayPicks a').getAttribute('href') : '';
    return {
      dome: q('#dome'), slide: q('.slide, .carousel, [data-slide]'),
      hero3d: !![].slice.call(document.scripts).find(function(s){ return /hero3d|three/.test(s.src); }),
      focusChildren: hero ? hero.children.length : 0,
      focusMatchLinks: q('#focusHero a[href*="match.html"]'),
      focusHasScore: /\\d+\\s*[:：]\\s*\\d+/.test(hero ? hero.textContent : '') ||
                     /已结束|待开赛|直播中|进行中/.test(hero ? hero.textContent : ''),
      picks: q('#replayPicks .rp-pick'), pickHref: pickHref || '',
      teams: q('#stTop tr'), heroes: q('#heroTop > *'), players: q('#plTop > *'),
      tools: q('.entry'),
      heroHTML: hero ? hero.innerHTML.length : 0
    };
  })()`);
  check("已删除 3D 穹顶容器 #dome", home && home.dome === 0, home && home.dome);
  check("已删除宣传轮播节点", home && home.slide === 0, home && home.slide);
  check("页面不再加载 hero3d/three", home && home.hero3d === false, home && home.hero3d);
  check("首屏焦点卡有内容", home && home.focusChildren > 0, home && home.focusChildren);
  check("首屏有可点的比赛链接", home && home.focusMatchLinks > 0, home && home.focusMatchLinks);
  check("首屏显示真实比分或状态", home && home.focusHasScore === true, home && home.focusHasScore);
  check("精选复盘卡片真实生成", home && home.picks > 0, home && home.picks);
  check("精选复盘直达比赛详情", home && /match\.html/.test(home.pickHref), home && home.pickHref);
  check("三榜真实生成", home && home.teams > 0 && home.heroes > 0 && home.players > 0,
    home && home.teams + "/" + home.heroes + "/" + home.players);
  check("分析工具入口存在", home && home.tools > 0, home && home.tools);

  // 行为断言：不自动切换。3.5 秒内焦点卡 HTML 必须逐字节不变
  // （实时比分 30s 才刷新一次，3.5s 内变化只可能来自轮播定时器）
  const before = await evaluate("document.getElementById('focusHero').innerHTML");
  await sleep(3500);
  const after = await evaluate("document.getElementById('focusHero').innerHTML");
  check("首屏 3.5s 内不自动切换", before === after,
    before === after ? "稳定" : "内容发生变化 → 仍有自动轮播");

  console.log("\n=== 导航链路：搜索 → 对象详情 → 比赛 → 复盘 ===");
  await visit(BASE + "index.html", 1500);
  await evaluate(`(function(){
    var i = document.getElementById('siteSearch');
    i.value = '狼队';
    i.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await sleep(900);
  const sr = await evaluate(`(function(){
    var as = document.querySelectorAll('#searchPop a');
    var first = as[0];
    return { n: as.length, href: first ? first.getAttribute('href') : '', text: first ? first.textContent : '' };
  })()`);
  check("搜索出结果", sr && sr.n > 0, sr && sr.n);
  check("搜索结果指向对象详情页", sr && /^(team|player|hero|match)\.html\?id=/.test(sr.href || ""), sr && sr.href);

  // 点进搜索结果，再从详情里找一场比赛
  if (sr && sr.href) {
    await visit(BASE + sr.href, 1500);
    const det = await evaluate(`(function(){
      var a = document.querySelector('a[href^="match.html"]');
      return { detailOK: document.querySelectorAll('#main .panel, .panel, .page-hero').length,
               matchHref: a ? a.getAttribute('href') : '' };
    })()`);
    check("对象详情页渲染成功", det && det.detailOK > 0, det && det.detailOK);
    check("详情页可继续进入比赛", det && !!det.matchHref, det && det.matchHref);
    if (det && det.matchHref) {
      // 走真实深链：比赛页必须能落到复盘滑块
      await visit(BASE + det.matchHref, 1800);
      const m = await evaluate(`(function(){
        return { panels: document.querySelectorAll('#main .panel').length,
                 hasReplay: !!document.getElementById('rpRange'),
                 tabs: document.querySelectorAll('.rp-tab').length };
      })()`);
      check("比赛页渲染成功", m && m.panels > 0, m && m.panels);
    }
  }
  // 复盘深链（已知有分钟级数据的场次）
  await visit(BASE + "match.html?id=2026062603&g=3&m=13", 1800);
  const deep = await evaluate(`(function(){
    var r = document.getElementById('rpRange');
    return { hasSlider: !!r, value: r ? Number(r.value) : -1,
             time: (document.getElementById('rpTime') || {}).textContent || '' };
  })()`);
  check("复盘深链落到指定分钟", deep && deep.hasSlider && deep.value > 0, deep && deep.value + " · " + deep.time);

  console.log("\n=== 复盘交互（拖动 / 键盘 / 切局 / 点曲线 / 分享）===");
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

  const clickRes = await evaluate(`(function(){
    var chart = document.getElementById('rpChart');
    var r = document.getElementById('rpRange');
    if (!chart || !r) return { err: 'no chart/slider' };
    var before = Number(r.value);
    var rect = chart.getBoundingClientRect();
    chart.dispatchEvent(new MouseEvent('click', { bubbles: true,
      clientX: rect.left + rect.width * 0.75, clientY: rect.top + rect.height / 2 }));
    var after = Number(document.getElementById('rpRange').value);
    return { before: before, after: after, sameNode: document.getElementById('rpRange') === r };
  })()`);
  check("点击曲线跳到对应分钟", clickRes && clickRes.after !== clickRes.before && clickRes.after > clickRes.before,
    clickRes ? clickRes.before + " → " + clickRes.after : "n/a");

  const shareBefore = await evaluate("(document.getElementById('rpShare')||{}).textContent || ''");
  await evaluate("(function(){var s=document.getElementById('rpShare'); if(s) s.click();})()");
  // clipboard.writeText 是 Promise，点完立刻读只能读到旧文本——必须等一拍再断言
  await sleep(500);
  const shareAfter = await evaluate("(document.getElementById('rpShare')||{}).textContent || ''");
  check("分享按钮产出本帧链接", shareAfter && shareAfter !== shareBefore &&
    (/已复制/.test(shareAfter) || /http/.test(shareAfter) || /match\.html|\?id=/.test(shareAfter)),
    shareAfter.slice(0, 70));

  console.log("\n=== 响应式：390 / 768 / 1440 ===");
  for (const w of [390, 768, 1440]) {
    await send("Emulation.setDeviceMetricsOverride", { width: w, height: 900, deviceScaleFactor: 1, mobile: w < 500 });
    const e1 = await visit(BASE + "index.html");
    const nav = await evaluate("(function(){var h=document.getElementById('siteHeader');return h?h.getBoundingClientRect().height:0;})()");
    check(w + "px 首页无异常", e1.length === 0, e1.slice(0, 2).join(" | "));
    check(w + "px 导航可见", nav > 0, nav);
    // 导航可达性：≤900px 走汉堡抽屉，必须真的能展开且抽屉里有赛事/复盘入口。
    // 只看"顶栏高度 > 0"是不够的——toggle 的 JS 坏了的话导航就等于不存在。
    const drawer = await evaluate(`(function(){
      var tg = document.querySelector('.nav-toggle');
      var nav = document.getElementById('siteNav');
      if (!nav) return { err: 'no nav' };
      if (!tg || getComputedStyle(tg).display === 'none') {
        return { mode: 'inline', links: nav.querySelectorAll('a').length,
                 toMatch: nav.querySelectorAll('a[href*="match.html"],a[href*="picks.html"],a[href*="schedule.html"]').length };
      }
      tg.click();
      var open = nav.classList.contains('open');
      var r = { mode: 'drawer', open: open, links: nav.querySelectorAll('a').length,
                toMatch: nav.querySelectorAll('a[href*="match.html"],a[href*="picks.html"],a[href*="schedule.html"]').length };
      tg.click();
      return r;
    })()`);
    if (drawer && drawer.mode === "drawer") {
      check(w + "px 汉堡导航可展开", drawer.open === true && drawer.links > 0,
        drawer.open + " · " + drawer.links + " 条");
      check(w + "px 抽屉含赛事/复盘入口", drawer.toMatch > 0, drawer.toMatch);
    } else {
      check(w + "px 横排导航含赛事/复盘入口", drawer && drawer.toMatch > 0, drawer && drawer.toMatch);
    }
    const mobile = await evaluate(`(function(){
      var de = document.documentElement;
      var over = de.scrollWidth - window.innerWidth;
      var focus = document.querySelector('#focusHero a[href*="match.html"]');
      var fr = focus ? focus.getBoundingClientRect() : null;
      var pick = document.querySelector('#replayPicks a');
      var pr = pick ? pick.getBoundingClientRect() : null;
      return { over: over,
               focusVisible: !!(fr && fr.width > 0 && fr.height > 0 && fr.right <= window.innerWidth + 1),
               pickVisible: !!(pr && pr.width > 0 && pr.height > 0 && pr.right <= window.innerWidth + 1) };
    })()`);
    check(w + "px 无横向溢出", mobile && mobile.over <= 1, mobile && mobile.over + "px");
    check(w + "px 首屏比赛入口在视口内", mobile && mobile.focusVisible === true, mobile && mobile.focusVisible);
    check(w + "px 复盘入口在视口内", mobile && mobile.pickVisible === true, mobile && mobile.pickVisible);
    const e2 = await visit(BASE + "match.html?id=2026062603&g=3&m=13");
    check(w + "px 复盘页无异常", e2.length === 0, e2.slice(0, 2).join(" | "));
    const mOver = await evaluate("document.documentElement.scrollWidth - window.innerWidth");
    check(w + "px 复盘页无横向溢出", mOver <= 1, mOver + "px");
    // 赛事中心：4 层媒体中心（海报/赛段进程/赛季横滑）不能把页面撑出横向溢出
    const e3 = await visit(BASE + "schedule.html");
    check(w + "px 赛程页无异常", e3.length === 0, e3.slice(0, 2).join(" | "));
    const sOver = await evaluate(`(function(){
      var de = document.documentElement;
      var bad = ['evPoster','stageTrack','seasonRail'].filter(function(id){
        var el = document.getElementById(id);
        return el && el.getBoundingClientRect().right > window.innerWidth + 1;
      }).join(',');
      var ons = document.querySelectorAll('#stageTrack .st-step.on');
      return { over: de.scrollWidth - window.innerWidth, bad: bad, onN: ons.length,
               onText: ons.length ? ons[0].textContent.replace(/\\s+/g, ' ').trim().slice(0, 26) : '' };
    })()`);
    check(w + "px 赛程页无横向溢出", sOver && sOver.over <= 1, sOver && sOver.over + "px");
    check(w + "px 赛程页媒体组件在视口内", sOver && !sOver.bad, sOver && ("越界:" + (sOver.bad || "—")));
    check(w + "px 赛段进程标出唯一当前赛段", sOver && sOver.onN === 1, sOver && sOver.onText);
    // 荣誉中心：五路数据条 + 候选榜不能撑出横向溢出，且必须高亮「荣誉」分组
    const e4 = await visit(BASE + "honors.html");
    check(w + "px 荣誉中心无异常", e4.length === 0, e4.slice(0, 2).join(" | "));
    const hOver = await evaluate(`(function(){
      var de = document.documentElement;
      var bad = ['lanes','team','boardRows'].filter(function(id){
        var el = document.getElementById(id);
        return el && el.getBoundingClientRect().right > window.innerWidth + 1;
      }).join(',');
      var g = document.querySelectorAll('#siteNav .ngrp.on');
      return { over: de.scrollWidth - window.innerWidth, bad: bad,
               lanes: document.querySelectorAll('#lanes .hn-lane').length,
               onN: g.length, onHref: g.length ? g[0].querySelector('a.ntop').getAttribute('href') : '' };
    })()`);
    check(w + "px 荣誉中心无横向溢出", hOver && hOver.over <= 1, hOver && hOver.over + "px");
    check(w + "px 荣誉中心五路数据条已渲染", hOver && hOver.lanes === 5, hOver && hOver.lanes);
    check(w + "px 荣誉中心高亮荣誉入口", hOver && hOver.onN === 1 && hOver.onHref === 'honors.html',
      hOver && (hOver.onN + " " + hOver.onHref));
  }
  await send("Emulation.clearDeviceMetricsOverride");

  console.log("\n=== V5 六入口分组导航 ===");
  await visit(BASE + "index.html", 900);
  const navSix = await evaluate(`(function(){
    var nav = document.getElementById('siteNav');
    var g = nav ? nav.querySelectorAll('.ngrp') : [];
    var hrefs = [].map.call(g, function (x) { return x.querySelector('a.ntop').getAttribute('href'); });
    return { n: g.length, hrefs: hrefs,
             sub: nav ? nav.querySelectorAll('.nsub a').length : 0,
             honorsIdx: hrefs.indexOf('honors.html'),
             on: nav ? nav.querySelectorAll('.ngrp.on').length : -1 };
  })()`);
  check("顶部导航为六组入口", navSix && navSix.n === 6, navSix && navSix.n + " · " + navSix.hrefs.join("/"));
  check("六入口含荣誉中心", navSix && navSix.honorsIdx >= 0, navSix && navSix.hrefs.join("/"));
  check("首页只高亮一个分组", navSix && navSix.on === 1, navSix && navSix.on);
  check("分组含下拉子项", navSix && navSix.sub >= 8, navSix && navSix.sub);

  ws.close();
  proc.kill();
  await sleep(300);
  try { fs.rmSync(require("os").tmpdir() + "\\kpl-edge-check", { recursive: true, force: true }); } catch (e) {}

  console.log("\n" + (bad ? "=== 失败 " + bad + " 项 ===" : "=== 全部通过 ==="));
  if (bad) console.log("失败项：" + fail.join(" / "));
  process.exit(bad ? 1 : 0);
}

main().catch((e) => { console.log("FAIL 运行异常:", e.message); process.exit(1); });
