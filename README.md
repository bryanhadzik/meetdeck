# MeetDeck

_Swim meet entries, database, timing and printing for Tooele County high school meets (formerly "Meet Entry Check")._

## Entry checking (the original tool)
Reads coaches' Hy-Tek entry files and checks them against the UHSAA rules (max 2 individual, max 4 total incl. relays, duplicate events, relay legs), remove bad entries, plan dual-meet lanes.

Output 1 (main): "Download Meet Manager backup" - a Swmm8Bkup*.zip to File > Restore in MM8.
  Built by mmdb/Builder.java (Jackcess) from the template MM backup in data/template/backup.zip:
  keeps the template's events/sessions/scoring/records/officials/prefs, replaces teams, athletes,
  entries, relays, Dualteams; sets meet name/date, meet_meetstyle (2 dual / 3 3+dual), dualteam_laneN,
  dual_evenodd (= "Use Lane Assignments Above"), anyone_onrelay when a relay uses another team's swimmer.
  Text columns are padded/defaulted exactly like the template rows. Entries are left unseeded.
Output 2 (fallback): per-team "(checked).zip" import files - coach lines untouched, only removed blocks dropped.

Verify a build independently: tests/verify_mm.py <backup.zip> <spec.json> (uses mdbtools).
Rebuild: docker compose up -d --build. Data: ./data (meets/, template/).

## Schools, masters, records (Schools & records tab)
Four host schools (data/hosts.json: THS, SHS, GHS, DPHS) each with data/hosts/<id>/master.zip (+ history/ of
previous versions). A meet picks its host; its MM backup is built from that host's master.
- Master tools in mmdb/Builder.java: --read-master, --write-master (meet info, RecordTags, Records full replace,
  clear_people to strip a real meet backup), --profile (learn MM padding/defaults; empty masters fall back to profile.json).
- Team-record tags (host.team_tags, e.g. THS "Varsity Rec" = tag 3) get RecordTags.team_no = the meet's home team
  (auto by host team_codes; none/several -> 0 = everyone, e.g. intrasquad; override per meet). Others forced to 0.
- Every built meet / stripped master gets Meet Mobile meet id + upload flags reset.
- THS master = 2024 Provo@Tooele DB, records corrected to the pool board 2026-10-28 (mmdb/records-fix-2026-10-28.json).

## Receiving entries (any number of teams)
Uploads accept Team Manager/SwimTopia .hy3/.zip (used as-is), SDIF .cl2/.sd3 and Word/.txt entry lists
(app/importers.py) plus a paste box; non-hy3 formats are converted to .hy3 numbered from the host master's events,
with reading notes kept in files/<name>.hy3.json. Per-team status board + "teams expected" + cross-team duplicate
swimmer check. Gmail scan (app/gmail.py): read-only IMAP (BODY.PEEK, EXAMINE) using GMAIL_USER/GMAIL_APP_PASSWORD
from ./.env (Bryan sets it; not in code). Tests: tests/make_cl2.py builds an SDIF file with the independent `sdif` lib.

## Seasons, meet files, Google Drive (2026-10-31)
- Season picker in the header (data/settings.json); a meet's season comes from its date (seasons start in July).
- Meet files (section 6): entry files with original / checked .hy3 downloads; removed or replaced files go to `archive/` and can be restored; every Meet Manager backup download is kept in `backups/` (newest 15); `docs/` holds any other documents; "Download everything" zips it all.
- Files that aren't entry lists are kept under Documents instead of being dropped.
- Google Drive: paste a share link (file, Google Doc -> .docx, Google Sheet -> tab text, or folder) shared "Anyone with the link" (app/drive.py). Private Drive access would need a Google service account.

