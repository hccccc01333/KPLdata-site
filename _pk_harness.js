
const fs = require("fs"), path = require("path"), vm = require("vm");
const SITE = process.argv[2], PAGE = process.argv[3];
const captured = {};
function el(id) {
  const o = { innerHTML: "", textContent: "", value: "", style: {}, checked: false,
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    setAttribute(){}, getAttribute(){ return null; }, addEventListener(){}, appendChild(){}, insertAdjacentHTML(){},
    querySelector(){ return null; }, querySelectorAll(){ return []; }, remove(){}, focus(){}, children: [] };
  return o;
}
const documentStub = {
  getElementById(id){ if (!captured["#"+id]) captured["#"+id] = el(id); return captured["#"+id]; },
  querySelector(sel){ if (!captured[sel]) captured[sel] = el(sel); return captured[sel]; },
  querySelectorAll(){ return []; }, createElement(){ return el("new"); }, addEventListener(){},
  body:{ getAttribute(){ return PAGE; }, appendChild(){}, classList:{add(){},remove(){},toggle(){}} }, head:{ appendChild(){} },
};
const sandbox = { console, setTimeout, clearTimeout, setInterval: ()=>0, clearInterval, Date, JSON, Math, Number, String,
  parseInt, parseFloat, encodeURIComponent, decodeURIComponent, Promise, URLSearchParams, Object, Array, isFinite,
  document: documentStub, localStorage:{ getItem(){ return null; }, setItem(){} }, history:{ replaceState(){} } };
sandbox.window = sandbox; sandbox.location = { search: "", pathname: PAGE };
sandbox.matchMedia = () => ({ matches:false, addEventListener(){}, addListener(){} });
sandbox.IntersectionObserver = function(){ return { observe(){}, unobserve(){}, disconnect(){} }; };
sandbox.requestAnimationFrame = (cb)=>setTimeout(cb,0);
sandbox.addEventListener = ()=>{}; sandbox.removeEventListener = ()=>{};
sandbox.fetch = () => Promise.resolve({ ok:false, status:404, json: () => Promise.resolve({}) });
vm.createContext(sandbox);
Object.assign(globalThis, { window: sandbox, document: documentStub, location: sandbox.location });
const html = fs.readFileSync(path.join(SITE, PAGE), "utf8");
[...html.matchAll(/<script src="(assets\/[^"?]+)[^"]*"><\/script>/g)].map(m=>m[1])
  .forEach(function (rel) { try { vm.runInContext(fs.readFileSync(path.join(SITE, rel), "utf8"), sandbox, {filename:rel}); } catch(e){ console.log("load fail", rel, e.message); } });
const inline = html.match(/<script>([\s\S]*?)<\/script>/);
try {
  vm.runInContext(inline[1], sandbox, {filename: PAGE});
  var g = function (k) { var n = captured[k]; return n ? (n.innerHTML || n.textContent || "") : "(missing)"; };
  console.log(JSON.stringify({
    picked: g("#pkPicked"), note: g("#pkNote"),
    rules: g("#pkRules").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 160),
    firstCard: g("#pickGrid").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 240),
    cardCount: (g("#pickGrid").match(/pick-card/g) || []).length,
    hasDeepLink: g("#pickGrid").indexOf("&m=") >= 0
  }, null, 1));
} catch (e) { console.log("RENDER ERROR:", e && e.message); }
process.exit(0);
