"""Referee program v3: DQ box, code box(es), infraction box per lane and an order-of-finish row per heat (v2's goals),
laid out to use no more paper than the original referee program.

Variants:
  A - landscape, two heat columns, every event starts a new page (reads like v1, same page count)
  B - landscape, two heat columns, events flow into the next free column (fewest pages)
  C - portrait, one column, compact rows, events flow (closest to v1's look)
"""
import datetime as dt
import io

from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from heatsheet import _blocks, _fonts, _name, event_title

VARIANTS = {
    #     page size        cols  packed  row   relay row  label
    "A": (landscape(letter), 2, False, 15.5, 25.0, "landscape, one event per page"),
    "B": (landscape(letter), 2, True, 15.5, 25.0, "landscape, events share pages"),
    "C": (letter, 1, True, 14.0, 23.0, "portrait, compact"),
}
M = 18.0            # page margin
GUT = 18.0          # between columns
HEAD = 70.0         # first line under the page header
EV_H = 24.0         # event title + column labels
HEAT_LBL = 12.0
FIN_H = 18.0        # order of finish boxes
GAP = 10.0


class _Ref3:
    def __init__(self, m, licensee, printed, variant):
        self.m, self.licensee, self.printed = m, licensee, printed
        self.size, self.ncols, self.packed, self.row_i, self.row_r, self.label = VARIANTS[variant]
        self.W, self.H = self.size
        self.reg, self.bold = _fonts()
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=self.size)
        self.c.setTitle(f"{m['meet']['name']} - Referee Program")
        self.page, self.col, self.y = 0, 0, 0.0
        self.cw = (self.W - 2 * M - GUT * (self.ncols - 1)) / self.ncols
        self.bottom = self.H - 22.0
        wide = self.ncols == 1
        # x offsets inside a column
        self.x_lane = 10.0
        self.x_name = 22.0
        self.w_name = 150.0 if wide else 116.0
        self.x_sch = self.x_name + self.w_name + 6.0
        self.w_sch = 64.0 if wide else 46.0
        self.x_dq = self.x_sch + self.w_sch + 6.0
        self.x_code = self.x_dq + 16.0
        self.w_code = 28.0 if wide else 26.0

    # ---- drawing helpers (top measured from the top of the page) ----
    def fit(self, s, w, bold, size):
        f = self.bold if bold else self.reg
        s = s or ""
        while s and pdfmetrics.stringWidth(s, f, size) > w:
            if size > 6.5:
                size -= 0.25
            else:
                s = s[:-1]
        return s, size

    def text(self, x, top, s, bold=False, size=8.0, align="l", w=None):
        if w:
            s, size = self.fit(s, w, bold, size)
        self.c.setFont(self.bold if bold else self.reg, size)
        base = self.H - (top + size * 0.778)
        (self.c.drawRightString if align == "r" else self.c.drawCentredString if align == "c" else self.c.drawString)(x, base, s)

    def box(self, x, top, w, h, lw=0.7):
        self.c.setLineWidth(lw)
        self.c.rect(x, self.H - top - h, w, h, stroke=1, fill=0)

    # ---- pages and columns ----
    def new_page(self):
        if self.page:
            self.c.showPage()
        self.page += 1
        self.col, self.y = 0, HEAD
        mt = self.m["meet"]
        self.text(M, 22.0, self.licensee, size=8.5)
        stamp = f"MeetDeck - {self.printed.strftime('%I:%M %p').lstrip('0')}  {self.printed.month}/{self.printed.day}/{self.printed.year}  Page {self.page}"
        self.text(self.W - M, 22.0, stamp, size=8.5, align="r")
        try:
            d = dt.date.fromisoformat(mt["start"])
            when = f"{d.month}/{d.day}/{d.year}"
        except Exception:
            when = mt.get("start") or ""
        self.text(self.W / 2, 22.0, f"{mt['name']} - {when}" if when else mt["name"], bold=True, size=10.0, align="c")
        self.text(self.W / 2, 35.0, "Referee Program", bold=True, size=10.0, align="c")
        self.c.setLineWidth(0.8)
        self.c.line(M, self.H - 52.0, self.W - M, self.H - 52.0)
        if self.ncols == 2:
            self.c.setLineWidth(0.5)
            x = M + self.cw + GUT / 2
            self.c.line(x, self.H - 58.0, x, self.H - self.bottom)

    def next_col(self):
        if self.col + 1 < self.ncols:
            self.col += 1
            self.y = HEAD
        else:
            self.new_page()

    @property
    def x0(self):
        return M + self.col * (self.cw + GUT)

    def ncodes(self, v):
        return 2 if (v.get("stroke") or "").upper() == "E" else 1

    def heat_h(self, lanes, relay):
        return HEAT_LBL + len(lanes) * (self.row_r if relay else self.row_i) + 4.0 + FIN_H + GAP

    def ev_header(self, v, cont=False):
        x, y = self.x0, self.y
        no = f"{v['no']}{v.get('ltr') or ''}"
        title = f"Event {no}  " + event_title(v, self.m["meet"].get("course") or 3).split(" ", 1)[1] + ("  (continued)" if cont else "")
        self.text(x, y, title, bold=True, size=10.5, w=self.cw)
        relay = v["ind_rel"] == "R"
        ly = y + 14.0
        self.text(x + self.x_lane, ly, "Lane", bold=True, size=7.0, align="c")
        self.text(x + self.x_name, ly, "Team" if relay else "Name", bold=True, size=7.0)
        self.text(x + self.x_sch, ly, "Relay" if relay else "School", bold=True, size=7.0)
        self.text(x + self.x_dq + 5.5, ly, "DQ", bold=True, size=7.0, align="c")
        self.text(x + self.x_code, ly, "Codes" if self.ncodes(v) == 2 else "Code", bold=True, size=7.0)
        self.text(x + self.inf_x(v), ly, "Infraction", bold=True, size=7.0)
        self.c.setLineWidth(0.8)
        self.c.line(x, self.H - (ly + 9.0), x + self.cw, self.H - (ly + 9.0))
        self.y += EV_H

    def inf_x(self, v):
        return self.x_code + self.ncodes(v) * (self.w_code + 3.0) + 3.0

    def heat(self, v, hi, nheats, lanes):
        relay = v["ind_rel"] == "R"
        aths, teams = self.m["athletes"], self.m["teams"]
        x, rh, nc, xi = self.x0, (self.row_r if relay else self.row_i), self.ncodes(v), self.inf_x(v)
        self.text(x, self.y + 1.0, f"Heat {hi + 1} of {nheats}", bold=True, size=8.5)
        y = self.y + HEAT_LBL
        for j, e in enumerate(lanes):
            bh = rh - 3.0
            self.c.setStrokeGray(0.8)
            self.c.setLineWidth(0.35)
            self.c.line(x, self.H - (y + rh), x + self.cw, self.H - (y + rh))
            self.c.setStrokeGray(0)
            self.text(x + self.x_lane, y + 2.5, str(j + 1), bold=True, size=9.5, align="c")
            self.box(x + self.x_dq, y + 2.0, 11.0, 11.0)
            for k in range(nc):
                self.box(x + self.x_code + k * (self.w_code + 3.0), y + 1.5, self.w_code, bh)
            self.box(x + xi, y + 1.5, self.cw - xi, bh)
            if e:
                if relay:
                    tm = teams.get(e["team"], {})
                    self.text(x + self.x_name, y + 2.5, tm.get("short") or tm.get("abbr") or tm.get("name") or "", size=9.0, w=self.w_name)
                    self.text(x + self.x_sch, y + 2.5, e.get("ltr") or "", size=9.0)
                    legs = [aths.get(a) for a in (e.get("legs") or [])[:4]] + [None] * 4
                    lw = (self.w_name + self.w_sch) / 2
                    for k in range(4):
                        if legs[k]:
                            self.text(x + self.x_name + (k % 2) * lw, y + 12.0 + (k // 2) * 6.6, f"{k + 1}) {_name(legs[k])}", size=6.3, w=lw - 3)
                else:
                    a_ = aths.get(e["ath"], {})
                    tm = teams.get(a_.get("team"), {})
                    self.text(x + self.x_name, y + 2.5, _name(a_), size=9.0, w=self.w_name)
                    self.text(x + self.x_sch, y + 3.0, tm.get("short") or tm.get("abbr") or tm.get("name") or "", size=7.5, w=self.w_sch)
            y += rh
        # order of finish: the referee writes the lane in each place's box
        y += 4.0
        self.text(x, y + 1.0, "Finish", bold=True, size=7.5)
        self.text(x, y + 9.5, "(lane)", size=6.0)
        n = len(lanes)
        bx = x + 30.0
        bw = min(30.0, (self.cw - 30.0) / max(n, 1) - 3.0)
        for k in range(n):
            self.box(bx + k * (bw + 3.0), y, bw, FIN_H, lw=0.9)
            self.text(bx + k * (bw + 3.0) + 1.5, y + 1.2, ("1st", "2nd", "3rd")[k] if k < 3 else f"{k + 1}th", size=5.0)
        self.y = y + FIN_H + GAP

    def render(self):
        for v, heats in _blocks(self.m):
            relay = v["ind_rel"] == "R"
            first = self.heat_h(heats[0], relay)
            if not self.page:
                self.new_page()
            elif not self.packed:
                self.new_page()
            elif self.y + EV_H + first > self.bottom:
                self.next_col()
            self.ev_header(v)
            for hi, lanes in enumerate(heats):
                if self.y + self.heat_h(lanes, relay) - GAP > self.bottom:
                    self.next_col()
                    self.ev_header(v, cont=True)
                self.heat(v, hi, len(heats), lanes)
        if not self.page:
            self.new_page()
        self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


def referee3_pdf(m, licensee="", variant="A", printed=None) -> bytes:
    if printed is None:
        try:
            from zoneinfo import ZoneInfo
            printed = dt.datetime.now(ZoneInfo("America/Denver"))
        except Exception:
            printed = dt.datetime.now()
    return _Ref3(m, licensee, printed, variant).render()
