"""Turn the entry formats coaches send into Hy-Tek .hy3 entry files.

Supported:
  * Team Manager / SwimTopia / TeamUnify Hy-Tek export (.hy3 or .zip)  - used as-is
  * SDIF / Team Manager .cl2 / .sd3 entry files (or a .zip of them)    - converted
  * Word (.docx) or plain-text entry lists like
        Blue Team Girls Relays
        200 Medley-   A: Olivia McCoy <tab><tab> B: Kate Starr
                         Katelyn Bolin  <tab><tab>   Sienna Roundy ...
        Blue Team Girls
        Olivia McCoy- 200 free, 100 fly
                                                                        - converted

Everything converted is written out as a normal .hy3 (with valid Hy-Tek line checksums)
so the rule checks, per-team import files and Meet Manager backup all work the same.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

from hy3 import make_line

# ---------------------------------------------------------------- model helpers
# A normalized team:
# {"code","name","lsc","city","state","zip",
#  "swimmers": {key: {"first","last","gender","age","dob","class"}},
#  "entries": [{"swimmer": key, "gender", "dist", "stroke", "seed", "course"}],
#  "relays":  [{"gender","dist","stroke","letter","legs":[key,...],"seed","course"}]}
# strokes: A free, B back, C breast, D fly, E IM / medley relay

EVENT_WORDS = [
    (r"\b(i\.?m\.?|individual medley)\b", "E"),
    (r"\b(medley)\b", "E"),
    (r"\b(free|freestyle|fr)\b", "A"),
    (r"\b(back|backstroke|bk)\b", "B"),
    (r"\b(breast|breaststroke|br)\b", "C"),
    (r"\b(fly|butterfly|bf)\b", "D"),
]


def event_from_text(s: str):
    """'200 free' -> (200, 'A'); '100 Fly' -> (100, 'D'); None if not an event."""
    m = re.search(r"(\d{2,4})\s*(?:yd|yard|y|m)?\s*([A-Za-z. ]+)", s)
    if not m:
        return None
    dist, words = int(m.group(1)), m.group(2).lower()
    for pat, code in EVENT_WORDS:
        if re.search(pat, words):
            return dist, code
    return None


def team_code_from_name(name: str, used: set) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name.upper())
    base = (words[0] if len(words) == 1 else "".join(w[:3] for w in words))[:5] or "TEAM"
    code, n = base, 2
    while code in used:
        code = f"{base[:4]}{n}"
        n += 1
    used.add(code)
    return code


def split_name(full: str):
    full = re.sub(r"\s+", " ", full.strip().strip(",;.")).strip()
    if "," in full:                       # "Last, First"
        last, first = [x.strip() for x in full.split(",", 1)]
    else:
        parts = full.split(" ")
        first, last = parts[0], " ".join(parts[1:])
    return first, last


def name_key(team: str, first: str, last: str) -> str:
    return f"{team}|{first.lower()} {last.lower()}"


# ---------------------------------------------------------------- Word / text lists
def docx_text(data: bytes) -> str:
    """Paragraph text of a .docx, keeping tabs (Word uses them for the relay columns)."""
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    lines = []
    for p in root.iter(w + "p"):
        buf = []
        for el in p.iter():
            if el.tag == w + "t":
                buf.append(el.text or "")
            elif el.tag == w + "tab":
                buf.append("\t")
            elif el.tag in (w + "br", w + "cr"):
                buf.append("\n")
        lines.extend("".join(buf).split("\n"))
    return "\n".join(lines)


HEADER = re.compile(r"^\s*(?P<team>.*?)\s*(?:team\s+)?(?P<g>girls|boys|women|men|ladies)\b\s*(?P<rel>relays?)?\s*[:\-–]?\s*$", re.I)
LABEL = re.compile(r"(?:(?<=^)|(?<=[\s\t])|(?<=[a-z\.]))([A-F])\s*[:\.\)]\s*")
COLSPLIT = re.compile(r"\t+|\s{3,}")


def _fuzzy(a: str, b: str) -> bool:
    """True for small typos like Ameila/Amelia (same letters, <=2 edits)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 2:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] <= 2 or sorted(a) == sorted(b)


