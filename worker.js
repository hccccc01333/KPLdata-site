/* 峡谷有数 · 最小匿名事件端点
   仅接收 5 个产品事件 + page_view；不写 Cookie、不存 IP、不接收查询参数或选手/战队名称。
   当前账号未启用 Analytics Engine，先用 KV 记录：每条事件一个 90 天 TTL 的独立 key。 */
const ALLOWED = new Set([
  "page_view",
  "match_open",
  "key_moment_click",
  "timeline_drag",
  "share_click",
  "fav_add"
]);

function noContent() {
  return new Response(null, {
    status: 204,
    headers: { "Access-Control-Allow-Origin": "*", "Cache-Control": "no-store" }
  });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname !== "/api/event") return new Response("Not found", { status: 404 });
    if (request.method === "OPTIONS") return noContent();
    if (request.method !== "POST") return new Response(null, { status: 405 });

    let data;
    try {
      data = await request.json();
    } catch (err) {
      return noContent();
    }
    const event = String((data && data.e) || "").slice(0, 40);
    if (!ALLOWED.has(event)) return noContent();

    const path = String((data && data.p) || "").split("?")[0].slice(0, 120);
    const ref = String((data && data.r) || "").slice(0, 80);
    const sid = String((data && data.s) || "").slice(0, 40);
    const day = new Date().toISOString().slice(0, 10);
    const id = (crypto.randomUUID && crypto.randomUUID()) ||
      (Date.now().toString(36) + Math.random().toString(36).slice(2, 10));
    const body = JSON.stringify({ t: Date.now(), e: event, p: path, r: ref, s: sid });

    try {
      if (env.EVENTS_KV) {
        // 小流量基线：等写入完成再返回，确保每条事件真的落盘；失败只记日志。
        await env.EVENTS_KV.put("e:" + day + ":" + event + ":" + id, body,
          { expirationTtl: 60 * 60 * 24 * 90 });
      } else {
        console.error("[analytics] EVENTS_KV 未绑定");
      }
    } catch (err) {
      // 统计失败不能影响页面；保留在 Worker 日志里便于排查。
      console.error("[analytics] write failed", String(err && err.message || err));
    }
    return noContent();
  }
};
