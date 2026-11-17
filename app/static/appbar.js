/* One top bar for both programs, so the pool's meet software reads as one app:

     Set up meet · Run meet · Music                 Screens ▾   ⚙ Setup ▾   ●

   The same file ships in MeetDeck (app/static/appbar.js) and meet-board (static/appbar.js);
   keep the two copies identical. Each page sets window.APPBAR before loading it:

     {app: "meetdeck" | "meetboard",   which program this page belongs to
      active: "setup" | "run" | "music" | "admin",
      debug: true,                     meet-board only: show Debug in the Setup menu
      screenControls: element}         meet-board only: the warm-up / break / black buttons,
                                       moved into the Screens menu

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

  var css = [
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
  css += "#appbar .abStream{display:contents}";
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
    main("music", "Music", MB + "/music") +
    '<span class="abStream">' + main("stream", "Stream", MB + "/stream") + "</span>" +
    '<span class="sp"></span>' +
    '<div class="menu" id="abScreens"><button class="ab" type="button">Screens <span class="hide-sm">&#9662;</span><span class="dot hidden" id="abScrOn" style="display:none;background:#ffd23f"></span></button><div class="pop">' +
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
      "<hr>" +
      '<div class="lbl">Screens &amp; stream</div>' +
      item(MB + "/settings", "Meet board settings", "settings") +
      item(MB + "/team_colors", "Team colors &amp; logos", "colors") +
      item(MB + "/state_times", "State times", "state") +
      item(MB + "/meet_files", "Meet files (load by hand)", "files") +
      item(MB + "/software_update", 'Meet board update <span class="badge" id="abUpdItem" style="display:none">new</span>', "update") +
      (C.debug ? item(MB + "/debug", "Debug", "debug") : "") +
    "</div></div>" +
    '<span class="st" id="abStatus" title="Checking…"><span class="dot" id="abDot"></span></span>';

  // Settings -> Streaming turned off: hide the Stream tab and the stream pages (meet-board tells us; from MeetDeck, ask it)
  function streamOff(off) {
    [].forEach.call(document.querySelectorAll("#appbar .abStream"), function (x) { x.style.display = off ? "none" : ""; });
  }
  var bar = document.createElement("div");
  bar.id = "appbar";
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

  // the page's own screen buttons (meet-board: warm-up, need timers, break, go black, refresh) live in Screens
  if (C.screenControls) {
    var box = document.getElementById("abCtlBox");
    box.innerHTML = '<hr><div class="lbl">On the TVs now</div>';
    var ctl = document.createElement("div"); ctl.className = "ctl";
    while (C.screenControls.firstChild) ctl.appendChild(C.screenControls.firstChild);
    box.appendChild(ctl);
    var flag = document.getElementById("abScrOn");
    var check = function () {
      var on = ctl.querySelectorAll(".on").length;
      flag.style.display = on ? "inline-block" : "none";
      flag.title = on ? on + " screen slide(s) on" : "";
    };
    new MutationObserver(check).observe(ctl, {subtree: true, attributes: true, attributeFilter: ["class"]});
    check();
  }

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
    var jobs = [C.app === "meetdeck" ? reach(MB + "/favicon.ico") : reach(MD + "/favicon.ico")];
    jobs.push(C.app === "meetdeck" ? json("/api/bridge/status") : json("/api/serial"));
    Promise.all(jobs).then(function (r) {
      var other = r[0], d = r[1], lines = [], cls = "ok";
      if (C.app === "meetdeck") {
        lines.push("Meet board program: " + (other ? "running" : "not reachable"));
        if (!other) cls = "bad";
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
