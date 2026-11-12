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
  // UHSAA AO training session (recorded Oct 26, 2026; in the UHSAA AO Google Classroom). Links open the video at that minute.
  const V = "https://www.youtube.com/watch?v=6Tv16uvZdeU";
  const at = hm => { const [h, m] = hm.split(":").map(Number); return `<a href="${V}&t=${(h * 60 + m) * 60}s" target="_blank">video ${hm}</a>`; };
  const html2 = sec("From the UHSAA AO training (recorded session, Oct 26 2026)", [
      `Entries: 2 individual + 2 relays, or 1 individual + 3 relays &mdash; 4 events at most, never more than 2 individual. Run Meet Manager's eligibility report &mdash; ${at("0:09")}`,
      `Prelims/finals in the same meet: still 4 events at most, 2 individual &mdash; ${at("0:56")}`,
      `Relays: the lead-off swimmer can't change after the referee's long whistle; legs 2&ndash;4 may switch, but tell the AO for the record &mdash; ${at("0:55")}`,
      `A lead-off split stays official when the relay is DQ'd later, unless it's an unsporting-conduct DQ &mdash; ${at("0:55")}`,
      `Combining boys and girls in one heat: leave an empty lane between them, and check with the AO &mdash; ${at("0:11")}`,
      `Timing order is always pad &rarr; buttons &rarr; watches. Keep the pad time unless you can prove it wrong; never mix systems (no pad + button, no button + watch averages) &mdash; ${at("0:23")}, ${at("0:58")}`,
      `Bad pad with two buttons: average the two buttons; one button: use it; watch average only when pad and buttons are both unusable &mdash; ${at("0:25")}, ${at("0:29")}, ${at("0:33")}`,
      `A difference of more than 0.03 between systems is a discrepancy to check; never round or hand-change a time without proving the pad wrong &mdash; ${at("0:58")}, ${at("1:03")}`,
      `The referee's eyes don't override the computer's finish order &mdash; ${at("0:32")}`,
      `Timers should be trained and at the meeting before the meet starts &mdash; ${at("0:33")}`,
      `DQs: the referee makes the call; the AO confirms event, heat, lane, swimmer and reason before entering it, may ask for clarification but doesn't challenge it. A DQ approved after scoring: enter it and re-score the event &mdash; ${at("0:18")}, ${at("0:36")}`,
      `Process each event as soon as the referee closes it &mdash; ${at("0:34")}`,
      `Before leaving the venue the AO sends initial results to all coaches; coaches review within 24 hours, copying the AO and referee on any fix &mdash; ${at("0:43")}, ${at("0:45")}`,
      `Corrections within 48 hours (NFHS). An error that changes state qualifying can be fixed later &mdash; email the UHSAA swim director &mdash; ${at("0:20")}, ${at("0:21")}`,
      `Final meet report + Meet Manager backup + results to utahtop50@yahoo.com and the meet director/host &mdash; sent by the AO now (the coach if the AO has no computer) &mdash; ${at("0:46")}, ${at("0:47")}`,
      `Final results cover sheet signed by two officials and all the coaches &mdash; ${at("0:54")}`,
      `Keep all paperwork for the season, including timer sheets and DQ slips &mdash; ${at("0:47")}`,
      `Every meet needs at least one trained, registered AO (timing-console operators don't need to be); AOs sign the meet roster to be paid ($61 per meet) &mdash; ${at("0:42")}`,
      `The referee's roster/pay sheet is due within 5 days of the meet &mdash; ${at("1:12")}`,
      `Championship meets: regions set up their own formats &mdash; some region meets are prelims/finals, some one day of finals &mdash; so confirm the scoring settings in Meet Manager &mdash; ${at("0:08")}`,
    ]);
  function render() { document.querySelectorAll("#utahRules").forEach(el => { el.innerHTML = html + html2; }); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", render); else render();
})();
