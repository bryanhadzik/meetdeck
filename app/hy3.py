"""Lossless Hy-Tek .hy3 entry-file handling.

We never rewrite a coach's lines. Parsing groups the raw lines into removable
entry blocks (E1 + its E2/G/H lines, F1 + its F2/F3/G/H lines). Cleaning just
drops whole blocks, so every surviving line keeps the checksum Team Manager /
SwimTopia / TeamUnify wrote, and Meet Manager imports it as if the coach had
sent it that way.
"""
from __future__ import annotations

import io
import math
import zipfile

STROKES = {"A": "Free", "B": "Back", "C": "Breast", "D": "Fly", "E": "IM",
           "1": "Free", "2": "Back", "3": "Breast", "4": "Fly", "5": "IM"}
GENDERS = {"F": "Women", "W": "Women", "G": "Women", "M": "Men", "B": "Men", "X": "Mixed"}


def checksum(body: bytes) -> bytes:
    """Hy-Tek per-line checksum over the first 128 bytes."""
    s_even = s_odd = 0
    for i, b in enumerate(body[:128]):
        if i % 2 == 0:
            s_even += b
        else:
            s_odd += 2 * b
    c = math.floor((s_even + s_odd) / 21) + 205
    return f"{c % 10}{(c // 10) % 10}".encode()


def make_line(body: str) -> bytes:
    """Build a checksummed line (used only for test fixtures)."""
    b = body.ljust(128)[:128].encode("latin-1")
    return b + checksum(b) + b"\r\n"


def _x(s: str, start: int, n: int) -> str:
    return s[start - 1:start - 1 + n].strip()


def _secs(raw: str):
    raw = raw.strip()
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v > 0 else None


def _dob(raw: str):
    if len(raw) == 8 and raw.isdigit():
        return f"{raw[4:]}-{raw[:2]}-{raw[2:4]}"
    return ""


def fmt_time(v):
    if not v:
        return "NT"
    m, s = divmod(v, 60)
    return f"{int(m)}:{s:05.2f}" if m else f"{s:.2f}"


