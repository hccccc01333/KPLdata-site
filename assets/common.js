/* KPL 数据中心 · 产品站公共层（v3）
   工具函数 / 图标 / 顶栏（含搜索）/ 页脚 / 动效 / 共用组件（曲线、对位、卡片、倒计时） */
window.KPL = (function () {
  "use strict";
  var D = window.SITE_DATA || null;
  var DT = window.SITE_DETAILS || { matches: [], teams: [], heroes: [] };

  /* ---------- 工具 ---------- */
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fmtInt(n) { return Number(n || 0).toLocaleString("en-US"); }
  function pct(v, d) { return (Number(v) * 100).toFixed(d == null ? 1 : d) + "%"; }
  function signed(v, d) { var n = Number(v); return (n >= 0 ? "+" : "") + n.toFixed(d == null ? 0 : d); }
  var WD = ["日", "一", "二", "三", "四", "五", "六"];
  function dateCN(iso) {
    var p = String(iso).split("-");
    return p.length === 3 ? parseInt(p[1], 10) + "月" + parseInt(p[2], 10) + "日" : String(iso);
  }
  function weekdayCN(iso) {
    var d = new Date(String(iso) + "T12:00:00");
    return isNaN(d) ? "" : "星期" + WD[d.getDay()];
  }
  function tierOf(wr) { return wr >= 0.55 ? "S" : wr >= 0.50 ? "A" : wr >= 0.45 ? "B" : "C"; }

  /* ---------- 图标（内联 SVG，stroke 现行色） ---------- */
  var ICONS = {
    home: '<path d="M4 11l8-7 8 7v9a1 1 0 01-1 1h-5v-6h-4v6H5a1 1 0 01-1-1z"/>',
    calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    shield: '<path d="M12 3l7 3v5c0 4.6-3 8.1-7 10-4-1.9-7-5.4-7-10V6z"/>',
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1.5-4.2 5-6 8-6s6.5 1.8 8 6"/>',
    crown: '<path d="M4 18h16M5 18l-2-10 5.5 4L12 5l3.5 7L21 8l-2 10"/>',
    sliders: '<path d="M4 8h9M19 8h1M4 16h3M13 16h7"/><circle cx="15.5" cy="8" r="2.4"/><circle cx="9.5" cy="16" r="2.4"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.6-3.6"/>',
    chart: '<path d="M4 20h16M7 20v-7M12 20V6M17 20v-10"/>',
    layers: '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M4.5 12.5L12 16.7l7.5-4.2"/><path d="M4.5 16.5L12 20.7l7.5-4.2"/>',
    target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    pulse: '<path d="M3 12h4l2.5-6.5 4.5 13 2.5-6.5H21"/>',
    grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/>',
    github: '<path d="M12 2a10 10 0 00-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.11-1.47-1.11-1.47-.9-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.9 1.52 2.34 1.08 2.91.83.09-.65.35-1.09.63-1.34-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.6 9.6 0 015 0c1.9-1.29 2.74-1.02 2.74-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.68-4.57 4.93.36.31.68.92.68 1.85v2.75c0 .26.18.58.69.48A10 10 0 0012 2z" fill="currentColor" stroke="none"/>'
  };
  function icon(name, size) {
    var s = size || 18;
    return '<svg width="' + s + '" height="' + s + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
      'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      (ICONS[name] || "") + "</svg>";
  }

  /* ---------- 顶栏（含站内搜索） ---------- */
  var NAV = [
    ["home", "首页", "index.html"],
    ["calendar", "赛事中心", "schedule.html"],
    ["shield", "战队", "teams.html"],
    ["user", "选手", "players.html"],
    ["crown", "英雄", "heroes.html"],
    ["layers", "组合", "combos.html"],
    ["target", "BP", "bp.html"],
    ["pulse", "预测", "predict.html"],
    ["grid", "查询", "query.html"],
    ["chart", "对比", "compare.html"],
    ["sliders", "模拟器", "simulator.html"]
  ];
  function topbar(page) {
    var links = NAV.map(function (n) {
      return '<a href="' + n[2] + '"' + (n[2] === page ? ' class="on"' : "") + ">" + n[1] + "</a>";
    }).join("");
    return '<div class="wrap topbar-in">' +
      '<a class="brand" href="index.html"><span class="brand-mark">K</span>' +
      '<span class="brand-name">KPL 数据中心</span></a>' +
      '<div class="search-wrap"><div class="search-box">' + icon("search", 16) +
      '<input id="siteSearch" placeholder="搜索战队 / 选手 / 英雄" autocomplete="off" spellcheck="false"></div>' +
      '<div class="search-pop" id="searchPop"></div></div>' +
      '<nav class="nav">' + links + "</nav>" +
      '<a class="gh-ico" href="https://github.com/hccccc01333/KPLdata" target="_blank" rel="noopener" ' +
      'title="开源仓库" aria-label="GitHub 仓库">' + icon("github", 19) + "</a></div>";
  }
  function footer() {
    return '<div class="wrap footer-in"><div>' +
      '<div class="foot-brand">KPL 数据中心 <span class="mono">/ KING PRO LEAGUE DATA CENTER</span></div>' +
      '<p class="foot-note">数据来自腾讯王者荣耀职业联赛公开接口，为个人搭建的赛事数据产品（非官方、与腾讯无关联）。' +
      '统计均为自算口径：胜率类为历史区间估计，赛程与比分以官方发布为准。' +
      '了解数据口径与更新方式 → <a href="about.html" style="color:var(--gold)">数据说明</a></p></div>' +
      '<div class="foot-right mono"><div>数据更新 <b>' + esc(D ? D.generatedAt : "—") + "</b></div>" +
      '<a href="https://github.com/hccccc01333/KPLdata" target="_blank" rel="noopener">开源仓库 ↗</a>' +
      '<a href="about.html">数据说明 · 免责</a></div></div>';
  }

  /* ---------- 站内搜索 ---------- */
  function initSearch() {
    var input = document.getElementById("siteSearch");
    var pop = document.getElementById("searchPop");
    if (!input || !pop) return;
    var items = [];
    (D.standings || []).forEach(function (s) {
      items.push({ kind: "战队", label: s.team, icon: s.icon, href: "teams.html", kw: s.team });
    });
    var plist = (window.KPL_SEASONS && KPL_SEASONS.scopes && KPL_SEASONS.scopes.all.players) || D.players || [];
    plist.forEach(function (p) {
      items.push({ kind: "选手", label: p.name + " · " + p.team, icon: p.icon || p.teamIcon,
                   href: "player.html?id=" + encodeURIComponent(p.name), kw: p.name + " " + p.team });
    });
    (D.heroes || []).forEach(function (h) {
      items.push({ kind: "英雄", label: h.name, icon: h.icon,
                   href: "hero.html?id=" + encodeURIComponent(h.name), kw: h.name });
    });
    (D.schedule || []).slice(0, 200).forEach(function (r) {
      items.push({ kind: "比赛", label: r.date + " " + r.team1 + " vs " + r.team2, icon: "",
                   href: r.score1 >= 0 && DT.matches.some(function (m) { return m.matchId === r.matchId; })
                     ? "match.html?id=" + r.matchId : "schedule.html",
                   kw: r.team1 + " " + r.team2 });
    });
    function render(q) {
      if (!q) { pop.classList.remove("on"); pop.innerHTML = ""; return; }
      var hits = items.filter(function (it) { return it.kw.indexOf(q) >= 0; }).slice(0, 9);
      pop.innerHTML = hits.length
        ? hits.map(function (h) {
            return '<a href="' + h.href + '">' + (h.icon ? '<img src="' + esc(h.icon) + '" alt="">' : "") +
              "<span>" + esc(h.label) + '</span><span class="k">' + h.kind + "</span></a>";
          }).join("")
        : '<a><span style="color:var(--muted)">没有匹配结果</span></a>';
      pop.classList.add("on");
    }
    input.addEventListener("input", function () { render(input.value.trim()); });
    input.addEventListener("focus", function () { render(input.value.trim()); });
    document.addEventListener("click", function (e) {
      if (!e.target.closest(".search-wrap")) pop.classList.remove("on");
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        var first = pop.querySelector("a[href]");
        if (first) location.href = first.getAttribute("href");
      }
    });
  }

  /* ---------- 共用渲染 ---------- */
  function side(team, ic, r) {
    return '<div class="side' + (r ? " r" : "") + '">' +
      (r && ic ? '<img src="' + esc(ic) + '" alt="" loading="lazy">' : "") +
      "<span>" + esc(team) + "</span>" +
      (!r && ic ? '<img src="' + esc(ic) + '" alt="" loading="lazy">' : "") + "</div>";
  }
  function resultRow(r) {
    var ok = r.score1 >= 0 && r.score2 >= 0;
    var s1 = ok ? '<span class="' + (r.score1 >= r.score2 ? "w" : "") + '">' + r.score1 + "</span>" : "–";
    var s2 = ok ? '<span class="' + (r.score2 > r.score1 ? "w" : "") + '">' + r.score2 + "</span>" : "–";
    var go = DT.matches.some(function (m) { return m.matchId === r.matchId; })
      ? '<a class="go" href="match.html?id=' + esc(r.matchId) + '">复盘</a>'
      : '<span class="go off">—</span>';
    return '<div class="row" data-mid="' + esc(String(r.matchId || "")) + '">' +
      '<div class="rt-date"><b>' + esc(dateCN(r.date)) + "</b>" + esc(weekdayCN(r.date)) + "</div>" +
      side(r.team1, r.icon1, false) +
      '<div class="score">' + s1 + " : " + s2 + "</div>" +
      side(r.team2, r.icon2, true) + go + "</div>";
  }
  function muBody(rows) {
    return rows.length ? rows.map(function (r) {
      var tag = r.n < 8 ? '<span class="chip">样本不足</span>' : '<span class="chip done">样本充足</span>';
      return "<tr>" +
        '<td><span class="team-cell">' + (r.blueIcon ? '<img src="' + esc(r.blueIcon) + '" alt="">' : "") + esc(r.blue) + "</span></td>" +
        '<td><span class="team-cell">' + (r.redIcon ? '<img src="' + esc(r.redIcon) + '" alt="">' : "") + esc(r.red) + "</span></td>" +
        '<td class="num">' + r.n + " 局</td>" +
        '<td class="num">' + pct(r.wr) + "</td>" +
        '<td class="mono" style="font-size:12px;color:var(--muted)">' + pct(r.ciLo, 0) + " – " + pct(r.ciHi, 0) + "</td>" +
        "<td>" + tag + "</td></tr>";
    }).join("") : '<tr><td colspan="6" style="color:var(--muted)">该位置暂无可展示对位</td></tr>';
  }
  function heroCard(h, i) {
    var banTxt = h.banRate != null ? pct(h.banRate, 0)
      : (h.bans != null ? pct(h.bans / Math.max(1, h.games + h.bans), 0) : "—");
    return '<a class="hcard reveal" style="transition-delay:' + Math.min((i || 0) * 25, 300) +
      'ms" href="hero.html?id=' + encodeURIComponent(h.name) + '" ' +
      'title="' + esc(h.name) + " · " + h.games + " 局 · 胜率 " + pct(h.wr) + '">' +
      (h.icon ? '<img src="' + esc(h.icon) + '" alt="" loading="lazy">' : "") +
      '<div class="nm">' + esc(h.name) + '<span class="tier ' + h.tier + '">' + h.tier + "</span></div>" +
      '<div class="wr"><span>胜率</span><b class="mono">' + pct(h.wr) + "</b></div>" +
      '<div class="minibar"><i style="width:' + (h.wr * 100).toFixed(1) + '%"></i></div>' +
      '<div class="sub">出场 ' + h.games + " · 禁用 " + banTxt + "</div></a>";
  }
  function playerCard(p, i) {
    var ava = p.icon ? '<img class="p-ava" src="' + esc(p.icon) + '" alt="" loading="lazy">'
      : '<span class="p-ava ph">' + esc(String(p.name).slice(0, 1)) + "</span>";
    return '<div class="player reveal" id="pl-' + esc(p.name) + '" style="transition-delay:' +
      Math.min((i || 0) * 30, 240) + 'ms">' + ava +
      '<div class="p-main"><div class="p-top">' +
      '<span class="p-name"><span class="nm">' + esc(p.name) + "</span><em>" + esc(p.pos) + "</em></span>" +
      '<span class="p-kda">' + p.kda.toFixed(1) + "<small>KDA</small></span></div>" +
      '<div class="p-team">' + (p.teamIcon ? '<img src="' + esc(p.teamIcon) + '" alt="">' : "") +
      "<b>" + esc(p.team) + "</b><span>· " + p.games + " 局 · MVP " + p.mvp + " · 参团 " + Math.round(p.part) + "%</span></div>" +
      "</div></div>";
  }

  /* ---------- 胜率曲线（深色主题） ---------- */
  function wrChart(el, F, team1) {
    var tl = (F && F.key ? F.key.timeline : (F ? F.timeline : [])) || [];
    var phases = (F && F.key ? F.key.phases : (F ? F.phases : [])) || [];
    var events = (F && F.key ? F.key.events : (F ? F.events : [])) || [];
    if (!el || tl.length < 2) { if (el) el.innerHTML = '<div class="empty-tip">该局无分钟级曲线</div>'; return; }
    var W = 1040, H = 300, P = { l: 48, r: 18, t: 22, b: 34 };
    var fc = (F && F.forecast) || [];
    var maxM = Math.max(16, tl[tl.length - 1].m, fc.length ? fc[fc.length - 1][0] : 0);
    var X = function (m) { return P.l + (m / maxM) * (W - P.l - P.r); };
    var Y = function (p) { return P.t + (1 - p) * (H - P.t - P.b); };
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" aria-label="胜率曲线">';
    s += '<defs><linearGradient id="gdarea" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0" stop-color="#4D9FE8" stop-opacity=".34"/>' +
      '<stop offset="1" stop-color="#4D9FE8" stop-opacity="0"/></linearGradient></defs>';
    var phLabels = ["早期 ≤8′", "中期 9–15′", "后期 16′+"];
    phases.forEach(function (ph, i) {
      var lo = i === 0 ? 0 : phases[i - 1].last_minute;
      s += '<rect x="' + X(lo).toFixed(1) + '" y="' + P.t + '" width="' + (X(ph.last_minute) - X(lo)).toFixed(1) +
        '" height="' + (H - P.t - P.b) + '" fill="#4D9FE8" opacity="0.05"/>' +
        '<text x="' + ((X(lo) + X(ph.last_minute)) / 2).toFixed(1) + '" y="' + (P.t + 13) +
        '" text-anchor="middle" font-size="11" fill="#6F84A3" font-family="Roboto Mono,monospace">' + (phLabels[i] || "") + "</text>";
    });
    [0, 0.25, 0.5, 0.75, 1].forEach(function (p) {
      var y = Y(p);
      s += '<line class="gridline" x1="' + P.l + '" y1="' + y.toFixed(1) + '" x2="' + (W - P.r) + '" y2="' + y.toFixed(1) +
        '" stroke="#1D2E47" stroke-dasharray="' + (p === 0.5 ? "4 4" : "2 6") + '"/>' +
        '<text x="' + (P.l - 9) + '" y="' + (y + 4).toFixed(1) +
        '" text-anchor="end" font-size="11" fill="#6F84A3" font-family="Roboto Mono,monospace">' + Math.round(p * 100) + "%</text>";
    });
    for (var m = 5; m <= maxM; m += 5) {
      s += '<text x="' + X(m).toFixed(1) + '" y="' + (H - 12) + '" text-anchor="middle" font-size="11" ' +
        'fill="#6F84A3" font-family="Roboto Mono,monospace">' + m + "′</text>";
    }
    var line = tl.map(function (pt, i) { return (i ? "L" : "M") + X(pt.m).toFixed(1) + "," + Y(pt.p).toFixed(1); }).join(" ");
    s += '<path d="' + line + " L" + X(tl[tl.length - 1].m).toFixed(1) + "," + (H - P.b) +
      " L" + X(tl[0].m).toFixed(1) + "," + (H - P.b) + ' Z" fill="url(#gdarea)"/>';
    s += '<path id="wrLine" d="' + line + '" fill="none" stroke="#4D9FE8" stroke-width="2.8" ' +
      'stroke-linejoin="round" stroke-linecap="round"/>';
    var EV_COLOR = { first_blood: "#E5484D", tyrant: "#2BB3A3", dark_tyrant: "#2BB3A3", lord: "#F6C021", storm: "#F6C021", big_dragon: "#F6C021" };
    var shown = 0;
    var probAt = function (mm) {
      var best = tl[0];
      for (var i = 0; i < tl.length; i++) if (Math.abs(tl[i].m - mm) < Math.abs(best.m - mm)) best = tl[i];
      return best.p;
    };
    events.forEach(function (e) {
      var c = EV_COLOR[e.type];
      if (!c || shown >= 26) return;
      shown++;
      s += '<circle cx="' + X(Math.min(e.m, maxM)).toFixed(1) + '" cy="' + Y(probAt(e.m)).toFixed(1) +
        '" r="3.4" fill="' + c + '" opacity="0.95"><title>' + esc(e.m.toFixed(0) + "′ " + e.label) + "</title></circle>";
    });
    /* 未来预测段（金色虚线）：从当前点延伸到预测点 */
    if (fc.length && tl.length) {
      var lastPt = tl[tl.length - 1];
      var fcPts = [[lastPt.m, lastPt.p]].concat(fc);
      var fd = fcPts.map(function (pt, i) {
        return (i ? "L" : "M") + X(pt[0]).toFixed(1) + " " + Y(pt[1]).toFixed(1);
      }).join(" ");
      s += '<path d="' + fd + '" fill="none" stroke="#F6C021" stroke-width="2" stroke-dasharray="6 5" opacity=".9"/>';
      fc.forEach(function (pt) {
        s += '<circle cx="' + X(pt[0]).toFixed(1) + '" cy="' + Y(pt[1]).toFixed(1) + '" r="3.2" fill="#F6C021" opacity=".9"/>' +
          '<text x="' + X(pt[0]).toFixed(1) + '" y="' + (Y(pt[1]) - 9).toFixed(1) + '" text-anchor="middle" font-size="10.5" fill="#F6C021" font-family="Inter,monospace">' +
          Math.round(pt[1] * 100) + "%</text>";
      });
    }
    s += '<g id="wrCross" style="display:none"><line y1="' + P.t + '" y2="' + (H - P.b) +
      '" stroke="#F6C021" stroke-width="1" stroke-dasharray="3 3"/>' +
      '<circle r="4.6" fill="#0A111C" stroke="#F6C021" stroke-width="2.4"/></g></svg>';
    el.innerHTML = s;

    var svg = el.querySelector("svg");
    var cross = svg.querySelector("#wrCross");
    var cline = cross.querySelector("line"), cdot = cross.querySelector("circle");
    var tip = document.createElement("div");
    tip.className = "chart-tip mono";
    el.appendChild(tip);
    svg.addEventListener("mousemove", function (ev) {
      var r = svg.getBoundingClientRect();
      var xRatio = (ev.clientX - r.left) / r.width * W;
      var m = Math.max(0, Math.min(maxM, ((xRatio - P.l) / (W - P.l - P.r)) * maxM));
      var near = tl[0];
      tl.forEach(function (pt) { if (Math.abs(pt.m - m) < Math.abs(near.m - m)) near = pt; });
      var x = X(near.m), y = Y(near.p);
      cross.style.display = "";
      cline.setAttribute("x1", x); cline.setAttribute("x2", x);
      cdot.setAttribute("cx", x); cdot.setAttribute("cy", y);
      tip.style.display = "block";
      tip.textContent = near.m.toFixed(0) + "′ · " + team1 + "胜率 " + pct(near.p, 0) + " · 金差 " + signed(near.gd);
      tip.style.left = Math.min(r.width - tip.offsetWidth - 8, (x / W) * r.width + 12) + "px";
      tip.style.top = Math.max(0, (y / H) * r.height - 36) + "px";
    });
    svg.addEventListener("mouseleave", function () {
      cross.style.display = "none"; tip.style.display = "none";
    });
    var lineEl = svg.querySelector("#wrLine");
    var len = lineEl.getTotalLength();
    lineEl.style.strokeDasharray = len;
    lineEl.style.strokeDashoffset = len;
    var io = new IntersectionObserver(function (es) {
      if (es[0].isIntersecting) {
        lineEl.style.transition = "stroke-dashoffset .9s ease-out";
        lineEl.style.strokeDashoffset = 0;
        io.disconnect();
      }
    }, { threshold: 0.25 });
    io.observe(svg);
  }

  /* ---------- 倒计时 ---------- */
  function countdown(targetMs, el) {
    function tick() {
      var diff = targetMs - Date.now();
      if (!el) return;
      if (diff <= 0) { el.textContent = "已开始"; return; }
      var d = Math.floor(diff / 86400000), h = Math.floor(diff % 86400000 / 3600000),
          m = Math.floor(diff % 3600000 / 60000), sec = Math.floor(diff % 60000 / 1000);
      el.textContent = (d > 0 ? d + " 天 " : "") + h + " 小时 " + m + " 分 " + (d > 0 ? "" : sec + " 秒");
    }
    tick();
    return setInterval(tick, 1000);
  }

  /* ---------- 初始化（可重复 scan） ---------- */
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var revealObs = null, countObs = null;

  function countUp(el) {
    var target = parseFloat(el.getAttribute("data-count")),
        dec = parseInt(el.getAttribute("data-dec") || "0", 10);
    if (isNaN(target)) return;
    if (reduce) { el.textContent = dec ? target.toFixed(dec) : fmtInt(target); return; }
    var t0 = null, dur = 800;
    (function tick(ts) {
      if (!t0) t0 = ts || performance.now();
      var k = Math.min(1, ((ts || performance.now()) - t0) / dur);
      var v = target * (1 - Math.pow(1 - k, 3));
      el.textContent = dec ? v.toFixed(dec) : fmtInt(Math.round(v));
      if (k < 1) requestAnimationFrame(tick);
    })();
  }

  function scan() {
    if (!revealObs && !reduce && "IntersectionObserver" in window) {
      revealObs = new IntersectionObserver(function (es) {
        es.forEach(function (e) { if (e.isIntersecting) { e.target.classList.add("in"); revealObs.unobserve(e.target); } });
      }, { rootMargin: "0px 0px -8% 0px" });
    }
    document.querySelectorAll(".reveal:not([data-anim])").forEach(function (x) {
      x.setAttribute("data-anim", "1");
      if (revealObs) revealObs.observe(x); else x.classList.add("in");
    });
    if (!countObs && !reduce && "IntersectionObserver" in window) {
      countObs = new IntersectionObserver(function (es) {
        es.forEach(function (e) { if (e.isIntersecting) { countUp(e.target); countObs.unobserve(e.target); } });
      }, { threshold: 0.4 });
    }
    document.querySelectorAll("[data-count]:not([data-counted])").forEach(function (x) {
      x.setAttribute("data-counted", "1");
      if (countObs) countObs.observe(x); else countUp(x);
    });
  }

  function init() {
    var page = document.body.getAttribute("data-page") || "index.html";
    var h = document.getElementById("siteHeader");
    var f = document.getElementById("siteFooter");
    if (h) h.innerHTML = topbar(page);
    if (f) f.innerHTML = footer();
    initSearch();
    scan();
    autoRefresh();
  }

  /* ---------- CSV 导出 ---------- */
  function exportCSV(filename, rows) {
    var csv = rows.map(function (r) {
      return r.map(function (c) {
        c = String(c == null ? "" : c);
        return /[",\n]/.test(c) ? '"' + c.replace(/"/g, '""') + '"' : c;
      }).join(",");
    }).join("\r\n");
    var blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }


  /* ---------- 数据简报（动态一句话结论） ---------- */
  function brief(mount, html) {
    var el = typeof mount === "string" ? document.querySelector(mount) : mount;
    if (!el) return;
    el.innerHTML = '<span class="ico">●</span><p>' + html + "</p>";
  }

  /* ---------- 多系列折线图（指标曲线） ---------- */
  function lineChart(el, opts) {
    if (!el) return;
    var series = (opts.series || []).filter(function (se) { return se.pts && se.pts.length > 1; });
    if (!series.length) { el.innerHTML = '<div class="empty-tip">暂无可展示的曲线</div>'; return; }
    var W = 1040, H = opts.height || 280, P = { l: 62, r: 18, t: 20, b: 34 };
    var xs = [], ys = [];
    series.forEach(function (se) {
      se.pts.forEach(function (pt) { xs.push(pt[0]); ys.push(pt[1]); });
    });
    var xMin = Math.min.apply(null, xs), xMax = Math.max.apply(null, xs);
    var yMin = Math.min.apply(null, ys), yMax = Math.max.apply(null, ys);
    if (opts.yZero) { yMin = Math.min(0, yMin); yMax = Math.max(0, yMax); }
    var pad = (yMax - yMin) * 0.08 || 1;
    yMin -= pad; yMax += pad;
    if (xMax - xMin < 1) xMax = xMin + 1;
    var X = function (v) { return P.l + (v - xMin) / (xMax - xMin) * (W - P.l - P.r); };
    var Y = function (v) { return P.t + (1 - (v - yMin) / (yMax - yMin)) * (H - P.t - P.b); };
    var yFmt = opts.yFmt || function (v) { return Math.round(v); };
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" role="img">';
    /* 网格与 y 轴 */
    for (var gi = 0; gi <= 3; gi++) {
      var gv = yMin + (yMax - yMin) * gi / 3;
      var gy = Y(gv).toFixed(1);
      s += '<line x1="' + P.l + '" y1="' + gy + '" x2="' + (W - P.r) + '" y2="' + gy +
        '" stroke="#1D2E47" stroke-dasharray="4 6"/>' +
        '<text x="' + (P.l - 8) + '" y="' + (parseFloat(gy) + 4) + '" text-anchor="end" font-size="10.5" fill="#6F84A3" font-family="Inter,monospace">' + yFmt(gv) + "</text>";
    }
    if (yMin < 0 && yMax > 0) {
      s += '<line x1="' + P.l + '" y1="' + Y(0).toFixed(1) + '" x2="' + (W - P.r) + '" y2="' + Y(0).toFixed(1) + '" stroke="#2C4568"/>';
    }
    /* x 轴刻度（每 5 分钟） */
    for (var m = Math.ceil(xMin / 5) * 5; m <= xMax; m += 5) {
      s += '<text x="' + X(m).toFixed(1) + '" y="' + (H - 12) + '" text-anchor="middle" font-size="10.5" fill="#6F84A3" font-family="Inter,monospace">' + m + "′</text>";
    }
    /* 折线 */
    series.forEach(function (se) {
      var d = se.pts.map(function (pt, i) {
        return (i ? "L" : "M") + X(pt[0]).toFixed(1) + " " + Y(pt[1]).toFixed(1);
      }).join(" ");
      if (se.fill && se.pts.length > 1) {
        s += '<path d="' + d + " L" + X(se.pts[se.pts.length - 1][0]).toFixed(1) + " " + Y(Math.max(0, yMin)).toFixed(1) +
          " L" + X(se.pts[0][0]).toFixed(1) + " " + Y(Math.max(0, yMin)).toFixed(1) + ' Z" fill="' + se.color + '" fill-opacity=".10" stroke="none"/>';
      }
      s += '<path d="' + d + '" fill="none" stroke="' + se.color + '" stroke-width="' + (se.width || 2.2) + '"' +
        (se.dash ? ' stroke-dasharray="6 5"' : "") + ' stroke-linejoin="round" opacity="' + (se.opacity || 1) + '"/>';
      if (se.dots) {
        se.pts.forEach(function (pt) {
          s += '<circle cx="' + X(pt[0]).toFixed(1) + '" cy="' + Y(pt[1]).toFixed(1) + '" r="2.6" fill="' + se.color + '"/>';
        });
      }
    });
    s += "</svg>";
    el.innerHTML = (opts.legend === false ? "" :
      '<div class="lc-legend">' + series.map(function (se) {
        return '<span><i style="background:' + se.color + (se.dash ? ';opacity:.65' : "") + '"></i>' + esc(se.name) + "</span>";
      }).join("") + "</div>") + s;
  }

  /* ---------- 实时框架：数据新鲜度探测 + 进行中判定 ---------- */
  var LIVE_WINDOW_MS = 3.5 * 3600 * 1000; // 开赛后 3.5 小时内视为进行中

  function isLive(r) {
    if (!r || r.done || !r.date) return false;
    var t = new Date(r.date + "T" + (r.time || "17:00") + ":00").getTime();
    var now = Date.now();
    return now >= t && now <= t + LIVE_WINDOW_MS;
  }

  function liveBadge() {
    return '<span class="chip live"><i></i>进行中</span>';
  }

  function showUpdateBar(at) {
    if (document.getElementById("updateBar")) return;
    var bar = document.createElement("div");
    bar.id = "updateBar";
    bar.innerHTML = '<span>检测到新数据（' + esc(at) + "），刷新查看最新赛况</span>" +
      '<button type="button">立即刷新</button>';
    bar.querySelector("button").addEventListener("click", function () { location.reload(); });
    document.body.appendChild(bar);
  }

  var _refreshTimer = null;
  function autoRefresh() {
    if (_refreshTimer || !D || !D.generatedAt) return;
    var cur = String(D.generatedAt);
    _refreshTimer = setInterval(function () {
      fetch("assets/data.js?ts=" + Date.now()).then(function (r) { return r.text(); })
        .then(function (txt) {
          var m = txt.match(/"generatedAt"\s*:\s*"([^"]+)"/);
          if (m && m[1] && m[1] !== cur) showUpdateBar(m[1]);
        }).catch(function () {});
    }, 90000);
  }

  /* ---------- 数据范围选择器（年份 × 赛事） ---------- */
  var SCOPE_KEY = "kpl_scope_v1";

  function scopeOf(id) {
    var S = window.KPL_SEASONS;
    if (!S) return null;
    return S.scopes[id] || S.scopes["all"] || null;
  }

  function scopeName(id) {
    var S = window.KPL_SEASONS;
    if (!S || id === "all") return "全部年份";
    if (/^\d{4}$/.test(id)) return id + " 年";
    var lg = (S.leagues || []).filter(function (l) { return l.id === id; })[0];
    return lg ? lg.name : id;
  }

  function scopeMeta(id) {
    var d = scopeOf(id);
    if (!d) return "";
    return "共 " + fmtInt(d.totals.matches) + " 场比赛 · " + fmtInt(d.totals.battles) + " 局";
  }

  /* 渲染 年份 + 赛事 两个下拉；返回当前 scope id。改变时回调 onChange(scopeId)。 */
  function scopeBar(mount, onChange) {
    var S = window.KPL_SEASONS;
    var el = typeof mount === "string" ? document.querySelector(mount) : mount;
    if (!S || !el) return "all";
    var saved = localStorage.getItem(SCOPE_KEY) || "all";
    var savedYear = "all", savedLg = "";
    if (/^\d{4}$/.test(saved)) savedYear = saved;
    else if (/^\d{8,}$/.test(saved)) { savedYear = saved.slice(0, 4); savedLg = saved; }

    el.innerHTML =
      '<div class="scope-lab">' + icon("sliders", 15) + '<span>数据范围</span></div>' +
      '<label class="fld"><span>年份</span><select id="scopeYear"></select></label>' +
      '<label class="fld"><span>赛事</span><select id="scopeLeague"></select></label>' +
      '<span class="scope-meta mono" id="scopeMeta"></span>';

    var selY = el.querySelector("#scopeYear");
    var selL = el.querySelector("#scopeLeague");
    var meta = el.querySelector("#scopeMeta");

    selY.insertAdjacentHTML("beforeend", '<option value="all">全部年份</option>');
    (S.years || []).slice().sort().reverse().forEach(function (y) {
      selY.insertAdjacentHTML("beforeend",
        '<option value="' + y + '"' + (String(y) === savedYear ? " selected" : "") + ">" + y + " 年</option>");
    });

    function fillLeagues() {
      var y = selY.value;
      var lgs = (S.leagues || []).filter(function (l) { return y !== "all" && String(l.year) === String(y); });
      selL.innerHTML = '<option value="">该年全部赛事</option>' + lgs.map(function (l) {
        return '<option value="' + l.id + '"' + (l.id === savedLg ? " selected" : "") + ">" +
          esc(l.name) + "（" + l.matches + " 场）</option>";
      }).join("");
      selL.disabled = (y === "all");
    }

    function current() {
      if (selY.value === "all") return "all";
      return selL.value || selY.value;
    }

    function emit() {
      var id = current();
      try { localStorage.setItem(SCOPE_KEY, id); } catch (e) {}
      if (meta) meta.textContent = scopeMeta(id);
      if (onChange) onChange(id);
    }

    fillLeagues();
    selY.addEventListener("change", function () { savedLg = ""; fillLeagues(); emit(); });
    selL.addEventListener("change", emit);
    var initId = current();
    if (meta) meta.textContent = scopeMeta(initId);
    return initId;
  }

  return {
    data: D, details: DT,
    esc: esc, fmtInt: fmtInt, pct: pct, signed: signed,
    dateCN: dateCN, weekdayCN: weekdayCN, tierOf: tierOf, icon: icon,
    side: side, resultRow: resultRow, muBody: muBody,
    heroCard: heroCard, playerCard: playerCard, wrChart: wrChart,
    countdown: countdown, scopeBar: scopeBar, scopeOf: scopeOf, scopeName: scopeName,
    isLive: isLive, liveBadge: liveBadge, exportCSV: exportCSV, lineChart: lineChart,
    brief: brief,
    init: init, refresh: scan
  };
})();