## Meet database editor (2026-10-31)
- `/db?meet=<id>` (button "Open meet database" on the meet page) edits the Meet Manager .mdb directly: scratch / un-scratch (one event or the whole meet, incl. relay legs), move heat/lane (swaps), seed times, finals time / DQ / no-show (re-places the event), add/delete entries, add/edit swimmers, relay swimmers, team names.
- Working DB at data/meets/<id>/db/meet.mdb; compressed copy before every change (db/versions, newest 60) -> Undo / restore; change log db/log.jsonl.
- Start from the team entries, an uploaded Meet Manager backup, or a backup in the meet's Drive folder.
- mmdb/Svc.java: long-running Jackcess service on 127.0.0.1:8765 (read/apply/close), started by FastAPI. app/meetdb.py = model + changes (built to grow into running the meet).
- Exports (app/results.py): Team Manager results .hy3 (matches Meet Manager's own export line-for-line on a real meet), printable results HTML, CSV. Points are left as Meet Manager scored them; places are recomputed on corrections.
- meta "no_drive": true stops Drive filing for a meet (used for test meets).

## Timing console (CTS System 6) - written, not yet tested on hardware (2026-10-31)
- timing/cts.py: computer-interface protocol (console COM PORT 1). Message = [len LE16][cmd][data][check LE16],
  check = 0xFFFF - sum(bytes). Who-are-you, meets, race list, race by number / event+heat / last, lane data
  (place, splits, final, buttons, backup in ms), event-sequence download (labels + events + select slot).
  Protocol notes: Pool Streaming project doc claude/cts-system6-computer-interface.md.
- timing/sim.py: simulated console; timing/tests/test_cts.py checks the reference byte sequences + a full round trip.
- timing/bridge.py: runs on the timing laptop (Python + pyserial), HTTP on localhost:8766, logs every byte to cts-log.txt.
  Download from the app at /timing/bridge.zip (includes start-bridge.bat / start-simulator.bat).
- Database page > Events > Timing console: connect (probe settings) or simulator, Get times per heat -> Apply
  (op heat_results: times, backups, splits into Split table, NS for empty entered lanes, DQ from console, re-place),
  Send events to a sequence slot.
- First real-console session: run `python bridge.py probe COMx`, then Get times on a test heat and keep cts-log.txt.

## Scoring (2026-10-31)
- Database page "Score meet": NFHS Rule 9 tables (UHSAA): dual 3/2/4-entry, triangular, championship 16-place (20-17-16..1, relays double), double/triple dual (pairwise).
  Scorer limits per team per event, ties split points, DQ/NS/exhibition don't score, over-limit = Fin_ptsplace 999 (like MM).
- Writes Ev_score / Fin_ptsplace; summary (team totals, pairs, per-event signatures) in db/info.json "scoring".
  Events changed after scoring show "Rescore". Validated: re-scoring the real Mel Roberts 2025 DB reproduces MM's points exactly (0 rows changed).
- DQ: 65 Hy-Tek/USA Swimming codes (app/dqcodes.py); hy3 H1/H2 lines match MM byte-for-byte.

### Scoring per race
- Every race is scored on its own. Open the event and press **Score event** once its times and DQs are final. The button turns into **Rescore event** (red) if times, DQs or scratches change after scoring.
- **Scoring** in the header sets the method and how many scorers each team gets, using the NFHS/UHSAA tables. Changing these rescores every race already scored. **Score all finished races** catches up on any you missed.
- A running team-score strip above the events shows the totals so far. Undo also rolls back a scoring step.

### Adding entries (Entries by team)
- Each swimmer row has **+ Add**: pick an event (only events of their gender that they aren't already in), type a seed time (blank = NT), and optionally mark it exhibition. Each team's Relays row has **+ Add relay**, which uses the next free letter; swimmers can be declared later.
- Added entries are saved in the meet (meta `added`), and the coach's original file is never changed. They show with a dashed border, and their × deletes them.
- They count in the rule check, coach messages, seeding and the Meet Manager backup. The "Checked .hy3" downloads write them into the team's file, right after the swimmer's other entries (relays at the end of the team block), with valid checksums.
- The new entry line is copied from an existing entry for the same event, so you can only add events that at least one team has entered.

### Results export = Meet Manager's, byte for byte
- **Download / export → Results for Team Manager** produces the same zip MM's "Export Results for Team Manager" makes: `Meet Results-<meet>-30Oct2026-00N.zip` holding a `.cl2` (SDIF v3) and a `.hy3`. MM's naming is copied: `&` becomes `-`, and exports are numbered 001, 002, and so on.
- Checked against a real meet run in MM 8.0Gh (Stansbury Blue & Black, 30 Oct 2026): the `.cl2` is identical byte for byte, and the `.hy3` is identical except the export time in line 1. The fixture is in `tests/fixtures/mm-blueblack-2026/`. To re-check after any change:
  `docker exec swimmeet mkdir -p /tmp/mmfixture && for f in tests/fixtures/mm-blueblack-2026/*; do docker cp "$f" swimmeet:/tmp/mmfixture/; done && docker exec -i swimmeet python3 - < tests/check_mm_results.py`
  All saved meets at once (Blue & Black 2026, Mel Roberts Dec 2025, GHS-LHS-MOR Jan 2026): `tests/check_all.sh` — each must show 0 differing lines. Add a meet by dropping its .mdb plus Meet Manager's results .cl2/.hy3 into a new `tests/fixtures/mm-<name>/` folder.
- Details learned:
  - The `.cl2` line check is sum(bytes[0:156]) // 19 + 211, with the last two digits reversed.
  - The E2/F2 timing letter is `A` when the final came from the buttons, and `K` when the touchpad was kept with no button within 0.30 s. It is blank when a button confirms the pad.
  - In the `.hy3`, splits (G1) and relay legs (F3) come before the DQ lines (H1/H2). The second relay DQ code also sits in F2 col 63.

### Meet header (database page → Meet tab)
- Edit the header stored in the MM database: name, location, header lines 1–2, start/end dates, age-up date, course (SCY/SCM/LCM), lanes, altitude, and the address (address, city, state, zip, country).
- Each field saves when you leave it, is checked against MM's column sizes, gets logged and can be undone. An end date before the start is refused. Moving the start date past the end moves the end along with it.
- Name, start date and location are also copied to the meet list. The header flows into the .hy3/.cl2 results (B1/B2, course letter) and the results file name.

### Printing (database page → Print ▾)
- **Heat sheet**, **Referee program** and **Timer sheets** (all lanes, or a single lane) are built as PDFs in Meet Manager's layouts. The measurements come from MM 8.0 reports of the Blue & Black meet:
  - heat sheet: three columns; an event is never split; a new column starts when a lane would print below 652 pt
  - referee program: one event per page, with blanks for the finals time and place
  - timer sheets: one set of pages per lane, every heat, a soft-touch box
- **Print** loads the PDF in a hidden frame and opens the printer dialog. **PDF** opens it in a new tab.
- Endpoint: `/api/meets/<id>/db/report/{heatsheet|referee|timer}.pdf` (`?lane=N` for timer sheets, `&download=1` to save).
- Long names never overlap: each field is fitted to its column (shrunk up to 15%, then trimmed). Relay teams on timer sheets use the full team name when it fits, otherwise the short name, and the relay letter is always kept.
- Font: Cambria (MM's font) when its files have been added under Setup → Report font (copied from C:\Windows\Fonts, kept in data/fonts/). Otherwise Caladea, a free font with the same letter widths. The header reads "MeetDeck" where MM prints its own product name.

### Timers column (hand timing)
- Events tab → **Timers per lane: 1 timer / 2 timers** (saved per meet, in db/info.json `timers`).
- 1 timer: one time box per lane, as before.
- 2 timers: boxes for timer 1 and timer 2, plus the official time in bold. Official = average of the two with the thousandths dropped, or the single time if only one timer got it (NFHS 6-4-1b).
- Both inputs turn amber with a ⚠ when the timers differ by more than the timing tolerance (Setup, 0.30 s).
- Storage: timer 1 → `Fin_watch1`, timer 2 → `Sem_watch1` (unused by MM for timed-final events). The official time goes to `Fin_Time`, places are recalculated, and the Changes log shows both timer times. The results export is unchanged (still matches MM byte for byte).

### Typing times
- Every time box accepts `1:05.32`, `65.32`, or digits only. In digits only, the last two digits are hundredths, the two before are seconds, and the rest are minutes: `10532` = 1:05.32, `5632` = 56.32, `20117` = 2:01.17. `1:05` = 1:05.00.
- An impossible time such as `26118` (2:61.18) is refused with a message instead of being saved.

### Rules library (main page → Rules)
- PDFs kept in `data/rules/`, searchable by page (all words on one page; "quoted phrase"; rule numbers match 6-4-1 or 6.4.1). Results link straight to the page in the PDF.
- Starting set (official, free, 2026-27): NFHS Swimming & Diving Rules Interpretations, NFHS Rules Changes press release, the full 2026-27 UHSAA Handbook (232 pages), and its swimming section on its own.
- The full NFHS Rules Book is sold by NFHS (print or the NFHS Digital app) and isn't posted free. Add its PDF via the upload if you have one.

### Meet checklist (main page tab, formerly "Run the meet")
- A per-meet checklist from before meet day through the season. Checks are saved with the meet, with when each was done.
- Phases:
  - **Before meet day:** entries, database, 2 certified officials, timers 15+, printing, Final Meet Report form.
  - **Meet day:** console, sign-in, scratches.
  - **During:** Get times, DQ slips, score each event.
  - **Before leaving the venue:** end time, backup, initial results to all coaches.
  - **Within 24 h:** coaches review; change requests verified with the AO/meet referee.
  - **Within 48 h:** Final Meet Report and results to utahtop50@yahoo.com, with the referee, AO and host coach cc'd.
  - **All season:** keep all paperwork, including timer sheets and DQ info.
- The 24 h and 48 h deadlines count from the "Meet ended" time, which is also required on the result sheets per the UHSAA Handbook. They turn red when overdue.
- The email links open your mail app pre-addressed. Initial results BCC every coach email found in the entry files. The 48-hour email cc's the referee, AO and host coach emails entered on the page. Attach the results and the scanned Final Meet Report yourself.
- Sources: the 2026-27 process slide, and the UHSAA Handbook swimming section (qualifying conditions: electronic timing, two certified officials, results signed by both officials and head coaches, end time on the results). The handbook still says results within one week; the newer 48-hour rule is stricter, so it applies.
- Section index: each PDF's own table of contents is read, and each heading is matched to the page where it actually appears. Pages that print from an app reflow, so the offset is followed as it drifts. The UHSAA Handbook's running page header ("SWIMMING", "BY-LAWS") wins over its contents page. Search results show "document · section · page" and open the PDF at that page. Each document has a clickable Contents list. Index files: `<pdf>.json` (page text) and `<pdf>.toc.json` (sections).
- Also on file: the 2025-26 & 2026-27 NFHS Swimming & Diving Officials Manual (90 pages, Bryan's purchased copy, kept for private reference).
- Get times previews the chosen time and console place in the heat table below (dashed outline = not saved) until Apply to meet. Cancel clears the preview.

### Results report (Print ▾ → Results)
- PDF in Meet Manager's "Results" layout: two columns (rule at x=299), "Event N  Label" titles, Name / Yr / School / Finals Time, or Team / Relay / Finals Time.
- Places by time across all heats; ties share a place; exhibition swims are ranked in line and shown as `x1:05.32`. DQs come last with `---`, the time column reads DQ (DFS for a declared false start), and the DQ reason goes on the next line. Relays read "code 1: code 2". Relay swimmers print with their year, 1-2 on one line and 3-4 on the next.
- Splits print four per line. Individual swims show every 50 as a lap. Relays show laps on 50-yard legs, and on longer legs the first 50 then that leg's running total (MM's style).
- An event continues into the next column without a header. On a new page it continues as "(Event N  Label)" with the header repeated.
- `/api/meets/<id>/db/report/results.pdf`

### Heat and lane are locked
- The Events tab has no heat·lane column (the heat heading and the lane number already say it). Press **Move swimmers** on the event to get the heat/lane pickers back; it locks again when you press Done or switch events.

### Race numbers
- Every heat has a console race number in its heading ("Race [ 9 ]  Get times"). By default they count up one per heat in event order: event 1 heat 1 = race 1, event 7 heat 2 = race 8, and so on.
- Type a different number into any heat and the heats after it count up from there, unless they have their own number. A heat you've set shows bold with an "auto" link to undo it. Overrides are saved in db/info.json `races` and logged.
- Get times asks a real console for that race number (`/race?race=N`). The simulator still looks races up by event/heat. If the console's race turns out to be a different event or heat, the panel shows a warning before you apply.
- Next to every time is a read-only tag showing which time became official: **Pad** (green), **Button** (blue), **Timers** (amber) or **Manual** (typed in, matching none of them). Hover it to see all three: Pad · Button(s) · Timers. It's worked out from the stored pad/button/timer times, so it also reads Meet Manager databases. On Blue & Black it found 106 pad and 19 button times, the same 19 MM flagged "A" in its export.
- A relay whose swimmer has been scratched (from any event or the whole meet), or that has some legs filled and others open, turns red with "Relay not complete" and the reason; the event list shows ⚠ relay on that event. Fix it with **Swimmers**.
- Scratching takes two clicks: the first turns the button red ("Scratch Kylene?"), and a second click within 4 seconds scratches. Otherwise it goes back. Un-scratch is one click. Deleting an entry and scratching a swimmer from every event still ask in a dialog.
- The meet database page (where you run the meet) has its own **Rules** tab. It searches the same library, and results open the PDF at the right page. Links are now the accent color in dark mode (they were dark blue).

### Seeding (main page, section 6; Download is now 7)
- Seeding has its own section: the on/off switch, minimum swimmers per heat, the per-event summary, and **Heats after seeding**. That's the full heat sheet with a highlight search.
- Moving swimmers: click a swimmer or relay, then click a lane in the same event. An empty lane moves them, a filled lane swaps the two. While you're moving, each event shows a spare "New heat" to move into. Click the picked row again (or "cancel") to stop.
- Moves are saved with the meet (meta `seed_moves`, entry → heat/lane) and laid over the automatic seeding every time, so they survive new entries. A swimmer the seeding puts in a moved-to spot gets swapped into the mover's old spot. Moved lanes are tagged "moved". There's "reset this event" per event, and "Reset all moves" (with a confirm).
- The moves go into the Meet Manager backup (`_spec` uses the adjusted heat/lane). Once the meet database exists, use its Events tab → Move swimmers instead.
- The minimum heat size is fixed at 3 swimmers; the dropdown is gone. When heat 1 would be short, the slowest swimmers of the next heat move down.
- The main-page button that opens the meet database page is now labeled **Run the meet ↗**.
- The meet page has a **← Meet setup** button (left of the meet name). It opens the main page with that meet selected on the Meets tab (`/?meet=<id>`).

## MeetDeck for Windows (stand-alone, no server)
- Download: Setup tab -> **Download MeetDeck for Windows** (or `/download/MeetDeck-Windows.zip`). Unzip anywhere, double-click **MeetDeck.bat**; it opens in the browser, adds a desktop shortcut, and puts an "MD" icon in the tray (Open / Open data folder / Quit).
- Data lives in `Documents\MeetDeck` (first start copies the host schools' master meets, rules library, settings and meets that ship in the zip).
- No Java, nothing to install: 32-bit embeddable Python is inside, and Meet Manager files are opened with Windows' built-in **Microsoft Access (Jet) ODBC driver** - the engine Meet Manager uses. `app/mdbjet.py` is the Python port of `mmdb/Svc.java` + `Builder.java`; `app/mdbpass.py` reads the database password from the .mdb header (same method as Jackcess). `meetdb.JET` picks it on Windows; the Docker server keeps using Java.
- Timing bridge runs inside the app (port 8766), so the CTS console plugs straight into the laptop.
- Gmail: `Documents\MeetDeck\meetdeck.env` (GMAIL_USER / GMAIL_APP_PASSWORD). Report font: Cambria from `C:\Windows\Fonts`.
- Build: `windows/build.sh --with-meets` on plex (downloads Python + Windows wheels, writes `windows/dist/MeetDeck-Windows.zip` and copies it into the server's download folder).
- Verified on Windows 10: all three Meet Manager fixture meets export identical .hy3/.cl2 through the Jet driver; edits, scratches, PDFs and the Meet Manager backup (identical to the Java builder's) all work.
