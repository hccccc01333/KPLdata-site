
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SITE = process.argv[2];
const HERO = process.argv[3];

const captured = {};
function el(id) {
  return {
    innerHTML: "", textContent: "", style: {}, classList: { add(){}, remove(){}, toggle(){}, contains(){return false;} },
    setAttribute(){}, getAttribute(){ return null; }, addEventListener(){}, appendChild(){},
    querySelector(){ return null; }, querySelectorAll(){ return []; }, remove(){},
    get children(){ return []; },
    get value(){ return ""; }, set value(v){},
  };
}
const documentStub = {
  getElementById(id) { captured[id] = el(id); return captured[id]; },
  querySelector(sel) { captured[sel] = el(sel); return captured[sel]; },
  querySelectorAll() { return []; },
  createElement() { return el("created"); },
  addEventListener() {},
  body: { getAttribute(){ return "heroes.html"; }, appendChild(){}, classList:{add(){},remove(){},toggle(){}} },
  head: { appendChild(){} },
};

function loadFile(rel) {
  const src = fs.readFileSync(path.join(SITE, rel), "utf8");
  vm.runInThisContext(src, { filename: rel });
}

const sandbox = {
  console, setTimeout, clearTimeout, setInterval, clearInterval, Date, JSON, Math, Number, String,
  parseInt, parseFloat, URLSearchParams, encodeURIComponent,
  document: documentStub,
  localStorage: { getItem(){ return null; }, setItem(){} },
};
sandbox.window = sandbox;
sandbox.matchMedia = function () { return { matches: false, addEventListener(){}, addListener(){} }; };
sandbox.IntersectionObserver = function () { return { observe(){}, unobserve(){}, disconnect(){} }; };
sandbox.requestAnimationFrame = function (cb) { return setTimeout(cb, 0); };
sandbox.addEventListener = function () {};
sandbox.removeEventListener = function () {};
sandbox.location = { search: "?id=" + encodeURIComponent(HERO), href: "" };
vm.createContext(sandbox);
Object.assign(globalThis, { window: sandbox.window, document: documentStub, localStorage: sandbox.localStorage });
globalThis.location = sandbox.location;

function evalIn(rel) {
  const src = fs.readFileSync(path.join(SITE, rel), "utf8");
  vm.runInContext(src, sandbox, { filename: rel });
}

evalIn("assets/seasons.js");
evalIn("assets/details.js");
evalIn("assets/players_detail.js");
evalIn("assets/data.js");
evalIn("assets/common.js");

const html = fs.readFileSync(path.join(SITE, "hero.html"), "utf8");
const m = html.match(/<script>([\s\S]*?)<\/script>/);
if (!m) throw new Error("no inline script");
try {
  vm.runInContext(m[1], sandbox, { filename: "hero.html:inline" });
  const head = captured["#heroHead"] ? captured["#heroHead"].innerHTML : "";
  const main = captured["#main"] ? captured["#main"].innerHTML : "";
  console.log(JSON.stringify({
    hero: HERO,
    headLen: head.length,
    mainLen: main.length,
    hasKPI: head.indexOf("hd-name") >= 0,
    mainSample: main.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").slice(0, 180),
    hasTrendPanel: main.indexOf("逐年表现") >= 0,
    hasBoundaryNote: main.indexOf("数据边界") >= 0,
  }, null, 1));
} catch (e) {
  console.log("RENDER ERROR:", e && e.message);
  process.exitCode = 1;
}
