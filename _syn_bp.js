
(function () {
  "use strict";
  var D = KPL.data, K = KPL, $ = function (s) { return document.querySelector(s); };
  K.init();
  var BP = window.KPL_BP;
  document.querySelector(".page-hero p").innerHTML =
    document.querySelector(".page-hero p").innerHTML.replace("{N}", K.fmtInt(BP.totalBattles));
  $("#hvNote").textContent = "谁在 ban 它 / 谁在选它（基于全部 " + K.fmtInt(BP.totalBattles) + " 局）";

  var heroIcon = {};
  ((K.scopeOf("all") || {}).heroes || []).forEach(function (h) { heroIcon[h.name] = h.icon; });
  var teamIcon = {};
  ((K.scopeOf("all") || {}).teams || []).forEach(function (t) { teamIcon[t.team] = t.icon; });

  /* ---------- 维度选项 ---------- */
  var teamSet = {}, yearSet = {}, stageSet = {};
  BP.games.forEach(function (g) {
    teamSet[g[3]] = 1; teamSet[g[4]] = 1;
    if (g[0]) yearSet[g[0]] = 1;
    if (g[2]) stageSet[g[2]] = 1;
  });
  var teamNames = Object.keys(teamSet).sort(function (a, b) { return a.localeCompare(b, "zh"); });
  var years = Object.keys(yearSet).sort().reverse();
  var stages = Object.keys(stageSet).sort();

  var selTeam = $("#selTeam"), selOpp = $("#selOpp"), selYear = $("#selYear"),
      selLeague = $("#selLeague"), selStage = $("#selStage"),
      selGame = $("#selGame"), selSide = $("#selSide"), selResult = $("#selResult");
  selTeam.innerHTML = teamNames.map(function (t) { return "<option>" + K.esc(t) + "</option>"; }).join("");
  selTeam.value = teamNames.indexOf("重庆狼队") >= 0 ? "重庆狼队" : teamNames[0];
  selOpp.insertAdjacentHTML("beforeend", teamNames.map(function (t) { return "<option>" + K.esc(t) + "</option>"; }).join(""));
  selYear.insertAdjacentHTML("beforeend", years.map(function (y) { return "<option>" + y + "</option>"; }).join(""));
  selStage.innerHTML = '<option value="">全部赛段</option>' +
    stages.map(function (s) { return "<option>" + K.esc(s) + "</option>"; }).join("");

  function fillLeagues() {
    var y = selYear.value;
    var cur = selLeague.value;
    var ids = {};
    BP.games.forEach(function (g) { if (!y || g[0] === y) ids[g[1]] = 1; });
    var keys = Object.keys(ids).sort().reverse();
    selLeague.innerHTML = '<option value="">全部赛事</option>' + keys.map(function (id) {
      return '<option value="' + id + '">' + K.esc(BP.leagues[id] || id) + "</option>";
    }).join("");
    if (keys.indexOf(cur) >= 0) selLeague.value = cur;
  }
  fillLeagues();

  var allHeroes = BP.heroes.slice(0, 140);
  $("#manualHero").insertAdjacentHTML("beforeend",
    allHeroes.map(function (h) { return "<option>" + K.esc(h) + "</option>"; }).join(""));
  $("#selHero").innerHTML = allHeroes.map(function (h) { return "<option>" + K.esc(h) + "</option>"; }).join("");
  $("#selHero").value = allHeroes.indexOf("鲁班大师") >= 0 ? "鲁班大师" : allHeroes[0];

  var picked = {}, step = 0, rowsCache = [], aggCached = null;

  function cond() {
    return {
      team: selTeam.value, opp: selOpp.value, year: selYear.value,
      league: selLeague.value, stage: selStage.value,
      gameNo: selGame.value, side: selSide.value, result: selResult.value,
    };
  }

  function filterGames(c) {
    var out = [];
    for (var i = 0; i < BP.games.length; i++) {
      var g = BP.games[i];
      if (c.year && g[0] !== c.year) continue;
      if (c.league && g[1] !== c.league) continue;
      if (c.stage && g[2] !== c.stage) continue;
      if (g[3] !== c.team && g[4] !== c.team) continue;
      var myCamp = g[3] === c.team ? 1 : 2;
      if (c.opp) {
        var oppName = myCamp === 1 ? g[4] : g[3];
        if (oppName !== c.opp) continue;
      }
      if (c.gameNo) {
        if (c.gameNo === "6+") { if (g[5] < 6) continue; }
        else if (String(g[5]) !== c.gameNo) continue;
      }
      if (c.side && String(myCamp) !== c.side) continue;
      if (c.result === "win" && g[6] !== myCamp) continue;
      if (c.result === "lose" && g[6] === myCamp) continue;
      out.push(g);
    }
    return out;
  }

  function aggregate(rows, team) {
    var myBan = {}, myPick = {}, oppBan = {};
    var handSub = [];
    for (var k = 0; k < 20; k++) handSub.push({});
    rows.forEach(function (g) {
      var myCamp = g[3] === team ? 1 : 2;
      var hands = g[7].split(";");
      for (var k = 0; k < hands.length; k++) {
        var p = hands[k].split(",");
        var act = +p[0], camp = +p[1], hero = BP.heroes[+p[2]];
        if (!hero) continue;
        handSub[k][hero] = (handSub[k][hero] || 0) + 1;
        if (camp === myCamp) {
          if (act === 0) myBan[hero] = (myBan[hero] || 0) + 1;
          else myPick[hero] = (myPick[hero] || 0) + 1;
        } else if (act === 0) {
          oppBan[hero] = (oppBan[hero] || 0) + 1;
        }
      }
    });
    return { myBan: myBan, myPick: myPick, oppBan: oppBan, handSub: handSub, n: rows.length };
  }

  function topN(map, n) {
    return Object.keys(map).map(function (h) { return [h, map[h]]; })
      .sort(function (a, b) { return b[1] - a[1]; }).slice(0, n);
  }

  function predict(k, agg, c, actorTeam) {
    var globalRows = BP.prior[k] || [];
    var globalRate = {};
    globalRows.forEach(function (r) { globalRate[r[0]] = r[2]; });
    var sub = agg.handSub[k] || {};
    var subTotal = agg.n || 0;
    var alpha = 15;
    var teamHand = {}, teamTotal = 0;
    if (actorTeam) {
      rowsCache.forEach(function (g) {
        var actorCamp = g[3] === actorTeam ? 1 : (g[4] === actorTeam ? 2 : 0);
        if (!actorCamp) return;
        var cell = g[7].split(";")[k];
        if (!cell) return;
        var q = cell.split(",");
        if (+q[1] === actorCamp) {
          var h = BP.heroes[+q[2]];
          teamHand[h] = (teamHand[h] || 0) + 1;
          teamTotal++;
        }
      });
    }
    var out = [], seen = {};
    function score(hero) {
      var gRate = globalRate[hero] || 0.0005;
      var sRate = ((sub[hero] || 0) + alpha * gRate * subTotal) / (subTotal + alpha || 1);
      var tRate = (teamHand[hero] || 0) / Math.max(1, teamTotal);
      return (sRate + 0.002) * (1 + tRate * 50);
    }
    Object.keys(sub).forEach(function (h) {
      if (picked[h] || seen[h]) return;
      seen[h] = 1; out.push({ h: h, p: score(h) });
    });
    Object.keys(teamHand).forEach(function (h) {
      if (picked[h] || seen[h]) return;
      seen[h] = 1; out.push({ h: h, p: score(h) });
    });
    globalRows.forEach(function (r) {
      if (picked[r[0]] || seen[r[0]]) return;
      seen[r[0]] = 1; out.push({ h: r[0], p: score(r[0]) });
    });
    var total = out.reduce(function (s, x) { return s + x.p; }, 0) || 1;
    out.forEach(function (x) { x.p /= total; });
    out.sort(function (a, b) { return b.p - a.p; });
    return out.slice(0, 8);
  }

  function chip(h, num, cls) {
    return '<span class="bp2-chip ' + (cls || "") + '">' +
      (heroIcon[h] ? '<img src="' + K.esc(heroIcon[h]) + '" alt="" loading="lazy">' : "") +
      K.esc(h) + '<b>' + num + "</b></span>";
  }

  function renderProfiles(agg, c) {
    var desc = [];
    if (c.opp) desc.push("对阵 " + c.opp);
    if (c.year) desc.push(c.year + " 赛季");
    if (c.league) desc.push(BP.leagues[c.league] || c.league);
    if (c.stage) desc.push(c.stage);
    if (c.gameNo) desc.push(c.gameNo === "6+" ? "第 6 局+" : "第 " + c.gameNo + " 局");
    if (c.side) desc.push(c.side === "1" ? "蓝方" : "红方");
    if (c.result) desc.push(c.result === "win" ? "赢下的局" : "输掉的局");
    var html = '<div class="bp2-panel" style="margin-bottom:14px">' +
      '<div class="pt">' + (teamIcon[c.team] ? '<img src="' + K.esc(teamIcon[c.team]) + '" alt="">' : "") + K.esc(c.team) +
      ' <span class="mono" style="color:var(--muted);font-weight:400;font-size:11.5px">' +
      (desc.length ? "条件：" + desc.join(" · ") : "条件：全部") + " · 共 " + agg.n + " 局样本</span></div>";
    if (!agg.n) {
      html += '<div class="empty-tip">该条件下没有样本，请放宽筛选</div></div>';
      $("#profiles").innerHTML = html;
      return;
    }
    html += '<div class="bp2-cap"><span class="dot red"></span>最爱禁用（该战队主动 ban 掉）</div><div class="bp2-chips">' +
      topN(agg.myBan, 8).map(function (r) { return chip(r[0], r[1]); }).join("") + "</div>" +
      '<div class="bp2-cap"><span class="dot red"></span>最常被对手禁用（对手 ban 掉它的英雄）</div><div class="bp2-chips">' +
      topN(agg.oppBan, 8).map(function (r) { return chip(r[0], r[1], "fall"); }).join("") + "</div>" +
      '<div class="bp2-cap"><span class="dot gold"></span>最爱选用（pick 出场）</div><div class="bp2-chips">' +
      topN(agg.myPick, 8).map(function (r) { return chip(r[0], r[1]); }).join("") + "</div></div>";
    $("#profiles").innerHTML = html;
  }

  /* ---------- 英雄反向查询（全量，不受筛选影响） ---------- */
  var heroAggCache = null;
  function buildHeroIndex() {
    var banBy = {}, pickBy = {}, posCnt = [];
    for (var k = 0; k < 20; k++) posCnt.push({});
    BP.games.forEach(function (g) {
      var hands = g[7].split(";");
      for (var k = 0; k < hands.length; k++) {
        var p = hands[k].split(",");
        var act = +p[0], camp = +p[1], hero = BP.heroes[+p[2]];
        if (!hero) continue;
        var team = camp === 1 ? g[3] : g[4];
        if (act === 0) {
          if (!banBy[hero]) banBy[hero] = {};
          banBy[hero][team] = (banBy[hero][team] || 0) + 1;
        } else {
          if (!pickBy[hero]) pickBy[hero] = {};
          pickBy[hero][team] = (pickBy[hero][team] || 0) + 1;
        }
        posCnt[k][hero] = (posCnt[k][hero] || 0) + 1;
      }
    });
    heroAggCache = { banBy: banBy, pickBy: pickBy, posCnt: posCnt };
  }

  function renderHeroView() {
    if (!heroAggCache) buildHeroIndex();
    var hero = $("#selHero").value;
    function rows(map) {
      if (!map) return '<div class="empty-tip" style="padding:10px">暂无记录</div>';
      return Object.keys(map).map(function (t) { return [t, map[t]]; })
        .sort(function (a, b) { return b[1] - a[1]; }).slice(0, 6).map(function (r) {
          return '<div class="hv-row"><span class="n">' +
            (teamIcon[r[0]] ? '<img src="' + K.esc(teamIcon[r[0]]) + '" alt="">' : "") +
            "<span>" + K.esc(r[0]) + '</span></span><span class="c">' + r[1] + " 次</span></div>";
        }).join("");
    }
    $("#hvBan").innerHTML = rows(heroAggCache.banBy[hero]);
    $("#hvPick").innerHTML = rows(heroAggCache.pickBy[hero]);
    var pos = heroAggCache.posCnt.map(function (m, k) { return [k, m[hero] || 0]; })
      .filter(function (r) { return r[1] > 0; }).sort(function (a, b) { return b[1] - a[1]; }).slice(0, 4)
      .map(function (r) {
        var tpl = BP.template[r[0]];
        return '<span class="bp2-chip"><span class="act-badge ' + (tpl[0] === 0 ? "ban" : "pick") + '" style="min-width:0">' +
          (tpl[0] === 0 ? "禁" : "选") + '</span>第 ' + (r[0] + 1) + " 手（" + (tpl[1] === 1 ? "蓝" : "红") + "）<b>" + r[1] + "</b></span>";
      }).join("");
    $("#hvPos").innerHTML = pos || '<span class="mono" style="color:var(--muted)">—</span>';
  }

  function renderBoard() {
    $("#board").innerHTML = BP.template.map(function (tpl, k) {
      var act = tpl[0] === 0 ? "禁" : "选";
      var camp = tpl[1];
      var hero = null;
      for (var h in picked) if (picked[h][0] === k) { hero = h; break; }
      var cls = "bp-slot " + (camp === 1 ? "blue" : "red") + (tpl[0] === 0 ? " ban-slot" : " pick-slot") +
        (hero ? " filled" : "") + (k === step ? " now" : "");
      return '<div class="' + cls + '"><div class="k"><span class="act-badge ' + (tpl[0] === 0 ? "ban" : "pick") + '">' +
        act + "</span>" + (k + 1) + " · " + (camp === 1 ? "蓝" : "红") + "</div>" +
        (hero ? '<div class="h">' + (heroIcon[hero] ? '<img src="' + K.esc(heroIcon[hero]) + '" alt="">' : "") + K.esc(hero) + "</div>"
              : '<div class="h" style="color:var(--muted);font-weight:400">' + (k === step ? "← 当前" : "—") + "</div>") +
        "</div>";
    }).join("");
  }

  function renderNow(agg, c) {
    var card = $("#nowCard");
    if (step >= BP.template.length) {
      var rowsx = [1, 2].map(function (camp) {
        var heroes = [];
        for (var h in picked) if (picked[h][1] === camp) heroes.push(h);
        return "<div><b>" + (camp === 1 ? "蓝方" : "红方") + "</b>：" + heroes.join("、") + "</div>";
      }).join("");
      card.innerHTML = '<div class="ask">BP 已完成 ✓</div>' +
        '<div style="margin-top:8px;display:flex;flex-direction:column;gap:6px;font-size:13px">' + rowsx + "</div>";
      return;
    }
    var tpl = BP.template[step];
    var actTxt = tpl[0] === 0 ? "禁用" : "选用";
    var campTxt = tpl[1] === 1 ? "蓝方" : "红方";
    var actorTeam = tpl[1] === 1 ? c.team : (c.opp || null);
    var team = actorTeam || "对位战队（未指定对手）";
    var preds = predict(step, agg, c, actorTeam);
    var hint = agg.n < 10 ? ' <span style="color:var(--orange)">（样本偏少，已平滑到全局）</span>' : "";
    var actBadge = tpl[0] === 0 ? '<span class="act-badge ban">禁用</span>' : '<span class="act-badge pick">选用</span>';
    card.innerHTML = '<div class="ask">第 ' + (step + 1) + ' 手 · ' + campTxt + " <b>" + K.esc(team) + "</b> " + actBadge + hint +
      ' <span class="mono" style="color:var(--muted);font-weight:400">（点预测行落子）</span></div>' +
      '<div style="margin-top:8px">' + preds.map(function (x) {
        return '<div class="pred-row" data-hero="' + K.esc(x.h) + '">' +
          '<span class="n">' + (heroIcon[x.h] ? '<img src="' + K.esc(heroIcon[x.h]) + '" alt="" loading="lazy">' : "") +
          "<span>" + K.esc(x.h) + "</span></span>" +
          '<span class="bar"><i style="width:' + Math.max(2, x.p * 100).toFixed(1) + '%"></i></span>' +
          '<span class="p">' + (x.p * 100).toFixed(1) + "%</span></div>";
      }).join("") + "</div>";
    card.querySelectorAll(".pred-row").forEach(function (el) {
      el.addEventListener("click", function () { place(el.getAttribute("data-hero")); });
    });
  }

  function place(hero) {
    if (step >= BP.template.length || picked[hero]) return;
    picked[hero] = [step, BP.template[step][1]];
    step++;
    renderBoard();
    renderNow(aggCached, cond());
  }

  function refresh() {
    var c = cond();
    rowsCache = filterGames(c);
    aggCached = aggregate(rowsCache, c.team);
    var tag = $("#sampleTag");
    tag.textContent = "命中 " + aggCached.n + " 局样本" + (aggCached.n < 10 && aggCached.n > 0 ? " · 样本偏少" : "");
    tag.className = "sample-tag" + (aggCached.n < 10 ? " warn" : "");
    renderProfiles(aggCached, c);
    renderBoard();
    renderNow(aggCached, c);
    /* 数据简报 */
    if (aggCached.n) {
      var mb = topN(aggCached.myBan, 1)[0];
      var mp = topN(aggCached.myPick, 1)[0];
      var ob = topN(aggCached.oppBan, 1)[0];
      K.brief("#brief", "当前条件命中 <b>" + aggCached.n + "</b> 局 BP。" + K.esc(c.team) + " 最爱禁用「" + (mb ? "<b>" + K.esc(mb[0]) + "</b>（" + mb[1] + " 次）" : "—") +
        "」，最爱选「" + (mp ? "<b>" + K.esc(mp[0]) + "</b>（" + mp[1] + " 次）" : "—") + "」；对手最常针对禁用的是「" +
        (ob ? "<b>" + K.esc(ob[0]) + "</b>（" + ob[1] + " 次）" : "—") + "」。换对手或局序，结论实时重算。");
    } else {
      K.brief("#brief", "当前条件下没有 BP 样本，放宽筛选试试。");
    }
  }

  function autoFill() {
    while (step < BP.template.length) {
      var c2 = cond();
      var actor = BP.template[step][1] === 1 ? c2.team : (c2.opp || null);
      var preds = predict(step, aggCached, c2, actor);
      if (!preds.length) break;
      place(preds[0].h);
    }
  }

  function resetSim() {
    picked = {};
    step = 0;
    renderBoard();
    renderNow(aggCached, cond());
  }

  var playTimer = null;
  $("#playBtn").addEventListener("click", function () {
    var btn = this;
    if (playTimer) {
      clearInterval(playTimer);
      playTimer = null;
      btn.textContent = "▶ 播放（每秒一步）";
      return;
    }
    btn.textContent = "⏸ 暂停";
    playTimer = setInterval(function () {
      if (step >= BP.template.length) {
        clearInterval(playTimer);
        playTimer = null;
        btn.textContent = "▶ 播放（每秒一步）";
        return;
      }
      var c2 = cond();
      var actor = BP.template[step][1] === 1 ? c2.team : (c2.opp || null);
      var preds = predict(step, aggCached, c2, actor);
      if (preds.length) place(preds[0].h);
    }, 1000);
  });
  $("#resetBtn").addEventListener("click", function () {
    if (playTimer) { clearInterval(playTimer); playTimer = null; $("#playBtn").textContent = "▶ 播放（每秒一步）"; }
    resetSim();
  });
  $("#autoBtn").addEventListener("click", autoFill);
  $("#manualBtn").addEventListener("click", function () {
    var h = $("#manualHero").value;
    if (h) { place(h); $("#manualHero").value = ""; }
  });
  $("#selHero").addEventListener("change", renderHeroView);
  selYear.addEventListener("change", function () { fillLeagues(); resetSim(); refresh(); });
  ["selTeam", "selOpp", "selLeague", "selStage", "selGame", "selSide", "selResult"].forEach(function (id) {
    $("#" + id).addEventListener("change", function () { resetSim(); refresh(); });
  });

  renderHeroView();
  refresh();

  /* ================= V4：对阵假设工作台 ================= */
  (function bench() {
    var TD = window.KPL_TEAM_DATA || {};
    var S = window.KPL_SEASONS || { scopes: {} };
    var SCOPES = [
      ["all", "全部赛事"],
      ["2026", "2026 年"], ["2025", "2025 年"], ["2024", "2024 年"], ["2023", "2023 年"]
    ];
    var SHRINK = 25;          // 先验收缩：英雄样本越少越贴近球队总体胜率
    var PICK_W = 0.9, BAN_W = 1.1;

    var logit = function (p) { p = Math.min(Math.max(p, 1e-4), 1 - 1e-4); return Math.log(p / (1 - p)); };
    var sig = function (x) { return 1 / (1 + Math.exp(-x)); };
    var pct1 = function (v) { return (v * 100).toFixed(1) + "%"; };

    function teamsOf(scope) {
      var d = S.scopes[scope] || S.scopes.all || {};
      return (d.teams || []).filter(function (t) { return t.games >= 10; })
        .sort(function (a, b) { return b.games - a.games; });
    }
    function teamRow(scope, name) {
      var d = S.scopes[scope] || S.scopes.all || {};
      return (d.teams || []).filter(function (t) { return t.team === name; })[0] || null;
    }
    function heroLeague(scope) {
      var d = S.scopes[scope] || S.scopes.all || {};
      var map = {};
      (d.heroes || []).forEach(function (h) { map[h.name] = h; });
      return map;
    }
    var LEAGUE_CACHE = {};
    function leagueHeroes(scope) {
      if (!LEAGUE_CACHE[scope]) LEAGUE_CACHE[scope] = heroLeague(scope);
      return LEAGUE_CACHE[scope];
    }

    /* 某队某英雄的收缩后胜率与"相对球队基准"的 log-odds 边际 */
    function heroEdge(team, hero, teamRowObj, scope) {
      var pool = (TD[team] || {}).h || [];
      var hit = pool.filter(function (r) { return r[0] === hero; })[0];
      var lg = leagueHeroes(scope)[hero];
      var prior = lg && lg.wr ? lg.wr : (teamRowObj ? teamRowObj.wr : 0.5);
      var n = hit ? hit[1] : 0, w = hit ? hit[2] : 0;
      var p = (w + SHRINK * prior) / (n + SHRINK);
      var base = teamRowObj ? Math.min(Math.max(teamRowObj.wr, 0.2), 0.8) : 0.5;
      var edge = logit(p) - logit(base);
      var usage = teamRowObj && teamRowObj.games ? Math.min(1, n / Math.max(1, teamRowObj.games) * 3) : 0;
      return { hero: hero, n: n, w: w, p: p, edge: edge, usage: usage };
    }

    function fillSelect(el, items, keep) {
      var cur = keep ? el.value : "";
      el.innerHTML = items.map(function (it) {
        return '<option value="' + K.esc(it[0] || it) + '">' + K.esc(it[1] || it) + "</option>";
      }).join("");
      if (cur) el.value = cur;
    }

    var $id = function (x) { return document.getElementById(x); };

    function refreshHeroSelects() {
      var A = $id("wbA").value, B = $id("wbB").value;
      var poolA = (((TD[A] || {}).h) || []).map(function (r) { return r[0]; });
      var poolB = (((TD[B] || {}).h) || []).map(function (r) { return r[0]; });
      var optA = [["", "— 不假设 —"]].concat(poolA.slice(0, 40).map(function (h) { return [h, h]; }));
      var optB = [["", "— 不假设 —"]].concat(poolB.slice(0, 40).map(function (h) { return [h, h]; }));
      ["wbA1", "wbA2"].forEach(function (id2) { fillSelect($id(id2), optA, true); });
      ["wbB1", "wbB2"].forEach(function (id2) { fillSelect($id(id2), optB, true); });
      fillSelect($id("wbBanA"), optB, true);   // A 禁 B 的英雄
      fillSelect($id("wbBanB"), optA, true);   // B 禁 A 的英雄
    }

    function compute() {
      var scope = $id("wbScope").value;
      var A = $id("wbA").value, B = $id("wbB").value;
      if (A === B) { $id("wbResult").innerHTML = '<div class="empty-tip">A/B 不能是同一支战队</div>'; return; }
      var ra = teamRow(scope, A) || teamRow("all", A);
      var rb = teamRow(scope, B) || teamRow("all", B);
      if (!ra || !rb) { $id("wbResult").innerHTML = '<div class="empty-tip">该范围内缺少战队样本</div>'; return; }

      var baseLogit = logit(ra.wr) - logit(rb.wr);
      var p0 = sig(baseLogit);
      var rows = [];
      var dLogit = 0;
      function addPick(team, hero, rowSelf, sign, kind) {
        if (!hero) return;
        var e = heroEdge(team, hero, rowSelf, scope);
        var contrib = sign * e.edge * (kind === "ban" ? BAN_W * Math.max(0.35, e.usage) : PICK_W);
        dLogit += contrib;
        rows.push({
          team: team, hero: hero, n: e.n, wr: e.p, edge: e.edge, contrib: contrib, kind: kind
        });
      }
      addPick(A, $id("wbA1").value, ra, +1, "pick");
      addPick(A, $id("wbA2").value, ra, +1, "pick");
      addPick(B, $id("wbB1").value, rb, -1, "pick");
      addPick(B, $id("wbB2").value, rb, -1, "pick");
      addPick(B, $id("wbBanA").value, rb, -1, "ban");
      addPick(A, $id("wbBanB").value, ra, +1, "ban");

      var p1 = sig(baseLogit + dLogit);
      var dpp = (p1 - p0) * 100;

      var bar = function (p) {
        return '<div class="wb-bar"><i style="width:' + (p * 100).toFixed(1) + '%"></i>' +
          '<span class="wb-mid"></span></div>';
      };
      var detail = rows.length ? '<table class="tbl wb-tbl"><thead><tr><th>方</th><th>英雄</th><th>类型</th>' +
        '<th class="num">队伍历史</th><th class="num">收缩胜率</th><th class="num">对胜率影响</th></tr></thead><tbody>' +
        rows.map(function (r) {
          var sign = r.contrib >= 0 ? "+" : "";
          var pp = (sig(baseLogit + r.contrib) - p0) * 100;  // 单条边际的近似影响
          return "<tr><td>" + K.esc(r.team) + "</td><td>" + K.esc(r.hero) + "</td>" +
            "<td>" + (r.kind === "ban" ? "禁用对手" : "选用") + "</td>" +
            '<td class="num mono">' + r.n + " 局</td>" +
            '<td class="num mono">' + pct1(r.wr) + "</td>" +
            '<td class="num mono" style="color:' + (pp >= 0 ? "#7BD88F" : "#FF7A7E") + '">' +
            sign + pp.toFixed(1) + " pp</td></tr>";
        }).join("") + "</tbody></table>"
        : '<div class="empty-tip">还没有假设。选几个关键英雄，看看胜率会怎么走。</div>';

      $id("wbResult").innerHTML =
        '<div class="wb-head">' +
        '<div class="wb-side"><div class="wb-t">' + K.esc(A) + '</div><div class="wb-sub mono">' +
        ra.games + " 局 · 胜率 " + pct1(ra.wr) + "</div>" + bar(p1) + "</div>" +
        '<div class="wb-mid-col"><div class="wb-p0 mono">赛前基准 ' + pct1(p0) + "</div>" +
        '<div class="wb-p1">' + pct1(p1) + "</div>" +
        '<div class="wb-d mono" style="color:' + (dpp >= 0 ? "#7BD88F" : "#FF7A7E") + '">' +
        (dpp >= 0 ? "+" : "") + dpp.toFixed(1) + " pp</div></div>" +
        '<div class="wb-side r"><div class="wb-t">' + K.esc(B) + '</div><div class="wb-sub mono">' +
        rb.games + " 局 · 胜率 " + pct1(rb.wr) + "</div>" +
        '<div class="wb-bar r"><i style="width:' + ((1 - p1) * 100).toFixed(1) + '%"></i></div></div>' +
        "</div>" + detail;

      // 替代方案
      ["A", "B"].forEach(function (side) {
        var team = side === "A" ? A : B;
        var row = side === "A" ? ra : rb;
        var pool = ((TD[team] || {}).h || []).map(function (r) { return heroEdge(team, r[0], row, scope); })
          .filter(function (e) { return e.n >= 5; })
          .sort(function (x, y) { return y.edge - x.edge; }).slice(0, 6);
        var html = pool.length ? '<div class="usage">' + pool.map(function (e) {
          var pp = (sig(baseLogit + e.edge * PICK_W * (side === "A" ? 1 : -1)) - p0) * 100;
          return '<a href="hero.html?id=' + encodeURIComponent(e.hero) + '">' +
            '<span class="nm">' + K.esc(e.hero) + "</span>" +
            '<span class="n">' + e.n + " 局</span>" +
            '<span class="wr">' + pct1(e.p) + "</span>" +
            '<span class="mono" style="font-size:11.5px;color:' + (pp >= 0 ? "#7BD88F" : "#FF7A7E") + '">' +
            (pp >= 0 ? "+" : "") + pp.toFixed(1) + "pp</span></a>";
        }).join("") + "</div>"
          : '<div class="empty-tip">该队在所选范围内样本不足</div>';
        $id("wbAlt" + side).innerHTML = html;
      });

      $id("wbFoot").textContent = "口径：先验收缩 k=" + SHRINK + "，选用权重 ×" + PICK_W + "、禁用权重 ×" + BAN_W +
        "，log-odds 相加后转概率。边际来自该队历史使用该英雄的胜率，未考虑版本、阵容联动与对手反制，不等于因果结论。";
    }

    function boot() {
      fillSelect($id("wbScope"), SCOPES);
      var ts = teamsOf("all").map(function (t) { return [t.team, t.team]; });
      if (!ts.length) { $id("wbResult").innerHTML = '<div class="empty-tip">缺少战队数据</div>'; return; }
      fillSelect($id("wbA"), ts);
      fillSelect($id("wbB"), ts);
      if (ts.length > 1) $id("wbB").value = ts[1][0];
      refreshHeroSelects();
      compute();
      ["wbScope", "wbA", "wbB"].forEach(function (id2) {
        $id(id2).addEventListener("change", function () { refreshHeroSelects(); compute(); });
      });
      ["wbA1", "wbA2", "wbB1", "wbB2", "wbBanA", "wbBanB"].forEach(function (id2) {
        $id(id2).addEventListener("change", compute);
      });
    }
    boot();
  })();
})();
