
(function () {
  "use strict";
  var D = KPL.data, DT = KPL.details, K = KPL, $ = function (s) { return document.querySelector(s); };
  K.init();

  var season = D.season;

  /* ---------- 今日赛场（进行中优先置顶 + 未来场次带日期） ---------- */
  (function () {
    var ups = D.upcoming || [];
    var ALL = window.KPL_SCHEDULE_ALL || [];
    var todayIso = new Date().toISOString().slice(0, 10);
    var LIVE = ALL.filter(function (r) { return r.st === 1; });
    var liveIds = {};
    LIVE.forEach(function (r) { liveIds[r.matchId] = 1; });
    var future = ups.filter(function (u) { return !liveIds[u.matchId]; });
    if (!LIVE.length && !future.length) {
      $("#todayStrip").innerHTML = '<span class="today-label">' + K.icon("clock", 15) + "本赛季赛程已全部结束</span>";
      return;
    }
    var head, cards = [];
    if (LIVE.length) {
      head = '<span class="today-label"><i></i>' + K.esc(K.dateCN(todayIso)) + " · " + K.esc(K.weekdayCN(todayIso)) +
        " · <b style='color:var(--red)'>" + LIVE.length + " 场进行中</b></span>";
      LIVE.slice(0, 1).forEach(function (l) {
        cards.push({ mid: l.matchId, time: l.time, t1: l.team1, i1: l.icon1, t2: l.team2, i2: l.icon2,
                     live: true, s1: l.score1, s2: l.score2 });
      });
    } else {
      head = '<span class="today-label"><i></i>' + K.esc(K.dateCN(future[0].date)) + " · " + K.esc(K.weekdayCN(future[0].date)) +
        " · 下一场</span>";
    }
    future.slice(0, Math.max(1, 2 - cards.length)).forEach(function (u) {
      cards.push({ mid: u.matchId, time: u.time, t1: u.team1, i1: u.icon1, t2: u.team2, i2: u.icon2,
                   live: false, date: u.date });
    });
    var html = head;
    var cdTarget = null;
    html += cards.map(function (c, i) {
      var inner;
      if (c.live) {
        inner = '<a class="cd" href="match.html?id=' + K.esc(c.mid) + '" style="text-decoration:none">' + K.liveBadge() +
          ' <span class="mono" style="color:var(--ink);font-weight:800">' + c.s1 + " : " + c.s2 + "</span> " +
          '<span class="mono" style="color:var(--muted);font-size:11px">比分 →</span></a>';
      } else {
        var isToday = c.date === todayIso;
        if (!isToday) {
          inner = '<span class="cd mono" style="font-size:12px">' + K.esc(K.dateCN(c.date)) + " " + K.esc(c.time) + "</span>";
        } else if (i === (cards[0].live ? 1 : 0)) {
          cdTarget = new Date(c.date + "T" + (c.time || "17:00") + ":00");
          inner = '<span class="cd" id="cd0">—</span>';
        } else {
          inner = '<span class="cd">待开赛</span>';
        }
      }
      return '<div class="today-match" data-mid="' + K.esc(c.mid || "") + '">' +
        '<span class="t">' + K.esc(c.time) + "</span>" +
        (c.i1 ? '<img src="' + K.esc(c.i1) + '" alt="">' : "") +
        '<span class="tm">' + K.esc(c.t1) + " vs " + K.esc(c.t2) + "</span>" +
        (c.i2 ? '<img src="' + K.esc(c.i2) + '" alt="">' : "") +
        '<span class="tstat">' + inner + "</span></div>";
    }).join("");
    html += '<a class="btn sm ghost" style="margin-left:auto" href="schedule.html">全部赛程</a>';
    $("#todayStrip").innerHTML = html;
    var cdEl = document.getElementById("cd0");
    if (cdEl && cdTarget) K.countdown(cdTarget.getTime(), cdEl);
  })();

  /* ---------- 实时比分与状态覆盖（live.js，每 60 秒） ---------- */
  function applyTodayLive() {
    var sc = document.createElement("script");
    sc.src = "assets/live.js?ts=" + Date.now();
    sc.onload = function () {
      sc.remove();
      var L = window.KPL_LIVE || {};
      (L.today || []).forEach(function (t) {
        var slot = document.querySelector('.today-match[data-mid="' + t.matchId + '"] .tstat');
        if (slot && (t.st === 1 || t.st === 2)) {
          slot.innerHTML = '<a href="match.html?id=' + encodeURIComponent(t.matchId) + '" style="text-decoration:none" class="cd">' +
            (t.st === 1 ? K.liveBadge() : '<span class="chip done">已结束</span>') +
            ' <span class="mono" style="color:var(--gold);font-weight:800">' + t.score1 + " : " + t.score2 + "</span></a>";
        }
        /* 最新战报列表的比分覆盖 */
        var rr = document.querySelector('#recentList [data-mid="' + t.matchId + '"] .score');
        if (rr && (t.st === 1 || t.st === 2)) {
          rr.innerHTML = '<span class="' + (t.score1 > t.score2 ? "w" : "") + '">' + t.score1 +
            '</span> : <span class="' + (t.score2 > t.score1 ? "w" : "") + '">' + t.score2 + "</span>";
        }
        var row = document.querySelector('.up-row[data-mid="' + t.matchId + '"]');
        if (row) {
          var chip = row.querySelector(".chip");
          if (chip) {
            if (t.st === 1) {
              chip.outerHTML = '<a class="chip live" href="match.html?id=' + encodeURIComponent(t.matchId) +
                '" style="text-decoration:none"><i></i>进行中 ' + t.score1 + " : " + t.score2 + "</a>";
            } else if (t.st === 2) {
              chip.outerHTML = '<a class="chip done" href="match.html?id=' + encodeURIComponent(t.matchId) +
                '" style="text-decoration:none">已结束 ' + t.score1 + " : " + t.score2 + "</a>";
            }
          }
        }
      });
    };
    sc.onerror = function () { sc.remove(); };
    document.head.appendChild(sc);
  }
  applyTodayLive();
  setInterval(applyTodayLive, 30000);

  /* ---------- 首屏：赛事焦点（直播 > 今日/下一场 > 最近一场结果） ---------- */
  (function renderFocus() {
    var ALL = window.KPL_SCHEDULE_ALL || [];
    var todayIso = new Date().toISOString().slice(0, 10);
    var live = ALL.filter(function (r) { return r.st === 1; })[0];
    var today = ALL.filter(function (r) { return r.date === todayIso; })
      .sort(function (a, b) { return String(a.time).localeCompare(String(b.time)); });
    var nextUp = ALL.filter(function (r) { return !r.done && (r.date > todayIso || (r.date === todayIso && r.st !== 2)); })
      .sort(function (a, b) { return (a.date + a.time).localeCompare(b.date + b.time); })[0];
    var last = ALL.filter(function (r) { return r.done; })
      .sort(function (a, b) { return (b.date + b.time).localeCompare(a.date + a.time); })[0];
    var el = document.getElementById("focusHero");
    if (!el) return;

    function teamChip(name, icon) {
      return '<a class="fh-team" href="team.html?id=' + encodeURIComponent(name) + '">' +
        (icon ? '<img src="' + K.esc(icon) + '" alt="">' : "") + "<span>" + K.esc(name) + "</span></a>";
    }
    function covBadges(mid) { return K.coverageBadges(K.coverageMask(mid)); }

    if (live) {
      el.innerHTML = '<div class="fh"><div class="fh-kicker mono"><span class="dot-live"></span> 正在进行 · ' +
        K.esc(live.leagueName || "") + (live.stage ? " · " + K.esc(live.stage) : "") + "</div>" +
        '<div class="fh-vs">' + teamChip(live.team1, live.icon1) +
        '<span class="fh-score mono">' + live.score1 + " : " + live.score2 + "</span>" +
        teamChip(live.team2, live.icon2) + "</div>" +
        '<div class="fh-actions"><a class="btn primary sm" href="match.html?id=' + encodeURIComponent(live.matchId) +
        '">进入实时页面</a><span class="fh-note mono">第 ' + live.bo + " 局赛制 · 比分自动刷新</span></div>" +
        '</div>';
      return;
    }
    if (today.length) {
      var nextT = today.filter(function (r) { return r.st !== 2; })[0] || today[0];
      el.innerHTML = '<div class="fh"><div class="fh-kicker mono">今日赛程 · ' + K.dateCN(todayIso) + " " +
        K.weekdayCN(todayIso) + " · 共 " + today.length + " 场</div>" +
        '<div class="fh-today">' + today.map(function (r) {
          var done = r.st === 2;
          return '<a class="fh-tcard" href="match.html?id=' + encodeURIComponent(r.matchId) + '">' +
            '<span class="t mono">' + K.esc(r.time) + "</span>" +
            '<span class="tm">' + K.esc(r.team1) + " vs " + K.esc(r.team2) + "</span>" +
            '<span class="sc mono">' + (done ? r.score1 + ":" + r.score2 : "—") + "</span>" +
            '<span class="st">' + (done ? "已结束" : r.st === 1 ? "直播中" : "待开赛") + "</span></a>";
        }).join("") + "</div>" +
        '<div class="fh-actions"><a class="btn primary sm" href="schedule.html">赛事中心</a>' +
        (nextT && nextT.st === 1 ? '<span class="fh-note mono">正在进行：' + K.esc(nextT.team1) + " vs " + K.esc(nextT.team2) + "</span>"
          : '<span class="fh-note mono">下一场 ' + K.esc((nextUp || nextT || {}).time || "") + " " +
            K.esc(((nextUp || nextT || {}).team1 || "")) + " vs " + K.esc(((nextUp || nextT || {}).team2 || "")) + "</span>") +
        "</div></div>";
      return;
    }
    if (last) {
      var w = last.score1 > last.score2 ? last.team1 : last.team2;
      el.innerHTML = '<div class="fh"><div class="fh-kicker mono">最近一场 · ' + K.esc(last.date) + " " +
        K.esc(last.leagueName || "") + "</div>" +
        '<div class="fh-vs">' + teamChip(last.team1, last.icon1) +
        '<span class="fh-score mono">' + last.score1 + " : " + last.score2 + "</span>" +
        teamChip(last.team2, last.icon2) + "</div>" +
        '<div class="fh-actions"><a class="btn primary sm" href="match.html?id=' + encodeURIComponent(last.matchId) +
        '">看这场复盘</a><span class="fh-note mono">胜方 ' + K.esc(w) + " · " + covBadges(last.matchId) + "</span></div>" +
        (nextUp ? '<div class="fh-next mono">下一场：' + K.esc(nextUp.date) + " " + K.esc(nextUp.time) + " " +
          K.esc(nextUp.team1) + " vs " + K.esc(nextUp.team2) + "</div>" : "") +
        "</div>";
      return;
    }
    el.innerHTML = '<div class="fh"><div class="fh-kicker mono">赛事焦点</div>' +
      '<p style="color:var(--muted);font-size:13.5px">暂无赛程数据。</p></div>';
  })();

  /* ---------- 精选复盘（有分钟级数据的对局，按日期倒序取 4 场） ---------- */
  (function renderReplayPicks() {
    var el = document.getElementById("replayPicks");
    if (!el) return;
    var idx = window.KPL_REPLAY_INDEX || {};
    var rows = Object.keys(idx).map(function (k) { return Object.assign({ matchId: k }, idx[k]); })
      .sort(function (a, b) { return String(b.date).localeCompare(String(a.date)); }).slice(0, 4);
    if (!rows.length) {
      el.innerHTML = '<div class="empty-tip">暂无分钟级复盘数据</div>';
      return;
    }
    el.innerHTML = rows.map(function (r) {
      var n = (r.b || []).length;
      return '<a class="rp-pick" href="match.html?id=' + encodeURIComponent(r.matchId) + '">' +
        '<span class="d mono">' + K.esc(String(r.date).slice(5)) + "</span>" +
        '<span class="vs">' + K.esc(r.t1) + " vs " + K.esc(r.t2) + "</span>" +
        '<span class="n mono">' + n + " 局可复盘</span>" +
        '<span class="cov-wrap">' + K.coverageBadges(K.coverageMask(r.matchId)) + "</span>" +
        '<span class="go">进入 →</span></a>';
    }).join("");
  })();

  /* ---------- 轮播（产品文案） ---------- */
  var slides = [
    {
      kicker: season + " · 进行中",
      h: 'KPL 赛事数据，<span class="hl">一站查完。</span>',
      p: "赛程比分、战队与选手数据、英雄梯度、逐局复盘与胜负模拟——打开就能用。",
      cta: [["schedule.html", "查看今日赛程", "primary"], ["simulator.html", "试试模拟器", "ghost"]],
      mini: (function () {
        var T = (window.KPL_SEASONS && KPL_SEASONS.scopes.all.totals) || { matches: 2874, battles: 11100 };
        return [["大场", K.fmtInt(T.matches)], ["对局", K.fmtInt(T.battles)], ["选手", "600+ 人"], ["英雄", "130+ 个"]];
      })()
    },
    {
      kicker: "逐局复盘 · 分钟级",
      h: '每一局，<span class="hl">都能看到胜负是怎么失去的。</span>',
      p: "最近 14 场大场支持逐局复盘：胜率曲线、阶段切片、资源转折与 BP 阵容一屏看完。",
      cta: [["match.html?id=2026073103", "看一场翻盘局", "primary"], ["schedule.html", "选择比赛", "ghost"]],
      mini: [["可复盘详情", "14 场"], ["曲线粒度", "分钟级"], ["事件标记", "一血 / 资源 / 推塔"]]
    },
    {
      kicker: "榜单与梯度 · 实时滚动",
      h: '战队、选手、英雄，<span class="hl">每周都在变。</span>',
      p: "战队战力榜、英雄强度梯度、选手数据榜——每个榜单都能按赛季切换查看。",
      cta: [["teams.html", "战队排行榜", "primary"], ["heroes.html", "英雄梯度", "ghost"]],
      mini: [["覆盖", "2019–2026"], ["联赛", "33 个"], ["英雄图鉴", "130+ 个"]]
    }
  ];
  $("#slides").innerHTML = slides.map(function (s, i) {
    return '<div class="slide' + (i === 0 ? " on" : "") + '" data-i="' + i + '"><div class="wrap">' +
      '<div class="slide-kicker mono">' + K.esc(s.kicker) + "</div><h1>" + s.h + "</h1><p>" + K.esc(s.p) + "</p>" +
      '<div class="slide-mini">' + s.mini.map(function (m) {
        return "<span>" + K.esc(m[0]) + "<b>" + K.esc(m[1]) + "</b></span>";
      }).join("") + "</div>" +
      '<div class="slide-cta">' + s.cta.map(function (c) {
        return '<a class="btn ' + c[2] + '" href="' + c[0] + '">' + K.esc(c[1]) + "</a>";
      }).join("") + "</div></div></div>";
  }).join("");
  $("#carDots").innerHTML = slides.map(function (_, i) {
    return '<button data-i="' + i + '"' + (i === 0 ? ' class="on"' : "") + ' aria-label="第 ' + (i + 1) + ' 张"></button>';
  }).join("");
  var cur = 0, timer = null;
  function go(i) {
    cur = (i + slides.length) % slides.length;
    document.querySelectorAll(".slide").forEach(function (s) { s.classList.toggle("on", +s.getAttribute("data-i") === cur); });
    document.querySelectorAll(".car-dots button").forEach(function (b) { b.classList.toggle("on", +b.getAttribute("data-i") === cur); });
  }
  function auto() { timer = setInterval(function () { go(cur + 1); }, 7000); }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }
  $("#carPrev").addEventListener("click", function () { stop(); go(cur - 1); auto(); });
  $("#carNext").addEventListener("click", function () { stop(); go(cur + 1); auto(); });
  $("#carDots").addEventListener("click", function (e) {
    var b = e.target.closest("button"); if (!b) return; stop(); go(+b.getAttribute("data-i")); auto();
  });
  document.querySelector(".carousel").addEventListener("mouseenter", stop);
  document.querySelector(".carousel").addEventListener("mouseleave", auto);
  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) auto();

  /* ---------- 图标点缀 ---------- */
  $("#icSim").innerHTML = K.icon("sliders", 22);
  $("#icHero").innerHTML = K.icon("crown", 22);
  $("#icData").innerHTML = K.icon("chart", 22);
  $("#icCombo").innerHTML = K.icon("layers", 22);
  $("#icH2h").innerHTML = K.icon("shield", 22);
  $("#icGo4").innerHTML = K.icon("arrow", 16);
  $("#icGo5").innerHTML = K.icon("arrow", 16);
  ["icGo1", "icGo2", "icGo3"].forEach(function (id) { $("#" + id).innerHTML = K.icon("arrow", 18); });

  /* ---------- 最新战报 ---------- */
  $("#recentList").innerHTML = (D.recent || []).slice(0, 8).map(K.resultRow).join("");
  applyTodayLive();
  var groups = [];
  (D.upcoming || []).slice(0, 5).forEach(function (u) {
    var last = groups[groups.length - 1];
    if (last && last.date === u.date) last.items.push(u);
    else groups.push({ date: u.date, items: [u] });
  });
  $("#upcomingList").innerHTML = groups.map(function (g) {
    return '<div class="day"><div class="day-h">' + K.esc(K.dateCN(g.date)) +
      "<span>" + K.esc(K.weekdayCN(g.date)) + "</span></div>" +
      g.items.map(function (u) {
        return '<div class="up-row" data-mid="' + K.esc(u.matchId || "") + '"><div class="up-time">' + K.esc(u.time) + "</div>" +
          K.side(u.team1, u.icon1, false) +
          '<div style="text-align:center;color:var(--muted);font-size:11px">VS</div>' +
          K.side(u.team2, u.icon2, true) + '<div class="chip next">未开始</div></div>';
      }).join("") + "</div>";
  }).join("");

  /* ---------- 排行榜（按数据范围） ---------- */
  function renderBoards(scopeId) {
    var d = K.scopeOf(scopeId);
    /* 战队榜前 8（按单局胜率，样本 >= 30 局） */
    var teams = (d.teams || []).filter(function (t) { return t.games >= 30; })
      .slice().sort(function (a, b) { return b.wr - a.wr; }).slice(0, 8);
    $("#stTop").innerHTML = teams.map(function (t, i) {
      var tier = K.tierOf(t.wr);
      return "<tr>" +
        '<td class="num"><span class="rank' + (i < 3 ? " r" + (i + 1) : "") + '">' + (i + 1) + "</span></td>" +
        '<td><span class="team-cell">' + (t.icon ? '<img src="' + K.esc(t.icon) + '" alt="" loading="lazy">' : "") +
        K.esc(t.team) + "</span></td>" +
        '<td class="num">' + t.mWin + "-" + t.mLoss + "</td>" +
        '<td class="num">' + K.pct(t.wr) + "</td>" +
        '<td class="num">' + t.games + "</td>" +
        '<td class="num" style="color:' + (t.goldDiff >= 0 ? "var(--blue)" : "var(--muted)") + '">' + K.signed(t.goldDiff) + "</td>" +
        '<td><span class="tier ' + tier + '">' + tier + "</span></td></tr>";
    }).join("");
    /* 热门英雄 top 12（按出场局数） */
    $("#heroTop").innerHTML = (d.heroes || []).slice(0, 12).map(K.heroCard).join("");
    /* 选手榜前 8（按 KDA，样本 >= 30 局） */
    var players = (d.players || []).filter(function (p) { return p.games >= 30; })
      .slice().sort(function (a, b) { return b.kda - a.kda; }).slice(0, 8);
    $("#plTop").innerHTML = players.map(function (p, i) {
      var ava = p.icon ? '<img class="p-ava" src="' + K.esc(p.icon) + '" alt="" loading="lazy">'
        : '<span class="p-ava ph">' + K.esc(String(p.name).slice(0, 1)) + "</span>";
      return '<a class="player reveal" href="player.html?id=' + encodeURIComponent(p.name) + '" style="transition-delay:' + Math.min(i * 22, 200) + 'ms">' + ava +
        '<div class="p-main"><div class="p-top"><span class="p-name"><span class="nm">' + K.esc(p.name) + "</span>" +
        (p.pos ? "<em>" + K.esc(p.pos) + "</em>" : "") + "</span>" +
        '<span class="p-kda">' + p.kda.toFixed(1) + "<small>KDA</small></span></div>" +
        '<div class="p-team">' + (p.teamIcon ? '<img src="' + K.esc(p.teamIcon) + '" alt="">' : "") +
        "<b>" + K.esc(p.team) + "</b><span>· " + p.games + " 局 · 胜率 " + K.pct(p.wr, 0) + " · MVP " + p.mvp + "</span></div></div></a>";
    }).join("");
    K.refresh();
  }
  renderBoards(K.scopeBar("#scopeBar", renderBoards));

  K.refresh();
})();
