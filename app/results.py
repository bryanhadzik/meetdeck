"""Results exports from a Meet Manager database: Team Manager .hy3 (laid out like Meet Manager's
own "Export Results for Team Manager"), a printable HTML results page, and CSV."""
import csv
import datetime as dt
import html
import io
import re
import zipfile

import dqcodes
import meetdb
from hy3 import make_line

GENDER = {"F": "Girls", "M": "Boys", "X": "Mixed", "W": "Girls"}


def _line(tag: str, fields) -> bytes:
    """fields: (start0, text, width, align) with 0-based columns, like Meet Manager's files."""
    b = list(tag.ljust(128))
    for f in fields:
        start, text = f[0], "" if f[1] is None else str(f[1])
        width = f[2] if len(f) > 2 else len(text)
        right = len(f) > 3 and f[3] == "r"
        text = text[:width].rjust(width) if right else text[:width].ljust(width)
        b[start:start + width] = list(text)
    return make_line("".join(b)[:128])


def _skey(s: str) -> str:
    """Meet Manager's sort: case-insensitive, punctuation ignored (Olsen before O'Neil)."""
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower())


def proper(n: str) -> str:
    """Meet Manager prints an all-caps name in mixed case (DIDI -> Didi)."""
    return " ".join(w.capitalize() if len(w) > 1 and w.isupper() else w for w in (n or "").split(" "))


def _mdy(iso: str) -> str:
    return f"{iso[5:7]}{iso[8:10]}{iso[0:4]}" if iso and len(iso) >= 10 else ""


def _t(v) -> str:
    return f"{float(v or 0):.2f}"


def _sex_evt(g):
    return "W" if g in ("F", "W") else ("X" if g == "X" else "M")


def splits(db) -> dict:
    out = {}
    for r in meetdb.read(db, ["Split"]).get("Split", {}).get("rows", []):
        if (r.get("Rnd_ltr") or "F").strip() not in ("F", ""):
            continue
        key = f"R:{r['Relay_no']}" if r.get("Relay_no") else f"E:{r['Event_ptr']}:{r['Ath_no']}"
        out.setdefault(key, []).append((r["Split_no"], r["Split_Time"] or 0))
    return {k: sorted(v) for k, v in out.items()}


def _g1(sp: list, final: float) -> list:
    """Split lines: Meet Manager writes 25-yard units (2, 4, 6...) and ends with the final time."""
    if not sp:
        return []
    pts = [(n * 2, t) for n, t in sp]
    if not pts or not final or abs(pts[-1][1] - final) > 0.001:
        pts.append(((pts[-1][0] + 2) if pts else 2, final))
    lines = []
    for i in range(0, len(pts), 10):
        f = []
        for j, (n, t) in enumerate(pts[i:i + 10]):
            s = 2 + 11 * j
            f += [(s, "F", 1), (s + 1, n, 2, "r"), (s + 3, _t(t), 8, "r")]
        lines.append(_line("G1", f))
    return lines


COURSE = {1: "L", 2: "S", 3: "Y"}   # Meet_course
TOL = 0.30   # Meet Manager's pad-vs-button tolerance


def time_code(e) -> str:
    """Meet Manager's timing letter: A = final came from the buttons, K = touchpad kept although no button
    agrees within the tolerance, blank = touchpad confirmed by a button."""
    if e.get("adj") is not None:          # what Meet Manager stored for this result
        return e["adj"]
    if "adj" in e:                         # a Meet Manager result without a stored letter prints blank
        return ""
    fin, pad = float(e["time"] or 0), float(e["pad"] or 0)
    if not fin:
        return ""
    if not pad or abs(fin - pad) > 0.001:
        return "A"
    btn = [float(b or 0) for b in (e["backup"], e.get("back2"), e.get("back3")) if b]
    return "" if any(abs(pad - b) <= TOL + 1e-9 for b in btn) else "K"


