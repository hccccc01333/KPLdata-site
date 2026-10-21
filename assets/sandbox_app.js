/* 胜率沙盘 · 纯前端交互
   数据来自 assets/sandbox.js（build_sandbox_data.py 生成），不请求后端。 */
(function () {
  "use strict";
  var D = window.KPL_SANDBOX;
  var K = window.KPL;
  if (!D || !K) return;
  K.init();

  var $ = function (s) { return document.querySelector(s); };
  var state = {
    battle: D.defaultBattle || 0,
    frame: D.defaultFrame || 0,
    mode: "hist"
  };
  var wi = { gd: 0, kd: 0, td: 0, obj: 0 };
  var drag = { on: false };

  function esc(s) { return K.esc ? K.esc(s) : String(s == null ? "" : s); }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function pct(p, digits) {
    if (p == null || isNaN(p)) return "—";
    return (p * 100).toFixed(digits == null ? 1 : digits) + "%";
  }
  function num(v) {
    if (v == null || isNaN(v)) return "—";
    return Number(v).toLocaleString("zh-CN");
  }
  function signed(v) {
    if (v == null || isNaN(v)) return "—";
    return (v > 0 ? "+" : "") + Number(v).toLocaleString("zh-CN");
  }
  function signedPct(v, digits) {
    if (v == null || isNaN(v)) return "—";
    var pp = v * 100;
    if (Math.abs(pp) < 0.05) return "0.0 pp";
    return (pp > 0 ? "+" : "") + pp.toFixed(digits == null ? 1 : digits) + " pp";
  }
  function teamOr(v, fallback) { return v || fallback; }
  function durText(b) {
    var d = Number(b.dur || 0);
    return d ? d.toFixed(1) + " 分钟" : "—";
  }

  /* ---------- 颜色 ---------- */
  function hexRgb(hex) {
    var n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  function mix(a, b, t) {
    var A = hexRgb(a), B = hexRgb(b);
    var c = A.map(function (v, i) { return Math.round(v + (B[i] - v) * t); });
    return "rgb(" + c.join(",") + ")";
  }
  function pColor(p) {
    if (p == null || isNaN(p)) return "#F1F2F4";
    p = clamp(p, 0, 1);
    if (p < 0.5) return mix("#D5374B", "#F2F3F5", p / 0.5);
    return mix("#F2F3F5", "#0F8A78", (p - 0.5) / 0.5);
  }
  function pTextColor(p) {
    if (p == null || isNaN(p)) return "var(--muted)";
    return p >= 0.5 ? "var(--teal)" : "var(--red)";
  }

  /* ---------- 基础数据 ---------- */
  function battleAt(i) { return D.battles[i]; }
  function matchForBattle(bi) {
    var b = battleAt(bi);
    for (var i = 0; i < D.matches.length; i++) {
      if (D.matches[i].id === b.mid) return D.matches[i];
    }
    return null;
  }
  function stateOf(f) {
    return { m: f[0], gd: f[2], kd: f[3], td: f[4], obj: f[5] };
  }
  function maxFrameMinute() {
    var mx = 25;
    D.battles.forEach(function (b) {
      b.frames.forEach(function (f) { if (f[0] > mx) mx = f[0]; });
    });
    return Math.ceil(mx / 5) * 5;
  }
  function nearestFrameIndex(b, minute, requireP) {
    var best = 0, bestD = Infinity;
    for (var i = 0; i < b.frames.length; i++) {
      var f = b.frames[i];
      if (requireP && f[1] == null) continue;
      var d = Math.abs(f[0] - minute);
      if (d < bestD) { bestD = d; best = i; }
    }
    return best;
  }

  /* ---------- Wilson 区间 ---------- */
  function wilson(wins, n) {
    if (!n) return [null, null];
    var p = wins / n, z = 1.96;
    var denom = 1 + z * z / n;
    var center = (p + z * z / (2 * n)) / denom;
    var half = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom;
    return [Math.max(0, center - half), Math.min(1, center + half)];
  }

  /* ---------- 同状态检索 ---------- */
  function findAnalogs(s, exclude) {
    var rows = [];
    for (var bi = 0; bi < D.battles.length; bi++) {
      if (bi === exclude) continue;
      var b = D.battles[bi];
      for (var fi = 0; fi < b.frames.length; fi++) {
        var f = b.frames[fi];
        if (f[1] == null) continue;
        var dm = Math.abs(f[0] - s.m) / 4;
        var dg = Math.abs(f[2] - s.gd) / 3000;
        var dk = Math.abs(f[3] - s.kd) / 3;
        var dt = Math.abs(f[4] - s.td) / 2.5;
        var dobj = Math.abs(f[5] - s.obj) / 6;
        var dist = dm * 1.1 + dg * 1.0 + dk * 0.45 + dt * 0.65 + dobj * 0.5;
        rows.push({ d: dist, bi: bi, fi: fi, b: b, f: f });
      }
    }
    rows.sort(function (a, b) { return a.d - b.d; });
    var top = rows.slice(0, 40);
    var n = top.length;
    var wins = 0;
    top.forEach(function (x) { if (x.b.win === 1) wins++; });
    var rate = n ? wins / n : null;
    var ci = wilson(wins, n);
    var examples = [], seen = {};
    for (var i = 0; i < top.length && examples.length < 3; i++) {
      var x = top[i];
      if (seen[x.b.id]) continue;
      seen[x.b.id] = 1;
      examples.push(x);
    }
    return {
      n: n, wins: wins, rate: rate, lo: ci[0], hi: ci[1],
      examples: examples,
      medianDist: n ? top[Math.floor(n / 2)].d : null
    };
  }

  /* ---------- 控件 ---------- */
  function renderMatches() {
    var sel = $("#sbMatch");
    if (!sel) return;
    sel.innerHTML = D.matches.map(function (m, i) {
      return '<option value="' + i + '">' + esc((m.date || "").slice(5)) + " " +
        esc(m.t1) + " vs " + esc(m.t2) + " · " + m.battles.length + "局</option>";
    }).join("");
    var cur = battleAt(state.battle).mid;
    for (var i = 0; i < D.matches.length; i++) {
      if (D.matches[i].id === cur) { sel.value = String(i); break; }
    }
  }
  function renderBattles() {
    var sel = $("#sbBattle");
    var m = matchForBattle(state.battle);
    if (!sel || !m) return;
    sel.innerHTML = m.battles.map(function (bi) {
      var b = battleAt(bi);
      return '<option value="' + bi + '">G' + b.seq + " · " + esc(b.t1) + " vs " +
        esc(b.t2) + "</option>";
    }).join("");
    sel.value = String(state.battle);
  }

  function loadBattle(bi, minute) {
    if (bi == null || !battleAt(bi)) return;
    state.battle = bi;
    var b = battleAt(bi);
    var target = minute == null ? b.frames[Math.floor(b.frames.length / 2)][0] : minute;
    state.frame = nearestFrameIndex(b, target, true);
    var slider = $("#sbMinute");
    if (slider) {
      slider.max = Math.max(0, b.frames.length - 1);
      slider.value = state.frame;
    }
    wi = { gd: 0, kd: 0, td: 0, obj: 0 };
    renderMatches();
    renderBattles();
    renderAll();
  }

  function setFrame(i) {
    var b = battleAt(state.battle);
    state.frame = clamp(i, 0, b.frames.length - 1);
    var slider = $("#sbMinute");
    if (slider) slider.value = state.frame;
    wi = { gd: 0, kd: 0, td: 0, obj: 0 };
    renderAll();
  }

  /* ---------- 概率地形 ---------- */
  function renderSurface() {
    var host = $("#sbSurface");
    var b = battleAt(state.battle);
    var f = b.frames[state.frame] || b.frames[0];
    if (!host) return;
    var W = Math.max(320, host.clientWidth || 720);
    var H = clamp(W * 0.5, 300, 430);
    var pad = { l: 58, r: 14, t: 16, b: 40 };
    var plotW = W - pad.l - pad.r;
    var plotH = H - pad.t - pad.b;
    var maxM = maxFrameMinute();
    var minG = D.surface.goldEdges[0];
    var maxG = D.surface.goldEdges[D.surface.goldEdges.length - 1];
    // 数值安全：避免 0 宽高
    plotW = Math.max(120, plotW);
    plotH = Math.max(150, plotH);

    function x(gd) { return pad.l + (gd - minG) / (maxG - minG) * plotW; }
    function y(m) { return pad.t + (1 - clamp(m, 0, maxM) / maxM) * plotH; }

    var svg = ['<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="胜率概率地形">'];
    svg.push('<rect x="0" y="0" width="' + W + '" height="' + H + '" fill="#FFFFFF"></rect>');

    // 网格单元
    D.surface.cells.forEach(function (c) {
      var x0 = x(D.surface.goldEdges[c.gi]);
      var x1 = x(D.surface.goldEdges[c.gi + 1]);
      var y0 = y(D.surface.minuteEdges[c.mi + 1]);
      var y1 = y(D.surface.minuteEdges[c.mi]);
      var p = state.mode === "hist" ? c.hist : c.model;
      var fill = p == null ? "#F1F2F4" : pColor(p);
      var op = c.n === 0 ? 0.32 : clamp(0.42 + c.n / 70 * 0.5, 0.42, 0.95);
      svg.push('<rect class="sb-cell" data-mi="' + c.mi + '" data-gi="' + c.gi +
        '" x="' + x0.toFixed(1) + '" y="' + y0.toFixed(1) + '" width="' +
        Math.max(0, x1 - x0).toFixed(1) + '" height="' +
        Math.max(0, y1 - y0).toFixed(1) + '" fill="' + fill +
        '" fill-opacity="' + op.toFixed(2) + '" stroke="#FFFFFF" stroke-width="1"></rect>');
    });

    // 0 金差参考线
    svg.push('<line x1="' + x(0) + '" y1="' + pad.t + '" x2="' + x(0) + '" y2="' +
      (pad.t + plotH) + '" stroke="#17191F" stroke-opacity=".18" stroke-dasharray="3 4"></line>');

    // 坐标轴
    [-20000, -10000, 0, 10000, 20000].forEach(function (g) {
      svg.push('<text x="' + x(g).toFixed(1) + '" y="' + (pad.t + plotH + 17) +
        '" text-anchor="middle" fill="#8A8F99" font-size="10" font-family="monospace">' +
        (g === 0 ? "0" : (g / 1000) + "k") + "</text>");
    });
    [0, 5, 10, 15, 20, 25].forEach(function (m) {
      if (m > maxM) return;
      svg.push('<text x="' + (pad.l - 8) + '" y="' + (y(m) + 3.5).toFixed(1) +
        '" text-anchor="end" fill="#8A8F99" font-size="10" font-family="monospace">' +
        m + "'</text>");
    });
    svg.push('<text x="' + (pad.l + plotW) + '" y="' + (pad.t + plotH + 33) +
      '" text-anchor="end" fill="#A3A7B0" font-size="10" font-family="monospace">金差（camp1 − camp2）</text>');
    svg.push('<text x="' + pad.l + '" y="' + (pad.t - 4) +
      '" fill="#A3A7B0" font-size="10" font-family="monospace">分钟</text>');

    // 轨迹 + 当前点
    var pts = [];
    for (var i = 0; i <= state.frame && i < b.frames.length; i++) {
      var pf = b.frames[i];
      pts.push([x(pf[2]), y(pf[0])]);
    }
    if (pts.length > 1) {
      svg.push('<polyline points="' + pts.map(function (p) {
        return p[0].toFixed(1) + "," + p[1].toFixed(1);
      }).join(" ") + '" fill="none" stroke="#17191F" stroke-opacity=".26" stroke-width="1.6"></polyline>');
    }
    var cx = x(f[2]), cy = y(f[0]);
    svg.push('<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) +
      '" r="8" fill="#FFFFFF" stroke="#17191F" stroke-width="2"></circle>');
    if (f[1] != null) {
      svg.push('<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) +
        '" r="4" fill="' + pColor(f[1]) + '" stroke="#FFFFFF" stroke-width="1"></circle>');
    }
    svg.push("</svg>");
    host.innerHTML = svg.join("");

    // 悬停提示
    var tip = $("#sbTip");
    host.querySelectorAll("rect.sb-cell").forEach(function (rect) {
      var mi = +rect.getAttribute("data-mi");
      var gi = +rect.getAttribute("data-gi");
      var cell = null;
      for (var j = 0; j < D.surface.cells.length; j++) {
        if (D.surface.cells[j].mi === mi && D.surface.cells[j].gi === gi) { cell = D.surface.cells[j]; break; }
      }
      if (!cell) return;
      rect.addEventListener("mousemove", function (evt) {
        if (!tip) return;
        var r = host.getBoundingClientRect();
        var content = "<b>" + esc(D.surface.minuteLabels[mi]) + " 分钟</b> · " +
          esc(D.surface.goldLabels[gi]) + "<br>";
        if (!cell.n) {
          content += "无样本";
        } else if (state.mode === "hist") {
          content += "历史同状态 <b>" + pct(cell.hist) + "</b> · n=" + cell.n + "<br>" +
            "95% 区间 " + pct(cell.lo) + "–" + pct(cell.hi) + "<br>" +
            "V12 均值 " + pct(cell.model);
        } else {
          content += "V12 均值 <b>" + pct(cell.model) + "</b> · n=" + cell.n + "<br>" +
            "历史同状态 " + pct(cell.hist) + " [" + pct(cell.lo) + "–" + pct(cell.hi) + "]";
        }
        tip.innerHTML = content;
        tip.style.display = "block";
        var left = evt.clientX - r.left + 12;
        var top = evt.clientY - r.top + 12;
        tip.style.left = Math.min(left, Math.max(0, host.clientWidth - 270)) + "px";
        tip.style.top = Math.min(top, Math.max(0, host.clientHeight - 92)) + "px";
      });
      rect.addEventListener("mouseleave", function () { if (tip) tip.style.display = "none"; });
      rect.addEventListener("click", function () {
        var m0 = D.surface.minuteEdges[mi], m1 = D.surface.minuteEdges[mi + 1];
        var g0 = D.surface.goldEdges[gi], g1 = D.surface.goldEdges[gi + 1];
        var best = -1, bestD = Infinity;
        b.frames.forEach(function (pf, idx) {
          if (pf[1] == null) return;
          if (pf[0] < m0 || pf[0] >= m1 || pf[2] < g0 || pf[2] >= g1) return;
          var d = Math.abs(pf[0] - (m0 + m1) / 2) + Math.abs(pf[2] - (g0 + g1) / 2) / 1000;
          if (d < bestD) { bestD = d; best = idx; }
        });
        if (best >= 0) setFrame(best);
      });
    });
  }

  function renderLegend() {
    var el = $("#sbLegend");
    if (!el) return;
    var modeText = state.mode === "hist"
      ? "颜色 = 历史同状态胜率（Beta 平滑）；越淡样本越少"
      : "颜色 = 该格内 V12 平均概率；越淡样本越少";
    el.innerHTML = '<span>0%</span><span class="grad"></span><span>100%</span>' +
      '<span><i class="dot"></i>当前局面</span><span>' + esc(modeText) + "</span>";
  }

  /* ---------- 胜率曲线 ---------- */
  function renderCurve() {
    var host = $("#sbCurve");
    var b = battleAt(state.battle);
    if (!host) return;
    var W = Math.max(320, host.clientWidth || 720);
    var H = 220;
    var pad = { l: 38, r: 14, t: 12, b: 26 };
    var plotW = W - pad.l - pad.r;
    var plotH = H - pad.t - pad.b;
    var maxM = Math.max(20, Math.ceil(maxFrameMinute() / 5) * 5);
    function x(m) { return pad.l + clamp(m, 0, maxM) / maxM * plotW; }
    function y(p) { return pad.t + (1 - clamp(p, 0, 1)) * plotH; }
    var svg = ['<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="V12 胜率曲线">'];
    [0, 0.25, 0.5, 0.75, 1].forEach(function (p) {
      svg.push('<line x1="' + pad.l + '" y1="' + y(p) + '" x2="' + (pad.l + plotW) +
        '" y2="' + y(p) + '" stroke="' + (p === 0.5 ? "#A3A7B0" : "#E7E8EC") +
        '" stroke-width="' + (p === 0.5 ? "1" : "1") + '"' +
        (p === 0.5 ? ' stroke-dasharray="4 4"' : "") + "></line>");
      svg.push('<text x="' + (pad.l - 6) + '" y="' + (y(p) + 3.5) +
        '" text-anchor="end" fill="#8A8F99" font-size="10" font-family="monospace">' +
        Math.round(p * 100) + "%</text>");
    });
    [0, 5, 10, 15, 20, 25, 30].forEach(function (m) {
      if (m > maxM) return;
      svg.push('<text x="' + x(m) + '" y="' + (H - 6) +
        '" text-anchor="middle" fill="#8A8F99" font-size="10" font-family="monospace">' +
        m + "'</text>");
    });

    // 胜率曲线：遇到 null 就断线
    var d = "", started = false;
    b.frames.forEach(function (f) {
      if (f[1] == null) { started = false; return; }
      d += (started ? "L" : "M") + x(f[0]).toFixed(1) + "," + y(f[1]).toFixed(1);
      started = true;
    });
    if (d) {
      svg.push('<path d="' + d + '" fill="none" stroke="#1B1D24" stroke-width="2.4" ' +
        'stroke-linejoin="round" stroke-linecap="round"></path>');
    }

    // 事件刻度
    var evColor = {
      tower: "#2E6FD0", tyrant: "#0F8A78", dark_tyrant: "#6B5BD2",
      lord: "#F02F55", storm: "#C81E40", first_blood: "#D99200"
    };
    b.events.forEach(function (ev) {
      var ex = x(ev[0]);
      svg.push('<circle cx="' + ex.toFixed(1) + '" cy="' + (H - pad.b + 4) +
        '" r="2.6" fill="' + (evColor[ev[1]] || "#A3A7B0") + '"><title>' +
        esc(ev[2]) + "</title></circle>");
    });

    // 当前时间
    var f = b.frames[state.frame] || b.frames[0];
    svg.push('<line x1="' + x(f[0]) + '" y1="' + pad.t + '" x2="' + x(f[0]) + '" y2="' +
      (pad.t + plotH) + '" stroke="#F02F55" stroke-opacity=".55" stroke-dasharray="3 3"></line>');
    if (f[1] != null) {
      svg.push('<circle cx="' + x(f[0]) + '" cy="' + y(f[1]) + '" r="5" fill="' +
        pColor(f[1]) + '" stroke="#FFFFFF" stroke-width="2"></circle>');
    }
    svg.push('<rect class="sb-overlay" x="' + pad.l + '" y="' + pad.t + '" width="' + plotW +
      '" height="' + plotH + '" fill="transparent" style="cursor:crosshair"></rect>');
    svg.push("</svg>");
    host.innerHTML = svg.join("");

    var overlay = host.querySelector(".sb-overlay");
    if (!overlay) return;
    function pick(evt) {
      var r = overlay.getBoundingClientRect();
      var px = (evt.clientX - r.left) / Math.max(1, r.width) * W;
      var m = (px - pad.l) / Math.max(1, plotW) * maxM;
      setFrame(nearestFrameIndex(b, m, false));
    }
    overlay.addEventListener("pointerdown", function (evt) {
      drag.on = true;
      if (overlay.setPointerCapture) overlay.setPointerCapture(evt.pointerId);
      pick(evt);
    });
    overlay.addEventListener("pointermove", function (evt) {
      if (drag.on) pick(evt);
    });
    overlay.addEventListener("pointerup", function () { drag.on = false; });
    overlay.addEventListener("pointercancel", function () { drag.on = false; });
  }

  /* ---------- 状态卡 ---------- */
  function renderState(b, f, s, a) {
    var host = $("#sbState");
    if (!host) return;
    var pFrame = f, p = f[1], pFallback = false;
    if (p == null) {
      var fallback = b.frames[nearestFrameIndex(b, f[0], true)];
      if (fallback && fallback[1] != null) {
        pFrame = fallback;
        p = fallback[1];
        pFallback = true;
      }
    }
    var p2 = p == null ? null : 1 - p;
    var t1 = teamOr(b.t1, "阵营 1");
    var t2 = teamOr(b.t2, "阵营 2");
    var winTeam = b.win === 1 ? t1 : t2;
    var gap = (p != null && a.rate != null) ? p - a.rate : null;
    var lowCls = a.n < 10 ? " sb-low" : "";
    var matchLink = b.mid ? '<a class="sb-link" href="match.html?id=' +
      encodeURIComponent(b.mid) + "&g=" + b.seq + '">赛后复盘 →</a>' : "";
    host.innerHTML =
      '<div class="panel-title">当前状态 <em>V12 · ' +
        (pFallback ? pFrame[0].toFixed(1) + "'（最近有效）" : f[0].toFixed(1) + "'") + "</em></div>" +
      '<div class="sb-state-top">' +
        '<div><span class="sb-team">' + esc(t1) + '</span><div class="p" style="color:' +
          pTextColor(p) + '">' + pct(p) + "</div></div>" +
        '<div class="sb-vs">VS</div>' +
        '<div class="right"><span class="sb-team">' + esc(t2) + '</span><div class="p" style="color:' +
          pTextColor(p2) + '">' + pct(p2) + "</div></div>" +
      "</div>" +
      '<div class="sb-state-meta"><span class="sb-tag gold">G' + b.seq + "</span>" +
        "<span>" + esc(b.date) + "</span><span>最终 " + esc(winTeam) + " 胜</span>" +
        "<span>" + esc(durText(b)) + "</span>" +
        (b.src && b.src !== "v12" ? '<span class="sb-tag">非 V12 重放</span>' : "") +
        (pFallback ? '<span class="sb-tag">该帧无模型输出 · 显示最近有效预测</span>' : "") +
        "</div>" +
      '<div class="sb-stat-grid">' +
        '<div class="sb-stat"><div class="k">金差（camp1 − camp2）</div><div class="v ' +
          (s.gd > 0 ? "pos" : s.gd < 0 ? "neg" : "") + '">' + signed(s.gd) + "</div></div>" +
        '<div class="sb-stat"><div class="k">击杀差</div><div class="v ' +
          (s.kd > 0 ? "pos" : s.kd < 0 ? "neg" : "") + '">' + signed(s.kd) + "</div></div>" +
        '<div class="sb-stat"><div class="k">推塔差</div><div class="v ' +
          (s.td > 0 ? "pos" : s.td < 0 ? "neg" : "") + '">' + signed(s.td) + "</div></div>" +
        '<div class="sb-stat"><div class="k">资源差（加权）</div><div class="v ' +
          (s.obj > 0 ? "pos" : s.obj < 0 ? "neg" : "") + '">' + signed(s.obj) + "</div></div>" +
      "</div>" +
      '<div class="sb-hist">' +
        '<div class="sb-hist-top"><span class="k">同状态历史（camp1 胜率）</span>' +
          '<span class="v">' + pct(a.rate) + ' <small>n=' + a.n + "</small></span></div>" +
        '<div class="sb-hist-sub">95% 区间 ' + pct(a.lo) + "–" + pct(a.hi) +
          " · 最相近的 " + a.n + " 个状态（分钟 / 金差 / 击杀 / 推塔 / 资源）</div>" +
        '<div class="sb-hist-gap' + lowCls + '">' +
          (gap == null ? "样本不足，暂不比较。" :
            "V12 比同状态历史" + (gap >= 0 ? "高" : "低") + " <b>" +
            Math.abs(gap * 100).toFixed(1) + " pp</b>；" +
            (a.n < 10 ? "样本偏少，百分比不稳定。" : "只代表历史伴随关系，不是因果。")) +
        "</div>" +
        '<div class="sb-state-meta" style="margin-top:9px">' + matchLink + "</div>" +
      "</div>";
  }

  /* ---------- What-if ---------- */
  function wiValue(k) {
    if (k === "gd") return (wi.gd / 1000).toFixed(2).replace(/\.?0+$/, "") + "k";
    return (wi[k] > 0 ? "+" : "") + wi[k];
  }
  function renderWhatIf(b, f, s, a) {
    var host = $("#sbWhatIf");
    if (!host) return;
    host.innerHTML =
      '<div class="panel-title">What-if <em>把状态改一点，再看历史</em></div>' +
      '<div class="sb-whatif-grid">' +
        '<label class="sb-wi"><span class="lab">经济 <b id="wiGdV">' + wiValue("gd") +
          '</b></span><input id="wiGd" type="range" min="-5" max="5" step="0.25" value="' +
          (wi.gd / 1000) + '"></label>' +
        '<label class="sb-wi"><span class="lab">推塔 <b id="wiTdV">' + wiValue("td") +
          '</b></span><input id="wiTd" type="range" min="-5" max="5" step="1" value="' + wi.td + '"></label>' +
        '<label class="sb-wi"><span class="lab">击杀 <b id="wiKdV">' + wiValue("kd") +
          '</b></span><input id="wiKd" type="range" min="-10" max="10" step="1" value="' + wi.kd + '"></label>' +
        '<label class="sb-wi"><span class="lab">资源 <b id="wiObjV">' + wiValue("obj") +
          '</b></span><input id="wiObj" type="range" min="-10" max="10" step="1" value="' + wi.obj + '"></label>' +
      "</div>" +
      '<div class="sb-whatif-out" id="wiOut">—</div>' +
      '<div class="sb-chips" id="wiChips"></div>' +
      '<div class="sb-whatif-foot"><span class="note">同状态历史，不是因果；单资源边际受样本与相关性影响，可能为负。</span>' +
        '<button class="btn ghost sm" id="wiReset" type="button">重置</button></div>';

    var bind = function (id, key, isGd) {
      var el = $("#" + id);
      if (!el) return;
      el.addEventListener("input", function () {
        wi[key] = isGd ? Math.round(parseFloat(el.value) * 1000) : parseInt(el.value, 10) || 0;
        var lab = $("#" + id + "V");
        if (lab) lab.textContent = wiValue(key);
        updateWhatIfOutput();
      });
    };
    bind("wiGd", "gd", true);
    bind("wiTd", "td", false);
    bind("wiKd", "kd", false);
    bind("wiObj", "obj", false);
    var reset = $("#wiReset");
    if (reset) {
      reset.addEventListener("click", function () {
        wi = { gd: 0, kd: 0, td: 0, obj: 0 };
        ["wiGd", "wiTd", "wiKd", "wiObj"].forEach(function (id) {
          var el = $("#" + id);
          if (el) el.value = 0;
        });
        ["gd", "kd", "td", "obj"].forEach(function (k) {
          var lab = $("#wi" + k.charAt(0).toUpperCase() + k.slice(1) + "V");
          if (lab) lab.textContent = wiValue(k);
        });
        updateWhatIfOutput();
      });
    }
    updateWhatIfOutput();
  }

  function updateWhatIfOutput() {
    var out = $("#wiOut");
    var chips = $("#wiChips");
    if (!out) return;
    var b = battleAt(state.battle);
    var f = b.frames[state.frame] || b.frames[0];
    var s = stateOf(f);
    var base = findAnalogs(s, state.battle);
    var adj = {
      m: s.m, gd: s.gd + wi.gd, kd: s.kd + wi.kd,
      td: s.td + wi.td, obj: s.obj + wi.obj
    };
    var after = findAnalogs(adj, state.battle);
    var delta = (base.rate != null && after.rate != null) ? after.rate - base.rate : null;
    out.innerHTML =
      '<div><span class="big">' + pct(base.rate) + " → " + pct(after.rate) + "</span>" +
      (delta == null ? "" : ' <span class="delta ' + (delta >= 0 ? "pos" : "neg") + '">' +
        signedPct(delta) + "</span>") + "</div>" +
      '<div style="margin-top:3px">同状态样本 n=' + after.n +
        (after.n < 8 ? ' <span class="sb-low">（偏少）</span>' : "") +
        " · 中位距离 " + (after.medianDist == null ? "—" : after.medianDist.toFixed(2)) + "</div>";

    if (chips) {
      if (base.rate == null) {
        chips.innerHTML = "";
      } else {
        var items = [
          ["+1k 经济", s, "gd", 1000],
          ["+1 塔", s, "td", 1],
          ["+1 击杀", s, "kd", 1],
          ["+1 资源", s, "obj", 1]
        ];
        chips.innerHTML = items.map(function (it) {
          var x = { m: it[1].m, gd: it[1].gd, kd: it[1].kd, td: it[1].td, obj: it[1].obj };
          x[it[2]] += it[3];
          var aa = findAnalogs(x, state.battle);
          var d = aa.rate == null ? null : aa.rate - base.rate;
          return '<span class="sb-chip ' + (d == null ? "" : d >= 0 ? "pos" : "neg") +
            '" title="历史同状态差异，受样本与相关性影响，可能为负">' +
            esc(it[0]) + " ≈ " + (d == null ? "—" : signedPct(d)) + "</span>";
        }).join("");
      }
    }
  }

  /* ---------- 同状态历史列表 ---------- */
  function renderAnalog(b, f, s, a) {
    var host = $("#sbAnalog");
    if (!host) return;
    if (!a.n) {
      host.innerHTML = '<div class="panel-title">同状态历史 <em>最相近的 40 个状态</em></div>' +
        '<div class="sb-empty">没有找到可比较的历史状态。</div>';
      return;
    }
    var rows = a.examples.map(function (x) {
      var bb = x.b;
      var w = bb.win === 1 ? bb.t1 : bb.t2;
      return '<div class="sb-analog-row" data-bi="' + x.bi + '" data-m="' + x.f[0] + '" title="' +
        esc(bb.t1) + " vs " + esc(bb.t2) + " · 最终 " + esc(w) + ' 胜">' +
        '<span class="d">' + esc((bb.date || "").slice(5)) + "</span>" +
        '<span class="vs">' + esc(bb.t1) + " vs " + esc(bb.t2) + " · G" + bb.seq + "</span>" +
        '<span class="r ' + (bb.win === 1 ? "win" : "") + '">' +
          (bb.win === 1 ? "camp1" : "camp2") + " 胜</span></div>";
    }).join("");
    host.innerHTML =
      '<div class="panel-title">同状态历史 <em>最相近的 40 个状态</em></div>' +
      '<div class="sb-analog-sum">在 ' + D.coverage.replayBattles + " 局里找到 <b>" + a.n +
        "</b> 个相近状态，camp1 最终赢 <b>" + a.wins + "</b> 次（<b>" + pct(a.rate) +
        "</b>）。<br>点一行可跳到那局同一分钟。</div>" +
      '<div class="sb-analog-list">' + rows + "</div>";
    host.querySelectorAll(".sb-analog-row").forEach(function (row) {
      row.addEventListener("click", function () {
        var bi = +row.getAttribute("data-bi");
        var m = parseFloat(row.getAttribute("data-m"));
        loadBattle(bi, m);
      });
    });
  }

  /* ---------- 模型体检 ---------- */
  function renderMeta() {
    var m = D.model;
    $("#sbMetaFrames").textContent = num(D.coverage.replayFrames);
    $("#sbMetaUpdated").textContent = D.updatedAt || "—";
    $("#sbKpiBrier").textContent = m.brier == null ? "—" : m.brier.toFixed(3);
    $("#sbKpiBrierS").textContent = num(m.testFrames) + " 帧 / " + m.testN + " 局 · ECE " +
      (m.ece == null ? "—" : m.ece.toFixed(3));
    $("#sbKpiAcc").textContent = pct(m.acc);
    $("#sbKpiAccS").textContent = "test 段 · 不是直播命中率";
    $("#sbKpiCoverage").textContent = D.coverage.replayBattles + " 局";
    $("#sbKpiCoverageS").textContent = D.coverage.replayMatches + " 场 · " +
      num(D.coverage.replayFrames) + " 个 V12 状态点";
    var earlyCb = (m.comeback || {}).early || {};
    $("#sbKpiWeak").textContent = pct(earlyCb.acc);
    $("#sbKpiWeakS").textContent = "early 翻盘局方向准确率 · n=" + (earlyCb.n || 0) + " 帧";
  }

  function renderHealth() {
    var m = D.model;
    $("#sbHealthNote").textContent = m.version + " · test " + m.testN + " 局 / " +
      num(m.testFrames) + " 帧 · 训练于 " + (m.trainedAt || "—");
    var cbAll = (m.comeback || {}).all || {};
    var kpis = [
      ["Brier（test）", m.brier == null ? "—" : m.brier.toFixed(3), "越低越好 · 298 帧"],
      ["ECE（test）", m.ece == null ? "—" : m.ece.toFixed(3), "校准误差 · 越低越好"],
      ["方向准确率", pct(m.acc), "test 段 · n=" + num(m.testFrames)],
      ["翻盘局方向准确率", pct(cbAll.acc), "全部翻盘帧 · n=" + (cbAll.n || 0)]
    ];
    $("#sbHealthKpis").innerHTML = kpis.map(function (x) {
      return '<div class="sb-health-kpi"><div class="k">' + esc(x[0]) + '</div><div class="v">' +
        esc(x[1]) + '</div><div class="s">' + esc(x[2]) + "</div></div>";
    }).join("");

    var labels = { early: "早期 ≤8′", mid: "中期 9–15′", late: "后期 16′+", all: "全部时点" };
    var order = ["early", "mid", "late", "all"];
    $("#sbPhases").innerHTML = order.filter(function (k) { return m.phases[k]; }).map(function (k) {
      var p = m.phases[k];
      return '<div class="sb-phase"><div class="k">' + labels[k] + '</div><div class="v">' +
        pct(p.acc) + '</div><div class="s">Brier ' + (p.brier == null ? "—" : p.brier.toFixed(3)) +
        ' · ECE ' + (p.ece == null ? "—" : p.ece.toFixed(3)) + ' · n=' + p.n +
        '</div><div class="bar"><i style="width:' + clamp((p.acc || 0) * 100, 0, 100) +
        '%"></i></div></div>';
    }).join("");

    renderReliability();
    renderBrierStrip();
    renderWorst();
    $("#sbNotes").innerHTML = "<h3>读数边界</h3><ul>" + (D.notes || []).map(function (n) {
      return "<li>" + esc(n) + "</li>";
    }).join("") + "</ul>";
  }

  function renderReliability() {
    var host = $("#sbReliability");
    if (!host) return;
    var bins = (D.calibration.bins || []).filter(function (b) { return b.n > 0; });
    if (!bins.length) {
      host.innerHTML = '<div class="sb-empty">暂无直播预测档案。</div>';
      return;
    }
    var W = Math.max(280, host.clientWidth || 400);
    var H = 250;
    var pad = { l: 38, r: 14, t: 14, b: 30 };
    var plotW = W - pad.l - pad.r, plotH = H - pad.t - pad.b;
    function x(p) { return pad.l + p * plotW; }
    function y(p) { return pad.t + (1 - p) * plotH; }
    var svg = ['<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="可靠性图">'];
    [0, 0.25, 0.5, 0.75, 1].forEach(function (p) {
      svg.push('<line x1="' + x(p) + '" y1="' + pad.t + '" x2="' + x(p) + '" y2="' +
        (pad.t + plotH) + '" stroke="#ECEFF3" stroke-width="1"></line>');
      svg.push('<line x1="' + pad.l + '" y1="' + y(p) + '" x2="' + (pad.l + plotW) +
        '" y2="' + y(p) + '" stroke="#ECEFF3" stroke-width="1"></line>');
      svg.push('<text x="' + (pad.l - 6) + '" y="' + (y(p) + 3.5) +
        '" text-anchor="end" fill="#8A8F99" font-size="10" font-family="monospace">' +
        Math.round(p * 100) + "%</text>");
      svg.push('<text x="' + x(p) + '" y="' + (H - 7) +
        '" text-anchor="middle" fill="#8A8F99" font-size="10" font-family="monospace">' +
        Math.round(p * 100) + "%</text>");
    });
    svg.push('<line x1="' + x(0) + '" y1="' + y(0) + '" x2="' + x(1) + '" y2="' + y(1) +
      '" stroke="#17191F" stroke-opacity=".38" stroke-dasharray="4 4"></line>');
    bins.forEach(function (b) {
      var r = 3 + Math.sqrt(b.n) / 3.2;
      svg.push('<circle cx="' + x(b.meanP).toFixed(1) + '" cy="' + y(b.obs).toFixed(1) +
        '" r="' + r.toFixed(1) + '" fill="#2E6FD0" fill-opacity=".55" stroke="#FFFFFF" stroke-width="1.2">' +
        "<title>" + pct(b.meanP) + " → " + pct(b.obs) + " · n=" + b.n + "</title></circle>");
    });
    svg.push('<text x="' + (pad.l + plotW) + '" y="' + (H - 17) +
      '" text-anchor="end" fill="#A3A7B0" font-size="10" font-family="monospace">预测概率</text>');
    svg.push("</svg>");
    host.innerHTML = svg.join("");
    var c = D.calibration;
    var note = "直播档案 " + c.nBattles + " 局 / " + num(c.nPoints) + " 分钟点";
    if (c.ece != null) note += " · ECE " + c.ece.toFixed(3);
    note += " · 非独立 test，只用于观察校准形态。";
    var live = D.model.live || {};
    var cps = (live.checkpoints || []).map(function (x) {
      return x.m + "′ " + pct(x.acc) + "（Brier " + Number(x.brier).toFixed(3) + "）";
    });
    if (cps.length) note += " 分时点：" + cps.join(" / ") + "。";
    var rvl = live.replayVsLive;
    if (rvl && rvl.gapAll != null) {
      note += " 重放 vs 直播 ΔBrier " + Number(rvl.gapAll).toFixed(3) +
        "（同一批局，直播更差）。";
    }
    $("#sbRelNote").textContent = note;
  }

  function renderBrierStrip() {
    var host = $("#sbBrierStrip");
    if (!host) return;
    var rows = (D.model.holdout || []).slice().sort(function (a, b) {
      return (b.brier || 0) - (a.brier || 0);
    });
    if (!rows.length) {
      host.innerHTML = '<div class="sb-empty">暂无 test 明细。</div>';
      return;
    }
    var maxB = Math.max(0.2, Math.max.apply(null, rows.map(function (r) { return r.brier || 0; })));
    host.innerHTML = rows.map(function (r) {
      var tag = r.isComeback ? "翻盘局" : "普通局";
      var date = (r.date || "").slice(5) || "—";
      return '<div class="sb-brier-row ' + (r.isComeback ? "cb" : "") + '" title="' +
        esc(r.t1 || r.id) + " vs " + esc(r.t2 || "—") + " · " + tag + ' · ' +
        (r.nPoints || 0) + ' 个预测点">' +
        '<span class="d">' + esc(date) + " G" + (r.seq || "?") + "</span>" +
        '<span class="bar"><i style="width:' + clamp((r.brier || 0) / maxB * 100, 0, 100) +
        '%"></i></span><span class="v">' + (r.brier == null ? "—" : r.brier.toFixed(3)) +
        "</span></div>";
    }).join("") + '<div class="sb-rel-note">红色 = 翻盘局；20 局中 6 局为翻盘局。' +
      "条形越短越好；每局样本量不同，不能只看单局排名。</div>";
  }

  function renderWorst() {
    var host = $("#sbWorst");
    if (!host) return;
    var rows = D.model.worst || [];
    var html = '<div class="sb-worst-row sb-worst-head"><div>对局</div><div class="n">Brier</div>' +
      '<div class="n">方向</div><div class="ty">类型</div></div>';
    rows.forEach(function (r) {
      var name = r.t1 ? esc(r.t1) + " vs " + esc(r.t2) : esc(r.id);
      var link = r.mid ? '<a class="sb-link" href="match.html?id=' + encodeURIComponent(r.mid) +
        "&g=" + r.seq + '">' + name + "</a>" : name;
      html += '<div class="sb-worst-row"><div class="vs">' + link +
        "<small>" + esc(r.date || "—") + " · G" + (r.seq || "?") + "</small></div>" +
        '<div class="n bad">' + (r.brier == null ? "—" : r.brier.toFixed(3)) + "</div>" +
        '<div class="n">' + pct(r.acc) + "</div><div class=\"ty\">" +
        (r.isComeback ? "翻盘" : "普通") + "</div></div>";
    });
    var bad = D.model.badBattle;
    if (bad) {
      var name2 = bad.t1 ? esc(bad.t1) + " vs " + esc(bad.t2) : esc(bad.id);
      html += '<div class="sb-worst-row"><div class="vs">' + name2 +
        "<small>护栏压力测试 · 命中 " + (bad.goldGuardHits || 0) + " 次</small></div>" +
        '<div class="n">' + (bad.brier == null ? "—" : bad.brier.toFixed(3)) + "</div>" +
        '<div class="n">' + pct(bad.acc) + "</div><div class=\"ty\">护栏</div></div>";
    }
    host.innerHTML = html;
  }

  /* ---------- 事件绑定 ---------- */
  function bindControls() {
    var matchSel = $("#sbMatch");
    if (matchSel) {
      matchSel.addEventListener("change", function () {
        var m = D.matches[+matchSel.value];
        if (m && m.battles.length) loadBattle(m.battles[0], null);
      });
    }
    var battleSel = $("#sbBattle");
    if (battleSel) {
      battleSel.addEventListener("change", function () {
        loadBattle(+battleSel.value, null);
      });
    }
    var slider = $("#sbMinute");
    if (slider) {
      slider.addEventListener("input", function () { setFrame(+slider.value); });
    }
    document.querySelectorAll("#sbMode button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll("#sbMode button").forEach(function (b) { b.classList.remove("on"); });
        btn.classList.add("on");
        state.mode = btn.getAttribute("data-mode") || "hist";
        renderSurface();
        renderLegend();
      });
    });
    var rnd = $("#sbRandom");
    if (rnd) {
      rnd.addEventListener("click", function () {
        var bi = Math.floor(Math.random() * D.battles.length);
        var b = D.battles[bi];
        var valid = [];
        b.frames.forEach(function (f, i) { if (f[1] != null) valid.push(i); });
        var fi = valid.length ? valid[Math.floor(Math.random() * valid.length)] : 0;
        state.battle = bi;
        state.frame = fi;
        wi = { gd: 0, kd: 0, td: 0, obj: 0 };
        renderMatches();
        renderBattles();
        var sl = $("#sbMinute");
        if (sl) { sl.max = Math.max(0, b.frames.length - 1); sl.value = fi; }
        renderAll();
      });
    }
  }

  function renderAll() {
    var b = battleAt(state.battle);
    if (!b) return;
    if (state.frame >= b.frames.length) state.frame = b.frames.length - 1;
    var f = b.frames[state.frame] || b.frames[0];
    var s = stateOf(f);
    var a = findAnalogs(s, state.battle);
    var label = $("#sbMinuteLabel");
    if (label) label.textContent = f[0].toFixed(1) + "'";
    var meta = $("#sbCurveMeta");
    if (meta) meta.textContent = b.date + " · G" + b.seq + " · " + b.t1 + " vs " + b.t2;
    renderSurface();
    renderLegend();
    renderCurve();
    renderState(b, f, s, a);
    renderWhatIf(b, f, s, a);
    renderAnalog(b, f, s, a);
  }

  function init() {
    renderMatches();
    renderBattles();
    var slider = $("#sbMinute");
    var b = battleAt(state.battle);
    if (slider) {
      slider.max = Math.max(0, b.frames.length - 1);
      slider.value = state.frame;
    }
    bindControls();
    renderMeta();
    renderAll();
    renderHealth();
  }

  var resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      renderSurface();
      renderCurve();
      renderReliability();
    }, 160);
  });

  init();
})();
