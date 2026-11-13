"""Heat sheet ("Meet Program") PDF laid out like Meet Manager's: letter page, three columns,
each event kept together, every lane printed, relay swimmers two per line.

Positions are measured from a Meet Manager 8.0 heat sheet (points from the top of the page;
text positions are the top of the line, converted to a baseline below)."""
import datetime as dt
import io
import re
import time
import os

from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

import meetdb

PAGE_W, PAGE_H = letter
COLS = (18.0, 212.4, 406.8)
COL_W = 186.0
SEP = 185.25           # column rule offset from the column's left edge
TOP, BOTTOM = 82.3, 774.0
LAST_LANE = 652.0      # Meet Manager starts a new column once a lane line would sit below this
SZ, HSZ = 8.0, 9.9     # body and page-header type sizes
ROW = 10.8             # lane row
GAP_AFTER = 15.8       # last lane -> next event title

STROKE = {"A": "Freestyle", "B": "Backstroke", "C": "Breaststroke", "D": "Butterfly", "E": "IM"}
SEX = {"F": "Women", "W": "Women", "G": "Women", "M": "Men", "B": "Men", "X": "Mixed"}
UNIT = {1: "Meter", 2: "Meter", 3: "Yard"}


from paths import DATA_ROOT
FONT_DIR = os.environ.get("FONT_DIR", str(DATA_ROOT / "fonts"))


def _fonts():
    """Cambria is what Meet Manager prints in. If Cambria files have been added (Setup -> Report font,
    copied from a Windows PC: cambria.ttc + cambriab.ttf), use them; otherwise Caladea, its free
    metric-compatible twin."""
    names = pdfmetrics.getRegisteredFontNames()
    reg = next((os.path.join(FONT_DIR, f) for f in ("cambria.ttc", "cambria.ttf") if os.path.exists(os.path.join(FONT_DIR, f))), None)
    bold = os.path.join(FONT_DIR, "cambriab.ttf")
    if reg and os.path.exists(bold):
        if "Cam" in names:
            return "Cam", "Cam-B"
        try:
            pdfmetrics.registerFont(TTFont("Cam", reg, subfontIndex=0) if reg.endswith(".ttc") else TTFont("Cam", reg))
            pdfmetrics.registerFont(TTFont("Cam-B", bold))
            return "Cam", "Cam-B"
        except Exception:
            pass
    if "Cal" in names:
        return "Cal", "Cal-B"
    for d in ("/usr/share/fonts/truetype/crosextra", "/usr/share/fonts/truetype/caladea"):
        r, b = os.path.join(d, "Caladea-Regular.ttf"), os.path.join(d, "Caladea-Bold.ttf")
        if os.path.exists(r) and os.path.exists(b):
            pdfmetrics.registerFont(TTFont("Cal", r))
            pdfmetrics.registerFont(TTFont("Cal-B", b))
            return "Cal", "Cal-B"
    return "Times-Roman", "Times-Bold"


def event_title(v, course=3):
    unit = UNIT.get(course, "Yard")
    if v["ind_rel"] == "R":
        what = "Medley Relay" if v["stroke"] == "E" else f"{STROKE.get(v['stroke'], v['stroke'])} Relay"
    else:
        what = STROKE.get(v["stroke"], v["stroke"])
    return f"#{v['no']}{v.get('ltr') or ''} {SEX.get(v['gender'], v['gender'])} {v['dist']} {unit} {what}"


def _seed(e):
    s = meetdb.fmt_time(e["seed"]) or "NT"
    return ("X" + s) if e.get("exh") else s


def _name(a):
    if not a:
        return ""
    return f"{a.get('last', '')}, {a.get('first', '')}"


def _blocks(m):
    """Per event: list of heats, each a list of lanes (entry or None)."""
    lanes = int(m["meet"].get("lanes") or 8)
    out = []
    for v in sorted(m["events"], key=lambda v: (v.get("order") or (99, v["no"]), v["no"])):
        ents = [e for e in m["entries"] if e["event"] == v["ptr"] and not e["scr"] and e.get("heat")]
        if not ents:
            continue
        nheats = max(e["heat"] for e in ents)
        heats = []
        for h in range(1, nheats + 1):
            row = {e["lane"]: e for e in ents if e["heat"] == h}
            heats.append([row.get(ln) for ln in range(1, max([lanes] + list(row)) + 1)])
        out.append((v, heats))
    return out


REC_ROW = 9.4         # one record line under the event title


def event_records(m, v):
    """Records for this event to print under its title (host school's and the pool's, as m["records"]
    lists them): ["PAC Record: 1:58.57  2020  Hadlee Begay", ...] in the tags' order."""
    out = []
    sex = (v.get("gender") or "").upper()[:1]
    sex = {"G": "F", "W": "F", "B": "M"}.get(sex, sex)
    for r in m.get("records") or []:
        if ((r.get("gender") or "").upper()[:1] != sex or int(r.get("dist") or 0) != int(v.get("dist") or 0)
                or (r.get("stroke") or "") != (v.get("stroke") or "") or (r.get("indrel") or "I") != (v.get("ind_rel") or "I")
                or not r.get("time")):
            continue
        who = r.get("holder") or r.get("relay_names") or r.get("team") or ""
        if r.get("indrel") == "R" and r.get("relay_names") and r.get("team"):
            who = f"{r['team']}  {r['relay_names']}"
        out.append((r.get("order") or 99, f"{r.get('name') or 'Record'}: {meetdb.fmt_time(r['time'])}  {r.get('year') or ''}  {who}".replace("    ", "  ").strip()))
    return [t for _, t in sorted(out, key=lambda x: x[0])]


def _height(v, heats, recs=0):
    """Top of title to top of the next event's title."""
    y = 21.6 + recs * REC_ROW               # first heat line
    relay = v["ind_rel"] == "R"
    for i, lanes in enumerate(heats):
        if i:
            y += ROW                        # heat line after the previous lane
        y += 9.1                            # heat line -> lane 1
        for j, e in enumerate(lanes):
            if j:
                y += 28.1 if (relay and prev) else ROW
            prev = e
        last = y
    return last + GAP_AFTER