def _result_fields(e, date_col: int, date: str):
    stat = (e["stat"] or "").strip()
    return [(2, "F", 1), (3, _t(e["time"]), 8, "r"), (11, e.get("fin_course") or "Y", 1), (12, stat, 1), (13, e["dq"], 2),
            (15, "0", 5, "r"), (20, e["heat"], 3, "r"), (23, e["lane"], 3, "r"), (26, e["heatplace"], 3, "r"),
            (29, e["place"], 4, "r"), (33, "0", 3, "r"), (36, _t(e["backup"]), 8, "r"), (44, _t(e.get("back2")), 8, "r"),
            (52, _t(e.get("back3")), 8, "r"), (63, e.get("dq2") if stat in ("Q", "F", "D") else "", 2), (65, _t(e["pad"]), 8, "r"),
            (74, "0.00", 8, "r"), (date_col, date, 8), (date_col + 8, time_code(e), 1),
            (date_col + 9, "" if e.get("dq_official") is None else e["dq_official"], 4, "r"), (122, "0", 1)]


def _swum(e) -> bool:
    """Meet Manager leaves out entries that never got a heat or a result (an unswum B relay)."""
    return bool(e["heat"] or e["time"] or (e["stat"] or "").strip())


def _dq_lines(e, v) -> list:
    if (e["stat"] or "").strip() not in ("Q", "F", "D") or not e["dq"]:
        return []
    relay = e["kind"] == "R"
    out = [_line("H1", [(2, e["dq"], 2), (4, dqcodes.describe(e["dq"], v["stroke"], relay), 124)])]
    if e.get("dq2"):
        out.append(_line("H2", [(2, e["dq2"], 2), (4, dqcodes.describe(e["dq2"], v["stroke"], True), 124)]))
    return out


def _hm(t) -> str:
    """Meet Manager's clock: hour padded with a space (" 5:04 PM")."""
    return f"{t.hour % 12 or 12:2d}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def _alt(meet) -> str:
    a = meet.get("altitude")
    return "" if a is None else str(int(a))