def parse_hy3(data: bytes, source: str) -> dict:
    raw_lines = data.splitlines(keepends=True)
    teams: dict[str, dict] = {}
    swimmers: dict[str, dict] = {}
    entries: list[dict] = []
    bad_checksums = 0
    team = None
    swimmer_key = None
    cur = None  # current removable entry block
    by_id: dict[str, list[str]] = {}

    def resolve(mid: str, tm: str) -> str:
        keys = by_id.get(mid, [])
        same = [k for k in keys if swimmers[k]["team"] == tm]
        return (same or keys or [f"{source}|{tm}|{mid}"])[0]

    for idx, raw in enumerate(raw_lines):
        line = raw.rstrip(b"\r\n").decode("latin-1")
        if len(line) < 2:
            continue
        rt = line[:2]
        if len(line) >= 130 and checksum(line[:128].encode("latin-1")) != line[128:130].encode("latin-1"):
            bad_checksums += 1

        if rt == "C1":
            code = _x(line, 3, 5) or _x(line, 8, 30)[:5].upper()
            team = code
            teams.setdefault(code, {"code": code, "name": _x(line, 8, 30) or code,
                                    "short": _x(line, 38, 16), "lsc": _x(line, 54, 2),
                                    "source": source})
            swimmer_key, cur = None, None
        elif rt == "C2" and team in teams:
            teams[team].update(addr1=_x(line, 3, 30), addr2=_x(line, 33, 30), city=_x(line, 63, 30),
                               state=_x(line, 93, 2), zip=_x(line, 95, 10), country=_x(line, 105, 3) or "USA")
            cur = None
        elif rt == "C3" and team in teams:
            teams[team].update(phone=_x(line, 33, 20), email=_x(line, 93, 36))
            cur = None
        elif rt[0] == "C":
            cur = None
        elif rt == "D1":
            mid = _x(line, 4, 5)
            swimmer_key = f"{source}|{mid}"
            if swimmer_key in swimmers:            # ids collide across teams: fall back to team-scoped key
                swimmer_key = f"{source}|{team}|{mid}"
            by_id.setdefault(mid, []).append(swimmer_key)
            age = _x(line, 97, 3)
            swimmers[swimmer_key] = {
                "key": swimmer_key, "team": team, "meet_id": mid,
                "gender": _x(line, 3, 1), "last": _x(line, 9, 20), "first": _x(line, 29, 20),
                "pref": _x(line, 49, 20), "age": int(age) if age.isdigit() else None,
                "class": _x(line, 100, 2), "initial": _x(line, 69, 1), "dob": _dob(_x(line, 89, 8)),
            }
            cur = None
        elif rt[0] == "D":
            cur = None  # extra swimmer info, stays with roster
        elif rt == "E1":
            mid = _x(line, 4, 5)
            cur = {
                "id": f"{source}#{idx}", "source": source, "kind": "ind", "team": team,
                "swimmers": [mid], "legs": {},
                "event_no": _x(line, 39, 4), "gender": _x(line, 14, 1),
                "distance": _x(line, 16, 6).split(".")[0], "stroke": _x(line, 22, 1),
                "seed": _secs(_x(line, 52, 8)) or _secs(_x(line, 43, 8)),
                "course": _x(line, 60, 1) or _x(line, 51, 1) or "Y",
                "conv_seed": _secs(_x(line, 43, 8)) or _secs(_x(line, 52, 8)),
                "conv_course": _x(line, 51, 1) or _x(line, 60, 1) or "Y",
                "exhibition": _x(line, 84, 1) == "X", "lines": [idx],
            }
            entries.append(cur)
        elif rt == "F1":
            cur = {
                "id": f"{source}#{idx}", "source": source, "kind": "relay", "team": team,
                "relay": _x(line, 8, 1) or "A", "swimmers": [], "legs": {},
                "event_no": _x(line, 39, 4), "gender": _x(line, 14, 1),
                "distance": _x(line, 16, 6).split(".")[0], "stroke": _x(line, 22, 1),
                "seed": _secs(_x(line, 52, 8)) or _secs(_x(line, 43, 8)),
                "course": _x(line, 60, 1) or _x(line, 51, 1) or "Y",
                "conv_seed": _secs(_x(line, 43, 8)) or _secs(_x(line, 52, 8)),
                "conv_course": _x(line, 51, 1) or _x(line, 60, 1) or "Y",
                "exhibition": False, "lines": [idx],
            }
            entries.append(cur)
        elif rt == "F3" and cur and cur["kind"] == "relay":
            cur["lines"].append(idx)
            for slot in range(8):
                off = slot * 13
                mid = _x(line, 4 + off, 5)
                if not mid or not mid.isdigit():
                    continue
                leg = _x(line, 15 + off, 1)
                leg = int(leg) if leg.isdigit() else slot + 1
                cur["legs"][leg] = mid
        elif rt[0] in "EFGH" and cur:
            cur["lines"].append(idx)  # results / splits / DQ lines belong to the entry
        else:
            cur = None  # anything unknown is kept as-is

    # Resolve swimmer ids only now: relays can name swimmers whose roster lines come later.
    for e in entries:
        e["legs"] = {leg: resolve(m, e["team"]) for leg, m in sorted(e["legs"].items())}
        if e["kind"] == "ind":
            e["swimmers"] = [resolve(e["swimmers"][0], e["team"])]
        else:
            e["swimmers"] = [k for leg, k in e["legs"].items() if leg <= 4]
    for e in entries:
        stroke = STROKES.get(e["stroke"], e["stroke"])
        if e["kind"] == "relay":
            stroke = ("Medley" if stroke == "IM" else stroke) + " Relay"
        e["event"] = f"{GENDERS.get(e['gender'], e['gender'])} {e['distance']} {stroke}"
        e["seed_fmt"] = fmt_time(e["seed"])
    return {"source": source, "teams": teams, "swimmers": swimmers, "entries": entries,
            "line_count": len(raw_lines), "bad_checksums": bad_checksums}


