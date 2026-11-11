"""This season's Utah high school top times from utahswimcoach.com.

utahswimcoach.com posts each classification's top 100 per event for the current season
(generated/<n>a<season>.htm, updated about weekly) and the class records
(generated/<n>ARecords.htm). This fetches them at most once a day, keeps a parsed copy
on disk (so a meet with no internet still has the last download), and answers:

  * where a swimmer stands in their class this season (rank + season best),
  * what a new time would rank,
  * the event's current state line (the 32nd fastest; 20th for relays - UHSAA takes
    that many per event to state), the #1 time and the class record.

Pure stdlib so the same file runs in MeetDeck and meet-board.
"""
from __future__ import annotations

import datetime
import html
import json
import re
import threading
import time
import unicodedata
import urllib.request
from pathlib import Path

BASE = "https://utahswimcoach.com/generated/"
CLASSES = ["6A", "5A", "4A", "3A", "2A"]
STATE_SPOTS = {False: 32, True: 20}      # individual, relay
MAX_AGE = 24 * 3600                      # refetch at most daily (the site updates ~weekly)
UA = "Mozilla/5.0 (MeetDeck; Tooele County swim meets)"

STROKES = {"FREE": "A", "BACK": "B", "BREAST": "C", "FLY": "D", "I.M.": "E", "IM": "E", "MEDLEY": "E"}


def season(today: datetime.date | None = None) -> str:
    """'2627' for the 2026-27 season (Aug - Jul)."""
    d = today or datetime.date.today()
    y = d.year if d.month >= 8 else d.year - 1
    return f"{y % 100:02d}{(y + 1) % 100:02d}"


def secs(t) -> float | None:
    t = str(t or "").strip().lstrip("xX*").rstrip("YyLlSs")
    m = re.match(r"^(?:(\d{1,2}):)?(\d{1,2}(?:\.\d{1,2})?)$", t)
    if not m:
        return None
    v = (int(m.group(1)) * 60 if m.group(1) else 0) + float(m.group(2))
    return round(v, 2) if v > 0 else None