def parse_entry_list(text: str, used_codes: set | None = None) -> dict:
    """Parse a coach's typed entry list. Returns {"teams": [...], "warnings": [...]}."""
    used = used_codes if used_codes is not None else set()
    teams: dict[str, dict] = {}
    warnings: list[str] = []
    team = gender = None
    section = None            # "ind" | "relay"
    relay_ev = None           # (dist, stroke)
    open_cols: list[dict] = []  # relays being filled column by column
    pending_relays = []       # (team, gender, (dist,stroke), letter, [names], lineno)

    def get_team(name: str) -> dict:
        nm = re.sub(r"\s+", " ", name).strip() or "Team"
        if nm not in teams:
            teams[nm] = {"code": team_code_from_name(nm, used), "name": nm, "lsc": "", "swimmers": {},
                         "entries": [], "relays": []}
        return teams[nm]

    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip():
            continue
        h = HEADER.match(line.strip())
        if h and not event_from_text(line):
            tname = h.group("team").strip() or (team["name"] if team else "Team")
            team = get_team(re.sub(r"\bteam\b", "", tname, flags=re.I))
            gender = "F" if h.group("g").lower() in ("girls", "women", "ladies") else "M"
            section = "relay" if h.group("rel") else "ind"
            relay_ev, open_cols = None, []
            continue
        if team is None:
            warnings.append(f"line {lineno}: ignored (no team/gender heading yet): {line.strip()[:60]}")
            continue

        if section == "relay":
            body = line
            ev = event_from_text(line.split(":")[0]) if re.match(r"^\s*\d{3}", line) else None
            if ev:
                relay_ev = (ev[0], "E" if ev[1] == "E" else "A")
                open_cols = []
                body = re.sub(r"^\s*\d{3}[^-–:]*?(relay)?\s*[-–:]\s*", "", line, flags=re.I)
                if not body.strip():
                    continue
            if relay_ev is None:
                warnings.append(f"line {lineno}: relay names before any relay event: {line.strip()[:60]}")
                continue
            parts = LABEL.split(body)
            if len(parts) > 1:                       # line with A:/B: labels
                labelled = list(zip(parts[1::2], parts[2::2]))
                open_cols = []
                for letter, rest in labelled:
                    names = [n for n in re.split(r",|\t+|\s{3,}", rest) if n.strip()]
                    r = {"team": team, "gender": gender, "ev": relay_ev, "letter": letter, "names": names, "line": lineno}
                    pending_relays.append(r)
                    if len(names) < 4:
                        open_cols.append(r)
            else:                                    # continuation row: one name per column
                cols = [c.strip() for c in COLSPLIT.split(line.strip()) if c.strip()]
                if not open_cols:
                    warnings.append(f"line {lineno}: relay names with no A:/B: column above: {line.strip()[:60]}")
                    continue
                if len(cols) != len(open_cols):
                    # fewer names than columns: fill left to right, but say so
                    warnings.append(f"line {lineno}: expected {len(open_cols)} relay columns, found {len(cols)}: {line.strip()[:60]}")
                for r, c in zip(open_cols, cols):
                    r["names"].append(c)
                open_cols = [r for r in open_cols if len(r["names"]) < 4]
            continue

        # individual line: "Name - event, event"
        m = re.match(r"^\s*(?P<name>[^\-–:0-9]+?)\s*[-–:]\s*(?P<evs>.+)$", line)
        if not m:
            warnings.append(f"line {lineno}: couldn't read: {line.strip()[:60]}")
            continue
        first, last = split_name(m.group("name"))
        key = name_key(team["code"], first, last)
        if key not in team["swimmers"]:
            team["swimmers"][key] = {"first": first, "last": last, "gender": gender, "age": 0, "dob": "", "class": ""}
        for piece in re.split(r",|;|/|\band\b", m.group("evs")):
            if not piece.strip():
                continue
            seed = 0.0
            tm = re.search(r"(\d+:)?\d{1,2}\.\d{2}", piece)
            if tm:
                v = tm.group(0)
                seed = (int(v.split(":")[0]) * 60 + float(v.split(":")[1])) if ":" in v else float(v)
            ev = event_from_text(piece)
            if not ev:
                warnings.append(f"line {lineno}: {first} {last}: unknown event '{piece.strip()}'")
                continue
            team["entries"].append({"swimmer": key, "gender": gender, "dist": ev[0], "stroke": ev[1], "seed": seed, "course": "Y"})

    # resolve relay names against the team roster (fuzzy for typos, add relay-only swimmers otherwise)
    for r in pending_relays:
        t, g = r["team"], r["gender"]
        legs = []
        for nm in r["names"][:8]:
            first, last = split_name(nm)
            key = name_key(t["code"], first, last)
            if key not in t["swimmers"]:
                cands = [k for k, s in t["swimmers"].items() if s["gender"] == g and s["last"].lower() == last.lower()
                         and _fuzzy(s["first"].lower(), first.lower())]
                cands = cands or [k for k, s in t["swimmers"].items() if s["gender"] == g and s["first"].lower() == first.lower()
                                  and _fuzzy(s["last"].lower(), last.lower())]
                if len(cands) == 1:
                    s = t["swimmers"][cands[0]]
                    warnings.append(f"line {r['line']}: relay name '{nm.strip()}' read as {s['first']} {s['last']}")
                    key = cands[0]
                else:
                    warnings.append(f"line {r['line']}: {nm.strip()} is on a relay but has no individual events - added as relay-only swimmer")
                    t["swimmers"][key] = {"first": first, "last": last, "gender": g, "age": 0, "dob": "", "class": ""}
            legs.append(key)
        if len(legs) != 4:
            warnings.append(f"line {r['line']}: {t['name']} {'girls' if g == 'F' else 'boys'} {r['ev'][0]} relay {r['letter']} has {len(legs)} swimmers")
        t["relays"].append({"gender": g, "dist": r["ev"][0], "stroke": r["ev"][1], "letter": r["letter"], "legs": legs,
                            "seed": 0.0, "course": "Y"})
    return {"teams": list(teams.values()), "warnings": warnings}


