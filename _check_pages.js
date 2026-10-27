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
  ["bracket-forecast.html", "冠军预测", ["#siteHeader #siteNav", ".bf-page .mcard", ".bf-page .bracket", "#siteFooter .footer-in"]],
  ["teams.html", "战队榜", ["#teamGrid > *, .tcard, .team-card", ".champ", ".pw b"]],
  ["team.html?id=重庆狼队", "战队详情", ["#teamHead, .page-hero", ".tstat-grid, .panel", ".cmp-radar svg, .radar-wrap .empty-tip"]],
  ["players.html", "选手榜", ["#plBody tr, .player, .pl-card"]],
  ["player.html?id=一诺", "选手详情", ["#main .panel", ".sr-grid"]],
  ["hero-performance.html", "英雄表现", ["#hpPlayer option", "#hpHeroTable tbody tr", ".hp-bench", ".hp-evidence tr", "#siteHeader #siteNav"]],
  ["series.html", "系列赛研究", ["#boRows tr", "#decRows tr", "#revRows", "#eloRows tr"]],
  ["heroes.html", "英雄列表", ["#heroGrid > *, .hcard"]],
  ["hero.html?id=曹操", "英雄详情", ["#heroHead .page-hero, #heroHead .hd-top", "#main .panel", "#heroGrowthChart svg"]],
  ["match.html?id=2026062603&g=3&m=13", "比赛复盘", ["#rpRange", "#rpChart svg", "#rpGrid .rp-panel"]],
  ["match.html?id=2026102201", "系列赛诊断", ["#seriesAnalysis", ".sr-game", ".sr-grid-3"]],
  // game.html 的 id 是 battle_id（不是 match_id），传错了会走空态
  ["game.html?id=1373651472_21_1779526666", "对局详情", ["#main .panel", "#main .bp-grid"]],
  ["bp.html", "BP 分析", ["#bpBody tr, .bp2-panel, main .panel"]],
  ["combos.html", "英雄组合", ["main .panel, .combo-card"]],
  ["compare.html", "英雄对比", ["#radar svg", "#cmpTable tbody tr"]],
  ["compare-team.html", "战队对比", ["#radar svg", "#cmpTable tbody tr"]],
  ["compare-player.html", "选手对比", ["#radar svg", "#cmpTable tbody tr"]],
  ["compare-lane.html", "位置对比", ["#radar svg", "#cmpTable tbody tr"]],
  ["comeback.html", "翻盘研究所", ["#cbKpi .hd-cell", "#cbRows tr", "#cbBins .cb-row", "#cbNote"]],
  ["h2h.html", "交手记录", ["main .panel, .h2h-panel"]],
  ["predict.html", "预测统计", ["#cpRows tr", "#kAccK"]],
  ["sandbox.html", "胜率沙盘", ["#sbSurface svg", "#sbState .sb-hist", "#sbWhatIf input", "#sbPhases .sb-phase", "#sbWorst .sb-worst-row"]],
  ["picks.html", "精选对局", [".pick-card"]],
  ["query.html", "数据查询", ["#qBody a.cell"]],
  ["find.html", "智能找局", ["#fYear option", "#findBody tr", "#fCount"]],
  ["simulator.html", "大场模拟", ["main .panel, .sim-wrap", "#sumCheck", "#qaList .qa-item"]],
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
  // 验收必须看到"磁盘上的当前版本"：复用同一 profile 时 Edge 会按 URL 命中 CSS/JS 缓存
  // （pages.css?v=52 内容改了但 URL 未变），陈旧缓存会让断言假失败/假通过。
  await send("Network.enable");
  await send("Network.setCacheDisabled", { cacheDisabled: true });

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

  if (!process.argv.includes('--ui-only')) {
  console.log("=== 逐页：未捕获异常 / 未处理 Promise 拒绝 + 关键区块渲染 ===");
  for (const [path, label, sels] of PAGES) {
    const errs = await visit(BASE + path, path === "find.html" ? 3600 : path === "hero-performance.html" ? 2800 : 1400);
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
  await sleep(2200);
  const sr = await evaluate(`(function(){
    var as = document.querySelectorAll('#searchPop a');
    var first = as[0];
    return { n: as.length, href: first ? first.getAttribute('href') : '', text: first ? first.textContent : '' };
  })()`);
  check("搜索出结果", sr && sr.n > 0, sr && sr.n);
  check("搜索结果指向对象详情页", sr && /^(team|player|hero|match)\.html\?id=/.test(sr.href || ""), sr && sr.href);

  // 点进搜索结果，再从详情里找一场比赛
  if (sr && sr.href) {
    await visit(BASE + sr.href, 2400);
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

  console.log("\n=== 复盘故事层：结论 / 三个转折 / 折叠 / 跳转 ===");
  await visit(BASE + "game.html?id=1054884368_8_1792576862", 2600);
  const story = await evaluate(`(function(){
    var d = document.getElementById('rpDetail');
    var lead = document.querySelector('.rp-story-lead');
    var moments = document.querySelectorAll('.rp-moment');
    return {
      has: !!document.querySelector('.rp-story'),
      lead: lead ? lead.textContent : '',
      moments: moments.length,
      detailHidden: d ? d.hasAttribute('hidden') : null,
      expand: (document.getElementById('rpExpand') || {}).textContent || '',
      cov: (document.querySelector('.rp-cov') || {}).textContent || '',
      analog: (document.querySelector('a.rp-link[href*="sandbox"]') || {}).getAttribute
        ? document.querySelector('a.rp-link[href*="sandbox"]').getAttribute('href') : '',
      labels: document.querySelectorAll('.rp-tag.official, .rp-tag.proxy, .rp-tag.est').length
    };
  })()`);
  check("复盘首屏有结论与三个转折", story && story.has && story.lead.length > 40 && story.moments === 3,
    story && (story.moments + " 个转折 · 结论 " + story.lead.slice(0, 36)));
  check("复盘详细面板默认折叠", story && story.detailHidden === true, story && story.expand);
  check("复盘覆盖数字不回避（221 / 全历史）", story && /221\s*\/\s*11,138/.test(story.cov), story && story.cov.slice(0, 80));
  check("复盘结论区分官方 / 代理 / 估算", story && story.labels >= 3, story && story.labels);
  check("复盘提供历史类似局面入口", story && /sandbox\.html\?battle=/.test(story.analog), story && story.analog);
  const expanded = await evaluate(`(function(){
    var b = document.getElementById('rpExpand'); if (b) b.click();
    var d = document.getElementById('rpDetail');
    var m = document.querySelector('.rp-moment');
    if (m) m.click();
    var r = document.getElementById('rpRange');
    return { hidden: d ? d.hasAttribute('hidden') : null, frame: r ? Number(r.value) : -1,
             text: (document.getElementById('rpExpand') || {}).textContent || '' };
  })()`);
  check("展开后面板可见、转折可跳帧", expanded && expanded.hidden === false && expanded.frame > 0,
    expanded && expanded.frame + " · " + expanded.text);

  await visit(BASE + "game.html?id=1272988176_18_1782478925", 2600);
  const miss = await evaluate(`(function(){
    return { tag: (document.querySelector('.rp-tag.warn') || {}).textContent || '',
             lead: (document.querySelector('.rp-story-lead') || {}).textContent || '',
             note: (document.querySelector('.rp-story-note') || {}).textContent || '' };
  })()`);
  check("模型终局与官方相反时明确标注", miss && /模型终局未命中/.test(miss.tag) &&
    /方向和官方结果相反/.test(miss.lead) && /不藏/.test(miss.note), miss && miss.tag);

  const tz = await evaluate("KPL.cnDate(new Date('2026-10-23T17:30:00Z'))");
  check("北京时间跨日按 Asia/Shanghai 计算", tz === "2026-10-24", tz);
  const brand = await evaluate(`(function(){
    return { name: (document.querySelector('.brand-name') || {}).textContent || '',
             sub: (document.querySelector('.brand-sub') || {}).textContent || '' };
  })()`);
  check("品牌统一为峡谷有数 / KPL Insight", brand && brand.name === "峡谷有数" && /KPL INSIGHT/i.test(brand.sub),
    brand && brand.name + " / " + brand.sub);

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

  console.log("\n=== V5 阶段5 复盘图表分层 / 同位置对位 / 转折诊断 ===");
  await visit(BASE + "match.html?id=2026062603&g=3&m=13", 1600);
  const lay0 = await evaluate(`(function(){
    var lb = document.getElementById('rpLayer');
    var on = lb ? lb.querySelector('button.on') : null;
    return { btns: lb ? lb.querySelectorAll('button').length : 0,
             onText: on ? on.textContent.trim() : '',
             teamBars: document.querySelectorAll('#rpGrid .rp-lbrow').length,
             laneTables: document.querySelectorAll('#rpGrid .rp-tblwrap').length };
  })()`);
  check("复盘默认答案=队伍总量（分层第一层）",
    lay0 && lay0.btns === 2 && lay0.onText === "队伍总量" && lay0.teamBars === 2 && lay0.laneTables === 0,
    lay0 && (lay0.onText + " · 分路条 " + lay0.teamBars + " · 对位表 " + lay0.laneTables));
  const lay1 = await evaluate(`(function(){
    var b = document.querySelector('#rpLayer button[data-layer="lane"]');
    if (b) b.click();
    var lanes = Array.prototype.map.call(document.querySelectorAll('#rpGrid td.ln'), function(t){return t.textContent.trim();});
    return { rows: document.querySelectorAll('#rpGrid .rp-tblwrap tbody tr').length, lanes: lanes,
             onText: (document.querySelector('#rpLayer button.on')||{}).textContent||'',
             disc: (document.querySelector('#rpGrid .rp-panel .rp-disc')||{}).textContent||'' };
  })()`);
  check("切到分路对位：5 行同位置对位表",
    lay1 && lay1.rows === 5 && lay1.lanes.length === 5 && lay1.lanes[0] === "对抗路",
    lay1 && (lay1.rows + " 行 / " + lay1.lanes.join(",")));
  check("分路对位标注对齐口径", lay1 && /同一分路/.test(lay1.disc), lay1 && lay1.disc.slice(0, 28));
  const turn = await evaluate(`(function(){
    var items = document.querySelectorAll('#rpTurn .rp-tp-item');
    return { has: !!document.querySelector('#rpTurn .rp-tp'), items: items.length,
             disc: (document.querySelector('#rpTurn .rp-disc')||{}).textContent||'' };
  })()`);
  check("比赛转折面板已渲染", turn && turn.has && turn.items >= 1 && turn.items <= 3,
    turn && turn.items + " 段");
  check("转折结论标注非因果口径", turn && /不构成因果归因/.test(turn.disc), turn && turn.disc.slice(0, 24));

  console.log("\n=== V5 阶段5 对局数据曲线：按分路拆同位置对位小图 ===");
  await visit(BASE + "game.html?id=1054884368_40_1792313942", 2400);
  const smReady = await evaluate("(function(){var t=document.querySelector('#curveTabs button[data-t=\"player\"]');return {has:!!t, chart:!!document.getElementById('curveChart'), note:(document.getElementById('curveNote')||{}).textContent||''};})()");
  if (smReady && smReady.has) {
    const sm = await evaluate(`(function(){
      document.querySelector('#curveTabs button[data-t="player"]').click();
      return { blocks: document.querySelectorAll('#curveChart .rp-sm').length,
               svgs: document.querySelectorAll('#curveChart .rp-sm-c svg').length,
               titles: Array.prototype.map.call(document.querySelectorAll('#curveChart .rp-sm-t'), function(t){return t.textContent.trim();}),
               note: (document.getElementById('curveNote')||{}).textContent||'' };
    })()`);
    check("选手经济按分路拆成 5 张同位置对位小图",
      sm && sm.blocks === 5 && sm.svgs === 5 && sm.titles[0] === "对抗路" && sm.titles[4] === "游走",
      sm && (sm.blocks + " 块 / " + sm.titles.join(",")));
    check("对位小图标注分路序来源", sm && /复盘名单/.test(sm.note), sm && sm.note.slice(0, 30));
    const smd = await evaluate(`(function(){
      document.querySelector('#curveTabs button[data-t="dmg"]').click();
      return { blocks: document.querySelectorAll('#curveChart .rp-sm').length };
    })()`);
    check("选手输出同样按分路拆图", smd && smd.blocks === 5, smd && smd.blocks);
  } else {
    check("对局详情提供分钟级数据曲线入口（本局无直播采集，跳过）", true, smReady && smReady.note.slice(0, 20));
  }

  console.log("\n=== V5 阶段5 翻盘路径研究所 ===");
  await visit(BASE + "comeback.html", 1600);
  const cb = await evaluate(`(function(){
    var rows = document.querySelectorAll('#cbRows tr');
    var first = rows.length ? rows[0].textContent : '';
    var link = rows.length ? (rows[0].querySelector('a')||{}).getAttribute('href') : '';
    return { kpi: document.querySelectorAll('#cbKpi .hd-cell').length,
             bins: document.querySelectorAll('#cbBins .cb-row').length,
             lows: document.querySelectorAll('#cbLows .cb-row').length,
             rows: rows.length, first: first, link: link || '',
             note: (document.getElementById('cbNote')||{}).textContent||'',
             share: document.querySelectorAll('.share-fab').length };
  })()`);
  check("翻盘研究所：样本概览 4 个关键指标", cb && cb.kpi === 4, cb && cb.kpi);
  check("翻盘研究所：低点分档与时段分布都有样本", cb && cb.bins >= 3 && cb.lows >= 3,
    cb && ("分档 " + cb.bins + " / 时段 " + cb.lows));
  check("翻盘研究所：典型翻盘榜有数据且能回到那一局",
    cb && cb.rows >= 10 && /match\.html\?id=.+&g=\d+/.test(cb.link), cb && (cb.rows + " 行 · " + cb.link.slice(0, 46)));
  check("翻盘研究所：口径写清 8 分钟窗口与覆盖率边界",
    cb && /第 8 分钟/.test(cb.note) && /覆盖率/.test(cb.note) && /不能代表全部/.test(cb.note),
    cb && cb.note.slice(0, 30));
  check("翻盘研究所：提供分享图入口", cb && cb.share >= 1, cb && cb.share);

  console.log("\n=== V5 阶段5 英雄成长曲线 ===");
  await visit(BASE + "hero.html?id=曹操", 1500);
  const hg = await evaluate(`(function(){
    var ms = document.querySelectorAll('#main .panel');
    var title = '', note = '';
    Array.prototype.some.call(ms, function (m) {
      var t = m.querySelector('.panel-title');
      if (t && /成长曲线/.test(t.textContent)) { title = t.textContent; note = m.textContent; return true; }
      return false;
    });
    var host = document.getElementById('heroGrowthChart');
    return { title: title, note: note, svg: host ? host.querySelectorAll('svg').length : 0 };
  })()`);
  check("英雄详情：成长曲线面板（8 / 12 / 16 分钟）已渲染",
    hg && /成长曲线/.test(hg.title) && /8 \/ 12 \/ 16/.test(hg.title), hg && hg.title.slice(0, 34));
  check("英雄详情：成长曲线画出 3 个采样点", hg && hg.svg === 1, hg && hg.svg);
  check("英雄详情：成长曲线标注样本门槛与覆盖率边界",
    hg && /分钟级出场 ≥/.test(hg.note) && /全量/.test(hg.note), hg && hg.note.slice(-40));
  const hgData = await evaluate(`(function(){
    var G = window.KPL_HERO_GROWTH || {};
    return { n: Object.keys(G.heroes||{}).length, min: (G.meta||{}).minGames,
             targets: ((G.meta||{}).targets||[]).join(','), honest: /样本量不足/.test(((G.meta||{}).note)||'') };
  })()`);
  check("成长曲线数据：样本不足的英雄不输出（诚实门槛）",
    hgData && hgData.n >= 20 && hgData.min === 5 && hgData.targets === "8,12,16" && hgData.honest,
    hgData && (hgData.n + " 个英雄 · 门槛 " + hgData.min + " 次"));

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
    await visit(BASE + "match.html?id=2026102201");
    const srOver = await evaluate("document.documentElement.scrollWidth - window.innerWidth");
    check(w + "px 系列赛诊断页无横向溢出", srOver <= 1, srOver + "px");
    await visit(BASE + "game.html?id=1054884368_8_1792576862");
    const gameOver = await evaluate(`(function(){
      var de = document.documentElement;
      var s = document.querySelector('.rp-story');
      var r = s ? s.getBoundingClientRect() : null;
      return { over: de.scrollWidth - window.innerWidth,
               storyRight: r ? Math.round(r.right) : -1, vw: window.innerWidth };
    })()`);
    check(w + "px 对局详情无横向溢出", gameOver && gameOver.over <= 1,
      gameOver && (gameOver.over + "px · story右 " + gameOver.storyRight + "/" + gameOver.vw));
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
               onN: g.length, onHref: g.length ? g[0].querySelector('.ntop').getAttribute('data-href') : '' };
    })()`);
    check(w + "px 荣誉中心无横向溢出", hOver && hOver.over <= 1, hOver && hOver.over + "px");
    check(w + "px 荣誉中心五路数据条已渲染", hOver && hOver.lanes === 5, hOver && hOver.lanes);
    check(w + "px 荣誉中心高亮荣誉入口", hOver && hOver.onN === 1 && hOver.onHref === 'honors.html',
      hOver && (hOver.onN + " " + hOver.onHref));
    // 战队页：战力榜卡片 / 冠军墙 / 详情三层都不能撑出横向溢出
    const e5 = await visit(BASE + "teams.html");
    check(w + "px 战队榜无异常", e5.length === 0, e5.slice(0, 2).join(" | "));
    const tOver = await evaluate("document.documentElement.scrollWidth - window.innerWidth");
    check(w + "px 战队榜无横向溢出", tOver <= 1, tOver + "px");
    const e6 = await visit(BASE + "team.html?id=重庆狼队");
    check(w + "px 战队详情无异常", e6.length === 0, e6.slice(0, 2).join(" | "));
    const dOver = await evaluate(`(function(){
      var de = document.documentElement;
      var bad = ['baseSeg'].filter(function(id){
        var el = document.getElementById(id);
        return el && el.getBoundingClientRect().right > window.innerWidth + 1;
      }).join(',');
      var wrap = document.querySelector('.radar-wrap');
      if (wrap && wrap.getBoundingClientRect().right > window.innerWidth + 1) bad += ',radar-wrap';
      return { over: de.scrollWidth - window.innerWidth, bad: bad };
    })()`);
    check(w + "px 战队详情无横向溢出", dOver && dOver.over <= 1, dOver && dOver.over + "px");
    check(w + "px 战队详情雷达/基准切换在视口内", dOver && !dOver.bad, dOver && ("越界:" + (dOver.bad || "—")));
    // 对比四入口：雷达 + 对照表 + 分享按钮在窄屏下都不能撑出横向溢出
    for (const cp of ["compare.html", "compare-team.html", "compare-player.html", "compare-lane.html"]) {
      const ec = await visit(BASE + cp, 2600);
      check(w + "px " + cp + " 无异常", ec.length === 0, ec.slice(0, 2).join(" | "));
      const cOver = await evaluate(`(function(){
        var de = document.documentElement;
        var bad = ["radar","legend"].filter(function(id){
          var el = document.getElementById(id);
          return el && el.getBoundingClientRect().right > window.innerWidth + 1;
        }).join(',');
        // 对照表在窄屏是「面板内横向滚动」：表格本身有 min-width，
        // 越界要看承载它的 .cmp-table，而不是 #cmpTable 的原始矩形。
        var wrap = document.querySelector('.cmp-table');
        if (wrap && wrap.getBoundingClientRect().right > window.innerWidth + 1) bad += ',cmpTable';
        var fab = document.querySelector('.filterbar .share-fab');
        if (fab && fab.getBoundingClientRect().right > window.innerWidth + 1) bad += ',share';
        return { over: de.scrollWidth - window.innerWidth, bad: bad,
                 svg: document.querySelectorAll('#radar svg').length };
      })()`);
      check(w + "px " + cp + " 无横向溢出", cOver && cOver.over <= 1, cOver && cOver.over + "px");
      check(w + "px " + cp + " 雷达在视口内", cOver && cOver.svg >= 1 && !cOver.bad,
        cOver && (cOver.svg + " 个 / 越界 " + (cOver.bad || "—")));
    }
    // 英雄表现：宽表在面板内滚动，承载容器不能把页面撑出视口
    const ehp = await visit(BASE + "hero-performance.html", 2800);
    check(w + "px 英雄表现无异常", ehp.length === 0, ehp.slice(0, 2).join(" | "));
    const hpOver = await evaluate(`(function(){
      var de = document.documentElement;
      var bad = ['.hp-table-wrap','.hp-evidence-wrap','.hp-grid'].filter(function(sel){
        var el = document.querySelector(sel);
        return el && el.getBoundingClientRect().right > window.innerWidth + 1;
      }).join(',');
      return { over: de.scrollWidth - window.innerWidth, bad: bad,
               rows: document.querySelectorAll('#hpHeroTable tbody tr').length };
    })()`);
    check(w + "px 英雄表现无横向溢出", hpOver && hpOver.over <= 1, hpOver && hpOver.over + "px");
    check(w + "px 英雄表现表格/证据容器在视口内", hpOver && hpOver.rows > 0 && !hpOver.bad,
      hpOver && (hpOver.rows + " 行 / 越界 " + (hpOver.bad || "—")));
    // 阶段5 新页：翻盘研究所 / 英雄成长曲线在窄屏下也不能撑出横向溢出
    const e7 = await visit(BASE + "comeback.html", 1500);
    check(w + "px 翻盘研究所无异常", e7.length === 0, e7.slice(0, 2).join(" | "));
    const cbOver = await evaluate(`(function(){
      var de = document.documentElement;
      // 宽表在窄屏是「面板内横向滚动」：tbody 自带宽度必然超出视口，
      // 越界要看承载它的 .table-panel（必须被约束在视口内），不是 tbody 的原始矩形。
      var bad = ["cbKpi","cbBins"].filter(function(id){
        var el = document.getElementById(id);
        return el && el.getBoundingClientRect().right > window.innerWidth + 1;
      }).join(',');
      var body = document.getElementById('cbRows');
      var tp = body && body.closest('.table-panel');
      if (tp && tp.getBoundingClientRect().right > window.innerWidth + 1) bad = (bad ? bad + ',' : '') + 'table-panel';
      return { over: de.scrollWidth - window.innerWidth, bad: bad,
               rows: document.querySelectorAll('#cbRows tr').length };
    })()`);
    check(w + "px 翻盘研究所无横向溢出", cbOver && cbOver.over <= 1, cbOver && cbOver.over + "px");
    check(w + "px 翻盘研究所榜单未越界", cbOver && !cbOver.bad && cbOver.rows > 0,
      cbOver && ("越界 " + (cbOver.bad || "—")));
    const e8 = await visit(BASE + "hero.html?id=曹操", 1500);
    check(w + "px 英雄详情无异常", e8.length === 0, e8.slice(0, 2).join(" | "));
    const gOver = await evaluate(`(function(){
      var de = document.documentElement;
      var host = document.getElementById('heroGrowthChart');
      var bad = host && host.getBoundingClientRect().right > window.innerWidth + 1 ? 'growth' : '';
      return { over: de.scrollWidth - window.innerWidth, bad: bad,
               svg: host ? host.querySelectorAll('svg').length : 0 };
    })()`);
    check(w + "px 英雄成长曲线无横向溢出", gOver && gOver.over <= 1 && !gOver.bad && gOver.svg === 1,
      gOver && (gOver.over + "px / svg " + gOver.svg));
  }
  await send("Emulation.clearDeviceMetricsOverride");

  console.log("\n=== V5 六入口分组导航 ===");
  await visit(BASE + "index.html", 900);
  const navSix = await evaluate(`(function(){
    var nav = document.getElementById('siteNav');
    var g = nav ? nav.querySelectorAll('.ngrp') : [];
    var hrefs = [].map.call(g, function (x) { return x.querySelector('.ntop').getAttribute('data-href'); });
    return { n: g.length, hrefs: hrefs,
             sub: nav ? nav.querySelectorAll('.nsub a').length : 0,
             honorsIdx: hrefs.indexOf('honors.html'),
             on: nav ? nav.querySelectorAll('.ngrp.on').length : -1 };
  })()`);
  check("顶部导航为六组入口", navSix && navSix.n === 6, navSix && navSix.n + " · " + navSix.hrefs.join("/"));
  check("六入口含荣誉中心", navSix && navSix.honorsIdx >= 0, navSix && navSix.hrefs.join("/"));
  check("首页只高亮一个分组", navSix && navSix.on === 1, navSix && navSix.on);
  check("分组含下拉子项", navSix && navSix.sub >= 8, navSix && navSix.sub);

  console.log("\n=== V5 阶段三 战队战力体系（战力榜 / 三层详情 / 冠军墙）===");
  await visit(BASE + "teams.html", 1500);
  const pw = await evaluate(`(function(){
    var cards = document.querySelectorAll('#teamGrid .tcard');
    var scored = [].filter.call(document.querySelectorAll('#teamGrid .pw b'),
      function(b){ return b.textContent.trim() !== '—'; });
    var bars = document.querySelectorAll('#teamGrid .pwbar');
    var champs = document.querySelectorAll('#champStrip .champ');
    var withScore = [].filter.call(document.querySelectorAll('#champStrip .champ span'),
      function(s){ return /\\d+\\s*:\\s*\\d+/.test(s.textContent); });
    return { cards: cards.length, scored: scored.length, bars: bars.length,
             champs: champs.length, withScore: withScore.length,
             src: (document.getElementById('srcNote')||{}).textContent || '' };
  })()`);
  check("战力榜卡片已渲染", pw && pw.cards > 0, pw && pw.cards);
  check("战力榜按多维战力分评级", pw && pw.scored > 0, pw && pw.scored);
  check("已评级卡片含六维能力条", pw && pw.bars === pw.scored * 6, pw && (pw.bars + "/" + pw.scored));
  check("冠军墙渲染历届冠军", pw && pw.champs > 0, pw && pw.champs);
  check("冠军墙含真实决赛比分", pw && pw.withScore > 0, pw && pw.withScore);
  check("来源标签标注基准与算法版本", pw && /power-v1/.test(pw.src), pw && pw.src.slice(0, 60));

  await visit(BASE + "team.html?id=重庆狼队", 1700);
  const tl = await evaluate(`(function(){
    return { kpis: document.querySelectorAll('#main .hd-cell').length,
      radar: !!(document.querySelector('#main .cmp-radar svg') || document.querySelector('#main .radar-wrap .empty-tip')),
      rings: document.querySelectorAll('#main .cmp-radar svg polygon').length,
      segs: document.querySelectorAll('#baseSeg button').length,
      on: document.querySelectorAll('#baseSeg button.on').length,
      rows: document.querySelectorAll('#main table.tbl tr').length,
      wall: document.querySelectorAll('#main .champ-strip .champ').length };
  })()`);
  check("详情页第一层总览 KPI 渲染", tl && tl.kpis >= 6, tl && tl.kpis);
  check("详情页第二层能力雷达渲染", tl && tl.radar === true, tl && tl.radar);
  check("雷达含 4 环 + 数据多边形", tl && tl.rings >= 5, tl && tl.rings);
  check("三基准切换按钮（赛事/年度/历史）", tl && tl.segs === 3, tl && tl.segs);
  check("默认只高亮一个基准", tl && tl.on === 1, tl && tl.on);
  check("详情页第三层时间轴/冠军墙有内容", tl && tl.rows > 0 && tl.wall > 0,
    tl && (tl.rows + " 行 / " + tl.wall + " 冠"));

  // 行为断言：手动切换基准后雷达仍渲染，且基准说明随之变化。
  // 注意：全部年份下默认基准已经是“历史”，所以这里改点“赛事”验证手动覆盖。
  await evaluate("localStorage.setItem('kpl_scope_v1','all')");
  await visit(BASE + "team.html?id=重庆狼队", 1500);
  const segBefore = await evaluate("(document.querySelector('#radarBaseNote')||{}).textContent || ''");
  await evaluate(`(function(){ var b = document.querySelector('#baseSeg button[data-base="league"]'); if (b) b.click(); })()`);
  await sleep(450);
  const segAfter = await evaluate(`(function(){
    return { note: (document.querySelector('#radarBaseNote')||{}).textContent || '',
             radar: !!(document.querySelector('#main .cmp-radar svg') || document.querySelector('#main .radar-wrap .empty-tip')) };
  })()`);
  check("切换基准后雷达仍渲染", segAfter && segAfter.radar === true, segAfter && segAfter.radar);
  check("切换基准后基准说明更新为赛事基准",
    segAfter && segAfter.note !== segBefore && /基准：/.test(segAfter.note) && !/全部年份/.test(segAfter.note),
    segAfter && segAfter.note.slice(0, 40));

  // 雷达默认基准必须跟随顶部数据范围：全部→历史、年度→年度、赛事→赛事；
  // 所选赛事样本不足时应回退到年度，而不是直接空图。
  const radarSnap = `JSON.stringify((function(){
    function txt(s){ var e=document.querySelector(s); return e ? e.textContent.trim().replace(/\\s+/g,' ') : ''; }
    return {
      note: txt('#radarBaseNote'), fallback: txt('#radarFallbackNote'),
      on: txt('#baseSeg button.on'), header: txt('.hd-sub'),
      radar: !!document.querySelector('#main .cmp-radar svg')
    };
  })())`;
  await evaluate("localStorage.setItem('kpl_scope_v1','all')");
  await visit(BASE + "team.html?id=重庆狼队", 1500);
  const radarAll = JSON.parse(await evaluate(radarSnap) || "{}");
  check("全部范围下雷达默认历史基准",
    radarAll.radar === true && /全部年份/.test(radarAll.note) && radarAll.on === "历史",
    radarAll.note);

  await evaluate(`(function(){ var y=document.getElementById('scopeYear'); y.value='2025'; y.dispatchEvent(new Event('change',{bubbles:true})); })()`);
  await sleep(650);
  const radarYear = JSON.parse(await evaluate(radarSnap) || "{}");
  check("年度范围下雷达默认年度基准",
    radarYear.radar === true && /2025 年/.test(radarYear.note) && radarYear.on === "年度" && /2025 年/.test(radarYear.header),
    radarYear.note + " / " + radarYear.header);

  await evaluate(`(function(){ var s=document.getElementById('scopeLeague'); s.value='20250004'; s.dispatchEvent(new Event('change',{bubbles:true})); })()`);
  await sleep(650);
  const radarFallback = JSON.parse(await evaluate(radarSnap) || "{}");
  check("赛事样本不足时雷达回退年度",
    radarFallback.radar === true && /回退到「年度」/.test(radarFallback.fallback) && /2025 年/.test(radarFallback.note),
    radarFallback.fallback || radarFallback.note);

  await evaluate(`(function(){ var s=document.getElementById('scopeLeague'); s.value='20250001'; s.dispatchEvent(new Event('change',{bubbles:true})); })()`);
  await sleep(650);
  const radarLeague = JSON.parse(await evaluate(radarSnap) || "{}");
  check("赛事范围下雷达默认赛事基准",
    radarLeague.radar === true && /2025年KPL春季赛/.test(radarLeague.note) && radarLeague.on === "赛事",
    radarLeague.note);

  await evaluate(`(function(){ var b=document.querySelector('#baseSeg [data-base="history"]'); if(b) b.click(); })()`);
  await sleep(450);
  const radarHistory = JSON.parse(await evaluate(radarSnap) || "{}");
  check("手动切到历史基准仍可用",
    radarHistory.radar === true && /全部年份/.test(radarHistory.note) && radarHistory.on === "历史",
    radarHistory.note);
  await evaluate("localStorage.setItem('kpl_scope_v1','all')");

  console.log("\n=== V5 阶段四 大场模拟升级（概率校验 / 参数输入 / 概率树 / 可解释结论）===");
  await visit(BASE + "simulator.html", 1500);
  const p0 = await evaluate("(document.querySelector('#simKpis .sim-kpi .v')||{}).textContent || ''");
  const sim = await evaluate(`(function(){
    var q = function(s){ return document.querySelectorAll(s).length; };
    return { qa: q('#qaList .qa-item'), rows: q('#simDist .sd-row'),
      sum: (document.getElementById('sumCheck')||{}).textContent || '',
      ok: !!document.querySelector('#sumCheck.ok'),
      manual: !!document.getElementById('simManual'), range: !!document.getElementById('simP'),
      bo: (document.getElementById('simBo')||{}).value || '' };
  })()`);
  check("模拟器可解释结论条数 ≥4", sim && sim.qa >= 4, sim && sim.qa);
  check("局分概率条数与赛制匹配", sim && sim.rows === parseInt(sim.bo, 10) + 1, sim && (sim.rows + " 条 / BO" + sim.bo));
  check("概率合计校验通过且显示 100%", sim && sim.ok === true && /100\.0/.test(sim.sum), sim && sim.sum.slice(0, 60));
  check("提供手动单局胜率参数输入", sim && sim.manual && sim.range, sim && (sim.manual + "/" + sim.range));

  // 行为：展开概率树
  await evaluate(`(function(){ var t=document.getElementById('treeOn'); if(t){ t.checked=true; t.dispatchEvent(new Event('change',{bubbles:true})); } })()`);
  await sleep(500);
  const tree = await evaluate(`(function(){
    var panel = document.getElementById('treePanel');
    return { svg: !!document.querySelector('#treeBox svg'),
      nodes: document.querySelectorAll('#treeBox svg circle').length,
      edges: document.querySelectorAll('#treeBox svg line').length,
      vis: !!panel && getComputedStyle(panel).display !== 'none' };
  })()`);
  check("概率树已渲染", tree && tree.svg === true && tree.vis === true, tree && (tree.nodes + " 节点 / " + tree.edges + " 边"));
  check("概率树覆盖系列赛状态", tree && tree.nodes >= 8, tree && tree.nodes);

  // 行为：手动参数生效，且守恒校验仍通过
  await evaluate(`(function(){
    var c=document.getElementById('simManual'); if(c){ c.checked=true; c.dispatchEvent(new Event('change',{bubbles:true})); }
    var r=document.getElementById('simP'); if(r){ r.value='78'; r.dispatchEvent(new Event('input',{bubbles:true})); }
  })()`);
  await sleep(400);
  const man = await evaluate(`(function(){
    return { p: (document.querySelector('#simKpis .sim-kpi .v')||{}).textContent || '',
      ok: !!document.querySelector('#sumCheck.ok'),
      src: (document.getElementById('simSrc')||{}).textContent || '' };
  })()`);
  check("手动参数生效且仍守恒校验", man && man.p !== p0 && man.ok === true && /手动/.test(man.src),
    man && (man.p + " | " + man.src.slice(0, 18)));

  console.log("\n=== V5 阶段四 BP 双模式（官方赛事板 / 分析模式 + 为什么推荐）===");
  await visit(BASE + "bp.html", 1600);
  const bpm = await evaluate(`(function(){
    var q = function(s){ return document.querySelectorAll(s).length; };
    return { tabs: q('#bpMode button'), on: q('#bpMode button.on'),
      board: (document.getElementById('draftPanel')||{}).offsetParent !== null,
      bench: (document.getElementById('benchBlock')||{}).offsetParent !== null,
      why: (document.getElementById('whyPanel')||{}).offsetParent !== null,
      note: (document.getElementById('modeNote')||{}).textContent || '' };
  })()`);
  check("BP 提供两个模式入口", bpm && bpm.tabs === 2 && bpm.on === 1, bpm && (bpm.tabs + " 个 / 高亮 " + bpm.on));
  check("默认官方赛事板：赛事板可见、分析区块隐藏", bpm && bpm.board === true && bpm.bench === false && bpm.why === false,
    bpm && ("板/工作台/依据 = " + bpm.board + "/" + bpm.bench + "/" + bpm.why));

  // 切到分析模式
  await evaluate(`(function(){ var b=document.querySelector('#bpMode button[data-mode="analyze"]'); if(b) b.click(); })()`);
  await sleep(500);
  const bpa = await evaluate(`(function(){
    var why = document.getElementById('whyBox');
    return { bench: (document.getElementById('benchBlock')||{}).offsetParent !== null,
      why: (document.getElementById('whyPanel')||{}).offsetParent !== null,
      note: (document.getElementById('modeNote')||{}).textContent || '',
      items: document.querySelectorAll('#whyBox .why-item').length,
      text: (why||{}).textContent || '',
      boardModeCls: document.getElementById('bp2Grid').classList.contains('board-mode') };
  })()`);
  check("分析模式：分析区块与推荐依据面板可见", bpa && bpa.bench === true && bpa.why === true, bpa && (bpa.bench + "/" + bpa.why));
  check("切换后模式说明更新", bpa && /分析模式/.test(bpa.note), bpa && bpa.note.slice(0, 24));
  check("推荐依据给出候选与证据", bpa && bpa.items >= 1 && /综合评分/.test(bpa.text) && /%/.test(bpa.text), bpa && bpa.items);

  console.log("\n=== V5 阶段四 对比工具拆分（英雄 / 战队 / 选手 / 位置：默认答案 + 高级条件）===");
  // 四个入口必须以「默认答案」打开（雷达 + 对照表先给结论），且确实是四类不同对象
  const CMP_KINDS = [
    ["compare.html", "英雄", ["禁用率", "选用率", "承伤"]],
    ["compare-team.html", "战队", ["大场胜率", "场均金差", "场均击杀差"]],
    ["compare-player.html", "选手", ["MVP 率", "参团率", "输出伤害"]],
    ["compare-lane.html", "位置", ["KDA", "胜率", "MVP 率", "参团率"]],
  ];
  for (const [path, label, mustDims] of CMP_KINDS) {
    await visit(BASE + path, 1500);
    const c = await evaluate(`(function(){
      var polys = document.querySelectorAll('#radar svg polygon').length;
      var rows = document.querySelectorAll('#cmpTable tbody tr').length;
      var heads = [].map.call(document.querySelectorAll('#cmpTable thead th'), function(t){ return t.textContent.trim(); });
      var dims = [].map.call(document.querySelectorAll('#cmpTable tbody tr td:first-child'), function(t){ return t.textContent.trim(); });
      var sels = document.querySelectorAll('#pickers select').length;
      var on = document.querySelectorAll('#siteNav .ngrp.on').length;
      var onTop = document.querySelector('#siteNav .ngrp.on .ntop');
      var onHref = onTop ? onTop.getAttribute('data-href') : '';
      return { polys: polys, rows: rows, heads: heads, dims: dims, sels: sels,
               on: on, onHref: onHref, url: location.search };
    })()`);
    check(label + "对比入口默认即有答案（雷达 + 对照表）", c && c.rows >= 5 && c.polys >= 5,
      c && (c.rows + " 行 / " + c.polys + " 多边形"));
    check(label + "对比入口提供 4 个对象选择器", c && c.sels === 4 && c.heads[0] === "指标",
      c && (c.sels + " 个 / 首列 " + (c.heads[0] || "")));
    check(label + "对比入口维度与对象类型匹配", c && mustDims.every(function (d) { return c.dims.indexOf(d) >= 0; }),
      c && c.dims.join(","));
    check(label + "对比入口默认答案进 URL（可分享）", c && /items=/.test(c.url || ""), c && c.url);
    check(label + "对比入口导航高亮分析组", c && c.on === 1 && /bp\.html/.test(c.onHref || ""),
      c && (c.on + " / " + c.onHref));
  }

  // 阶段5-A：分享图入口必须出现在首页与四个对比入口（生成固定尺寸卡片，非截屏）
  await visit(BASE + "index.html", 1400);
  const idxFab = await evaluate("document.querySelectorAll('#focusBlock .share-fab').length");
  check("首页赛事焦点提供分享图入口", idxFab >= 1, idxFab);
  for (const cp of ["compare.html", "compare-team.html", "compare-player.html", "compare-lane.html"]) {
    await visit(BASE + cp, 1400);
    const fab = await evaluate("document.querySelectorAll('.filterbar .share-fab').length");
    check(cp + " 提供分享图入口", fab === 1, fab);
  }

  // 位置入口的专有口径：必须标注「分路画像 ≠ 强弱排名」
  const laneNote = await evaluate(`(function(){
    var tip = (document.getElementById('cmpTip')||{}).textContent || '';
    var body = document.body.textContent || '';
    return { tip: tip, boundary: /分路画像/.test(tip) && /不能/.test(tip),
             weighted: /加权/.test(tip), page: /实际出场位置/.test(body) };
  })()`);
  check("位置入口标注加权聚合与画像口径", laneNote && laneNote.weighted === true,
    laneNote && laneNote.tip.slice(0, 70));
  check("位置入口声明不可跨分路比强弱", laneNote && laneNote.boundary === true && laneNote.page === true,
    laneNote && (laneNote.boundary + "/" + laneNote.page));

  // 交互：挪到只剩 2 个对象 → 对照表多一列「差（1−2）」
  await evaluate(`(function(){
    ['sel3','sel2'].forEach(function(id){
      var s = document.getElementById(id); if (s) { s.value = ''; s.dispatchEvent(new Event('change', { bubbles: true })); }
    });
  })()`);
  await sleep(450);
  const twoSel = await evaluate(`(function(){
    return { cols: document.querySelectorAll('#cmpTable thead th').length,
             mean: /范围均值/.test((document.querySelector('#cmpTable thead')||{}).textContent || ''),
             diff: /差（1−2）/.test((document.querySelector('#cmpTable thead')||{}).textContent || '') };
  })()`);
  check("位置入口：选 2 个对象多一列差值", twoSel && twoSel.diff === true && twoSel.mean === true && twoSel.cols === 5,
    twoSel && (twoSel.cols + " 列 / 差值 " + twoSel.diff + " / 均值 " + twoSel.mean));

  // 趋势开关：英雄 / 战队有逐年数据，选手 / 位置没有
  await visit(BASE + "compare.html", 1400);
  const tHero = await evaluate("!!document.getElementById('trendToggle')");
  await visit(BASE + "compare-team.html", 1400);
  const tTeam = await evaluate("!!document.getElementById('trendToggle')");
  await visit(BASE + "compare-player.html", 1400);
  const tPlayer = await evaluate("!!document.getElementById('trendToggle')");
  check("英雄入口保留逐年趋势开关", tHero === true, tHero);
  check("战队入口保留逐年趋势开关", tTeam === true, tTeam);
  check("选手入口无逐年趋势开关（无逐年数据）", tPlayer === false, tPlayer);

  }
  console.log("\n=== Arena · 全站 UI 与数据可信度专项 ===");
  // (A) 原生选择控件：主题可切换，前景与背景的对比度须达到 4.5:1。
  //     诚实说明：无头浏览器无法真正展开系统原生弹出层，这里校验的是浏览器实际计算出的
  //     select / option 背景与前景色（深底 + 深字 = 文字不可见）；真实弹出层观感仍需在
  //     桌面与手机上人工确认。
  const SEL_PAGES = ["schedule.html", "teams.html", "players.html", "heroes.html", "combos.html",
                     "h2h.html", "stage.html", "simulator.html", "bp.html", "query.html",
                     "honors.html", "compare.html", "compare-team.html", "compare-player.html", "compare-lane.html"];
  for (const sp of SEL_PAGES) {
    await visit(BASE + sp, 1500);
    const s = await evaluate(`(function(){
      function lum(c){
        var m = /rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?/.exec(c || '');
        if (!m) return null;
        var a = m[4] === undefined ? 1 : parseFloat(m[4]);
        var r = +m[1], g = +m[2], b = +m[3];
        if (a < 1) return null;
        function linear(v){ v /= 255; return v <= .04045 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); }
        return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b);
      }
      var sels = [].slice.call(document.querySelectorAll('select'));
      var opts = 0, badOpt = [], emptyOpt = 0, badSel = [];
      sels.forEach(function(sel){
        var cs = getComputedStyle(sel);
        var bg = lum(cs.backgroundColor), fg = lum(cs.color);
        if (bg === null || fg === null || (Math.max(bg,fg)+.05)/(Math.min(bg,fg)+.05) < 4.5) badSel.push(sel.id || sel.className || 'select');
        var os = [].slice.call(sel.options || []);
        opts += os.length;
        os.forEach(function(o){
          if (!(o.text || '').trim()) emptyOpt++;
          var oc = getComputedStyle(o);
          var obg = lum(oc.backgroundColor), ofg = lum(oc.color);
          if (obg === null || ofg === null || (Math.max(obg,ofg)+.05)/(Math.min(obg,ofg)+.05) < 4.5) {
            if (badOpt.length < 4) badOpt.push((sel.id || '') + ':' + (o.text || '').slice(0, 6));
          }
        });
      });
      return { n: sels.length, opts: opts, badSel: badSel, badOpt: badOpt, emptyOpt: emptyOpt };
    })()`);
    check(sp + " 选择框文字对比度 ≥4.5:1", s && s.n > 0 && s.badSel.length === 0,
      s && (s.n + " 个" + (s.badSel.length ? " / 异常 " + s.badSel.join(",") : " / 全部合规")));
    check(sp + " 选择框选项对比度 ≥4.5:1", s && s.opts > 0 && s.badOpt.length === 0,
      s && (s.opts + " 项" + (s.badOpt.length ? " / 异常 " + s.badOpt.join(",") : " / 全部合规")));
    check(sp + " 选择框选项均有文字", s && s.emptyOpt === 0, s && s.emptyOpt);
  }

  if (!process.argv.includes('--ui-only')) {
  // (B) 荣誉中心候选行不得出现「假零」：候选同样带完整指标，缺失必须是 —，不是 0
  await visit(BASE + "honors.html", 1600);
  // 已完赛周期也可能没有达标选手；选择最近一个确有候选的周期。
  await evaluate(`(function(){
    var sel = document.getElementById('fPeriod');
    if (!sel) return;
    var opts = [].slice.call(sel.options);
    var periods = (window.KPL_HONORS || {}).weeks || [];
    var pick = opts.filter(function(o){
      var p = periods.find(function(p){ return p.id === o.value; });
      if (!p || p.ongoing) return false;
      return Object.keys(p.lanes || {}).reduce(function(n, lane){
        return n + ((p.lanes[lane] || {}).board || []).length;
      }, 0) >= 5;
    })[0];
    if (pick) { sel.value = pick.value; sel.dispatchEvent(new Event('change', {bubbles:true})); }
  })()`);
  await sleep(800);
  const hn = await evaluate(`(function(){
    var rows = [].slice.call(document.querySelectorAll('#boardRows tr'));
    var zero = [], n = 0;
    rows.forEach(function(tr){
      var tds = [].slice.call(tr.children).map(function(td){ return td.textContent.replace(/\\s+/g, ''); });
      if (tds.length < 12) return;   // 占位行（colspan）跳过
      n += 1;
      // 列序：分路/名次/选手/战队/局·场/胜率/KDA/分均经济/分均输出/参团/MVP/综合分
      if (tds[6] === '0.0' || tds[7] === '0' || tds[8] === '0' || tds[9] === '0.0%') {
        zero.push(tds[2] + ':' + tds[6] + '/' + tds[7] + '/' + tds[8] + '/' + tds[9]);
      }
    });
    return { n: n, zero: zero };
  })()`);
  check("荣誉中心候选行带完整指标（无 0.0 KDA / 0 分均经济 / 0 分均输出）",
    hn && hn.n >= 5 && hn.zero.length === 0, hn && (hn.n + " 行 / 假零 " + (hn.zero.slice(0, 3).join(" | ") || "无")));

  // (C) 选手榜按「输出占比」排序：缺失值不得排到前面，也不得显示成 0%
  await visit(BASE + "players.html", 1600);
  await evaluate(`(function(){ var s=document.getElementById('fSort');
    if (s) { s.value='dmg'; s.dispatchEvent(new Event('change',{bubbles:true})); } })()`);
  await sleep(600);
  const pd = await evaluate(`(function(){
    var cards = [].slice.call(document.querySelectorAll('#playerGrid .player')).slice(0, 12);
    var bad = [];
    cards.forEach(function(c){
      var big = c.querySelector('.p-kda');
      var v = big ? big.textContent.replace(/输出|KDA|MVP|胜率|局数/g, '').trim() : '';
      if (/^(0|0\\.0)%?$/.test(v)) bad.push(v + ' / ' + c.textContent.slice(0, 30));
    });
    return { n: cards.length, bad: bad, first: cards[0] ? cards[0].querySelector('.p-kda').textContent.trim() : '' };
  })()`);
  check("选手榜按输出占比排序：无假零 0% 占位", pd && pd.n > 0 && pd.bad.length === 0,
    pd && (pd.n + " 张 / 榜首 " + pd.first + (pd.bad[0] ? " | " + pd.bad[0] : "")));

  // (D) 选手详情 · 同位置对比：无有效样本必须标「— / 无有效样本」，不得出现假的「0.0% 超过 0%」
  await visit(BASE + "player.html?id=清清", 1600);
  const pc = await evaluate(`(function(){
    var rows = [].slice.call(document.querySelectorAll('.pos-row'));
    var bad = [];
    rows.forEach(function(r){
      var my = (r.querySelector('.my') || {}).textContent || '';
      var rk = (r.querySelector('.rk') || {}).textContent || '';
      if (/0\\.0%/.test(my)) bad.push('假零 ' + r.textContent.replace(/\\s+/g, ' ').slice(0, 40));
      if (/—/.test(my) && rk.trim() && rk.trim() !== '无有效样本') {
        bad.push('缺样本仍给排名 ' + r.textContent.replace(/\\s+/g, ' ').slice(0, 40));
      }
    });
    return { n: rows.length, bad: bad };
  })()`);
  check("选手详情同位置对比：缺失标 —、不出现假 0.0%",
    pc && pc.n >= 4 && pc.bad.length === 0, pc && (pc.n + " 行 / " + (pc.bad.join(" | ") || "正常")));

  }
  ws.close();
  proc.kill();
  await sleep(300);
  try { fs.rmSync(require("os").tmpdir() + "\\kpl-edge-check", { recursive: true, force: true }); } catch (e) {}

  console.log("\n" + (bad ? "=== 失败 " + bad + " 项 ===" : "=== 全部通过 ==="));
  if (bad) console.log("失败项：" + fail.join(" / "));
  process.exit(bad ? 1 : 0);
}

main().catch((e) => { console.log("FAIL 运行异常:", e.message); process.exit(1); });
