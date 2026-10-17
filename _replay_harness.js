
const fs = require("fs"), path = require("path"), vm = require("vm");
const SITE = process.argv[2], MATCH = process.argv[3];
const captured = {};
function el(id) {
  const o = {
    innerHTML: "", textContent: "", value: "0", style: {}, dataset: {},
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    setAttribute(){}, getAttribute(){ return null; }, addEventListener(){}, appendChild(){},
    querySelector(){ return null; }, querySelectorAll(){ return []; }, remove(){}, focus(){},
    getBoundingClientRect(){ return { left: 0, width: 1000 }; },
  };
  return o;
}
const documentStub = {
  getElementById(id) { captured["#" + id] = el(id); return captured["#" + id]; },
  querySelector(sel) { captured[sel] = el(sel); return captured[sel]; },
  querySelectorAll(){ return []; }, createElement(){ return el("new"); },
  addEventListener(){}, body: { getAttribute(){ return "match.html"; }, appendChild(){}, classList:{add(){},remove(){},toggle(){}} },
  head: { appendChild(){} },
};
const sandbox = {
  console, setTimeout, clearTimeout, setInterval: () => 0, clearInterval, Date, JSON, Math, Number, String,
  parseInt, parseFloat, encodeURIComponent, Promise, URLSearchParams,
  document: documentStub, localStorage: { getItem(){ return null; }, setItem(){} },
};
sandbox.window = sandbox;
sandbox.location = { search: "?id=" + MATCH, href: "" };
sandbox.matchMedia = () => ({ matches: false, addEventListener(){}, addListener(){} });
sandbox.IntersectionObserver = function(){ return { observe(){}, unobserve(){}, disconnect(){} }; };
sandbox.requestAnimationFrame = (cb) => setTimeout(cb, 0);
sandbox.addEventListener = () => {}; sandbox.removeEventListener = () => {};
sandbox.fetch = function (url) {
  const rel = String(url).replace(/\?.*$/, "").replace(/^assets\//, "assets/");
  const p = path.join(SITE, rel);
  return Promise.resolve({
    ok: fs.existsSync(p),
    status: fs.existsSync(p) ? 200 : 404,
    json: () => Promise.resolve(JSON.parse(fs.readFileSync(p, "utf8"))),
  });
};
vm.createContext(sandbox);
Object.assign(globalThis, { window: sandbox, document: documentStub, fetch: sandbox.fetch, location: sandbox.location });
function evalIn(rel) { vm.runInContext(fs.readFileSync(path.join(SITE, rel), "utf8"), sandbox, { filename: rel }); }

evalIn("assets/seasons.js");
evalIn("assets/details.js");
evalIn("assets/data.js");
evalIn("assets/common.js");
evalIn("assets/replay/index.js");
evalIn("assets/replay.js");

const MATCHID = MATCH;
sandbox.KPL_REPLAY.loadPackage(MATCHID, function () {});
const _orig = sandbox.fetch;
sandbox.__RP_DEBUG = true;
sandbox.fetch = function (u) { console.error("FETCH", u); return _orig(u).then(function (r) { console.error("RES", r.ok); return r; }); };
const box = { innerHTML: "" };
let done = false;
setTimeout(function () {
  try {
    sandbox.KPL_REPLAY.mount(box, { matchId: MATCH });
    console.log("MOUNT OK len=", (box.innerHTML || "").length);
  } catch (err) {
    console.log("MOUNT THROW:", String(err && err.message));
    console.log((err && err.stack || "").split("\n").slice(0, 6).join("\n"));
  }
}, 50);
setTimeout(function () {
  const html = box.innerHTML || "";
  const out = {
    rendered: html.length > 0,
    len: html.length,
    hasTabs: html.indexOf("rp-tab") >= 0,
    hasChart: html.indexOf("<svg") >= 0,
    hasRange: html.indexOf("rpRange") >= 0,
    hasGold: html.indexOf("经济状态") >= 0,
    hasResource: html.indexOf("资源控制") >= 0,
    hasEvidence: html.indexOf("事件证据摘要") >= 0,
    hasEvents: html.indexOf("rp-ev") >= 0,
    hasCausalDisclaimer: html.indexOf("不等于因果") >= 0,
    hasSourceLabel: html.indexOf("rp-src") >= 0,
    textSample: html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").slice(0, 260),
  };
  console.log(JSON.stringify(out, null, 1));
  process.exit(0);
}, 300);
