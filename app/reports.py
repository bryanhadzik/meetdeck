"""Extra printable reports in Meet Manager's style: psych sheet, DQ summary, team scores.
Two columns (one for team scores), the same page header as the heat sheet and results."""
import datetime as dt
import io

from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

import dqcodes
import meetdb
from heatsheet import _fonts, event_title, event_records

PAGE_W, PAGE_H = letter
SZ, TSZ = 7.7, 8.5
ROW = 11.0
TOP, LAST = 76.8, 760.0


def _now():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Denver"))
    except Exception:
        return dt.datetime.now()


class Doc:
    """Flowing report: blocks (lists of rows) kept together, filling column by column."""

    def __init__(self, m, title, licensee="", cols=2, printed=None):
        self.m, self.title, self.licensee = m, title, licensee
        self.printed = printed or _now()
        self.reg, self.bold = _fonts()
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=letter)
        self.c.setTitle(f"{m['meet']['name']} - {title}")
        self.ncols = cols
        self.colw = (PAGE_W - 36 - 12 * (cols - 1)) / cols
        self.page, self.col, self.y = 0, 0, TOP
        self.new_page()

    def x0(self):
        return 18 + self.col * (self.colw + 12)

    def fit(self, s, w, bold, size):
        f = self.bold if bold else self.reg
        s = str(s or "")
        if not w or pdfmetrics.stringWidth(s, f, size) <= w:
            return s, size
        if pdfmetrics.stringWidth(s, f, size) * 0.85 <= w:
            return s, size * w / pdfmetrics.stringWidth(s, f, size)
        size *= 0.85
        while s and pdfmetrics.stringWidth(s, f, size) > w:
            s = s[:-1]
        return s, size

    def text(self, x, top, s, bold=False, size=SZ, align="l", w=None):
        s, size = self.fit(s, w, bold, size)
        self.c.setFont(self.bold if bold else self.reg, size)
        base = PAGE_H - (top + size * 0.778)
        (self.c.drawRightString if align == "r" else self.c.drawCentredString if align == "c" else self.c.drawString)(x, base, s)

    def new_page(self):
        if self.page:
            self.c.showPage()
        self.page += 1
        self.col, self.y = 0, TOP
        mt, p = self.m["meet"], self.printed
        self.text(18.0, 35.2, self.licensee, size=TSZ)
        self.text(PAGE_W - 18, 35.2, f"MeetDeck - {p.strftime('%I:%M %p').lstrip('0')}  {p.month}/{p.day}/{p.year}  Page {self.page}",
                  size=TSZ, align="r")
        try:
            d = dt.date.fromisoformat(mt["start"])
            when = f"{d.month}/{d.day}/{d.year}"
        except Exception:
            when = mt.get("start") or ""
        self.text(PAGE_W / 2, 47.2, f"{mt['name']} - {when}" if when else mt["name"], bold=True, size=TSZ, align="c")
        self.text(PAGE_W / 2, 59.5, self.title, bold=True, size=TSZ, align="c")
        self.c.setLineWidth(0.75)
        self.c.line(18.0, PAGE_H - 67.5, PAGE_W - 18, PAGE_H - 67.5)
        if self.ncols == 2:
            x = 18 + self.colw + 6
            self.c.line(x, PAGE_H - 67.5, x, PAGE_H - LAST)

    def need(self, h):
        if self.y + h <= LAST:
            return
        if self.col + 1 < self.ncols:
            self.col, self.y = self.col + 1, TOP
        else:
            self.new_page()

    def heading(self, s, rows_after=1):
        self.need(14 + ROW * rows_after)
        self.text(self.x0(), self.y, s, bold=True, size=TSZ, w=self.colw)
        self.y += 12
        self.c.setLineWidth(0.5)
        self.c.line(self.x0(), PAGE_H - self.y, self.x0() + self.colw, PAGE_H - self.y)
        self.y += 2.5

    def row(self, cells, bold=False):
        """cells: [(x as a fraction of the column width, text, align, width fraction)]"""
        self.need(ROW)
        for fx, s, al, fw in cells:
            self.text(self.x0() + fx * self.colw, self.y, s, bold=bold, align=al, w=fw * self.colw if fw else None)
        self.y += ROW

    def gap(self, h=6):
        self.y += h

    def done(self):
        self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


def _ordered(m):
    return sorted(m["events"], key=lambda v: (v.get("order") or (99, v["no"]), v["no"]))


def _who(m, e):
    if e["kind"] == "R":
        t = m["teams"].get(e["team"], {})
        return f"{t.get('name') or t.get('abbr', '')} {e.get('ltr') or ''}".strip(), t.get("abbr", ""), ""
    a = m["athletes"].get(e["ath"], {})
    t = m["teams"].get(a.get("team"), {})
    return f"{a.get('last', '')}, {a.get('first', '')}", t.get("abbr", ""), a.get("yr", "")