def hy3(m: dict, db, licensee: str = "", now=None) -> bytes:
    meet, teams, aths = m["meet"], m["teams"], m["athletes"]
    ev = {e["ptr"]: e for e in m["events"]}
    sp = splits(db)
    now = now or dt.datetime.now()
    out = [_line("A1", [(2, "07", 2), (4, "Results From MM to TM", 25), (29, "Hy-Tek, Ltd", 15), (44, "MM5 8.0Gh", 14),
                        (58, now.strftime("%m%d%Y"), 8), (67, _hm(now), 8), (75, licensee, 53)]),
           _line("B1", [(2, meet["name"], 45), (47, meet["location"], 45), (92, _mdy(meet["start"]), 8),
                        (100, _mdy(meet["end"] or meet["start"]), 8), (108, _mdy(meet.get("calc_date") or meet["start"]), 8),
                        (116, _alt(meet), 4, "r")]),
           _line("B2", [(92, f"{int(meet.get('idformat') or 1):02d}{int(meet.get('mtype') or 1):02d}{int(meet.get('course') or 3):02d}{COURSE.get(meet.get('course'), 'Y')}{meet.get('style') or 1}", 8),
                        (100, "0.00", 6, "r")])]
    start = dt.date.fromisoformat(meet["start"]) if meet["start"] else dt.date.today()
    day = lambda v: (start + dt.timedelta(days=(v.get("day") or 1) - 1)).strftime("%m%d%Y")
    sty = "A" if meet.get("style") == 3 else "S"      # 3+ team double-dual meets mark every entry A
    active = [e for e in m["entries"] if not e["scr"] and _swum(e)]
    for tno, tm in sorted(teams.items(), key=lambda x: _skey(x[1]["name"])):
        swam = {e["ath"] for e in active if e["kind"] == "I"} | {x for e in active if e["kind"] == "R" for x in e["legs"] if x}
        mine = [a for a in aths.values() if a["team"] == tno and a["no"] in swam]
        rels = [e for e in active if e["kind"] == "R" and e["team"] == tno]
        inds = [e for e in active if e["kind"] == "I" and aths.get(e["ath"], {}).get("team") == tno]
        if not mine and not rels:
            continue
        out.append(_line("C1", [(2, tm["abbr"], 5), (7, tm["name"], 30), (37, tm["short"], 16), (53, tm.get("lsc", ""), 2),
                                (55, tm.get("head", ""), 30), (85, tm.get("asst", ""), 30), (118, "0", 1), (121, "0", 1)]))
        if any(tm.get(k) for k in ("addr1", "addr2", "city", "state", "zip", "country")):
          out.append(_line("C2", [(2, tm.get("addr1", ""), 30), (32, tm.get("addr2", ""), 30), (62, tm.get("city", ""), 30),
                                (92, tm.get("state", ""), 2), (94, tm.get("zip", ""), 10), (104, tm.get("country", ""), 3)]))
        if any(tm.get(k) for k in ("day_tel", "eve_tel", "cell", "fax", "email")):
            out.append(_line("C3", [(32, tm.get("day_tel", ""), 20), (52, tm.get("eve_tel", ""), 20), (72, tm.get("fax", ""), 20),
                                    (92, tm.get("email", ""), 36)]))
        for a in sorted(mine, key=lambda a: (_skey(a["last"]), _skey(a["first"]))):
            out.append(_line("D1", [(2, a["sex"], 1), (3, a["no"], 5, "r"), (8, proper(a["last"]), 20), (28, proper(a["first"]), 20),
                                    (48, a["pref"], 20), (68, a["initial"], 1), (69, a.get("reg", ""), 14), (83, a.get("comp") or "", 5, "r"),
                                    (88, _mdy(a["birth"]), 8), (97, a["age"] or 0, 2, "r"),
                                    (99, a["yr"], 2), (101, a.get("stat", ""), 1), (104, "0", 1), (112, a.get("citizen", ""), 3), (124, "N", 1)]))
            for e in (x for x in inds if x["ath"] == a["no"]):      # Meet Manager keeps the entries' database order
                v = ev[e["event"]]
                out.append(_line("E1", [(2, a["sex"], 1), (3, a["no"], 5, "r"), (8, a["last"], 5), (13, a["sex"], 1),
                                        (14, v.get("sex") or _sex_evt(v["gender"]), 1), (15, v["dist"], 6, "r"), (21, v["stroke"], 1),
                                        (22, "0", 3, "r"), (25, "109", 3), (30, "0", 1), (31, sty, 1), (32, "0.00", 6, "r"),
                                        (38, v["no"], 3, "r"), (41, v.get("ltr", ""), 1), (42, _t(e["seed"]), 8, "r"), (50, e.get("seed_crs", "Y"), 1),
                                        (51, _t(e["seed"]), 8, "r"), (59, e.get("seed_crs", "Y"), 1), (60, _t(e["points"]), 8, "r"),
                                        (68, "0.00", 8, "r"), (79, "NN", 2), (83, "X" if e["exh"] else "", 1), (96, "N", 1)]))
                out.append(_line("E2", _result_fields(e, 87, day(v))))
                out += _g1(sp.get(e["key"], []), e["time"] if not (e["stat"] or "").strip() or e["stat"] == "Q" else 0)
                out += _dq_lines(e, v)
        for e in sorted(rels, key=lambda x: (ev[x["event"]]["no"], x["ltr"])):
            v = ev[e["event"]]
            g = "F" if v["gender"] in ("F", "W") else ("X" if v["gender"] == "X" else "M")
            out.append(_line("F1", [(2, tm["abbr"], 5), (7, e["ltr"], 1), (11, "0", 1), (12, e.get("rel_sex") or g, 1), (13, g, 1),
                                    (14, v.get("sex") or _sex_evt(v["gender"]), 1), (15, v["dist"], 6, "r"), (21, v["stroke"], 1),
                                    (22, "0", 3, "r"), (25, "109", 3), (30, "0", 1), (31, sty, 1), (32, "0.00", 6, "r"),
                                    (38, v["no"], 3, "r"), (41, v.get("ltr", ""), 1), (42, _t(e["seed"]), 8, "r"), (50, e.get("seed_crs", "Y"), 1),
                                    (51, _t(e["seed"]), 8, "r"), (59, e.get("seed_crs", "Y"), 1), (60, _t(e["points"]), 8, "r"),
                                    (68, "0.00", 8, "r"), (79, "NN", 2), (84, "4", 1), (96, "N", 1), (97, e["ltr"], 1)]))
            out.append(_line("F2", _result_fields(e, 102, day(v))))
            out += _g1(sp.get(e["key"], []), e["time"] if not (e["stat"] or "").strip() or e["stat"] == "Q" else 0)
            f3 = []
            named = [(p + 1, x) for p, x in enumerate(list(e["legs"]) + list(e.get("alts") or [])) if x]
            for slot, (pos, ano) in enumerate(named[:8]):      # legs 1-4, then alternates 5-8
                a = aths.get(ano, {})
                s = 2 + 13 * slot
                f3 += [(s, a.get("sex", ""), 1), (s + 1, ano, 5, "r"), (s + 6, a.get("last", ""), 5), (s + 11, "F", 1),
                       (s + 12, pos, 1)]
            out.append(_line("F3", f3 or [(2, "", 1)]))
            out += _dq_lines(e, v)
    return b"".join(out)