def clean_hy3(data: bytes, drop_lines: set[int]) -> bytes:
    raw_lines = data.splitlines(keepends=True)
    return b"".join(l for i, l in enumerate(raw_lines) if i not in drop_lines)


def read_upload(filename: str, data: bytes) -> list[tuple[str, bytes]]:
    """Return [(hy3_name, bytes)] from a .hy3 or a .zip that contains them."""
    name = filename.lower()
    if name.endswith(".hy3"):
        return [(filename, data)]
    if name.endswith(".zip"):
        out = []
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in z.namelist():
                if n.lower().endswith(".hy3"):
                    out.append((n.split("/")[-1], z.read(n)))
        return out
    return []


# ---- rules -----------------------------------------------------------------

def _lbl(e):
    """'Girls 50 Free (Ev 7)' / 'Girls 200 Free Relay "A" (Ev 15)'."""
    return f"{e['event']}{' \"' + e.get('relay', 'A') + '\"' if e['kind'] == 'relay' else ''} (Ev {e['event_no']})"


def _list(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def validate(swimmers: dict, entries: list[dict], removed: set[str], rules: dict, team_names: dict | None = None) -> list[dict]:
    """Rule problems. Each issue: level, msg (for Bryan), coach (plain wording for the coach),
    teams (team codes the coach message should go to), entries, swimmer."""
    max_ind = rules.get("max_individual", 2)
    max_total = rules.get("max_total", 4)
    team_cap = rules.get("team_cap_per_event") or 0
    exhibition = rules.get("meet_type") == "exhibition"
    if exhibition:
        team_cap = 0
    R_EV = "UHSAA / NFHS: max 2 individual events (diving counts as one) and 4 events total"
    R_RELAY = "NFHS: a relay is 4 different swimmers from the same school, each swimming one leg"
    active = [e for e in entries if e["id"] not in removed]
    issues = []
    tn = lambda c: (team_names or {}).get(c, c)

    by_swimmer: dict[str, list[dict]] = {}
    for e in active:
        for s in set(e["swimmers"]):
            by_swimmer.setdefault(s, []).append(e)

    for key, ents in by_swimmer.items():
        sw = swimmers.get(key, {"first": "?", "last": key, "team": key.split("|")[0]})
        name = f"{sw['first']} {sw['last']}"
        who = f"{name} ({sw['team']})"
        ind = [e for e in ents if e["kind"] == "ind"]
        rel = [e for e in ents if e["kind"] != "ind"]
        over_ind = max(0, len(ind) - max_ind)
        over_tot = max(0, len(ents) - over_ind - max_total)   # still over after dropping the extra individuals
        if over_ind or over_tot:
            msg = []
            if over_ind:
                msg.append(f"{len(ind)} individual events (max {max_ind})")
            if len(ents) > max_total:
                msg.append(f"{len(ents)} events total (max {max_total})")
            parts = []
            if ind:
                parts.append(f"Individual: {_list(_lbl(e) for e in ind)}.")
            if rel:
                parts.append(f"Relays: {_list(_lbl(e) for e in rel)}.")
            fix = []
            if over_ind:
                fix.append(f"drop {over_ind} of the individual events")
            if over_tot:
                fix.append(f"{'drop ' if not over_ind else ''}{over_tot} more event{'s' if over_tot != 1 else ''} (individual or relay)")
            also = f", which also brings the total to {len(ents) - over_ind}" if over_ind and len(ents) > max_total and not over_tot else ""
            issues.append({"level": "error", "swimmer": key, "entries": [e["id"] for e in ents],
                           "teams": sorted({sw["team"]} | {e["team"] for e in ents}), "rule": R_EV,
                           "msg": f"{who} is in " + " and ".join(msg),
                           "coach": f"{name} is in {len(ents)} event{'s' if len(ents) != 1 else ''}. " + " ".join(parts) +
                                    f" The limits are {max_ind} individual and {max_total} total including relays, "
                                    f"so please {' and '.join(fix)}{also}."})
        seen = {}
        for e in ents:
            seen.setdefault(e["event_no"], []).append(e)
        for evn, dup in seen.items():
            if len(dup) > 1:
                if all(e["kind"] == "relay" for e in dup):
                    where = _list(f"{tn(e['team'])}'s \"{e.get('relay', 'A')}\" relay" for e in dup)
                    txt = f"{name} is on {len(dup)} relays in {dup[0]['event']} (Ev {evn}): {where}. A swimmer can only swim an event once - please pick one."
                else:
                    txt = f"{name} is entered {len(dup)} times in {dup[0]['event']} (Ev {evn}). Please remove the extra entry."
                issues.append({"level": "error", "swimmer": key, "entries": [e["id"] for e in dup],
                               "teams": sorted({sw["team"]} | {e["team"] for e in dup}),
                               "rule": "A swimmer may swim each event only once", "msg": f"{who} is entered {len(dup)}x in event {evn}", "coach": txt})

    for e in active:
        if e["kind"] == "relay":
            other = [swimmers[k] for k in e["swimmers"] if k in swimmers and swimmers[k]["team"] != e["team"]]
            for o in ([] if exhibition else other):
                issues.append({"level": "warn", "rule": R_RELAY + " (switch the meet to Exhibition / intersquad if the teams are one school)", "swimmer": None, "entries": [e["id"]], "teams": sorted({e["team"], o["team"]}),
                               "msg": f"{o['first']} {o['last']} ({o['team']}) is on {e['team']}'s {e['relay']} relay in event "
                                      f"{e['event_no']} - allowed only if you turn on 'anyone on relay' (the MM backup does this automatically)",
                               "coach": f"{o['first']} {o['last']} is entered for {tn(o['team'])} but is listed on {tn(e['team'])}'s {_lbl(e)}. "
                                        f"Please confirm that's intended, or send a replacement swimmer."})
        if e["kind"] == "relay" and len(set(e["swimmers"])) < len(e["swimmers"]):
            dups = sorted({swimmers.get(k, {}).get("first", "?") + " " + swimmers.get(k, {}).get("last", "") for k in e["swimmers"] if e["swimmers"].count(k) > 1})
            issues.append({"level": "error", "swimmer": None, "entries": [e["id"]], "teams": [e["team"]], "rule": R_RELAY,
                           "msg": f"{e['team']} {e['relay']} relay, event {e['event_no']}: same swimmer on two legs",
                           "coach": f"{_lbl(e)}: {_list(dups)} is listed on more than one leg. Please send four different swimmers."})
        if e["kind"] == "relay" and (0 < len(e["swimmers"]) or e.get("legs_changed")) and len(e["swimmers"]) < 4:
            issues.append({"level": "error", "swimmer": None, "entries": [e["id"]], "teams": [e["team"]], "rule": R_RELAY,
                           "msg": f"{e['team']} {e['relay']} relay, event {e['event_no']}: only {len(e['swimmers'])} swimmer(s) listed",
                           "coach": f"{_lbl(e)} only lists {len(e['swimmers'])} swimmer(s): "
                                    f"{_list(swimmers.get(k, {}).get('first', '?') + ' ' + swimmers.get(k, {}).get('last', '') for k in e['swimmers']) if e['swimmers'] else 'nobody'}. "
                                    f"A relay needs four - please send the rest."})
        if e["kind"] == "relay" and e["gender"] in "FMWBG" and e["gender"] != "X":
            wrong = [swimmers[k] for k in dict.fromkeys(e["swimmers"]) if k in swimmers and swimmers[k].get("gender")
                     and GENDERS.get(swimmers[k]["gender"]) != GENDERS.get(e["gender"])]
            if wrong:
                nm = _list(f"{w['first']} {w['last']}" for w in wrong)
                issues.append({"level": "error", "swimmer": None, "entries": [e["id"]], "teams": [e["team"]],
                               "rule": "A girls' or boys' relay may only include swimmers of that gender",
                               "msg": f"{e['team']} {e['relay']} relay, event {e['event_no']}: {nm} listed as the other gender",
                               "coach": f"{_lbl(e)} includes {nm}, who {'is' if len(wrong) == 1 else 'are'} listed as "
                                        f"{GENDERS.get(wrong[0]['gender'], '').lower()[:-1]} on your roster. Please check the roster or swap the swimmer."})
        if e["kind"] == "ind" and e["swimmers"][0] in swimmers:
            sw = swimmers[e["swimmers"][0]]
            sg = sw["gender"]
            if sg and e["gender"] in "FMWB" and GENDERS.get(sg) != GENDERS.get(e["gender"]):
                issues.append({"level": "warn", "swimmer": e["swimmers"][0], "entries": [e["id"]], "teams": [e["team"]], "rule": "Swimmers enter events for their own gender",
                               "msg": f"Gender mismatch: {sw['first']} {sw['last']} entered in {e['event']}",
                               "coach": f"{sw['first']} {sw['last']} is listed as {GENDERS.get(sg, sg).lower()[:-1]} but entered in "
                                        f"{_lbl(e)}. Please check which is right."})

    if team_cap:
        counts: dict[tuple, list] = {}
        for e in active:
            if e["kind"] == "ind" and not e["exhibition"]:
                counts.setdefault((e["team"], e["event_no"]), []).append(e)
        for (t, evn), ents in counts.items():
            if len(ents) > team_cap:
                names = [f"{swimmers[e['swimmers'][0]]['first']} {swimmers[e['swimmers'][0]]['last']}" for e in ents if e["swimmers"][0] in swimmers]
                issues.append({"level": "warn", "swimmer": None, "entries": [e["id"] for e in ents], "teams": [t],
                               "rule": "NFHS 3-1-1: championship meets allow 4 entries per team in an individual event" if rules.get("championship") else "Meet limit you set",
                               "msg": f"{t} has {len(ents)} scoring entries in event {evn} (cap {team_cap})",
                               "coach": f"{ents[0]['event']} (Ev {evn}) has {len(ents)} scoring entries ({_list(names)}); the limit is "
                                        f"{team_cap} per team. Please tell me which to make exhibition."})
    if rules.get("championship"):          # NFHS 3-1-1: one relay team per event in championship meets
        rel: dict[tuple, list] = {}
        for e in active:
            if e["kind"] == "relay" and not e.get("exhibition"):
                rel.setdefault((e["team"], e["event_no"]), []).append(e)
        for (t, evn), ents in rel.items():
            if len(ents) > 1:
                issues.append({"level": "warn", "swimmer": None, "entries": [e["id"] for e in ents], "teams": [t],
                               "rule": "NFHS 3-1-1: championship meets allow one relay team per team in each relay event",
                               "msg": f"{t} has {len(ents)} relays in event {evn} (championship rules allow 1)",
                               "coach": f"{ents[0]['event']} (Ev {evn}) has {len(ents)} relays for your team; championship rules allow one. "
                                        f"Please tell me which one swims (the others can be exhibition)."})
    return issues


# NFHS Rule 5-3 (2026-27 Rules Book p. 45-46), lane assignments for team-lane meets:
#  2 teams (dual meet, 5-3-1): odd / even lanes.
#  3 or 4 teams (non-championship multi-team, double dual / triple dual, 5-3-2 TABLE 5-1), by number of lanes.
#  5+ teams, or a lane count the table seeds: by seeding.
TABLE_5_1 = {
    3: {6: [[1, 4], [2, 5], [3, 6]], 8: [[1, 4], [2, 5], [3, 6]], 9: [[1, 4, 7], [2, 5, 8], [3, 6, 9]], 10: [[1, 4, 7], [2, 5, 8], [3, 6, 9]]},
    4: {8: [[1, 5], [2, 6], [3, 7], [4, 8]], 9: [[1, 5], [2, 6], [3, 7], [4, 8]], 10: [[1, 5], [2, 6], [3, 7], [4, 8]]},
    5: {10: [[1, 6], [2, 7], [3, 8], [4, 9], [5, 10]]},
}


def table_plan(team_codes: list[str], lanes: int, first_lane: int = 1):
    """Team lanes per NFHS 5-3: [{lane, team}] (lanes not listed stay open), or None when the meet is seeded."""
    n = len(team_codes)
    if n == 0:
        return []
    if n <= 2:
        return lane_plan(team_codes, lanes, first_lane)
    sets = TABLE_5_1.get(n, {}).get(lanes)
    if not sets:
        return None
    return sorted(({"lane": first_lane - 1 + ln, "team": t} for t, s_ in zip(team_codes, sets) for ln in s_), key=lambda p: p["lane"])


def table_has_open(team_codes: list[str], lanes: int) -> bool:
    """True when TABLE 5-1 leaves lanes open - meet management may seed instead (5-3-2)."""
    p = table_plan(team_codes, lanes)
    return bool(p) and len(team_codes) > 2 and len(p) < lanes


def lane_plan(team_codes: list[str], lanes: int, first_lane: int = 1) -> list[dict]:
    """Alternate lanes across teams in the given order (home team first)."""
    if not team_codes:
        return []
    return [{"lane": first_lane + i, "team": team_codes[i % len(team_codes)]} for i in range(lanes)]


# ---- combined boys/girls heats ---------------------------------------------
# Meet Manager's standard lane order for an n-lane block (center out), from its StdLanes table.
STD_ORDER = {1: [1], 2: [1, 2], 3: [2, 3, 1], 4: [2, 3, 1, 4], 5: [3, 4, 2, 5, 1], 6: [3, 4, 2, 5, 1, 6],
             7: [4, 5, 3, 6, 2, 7, 1], 8: [4, 5, 3, 6, 2, 7, 1, 8], 9: [5, 6, 4, 7, 3, 8, 2, 9, 1],
             10: [5, 6, 4, 7, 3, 8, 2, 9, 1, 10], 11: [6, 7, 5, 8, 4, 9, 3, 10, 2, 11, 1],
             12: [6, 7, 5, 8, 4, 9, 3, 10, 2, 11, 1, 12]}
COMBINABLE = [("ind", "200", "A"), ("ind", "500", "A"), ("relay", "400", "A")]
GIRLS = {"F", "W", "G"}


def _seed_key(e):
    return (0, e["seed"]) if e.get("seed") else (1, 0)


def _place_block(ents, lanes, center):
    """Fastest swimmers in the lanes nearest the middle of the pool; returns {entry_id: lane}."""
    order = sorted(lanes, key=lambda l: (abs(l - center), l))
    return {e["id"]: order[i] for i, e in enumerate(sorted(ents, key=_seed_key))}


def combine_plan(entries, removed, lane_count, first_lane, low="F", selected=()):
    """Find girls/boys event pairs that can swim as one heat with an empty lane between them.

    Returns (candidates, lanes) where lanes maps entry id -> (heat, lane) for selected pairs that fit."""
    active = [e for e in entries if e["id"] not in removed]
    cands, lanes = [], {}
    for kind, dist, stroke in COMBINABLE:
        evs = [e for e in active if e["kind"] == kind and e["distance"] == dist and e["stroke"] == stroke]
        girls = [e for e in evs if e["gender"] in GIRLS]
        boys = [e for e in evs if e["gender"] not in GIRLS]
        if not girls and not boys:
            continue
        key = f"{kind}-{dist}-{stroke}"
        g_no = sorted({e["event_no"] for e in girls}, key=lambda x: int(x or 0))
        b_no = sorted({e["event_no"] for e in boys}, key=lambda x: int(x or 0))
        need = len(girls) + len(boys) + 1
        label = f"{dist} {'Free Relay' if kind == 'relay' else 'Free'}"
        c = {"key": key, "label": label, "girls_event": ",".join(g_no), "boys_event": ",".join(b_no),
             "girls": len(girls), "boys": len(boys), "need": need, "lanes": lane_count,
             "fits": bool(girls and boys) and need <= lane_count, "selected": key in selected, "layout": []}
        if not girls or not boys:
            c["why"] = "only one gender entered - nothing to combine"
        elif need > lane_count:
            c["why"] = f"{len(girls)} girls + {len(boys)} boys + 1 empty lane = {need} lanes; pool has {lane_count}"
        if c["fits"]:
            start = first_lane + (lane_count - need) // 2
            lo, hi = (girls, boys) if low == "F" else (boys, girls)
            lo_lanes = list(range(start, start + len(lo)))
            hi_lanes = list(range(start + len(lo) + 1, start + need))
            gap = start + len(lo)
            center = first_lane + (lane_count - 1) / 2
            plan = {**_place_block(lo, lo_lanes, center), **_place_block(hi, hi_lanes, center)}
            byid = {e["id"]: e for e in evs}
            c["layout"] = sorted([{"lane": l, "who": "G" if byid[i]["gender"] in GIRLS else "B"} for i, l in plan.items()]
                                 + [{"lane": gap, "who": "-"}], key=lambda x: x["lane"])
            g_l = [l for i, l in plan.items() if byid[i]["gender"] in GIRLS]
            b_l = [l for i, l in plan.items() if byid[i]["gender"] not in GIRLS]
            c["girls_lanes"] = f"{min(g_l)}-{max(g_l)}" if len(g_l) > 1 else str(g_l[0])
            c["boys_lanes"] = f"{min(b_l)}-{max(b_l)}" if len(b_l) > 1 else str(b_l[0])
            if c["selected"]:
                lanes.update({i: (1, l) for i, l in plan.items()})
        cands.append(c)
    return cands, lanes


# ---- full pre-seeding (dual-meet style, no lone swimmers) --------------------------
POOL_LANES = 8


def seed_event(ents: list[dict], plan: list[dict], min_heat: int = 2, strict: bool = False):
    """Seed one event the way Meet Manager's dual-meet seeding does, plus a minimum heat size.

    plan: [{"lane": n, "team": code}] (the meet's lane assignments).
    Heats are filled fastest first with each team's fastest swimmers in that team's lanes; a team's
    unused lanes go to the next-fastest swimmers of other teams (MM's non-strict mode). Heat 1 swims
    first and is the slowest. If heat 1 would have fewer than min_heat swimmers, the slowest swimmers
    of heat 2 move into it.
    strict: NFHS 5-3-1 / 5-3-2 to the letter - every swimmer swims in their own team's lanes in every heat, even a
    heat with only one team in it; a team with more swimmers than lanes gets more heats instead of borrowing lanes.
    Returns ({entry_id: (heat, lane)}, info)."""
    if strict:
        return _seed_event_strict(ents, plan, min_heat)
    lanes = [p["lane"] for p in plan]
    if not ents or not lanes:
        return {}, {"heats": []}
    center = (min(lanes) + max(lanes)) / 2
    by_team: dict[str, list] = {}
    for e in sorted(ents, key=_seed_key):
        by_team.setdefault(e["team"], []).append(e)
    pool = {t: list(v) for t, v in by_team.items()}
    heats = []                      # fastest first: list of lists of entries
    while any(pool.values()):
        heat, free = [], []
        for p in plan:              # each team's lanes, fastest of that team first
            q = pool.get(p["team"])
            if q:
                heat.append(q.pop(0))
            else:
                free.append(p["lane"])
        rest = sorted((e for q in pool.values() for e in q), key=_seed_key)
        for e in rest[:len(free)]:  # fill unused lanes with next fastest overall
            pool[e["team"]].remove(e)
            heat.append(e)
        heats.append(heat)
    heats.reverse()                 # heat 1 = slowest, swum first
    moved = 0
    if len(heats) > 1 and len(heats[0]) < min_heat:
        need = min_heat - len(heats[0])
        donors = sorted(heats[1], key=_seed_key)       # slowest of heat 2 at the end
        give = donors[-need:] if len(heats[1]) - need >= min_heat else []
        for e in give:
            heats[1].remove(e)
            heats[0].append(e)
        moved = len(give)
    out = {}
    srt = sorted(lanes)
    for hno, heat in enumerate(heats, 1):
        used = set()
        # a short heat swims in the middle lanes (no gaps); teams keep their own lanes inside that block
        block = set(srt) if len(heat) >= len(srt) else {srt[i - 1] for i in STD_ORDER.get(len(srt), range(1, len(srt) + 1))[:len(heat)]}
        team_lanes = {}
        for p in plan:
            if p["lane"] in block:
                team_lanes.setdefault(p["team"], []).append(p["lane"])
        for t in team_lanes:
            team_lanes[t].sort(key=lambda l: (abs(l - center), l))
        overflow = []
        for e in sorted(heat, key=_seed_key):
            own = [l for l in team_lanes.get(e["team"], []) if l not in used]
            if own:
                out[e["id"]] = (hno, own[0])
                used.add(own[0])
            else:
                overflow.append(e)
        for e in overflow:
            free = sorted((l for l in block if l not in used), key=lambda l: (abs(l - center), l))
            out[e["id"]] = (hno, free[0])
            used.add(free[0])
    return out, {"heats": [len(h) for h in heats], "moved": moved,
                 "lone_before": len(heats) > 1 and len(heats[0]) - moved < min_heat}


def _seed_event_strict(ents, plan, min_heat):
    lanes = [p["lane"] for p in plan]
    if not ents or not lanes:
        return {}, {"heats": []}
    center = (min(lanes) + max(lanes)) / 2
    own = {}
    for p in plan:
        own.setdefault(p["team"], []).append(p["lane"])
    for t in own:
        own[t].sort(key=lambda l: (abs(l - center), l))
    pool = {}
    for e in sorted(ents, key=_seed_key):
        pool.setdefault(e["team"], []).append(e)
    stray = [e for t, q in pool.items() if t not in own for e in q]     # a team with no lanes (shouldn't happen)
    pool = {t: q for t, q in pool.items() if t in own}
    heats = []
    while any(pool.values()):            # fastest heat first: each team's fastest, one per lane it owns
        heat = []
        for t, ls in own.items():
            q = pool.get(t) or []
            heat += q[:len(ls)]
            pool[t] = q[len(ls):]
        heats.append(heat)
    heats.reverse()                      # heat 1 = slowest, swum first
    moved = 0
    if len(heats) > 1 and len(heats[0]) < min_heat:
        # bring the slowest of heat 2 down - only into a free lane of their own team
        for e in sorted(heats[1], key=_seed_key, reverse=True):
            if len(heats[0]) >= min_heat or len(heats[1]) <= min_heat:
                break
            if sum(1 for x in heats[0] if x["team"] == e["team"]) < len(own[e["team"]]):
                heats[1].remove(e)
                heats[0].append(e)
                moved += 1
    out = {}
    for hno, heat in enumerate(heats, 1):
        used = {}
        for e in sorted(heat, key=_seed_key):
            i = used.get(e["team"], 0)
            out[e["id"]] = (hno, own[e["team"]][i])
            used[e["team"]] = i + 1
    if stray:                            # never drop a swimmer: one extra heat, middle lanes
        hno = len(heats) + 1
        order = sorted(lanes, key=lambda l: (abs(l - center), l))
        for i, e in enumerate(stray[:len(order)]):
            out[e["id"]] = (hno, order[i])
    return out, {"heats": [len(h) for h in heats], "moved": moved,
                 "lone_before": len(heats) > 1 and len(heats[0]) - moved < min_heat, "strict": True}


def seed_meet(entries, removed, plan, min_heat=2, skip=(), strict=False):
    """Seed every event (individual and relay) not in skip. Returns ({id: (heat, lane)}, [per-event info])."""
    active = [e for e in entries if e["id"] not in removed and e["id"] not in skip]
    by_ev: dict[str, list] = {}
    for e in active:
        by_ev.setdefault(e["event_no"], []).append(e)
    lanes, info = {}, []
    for evn in sorted(by_ev, key=lambda x: int(x or 0)):
        res, inf = seed_event(by_ev[evn], plan, min_heat, strict)
        lanes.update(res)
        info.append({"event_no": evn, "event": by_ev[evn][0]["event"], "entries": len(by_ev[evn]), **inf})
    return lanes, info
