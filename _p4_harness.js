
const fs = require("fs"), path = require("path"), vm = require("vm");
const SITE = process.argv[2];
const captured = {};
function el(id) {
  const o = { innerHTML: "", textContent: "", value: "", style: {}, checked: false,
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    setAttribute(){}, getAttribute(){ return null; }, addEventListener(){}, appendChild(){}, insertAdjacentHTML(){},
    querySelector(){ return null; }, querySelectorAll(){ return []; }, remove(){}, focus(){}, children: [],
    getBoundingClientRect(){ return { left: 0, width: 1000 }; } };
  return o;
}
const documentStub = {
  getElementById(id){ if (!captured["#"+id]) captured["#"+id] = el(id); return captured["#"+id]; },
  querySelector(sel){ if (!captured[sel]) captured[sel] = el(sel); return captured[sel]; },
  querySelectorAll(){ return []; }, createElement(){ return el("new"); }, addEventListener(){},
  body:{ getAttribute(){ return "match.html"; }, appendChild(){}, classList:{add(){},remove(){},toggle(){}} },
  head:{ appendChild(){} },
};
const sandbox = { console, setTimeout, clearTimeout, setInterval: ()=>0, clearInterval, Date, JSON, Math, Number, String,
  parseInt, parseFloat, encodeURIComponent, decodeURIComponent, Promise, URLSearchParams, Object, Array, isFinite,
  document: documentStub, localStorage:{ getItem(){ return null; }, setItem(){} }, history:{ replaceState(){} },
  navigator: { clipboard: null } };
sandbox.window = sandbox;
sandbox.location = { search: "?id=2026101701", pathname: "match.html", origin: "https://x", href: "" };
sandbox.matchMedia = () => ({ matches:false, addEventListener(){}, addListener(){} });
sandbox.IntersectionObserver = function(){ return { observe(){}, unobserve(){}, disconnect(){} }; };
sandbox.requestAnimationFrame = (cb)=>setTimeout(cb,0);
sandbox.addEventListener = ()=>{}; sandbox.removeEventListener = ()=>{};
sandbox.fetch = function (url) {
  const rel = String(url).replace(/\?.*$/, "");
  const p = path.join(SITE, rel);
  return Promise.resolve({ ok: fs.existsSync(p), status: fs.existsSync(p) ? 200 : 404,
    json: () => Promise.resolve(JSON.parse(fs.readFileSync(p, "utf8"))) });
};
vm.createContext(sandbox);
Object.assign(globalThis, { window: sandbox, document: documentStub, location: sandbox.location });
function evalIn(rel){ vm.runInContext(fs.readFileSync(path.join(SITE, rel), "utf8"), sandbox, { filename: rel }); }
["assets/seasons.js","assets/data.js","assets/details.js","assets/coverage.js","assets/replay/index.js","assets/common.js","assets/replay.js"].forEach(evalIn);

// 1) 徽标：4 项
const b1 = sandbox.KPL.coverageBadges(7);
const b2 = sandbox.KPL.coverageBadges(31);
const cnt = (s) => (s.match(/cov-i/g) || []).length;
console.log(JSON.stringify({
  badgeItems_mask7: cnt(b1), badgeItems_mask31: cnt(b2),
  hasModelWord: b2.indexOf("模型") >= 0,
  mask31_sample: b2.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()
}, null, 1));

// 2) 复盘工作台：初始分钟 + 分享按钮
const box = el("box");
box.querySelectorAll = () => [];
box.querySelector = () => null;
sandbox.KPL_REPLAY.mount(box, { matchId: "2026101701", battleId: "", initialMinute: 12 });
setTimeout(function () {
  const html = box.innerHTML || "";
  const txt = html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
  console.log(JSON.stringify({
    rendered: html.length > 0,
    hasShare: html.indexOf("rpShare") >= 0,
    minutePick: (txt.match(/第 \d+′ \/ \d+′/) || ["?"])[0],
    hasEvidence: txt.indexOf("事件证据摘要") >= 0
  }, null, 1));
  process.exit(0);
}, 400);
