/* 本地工作台徽标：只在 server.py 起的本地服务上出现。
   托管静态站（Cloudflare / GitHub Pages）没有 /api/status，本脚本静默退出，不影响线上。 */
(function () {
  "use strict";
  fetch("/api/status", { method: "GET" }).then(function (r) {
    if (!r.ok) throw 0;
    return r.json();
  }).then(function (st) {
    var el = document.createElement("a");
    el.href = "/query.html?m=sql";
    el.title = (st && st.service) || "本地工作台";
    el.style.cssText = "position:fixed;left:16px;bottom:16px;z-index:200;display:flex;align-items:center;gap:8px;" +
      "padding:8px 14px;border-radius:999px;background:#101D30;border:1px solid #2C4568;color:#EAF1FA;" +
      "font:12px/1 Inter,MiSans,sans-serif;text-decoration:none;box-shadow:0 10px 30px rgba(0,0,0,.4)";
    el.innerHTML = '<i style="width:8px;height:8px;border-radius:50%;background:#7BE0A3;display:inline-block"></i>' +
      '<span>本地工作台 · ' + ((st && st.dbMB) || "?") + ' MB 就绪 · SQL 控制台</span>';
    document.body.appendChild(el);
  }).catch(function () { /* 静态托管：无 API，静默 */ });
})();
