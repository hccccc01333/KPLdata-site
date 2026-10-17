/* KPL 数据中心 · 单局复盘工作台（V4 阶段二）
   一条时间轴同时驱动：模型胜率 / 经济 / 资源 / 选手 / 邻近事件。
   数据由 build_replay_frames.py 预生成（assets/replay/<matchId>.json），按需加载。 */
window.KPL_REPLAY = (function () {
  "use strict";
  var esc = (window.KPL && KPL.esc) || function (v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var pct = function (v, d) { return v == null ? "—" : (Number(v) * 100).toFixed(d == null ? 0 : d) + "%"; };
  var signed = function (v, d) { var n = Number(v || 0); return (n >= 0 ? "+" : "") + n.toFixed(d == null ? 0 : d); };
  var cache = {};

  function loadPackage(matchId, cb) {
    if (cache[matchId]) { cb(cache[matchId]); return; }
    fetch("assets/replay/" + encodeURIComponent(matchId) + ".json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error("http " + r.status); return r.json(); })
      .then(function (d) { cache[matchId] = d; cb(d); })
      .catch(function () { cb(null); });
  }

  function hasReplay(matchId) {
    var idx = window.KPL_REPLAY_INDEX || {};
    return !!idx[matchId];
  }

  /* ---------- 时间轴曲线 ---------- */
  function curveSVG(frames, t1, t2, curIdx) {
    var W = 1040, H = 240, P = { l: 46, r: 54, t: 16, b: 28 };
    var maxM = Math.max(10, frames[frames.length - 1].m);
    var gds = frames.map(function (f) { return f.gd || 0; });
    var gMax = Math.max(1, Math.max.apply(null, gds.map(Math.abs)));
    var X = function (m) { return P.l + m / maxM * (W - P.l - P.r); };
    var Y = function (p) { return P.t + (1 - p) * (H - P.t - P.b); };
    var YG = function (v) { return P.t + (0.5 - v / (gMax * 2)) * (H - P.t - P.b); };
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" role="img" aria-label="胜率时间轴">';
    for (var gi = 0; gi <= 4; gi++) {
      var gv = gi / 4, gy = Y(gv).toFixed(1);
      s += '<line x1="' + P.l + '" y1="' + gy + '" x2="' + (W - P.r) + '" y2="' + gy + '" stroke="#1D2E47" stroke-dasharray="4 6"/>' +
        '<text x="' + (P.l - 8) + '" y="' + (parseFloat(gy) + 4) + '" text-anchor="end" font-size="10.5" fill="#6F84A3" font-family="Inter,monospace">' +
        Math.round(gv * 100) + '%</text>';
    }
    for (var m = 0; m <= maxM; m += 5) {
      s += '<text x="' + X(m).toFixed(1) + '" y="' + (H - 10) + '" text-anchor="middle" font-size="10.5" fill="#6F84A3" font-family="Inter,monospace">' + m + "′</text>";
    }
    /* 50% 中线 + 金差右轴 */
    s += '<line x1="' + P.l + '" y1="' + Y(0.5).toFixed(1) + '" x2="' + (W - P.r) + '" y2="' + Y(0.5).toFixed(1) + '" stroke="#2C4568"/>';
    [gMax, 0, -gMax].forEach(function (gv) {
      s += '<text x="' + (W - P.r + 8) + '" y="' + (YG(gv) + 4).toFixed(1) +
        '" font-size="10.5" fill="#5C7FA8" font-family="Inter,monospace">' +
        (gv > 0 ? "+" : "") + (gv / 1000).toFixed(1) + "k</text>";
    });
    var gPts = frames.map(function (f) { return X(f.m).toFixed(1) + "," + YG(f.gd || 0).toFixed(1); }).join(" ");
    s += '<polyline points="' + gPts + '" fill="none" stroke="#5C7FA8" stroke-width="1.6" stroke-dasharray="5 4" opacity=".85"/>';
    var pts = frames.map(function (f) {
      return X(f.m).toFixed(1) + "," + Y(f.p == null ? 0.5 : f.p).toFixed(1);
    }).join(" ");
    var area = "M" + X(frames[0].m).toFixed(1) + "," + Y(0.5).toFixed(1) + " L" + pts.split(" ").join(" L") +
      " L" + X(frames[frames.length - 1].m).toFixed(1) + "," + Y(0.5).toFixed(1) + " Z";
    s += '<path d="' + area + '" fill="#F6C021" fill-opacity=".10"/>';
    s += '<polyline points="' + pts + '" fill="none" stroke="#F6C021" stroke-width="2.2" stroke-linejoin="round"/>';
    var cf = frames[curIdx] || frames[frames.length - 1];
    var cx = X(cf.m).toFixed(1), cy = Y(cf.p == null ? 0.5 : cf.p).toFixed(1);
    s += '<line x1="' + cx + '" y1="' + P.t + '" x2="' + cx + '" y2="' + (H - P.b) + '" stroke="#9FB3CE" stroke-width="1" stroke-dasharray="3 4"/>';
    s += '<circle cx="' + cx + '" cy="' + cy + '" r="4.5" fill="#0A111C" stroke="#F6C021" stroke-width="2.4"/>';
    s += "</svg>";
    return s;
  }

  /* ---------- 面板 ---------- */
  function goldPanel(b, f, prev) {
    var gd = f.gd, d = prev ? gd - prev.gd : 0;
    var g1 = f.g[0] || [], g2 = f.g[1] || [];
    var rows = [];
    for (var i = 0; i < Math.max(g1.length, g2.length); i++) {
      var a = g1[i] || 0, c = g2[i] || 0;
      var n1 = (b.names || [])[i] || "?", n2 = (b.names || [])[i + 5] || "?";
      rows.push('<tr><td class="n">' + esc(n1) + '</td><td class="num">' + K.fmtInt(a) + '</td>' +
        '<td class="d ' + (a - c >= 0 ? "up" : "down") + '">' + signed(a - c) + "</td>" +
        '<td class="num">' + K.fmtInt(c) + '</td><td class="n r">' + esc(n2) + "</td></tr>");
    }
    return '<div class="rp-panel"><div class="rp-pt">经济状态 <em class="mono">金差 ' + signed(gd) +
      (prev ? " · 较上一帧 " + signed(d) : "") + '</em></div>' +
      '<div class="rp-gd"><b class="' + (gd >= 0 ? "up" : "down") + '">' + signed(gd) + "</b>" +
      '<span class="mono">' + esc(b.t1) + " 视角</span></div>" +
      '<table class="rp-tbl"><thead><tr><th>' + esc(b.t1) + '</th><th class="num">金币</th><th class="num">差值</th>' +
      '<th class="num">金币</th><th class="r">' + esc(b.t2) + "</th></tr></thead><tbody>" + rows.join("") + "</tbody></table></div>";
  }

  function resourcePanel(b, f, prev) {
    var names = ["暴君", "黑暗暴君", "主宰", "风暴龙王"];
    var d1 = prev ? f.o[0].map(function (v, i) { return v - prev.o[0][i]; }) : [0, 0, 0, 0];
    var d2 = prev ? f.o[1].map(function (v, i) { return v - prev.o[1][i]; }) : [0, 0, 0, 0];
    var rows = names.map(function (nm, i) {
      var a = f.o[0][i], c = f.o[1][i];
      var hot1 = d1[i] > 0 ? ' <em class="rp-hot">+' + d1[i] + "</em>" : "";
      var hot2 = d2[i] > 0 ? ' <em class="rp-hot">+' + d2[i] + "</em>" : "";
      return "<tr><td>" + nm + "</td><td class='num'>" + a + hot1 + "</td><td class='num'>" + c + hot2 + "</td></tr>";
    }).join("");
    var tk = f.t, kk = f.k;
    return '<div class="rp-panel"><div class="rp-pt">资源控制 <em class="mono">本帧累计</em></div>' +
      '<div class="rp-kv"><span>推塔</span><b class="mono">' + tk[0] + " : " + tk[1] + "</b>" +
      '<span>击杀</span><b class="mono">' + kk[0] + " : " + kk[1] + "</b></div>" +
      '<table class="rp-tbl two"><thead><tr><th>资源</th><th class="num">' + esc(b.t1) + '</th><th class="num">' + esc(b.t2) + "</th></tr></thead>" +
      "<tbody>" + rows + "</tbody></table></div>";
  }

  /* 事件证据摘要：只陈述"同一时间段发生"，不做因果归因 */
  function evidencePanel(b, f, prev, frames, idx) {
    var fiveAgo = frames[Math.max(0, idx - 3)];
    var dp = (f.p != null && fiveAgo && fiveAgo.p != null) ? (f.p - fiveAgo.p) * 100 : 0;
    var near = (b.events || []).filter(function (e) { return Math.abs(e.m - f.m) <= 1.5; });
    var lines = [];
    var lead = f.p == null ? "" : (f.p >= 0.5 ? b.t1 : b.t2);
    lines.push("第 <b>" + f.m.toFixed(0) + "</b> 分钟：" +
      (f.p == null ? "无模型胜率" : "模型给 <b>" + esc(lead) + "</b> " + pct(f.p >= 0.5 ? f.p : 1 - f.p) + " 胜率") +
      (fiveAgo && fiveAgo.p != null ? "，较约 3 个采样点前 " + signed(dp, 0) + "pp" : ""));
    var gdNow = f.gd, gdThen = fiveAgo ? fiveAgo.gd : f.gd;
    lines.push("同期金差 <b class='mono'>" + signed(gdNow) + "</b>（" + signed(gdNow - gdThen) + "）" +
      "，推塔 " + f.t[0] + ":" + f.t[1] + "，击杀 " + f.k[0] + ":" + f.k[1]);
    if (near.length) {
      lines.push("同时间段事件：" + near.map(function (e) { return esc(e.l); }).join(" · "));
    } else {
      lines.push("同时间段无结构性事件记录");
    }
    if (f.lc) {
      lines.push('<span class="rp-lc">该采样点模型置信度低：早期局势样本少，胜率波动不代表局势真的剧烈变化。</span>');
    }
    return '<div class="rp-panel rp-evidence"><div class="rp-pt">事件证据摘要 <em class="mono">同时发生，不等于因果</em></div>' +
      lines.map(function (l) { return '<p class="rp-line">' + l + "</p>"; }).join("") +
      '<p class="rp-disc">说明：以上只表示这些现象出现在同一时间段，不能据此断言是某个事件改变了胜率。</p></div>';
  }

  function eventList(b, curIdx) {
    if (!(b.events || []).length) return '<div class="empty-tip">该局没有结构性事件记录</div>';
    return '<div class="rp-events">' + b.events.map(function (e, i) {
      var active = Math.abs(e.m - b.frames[curIdx].m) <= 1.5 ? " on" : "";
      return '<button type="button" class="rp-ev' + active + '" data-m="' + e.m + '">' +
        '<span class="t mono">' + e.m.toFixed(0) + "′</span>" + esc(e.l) + "</button>";
    }).join("") + "</div>";
  }

  /* ---------- 挂载 ---------- */
  function mount(el, opts) {
    if (!el) return;
    var matchId = String(opts.matchId || "");
    if (!matchId) { el.innerHTML = '<div class="empty-tip">缺少 matchId</div>'; return; }
    el.innerHTML = '<div class="rp-loading mono">加载复盘数据…</div>';
    loadPackage(matchId, function (pkg) {
      if (!pkg || !(pkg.battles || []).length) {
        el.innerHTML = '<div class="empty-tip">该场暂无分钟级复盘数据（只有基础比分 / BP / 选手明细）</div>';
        return;
      }
      var battles = pkg.battles;
      var bi = 0;
      if (opts.battleId) {
        for (var i = 0; i < battles.length; i++) if (battles[i].battleId === opts.battleId) { bi = i; break; }
      }
      var frameIdx = 0;

      function frameCount() { return battles[bi].frames.length; }

      function draw() {
        var b = battles[bi];
        var f = b.frames[frameIdx];
        var prev = frameIdx > 0 ? b.frames[frameIdx - 1] : null;
        el.innerHTML =
          '<div class="rp">' +
          '<div class="rp-head">' +
          '<div class="rp-tabs">' + battles.map(function (x, i) {
            return '<button type="button" class="rp-tab' + (i === bi ? " on" : "") + '" data-i="' + i + '">G' + (x.seq || i + 1) +
              '<i class="' + (x.win === 1 ? "w" : x.win === 2 ? "l" : "") + '">' + (x.win === 1 ? "胜" : x.win === 2 ? "负" : "—") + "</i></button>";
          }).join("") + "</div>" +
          '<div class="rp-meta mono">' + esc(b.t1) + " vs " + esc(b.t2) + " · 时长 " + b.dur.toFixed(0) + "′ · " +
          (b.win === 1 ? esc(b.t1) : b.win === 2 ? esc(b.t2) : "—") + " 胜出" +
          ' <span class="rp-src ' + (b.src === "live" ? "live" : "replay") + '">' +
          (b.src === "live" ? "胜率=直播当时预测" : "胜率=赛后重放") + "</span></div>" +
          "</div>" +
          (b.src === "replay"
            ? '<div class="rp-warn">本局没有直播期预测记录，曲线是赛后用当前模型重放的结果，只作参考；复盘结论请以经济 / 资源等客观指标为主。</div>'
            : "") +
          '<div class="rp-chart" id="rpChart">' + curveSVG(b.frames, b.t1, b.t2, frameIdx) + "</div>" +
          '<div class="rp-tl"><input type="range" min="0" max="' + (b.frames.length - 1) + '" step="1" value="' + frameIdx + '" id="rpRange">' +
          '<div class="rp-tl-meta mono"><span>第 <b>' + f.m.toFixed(0) + "′</b> / " + b.dur.toFixed(0) + "′</span>" +
          "<span>拖动查看该时刻的经济、资源与选手表现</span></div></div>" +
          '<div class="rp-grid">' + goldPanel(b, f, prev) + resourcePanel(b, f, prev) + evidencePanel(b, f, prev, b.frames, frameIdx) + "</div>" +
          '<div class="rp-evs"><div class="rp-pt">关键事件 <em class="mono">点击跳到该分钟</em></div>' + eventList(b, frameIdx) + "</div>" +
          "</div>";
        bind();
      }

      function setFrame(i) {
        frameIdx = Math.max(0, Math.min(frameCount() - 1, i));
        draw();
        var r = document.getElementById("rpRange");
        if (r) r.focus({ preventScroll: true });
      }

      function bind() {
        var r = document.getElementById("rpRange");
        if (r) {
          r.addEventListener("input", function () { frameIdx = parseInt(r.value, 10); draw(); });
          r.addEventListener("change", function () { frameIdx = parseInt(r.value, 10); draw(); });
          r.addEventListener("keydown", function (e) {
            if (e.key === "ArrowLeft") { e.preventDefault(); setFrame(frameIdx - 1); }
            if (e.key === "ArrowRight") { e.preventDefault(); setFrame(frameIdx + 1); }
          });
        }
        el.querySelectorAll(".rp-tab").forEach(function (btn) {
          btn.addEventListener("click", function () {
            bi = parseInt(btn.getAttribute("data-i"), 10);
            frameIdx = 0;
            draw();
            if (opts.onBattleChange) opts.onBattleChange(battles[bi].battleId);
          });
        });
        el.querySelectorAll(".rp-ev").forEach(function (btn) {
          btn.addEventListener("click", function () {
            var m = parseFloat(btn.getAttribute("data-m"));
            var b = battles[bi], best = 0;
            for (var i = 0; i < b.frames.length; i++) {
              if (Math.abs(b.frames[i].m - m) < Math.abs(b.frames[best].m - m)) best = i;
            }
            setFrame(best);
          });
        });
        var chart = document.getElementById("rpChart");
        if (chart) {
          chart.addEventListener("click", function (e) {
            var rect = chart.getBoundingClientRect();
            var ratio = (e.clientX - rect.left) / rect.width;
            var b = battles[bi];
            var maxM = Math.max(10, b.frames[b.frames.length - 1].m);
            var target = ratio * maxM;
            var best = 0;
            for (var i = 0; i < b.frames.length; i++) {
              if (Math.abs(b.frames[i].m - target) < Math.abs(b.frames[best].m - target)) best = i;
            }
            setFrame(best);
          });
        }
      }

      draw();
    });
  }

  return { mount: mount, hasReplay: hasReplay, loadPackage: loadPackage };
})();
