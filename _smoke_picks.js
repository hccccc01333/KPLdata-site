// 临时冒烟：DOM 桩跑 picks.html 的内联脚本，验证卡片数 / 规则面板 / 深链
const fs = require("fs");
const path = require("path");

const html = fs.readFileSync(path.join(__dirname, "picks.html"), "utf8");
const blocks = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)];
if (!blocks.length) throw new Error("未找到内联脚本");
const code = blocks[blocks.length - 1][1];

function el() {
  return {
    _html: "", _text: "", children: [], classList: { toggle() {} },
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    set textContent(v) { this._text = v; }, get textContent() { return this._text; },
    addEventListener() {}, closest() { return null; },
  };
}
const nodes = {};
const document = {
  querySelector(sel) { return (nodes[sel] = nodes[sel] || el()); },
};
const window = { get KPL_PICKS() { return KPL_PICKS; } };

// picks.js
const picksRaw = fs.readFileSync(path.join(__dirname, "assets", "picks.js"), "utf8");
const KPL_PICKS = JSON.parse(picksRaw.slice(picksRaw.indexOf("=") + 1).trim().replace(/;\s*$/, ""));
const KPL = { init() {}, esc: (s) => String(s == null ? "" : s) };

const fn = new Function("document", "window", "KPL", "KPL_PICKS", code);
fn(document, window, KPL, KPL_PICKS);

const grid = nodes["#pickGrid"]._html || "";
const rules = nodes["#pkRules"]._html || "";
const cards = (grid.match(/class="pick-card"/g) || []).length;
const deep = (grid.match(/match\.html\?id=[^"]*&m=\d+/g) || []).length;
const noM = (grid.match(/match\.html\?id=[^"]*"(?![^>]*&m=)/g) || []).length;

const checks = [
  ["卡片数 = 48", cards === 48, cards],
  ["深链带 &m= 的卡片数 = 48", deep === 48, deep],
  ["规则面板 4 条", (rules.match(/<div>/g) || []).length === 4, rules.length],
  ["规则面板含「达标」", rules.includes("达标"), null],
  ["规则面板含「入选」", rules.includes("入选"), null],
  ["翻盘局达标 8", /翻盘局.*达标 8 局.*入选 8 条/.test(rules), null],
  ["拉锯局达标 34 / 入选 16", /拉锯局.*达标 34 局.*入选 16 条/.test(rules), null],
  ["总/入选/日期", nodes["#pkTotal"]._text + "/" + nodes["#pkPicked"]._text, null],
  ["首卡 = TTG vs JDG", /广州TTG vs 北京JDG/.test(grid.split("pick-card")[1] || ""), null],
];

let bad = 0;
for (const [name, ok, extra] of checks) {
  if (!ok) bad++;
  console.log((ok ? "PASS " : "FAIL ") + name + (extra !== null && extra !== undefined ? "  → " + extra : ""));
}
console.log("\n规则面板实际输出：\n" + rules.replace(/<\/div>/g, "\n").replace(/<[^>]+>/g, ""));
process.exit(bad ? 1 : 0);