class _Sheet:
    def __init__(self, m, licensee, printed):
        self.m, self.licensee, self.printed = m, licensee, printed
        self.reg, self.bold = _fonts()
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=letter)
        title = f"{m['meet']['name']} - Heat Sheet"
        self.c.setTitle(title)
        self.c.setAuthor(licensee or "")
        self.page = 0
        self.col = 0
        self.y = TOP
        self.cols_used = set()

    # text helpers; `top` is measured from the top of the page like the original
    def fit(self, s, w, bold=False, size=SZ):
        """Text and size that fit width w: shrink down to 85%, then trim."""
        f = self.bold if bold else self.reg
        s = s or ""
        sw = pdfmetrics.stringWidth(s, f, size)
        if sw <= w:
            return s, size
        if sw * 0.85 <= w:
            return s, size * w / sw
        size = size * 0.85
        while s and pdfmetrics.stringWidth(s, f, size) > w:
            s = s[:-1]
        return s.rstrip(" ,"), size

    def team_label(self, tm, w, size, suffix=""):
        """Full team name if it fits (allowing a little shrink), otherwise the short name."""
        full = (tm.get("name") or tm.get("abbr") or "") + suffix
        f = self.reg
        if pdfmetrics.stringWidth(full, f, size) * 0.9 <= w:
            return full
        return (tm.get("short") or tm.get("abbr") or tm.get("name") or "") + suffix

    def text(self, x, top, s, bold=False, size=SZ, align="l", w=None):
        f = self.bold if bold else self.reg
        base = PAGE_H - (top + size * 0.778)       # baseline from the line's top, at the intended size
        if w:
            s, size = self.fit(s, w, bold, size)
        self.c.setFont(f, size)
        if align == "r":
            self.c.drawRightString(x, base, s)
        elif align == "c":
            self.c.drawCentredString(x, base, s)
        else:
            self.c.drawString(x, base, s)

    def rule(self, x0, x1, top, w=1.0):
        self.c.setLineWidth(w)
        y = PAGE_H - (top + w / 2)
        self.c.line(x0, y, x1, y)

    def new_page(self):
        if self.page:
            self.finish_page()
        self.page += 1
        self.col, self.y = 0, TOP
        self.cols_used = set()
        mt = self.m["meet"]
        self.text(18.0, 34.1, self.licensee, size=HSZ)
        stamp = f"MeetDeck - {self.printed.strftime('%I:%M %p').lstrip('0')}  " \
                f"{self.printed.month}/{self.printed.day}/{self.printed.year}  Page {self.page}"
        self.text(557.7, 34.1, stamp, size=HSZ, align="r")
        try:
            d = dt.date.fromisoformat(mt["start"])
            when = f"{d.month}/{d.day}/{d.year}"
        except Exception:
            when = mt.get("start") or ""
        self.text(PAGE_W / 2, 46.1, f"{mt['name']} - {when}" if when else mt["name"], bold=True, size=HSZ, align="c")
        self.text(PAGE_W / 2, 57.7, "Meet Program", bold=True, size=HSZ, align="c")

    def finish_page(self):
        self.c.setLineWidth(0.5)
        for i in range(3):
            x = COLS[i] + SEP
            self.c.line(x, PAGE_H - 76.0, x, PAGE_H - BOTTOM)
        self.c.showPage()

    def next_col(self):
        if self.col == 2:
            self.new_page()
        else:
            self.col += 1
            self.y = TOP

    def event(self, v, heats):
        h = _height(v, heats, len(event_records(self.m, v)))
        if self.y + h - GAP_AFTER > LAST_LANE and self.y > TOP:
            self.next_col()
            if self.y + h - GAP_AFTER > LAST_LANE:
                return self.event_split(v, heats)
        self.draw_event(v, heats, 0, len(heats))

    def event_split(self, v, heats):
        """An event taller than a column (many heats): break between heats, title repeated."""
        i = 0
        while i < len(heats):
            j = i + 1
            while j < len(heats) and self.y + _height(v, heats[i:j + 1], 0 if i else len(event_records(self.m, v))) - GAP_AFTER <= LAST_LANE:
                j += 1
            self.draw_event(v, heats, i, j)
            i = j
            if i < len(heats):
                self.next_col()

    def draw_event(self, v, heats, a, b):
        c, T = COLS[self.col], self.y
        relay = v["ind_rel"] == "R"
        aths, teams = self.m["athletes"], self.m["teams"]
        self.text(c, T, event_title(v, self.m["meet"].get("course") or 3) + (" (continued)" if a else ""), bold=True, w=COL_W)
        recs = [] if a else event_records(self.m, v)
        for k, line in enumerate(recs):       # the host school's and the pool's record, under the title like Meet Manager
            self.text(c, T + 9.6 + k * REC_ROW, line, size=SZ - 0.6, w=COL_W)
        T += len(recs) * REC_ROW
        self.rule(c, c + COL_W, T + 8.4)
        self.text(c, T + 10.8, "Lane", bold=True)
        if relay:
            self.text(c + 24.6, T + 10.8, "Team", bold=True)
            self.text(c + 108.0, T + 10.8, "Relay", bold=True)
        else:
            self.text(c + 24.6, T + 10.8, "Name", bold=True)
            self.text(c + 99.8, T + 10.8, "Yr", bold=True)
            self.text(c + 111.6, T + 10.8, "School", bold=True)
        self.text(c + 179.9, T + 10.8, "Seed Time", bold=True, align="r")
        self.rule(c, c + COL_W, T + 19.1)
        y = T + 21.6
        for hi in range(a, b):
            if hi > a:
                y += ROW
            self.text(c, y, "Heat", bold=True)
            hs = f"{hi + 1} of {len(heats)}"
            self.text(c + 22.6, y, hs, bold=True)
            fx = max(c + 48.4, c + 22.6 + pdfmetrics.stringWidth(hs, self.bold, SZ) + 5.4)
            self.text(fx, y, "Finals", bold=True)
            y += 9.1
            prev = None
            for j, e in enumerate(heats[hi]):
                if j:
                    y += 28.1 if (relay and prev) else ROW
                prev = e
                self.text(c + 13.0, y, str(j + 1), align="r")
                if not e:
                    continue
                if relay:
                    tm = teams.get(e["team"], {})
                    self.text(c + 17.4, y, tm.get("abbr", ""), w=94)
                    self.text(c + 114.0, y, e.get("ltr") or "")
                    self.text(c + 180.0, y, _seed(e), align="r")
                    legs = [aths.get(x) for x in (e.get("legs") or [])[:4]] + [None] * 4
                    for k in range(2):
                        self.text(c + 24.0, y + (10.8 if k == 0 else 19.5), _name(legs[2 * k]), w=82)
                        self.text(c + 108.0, y + (10.8 if k == 0 else 19.5), _name(legs[2 * k + 1]), w=76)
                else:
                    a_ = aths.get(e["ath"], {})
                    self.text(c + 17.4, y, _name(a_), w=80)
                    if a_.get("yr"):
                        self.text(c + 99.8, y, a_["yr"], w=13)
                    self.text(c + 114.0, y, teams.get(a_.get("team"), {}).get("abbr", ""), w=40)
                    self.text(c + 180.0, y, _seed(e), align="r")
        self.y = y + GAP_AFTER

    def team_scores(self):
        """Meet Manager's "Scores" block at the end: each team's women's, men's and combined points."""
        evs, aths, teams = {v["ptr"]: v for v in self.m["events"]}, self.m["athletes"], self.m["teams"]
        tot = {}
        for e in self.m["entries"]:
            pts = e.get("points") or 0
            if pts <= 0 or e["scr"]:
                continue
            tno = e["team"] if e["kind"] == "R" else aths.get(e["ath"], {}).get("team")
            v = evs.get(e["event"], {})
            women = (v.get("sex") or v.get("gender") or "").upper() in ("F", "W", "G")
            t = tot.setdefault(tno, [0.0, 0.0])
            t[0 if women else 1] += pts
        if not tot:
            return
        rows = sorted(tot.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))
        need = 24.2 + 11.5 * (len(rows) + 1)
        self.y += 10.0
        if self.y + need > R_LAST:
            self.next_area(None, False)
        c, T = self.col_x(), self.y
        self.text(c, T, "Scores - Team", bold=True, size=RTSZ)
        h = T + 12.0
        for x, lab, al in ((24.0, "Team", "l"), (190.0, "Women", "r"), (232.0, "Men", "r"), (RW, "Total", "r")):
            self.text(c + x, h, lab, bold=True, size=RTSZ, align=al)
        self.c.setLineWidth(0.75)
        self.c.line(c, PAGE_H - (T + 20.0), c + RW, PAGE_H - (T + 20.0))
        self.y = T + 24.2
        f = lambda x: f"{x:g}"
        for i, (tno, (w, mpts)) in enumerate(rows, 1):
            t = teams.get(tno, {})
            for x, txt, al, ww in ((18.0, str(i), "r", None), (24.0, t.get("name") or t.get("abbr", ""), "l", 150), (190.0, f(w), "r", None),
                                   (232.0, f(mpts), "r", None), (RW, f(w + mpts), "r", None)):
                self.text(c + x, self.y, txt, bold=(x == RW), size=RSZ, align=al, w=ww)
            self.y += 11.5

    def render(self):
        self.new_page()
        for v, heats in _blocks(self.m):
            self.event(v, heats)
        self.finish_page()
        self.c.save()
        return self.buf.getvalue()


def heat_sheet_pdf(m, licensee="", printed=None) -> bytes:
    if printed is None:
        try:
            from zoneinfo import ZoneInfo
            printed = dt.datetime.now(ZoneInfo("America/Denver"))
        except Exception:
            printed = dt.datetime.now()
    return _Sheet(m, licensee, printed).render()


