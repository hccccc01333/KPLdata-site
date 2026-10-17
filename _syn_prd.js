
(function () {
  "use strict";
  var D = KPL.data, K = KPL, $ = function (s) { return document.querySelector(s); };
  K.init();
  var P = window.KPL_PREDICT;

  var teamIcon = {};
  ((K.scopeOf("all") || {}).teams || []).forEach(function (t) { teamIcon[t.team] = t.icon; });

  var acc = P.accuracy || { n: 0, hits: 0, rate: 0 };
  $("#prN").textContent = acc.n;
  $("#prAt").textContent = P.updatedAt;
  $("#prTrained").textContent = (P.backtest || {}).trainedAt || "—";

  /* 分时点命中率 */
  var cps = P.checkpoints || [];
  var lastF = P.lastFrame || {};
  function cpAt(m) { return cps.filter(function (c) { return c.m === m; })[0]; }
  var c8 = cpAt(8), c12 = cpAt(12), c16 = cpAt(16);
  if (c8) {
    $("#kCp8").textContent = Math.round(c8.acc * 100) + "%";
    $("#kCp8S").textContent = "命中 " + c8.hits + " / " + c8.n + " 局 · Brier " + c8.brier.toFixed(3);
  }
  if (c12) {
    $("#kCp12").textContent = Math.round(c12.acc * 100) + " / " + (c16 ? Math.round(c16.acc * 100) : "—") + "%";
    $("#kCp12S").textContent = "样本 " + c12.n + " 局 · 越往后越接近真实结果";
  }
  $("#kLast").textContent = lastF.n ? Math.round((lastF.acc || 0) * 100) + "%" : "—";
  var cpRows = cps.slice();
  if (lastF.n) cpRows.push({ m: "最后一帧", n: lastF.n, hits: Math.round((lastF.acc || 0) * lastF.n), acc: lastF.acc || 0, brier: lastF.brier || 0, last: true });
  $("#cpRows").innerHTML = cpRows.map(function (c) {
    return "<tr><td>" + (c.last ? "最后一帧" : "第 " + c.m + " 分钟") + "</td>" +
      '<td class="num mono">' + c.n + "</td>" +
      '<td class="num mono">' + c.hits + "</td>" +
      '<td class="num mono"' + (c.last ? ' style="color:var(--muted)"' : "") + ">" + Math.round(c.acc * 100) + "%</td>" +
      '<td class="num mono">' + Number(c.brier || 0).toFixed(3) + "</td>" +
      "<td>" + (c.last ? "比赛已基本结束，命中率高是口径使然" : "赛前中期，样本少，仅供参考") + "</td></tr>";
  }).join("") || '<tr><td colspan="6" style="color:var(--muted)">暂无预测档案</td></tr>';

  var bt = P.backtest || {};
  var ph = bt.phases || {};
  if (ph.all) {
    $("#kAcc").textContent = Math.round(ph.all.acc * 100) + "%";
    $("#kAccS").textContent = "共 " + ph.all.n + " 个采样阶段样本";
  }
  $("#prGate").textContent = bt.gatesPassed ? "全部通过 ✓" : "部分未达标";

  /* 预测档案表 */
  var LABELS = { early: "早期（≤8′）", mid: "中期（9–15′）", late: "后期（16′+）", all: "全部阶段" };
  $("#prPhases").innerHTML = ["early", "mid", "late", "all"].filter(function (k) { return ph[k]; }).map(function (k) {
    var m = ph[k];
    if (k === "all") {
      return '<div class="pr-ph" style="border-color:rgba(255,255,255,.45)"><div class="k">' + LABELS[k] +
        '</div><div class="v">' + Math.round(m.acc * 100) + '%</div><div class="s">Brier ' + m.brier.toFixed(3) +
        ' · n=' + m.n + '</div><div class="pr-bar"><i style="width:' + (m.acc * 100).toFixed(0) + '%"></i></div></div>';
    }
    return '<div class="pr-ph"><div class="k">' + LABELS[k] + '</div><div class="v">' + Math.round(m.acc * 100) +
      '%</div><div class="s">Brier ' + m.brier.toFixed(3) + ' · n=' + m.n +
      '</div><div class="pr-bar"><i style="width:' + (m.acc * 100).toFixed(0) + '%"></i></div></div>';
  }).join("");

  /* 归档行 */
  $("#prRows").innerHTML = (P.archived || []).map(function (a) {
    var predTeam = a.prob >= 0.5 ? a.t1 : a.t2;
    var predProb = a.prob >= 0.5 ? a.prob : 1 - a.prob;
    var actualTeam = a.win === 1 ? a.t1 : a.t2;
    var li = teamIcon[a.t1] ? '<img src="' + K.esc(teamIcon[a.t1]) + '" alt="" style="width:18px;height:18px;vertical-align:-4px;margin-right:5px">' : "";
    var link = a.matchId ? '<a class="go" href="match.html?id=' + K.esc(a.matchId) + '">回看 →</a>' : "<span></span>";
    return '<div class="pr-row">' +
      '<span class="d">' + K.esc(a.date.slice(5)) + "</span>" +
      '<span class="vs">' + li + K.esc(a.t1) + " vs " + K.esc(a.t2) + "</span>" +
      '<span class="g">G' + a.seq + "</span>" +
      '<span class="pred">' + K.esc(predTeam) + " <b>" + Math.round(predProb * 100) + "%</b>（" + a.frames + " 个预测点）</span>" +
      '<span class="res">' + K.esc(actualTeam) + " 胜</span>" +
      '<span class="hit ' + (a.hit ? "y" : "n") + '">' + (a.hit ? "命中 ✓" : "未命中 ✗") + "</span>" +
      link + "</div>";
  }).join("") || '<div class="empty-tip">暂无归档预测（比赛日自动积累）</div>';

  /* 数据简报 */
  {
    var last = (P.archived || [])[P.archived.length - 1];
    var txt = "直播预测已归档 <b>" + acc.n + "</b> 局，命中 <b>" + acc.hits + "</b> 局（<b>" + Math.round(acc.rate * 100) +
      "%</b>）。用最近一批比赛做检验，模型在早期/中期阶段判断约 <b>" +
      (ph.early ? Math.round(ph.early.acc * 100) : "—") + "%</b> 准确，后期局势反复时约 <b>" +
      (ph.late ? Math.round(ph.late.acc * 100) : "—") + "%</b>——每一条都可在上方逐局核对。";
    if (last) {
      txt += "最近归档：" + K.esc(last.date) + " " + K.esc(last.t1) + " vs " + K.esc(last.t2) + "（G" + last.seq + "）。";
    }
    K.brief("#brief", txt);
  }
})();