def psych_pdf(m, licensee="") -> bytes:
    """Psych sheet: every event's entries ranked by seed time (no time last), records under the title."""
    doc = Doc(m, "Psych Sheet", licensee)
    course = m["meet"].get("course") or 3
    for v in _ordered(m):
        ents = [e for e in m["entries"] if e["event"] == v["ptr"] and not e["scr"]]
        if not ents:
            continue
        ents.sort(key=lambda e: (not e["seed"], e["seed"] or 0, _who(m, e)[0]))
        recs = event_records(m, v)
        doc.gap(4)
        doc.heading(event_title(v, course).replace("#", "Event ", 1), rows_after=1 + len(recs))
        for r in recs:
            doc.row([(0.03, r, "l", 0.95)])
        rank = 0
        for i, e in enumerate(ents, 1):
            nm, team, yr = _who(m, e)
            rank = i if e["seed"] else rank
            seed = ("X" if e.get("exh") else "") + (meetdb.fmt_time(e["seed"]) or "NT")
            doc.row([(0.06, str(i) if e["seed"] else "", "r", None), (0.09, nm, "l", 0.52 if v["ind_rel"] != "R" else 0.62),
                     (0.66, yr, "l", 0.06), (0.73, team, "l", 0.14), (1.0, seed, "r", None)])
    return doc.done()


def dq_summary_pdf(m, licensee="") -> bytes:
    """Every disqualification by event: who, heat/lane, code and the infraction."""
    doc = Doc(m, "DQ Summary", licensee)
    course = m["meet"].get("course") or 3
    total = 0
    for v in _ordered(m):
        dqs = [e for e in m["entries"] if e["event"] == v["ptr"] and not e["scr"] and (e["stat"] or "").strip() in ("Q", "F", "D")]
        if not dqs:
            continue
        dqs.sort(key=lambda e: (e["heat"] or 0, e["lane"] or 0))
        doc.gap(4)
        doc.heading(event_title(v, course).replace("#", "Event ", 1), rows_after=2)
        relay = v["ind_rel"] == "R"
        for e in dqs:
            nm, team, yr = _who(m, e)
            dfs = (e.get("dq") or "").upper() in ("7B", "7P") and not e["time"]
            doc.row([(0.0, f"H{e['heat'] or '-'} L{e['lane'] or '-'}", "l", 0.12), (0.13, nm, "l", 0.5), (0.65, team, "l", 0.14),
                     (1.0, "DFS" if dfs else "DQ", "r", None)])
            codes = [c for c in (e.get("dq"), e.get("dq2")) if c]
            txt = " / ".join(f"{c} {dqcodes.describe(c, v['stroke'], relay)}".strip() for c in codes) or "(no code entered)"
            doc.row([(0.13, txt, "l", 0.86)])
            total += 1
    if not total:
        doc.row([(0.0, "No disqualifications.", "l", 1.0)])
    return doc.done()


def team_scores_pdf(m, summary, teams_order=None, licensee="") -> bytes:
    """Team scores: women, men and combined, plus each dual pairing for dual / double-dual scoring."""
    doc = Doc(m, "Team Scores", licensee, cols=1)
    teams = m["teams"]
    tot = meetdb.score_totals(m, summary) if summary and summary.get("method") else {"teams": {}, "pairs": []}
    rows = sorted(tot["teams"].items(), key=lambda kv: -kv[1]["total"])
    f = lambda x: f"{x:g}"
    name = lambda no: (teams.get(int(no)) or teams.get(no) or {}).get("name") or str(no)
    done = len(summary.get("events") or []) if summary else 0
    nev = len(m["events"])
    how = summary.get("method_name", "").split(" (")[0] if summary else "not scored yet"
    doc.heading(f"Scores - Team ({how}{f', {done} of {nev} events scored' if summary else ''})", 2)
    doc.row([(0.04, "Place", "r", None), (0.07, "Team", "l", None), (0.62, "Women", "r", None), (0.77, "Men", "r", None),
             (1.0, "Total", "r", None)], bold=True)
    for i, (no, t) in enumerate(rows, 1):
        doc.row([(0.04, str(i), "r", None), (0.07, name(no), "l", 0.5), (0.62, f(t["F"] + t.get("X", 0)), "r", None),
                 (0.77, f(t["M"]), "r", None), (1.0, f(t["total"]), "r", None)])
    if not rows:
        doc.row([(0.07, "No events scored yet.", "l", 0.9)])
    if tot.get("pairs"):
        doc.gap(10)
        doc.heading("Dual meet results", 2)
        doc.row([(0.07, "Teams", "l", None), (0.62, "Women", "r", None), (0.77, "Men", "r", None), (1.0, "Total", "r", None)], bold=True)
        for p in tot["pairs"]:
            a, b = p["a_pts"], p["b_pts"]
            ta, tb = a["F"] + a["M"], b["F"] + b["M"]
            win = name(p["a"]) if ta > tb else name(p["b"]) if tb > ta else "Tie"
            doc.row([(0.07, f"{name(p['a'])} vs {name(p['b'])}", "l", 0.5), (0.62, f"{f(a['F'])} - {f(b['F'])}", "r", None),
                     (0.77, f"{f(a['M'])} - {f(b['M'])}", "r", None), (1.0, f"{f(ta)} - {f(tb)}", "r", None)])
            doc.row([(0.1, f"Winner: {win}", "l", 0.6)])
    return doc.done()
