// 线上部署验收：关键资源可访问 + 无旧缓存造成的脚本/数据版本错配
//
// 为什么单独一个脚本：部署命令退出 0 只代表"上传完成"，不代表线上真的换了版本。
// 这一层只做三件事：
//   1. 关键资源都拿得到（200 + 正确 content-type）
//   2. index.html 里所有 ?v= 是同一个号（混号 = 浏览器拿到一半新一半旧）
//   3. 线上 data.js 的模型口径与仓库一致（V12 / holdoutN=20），且已删除的资源真的 404
//
// 用法：
//   node _check_deploy.js                                  // 默认线上域名
//   node _check_deploy.js https://xxx.workers.dev          // 指定环境
//   node _check_deploy.js http://127.0.0.1:8777            // 也可以打本地
const { spawnSync } = require("child_process");

const BASE = (process.argv[2] || "https://kpldata-site.hccccc01333.workers.dev").replace(/\/$/, "");
const TIMEOUT_MS = 25000;

let bad = 0;
const fail = [];
const check = (name, ok, extra) => {
  if (!ok) { bad++; fail.push(name); }
  console.log((ok ? "PASS " : "FAIL ") + name + (extra !== undefined && extra !== "" ? "  → " + extra : ""));
};

// Node 的 fetch 不读 http_proxy，沙箱里出网必须走代理 → 退回 curl
async function get(url) {
  try {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
    const r = await fetch(url, { redirect: "follow", signal: ctl.signal });
    clearTimeout(timer);
    return { status: r.status, body: await r.text(), ct: r.headers.get("content-type") || "", via: "fetch" };
  } catch (e) {
    const proxy = process.env.https_proxy || process.env.HTTPS_PROXY ||
                  process.env.http_proxy || process.env.HTTP_PROXY || "";
    for (const bin of ["curl", "D:/Git/mingw64/bin/curl.exe", "C:/Windows/System32/curl.exe"]) {
      const args = ["-sS", "-L", "--max-time", String(TIMEOUT_MS / 1000),
                    "-w", "\n__STATUS__%{http_code}|%{content_type}", url];
      if (proxy) args.unshift("-x", proxy);
      const r = spawnSync(bin, args, { encoding: "utf8", windowsHide: true });
      if (r.error || r.status === null) continue;
      const out = String(r.stdout || "");
      const m = out.match(/__STATUS__(\d+)\|(.*)$/);
      return {
        status: m ? Number(m[1]) : (r.status === 0 ? 200 : 0),
        body: m ? out.slice(0, m.index) : out,
        ct: m ? m[2] : "",
        via: "curl" + (proxy ? "(proxy)" : ""),
      };
    }
    return { status: 0, body: "", ct: "", via: "unreachable", err: e.message };
  }
}

const KEY_ASSETS = [
  ["index.html", "text/html"],
  ["assets/style.css", "css"],
  ["assets/pages.css", "css"],
  ["assets/data.js", "javascript"],
  ["assets/details.js", "javascript"],
  ["assets/common.js", "javascript"],
  ["assets/replay.js", "javascript"],
  ["assets/replay/index.js", "javascript"],
  ["assets/picks.js", "javascript"],
  ["assets/search.js", "javascript"],
  ["assets/live.js", "javascript"],
];

async function main() {
  console.log("=== 线上部署验收：" + BASE + " ===");

  const first = await get(BASE + "/index.html");
  if (first.status === 0) {
    console.log("FAIL 站点不可达：" + (first.err || "连接失败"));
    console.log("     若这是沙箱/代理限制（workers.dev 被拦），请在本机浏览器直接打开上面域名人工核对。");
    process.exit(1);
  }
  console.log("（取数方式：" + first.via + "）\n");

  console.log("=== 关键资源可访问 ===");
  for (const [path, ctHint] of KEY_ASSETS) {
    const r = await get(BASE + "/" + path);
    const okCt = r.status === 200 && r.ct.toLowerCase().includes(ctHint);
    check(path + " 200", r.status === 200, r.status);
    check(path + " content-type 正确", okCt, r.ct || "(空)");
  }

  console.log("\n=== 版本一致性（防新旧缓存混用）===");
  const versions = [...new Set((first.body.match(/\?v=(\d+)/g) || []))];
  check("index.html 资源版本号唯一", versions.length <= 1, versions.join(", ") || "(无 ?v=)");

  console.log("\n=== 线上数据版本与仓库一致 ===");
  const data = await get(BASE + "/assets/data.js");
  const mv = (data.body.match(/"version"\s*:\s*"([^"]+)"/) || [])[1];
  const hn = (data.body.match(/"holdoutN"\s*:\s*(\d+)/) || [])[1];
  const gen = (data.body.match(/"generatedAt"\s*:\s*"([^"]+)"/) || [])[1];
  check("线上 data.js 模型版本 = V12", mv === "V12", mv || "(取不到)");
  check("线上 data.js holdout 局数 = 20", hn === "20", hn || "(取不到)");
  check("线上 data.js 生成时间不超过 3 天", (() => {
    if (!gen) return false;
    const d = new Date(String(gen).replace(" ", "T"));
    return !isNaN(d.getTime()) && (Date.now() - d.getTime()) < 3 * 86400 * 1000;
  })(), gen || "(取不到)");

  console.log("\n=== 已删除资源不应再被提供 ===");
  for (const p of ["assets/hero3d.js", "assets/vendor/three.module.min.js"]) {
    const r = await get(BASE + "/" + p);
    check(p + " 已下线（404）", r.status === 404, r.status);
  }

  console.log("\n=== 首页结构（线上确实是新版）===");
  check("线上首页含赛事焦点容器", first.body.includes("focusHero"));
  check("线上首页已无 #dome 穹顶", !/\bid=["']dome["']/.test(first.body));
  check("线上首页已无 #todayStrip 残留", !/todayStrip/.test(first.body));
  check("线上首页已无轮播容器", !/\bid=["']slides["']/.test(first.body));

  console.log("\n" + (bad ? "=== 失败 " + bad + " 项 ===" : "=== 全部通过 ==="));
  if (bad) console.log("失败项：" + fail.join(" / "));
  process.exit(bad ? 1 : 0);
}

main().catch((e) => { console.log("FAIL 运行异常:", e.message); process.exit(1); });
