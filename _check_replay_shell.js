// 复盘工作台：拖动时不再重建 DOM 的结构性检查
// 说明：完整验证需要真实浏览器（节点身份、指针捕获）。这里做的是"代码形状"回归：
// 一旦有人把 paint() 改回 el.innerHTML = ...，或者让 input 回调走 renderShell，就会红。
const fs = require("fs");
const path = require("path");

const src = fs.readFileSync(path.join(__dirname, "assets", "replay.js"), "utf8");

let bad = 0;
const check = (name, ok, extra) => {
  if (!ok) bad++;
  console.log((ok ? "PASS " : "FAIL ") + name + (extra ? "  → " + extra : ""));
};

// 1) 语法可加载
let mod;
const window = {};
try {
  new Function("window", "fetch", "document", src)(window, () => {}, {});
  mod = window.KPL_REPLAY;
  check("replay.js 可加载并导出 mount", !!(mod && typeof mod.mount === "function"));
} catch (e) {
  check("replay.js 可加载并导出 mount", false, e.message);
}

// 2) 抽出 paint / renderShell / bind 三段函数体
function body(name) {
  const i = src.indexOf("function " + name + "(");
  if (i < 0) return "";
  let depth = 0, started = false;
  for (let j = i; j < src.length; j++) {
    const c = src[j];
    if (c === "{") { depth++; started = true; }
    else if (c === "}") { depth--; if (started && depth === 0) return src.slice(i, j + 1); }
  }
  return "";
}

const paintBody = body("paint");
const shellBody = body("renderShell");
const bindBody = body("bind");

check("paint() 存在", paintBody.length > 0);
check("paint() 不写 el.innerHTML", paintBody.length > 0 && !/el\.innerHTML\s*=/.test(paintBody));
check("renderShell() 是唯一重建外壳的地方", /el\.innerHTML\s*=/.test(shellBody));

// 3) 滑块 input 回调必须走 paint，不能走 renderShell
const inputLine = (bindBody.match(/addEventListener\("input"[\s\S]*?\}\);/g) || []).join("");
check("input 回调调用 paint()", /paint\(\)/.test(inputLine), inputLine.slice(0, 80));
check("input 回调不调用 renderShell()", !/renderShell\(\)/.test(inputLine));
check("input 回调不调用 draw()", !/\bdraw\(\)/.test(inputLine));

// 4) 全文不应再有 draw() 调用残留
check("无 draw() 残留调用", !/\bdraw\(\)\s*;/.test(src));

// 5) 事件按钮只切 class，不重建
check("事件高亮用 classList.toggle", /classList\.toggle\("on"/.test(paintBody));

console.log("\npaint() 长度 " + paintBody.split("\n").length + " 行 · renderShell() " +
  shellBody.split("\n").length + " 行");
process.exit(bad ? 1 : 0);
