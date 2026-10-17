
(function () {
  "use strict";
  var D = KPL.data, K = KPL, $ = function (s) { return document.querySelector(s); };
  K.init();
  var NAME = new URLSearchParams(location.search).get("id") || "";
  var P = (window.KPL_PLAYERS || {})[NAME];

  var heroIcon = {};
  ((K.scopeOf("all") || {}).heroes || []).forEach(function (h) { heroIcon[h.name] = h.icon; });

  if (!P) {
    $("#wrapHero").innerHTML = '<header class="page-hero"><div class="wrap">' +
      '<div class="ph-kicker mono">PLAYER · 选手</div><h1>未找到该选手</h1>' +
      "<p>选手详情覆盖出场 15 局以上的选手；可在选手榜搜索。</p>" +
      '<div class="slide-cta" style="margin-top:18px"><a class="btn primary" href="players.html">返回选手榜</a></div></div></header>';
    return;
  }

  /* ---------- 头部 ---------- */
  $("#wrapHero").innerHTML = '<header class="page-hero"><div class="wrap"><div class="hd-top">' +
    (P.icon ? '<img class="hd-ava" src="' + K.esc(P.icon) + '" alt="">'
            : '<span class="hd-ava ph">' + K.esc(NAME.slice(0, 1)) + "</span>") +
    '<div><div class="hd-name">' + K.esc(NAME) +
    (P.pos ? ' <span class="tier B" style="vertical-align:middle">' + K.esc(P.pos) + "</span>" : "") + "</div>" +
    '<div class="hd-sub">' + (P.teamIcon ? '<img src="' + K.esc(P.teamIcon) + '" alt="" style="width:16px;height:16px;vertical-align:-3px;margin-right:5px">' : "") +
    K.esc(P.team) + " · 全部赛事 " + K.fmtInt(P.games) + " 局 · 赢下 " + K.fmtInt(P.wins) + " 局</div></div>" +
    "</div></div></header>";

  /* ---------- KPI 四格 ---------- */
  var kpi = '<div class="hd-stats">' +
    '<div class="hd-cell hl"><div class="k">胜率</div><div class="v">' + K.pct(P.wr) + '</div><div class="s">' + P.wins + " 胜 / " + P.games + " 局</div></div>" +
    '<div class="hd-cell"><div class="k">KDA</div><div class="v">' + P.kda.toFixed(2) + '</div><div class="s">击杀 + 助攻 ÷ 死亡</div></div>' +
    '<div class="hd-cell"><div class="k">MVP</div><div class="v">' + P.mvp + '</div><div class="s">共 ' + P.games + " 局中当选</div></div>" +
    '<div class="hd-cell"><div class="k">场均数据</div><div class="v">' + K.fmtInt(P.gold) + '</div><div class="s">经济 · 参团 ' + Math.round(P.part) + "%</div></div>" +
    "</div>";

  /* ---------- 赛季趋势（胜率折线） ---------- */
  var years = P.years || [];
  var trendHTML = "";
  if (years.length >= 2) {
    var W = 1040, H = 210, PL = 46, PR = 20, PT = 22, PB = 34;
    var n = years.length;
    var X = function (i) { return PL + (n === 1 ? 0 : i * (W - PL - PR) / (n - 1)); };
    var Y = function (p) { return PT + (1 - p) * (H - PT - PB); };
    var s = '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" aria-label="赛季胜率趋势">';
    [0.3, 0.5, 0.7].forEach(function (g) {
      s += '<line x1="' + PL + '" y1="' + Y(g).toFixed(1) + '" x2="' + (W - PR) + '" y2="' + Y(g).toFixed(1) + '" stroke="#1D2E47" stroke-dasharray="' + (g === 0.5 ? "0" : "4 6") + '"/>' +
        '<text x="' + (PL - 8) + '" y="' + (Y(g) + 4).toFixed(1) + '" text-anchor="end" font-size="10.5" fill="#6F84A3" font-family="Inter,monospace">' + (g * 100) + "%</text>";
    });
    var pts = years.map(function (y, i) { return X(i).toFixed(1) + "," + Y(y[2]).toFixed(1); }).join(" ");
    s += '<polyline points="' + pts + '" fill="none" stroke="#FFFFFF" stroke-width="2.4" stroke-linejoin="round"/>';
    years.forEach(function (y, i) {
      s += '<circle cx="' + X(i).toFixed(1) + '" cy="' + Y(y[2]).toFixed(1) + '" r="4" fill="#FFFFFF"/>' +
        '<text x="' + X(i).toFixed(1) + '" y="' + (H - 12) + '" text-anchor="middle" font-size="11.5" fill="#9FB3CE" font-family="Inter,monospace">' + y[0] + "</text>" +
        '<text x="' + X(i).toFixed(1) + '" y="' + (Y(y[2]) - 10).toFixed(1) + '" text-anchor="middle" font-size="11" fill="#EAF1FA" font-family="Inter,monospace">' + Math.round(y[2] * 100) + "%</text>";
    });
    s += "</svg>";
    trendHTML = '<div class="panel"><div class="panel-title">赛季胜率趋势 <em class="mono">逐年胜率 · 全赛事</em></div>' +
      '<div class="pl-trend">' + s + "</div></div>";
  }


  /* ---------- 逐年明细（胜率之外还有局数与 KDA，避免"只看折线"） ---------- */
  var yearTable = "";
  if (years.length) {
    yearTable = '<div class="panel" style="grid-column:1/-1"><div class="panel-title">逐年明细 <em class="mono">' +
      "全部赛事 " + P.games + ' 局</em></div>' +
      '<div class="yr-trend">' + years.map(function (y) {
        var maxG = Math.max.apply(null, years.map(function (r) { return r[1] || 1; }));
        return '<div class="yr-row"><span class="y mono">' + y[0] + "</span>" +
          '<span class="bar"><i style="width:' + Math.max(2, (y[1] || 0) / maxG * 100).toFixed(1) + '%"></i></span>' +
          '<span class="n mono">' + y[1] + " 局</span>" +
          '<span class="wr mono">' + K.pct(y[2], 1) + "</span>" +
          '<span class="ban mono">KDA ' + (y[3] != null ? Number(y[3]).toFixed(2) : "—") + "</span></div>";
      }).join("") + "</div></div>";
  }

  /* ---------- 同位置对比（这个位置里他排第几） ---------- */
  var posHTML = (function () {
    var all = ((K.scopeOf("all") || {}).players) || [];
    var peers = all.filter(function (p) { return p.pos === P.pos && p.games >= 20; });
    if (peers.length < 4) return "";
    var METRICS = [
      { k: "wr", label: "胜率", fmt: function (v) { return K.pct(v, 1); }, get: function (p) { return p.wr; } },
      { k: "kda", label: "KDA", fmt: function (v) { return Number(v).toFixed(2); }, get: function (p) { return p.kda; } },
      { k: "mvpRate", label: "MVP 率", fmt: function (v) { return (v * 100).toFixed(1) + "%"; },
        get: function (p) { return p.mvp / Math.max(1, p.games); } },
      { k: "part", label: "参团率", fmt: function (v) { return Number(v).toFixed(1) + "%"; }, get: function (p) { return p.part; } },
      { k: "dmg", label: "输出占比", fmt: function (v) { return Number(v).toFixed(1) + "%"; }, get: function (p) { return p.dmg; } }
    ];
    var self = peers.filter(function (p) { return p.name === P.name; })[0];
    function pctRank(arr, v) {
      var below = arr.filter(function (x) { return x < v; }).length;
      return arr.length ? below / arr.length : 0;
    }
    var rows = METRICS.map(function (m) {
      var vals = peers.map(m.get).filter(function (v) { return typeof v === "number" && isFinite(v); });
      var my = self ? m.get(self) : m.get({ games: P.games, wr: P.wr, kda: P.kda, mvp: P.mvp, part: P.part, dmg: 0 });
      var r = pctRank(vals, my);
      var mid = vals.slice().sort(function (a, b) { return a - b; })[Math.floor(vals.length / 2)];
      return '<div class="pos-row"><span class="k">' + m.label + "</span>" +
        '<span class="bar"><i style="width:' + Math.max(2, r * 100).toFixed(1) + '%"></i></span>' +
        '<span class="my mono">' + m.fmt(my) + "</span>" +
        '<span class="mid mono">位置中位 ' + m.fmt(mid) + "</span>" +
        '<span class="rk mono">超过 ' + Math.round(r * 100) + "%</span></div>";
    }).join("");
    return '<div class="panel" style="grid-column:1/-1"><div class="panel-title">同位置对比 <em class="mono">' +
      "全部赛事 · " + K.esc(P.pos || "同位置") + " · 样本 " + peers.length + " 人（≥20 局）</em></div>" +
      '<div class="pos-cmp">' + rows + "</div>" +
      '<div class="block-note mono">百分位 = 在该位置的所有选手中超过多少人；不做跨位置的横向比较（对位职责不同）。</div></div>';
  })();

  /* ---------- 常用英雄 ---------- */
  var heroesHTML = (P.heroes || []).map(function (h) {
    var ic = heroIcon[h[0]];
    return '<a class="pl-hero" href="hero.html?id=' + encodeURIComponent(h[0]) + '">' +
      (ic ? '<img src="' + K.esc(ic) + '" alt="" loading="lazy">' : "") +
      '<span class="nm">' + K.esc(h[0]) + "</span>" +
      '<span class="g mono">' + h[1] + " 局</span>" +
      '<span class="kda mono">KDA ' + (h[3] != null ? h[3].toFixed(2) : "—") + "</span>" +
      '<span class="wr mono">' + K.pct(h[2]) + "</span></a>";
  }).join("");
  var poolN = P.poolN || (P.heroes || []).length;

  /* ---------- 最近比赛 ---------- */
  var recentHTML = (P.recent || []).map(function (r) {
    return '<a class="pl-recent" href="game.html?id=' + encodeURIComponent(r[2]) + '">' +
      '<span class="d mono">' + K.esc(String(r[0]).slice(5)) + "</span>" +
      '<span class="vs">' + K.esc(r[3]) + " vs " + K.esc(r[4]) + "</span>" +
      '<span class="hero">' + (heroIcon[r[5]] ? '<img src="' + K.esc(heroIcon[r[5]]) + '" alt="">' : "") + K.esc(r[5]) + "</span>" +
      '<span class="res ' + (r[6] ? "w" : "l") + '">' + (r[6] ? "胜" : "负") + "</span>" +
      '<span class="kda mono">' + r[7] + "/" + r[8] + "/" + r[9] + "</span></a>";
  }).join("");

  $("#main").innerHTML = kpi + trendHTML + posHTML + yearTable +
    '<div class="pl-grid">' +
    '<div class="panel"><div class="panel-title">英雄池 <em class="mono">共 ' + poolN + " 个英雄 · 按使用局数展示前 " + (P.heroes || []).length + "</em></div>" +
    '<div class="pl-heroes">' + (heroesHTML || '<div class="empty-tip">暂无数据</div>') + "</div></div>" +
    '<div class="panel"><div class="panel-title">最近比赛 <em class="mono">点击进入对局详情</em></div>' +
    '<div class="pl-recents">' + (recentHTML || '<div class="empty-tip">暂无数据</div>') + "</div></div>" +
    "</div>";
  K.refresh();
})();