# ---------------- referee program: one event per page, blanks for finals time and place ----------------
class _Referee(_Sheet):
    BOTTOM = 760.0

    def page_for(self, v, cont=False):
        self.new_page()
        c = 18.0
        no = f"{v['no']}{v.get('ltr') or ''}"
        self.text(c, 81.2, "Event", bold=True, size=HSZ)
        self.text(47.7, 81.2, no, bold=True, size=HSZ)
        lx = max(60.1, 47.7 + pdfmetrics.stringWidth(no, self.bold, HSZ) + 6.5)
        self.text(lx, 81.2, event_title(v, self.m["meet"].get("course") or 3).split(" ", 1)[1] + (" (continued)" if cont else ""),
                  bold=True, size=HSZ)
        relay = v["ind_rel"] == "R"
        self.text(18.0, 92.2, "Lane", bold=True, size=HSZ)
        if relay:
            self.text(54.0, 92.2, "Team", bold=True, size=HSZ)
            self.text(228.0, 92.2, "Relay", bold=True, size=HSZ)
        else:
            self.text(54.0, 92.2, "Name", bold=True, size=HSZ)
            self.text(222.0, 92.2, "Year", bold=True, size=HSZ, align="r")
            self.text(228.0, 92.2, "School", bold=True, size=HSZ)
        self.text(426.0, 92.2, "Seed Time", bold=True, size=HSZ, align="r")
        self.text(533.9, 92.2, "Finals", bold=True, size=HSZ, align="r")
        self.text(576.0, 92.2, "Place", bold=True, size=HSZ, align="r")
        self.c.setFillGray(0)
        self.c.rect(18.0, PAGE_H - 103.4, 558.0, 0.9, stroke=0, fill=1)
        return 105.3

    @staticmethod
    def heat_h(heats_lanes, relay):
        y = 12.2
        for j, e in enumerate(heats_lanes):
            if j:
                y += 23.0 if (relay and prev) else 11.5
            prev = e
        return y + 11.4                      # to the next heat line

    def event(self, v, heats):
        relay = v["ind_rel"] == "R"
        aths, teams = self.m["athletes"], self.m["teams"]
        y = self.page_for(v)
        for hi, lanes in enumerate(heats):
            if hi and y + self.heat_h(lanes, relay) - 11.4 > self.BOTTOM:
                y = self.page_for(v, cont=True)
            self.text(18.0, y, "Heat", bold=True, size=HSZ)
            self.text(45.8, y, f"{hi + 1} of {len(heats)}", bold=True, size=HSZ)
            self.text(77.3, y, "Timed Finals", bold=True, size=HSZ)
            y += 12.2
            prev = None
            for j, e in enumerate(lanes):
                if j:
                    y += 23.0 if (relay and prev) else 11.5
                prev = e
                self.text(34.35, y, str(j + 1), size=11.0, align="c")
                self.text(480.0, y, "_" * 17, size=HSZ)
                self.text(548.5, y, "_" * 7, size=HSZ)
                if not e:
                    continue
                self.text(426.0, y, _seed(e), size=HSZ, align="r")
                if relay:
                    tm = teams.get(e["team"], {})
                    self.text(54.0, y, self.team_label(tm, 170, 11.0), size=11.0, w=170)
                    self.text(228.0, y, e.get("ltr") or "", size=HSZ)
                    legs = [aths.get(x) for x in (e.get("legs") or [])[:4]] + [None] * 4
                    for k, x in enumerate((54.0, 162.0, 269.9, 372.0)):
                        if legs[k]:
                            self.text(x, y + 11.2, f"{k + 1}) {_name(legs[k])}", size=9.0, w=(104, 104, 98, 100)[k])
                else:
                    a_ = aths.get(e["ath"], {})
                    self.text(54.0, y, _name(a_), size=11.0, w=140)
                    if a_.get("yr"):
                        self.text(222.0, y, a_["yr"], size=HSZ, align="r")
                    self.text(228.0, y, self.team_label(teams.get(a_.get("team"), {}), 160, HSZ), size=HSZ, w=160)
            y += 11.4

    def finish_page(self):
        self.c.showPage()

    def render(self):
        for v, heats in _blocks(self.m):
            self.event(v, heats)
        if not self.page:
            self.new_page()
        self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


def referee_pdf(m, licensee="", printed=None) -> bytes:
    if printed is None:
        try:
            from zoneinfo import ZoneInfo
            printed = dt.datetime.now(ZoneInfo("America/Denver"))
        except Exception:
            printed = dt.datetime.now()
    r = _Referee(m, licensee, printed)
    r.c.setTitle(f"{m['meet']['name']} - Referee Program")
    return r.render()


# ---------------- timer sheets: one set of pages per lane, every heat of every event ----------------
class _Timer(_Sheet):
    LAST_ROW = 740.0

    def __init__(self, m, licensee, printed):
        super().__init__(m, licensee, printed)
        self.first_on_page = True

    def new_page(self):
        if self.page:
            self.c.showPage()
        self.page += 1
        self.first_on_page = True
        mt = self.m["meet"]
        try:
            d = dt.date.fromisoformat(mt["start"])
            when = f"{d.month}/{d.day}/{d.year}"
        except Exception:
            when = mt.get("start") or ""
        self.text(293.85, 63.7, f"{mt['name']} - {when}" if when else mt["name"], bold=True, size=HSZ, align="c")
        self.y = 75.2

    @staticmethod
    def rows_h(rows, relay):
        return 19.2 + sum(36.2 if (relay and e) else 25.25 for e in rows)

    def box(self, x, top):
        self.c.setLineWidth(1.0)
        self.c.rect(x + 0.5, PAGE_H - (top + 11.5), 13.4, 11.0, stroke=1, fill=0)

    def lane_event(self, lane, v, heats):
        relay = v["ind_rel"] == "R"
        rows = [hl[lane - 1] if lane - 1 < len(hl) else None for hl in heats]
        h = self.rows_h(rows, relay)
        last_row = self.y + h - (36.2 if (relay and rows[-1]) else 25.25)
        if last_row > self.LAST_ROW and not self.first_on_page:
            self.new_page()
        T = self.y
        self.text(36.0, T, f"Event {v['no']}{v.get('ltr') or ''} " + event_title(v, self.m["meet"].get("course") or 3).split(" ", 1)[1] + " Finals",
                  bold=True, size=HSZ)
        if self.first_on_page:
            self.text(557.6, T, "Soft Touch ?", bold=True, size=HSZ, align="r")
            self.first_on_page = False
        self.c.setFillGray(0)
        self.c.rect(48.7, PAGE_H - (T + 11.2), 521.3, 1.0, stroke=0, fill=1)
        y = T + 19.2
        aths, teams = self.m["athletes"], self.m["teams"]
        for hi, e in enumerate(rows):
            self.text(36.0, y, "Lane", size=HSZ)
            self.text(58.8, y, str(lane), size=HSZ)
            self.text(78.0, y, "Heat", size=HSZ)
            self.text(100.0, y, str(hi + 1), size=HSZ)
            if not e:
                self.text(120.0, y, "_" * 30, size=HSZ)
            elif relay:
                tm = teams.get(e["team"], {})
                ltr = " " + (e.get("ltr") or "")
                lw = pdfmetrics.stringWidth(ltr, self.reg, HSZ)
                nm, sz = self.fit(self.team_label(tm, 120 - lw, HSZ), 120 - lw, False, HSZ)
                self.text(120.0, y, nm + ltr, size=sz)
                self.text(245.9, y, tm.get("abbr", ""), size=HSZ, w=70)
                self.text(319.6, y, _seed(e), size=HSZ)
            else:
                a_ = aths.get(e["ath"], {})
                self.text(120.0, y, _name(a_), size=HSZ, w=120)
                self.text(245.9, y, teams.get(a_.get("team"), {}).get("abbr", ""), size=HSZ, w=70)
                self.text(319.6, y, _seed(e), size=HSZ)
            for x in (373.2, 426.0, 480.0):
                self.text(x, y, "_" * 10, size=HSZ)
            self.box(543.6, y - 1.0)
            if relay and e:
                legs = [aths.get(x) for x in (e.get("legs") or [])[:4]] + [None] * 4
                for k, x in enumerate((126.0, 233.9, 341.9, 461.9)):
                    if legs[k]:
                        self.text(x, y + 13.1, f"{k + 1}) {_name(legs[k])}", size=9.0, w=(102, 102, 114, 80)[k])
                y += 36.2
            else:
                y += 25.25
        self.y = y

    def render(self):
        blocks = _blocks(self.m)
        lanes = int(self.m["meet"].get("lanes") or 8)
        for lane in range(1, lanes + 1):
            self.new_page()
            for v, heats in blocks:
                self.lane_event(lane, v, heats)
        if not self.page:
            self.new_page()
        self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


