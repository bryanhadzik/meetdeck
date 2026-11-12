// Utah (UHSAA) rules that apply on top of the NFHS Rules Book, with the printed page to look them up.
// Source: 2026-27 UHSAA Handbook, Swimming section (p. 122-123), and the NFHS Rules Book's State Association
// Adoption Chart (p. 95). Rendered into any element with id "utahRules".
(function () {
  const HB = "2026-27 UHSAA Handbook - Swimming.pdf";
  const hb = (pdfPage, book, text) => `<a href="/rules/view/${encodeURIComponent(HB)}?page=${pdfPage}" target="_blank">UHSAA Handbook p. ${book}</a>`;
  const sec = (title, items) => `<h3 style="margin:12px 0 4px">${title}</h3><ul style="margin:0;padding-left:20px;line-height:1.5">${items.map(i => `<li>${i}</li>`).join("")}</ul>`;
  const html = `<div class="muted" style="font-size:13px">Utah follows the NFHS Rules Book plus these UHSAA rules (${hb(1, 122)}: "Coaches, athletes and officials must adhere to all UHSAA and NFHS rules").</div>` +
    sec("Every meet whose times count toward state", [
      `Electronic timing &mdash; ${hb(1, 122)}`,
      `Two certified officials from the Utah Swim Coaches Association list &mdash; ${hb(1, 122)}`,
      `Results signed by both officials and the head coaches, with the meet date and the time the meet ended &mdash; ${hb(1, 122)}`,
      `Results to the State Top 100 compiler within one week (UHSAA AO training: within 48 hours) &mdash; ${hb(1, 122)}`,
      `Meter-pool times are converted: seconds &divide; 1.11 &mdash; ${hb(1, 122)}`,
      `Swimmers must be from a UHSAA member school in good standing &mdash; ${hb(1, 122)}`,
      `No video or photos on the deck behind the starting blocks &mdash; ${hb(1, 122)}`,
      `14 meets per swimmer; region and state don't count &mdash; ${hb(1, 122)}`,
    ]) +
    sec("Region and state", [
      `Region is the last meet before state &mdash; ${hb(1, 122)}`,
      `State uses NFHS championship meet entry rules &mdash; ${hb(2, 123)}. The handbook doesn't say whether region does (Rules Book 1-4-10: the state decides which meets are championships)`,
      `State: 3A&ndash;6A prelims and finals (2 days), 2A timed finals (1 day) &mdash; ${hb(1, 122)}`,
      `State entries: 4 swimmers per team per individual event, 1 relay per relay event; each swimmer 2 individual + 2 relays, or 1 individual + 3 relays &mdash; ${hb(2, 123)}`,
      `State relays are entered without names and declared at the meet &mdash; ${hb(2, 123)}`,
      `State breaks: 15 min after the boys' 50 free, 10 min after the boys' 500 free, 10 min after the boys' 100 breast &mdash; ${hb(2, 123)}`,
      `State timers must be 15 or older &mdash; ${hb(2, 123)}`,
    ]) +
    sec("NFHS options left to each state (Rules Book, State Association Adoption Chart, p. 95)", [
      `Which meets are championship meets &mdash; <b>Utah: state (championship entry rules apply); region not stated</b>`,
      `Entering relays without swimmers' names &mdash; <b>Utah: yes, at state</b>`,
      `Championship entry limits &mdash; <b>Utah state: 4 per individual event, 1 relay</b>`,
      `Exhibition swimmers, backstroke ledges, relay judging platforms, resuming a suspended meet, unlimited team entries at multi-team meets, event changes for multi-team meets &mdash; <b>not stated in the UHSAA Handbook</b>; ask the UHSAA swim director (Steve Marsing, 801-598-9460, per ${hb(2, 123)})`,
    ]);
  function render() { document.querySelectorAll("#utahRules").forEach(el => { el.innerHTML = html; }); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render); else render();
})();