# ---- SDIF v3 (.cl2), laid out like Meet Manager's "Export Results for Team Manager" ----
SDIF_STROKE = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}


def cl2_checksum(body: bytes) -> bytes:
    """Hy-Tek's .cl2 check: sum of the first 156 bytes // 19 + 211, last two digits reversed."""
    c = sum(body[:156]) // 19 + 211
    return f"{c % 10}{(c // 10) % 10}".encode()


def _sline(tag: str, fields) -> bytes:
    b = list(tag.ljust(160))
    for f in fields:
        start, text = f[0], "" if f[1] is None else str(f[1])
        width = f[2] if len(f) > 2 else len(text)
        text = text[:width].rjust(width) if (len(f) > 3 and f[3] == "r") else text[:width].ljust(width)
        b[start:start + width] = list(text)
    b[157] = "N"
    body = "".join(b)[:158].encode("latin-1")
    return body + cl2_checksum(body) + b"\r\n"


def _st(v) -> str:
    """SDIF time: 1:04.46 / 56.01."""
    v = float(v or 0)
    if not v:
        return ""
    m, sec = divmod(round(v * 100), 6000)
    return f"{m}:{sec / 100:05.2f}" if m else f"{sec / 100:.2f}"


def _pts(p) -> str:
    p = float(p or 0)
    if not p:
        return ""
    return f"{int(p)}."          # Meet Manager writes the fraction separately (cols 151-152)


def _splits_cum(sp, final):
    """[(units_of_50, time)] including the final, like the .hy3 G1 lines."""
    if not sp:
        return []
    pts = [(n, t) for n, t in sp]
    if final and abs((pts[-1][1] or 0) - final) > 0.001:
        pts.append((pts[-1][0] + 1, final))
    return pts


