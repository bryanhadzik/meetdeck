// AO (Administrative Official) training highlights, from the UHSAA AO Training slides 2026-27
// (rules library: "2026-27 UHSAA AO Training (slides).pdf"). aoTip(key) returns a small collapsible box.
(function () {
  const DOC = "2026-27 UHSAA AO Training (slides).pdf";
  // slide number -> page in the library PDF (slide 22 has no content of its own)
  const page = n => (n <= 21 ? n : n - 1);
  const T = {
    timing: {t: "Times: pad, buttons, timers", s: [25, 26, 10, 29], p: [
      "The touchpad is the official time. Pad vs backup differing by <b>more than .3</b> is a potential discrepancy: <b>pause the result, collect evidence, consult the referee</b>.",
      "<b>Never mix timing systems.</b> Average two valid buttons, or two valid watches; one valid backup is used alone. Never average a button with a watch.",
      "Diagnose why the pad is wrong first. Don't pick the faster watch, and never invent, round or truncate a time.",
      "Document the approved official time, then recheck places and scoring."]},
    missingpad: {t: "Missing touchpad", s: [13, 14, 20], p: [
      "Verify the lane and swimmer first, then collect the backup evidence (buttons / watches).",
      "Process the result once the referee closes the event; apply the timing rules; document the approved time.",
      "Hold the lane until there's evidence &mdash; never type in a guessed time."]},
    wholeheat: {t: "Whole-heat timing failure", s: [28], p: [
      "Several bad pad times in one heat is a coordinated review with the referee, not a series of guesses.",
      "Collect: primary readings if any, valid backups, the verified finish order, and what happened to the system. Seed times are not evidence."]},
    dq: {t: "DQs", s: [11, 15], p: [
      "DQs come from the referee. Confirm <b>event, heat, lane, swimmer and reason</b> before recording it.",
      "A valid DQ after the event was scored: apply it, re-rank and <b>re-score</b>, and tell the coaches.",
      "The referee makes rule calls; the AO keeps the record accurate."]},
    score: {t: "Before you score", s: [12, 9], p: [
      "Check DQs, exhibition swims and ties; make sure relay and individual results are right.",
      "Review the cumulative team scores and flag anything odd <b>before</b> results are published.",
      "Loop: select event &rarr; check heat &rarr; enter times &rarr; verify lanes &rarr; review exceptions &rarr; apply approved DQs &rarr; score &rarr; review &rarr; release."]},
    relay: {t: "Relay swimmers", s: [23, 30], p: [
      "<b>No change of the lead-off swimmer after the long whistle</b> (NFHS 8-3-3). Swimmers 2, 3 and 4 may change order.",
      "A lead-off split counts as an official time only with a legal start, stroke and finish.",
      "A coach changing the lead-off after the start: notify the referee."]},
    swimmer: {t: "Wrong swimmer in the lane", s: [16], p: [
      "A different athlete in the lane than the heat sheet shows is an entry / substitution <b>rules question for the referee</b>, not a software edit."]},
    entries: {t: "Entries and eligibility", s: [7, 24], p: [
      "Check entry limits and eligibility; review scratches and substitutions; tell coaches about revised heats and lanes.",
      "Prelims and finals in one meet: at most four events, only two individual. Two individual events plus all three relays = a fifth event, illegal when swum.",
      "A software warning is not a rules decision &mdash; eligibility calls go to the meet referee."]},
    seeding: {t: "Seeding", s: [24, 7], p: [
      "With more than one heat, every heat needs the minimum number of swimmers (MeetDeck seeds at least 3).",
      "After scratches or substitutions, communicate the revised heats and lanes."]},
    setup: {t: "Before athletes arrive", s: [5, 6], p: [
      "Confirm meet setup, events, teams and pool course; open the correct meet database.",
      "Verify the timing interface and backups; check entries, event order and heat sheets.",
      "Agree on the correction and communication workflow with the referee. Back up before major changes."]},
    closing: {t: "Closing the meet", s: [17, 18, 19], p: [
      "Reconcile every event, DQ, time and score; check relay results; review final results with the referee.",
      "Back up the database; keep all timer sheets and DQ slips / logs for the whole season.",
      "Before leaving: initial results to all coaches. Coaches have 24 hours; verify change requests with the AO / referee. Changes can be made within the 48-hour window."]},
  };
  window.AO_DOC = DOC;
  window.aoTip = function (key, open) {
    const x = T[key]; if (!x) return "";
    const href = `/api/rules/file/${encodeURIComponent(DOC)}#page=${page(x.s[0])}`;
    return `<details class="aotip"${open ? " open" : ""}><summary><span class="aotag">AO training</span> ${x.t}</summary><ul>${x.p.map(p => `<li>${p}</li>`).join("")}</ul>
      <div class="aosrc">UHSAA AO Training 2026&ndash;27, ${x.s.map(n => `<a href="/api/rules/file/${encodeURIComponent(DOC)}#page=${page(n)}" target="_blank">slide ${n}</a>`).join(", ")}</div></details>`;
  };
  const css = document.createElement("style");
  css.textContent = `.aotip{border-left:3px solid #c08a00;background:rgba(192,138,0,.08);border-radius:6px;padding:4px 10px;margin:6px 0;font-size:13px;line-height:1.4}
  .aotip summary{cursor:pointer;font-weight:600;list-style:revert}.aotip ul{margin:4px 0 2px 18px;padding:0}.aotip li{margin:2px 0}
  .aotag{background:#c08a00;color:#fff;border-radius:4px;padding:0 5px;font-size:11px;font-weight:700;margin-right:4px}
  .aosrc{font-size:11.5px;opacity:.75;margin-top:2px}
  .aorow{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:0 10px;margin:2px 0 8px}.aorow .aotip[open]{grid-column:1/-1}`;
  document.head.appendChild(css);
})();
