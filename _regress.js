// 回归总入口：一条命令跑完所有层级的浏览器断言
//
// 验收门槛（2026-10-18 定）：
//   **任何一个核心页面出现未捕获 JS 异常或未处理 Promise 拒绝 → 验收立即失败。**
//   这条优先于一切。"页面里有这个容器""README 写了这个功能"都不算数，
//   只有浏览器里真的渲染出来、真的能交互才算。
//
// 分层：
//   L0 静态结构   _check_replay_shell.js  复盘 paint 不重建 DOM（源码级断言，毫秒级）
//   L1 DOM 桩     _smoke_picks.js / _smoke_metrics.js  数据与文案渲染（不需要浏览器）
//   L2 真浏览器   _check_pages.js         全部页面异常 + 渲染 + 导航 + 交互 + 响应式
//   L3 真拖动     _check_replay_drag.js   CDP 连续拖 13 次滑块节点不变
//   L4 线上部署   _check_deploy.js        资源可达 + 版本一致 + 已删资源 404
//
// 用法：
//   python -m http.server 8777        # 另开一个终端（后台）起本地服务
//   node _regress.js                  # 只打本地
//   node _regress.js --live           # 本地 + 线上都打
//   node _regress.js --live-only      # 只打线上（部署后验收用）
const { spawnSync } = require("child_process");

const NODE = process.execPath;
const LOCAL = "http://127.0.0.1:8777";
const LIVE = "https://kpldata-site.hccccc01333.workers.dev";
const args = process.argv.slice(2);
const live = args.includes("--live") || args.includes("--live-only");
const onlyLive = args.includes("--live-only");

const steps = [];
if (!onlyLive) {
  steps.push(["L0 复盘 DOM 结构（静态）", NODE, ["_check_replay_shell.js"]]);
  steps.push(["L1 精选对局数据与文案（DOM 桩）", NODE, ["_smoke_picks.js"]]);
  steps.push(["L1 指标面板与口径文案（DOM 桩）", NODE, ["_smoke_metrics.js"]]);
  steps.push(["L2 全站浏览器验收（本地）", NODE, ["_check_pages.js", LOCAL]]);
  steps.push(["L3 复盘连续拖动（本地）", NODE, ["_check_replay_drag.js",
    LOCAL + "/match.html?id=2026062603&g=3&m=13"]]);
}
if (live) {
  steps.push(["L2 全站浏览器验收（线上）", NODE, ["_check_pages.js", LIVE]]);
  steps.push(["L4 线上部署验收", NODE, ["_check_deploy.js", LIVE]]);
}
if (!steps.length) {
  console.log("用法：node _regress.js [--live | --live-only]");
  process.exit(2);
}

let failed = 0;
const summary = [];
for (const [label, bin, argv] of steps) {
  console.log("\n" + "─".repeat(64));
  console.log("▶ " + label);
  console.log("─".repeat(64));
  const r = spawnSync(bin, argv, { encoding: "utf8", maxBuffer: 128 * 1024 * 1024, windowsHide: true });
  const out = String(r.stdout || "") + String(r.stderr || "");
  console.log(out.trim());
  const ok = r.status === 0;
  if (!ok) failed++;
  // 从子脚本输出里抓失败项，汇总到最后的报告里
  const fl = out.match(/失败项：(.+)/);
  summary.push({ label, ok, detail: fl ? fl[1].trim() : "" });
}

console.log("\n" + "═".repeat(64));
console.log("回归汇总");
console.log("═".repeat(64));
summary.forEach((s) => {
  console.log((s.ok ? "  PASS  " : "  FAIL  ") + s.label + (s.detail ? "\n           " + s.detail : ""));
});
console.log("═".repeat(64));
console.log(failed ? "结果：失败 " + failed + " / " + steps.length + " 个层级" : "结果：全部通过（" + steps.length + " 个层级）");
process.exit(failed ? 1 : 0);