def cl2(m: dict, db, export_time=None) -> bytes:
    meet, teams, aths = m["meet"], m["teams"], m["athletes"]
    ev = {e["ptr"]: e for e in m["events"]}
    sp = splits(db)
    now = export_time or dt.datetime.now()
    start = dt.date.fromisoformat(meet["start"]) if meet["start"] else dt.date.today()
    day = lambda v: (start + dt.timedelta(days=(v.get("day") or 1) - 1)).strftime("%m%d%Y")
    out = [_sline("A0", [(2, "9", 1), (3, "V3", 8), (11, "02", 2), (13, "Meet Results", 30), (43, "Hy-Tek, Ltd", 20),
                         (63, "WMM 8.0Gh", 10), (73, "Hy-Tek, Ltd", 20), (93, "866-456-5111", 12),
                         (105, now.strftime("%m%d%Y"), 8), (149, "MM40", 4)]),
           _sline("B1", [(2, "9", 1), (11, meet["name"], 30), (41, meet.get("addr1", ""), 22), (63, meet.get("addr2", ""), 22), (85, meet.get("city", ""), 20), (105, meet.get("state", ""), 2),
                         (107, meet.get("zip", ""), 10), (117, meet.get("country") or "USA", 3), (121, _mdy(meet["start"]), 8),
                         (129, _mdy(meet["end"] or meet["start"]), 8), (137, _alt(meet), 4, "r"),
                         (149, COURSE.get(meet.get("course"), "Y"), 1), (151, "000", 3)])]
    n = {"C": 0, "D": 0, "S": 0, "E": 0, "F": 0, "G": 0}
    active = [e for e in m["entries"] if not e["scr"] and _swum(e)]
    final_of = lambda e: e["time"] if not (e["stat"] or "").strip() or e["stat"] == "Q" else 0

    def name(a):
        return f"{proper(a.get('last', ''))}, {proper(a.get('first', ''))}" + (f" {a['initial']}" if a.get("initial") else "")

    def result(e):
        st = (e["stat"] or "").strip()
        return "DQ" if st == "Q" else ("NS" if st in ("R", "F") else ("DNF" if st == "D" else _st(e["time"])))

    def g0(nm, lsc, pts, total, reg=""):
        lines = []
        for i in range(0, max(len(pts), 1), 10):
            chunk = pts[i:i + 10]
            f = [(2, "9", 1), (3, lsc, 2), (15, nm, 28), (43, reg[:12], 12), (55, i // 10 + 1, 1), (56, total, 2, "r"), (58, "50", 4, "r"), (62, "C", 1),
                 (143, "F", 1)]
            for j, t in enumerate(chunk):
                f.append((63 + 8 * j, _st(t), 8, "r"))
            lines.append(_sline("G0", f))
        return lines

    swam = {e["ath"] for e in active if e["kind"] == "I"} | {x for e in active if e["kind"] == "R" for x in e["legs"] if x}

    def tcode(a):            # a relay swimmer's own team code (mixed-team relays)
        t = teams.get(a.get("team"), {})
        return (t.get("lsc") or "").ljust(2) + t.get("abbr", "")[:4]

    for tno, tm in sorted(teams.items(), key=lambda x: _skey(x[1]["name"])):
        mine = [a for a in aths.values() if a["team"] == tno and a["no"] in swam]
        rels = [e for e in active if e["kind"] == "R" and e["team"] == tno]
        inds = [e for e in active if e["kind"] == "I" and aths.get(e["ath"], {}).get("team") == tno]
        if not mine and not rels:
            continue
        lsc = tm.get("lsc") or ""
        code = lsc.ljust(2) + tm["abbr"][:4]
        out.append(_sline("C1", [(2, "9", 1), (3, lsc, 2), (11, code, 6), (17, tm["name"], 30), (47, proper(tm["short"]), 16),
                                 (63, tm.get("addr1", ""), 22), (85, tm.get("addr2", ""), 22),
                                 (107, tm.get("city", ""), 20), (127, tm.get("state", ""), 2), (129, tm.get("zip", ""), 10),
                                 (139, tm.get("country", ""), 3), (149, tm["abbr"][4:5], 1)]))
        n["C"] += 1
        for a in sorted(mine, key=lambda a: (_skey(a["last"]), _skey(a["first"]))):
            first = True
            for e in (x for x in inds if x["ath"] == a["no"]):      # database order, like Meet Manager
                v = ev[e["event"]]
                st = (e["stat"] or "").strip()
                bad = st in ("Q", "F", "D", "R")
                g = "F" if v["gender"] in ("F", "W") else ("X" if v["gender"] == "X" else "M")
                out.append(_sline("D0", [(2, "9", 1), (3, lsc, 2), (7, a.get("yr", "") if a.get("age") else "", 2), (11, name(a), 28),
                                         (39, a.get("reg", "")[:12], 12), (51, "A", 1), (52, a.get("citizen", ""), 3), (55, _mdy(a.get("birth", "")), 8),
                                         (63, a.get("age") or a.get("yr") or 0, 2, "r"),
                                         (65, a["sex"], 1), (66, g, 1), (67, v["dist"], 4, "r"), (71, SDIF_STROKE.get(v["stroke"], 1), 1),
                                         (72, v["no"], 3, "r"), (76, "UNOV", 4), (80, day(v), 8),
                                         (88, _st(e["seed"]), 8, "r"), (96, "Y" if e["seed"] else "", 1),
                                         (115, result(e), 8, "r"), (123, "Y", 1), (128, e["heat"] or "", 2, "r"), (130, e["lane"] or "", 2, "r"),
                                         (135, 0 if bad else (e["place"] or 0), 3, "r"), (138, "" if bad else _pts(e["points"]), 4, "r"),
                                         (145, 0 if bad else (e["heatplace"] or 0), 3), (148, f"{SDIF_STROKE.get(v['stroke'], 1):02d}", 2),
                                         (150, f"{round((e['points'] - int(e['points'])) * 100):02d}" if (e["points"] and not bad) else "", 2), (156, "N", 1)]))
                n["D"] += 1
                if first:
                    out.append(_sline("D3", [(2, a.get("reg", ""), 14), (16, a.get("pref", ""), 15)]))
                    n["S"] += 1
                    first = False
                pts = _splits_cum(sp.get(e["key"], []), final_of(e))
                if pts:
                    gl = g0(name(a), lsc, [t for _, t in pts], v["dist"] // 50, a.get("reg", ""))
                    out += gl
                    n["G"] += len(gl)
        for e in sorted(rels, key=lambda x: (ev[x["event"]]["no"], x["ltr"])):
            v = ev[e["event"]]
            st = (e["stat"] or "").strip()
            bad = st in ("Q", "F", "D", "R")
            g = "F" if v["gender"] in ("F", "W") else ("X" if v["gender"] == "X" else "M")
            rs = 7 if v["stroke"] == "E" else 6
            out.append(_sline("E0", [(2, "9", 1), (3, lsc, 2), (11, e["ltr"], 1), (12, code, 6), (20, g, 1), (21, v["dist"], 4, "r"),
                                     (25, rs, 1), (26, v["no"], 3, "r"), (30, "UNOV", 4), (34, "0", 3, "r"), (37, day(v), 8),
                                     (45, _st(e["seed"]), 8, "r"), (53, "Y" if e["seed"] else "", 1),
                                     (72, result(e), 8, "r"), (80, "Y", 1), (85, e["heat"] or "", 2, "r"), (87, e["lane"] or "", 2, "r"),
                                     (92, 0 if bad else (e["place"] or 0), 3, "r"), (95, "" if bad else _pts(e["points"]), 4, "r"),
                                     (143, 0 if bad else (e["heatplace"] or 0), 1), (144, "N", 1),
                                     (148, f"{SDIF_STROKE.get(v['stroke'], 1):02d}", 2), (150, f"{round((e['points'] - int(e['points'])) * 100):02d}" if (e["points"] and not bad) else "", 2),
                                     (152, "X", 1)]))
            n["E"] += 1
            legs = [x for x in e["legs"] if x][:4]
            total = v["dist"] // 50
            per = max(1, total // max(1, len(legs)))
            bynum = dict(sp.get(e["key"], []))
            if final_of(e):
                # Meet Manager shows the final in a blank last split if it falls in the last leg
                # (a blank split in an earlier leg stays blank), and as the race's last split when it's missing
                if bynum and max(bynum) > total - per and not bynum[max(bynum)] and not (e["stat"] or "").strip():
                    bynum[max(bynum)] = final_of(e)
                bynum.setdefault(total, final_of(e))
            for k, ano in enumerate(legs):
                a = aths.get(ano, {})
                out.append(_sline("F0", [(2, "9", 1), (3, lsc, 2), (7, a.get("yr", "") if a.get("age") else "", 2), (15, tcode(a), 6), (21, e["ltr"], 1), (22, name(a), 28), (50, a.get("reg", "")[:12], 12), (62, a.get("citizen", ""), 3), (92, a.get("reg", ""), 14),
                                         (65, _mdy(a.get("birth", "")), 8), (73, str(a.get("age") or a.get("yr") or 0), 2), (106, a.get("pref", ""), 15), (75, a.get("sex", ""), 1), (78, k + 1, 1)]))
                n["F"] += 1
                # every leg gets a split line (blank when the splits are missing), like Meet Manager
                mine_pts = [bynum.get(j, 0) for j in range(k * per + 1, (k + 1) * per + 1)]
                while mine_pts and not mine_pts[-1]:
                    mine_pts.pop()
                gl = g0(name(a), lsc, mine_pts, total, a.get("reg", ""))
                out += gl
                n["G"] += len(gl)
    out.append(_sline("Z0", [(2, "9", 1), (3, "Meet Res", 8), (11, "02", 2), (13, f"Successful Build on {now.month}/{now.day}/{now.year}", 30),
                             (43, 1, 3, "r"), (46, 1, 3, "r"), (49, n["C"], 4, "r"), (53, n["C"], 4, "r"), (57, n["D"], 6, "r"),
                             (63, len(swam), 6, "r"), (69, n["E"], 5, "r"), (74, n["F"], 6, "r"), (80, n["G"], 6, "r")]))
    return b"".join(out)


def results_stem(m, seq: int = 1) -> str:
    """Meet Manager's name: 'Meet Results-<meet>-30Oct2026-002' (& and other unsafe characters become '-')."""
    import re
    d = dt.date.fromisoformat(m["meet"]["start"]) if m["meet"]["start"] else dt.date.today()
    name = re.sub(r'[&/\\:*?"<>|]', "-", m["meet"]["name"])
    return f"Meet Results-{name}-{d.strftime('%d%b%Y')}-{seq:03d}"


def hy3_zip(m, db, licensee="", seq: int = 1) -> tuple[bytes, str]:
    stem = results_stem(m, seq)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(stem + ".cl2", cl2(m, db))
        z.writestr(stem + ".hy3", hy3(m, db, licensee))
    return buf.getvalue(), stem + ".zip"


# ---- people-readable ---------------------------------------------------------
def _rows(m):
    """Per event, in meet order: finishers by place, then DQ / no-shows."""
    aths, teams = m["athletes"], m["teams"]
    for v in m["events"]:
        ents = [e for e in m["entries"] if e["event"] == v["ptr"] and not e["scr"]]
        if not ents:
            continue
        done = sorted((e for e in ents if e["place"]), key=lambda e: (e["place"], e["time"]))
        other = sorted((e for e in ents if not e["place"]), key=lambda e: ({"Q": 0, "F": 0, "R": 2}.get((e["stat"] or "").strip(), 1), e["time"] or 999))
        rows = []
        for e in done + other:
            st = (e["stat"] or "").strip()
            mark = {"Q": "DQ", "F": "DQ", "R": "NS"}.get(st, "")
            if e["kind"] == "I":
                a = aths.get(e["ath"], {})
                name, yr, team = f"{a.get('last', '')}, {a.get('first', '')}", a.get("yr", ""), teams.get(a.get("team"), {}).get("abbr", "")
                legs = ""
                who = {"last": a.get("last", ""), "first": a.get("first", ""), "pref": a.get("pref", ""), "school": teams.get(a.get("team"), {}).get("name", "")}
            else:
                tm = teams.get(e["team"], {})
                name, yr, team = f"{tm.get('name', '')} \"{e['ltr']}\"", "", tm.get("abbr", "")
                legs = ", ".join(f"{aths.get(x, {}).get('first', '')} {aths.get(x, {}).get('last', '')}" for x in e["legs"] if x)
                who = {"last": "", "first": "", "pref": "", "school": tm.get("name", ""), "ltr": e.get("ltr", "")}
            result = mark if st == "R" else meetdb.fmt_time(e["time"]) if e["time"] else ("NT" if not mark else mark)
            if st in ("Q", "F", "D") and e["time"]:
                result = f"DQ {meetdb.fmt_time(e['time'])}"
            dqtxt = " / ".join(f"{c} {dqcodes.describe(c, v['stroke'], e['kind'] == 'R')}" for c in (e["dq"], e.get("dq2")) if c) if st in ("Q", "F", "D") else ""
            rows.append({"place": e["place"] or "", "name": name, "dqtxt": dqtxt, "yr": yr, "team": team, "seed": meetdb.fmt_time(e["seed"]) or "NT",
                         "result": result if (e["time"] or mark) else "", "points": (f"{e['points']:g}" if e["points"] else ""),
                         "dq": e["dq"], "legs": legs, "exh": e["exh"], "seed_v": e["seed"] or 0, "time_v": e["time"] or 0, "who": who})
        yield v, rows


def results_csv(m) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Event", "Place", "Name", "Year", "Team", "Seed", "Result", "Points", "DQ code", "Relay swimmers"])
    for v, rows in _rows(m):
        for r in rows:
            w.writerow([f"#{v['no']} {v['label']}", r["place"], r["name"], r["yr"], r["team"], r["seed"], r["result"],
                        r["points"], r["dqtxt"] or r["dq"], r["legs"]])
    return buf.getvalue().encode("utf-8-sig")


def results_html(m, scoring=None) -> str:
    meet = m["meet"]
    esc = html.escape
    parts = [f"""<!doctype html><html><head><meta charset="utf-8"><title>Results - {esc(meet['name'])}</title>
<style>body{{font:13px/1.35 system-ui,sans-serif;margin:24px;color:#111}}h1{{font-size:20px;margin:0}}.sub{{color:#555;margin-bottom:14px}}
h2{{font-size:14px;margin:18px 0 4px;border-bottom:1px solid #999}}table{{border-collapse:collapse;width:100%;max-width:820px}}
td,th{{padding:2px 6px;text-align:left}}th{{font-size:11px;color:#555;text-transform:uppercase}}td.n{{text-align:right;font-variant-numeric:tabular-nums}}
.legs{{color:#555;font-size:12px}}.dq{{color:#a00}}@media print{{body{{margin:0}}h2{{break-after:avoid}}tr{{break-inside:avoid}}}}</style></head><body>
<h1>{esc(meet['name'])}</h1><div class="sub">{esc(meet['location'])} &middot; {esc(meet['start'])} &middot; Results</div>"""]
    sc = scoring or {}
    if sc.get("pairs"):
        parts.append("<h2>Team scores</h2><table style='max-width:520px'><tr><th>Dual</th><th class='n'>Girls</th><th class='n'>Boys</th><th class='n'>Combined</th></tr>")
        for p in sc["pairs"]:
            a, b = m["teams"].get(p["a"], {}), m["teams"].get(p["b"], {})
            parts.append(f"<tr><td>{esc(a.get('abbr', ''))} vs {esc(b.get('abbr', ''))}</td><td class='n'>{p['a_pts']['F']:g} - {p['b_pts']['F']:g}</td>"
                         f"<td class='n'>{p['a_pts']['M']:g} - {p['b_pts']['M']:g}</td><td class='n'>{p['a_pts']['F'] + p['a_pts']['M']:g} - {p['b_pts']['F'] + p['b_pts']['M']:g}</td></tr>")
        parts.append("</table>")
    elif sc.get("teams"):
        parts.append("<h2>Team scores</h2><table style='max-width:520px'><tr><th>Team</th><th class='n'>Girls</th><th class='n'>Boys</th><th class='n'>Combined</th></tr>")
        for t, v in sorted(sc["teams"].items(), key=lambda x: -x[1]["total"]):
            tm = m["teams"].get(int(t), {})
            parts.append(f"<tr><td>{esc(tm.get('name', ''))}</td><td class='n'>{v['F']:g}</td><td class='n'>{v['M']:g}</td><td class='n'><b>{v['total']:g}</b></td></tr>")
        parts.append(f"</table><div class='sub'>{esc(sc.get('method_name', ''))}</div>")
    for v, rows in _rows(m):
        parts.append(f"<h2>Event {v['no']} &nbsp; {esc(v['label'])}</h2><table><tr><th></th><th>Name</th><th>Yr</th><th>Team</th>"
                     f"<th class='n'>Seed</th><th class='n'>Finals</th><th class='n'>Points</th></tr>")
        for r in rows:
            cls = " class='dq'" if r["result"].startswith(("DQ", "NS")) else ""
            legs = f"<div class='legs'>{esc(r['legs'])}</div>" if r["legs"] else ""
            if r["dqtxt"]:
                legs += f"<div class='legs dq'>{esc(r['dqtxt'])}</div>"
            parts.append(f"<tr><td class='n'>{r['place'] or ('--' if r['result'] else '')}</td><td>{esc(r['name'])}{' (exh)' if r['exh'] else ''}"
                         f"{legs}</td>"
                         f"<td>{esc(r['yr'])}</td><td>{esc(r['team'])}</td><td class='n'>{esc(r['seed'])}</td>"
                         f"<td class='n'{cls}>{esc(r['result'])}</td><td class='n'>{esc(r['points'])}</td></tr>")
        parts.append("</table>")
    parts.append("</body></html>")
    return "".join(parts)