# ---------------------------------------------------------------- SDIF (.cl2 / .sd3)
SDIF_STROKE = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E", "6": "A", "7": "E"}
SDIF_COURSE = {"1": "S", "2": "Y", "3": "L", "S": "S", "M": "S", "Y": "Y", "L": "L", "X": "Y"}


def _f(line: str, start: int, n: int) -> str:
    return line[start - 1:start - 1 + n].strip()


def _sdif_time(s: str) -> float:
    s = s.strip().upper()
    if not s or s.startswith("NT") or s in ("NS", "DQ", "SCR"):
        return 0.0
    try:
        if ":" in s:
            m, sec = s.split(":", 1)
            return int(m) * 60 + float(sec)
        return float(s)
    except ValueError:
        return 0.0


def _sdif_date(s: str) -> str:
    return f"{s[4:8]}-{s[0:2]}-{s[2:4]}" if len(s) == 8 and s.isdigit() else ""


def parse_sdif(data: bytes, used_codes: set | None = None) -> dict:
    used = used_codes if used_codes is not None else set()
    teams, warnings, cur, relay = {}, [], None, None
    for lineno, raw in enumerate(data.decode("latin-1").splitlines(), 1):
        rt = raw[:2]
        if rt == "C1":
            code = (_f(raw, 12, 6)[2:] or _f(raw, 12, 6) or team_code_from_name(_f(raw, 18, 30), used))[:5]
            cur = teams.setdefault(code, {"code": code, "name": _f(raw, 18, 30) or code, "lsc": _f(raw, 12, 6)[:2],
                                          "city": _f(raw, 108, 20), "state": _f(raw, 128, 2), "zip": _f(raw, 130, 10),
                                          "swimmers": {}, "entries": [], "relays": []})
            used.add(code)
            relay = None
        elif rt == "D0" and cur is not None:
            first, last = split_name(_f(raw, 12, 28))
            g = _f(raw, 66, 1) or "F"
            key = name_key(cur["code"], first, last)
            age = _f(raw, 64, 2)
            cur["swimmers"].setdefault(key, {"first": first, "last": last, "gender": "F" if g in "FW" else "M",
                                             "age": int(age) if age.isdigit() else 0, "dob": _sdif_date(_f(raw, 56, 8)),
                                             "class": "" if age.isdigit() else age})
            dist, stroke = _f(raw, 68, 4), _f(raw, 72, 1)
            if dist.isdigit() and stroke in SDIF_STROKE:
                esex = _f(raw, 67, 1) or g
                cur["entries"].append({"swimmer": key, "gender": "F" if esex in "FW" else ("X" if esex == "X" else "M"),
                                       "dist": int(dist), "stroke": SDIF_STROKE[stroke], "seed": _sdif_time(_f(raw, 89, 8)),
                                       "course": SDIF_COURSE.get(_f(raw, 97, 1), "Y")})
        elif rt == "E0" and cur is not None:
            esex, dist, stroke = _f(raw, 21, 1), _f(raw, 22, 4), _f(raw, 26, 1)
            if not dist.isdigit() or stroke not in SDIF_STROKE:
                warnings.append(f"line {lineno}: relay record without distance/stroke skipped")
                relay = None
                continue
            relay = {"gender": "F" if esex in "FW" else ("X" if esex == "X" else "M"), "dist": int(dist),
                     "stroke": SDIF_STROKE[stroke], "letter": _f(raw, 12, 1) or "A", "legs": [], "seed": _sdif_time(_f(raw, 46, 8)),
                     "course": SDIF_COURSE.get(_f(raw, 54, 1), "Y"), "_order": []}
            cur["relays"].append(relay)
        elif rt == "F0" and cur is not None and relay is not None:
            first, last = split_name(_f(raw, 23, 28))
            g = _f(raw, 76, 1) or relay["gender"]
            key = name_key(cur["code"], first, last)
            if key not in cur["swimmers"]:
                age = _f(raw, 74, 2)
                cur["swimmers"][key] = {"first": first, "last": last, "gender": "F" if g in "FW" else "M",
                                        "age": int(age) if age.isdigit() else 0, "dob": _sdif_date(_f(raw, 66, 8)), "class": ""}
            order = _f(raw, 79, 1)
            relay["_order"].append((int(order) if order.isdigit() and order != "0" else 9, key))
    for t in teams.values():
        for r in t["relays"]:
            r["legs"] = [k for _, k in sorted(r.pop("_order"), key=lambda x: x[0])][:8]
    if not teams:
        warnings.append("no team (C1) records found - is this an SDIF/.cl2 entry file?")
    return {"teams": list(teams.values()), "warnings": warnings}


