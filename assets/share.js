/* 分享图工坊 · 固定尺寸卡片模板（纯前端 Canvas，无依赖）
   为什么不用截屏：截屏会带上导航/滚动位置/浏览器 UI，尺寸不定、口径不可复现。
   本模块所有卡片都走同一套 1080×1440 模板，强制带「数据范围 + 口径 + 统计时间 + 来源」页脚。

   用法（页面内）：
     SHARE.mount(容器元素, function () { return {kind, title, sub, stats, note, url}; });
   字段：
     kind   卡片类型徽标，如 "选手档案"
     title  主体（选手名 / 战队名 / 英雄名 / 比赛标题）
     sub    一行副标题（队伍·位置 / 对手与比分 / 数据范围）
     stats  [[标签, 数值], ...]  2–6 行，标签左、数值右
     note   口径与样本说明（必填，会按宽度自动折行）
     url    可复现链接（会画在卡片底部）
*/
(function () {
  "use strict";
  var W = 1080, H = 1440;
  var FONT = '"Microsoft YaHei","PingFang SC","Hiragino Sans GB",sans-serif';
  var INK = "#F2F6FC", INK2 = "#C4CDDB", MUTED = "#8A97A8",
      BG = "#0A111C", PANEL = "#101B2A", LINE = "#243349", GOLD = "#F6C021";

  function font(size, weight) { return (weight || 400) + " " + size + "px " + FONT; }

  function roundRect(g, x, y, w, h, r) {
    g.beginPath();
    g.moveTo(x + r, y);
    g.arcTo(x + w, y, x + w, y + h, r);
    g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r);
    g.arcTo(x, y, x + w, y, r);
    g.closePath();
  }

  function wrap(g, text, maxW) {
    var out = [], line = "";
    for (var i = 0; i < text.length; i++) {
      var c = text[i];
      if (g.measureText(line + c).width > maxW && line) { out.push(line); line = c; }
      else line += c;
    }
    if (line) out.push(line);
    return out;
  }

  function fmtTime() {
    var d = new Date();
    function p(n) { return (n < 10 ? "0" : "") + n; }
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
  }

  function draw(spec) {
    var cv = document.createElement("canvas");
    cv.width = W; cv.height = H;
    var g = cv.getContext("2d");

    g.fillStyle = BG;
    g.fillRect(0, 0, W, H);

    /* 顶部强调条 */
    g.fillStyle = GOLD;
    g.fillRect(0, 0, W, 8);

    /* 品牌行 */
    g.textAlign = "left";
    g.fillStyle = INK;
    g.font = font(30, 700);
    g.fillText("KPL 数据中心", 72, 116);
    g.fillStyle = MUTED;
    g.font = font(22);
    g.fillText("kpldata · 2019–2026 全历史赛事数据", 72, 152);

    if (spec.kind) {
      g.font = font(24, 600);
      var kw = g.measureText(spec.kind).width + 40;
      g.fillStyle = "rgba(246,192,33,0.10)";
      roundRect(g, W - 72 - kw, 92, kw, 46, 10);
      g.fill();
      g.strokeStyle = "rgba(246,192,33,0.45)";
      g.lineWidth = 2;
      g.stroke();
      g.fillStyle = GOLD;
      g.textAlign = "center";
      g.fillText(spec.kind, W - 72 - kw / 2, 123);
      g.textAlign = "left";
    }

    /* 先量后画：把「标题 + 副标题 + 数据区 + 口径」当成一整块，
       在品牌行与页脚之间垂直居中，避免内容少时下半张卡片空一大片。 */
    var TITLE_LH = 86, SUB_LH = 44, ROW_H = 96, NOTE_LH = 36, GAP = 34;
    var stats = spec.stats || [];

    g.font = font(72, 700);
    var titleLines = wrap(g, String(spec.title || ""), W - 144).slice(0, 2);
    g.font = font(30);
    var subLines = spec.sub ? wrap(g, String(spec.sub), W - 144).slice(0, 2) : [];
    g.font = font(24);
    var noteLines = spec.note ? wrap(g, String(spec.note), W - 192).slice(0, 4) : [];

    var boxH = stats.length * ROW_H + 56;
    var noteH = noteLines.length ? 26 + noteLines.length * NOTE_LH + 22 : 0;
    var contentH = titleLines.length * TITLE_LH + subLines.length * SUB_LH +
      GAP + boxH + (noteH ? GAP + noteH : 0);

    var TOP = 268, BOTTOM = H - 138 - 40; /* 页面页脚线上方留 40px 呼吸位 */
    var y = TOP + Math.max(0, Math.min(170, Math.round((BOTTOM - TOP - contentH) / 2)));

    /* 主体 */
    g.fillStyle = INK;
    g.font = font(72, 700);
    titleLines.forEach(function (t) { g.fillText(t, 72, y); y += TITLE_LH; });
    if (subLines.length) {
      g.fillStyle = INK2;
      g.font = font(30);
      subLines.forEach(function (t) { g.fillText(t, 72, y); y += SUB_LH; });
    }

    /* 数据区 */
    y += GAP;
    g.fillStyle = PANEL;
    roundRect(g, 72, y, W - 144, boxH, 18);
    g.fill();
    g.strokeStyle = LINE;
    g.lineWidth = 2;
    g.stroke();

    var ty = y + 28;
    stats.forEach(function (row, i) {
      if (i) {
        g.strokeStyle = "rgba(36,51,73,0.75)";
        g.beginPath();
        g.moveTo(104, ty + ROW_H / 2 - 30);
        g.lineTo(W - 104, ty + ROW_H / 2 - 30);
        g.stroke();
      }
      g.textAlign = "left";
      g.fillStyle = MUTED;
      g.font = font(28);
      g.fillText(String(row[0]), 104, ty + 46);
      g.textAlign = "right";
      g.fillStyle = i === 0 ? GOLD : INK;
      g.font = font(38, 700);
      g.fillText(String(row[1]), W - 104, ty + 50);
      ty += ROW_H;
    });
    g.textAlign = "left";
    y += boxH;

    /* 口径说明（必填） */
    if (noteLines.length) {
      y += GAP;
      g.fillStyle = GOLD;
      g.fillRect(72, y, 4, 26);
      g.fillStyle = INK2;
      g.font = font(24);
      noteLines.forEach(function (t, i) { g.fillText(t, 96, y + 22 + i * NOTE_LH); });
    }

    /* 页脚：来源 + 生成时间 */
    g.strokeStyle = LINE;
    g.lineWidth = 2;
    g.beginPath();
    g.moveTo(72, H - 138);
    g.lineTo(W - 72, H - 138);
    g.stroke();
    g.fillStyle = MUTED;
    g.font = font(22);
    g.fillText("数据来源：官方赛事接口（data/history）· 生成时间 " + fmtTime(), 72, H - 96);
    if (spec.url) {
      var u = String(spec.url); /* 卡片是给人看的，中文参数解码后再画 */
      try { u = decodeURIComponent(u); } catch (e) {}
      g.fillStyle = GOLD;
      g.font = font(22, 600);
      g.fillText(u.slice(0, 78), 72, H - 60);
    }
    return cv;
  }

  /* 预览浮层：先看图，再决定下载 */
  function preview(cv, name) {
    var old = document.getElementById("shareLayer");
    if (old) old.remove();
    var layer = document.createElement("div");
    layer.id = "shareLayer";
    layer.setAttribute("style",
      "position:fixed;inset:0;z-index:9999;background:rgba(4,8,14,.86);display:flex;" +
      "flex-direction:column;align-items:center;justify-content:center;gap:16px;padding:20px;" +
      "backdrop-filter:blur(3px)");
    var img = document.createElement("img");
    img.src = cv.toDataURL("image/png");
    img.alt = "分享图预览";
    img.setAttribute("style", "max-width:min(92vw,460px);max-height:74vh;border-radius:14px;" +
      "border:1px solid #243349;box-shadow:0 24px 60px rgba(0,0,0,.55)");
    var bar = document.createElement("div");
    bar.setAttribute("style", "display:flex;gap:12px;align-items:center");
    var dl = document.createElement("a");
    dl.href = img.src;
    dl.download = name;
    dl.textContent = "下载 PNG";
    dl.setAttribute("class", "btn primary");
    var close = document.createElement("button");
    close.type = "button";
    close.textContent = "关闭";
    close.setAttribute("class", "btn");
    close.onclick = function () { layer.remove(); };
    var tip = document.createElement("div");
    tip.setAttribute("style", "color:#8A97A8;font-size:12.5px;text-align:center;line-height:1.7;" +
      "max-width:min(92vw,460px)");
    tip.textContent = "卡片固定尺寸 1080×1440，已自带数据范围、口径与生成时间；请勿裁剪或改数后再传播。";
    bar.appendChild(dl);
    bar.appendChild(close);
    layer.appendChild(img);
    layer.appendChild(bar);
    layer.appendChild(tip);
    layer.onclick = function (e) { if (e.target === layer) layer.remove(); };
    document.body.appendChild(layer);
  }

  window.SHARE = {
    /* 把一个"生成分享图"按钮挂到容器里；specFn 每次点击时求值，保证拿到最新数据 */
    mount: function (anchor, specFn, fileName) {
      if (!anchor || anchor.querySelector(".share-fab")) return;
      /* 挂到容器内的排版层里，避免直接挂在 #heroHead 上跑到页面左边缘外 */
      var host = anchor.querySelector(".wrap") || anchor;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn share-fab";
      btn.textContent = "生成分享图";
      btn.setAttribute("style", "margin-top:14px");
      btn.onclick = function () {
        var spec;
        try { spec = specFn(); } catch (e) { spec = null; }
        if (!spec || !spec.title) { btn.textContent = "暂无可用数据"; return; }
        preview(draw(spec), fileName || "kpldata-share.png");
      };
      host.appendChild(btn);
    },
    /* 需要直接拿 canvas（例如做批量导出）时用这个 */
    render: draw
  };
})();