def timer_pdf(m, licensee="", printed=None, lane=None) -> bytes:
    t = _Timer(m, licensee, printed or dt.datetime.now())
    t.c.setTitle(f"{m['meet']['name']} - Timer Sheets")
    if lane:
        t.m = {**m, "meet": {**m["meet"]}}
        blocks = _blocks(m)
        t.new_page()
        for v, heats in blocks:
            t.lane_event(int(lane), v, heats)
        t.c.showPage()
        t.c.save()
        return t.buf.getvalue()
    return t.render()


def font_status() -> dict:
    have = {f: os.path.exists(os.path.join(FONT_DIR, f)) for f in ("cambria.ttc", "cambriab.ttf")}
    return {"cambria": have["cambria.ttc"] and have["cambriab.ttf"], "files": have}


# ---------------- results: two columns, places, relay swimmers with year, splits, DQ reasons ----------------
import dqcodes   # noqa: E402

RCOLS = (18.0, 309.6)
RW = 274.5
RSZ, RTSZ = 7.7, 8.5          # rows, titles
R_LAST = 718.0                # last line of a block must sit above this


def _lap_splits(cum: list, final: float) -> list:
    """Cumulative split times (with the final added) -> lap times, as Meet Manager prints them."""
    pts = [t or 0 for t in cum]
    if final and (not pts or abs(pts[-1] - final) > 0.001):
        pts.append(final)
    out, prev = [], 0.0
    for t in pts:
        out.append(round(t - prev, 2) if t else 0)
        prev = t or prev
    return out