# ---------------------------------------------------------------- normalized -> .hy3
def _rec(rt: str, fields) -> bytes:
    b = list(rt.ljust(128))
    for col, s in fields:
        s = str(s)
        b[col - 1:col - 1 + len(s)] = list(s[:128 - col + 1])
    return make_line("".join(b)[:128])


def to_hy3(parsed: dict, events: list[dict], meet_name: str = "") -> tuple[bytes, list[str]]:
    """events = master events [{"no","gender","indrel","dist","stroke"}] used to number entries."""
    evmap = {(e["gender"], e["indrel"], int(e["dist"]), e["stroke"]): int(e["no"]) for e in events}
    warnings: list[str] = []
    lines = [_rec("A1", [(3, "02"), (5, "Meet Entries"), (30, "MeetDeck"), (45, "converted")]),
             _rec("B1", [(3, meet_name[:45])])]
    mid = 0
    for t in parsed["teams"]:
        lines.append(_rec("C1", [(3, t["code"].ljust(5)), (8, t["name"][:30].ljust(30)), (38, t["name"][:16].ljust(16)),
                                 (54, (t.get("lsc") or "")[:2])]))
        lines.append(_rec("C2", [(63, (t.get("city") or "")[:30].ljust(30)), (93, (t.get("state") or "")[:2]),
                                 (95, (t.get("zip") or "")[:10].ljust(10)), (105, "USA")]))
        ids = {}
        by_sw: dict[str, list] = {}
        for e in t["entries"]:
            by_sw.setdefault(e["swimmer"], []).append(e)
        for key, s in t["swimmers"].items():
            mid += 1
            ids[key] = mid
            dob = s.get("dob") or ""
            dob_s = f"{dob[5:7]}{dob[8:10]}{dob[0:4]}" if len(dob) == 10 else ""
            lines.append(_rec("D1", [(3, s["gender"]), (4, f"{mid:5d}"), (9, s["last"][:20].ljust(20)), (29, s["first"][:20].ljust(20)),
                                     (89, dob_s.ljust(8)), (97, f"{s['age']:3d}" if s.get("age") else "   "),
                                     (100, (s.get("class") or "")[:2])]))
            for e in by_sw.get(key, []):
                g = e["gender"] if e["gender"] in "FM" else s["gender"]
                no = evmap.get((g, "I", e["dist"], e["stroke"]))
                if no is None:
                    warnings.append(f"{t['name']}: {s['first']} {s['last']} entered in {e['dist']} {e['stroke']} - no such event in the host master; skipped")
                    continue
                seed = e.get("seed") or 0.0
                lines.append(_rec("E1", [(3, g), (4, f"{mid:5d}"), (9, s["last"][:5].ljust(5)), (14, g), (15, g),
                                         (16, str(e["dist"]).rjust(6)), (22, e["stroke"]), (39, str(no).rjust(4)),
                                         (43, f"{seed:8.2f}"), (51, e.get("course", "Y")), (52, f"{seed:8.2f}"), (60, e.get("course", "Y"))]))
        for r in t["relays"]:
            g = r["gender"] if r["gender"] in "FM" else "M"
            no = evmap.get((g, "R", r["dist"], r["stroke"]))
            if no is None:
                warnings.append(f"{t['name']}: {r['dist']} relay ({r['stroke']}) not in the host master; skipped")
                continue
            seed = r.get("seed") or 0.0
            lines.append(_rec("F1", [(3, t["code"].ljust(5)), (8, r["letter"]), (14, g), (15, g), (16, str(r["dist"]).rjust(6)),
                                     (22, r["stroke"]), (39, str(no).rjust(4)), (43, f"{seed:8.2f}"), (51, r.get("course", "Y")),
                                     (52, f"{seed:8.2f}"), (60, r.get("course", "Y"))]))
            f3 = []
            for slot, key in enumerate(r["legs"][:8]):
                s = t["swimmers"][key]
                f3 += [(3 + 13 * slot, s["gender"]), (4 + 13 * slot, f"{ids[key]:5d}"), (9 + 13 * slot, s["last"][:5].ljust(5)),
                       (14 + 13 * slot, "F"), (15 + 13 * slot, str(slot + 1))]
            lines.append(_rec("F3", f3 or [(3, " ")]))
    return b"".join(lines), warnings


# ---------------------------------------------------------------- dispatcher
def detect(filename: str, data: bytes) -> list[tuple[str, str, bytes]]:
    """Return [(kind, inner_name, bytes)] for everything usable in an upload.
    kind: 'hy3' | 'sdif' | 'docx' | 'text'."""
    name = filename.lower()
    if name.endswith(".zip"):
        out = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():
                if n.endswith("/"):
                    continue
                out += detect(n.split("/")[-1], z.read(n))
        return out
    if name.endswith(".hy3"):
        return [("hy3", filename, data)]
    if name.endswith((".cl2", ".sd3", ".sdif")):
        return [("sdif", filename, data)]
    if name.endswith(".docx"):
        return [("docx", filename, data)]
    if name.endswith((".txt", ".text", ".csv")) or not re.search(r"\.[a-z0-9]{2,5}$", name):
        return [("text", filename, data)]
    if data[:2] in (b"A0", b"A1") and b"\nC1" in data[:4000].replace(b"\r", b""):
        return [("sdif" if data[:2] == b"A0" else "hy3", filename, data)]
    return []