def fmt(v) -> str:
    if not v:
        return ""
    v = round(float(v) + 1e-9, 2)
    m = int(v // 60)
    return f"{m}:{v - m * 60:05.2f}" if m else f"{v:.2f}"


def key(sex: str, dist: int, stroke: str, relay: bool) -> str:
    """'F|100|A|I' - sex F/M, distance, Hy-Tek stroke letter (A free .. E IM/medley), I/R."""
    return f"{sex}|{int(dist)}|{stroke}|{'R' if relay else 'I'}"


def event_key(title: str):
    """'4A  Women 200 Medley Relay' / 'Men 100 Breast' / 'Women 200 I.M.' -> key, or None."""
    t = " ".join(title.split())
    m = re.search(r"\b(Women|Men|Girls|Boys)\s+(\d{2,4})\s+(.+)$", t, re.I)
    if not m:
        return None
    sex = "F" if m.group(1).lower() in ("women", "girls") else "M"
    rest = m.group(3).upper()
    relay = "RELAY" in rest
    word = rest.replace("RELAY", "").split()
    stroke = STROKES.get(word[0] if word else "", None)
    if relay and "MEDLEY" in rest:
        stroke = "E"
    return key(sex, int(m.group(2)), stroke, relay) if stroke else None


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


_SCHOOL_DROP = re.compile(r"\b(high|school|hs|h s|academy|charter|the)\b")


def school_key(name: str) -> str:
    s = norm(name).replace("mt ", "mount ").replace("saint ", "st ")
    return " ".join(_SCHOOL_DROP.sub(" ", s).split())


# ---------------------------------------------------------------- parsing

def _cells(row):
    return [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", c)).split())
            for c in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", row)]


def _tables(page: str):
    page = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", page)
    pos = 0
    for m in re.finditer(r"(?is)<table\b.*?</table>", page):
        before = html.unescape(re.sub(r"<[^>]+>", "\n", page[pos:m.start()]))
        lines = [ln.strip() for ln in before.splitlines() if ln.strip()]
        yield (lines[-1] if lines else ""), [_cells(r) for r in re.findall(r"(?is)<tr\b.*?</tr>", m.group(0))]
        pos = m.end()


def parse_top(page: str) -> dict:
    """Top-100 page -> {key: [{rank, t, name, yr, school, date, meet}]} (relays: name = '')."""
    out = {}
    for title, rows in _tables(page):
        k = event_key(title)
        if not k or not rows:
            continue
        head = [c.lower() for c in rows[0]]
        col = {n: head.index(n) for n in ("order", "time", "name", "grade", "school", "date", "meet") if n in head}
        if "time" not in col or "school" not in col:
            continue
        lst = []
        for r in rows[1:]:
            g = lambda n: r[col[n]] if n in col and col[n] < len(r) else ""
            t = secs(g("time"))
            if not t:
                continue
            lst.append({"rank": int(g("order")) if g("order").isdigit() else len(lst) + 1, "t": t,
                        "name": g("name"), "yr": g("grade"), "school": g("school"),
                        "date": g("date"), "meet": g("meet")})
        out[k] = lst
    return out


def parse_records(page: str) -> dict:
    """Records page -> {key: {t, who, school, year}}."""
    out, sex = {}, None
    for _title, rows in _tables(page):
        for r in rows:
            if len(r) == 1 and r[0].lower() in ("women", "men", "girls", "boys"):
                sex = "Women" if r[0].lower() in ("women", "girls") else "Men"
                continue
            if len(r) < 4 or not sex or r[0].lower() == "event":
                continue
            k = event_key(f"{sex} {r[0]}")
            t = secs(r[3])
            if k and t:
                out[k] = {"t": t, "who": r[1], "school": r[2], "year": r[4] if len(r) > 4 else ""}
    return out


# ---------------------------------------------------------------- the store

class Store:
    """The parsed lists on disk at <folder>/utahswimcoach.json, refreshed in the background."""

    def __init__(self, folder):
        self.path = Path(folder) / "utahswimcoach.json"
        self._lock = threading.Lock()
        self._busy = False
        self.error = ""
        self.data = {}
        try:
            self.data = json.loads(self.path.read_text())
        except Exception:
            pass
        self._index()

    # -- fetching
    def stale(self) -> bool:
        return time.time() - (self.data.get("fetched") or 0) > MAX_AGE or self.data.get("season") != season()

    def refresh(self, force=False, wait=False):
        """Fetch in the background when the copy on disk is over a day old (or `force`)."""
        if not (force or self.stale()) or self._busy:
            return
        self._busy = True
        th = threading.Thread(target=self._fetch, daemon=True)
        th.start()
        if wait:
            th.join(120)

    def _get(self, name):
        req = urllib.request.Request(BASE + name, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.read().decode("latin-1")

    def _fetch(self):
        try:
            sn = season()
            top, rec, school_class = {}, {}, {}
            for c in CLASSES:
                n = c[0]
                try:
                    lists = parse_top(self._get(f"{n.lower()}a{sn}.htm"))
                except Exception:
                    lists = {}
                top[c] = lists
                for rows in lists.values():
                    for r in rows:
                        school_class.setdefault(school_key(r["school"]), c)
                try:
                    rec[c] = parse_records(self._get(f"{n}ARecords.htm"))
                except Exception:
                    rec[c] = {}
                time.sleep(1)                 # be gentle with a one-person site
            if not any(top.values()):
                raise RuntimeError("no top-time lists found (site down or layout changed)")
            data = {"season": sn, "fetched": time.time(),
                    "fetched_at": datetime.datetime.now().isoformat(timespec="minutes"),
                    "top": top, "records": rec, "school_class": school_class}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, separators=(",", ":")))
            tmp.replace(self.path)
            with self._lock:
                self.data = data
                self._index()
            self.error = ""
        except Exception as e:                # keep the last good copy
            self.error = str(e)
        finally:
            self._busy = False

    def status(self) -> dict:
        top = self.data.get("top") or {}
        return {"season": self.data.get("season", ""), "fetched_at": self.data.get("fetched_at", ""),
                "classes": {c: sum(len(v) for v in (top.get(c) or {}).values()) for c in CLASSES},
                "busy": self._busy, "error": self.error, "source": "utahswimcoach.com"}

    # -- lookups
    def _index(self):
        self._by_name = {}
        for c, lists in (self.data.get("top") or {}).items():
            for k, rows in lists.items():
                for r in rows:
                    nm = r["name"] or ""
                    sk = school_key(r["school"])
                    self._by_name[(c, k, sk, _person(nm))] = r
                    if not nm:                # relays: best per school
                        self._by_name.setdefault((c, k, sk, ""), r)

    def school_class(self, school: str) -> str:
        sk = school_key(school)
        sc = self.data.get("school_class") or {}
        if sk in sc:
            return sc[sk]
        for s, c in sc.items():               # 'Tooele' vs 'Tooele Buffaloes'
            if s and (sk.startswith(s + " ") or s.startswith(sk + " ")):
                return c
        return ""

    def school_on_site(self, school: str) -> str:
        sk = school_key(school)
        sc = self.data.get("school_class") or {}
        if sk in sc:
            return sk
        for s in sc:
            if s and (sk.startswith(s + " ") or s.startswith(sk + " ")):
                return s
        return sk

    def standing(self, k: str, school: str, last: str = "", first: str = "", cls: str = "") -> dict | None:
        """{cls, rank, sb} for a swimmer (or a school's relay when last == '') this season."""
        cls = cls or self.school_class(school)
        if not cls:
            return None
        sk = self.school_on_site(school)
        r = self._by_name.get((cls, k, sk, _person(f"{last}, {first}") if last else ""))
        if r is None and last:                # 'Smith, Kate' vs 'Smith, Katherine A'
            want_l, want_f = norm(last), norm(first)[:1]
            for row in ((self.data.get("top") or {}).get(cls) or {}).get(k, []):
                if school_key(row["school"]) != sk:
                    continue
                l, _, f = row["name"].partition(",")
                if norm(l) == want_l and norm(f)[:1] == want_f:
                    r = row
                    break
        if r is None:
            return {"cls": cls}
        return {"cls": cls, "rank": r["rank"], "sb": r["t"], "sb_date": r.get("date", ""), "sb_meet": r.get("meet", "")}

    def rank_of(self, k: str, cls: str, t: float, exclude: dict | None = None) -> int | None:
        """Where time t would place in the class list (1 = fastest), if inside the top 100."""
        rows = ((self.data.get("top") or {}).get(cls) or {}).get(k) or []
        if not t:
            return None
        faster = sum(1 for r in rows if r["t"] < t and r is not exclude
                     and not (exclude and r["name"] and r["name"] == exclude.get("name") and r["school"] == exclude.get("school")))
        return faster + 1 if faster < len(rows) or len(rows) < 100 else None

    def event_line(self, k: str, cls: str) -> dict | None:
        """{cls, n, top, top_by, line, spots, record, record_by, record_year} for one event and class."""
        rows = ((self.data.get("top") or {}).get(cls) or {}).get(k) or []
        rec = ((self.data.get("records") or {}).get(cls) or {}).get(k) or {}
        if not rows and not rec:
            return None
        spots = STATE_SPOTS[k.endswith("|R")]
        out = {"cls": cls, "n": len(rows), "spots": spots}
        if rows:
            out.update(top=rows[0]["t"], top_by=_who(rows[0]))
            if len(rows) >= spots:
                out["line"] = rows[spots - 1]["t"]
        if rec:
            out.update(record=rec["t"], record_by=rec["who"], record_school=rec["school"], record_year=rec["year"])
        return out

    def find_row(self, k, cls, school, last, first):
        sk = self.school_on_site(school)
        return self._by_name.get((cls, k, sk, _person(f"{last}, {first}") if last else ""))


def _person(name: str) -> str:
    last, _, first = str(name or "").partition(",")
    return f"{norm(last)}|{norm(first).split(' ')[0] if norm(first) else ''}"


def _who(r):
    if not r.get("name"):
        return r.get("school", "")
    last, _, first = r["name"].partition(",")
    return f"{first.strip()} {last.strip()} ({r['school']})".strip()