def _relay_splits(cum: list, final: float, legs: int = 4) -> list:
    """Relays: 50-yard legs show the lap; longer legs show lap, then the leg's running total."""
    pts = [t or 0 for t in cum]
    if final and (not pts or abs(pts[-1] - final) > 0.001):
        pts.append(final)
    if not pts:
        return []
    per = max(1, len(pts) // legs)
    out, prev, leg_start = [], 0.0, 0.0
    for i, t in enumerate(pts):
        k = i % per
        if k == 0:
            leg_start = prev
        if per == 1 or k % 2 == 0:
            out.append(round(t - prev, 2) if t else 0)
        else:
            out.append(round(t - leg_start, 2) if t else 0)
        prev = t or prev
    return out


class _Results(_Sheet):
    def __init__(self, m, licensee, printed, splits_by_key):
        super().__init__(m, licensee, printed)
        self.sp = splits_by_key
        self.c.setTitle(f"{m['meet']['name']} - Results")
        self.has_pts = any((e.get("points") or 0) > 0 for e in m["entries"])      # scored: points column + team scores

    def new_page(self):
        if self.page:
            self.finish_page()
        self.page += 1
        self.col, self.y = 0, 76.8
        mt = self.m["meet"]
        self.text(18.0, 35.2, self.licensee, size=RTSZ)
        stamp = f"MeetDeck - {self.printed.strftime('%I:%M %p').lstrip('0')}  " \
                f"{self.printed.month}/{self.printed.day}/{self.printed.year}  Page {self.page}"
        self.text(557.8, 35.2, stamp, size=RTSZ, align="r")
        try:
            d = dt.date.fromisoformat(mt["start"])
            when = f"{d.month}/{d.day}/{d.year}"
        except Exception:
            when = mt.get("start") or ""
        self.text(PAGE_W / 2, 47.2, f"{mt['name']} - {when}" if when else mt["name"], bold=True, size=RTSZ, align="c")
        self.text(PAGE_W / 2, 59.5, "Results", bold=True, size=RTSZ, align="c")
        self.c.setLineWidth(0.75)
        self.c.line(18.0, PAGE_H - 67.5, 586.5, PAGE_H - 67.5)

    def finish_page(self):
        self.c.setLineWidth(0.75)
        self.c.line(299.2, PAGE_H - 67.5, 299.2, PAGE_H - 774.0)
        self.c.showPage()

    def col_x(self):
        return RCOLS[self.col]

    def header(self, v, cont=False):
        c, T = self.col_x(), self.y
        label = event_title(v, self.m["meet"].get("course") or 3).split(" ", 1)[1]
        no = f"{v['no']}{v.get('ltr') or ''}"
        self.text(c, T, f"(Event {no}  {label})" if cont else f"Event {no}  {label}", bold=True, size=RTSZ, w=RW)
        h = T + 12.0
        if v["ind_rel"] == "R":
            self.text(c + 24.0, h, "Team", bold=True, size=RTSZ)
            self.text(c + 132.0, h, "Relay", bold=True, size=RTSZ)
        else:
            self.text(c + 24.0, h, "Name", bold=True, size=RTSZ)
            self.text(c + 138.0, h, "Yr", bold=True, size=RTSZ, align="r")
            self.text(c + 137.6, h, "School", bold=True, size=RTSZ)
        self.text(c + 240.0, h, "Finals Time", bold=True, size=RTSZ, align="r")
        if self.has_pts:
            self.text(c + RW, h, "Points", bold=True, size=RTSZ, align="r")
        self.c.setLineWidth(0.75)
        self.c.line(c, PAGE_H - (T + 20.0), c + RW, PAGE_H - (T + 20.0))
        self.y = T + 24.2

    def rows(self, v):
        """Blocks of lines for an event, in results order."""
        aths, teams = self.m["athletes"], self.m["teams"]
        relay = v["ind_rel"] == "R"
        ents = [e for e in self.m["entries"] if e["event"] == v["ptr"] and not e["scr"]]
        stat = lambda e: (e["stat"] or "").strip()
        fin = sorted((e for e in ents if e["time"] and stat(e) == ""), key=lambda e: e["time"])
        dqs = sorted((e for e in ents if stat(e) in ("Q", "F", "D")), key=lambda e: (e["time"] or 9e9))
        blocks, place, prev_t = [], 0, None
        for i, e in enumerate(fin):
            if prev_t is None or abs(e["time"] - prev_t) > 0.001:
                place = i + 1
            prev_t = e["time"]
            blocks.append(self.block(v, e, str(place), relay, aths, teams))
        for e in dqs:
            blocks.append(self.block(v, e, "---", relay, aths, teams))
        return blocks

    def block(self, v, e, place, relay, aths, teams):
        lines = []          # (dy, [(x, text, align)])
        st = (e["stat"] or "").strip()
        dfs = st in ("Q", "F", "D") and (e.get("dq") or "").upper() in ("7B", "7P") and not e["time"]
        if st in ("Q", "F", "D"):
            tm = "DFS" if dfs else "DQ"
        else:
            tm = ("x" if e.get("exh") else "") + meetdb.fmt_time(e["time"])
        nm = lambda a: (f"{a.get('last', '')}, {a.get('first', '')}" + (f" {a['initial']}" if a.get("initial") else "")) if a else ""
        pts = f"{e['points']:g}" if self.has_pts and (e.get("points") or 0) > 0 and st == "" else ""
        if relay:
            tmn = teams.get(e["team"], {})
            lines.append((0, [(18.0, place, "r"), (24.0, tmn.get("abbr", ""), "l", 116), (144.0, e.get("ltr") or "", "l"), (240.0, tm, "r"),
                              (RW, pts, "r")]))
        else:
            a = aths.get(e["ath"], {})
            lines.append((0, [(18.0, place, "r"), (24.0, nm(a), "l", 108), (138.0, a.get("yr", ""), "r"),
                              (144.0, teams.get(a.get("team"), {}).get("abbr", ""), "l", 60), (240.0, tm, "r"), (RW, pts, "r")]))
        y = 11.5
        if st in ("Q", "F", "D") and e.get("dq"):
            if relay:
                d1 = dqcodes.describe(e["dq"], v["stroke"], True)
                d2 = dqcodes.describe(e["dq2"], v["stroke"], True) if e.get("dq2") else ""
                txt = f"{d1}: {d2}" if d2 else d1
            else:
                txt = dqcodes.describe(e["dq"], v["stroke"], False)
            lines.append((y, [(30.0, txt, "l", 240)]))
            y += 11.5
        if relay:
            legs = (e.get("legs") or [])[:4]
            leg = lambda k: (lambda a: f"{k + 1}) {nm(a)}" + (f" {a['yr']}" if a and a.get("yr") else ""))(aths.get(legs[k]) if k < len(legs) else None)
            if any(legs):
                lines.append((y, [(24.0, leg(0), "l", 116), (144.0, leg(1), "l", 128)]))
                lines.append((y + 11.0, [(24.0, leg(2), "l", 116), (144.0, leg(3), "l", 128)]))
                y += 22.0
        cum = [t for _, t in self.sp.get(e["key"], [])]
        final = e["time"] if (not st or st == "Q") else 0
        sp = (_relay_splits(cum, final, max(1, len([x for x in (e.get("legs") or []) if x]) or 4)) if relay else _lap_splits(cum, final)) if cum else []
        for i in range(0, len(sp), 4):
            lines.append((y, [(65.8 + 48.0 * j, meetdb.fmt_time(t) if t else "", "r") for j, t in enumerate(sp[i:i + 4])]))
            y += 11.0 if i + 4 < len(sp) else 11.0
        return {"lines": lines, "h": (lines[-1][0] if lines else 0)}

    def draw_block(self, b):
        c = self.col_x()
        for dy, items in b["lines"]:
            for it in items:
                x, s, al = it[0], it[1], it[2]
                self.text(c + x, self.y + dy, str(s), size=RSZ, align=al, w=it[3] if len(it) > 3 else None)
        self.y += b["h"] + 11.5 if b["lines"] and len(b["lines"]) > 0 else 11.5

    def next_area(self, v, cont):
        if self.col == 0:
            self.col, self.y = 1, (71.5 if cont else 76.8)
            if cont:
                return                       # same page: Meet Manager just keeps listing
        else:
            self.new_page()
            self.y = 71.8 if cont else 76.8
        if v is not None:
            self.header(v, cont=cont)

    def team_scores(self):
        """Meet Manager's "Scores" block at the end: each team's women's, men's and combined points."""
        evs, aths, teams = {v["ptr"]: v for v in self.m["events"]}, self.m["athletes"], self.m["teams"]
        tot = {}
        for e in self.m["entries"]:
            pts = e.get("points") or 0
            if pts <= 0 or e["scr"]:
                continue
            tno = e["team"] if e["kind"] == "R" else aths.get(e["ath"], {}).get("team")
            v = evs.get(e["event"], {})
            women = (v.get("sex") or v.get("gender") or "").upper() in ("F", "W", "G")
            t = tot.setdefault(tno, [0.0, 0.0])
            t[0 if women else 1] += pts
        if not tot:
            return
        rows = sorted(tot.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))
        need = 24.2 + 11.5 * (len(rows) + 1)
        self.y += 10.0
        if self.y + need > R_LAST:
            self.next_area(None, False)
        c, T = self.col_x(), self.y
        self.text(c, T, "Scores - Team", bold=True, size=RTSZ)
        h = T + 12.0
        for x, lab, al in ((24.0, "Team", "l"), (190.0, "Women", "r"), (232.0, "Men", "r"), (RW, "Total", "r")):
            self.text(c + x, h, lab, bold=True, size=RTSZ, align=al)
        self.c.setLineWidth(0.75)
        self.c.line(c, PAGE_H - (T + 20.0), c + RW, PAGE_H - (T + 20.0))
        self.y = T + 24.2
        f = lambda x: f"{x:g}"
        for i, (tno, (w, mpts)) in enumerate(rows, 1):
            t = teams.get(tno, {})
            for x, txt, al, ww in ((18.0, str(i), "r", None), (24.0, t.get("name") or t.get("abbr", ""), "l", 150), (190.0, f(w), "r", None),
                                   (232.0, f(mpts), "r", None), (RW, f(w + mpts), "r", None)):
                self.text(c + x, self.y, txt, bold=(x == RW), size=RSZ, align=al, w=ww)
            self.y += 11.5

    def render(self):
        self.new_page()
        first = True
        for v in sorted(self.m["events"], key=lambda v: (v.get("order") or (99, v["no"]), v["no"])):
            blocks = self.rows(v)
            if not blocks:
                continue
            if not first:
                self.y += 4.8                # gap before the next event title
            first = False
            # the title, header and first result must stay together
            if self.y + 24.2 + blocks[0]["h"] > R_LAST:
                self.next_area(None, False)
            self.header(v)
            for b in blocks:
                if self.y + b["h"] > R_LAST:
                    self.next_area(v, cont=True)
                self.draw_block(b)
        if self.has_pts:
            self.team_scores()
        self.finish_page()
        self.c.save()
        return self.buf.getvalue()


def results_pdf(m, db, licensee="", printed=None) -> bytes:
    import results as results_mod
    if printed is None:
        try:
            from zoneinfo import ZoneInfo
            printed = dt.datetime.now(ZoneInfo("America/Denver"))
        except Exception:
            printed = dt.datetime.now()
    return _Results(m, licensee, printed, results_mod.splits(db)).render()


# ---------------- timeline (Meet Manager's Session Report) ----------------
TL_SEX = {"G": "Women", "B": "Men", "W": "Women", "F": "Women", "M": "Men", "X": "Mixed"}
TL_STROKE = {"A": "Freestyle", "B": "Backstroke", "C": "Breaststroke", "D": "Butterfly", "E": "IM"}


def _tl_title(v):
    what = ("Medley Relay" if v["stroke"] == "E" else f"{TL_STROKE.get(v['stroke'], v['stroke'])} Relay") if v["ind_rel"] == "R" \
        else TL_STROKE.get(v["stroke"], v["stroke"])
    return f"{TL_SEX.get(v.get('sex') or v['gender'], v['gender'])} {v['dist']} {what}"


def _nt_estimate(v, course):
    """Meet Manager's canned time for an NT swim: distance x a stroke/distance factor (x1.1 for meters)."""
    d, st = v["dist"], v["stroke"]
    if d <= 200:
        f = {"A": 0.82, "C": 0.90}.get(st, 0.85)
    else:
        f = {"A": 0.95, "C": 1.0}.get(st, 0.90)
    return d * f * (1.1 if course in ("L", "S") else 1.0)


