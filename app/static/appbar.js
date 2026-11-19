/* One top bar for both programs, so the pool's meet software reads as one app:

     Set up meet · Run meet · Music                 Screens ▾   ⚙ Setup ▾   ●

   The same file ships in MeetDeck (app/static/appbar.js) and meet-board (static/appbar.js);
   keep the two copies identical. Each page sets window.APPBAR before loading it:

     {app: "meetdeck" | "meetboard",   which program this page belongs to
      active: "setup" | "run" | "music" | "admin",
      debug: true,                     meet-board only: show Debug in the Setup menu
      pool: true|false}                MeetDeck only, optional: pool features (meet board, music, stream,
                                       screens). Left out, MeetDeck's setting (Setup > Pool features) decides;
                                       meet-board pages always have them.

   The Screens menu has the TV controls (warm-up slide, need timers, break slide, go black,
   refresh all screens) on every page of both programs; they talk to meet-board's API.
   Pages that show the same state elsewhere get it through window.wuShow / ntShow / brShow /
   bkShow, and can push a change back with window.wuNavShow / ntNavShow / brNavShow.

   MeetDeck runs on port 8001 and meet-board on 5000 of the same computer, so links to the
   other program use this page's host name with the other port. Nothing here changes either
   server; it only links their pages.
*/
(function () {
  "use strict";
  var C = window.APPBAR || {};
  var host = location.hostname || "127.0.0.1";
  var MD = C.app === "meetdeck" ? location.origin : "http://" + host + ":8001";
  var MB = C.app === "meetboard" && location.port === "5000" ? location.origin : "http://" + host + ":5000";
  // pool features: the meet board / music / stream / screens parts, only for the pool's own PCs
  var POOL = C.app === "meetboard" ? true : (typeof C.pool === "boolean" ? C.pool : null);

  var css = [
    "#appbar .rl{font:600 13px/1 'Segoe UI',system-ui,sans-serif;color:#0b1618;background:#d9a441;border:0;border-radius:7px;padding:9px 11px;cursor:pointer}",
    "#appbar .rl.done{background:#7fe0ab}",
    "#appbar .bk,#appbar .wu,#appbar .nt,#appbar .brk{background:#2a3a3d;color:#e6eef0}",
    "#appbar .wu.on{background:#3ddc84;color:#0b1618}#appbar .nt.on{background:#ffd23f;color:#0b1618}",
    "#appbar .brk.on{background:#ffd60a;color:#0b1618}#appbar .bk.on{background:#000;color:#ffd479;box-shadow:0 0 0 1px #ffd479 inset}",
    "#appbar .rl[disabled]{opacity:.45;cursor:default}",
    "body.hasAppbar{margin-top:0}",
    "#appbar{position:sticky;top:0;z-index:1000;display:flex;align-items:center;gap:4px;flex-wrap:wrap;",
    "  background:#0b1618;color:#d9e8eb;padding:6px 12px;font:600 14px/1.2 'Segoe UI',system-ui,sans-serif;",
    "  box-shadow:0 1px 0 rgba(255,255,255,.06),0 2px 8px rgba(0,0,0,.25)}",
    "#appbar *{box-sizing:border-box}",
    "#appbar a.ab,#appbar button.ab{color:#9fb6bb;text-decoration:none;background:transparent;border:0;border-radius:8px;",
    "  padding:8px 13px;font:inherit;cursor:pointer;white-space:nowrap;display:inline-flex;align-items:center;gap:6px}",
    "#appbar a.ab:hover,#appbar button.ab:hover{color:#fff;background:#16282c}",
    "#appbar a.ab.on{color:#0b1618;background:#e6f2f4}",
    "#appbar .main{font-size:15px}",
    "#appbar .sp{flex:1}",
    "#appbar .menu{position:relative}",
    "#appbar .pop{display:none;position:absolute;right:0;top:calc(100% + 6px);min-width:230px;background:#11211f;border:1px solid #23383c;",
    "  border-radius:10px;padding:6px;box-shadow:0 10px 28px rgba(0,0,0,.45);z-index:1001}",
    "#appbar .menu.open .pop{display:block}",
    "#appbar .pop a,#appbar .pop .lbl{display:block;color:#d9e8eb;text-decoration:none;padding:8px 10px;border-radius:7px;font-weight:500;font-size:14px}",
    "#appbar .pop a:hover{background:#1b3236}",
    "#appbar .pop a.on{background:#e6f2f4;color:#0b1618}",
    "#appbar .pop .lbl{color:#7f9aa0;font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;padding:8px 10px 4px}",
    "#appbar .pop hr{border:0;border-top:1px solid #23383c;margin:5px 4px}",
    "#appbar .pop .ctl{display:flex;flex-wrap:wrap;gap:6px;padding:6px 6px 4px}",
    "#appbar .pop .ctl button{margin:0!important;flex:1 1 auto}",
    "#appbar .dot{width:9px;height:9px;border-radius:50%;background:#58707a;display:inline-block;flex:0 0 auto}",
    "#appbar .dot.ok{background:#3ddc84}#appbar .dot.warn{background:#f2b705}#appbar .dot.bad{background:#ff5d5d}",
    "#appbar .badge{background:#ffd23f;color:#0b1618;border-radius:9px;padding:1px 7px;font-size:11.5px}",
    "#appbar .st{padding:8px 10px;cursor:default}",
    "@media (max-width:640px){#appbar{padding:4px 6px}#appbar a.ab,#appbar button.ab{padding:8px 8px}#appbar .main{font-size:14px}",
    "  #appbar .hide-sm{display:none}#appbar .pop{position:fixed;left:8px;right:8px;top:52px;min-width:0}}"
  ].join("\n");
  css += "#appbar .abStream{display:contents}#appbar .abPool{display:contents}#appbar.nopool .abPool{display:none!important}";
  var st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]; }); }
  var A = C.active || "";
  function main(key, label, href) {
    return '<a class="ab main' + (A === key ? " on" : "") + '" data-k="' + key + '" href="' + esc(href) + '">' + esc(label) + "</a>";
  }
  function item(href, label, key, blank) {
    return '<a href="' + esc(href) + '"' + (blank ? ' target="_blank" rel="noopener"' : "") + (key ? ' data-page="' + key + '"' : "") +
      (key && C.page === key ? ' class="on"' : "") + ">" + label + "</a>";
  }
  // Run meet: the meet open in MeetDeck (it remembers it); from meet-board, MeetDeck works it out
  var runHref = C.app === "meetdeck" ? "/#runmeet" : MD + "/#runmeet";
  var html =
    main("setup", "Set up meet", MD + "/#meets") +
    main("run", "Run meet", runHref) +
    '<span class="abPool">' + main("music", "Music", MB + "/music") +
    '<span class="abStream">' + main("stream", "Stream", MB + "/stream") + "</span></span>" +
    '<span class="sp"></span>' +
    '<div class="menu abPool" id="abScreens"><button class="ab" type="button">Screens <span class="hide-sm">&#9662;</span><span class="dot hidden" id="abScrOn" style="display:none;background:#ffd23f"></span></button><div class="pop">' +
      '<div class="lbl">Open</div>' +
      item(MB + "/web/meetboard", "Meet board &#8599;", "", true) +
      '<span class="abStream">' + item(MB + "/overlay/race?layout=strip&test", "Lower Lanes (stream) &#8599;", "", true) +
      item(MB + "/overlay/lanes?test&demo", "Lane rail (stream) &#8599;", "", true) + "</span>" +
      '<div id="abCtlBox"></div>' +
    "</div></div>" +
    '<div class="menu" id="abSetup"><button class="ab' + (A === "admin" ? " on" : "") + '" type="button">&#9881; <span class="hide-sm">Setup</span> &#9662;<span class="badge" id="abUpd" style="display:none">!</span></button><div class="pop">' +
      '<div class="lbl">Meets &amp; schools</div>' +
      item(MD + "/#schools", "Schools &amp; records", "schools") +
      item(MD + "/#contacts", "Contacts", "contacts") +
      item(MD + "/#rules", "Rules", "rules") +
      item(MD + "/#setup", "MeetDeck setup (Drive, phone results, timing)", "mdsetup") +
      '<div class="abPool"><hr>' +
      '<div class="lbl">Screens &amp; stream</div>' +
      item(MB + "/settings", "Meet board settings", "settings") +
      item(MB + "/team_colors", "Team colors &amp; logos", "colors") +
      item(MB + "/state_times", "State times", "state") +
      item(MB + "/meet_files", "Meet files (load by hand)", "files") +
      item(MB + "/software_update", 'Meet board update <span class="badge" id="abUpdItem" style="display:none">new</span>', "update") +
      (C.debug ? item(MB + "/debug", "Debug", "debug") : "") +
    "</div></div></div>" +
    '<span class="st" id="abStatus" title="Checking…"><span class="dot" id="abDot"></span></span>';

  // Settings -> Streaming turned off: hide the Stream tab and the stream pages (meet-board tells us; from MeetDeck, ask it)
  function streamOff(off) {
    [].forEach.call(document.querySelectorAll("#appbar .abStream"), function (x) { x.style.display = off ? "none" : ""; });
  }
  var bar = document.createElement("div");
  bar.id = "appbar";
  if (POOL !== true) bar.classList.add("nopool");     // shown once MeetDeck says this PC has pool features
  bar.innerHTML = html;
  document.body.insertBefore(bar, document.body.firstChild);
  document.body.classList.add("hasAppbar");
  if (typeof C.streamOff === "boolean") streamOff(C.streamOff);
  else try {
    fetch(MB + "/api/stream_link", {cache: "no-store"}).then(function (r) { return r.json(); })
      .then(function (j) { streamOff(!!j.off); }).catch(function () {});
  } catch (e) {}
  // pages with their own sticky header put it just under this bar: top: var(--abh)
  function setH() { document.documentElement.style.setProperty("--abh", bar.offsetHeight + "px"); }
  setH(); window.addEventListener("resize", setH);

  // TV controls in Screens (the same on every page of both programs): they work meet-board's API
  function initScreens() {
    var box = document.getElementById("abCtlBox");
    box.innerHTML = '<hr><div class="lbl">On the TVs now</div><div class="ctl">' +
      '<button class="rl wu" type="button" data-k="wu" title="Show the warm-up slide (meet, teams, start time) on the meet boards and the stream">Warm-up slide</button>' +
      '<button class="rl nt" type="button" data-k="nt" title="Full-screen &quot;We need timers&quot; slide on the meet board TVs (change the words in Settings &gt; Screens)">Need timers</button>' +
      '<button class="rl brk" type="button" data-k="br" title="Break slide on the meet board TVs: team scores, results so far and the events still to come">Break slide</button>' +
      '<button class="rl bk" type="button" data-k="bk" title="Blank the meet board and scoreboard TVs (the OBS overlay is not affected)">Go black</button>' +
      '<button class="rl" type="button" data-k="rl" title="Reload every meet board, scoreboard and overlay page (TVs, OBS)">Refresh all screens</button>' +
      '</div><div class="lbl" id="abCtlMsg" style="display:none;text-transform:none;letter-spacing:0"></div>';
    var ctl = box.querySelector(".ctl"), msg = document.getElementById("abCtlMsg"), flag = document.getElementById("abScrOn");
    var B = function (k) { return ctl.querySelector('[data-k="' + k + '"]'); };
    var st = {wu: null, nt: null, br: null, bk: null};
    function api(path, body) {
      return fetch(MB + path, body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {cache: "no-store"})
        .then(function (r) { return r.json(); })
        .then(function (d) { msg.style.display = "none"; [].forEach.call(ctl.children, function (b) { b.disabled = false; }); return d; },
              function (e) { msg.textContent = "Can't reach the meet board"; msg.style.display = ""; throw e; });
    }
    function check() {
      var on = ctl.querySelectorAll(".on").length;
      flag.style.display = on ? "inline-block" : "none";
      flag.title = on ? on + " screen slide(s) on" : "";
    }
    var show = {
      wu: function (d) { st.wu = d; var b = B("wu"), on = !!(d && d.on); b.classList.toggle("on", on);
        b.textContent = on ? "Warm-up: ON" : "Warm-up slide"; if (window.wuShow) window.wuShow(d); check(); },
      nt: function (d) { st.nt = d; var b = B("nt"), on = !!(d && d.on); b.classList.toggle("on", on);
        b.textContent = on ? "Timers slide: ON" : "Need timers"; if (window.ntShow) window.ntShow(d); check(); },
      br: function (d) { st.br = d; var b = B("br"), on = !!(d && d.on); b.classList.toggle("on", on);
        b.textContent = on ? (d.final ? "Final results: ON" : "Break slide: ON") : (d && d.pending ? "Results slide soon\u2026" : "Break slide");
        if (window.brShow) window.brShow(d); check(); },
      bk: function (d) { st.bk = d; var b = B("bk"); if (window.bkShow) window.bkShow(d); b.classList.toggle("on", !!d.black);
        b.textContent = d.black ? (d.reason === "auto" ? "Screens black (idle) \u2014 wake" : "Screens black \u2014 wake") : "Go black";
        b.title = d.black ? "TVs are black. Click to wake them." :
          (d.auto && d.black_in_seconds != null ? "Blank the TVs now. Otherwise they go black by themselves in " +
            Math.ceil(d.black_in_seconds / 60) + " min with no meet activity." : "Blank the meet board and scoreboard TVs"); check(); }
    };
    var path = {wu: "/api/warmup_slide", nt: "/api/notice", br: "/api/break_slide", bk: "/api/blackout"};
    window.wuNavShow = show.wu; window.ntNavShow = show.nt; window.brNavShow = show.br;
    ctl.addEventListener("click", function (e) {
      var b = e.target.closest("button"); if (!b || b.disabled) return;
      var k = b.dataset.k;
      if (k === "rl") {
        fetch(MB + "/screens/reload?json=1", {method: "POST"}).then(function () {
          b.textContent = "Screens refreshing\u2026"; b.classList.add("done");
          setTimeout(function () { b.textContent = "Refresh all screens"; b.classList.remove("done"); }, 4000);
        }).catch(function () { msg.textContent = "Can't reach the meet board"; msg.style.display = ""; });
        return;
      }
      var body = k === "bk" ? {black: !(st.bk && st.bk.black)} : {on: !(st[k] && st[k].on)};
      api(path[k], body).then(show[k]).catch(function () {});
    });
    function load() {
      if (document.hidden) return;
      Object.keys(path).forEach(function (k) { api(path[k]).then(show[k]).catch(function () {}); });
    }
    load(); setInterval(load, 15000);
  }
  function setPool(on) {
    POOL = !!on;
    bar.classList.toggle("nopool", !POOL);
    if (POOL && !bar.dataset.scr) { bar.dataset.scr = "1"; initScreens(); }
    setH();
  }
  if (POOL !== null) setPool(POOL);
  else fetch(MD + "/api/settings", {cache: "no-store"}).then(function (r) { return r.json(); })
    .then(function (s) { setPool(!!s.pool_features); poll(); }).catch(function () { setPool(false); });

  // menus: click to open, click elsewhere to close
  [].forEach.call(bar.querySelectorAll(".menu"), function (m) {
    m.querySelector("button.ab").addEventListener("click", function (e) {
      e.stopPropagation();
      var was = m.classList.contains("open");
      [].forEach.call(bar.querySelectorAll(".menu.open"), function (x) { x.classList.remove("open"); });
      if (!was) m.classList.add("open");
    });
    m.querySelector(".pop").addEventListener("click", function (e) { if (e.target.closest("a")) m.classList.remove("open"); e.stopPropagation(); });
  });
  document.addEventListener("click", function () { [].forEach.call(bar.querySelectorAll(".menu.open"), function (x) { x.classList.remove("open"); }); });

  // "update available" flag (pages call window.AppBar.update(text))
  window.AppBar = {
    // a page that switches views without loading (MeetDeck's main page) says which one is showing
    setActive: function (active, page) {
      [].forEach.call(bar.querySelectorAll("a.main"), function (a) { a.classList.toggle("on", a.dataset.k === active); });
      bar.querySelector("#abSetup > button").classList.toggle("on", active === "admin");
      [].forEach.call(bar.querySelectorAll("[data-page]"), function (a) { a.classList.toggle("on", a.dataset.page === page); });
    },
    update: function (text) {
      document.getElementById("abUpd").style.display = "";
      var i = document.getElementById("abUpdItem"); i.style.display = ""; i.title = text || "";
    }
  };

  // status dot: both programs up, the scoreboard feed (meet-board) and the timing console (MeetDeck)
  var dot = document.getElementById("abDot"), stEl = document.getElementById("abStatus");
  function reach(url) {
    var ctl = window.AbortController ? new AbortController() : null;
    var t = setTimeout(function () { if (ctl) ctl.abort(); }, 4000);
    return fetch(url, {mode: "no-cors", cache: "no-store", signal: ctl ? ctl.signal : undefined})
      .then(function () { clearTimeout(t); return true; }, function () { clearTimeout(t); return false; });
  }
  function json(url) { return fetch(url, {cache: "no-store"}).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }); }
  function poll() {
    if (document.hidden) return;
    var jobs = [C.app === "meetdeck" ? (POOL ? reach(MB + "/favicon.ico") : Promise.resolve(null)) : reach(MD + "/favicon.ico")];
    jobs.push(C.app === "meetdeck" ? json("/api/bridge/status") : json("/api/serial"));
    Promise.all(jobs).then(function (r) {
      var other = r[0], d = r[1], lines = [], cls = "ok";
      if (C.app === "meetdeck") {
        if (other !== null) {           // pool PCs only: the meet board program
          lines.push("Meet board program: " + (other ? "running" : "not reachable"));
          if (!other) cls = "bad";
        }
        var con = d && d.connected;
        lines.push("Timing console: " + (con ? "connected" + (d.port ? " (" + d.port + ")" : "") : "not connected"));
        if (!con && cls === "ok") cls = "warn";
      } else {
        lines.push("MeetDeck: " + (other ? "running" : "not reachable"));
        if (!other) cls = "bad";
        var live = d && d.state === "open" && (d.records_per_sec > 0 || (d.idle_seconds != null && d.idle_seconds < 60));
        lines.push("Scoreboard feed: " + (live ? "live" : d && d.state === "open" ? "port open, nothing arriving" : "not open"));
        if (!live && cls === "ok") cls = "warn";
      }
      dot.className = "dot " + cls;
      stEl.title = lines.join("\n");
    });
  }
  poll(); setInterval(poll, 20000);
  document.addEventListener("visibilitychange", poll);
})();
