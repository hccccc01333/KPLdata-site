// 临时冒烟：DOM 桩跑 about.html / predict.html 的内联脚本，验证新指标真的渲染出来
const fs = require("fs");
const path = require("path");

function loadAsset(name) {
  const raw = fs.readFileSync(path.join(__dirname, "assets", name), "utf8");
  return JSON.parse(raw.slice(raw.indexOf("=") + 1).trim().replace(/;\s*$/, ""));
}

function makeEl() {
  return {
    _html: "", _text: "", children: [], style: {},
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    set textContent(v) { this._text = v; }, get textContent() { return this._text; },
    addEventListener() {}, appendChild() {}, closest() { return null; },
    classList: { toggle() {}, add() {}, remove() {} },
    querySelectorAll() { return []; }, querySelector() { return makeEl(); },
  };
}

function runPage(file, extraWindow = {}) {
  const html = fs.readFileSync(path.join(__dirname, file), "utf8");
  const blocks = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)];
  const code = blocks[blocks.length - 1][1];
  const nodes = {};
  const document = {
    querySelector(sel) { return (nodes[sel] = nodes[sel] || makeEl()); },
    querySelectorAll() { return []; },
  };
  const KPLbase = {
    data: loadAsset("data.js"),
    esc: (s) => String(s == null ? "" : s),
    fmtInt: (n) => String(n),
    init() {}, countUp() {}, reveal() {},
  };
  // 未实现的工具函数一律返回空串，避免冒烟被无关 API 打断
  const KPL = new Proxy(KPLbase, {
    get(t, p) { return p in t ? t[p] : () => ""; },
  });
  const window = { ...extraWindow };
  new Function("document", "window", "KPL", "KPL_SEASONS", code)(document, window, KPL, null);
  return nodes;
}

let bad = 0;
const check = (name, ok, extra) => {
  if (!ok) bad++;
  console.log((ok ? "PASS " : "FAIL ") + name + (extra ? "  → " + extra : ""));
};

// ---- about.html ----
const a = runPage("about.html");
const rows = (a["#holdoutBody"]._html || "").match(/<tr/g) || [];
check("about: 回测表 4 行", rows.length === 4, rows.length);
const foot2 = a["#modelFoot2"]._text || "";
check("about: 口径脚注含「三段隔离」", foot2.includes("三段隔离"), "");
check("about: 脚注含同一样本对照 0.143 → 0.135", /0\.143.*0\.135/.test(foot2), "");
check("about: 表格出现 0.235（新 early）", /0.23\d/.test(a["#holdoutBody"]._html || ""), "");

// ---- predict.html ----
const p = runPage("predict.html", { KPL_PREDICT: loadAsset("predict.js") });
const kTitle = p["#kAccK"]._text || "";
const kSub = p["#kAccS"]._text || "";
check("predict: KPI 标题是动态局数", kTitle.includes("20 局"), kTitle);
check("predict: 副标题同时给局数与帧数", /20 局 · 298 帧/.test(kSub), kSub);

const rvlGrid = p["#rvlGrid"]._html || "";
const rvlNote = p["#rvlNote"]._text || "";
check("predict: 重放vs直播 5 个指标格", (rvlGrid.match(/pr-kpi/g) || []).length === 5,
  (rvlGrid.match(/pr-kpi/g) || []).length);
check("predict: 含考试段干净估计 -0.127", rvlGrid.includes("-0.127"), "");
check("predict: 脚注点明「不是当前模型的能力」", rvlNote.includes("不是当前模型的能力"), "");

console.log("\nabout 脚注：" + foot2);
console.log("predict KPI：" + kTitle + " / " + kSub);
process.exit(bad ? 1 : 0);