def timeline(m, gap_min=None) -> list:
    """Session Report timeline, worked out the way Meet Manager does:
    each heat lasts as long as its slowest seed time (NT entries don't count unless the whole heat is NT,
    then a canned estimate) plus the session's heat interval, plus the backstroke allowance for events that
    start in the water (backstroke and medley relays). Unseeded events use the average entry time and a
    projected heat count. Start times are rounded up to the minute.
    gap_min: break between sessions (minutes). When set, a later session on the same day starts that long after
    the one before it is projected to finish, instead of at its Meet Manager start time."""
    import math
    evs = {v["ptr"]: v for v in m["events"]}
    lanes = m["meet"].get("lanes") or 8
    out = []
    for s in m.get("sessions", []):
        if gap_min is not None and out and out[-1]["day"] == s["day"]:
            s = {**s, "start": out[-1]["finish"] + int(gap_min) * 60}
        t, rows, swimmers, n_ent, n_heat = 0.0, [], set(), 0, 0
        for it in s["items"]:
            v = evs.get(it["event"])
            if not v:
                continue
            t += it["delay"] or 0
            ents = [e for e in m["entries"] if e["event"] == v["ptr"] and not e["scr"]]
            for e in ents:
                if e["kind"] == "I":
                    swimmers.add(e["ath"])
                else:
                    swimmers.update(a for a in e["legs"] if a)
            back = s["back"] if (v["stroke"] == "B" or (v["ind_rel"] == "R" and v["stroke"] == "E")) else 0
            nt = _nt_estimate(v, s["course"])
            seeded = any(e["heat"] for e in ents)
            start = t
            if seeded:
                heats = sorted({e["heat"] for e in ents if e["heat"]})
                for h in heats:
                    times = [e["conv"] or e["seed"] for e in ents if e["heat"] == h]
                    slow = max([x for x in times if x] or [nt])
                    t += slow + s["interval"] + back
                nh, proj = len(heats), False
            else:
                nh, proj = (math.ceil(len(ents) / lanes) if ents else 0), True
                times = [e["conv"] or e["seed"] for e in ents if (e["conv"] or e["seed"])]
                avg = sum(times) / len(times) if times else nt
                t += nh * (avg + s["interval"] + back)
            n_ent += len(ents)
            n_heat += nh
            rows.append({"no": v["no"], "ltr": v.get("ltr") or "", "title": _tl_title(v), "round": "Finals" if it["rnd"] == "F" else "Prelims",
                         "entries": len(ents), "heats": nh, "projected": proj, "start": s["start"] + math.ceil(start / 60 - 1e-9) * 60,
                         "break": it["delay_desc"] if it["delay"] else ""})
        out.append({**{k: s[k] for k in ("no", "ltr", "name", "day", "start", "interval", "back")}, "rows": rows,
                    "swimmers": len(swimmers), "entries": n_ent, "heats": n_heat,
                    "finish": s["start"] + math.ceil(t / 60 - 1e-9) * 60})
    return out


def _clock(sec):
    h, mi = divmod(int(sec) // 60, 60)
    return f"{(h - 1) % 12 + 1:02d}:{mi:02d} {'AM' if h % 24 < 12 else 'PM'}"


def timeline_pdf(m, licensee="", printed=None, gap_min=None) -> bytes:
    if printed is None:
        try:
            from zoneinfo import ZoneInfo
            printed = dt.datetime.now(ZoneInfo("America/Denver"))
        except Exception:
            printed = dt.datetime.now()
    sh = _Sheet(m, licensee, printed)
    sh.c.setTitle(f"{m['meet']['name']} - Session Report")
    mt = m["meet"]
    try:
        d = dt.date.fromisoformat(mt["start"])
        when = f"{d.month}/{d.day}/{d.year}"
    except Exception:
        when = mt.get("start") or ""
    sessions = timeline(m, gap_min) or [{"no": 0, "ltr": "", "name": "No sessions set up in Meet Manager", "day": 1, "start": 0,
                                "interval": 0, "back": 0, "rows": [], "swimmers": 0, "entries": 0, "heats": 0, "finish": 0}]
    X_RND, X_NO, X_EV, X_ENT, X_HT, X_ST, X_END = 28.0, 177.0, 187.0, 588.0, 672.0, 709.0, 869.0
    k = 0.6458   # the layout above is in 936-wide units (the original's), scaled to the page
    S = lambda x: x * k
    for page, s in enumerate(sessions, 1):
        if page > 1:
            sh.c.showPage()
        sh.text(18.0, 34.1, licensee, size=HSZ)
        stamp = f"MeetDeck - {printed.strftime('%I:%M %p').lstrip('0')}  {printed.month}/{printed.day}/{printed.year}  Page {page}"
        sh.text(557.7, 34.1, stamp, size=HSZ, align="r")
        sh.text(PAGE_W / 2, 46.1, f"{mt['name']} - {when}" if when else mt["name"], bold=True, size=HSZ, align="c")
        sh.text(PAGE_W / 2, 57.7, "Session Report", bold=True, size=HSZ, align="c")
        sh.text(PAGE_W / 2, 90.0, f"Session: {s['no']}{s['ltr'] or ''}   {s['name']}", size=HSZ, align="c")
        sh.text(PAGE_W / 2, 101.5, f"Day of Meet: {s['day']}   Starts at {_clock(s['start'])}   Heat Interval: {s['interval']} Seconds"
                + (f" / Back +{s['back']} Seconds" if s["back"] else ""), size=HSZ, align="c")
        y = 126.0
        for x, lab, al in ((X_RND, "Round", "l"), (X_EV, "Event", "l"), (X_ENT, "Entries", "r"), (X_HT, "Heats", "r"), (X_ST + 66, "Starts at", "r")):
            sh.text(S(x), y, lab, bold=True, size=SZ + 0.5, align=al)
        sh.rule(S(X_RND), S(X_END), y + 10.5, 0.7)
        y += 15.0
        for r in s["rows"]:
            if r["break"]:
                sh.text(S(X_EV), y, r["break"], size=SZ + 0.5)
                y += 13.5
            sh.text(S(X_RND), y, r["round"], size=SZ + 0.5)
            sh.text(S(X_NO), y, f"{r['no']}{r['ltr']}", size=SZ + 0.5, align="r")
            sh.text(S(X_EV), y, r["title"], size=SZ + 0.5, w=S(X_ENT - X_EV - 60))
            sh.text(S(X_ENT), y, str(r["entries"]), size=SZ + 0.5, align="r")
            sh.text(S(X_HT), y, f"{r['heats']}{'u' if r['projected'] else ''}", size=SZ + 0.5, align="r")
            sh.text(S(X_ST + 66), y, _clock(r["start"]), size=SZ + 0.5, align="r")
            sh.rule(S(X_END - 43), S(X_END), y + 9.5, 0.5)
            y += 13.5
            if y > 740:
                sh.c.showPage()
                y = 60.0
        if s["rows"]:
            sh.text(S(X_EV + 6), y, f"Swimmers Counts for Warm-ups: {s['swimmers']}", size=SZ + 0.5)
            sh.text(S(X_ENT), y, "====", size=SZ + 0.5, align="r")
            sh.text(S(X_HT), y, "====", size=SZ + 0.5, align="r")
            y += 13.5
            sh.text(S(X_EV + 6), y, "Entry / Heat Totals:", size=SZ + 0.5)
            sh.text(S(X_ENT), y, str(s["entries"]), size=SZ + 0.5, align="r")
            sh.text(S(X_HT), y, str(s["heats"]), size=SZ + 0.5, align="r")
            y += 13.5
            sh.text(S(X_EV + 6), y, "Finish Time", size=SZ + 0.5)
            sh.text(S(X_ST + 66), y, _clock(s["finish"]), size=SZ + 0.5, align="r")
            sh.rule(S(X_END - 43), S(X_END), y + 9.5, 0.5)
    sh.c.showPage()
    sh.c.save()
    return sh.buf.getvalue()


# ---- soft-touch backup slips --------------------------------------------------------------
def softtouch_pdf(m, licensee="", printed=None) -> bytes:
    """Blank log for lanes where the pad didn't register (soft touch): write the event, heat and
    lane, then the two stopwatch times. Two tables side by side, as many rows as fit a letter page."""
    reg, bold = _fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    W, H = letter
    c.setTitle(f"{m['meet']['name']} - Soft touch backup times")
    margin, gap = 27.0, 14.0
    col_w = (W - 2 * margin - gap) / 2
    # Event, Heat, Lane, Watch 1, Watch 2 - times get the room
    fr = [0.15, 0.13, 0.13, 0.295, 0.295]
    widths = [col_w * f for f in fr]
    top = H - margin
    c.setFont(bold, 12.5)
    c.drawString(margin, top - 11, "Soft touch - backup times")
    c.setFont(reg, 9.5)
    meet = (m.get("meet") or {}).get("name", "")
    date = (m.get("meet") or {}).get("start", "")
    c.drawRightString(W - margin, top - 11, f"{meet}  {date}".strip())
    c.setFont(reg, 8.5)
    c.drawString(margin, top - 24, "Lane didn't register on the pad: write the event, heat and lane, then get both stopwatch times. "
                 "Official time = average of the two, thousandths dropped.")
    head_y = top - 32
    head_h, row_h = 16.0, 24.5
    bottom = margin + 10
    rows = int((head_y - head_h - bottom) // row_h)
    for k in range(2):
        x0 = margin + k * (col_w + gap)
        # header
        c.setFillGray(0.88)
        c.rect(x0, head_y - head_h, col_w, head_h, stroke=0, fill=1)
        c.setFillGray(0)
        c.setFont(bold, 9)
        x = x0
        for label, w in zip(("Event", "Heat", "Lane", "Watch 1", "Watch 2"), widths):
            c.drawCentredString(x + w / 2, head_y - head_h + 4.6, label)
            x += w
        # grid
        y_top, y_bot = head_y, head_y - head_h - rows * row_h
        c.setLineWidth(0.9)
        c.rect(x0, y_bot, col_w, y_top - y_bot)
        c.setLineWidth(0.5)
        x = x0
        for w in widths[:-1]:
            x += w
            c.line(x, y_top, x, y_bot)
        c.line(x0, head_y - head_h, x0 + col_w, head_y - head_h)
        for r in range(1, rows):
            y = head_y - head_h - r * row_h
            c.setStrokeGray(0.55)
            c.line(x0, y, x0 + col_w, y)
        c.setStrokeGray(0)
        # light guides in the time boxes: m : ss . hh
        c.setFont(reg, 11)
        c.setFillGray(0.72)
        xt = x0 + sum(widths[:3])
        for r in range(rows):
            yb = head_y - head_h - (r + 1) * row_h + 7.5
            for w in widths[3:]:
                c.drawString(xt - 0 + w * 0.30, yb, ":")
                c.drawString(xt + w * 0.66, yb, ".")
                xt += w
            xt = x0 + sum(widths[:3])
        c.setFillGray(0)
    c.showPage()
    c.save()
    return buf.getvalue()


def watches_needed(m, tol=0.30, keys=None):
    """Lanes that still need the timers' watch times: no pad touch, or pad and backup button disagree by more
    than the tolerance - and no watch time entered yet (entering one takes the lane off the list)."""
    import meetdb as _mdb
    evs = {v["ptr"]: v for v in m["events"]}
    order = {v["ptr"]: i for i, v in enumerate(m["events"])}
    out = []
    for e in m["entries"]:
        if e["scr"] or not e["heat"] or not e["lane"] or (e["stat"] or "").strip() in ("R", "F", "D"):
            continue
        if keys is not None:
            if e["key"] not in keys:
                continue
        elif (e.get("watch") or 0) > 0 or (e.get("watch2") or 0) > 0:
            continue
        pad = float(e.get("pad") or 0)
        btn = [float(x) for x in (e.get("backup"), e.get("back2"), e.get("back3")) if x and float(x) > 0]
        back = (sum(round(b * 100) for b in btn) // len(btn)) / 100 if btn else 0
        if not pad and not back and keys is None:
            continue
        if not pad:
            why = "No pad"
        elif back and abs(pad - back) > tol + 1e-6:
            d = back - pad
            why = f"Btn {'+' if d > 0 else '-'}{abs(d):.2f}"
        elif keys is not None:
            why = ""
        else:
            continue
        v = evs.get(e["event"], {})
        team = m["teams"].get(e["team"] if e["kind"] == "R" else m["athletes"].get(e["ath"], {}).get("team"), {}).get("abbr", "")
        out.append({"order": (e["lane"], order.get(e["event"], 999), e["heat"]), "event": v.get("no", ""), "label": v.get("label", ""),   # by lane: each timer finds their rows together
                    "heat": e["heat"], "lane": e["lane"], "who": _mdb.who(m, e), "team": team, "key": e["key"], "ptr": e["event"],
                    "pad": _mdb.fmt_time(pad) if pad else "none", "back": _mdb.fmt_time(back) if back else "none", "why": why})
    out.sort(key=lambda r: r["order"])
    return out


def watches_pdf(m, tol=0.30, licensee="", printed=None) -> bytes:
    """The watch times still to collect, one row per lane, with boxes for both watches."""
    rows_data = watches_needed(m, tol)
    reg, bold = _fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    W, H = letter
    c.setTitle(f"{m['meet']['name']} - Watches needed")
    margin = 27.0
    # lane first (the list is in lane order, one block per timer), then event and heat; the watch boxes get the room
    cols = [("Lane", 0.065), ("Event", 0.065), ("Heat", 0.06), ("Swimmer / relay", 0.21), ("Pad", 0.075), ("Button", 0.075),
            ("Why", 0.08), ("Watch 1", 0.185), ("Watch 2", 0.185)]
    tw = W - 2 * margin
    widths = [tw * f for _, f in cols]
    head_h, row_h = 16.0, 27.0
    meet = (m.get("meet") or {}).get("name", "")
    stamp = printed or __import__("time").strftime("%I:%M %p").lstrip("0")

    def header(page):
        top = H - margin
        c.setFont(bold, 12.5)
        c.drawString(margin, top - 11, "Watches needed")
        c.setFont(reg, 9.5)
        c.drawRightString(W - margin, top - 11, f"{meet}  ·  printed {stamp}" + (f"  ·  page {page}" if page > 1 else ""))
        c.setFont(reg, 8.5)
        c.drawString(margin, top - 24, f"Lanes with no pad touch, or pad and backup button more than {tol:.2f} apart. Get both timers' watches; "
                     "enter them in MeetDeck and the lane drops off this list.")
        y = top - 32
        c.setFillGray(0.88)
        c.rect(margin, y - head_h, tw, head_h, stroke=0, fill=1)
        c.setFillGray(0)
        c.setFont(bold, 8.5)
        x = margin
        for (label, _), w in zip(cols, widths):
            c.drawCentredString(x + w / 2, y - head_h + 4.6, label)
            x += w
        return y - head_h

    page, y, last_lane = 1, header(1), None
    if not rows_data:
        c.setFont(reg, 12)
        c.drawString(margin + 6, y - 24, "Nothing to collect right now - every lane has a pad time that agrees with its backup button, or a watch time.")
    for r in rows_data:
        if y - row_h < margin + 8:
            c.showPage()
            page += 1
            y = header(page)
        yb = y - row_h
        if last_lane is not None and r["lane"] != last_lane:      # a heavier line where the next lane's rows start
            c.setLineWidth(2)
            c.line(margin, y, margin + tw, y)
        last_lane = r["lane"]
        c.setLineWidth(0.5)
        c.setStrokeGray(0.55)
        c.line(margin, yb, margin + tw, yb)
        c.setStrokeGray(0)
        x = margin
        cells = [str(r["lane"]), str(r["event"]), str(r["heat"]), None, r["pad"], r["back"], r["why"], "", ""]
        for i, (val, w) in enumerate(zip(cells, widths)):
            if i < 3:                                   # L 4 / E 12 / H 2: a letter so the three numbers can't be mixed up
                c.setFont(reg, 8)
                c.setFillGray(0.45)
                c.drawString(x + 4, yb + 10, "LEH"[i])
                c.setFillGray(0)
                c.setFont(bold, 14 if i == 0 else 11.5)
                c.drawString(x + 13, yb + (9 if i == 0 else 9.5), val)
                x += w
                continue
            if i == 3:
                c.setFont(bold, 9)
                nm = r["who"] if len(r["who"]) <= 25 else r["who"][:24] + "…"
                c.drawString(x + 4, yb + 15, nm)
                c.setFont(reg, 7.5)
                c.drawString(x + 4, yb + 5, f"{r['team']}  ·  {r['label']}"[:40])
            elif i in (7, 8):
                c.setFont(reg, 13)
                c.setFillGray(0.72)
                c.drawString(x + w * 0.33, yb + 9, ":")
                c.drawString(x + w * 0.66, yb + 9, ".")
                c.setFillGray(0)
            else:
                c.setFont(reg, 8.5)
                if i == 6:
                    c.drawString(x + 3, yb + 10, val[:12])
                else:
                    c.drawCentredString(x + w / 2, yb + 10, val)
            x += w
        x = margin
        for w in widths[:-1]:
            x += w
            c.line(x, y, x, yb)
        c.rect(margin, yb, tw, 0)
        y = yb
    c.setLineWidth(0.9)
    c.showPage()
    c.save()
    return buf.getvalue()


def lanes_pdf(info: dict, printed=None) -> bytes:
    """One page explaining the meet's lane assignments under NFHS Rule 5-3 (for the coaches' meeting):
    this meet's lanes (open lanes shaded), why, the rule text when the Rules Book is on file, and Table 5-1
    for an 8-lane pool.
    info: meet, date, teams [(code, name)], plan [{lane, team}], lanes, seeded, why, draw, rules [{ref, text, book_page}]."""
    from reportlab.lib.utils import simpleSplit
    reg, bold = _fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    W, H = letter
    M = 46.0
    c.setTitle(f"{info.get('meet', '')} - Lane assignments")
    y = H - M

    def para(text, size=10.5, font=None, width=W - 2 * M, lead=1.32, x=M):
        nonlocal y
        c.setFont(font or reg, size)
        for ln in simpleSplit(text, font or reg, size, width):
            c.drawString(x, y, ln)
            y -= size * lead
    c.setFont(bold, 18)
    c.drawString(M, y - 4, "Lane assignments")
    c.setFont(reg, 10.5)
    c.drawRightString(W - M, y - 4, f"{info.get('meet', '')}  {info.get('date', '')}".strip())
    y -= 22
    para("NFHS Swimming & Diving Rules Book 2026-27, Rule 5-3 (book p. 45-46)", 10, reg)
    y -= 10

    # this meet: lane boxes
    n_lanes = int(info.get("lanes") or 8)
    teams = dict(info.get("teams") or [])
    plan = {p["lane"]: p["team"] for p in info.get("plan") or []}
    c.setFont(bold, 13)
    c.drawString(M, y, f"This meet: {len(teams)} team{'s' if len(teams) != 1 else ''}")
    y -= 12
    box_w, box_h = (W - 2 * M - (n_lanes - 1) * 6) / n_lanes, 62
    for i in range(n_lanes):
        ln = i + 1
        x = M + i * (box_w + 6)
        team = plan.get(ln)
        if info.get("seeded"):
            c.setFillGray(0.97)
        elif team:
            c.setFillGray(1)
        else:
            c.setFillGray(0.82)
        c.rect(x, y - box_h, box_w, box_h, stroke=1, fill=1)
        c.setFillGray(0)
        c.setFont(reg, 9)
        c.drawCentredString(x + box_w / 2, y - 14, f"Lane {ln}")
        label = "seeded" if info.get("seeded") else (team or "OPEN")
        fs = 15
        while fs > 8 and pdfmetrics.stringWidth(label, bold, fs) > box_w - 8:      # shrink to fit the box
            fs -= 0.5
        c.setFont(bold, fs)
        c.drawCentredString(x + box_w / 2, y - 36, label)
        if team and not info.get("seeded"):
            nm = teams.get(team, "")
            nfs = 7
            lines = simpleSplit(nm, reg, nfs, box_w - 6)
            if len(lines) > 2:                                                    # keep it to two lines
                lines = lines[:2]
                while lines[1] and pdfmetrics.stringWidth(lines[1] + "...", reg, nfs) > box_w - 6:
                    lines[1] = lines[1][:-1]
                lines[1] = lines[1].rstrip() + "..."
            c.setFont(reg, nfs)
            for k, ln in enumerate(lines):
                c.drawCentredString(x + box_w / 2, y - 48 - k * 8, ln)
    y -= box_h + 18
    if not info.get("seeded") and len(teams) > 1:
        for code, name in info.get("teams") or []:
            ls = [str(k) for k, v in sorted(plan.items()) if v == code]
            para(f"{name} ({code}): lanes {' & '.join(ls)}", 11, bold)
        opn = [str(k) for k in range(1, n_lanes + 1) if k not in plan]
        if opn:
            para(f"Lanes {' & '.join(opn)}: open", 11, bold)
        y -= 4
    para(info.get("why") or "", 11)
    if info.get("draw"):
        para(f"Lane sets drawn by lot: {info['draw']}", 10)
    y -= 12

    # the rule
    c.setFont(bold, 13)
    c.drawString(M, y, "The rule")
    y -= 16
    rules = info.get("rules") or []
    if rules:
        for r in rules:
            para(f"{r['ref']}{'  (book p. ' + str(r['book_page']) + ')' if r.get('book_page') else ''}", 10, bold)
            para(re.sub(r"\s+", " ", r["text"]).replace("ART. ", "Art. "), 10, reg, lead=1.3)
            y -= 4
    else:
        para("5-3-1: In dual meets the visiting team chooses the odd or even lanes. 5-3-2: In non-championship "
             "multi-team meets and double dual / triple dual meets, Table 5-1 is used; when the teams can't be divided "
             "equally into the lanes, meet management may seed or use the table and leave lanes open. More than five teams are seeded.", 10)
    y -= 10

    # Table 5-1 for this pool
    c.setFont(bold, 13)
    c.drawString(M, y, "Table 5-1 for an 8-lane pool")
    y -= 8
    rows = [("Teams", "Lane assignment"),
            ("2 (dual meet)", "Odd / even lanes - the visiting team chooses (Rule 5-3-1)"),
            ("3", "1-4 ; 2-5 ; 3-6 (by lot) with 2 lanes open, or seed"),
            ("4", "1-5 ; 2-6 ; 3-7 ; 4-8 (by lot)"),
            ("5 or more", "By seeding"),
            ("Championship meet", "By seeding (Rule 5-3-3, Table 5-2: fastest in lanes 4, 5, 3, 6, 2, 7, 1, 8)")]
    col1 = 120
    rh = 20
    for i, (a, b) in enumerate(rows):
        hl = i > 0 and ((a.startswith(str(len(teams))) and not info.get("champ")) or (a.startswith("Champ") and info.get("champ")))
        c.setFillGray(0.88 if i == 0 else (0.93 if hl else 1))
        c.rect(M, y - rh, W - 2 * M, rh, stroke=1, fill=1)
        c.setFillGray(0)
        c.line(M + col1, y, M + col1, y - rh)
        c.setFont(bold if i == 0 or hl else reg, 10.5)
        c.drawString(M + 6, y - 14, a)
        c.drawString(M + col1 + 6, y - 14, b)
        y -= rh
    y -= 14
    para("\"By lot\" means a random draw: each team draws which set of lanes it swims in.", 9.5)
    c.setFont(reg, 8)
    c.drawRightString(W - M, M - 18, f"Printed {printed or time.strftime('%m/%d/%Y %I:%M %p')} - MeetDeck")
    c.showPage()
    c.save()
    return buf.getvalue()
