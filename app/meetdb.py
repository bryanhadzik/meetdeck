"""Read and change a Meet Manager 8 database through the mmdb service (mmdb/Svc.java).

Everything here works on Meet Manager's own tables, so the same file restores straight into
Meet Manager. Built to grow into running the whole meet (times, places, scoring)."""
import json
import os
import subprocess
import time
import urllib.request

SVC_PORT = int(os.environ.get("MMDB_PORT", "8765"))
# Windows: no Java - Windows' own Access driver through mdbjet. Server: the Jackcess service.
JET = os.name == "nt" or os.environ.get("MMDB_BACKEND") == "jet"
MMDB_DIR = os.environ.get("MMDB_DIR", "/opt/mmdb")
_proc = None

STROKE = {"A": "Free", "B": "Back", "C": "Breast", "D": "Fly", "E": "IM"}
GENDER = {"F": "Girls", "M": "Boys", "X": "Mixed", "W": "Women"}
STAT = {"": "", "Q": "DQ", "F": "DQ", "R": "NS", "S": "SCR", "D": "DQ"}
TABLES = ["Meet", "Team", "Athlete", "Event", "Session", "Sessitem", "Entry", "Relay", "RelayNames", "Scoring"]


# ---- service ----------------------------------------------------------------
def start():
    global _proc
    if JET:
        return
    if _proc and _proc.poll() is None:
        return
    import tempfile
    _proc = subprocess.Popen(["java", "-cp", f"{MMDB_DIR}/lib/*{os.pathsep}{MMDB_DIR}", "Svc", str(SVC_PORT)],
                             stdout=subprocess.DEVNULL, stderr=open(os.path.join(tempfile.gettempdir(), "mmdb-svc.log"), "a"))
    for _ in range(60):
        try:
            _call("/ping", {})
            return
        except Exception:
            time.sleep(0.25)


def _call(path, body, timeout=120):
    req = urllib.request.Request(f"http://127.0.0.1:{SVC_PORT}{path}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(json.loads(e.read() or b"{}").get("error", str(e)))


def call(path, body):
    try:
        return _call(path, body)
    except (ConnectionError, urllib.error.URLError):
        start()
        return _call(path, body)


def read(db, tables=None):
    if JET:
        import mdbjet
        return mdbjet.read(db, tables or TABLES)
    return call("/read", {"db": str(db), "tables": tables or TABLES})["tables"]


def apply(db, ops):
    if JET:
        import mdbjet
        return mdbjet.apply(db, ops)
    return call("/apply", {"db": str(db), "ops": ops})["results"]


def close(db):
    if JET:
        import mdbjet
        mdbjet.close(db)
        return
    try:
        call("/close", {"db": str(db)})
    except Exception:
        pass


# ---- model ------------------------------------------------------------------
def fmt_time(t):
    if not t:
        return ""
    m, s = divmod(round(float(t), 2), 60)
    return f"{int(m)}:{s:05.2f}" if m else f"{s:.2f}"


def parse_time(s):
    """Swim times typed any way: 1:05.32, 65.32, or just digits - 10532 = 1:05.32, 5632 = 56.32,
    105 = 1.05 (last two digits are hundredths, the two before are seconds, the rest minutes).
    1:05 with no hundredths = 1:05.00."""
    import re as _re
    s = str(s or "").strip().upper()
    if not s or s in ("NT", "0"):
        return 0.0
    if "." not in s:
        if ":" in s and _re.fullmatch(r"\d+:\d{1,2}", s):
            m, sec = s.split(":")
            if int(sec) >= 60:
                raise ValueError(f"'{s}': seconds must be under 60")
            return float(int(m) * 60 + int(sec))
        d = _re.sub(r"\D", "", s)
        if not d:
            raise ValueError(f"Can't read the time '{s}'")
        hund, sec, mins = int(d[-2:]), int(d[-4:-2] or 0), int(d[:-4] or 0)
        if mins and sec >= 60:
            raise ValueError(f"'{s}' reads as {mins}:{sec:02d}.{hund:02d} - seconds must be under 60")
        return round(mins * 60 + sec + hund / 100, 2)
    try:
        if ":" in s:
            m, sec = s.split(":", 1)
            return round(int(m) * 60 + float(sec), 2)
        return round(float(s), 2)
    except ValueError:
        raise ValueError(f"Can't read the time '{s}'")


def _s(v):
    return (v or "").strip() if isinstance(v, str) else ("" if v is None else v)


def load(db) -> dict:
    t = {k: v["rows"] for k, v in read(db).items()}
    meet = t["Meet"][0] if t.get("Meet") else {}
    teams = {r["Team_no"]: {"no": r["Team_no"], "abbr": _s(r["Team_abbr"]), "name": _s(r["Team_name"]),
                            "short": _s(r["Team_short"]), "lsc": _s(r.get("Team_lsc") or r.get("team_lsc")), "city": _s(r.get("Team_city")),
                            "state": _s(r.get("Team_statenew") or r.get("Team_state")), "zip": _s(r.get("Team_zip")),
                            "country": _s(r.get("Team_cntry")), "addr1": _s(r.get("Team_addr1")), "addr2": _s(r.get("Team_addr2")),
                            "head": _s(r.get("Team_head")), "asst": _s(r.get("Team_asst")), "day_tel": _s(r.get("Team_daytele")),
                            "eve_tel": _s(r.get("Team_evetele")), "cell": _s(r.get("Team_cell")), "fax": _s(r.get("Team_faxtele")),
                            "email": _s(r.get("Team_email"))} for r in t["Team"]}
    aths = {r["Ath_no"]: {"no": r["Ath_no"], "first": _s(r["First_name"]), "last": _s(r["Last_name"]),
                          "pref": _s(r.get("Pref_name")), "initial": _s(r.get("Initial")), "sex": _s(r["Ath_Sex"]),
                          "age": r.get("Ath_age") or 0, "yr": _s(r.get("Schl_yr")), "team": r["Team_no"],
                          "birth": (r.get("Birth_date") or "")[:10], "stat": _s(r.get("Ath_stat")),
                          "comp": r.get("Comp_no") or 0, "reg": _s(r.get("Reg_no")), "citizen": _s(r.get("Citizen_of"))} for r in t["Athlete"]}
    order = {}
    sess = {s["Sess_ptr"]: s for s in t.get("Session", [])}
    for it in t.get("Sessitem", []):
        s = sess.get(it["Sess_ptr"], {})
        order.setdefault(it["Event_ptr"], (s.get("Sess_no") or 0, it["Sess_order"] or 0, s.get("Sess_day") or 1))
    events = []
    for r in t["Event"]:
        ir = _s(r["Ind_rel"]) or "I"
        st = _s(r["Event_stroke"])
        stroke = ("Medley Relay" if st == "E" else f"{STROKE.get(st, st)} Relay") if ir == "R" else STROKE.get(st, st)
        g = _s(r["Event_gender"]) or _s(r["Event_sex"])
        events.append({"ptr": r["Event_ptr"], "no": r["Event_no"], "ltr": _s(r["Event_ltr"]), "ind_rel": ir,
                       "gender": g, "sex": _s(r["Event_sex"]), "dist": int(r["Event_dist"] or 0), "stroke": st, "rounds": r.get("Event_rounds") or 1,
                       "label": f"{GENDER.get(g, g)} {int(r['Event_dist'] or 0)} {stroke}",
                       "order": order.get(r["Event_ptr"], (99, r["Event_no"] or 0, 1))[:2],
                       "day": order.get(r["Event_ptr"], (0, 0, 1))[2],
                       "legs": r.get("Num_RelayLegs") or r.get("Relay_size") or 4})
    events.sort(key=lambda e: (e["order"], e["no"]))
    for e in events:
        e["order"] = list(e["order"])
    legs = {}
    for r in t["RelayNames"]:
        if _s(r.get("Event_round")) in ("", "F"):
            legs.setdefault(r["Relay_no"], {})[r["Pos_no"]] = r["Ath_no"]
    entries = []
    for r in t["Entry"]:
        entries.append(_entry(r, "I", f"E:{r['Event_ptr']}:{r['Ath_no']}", ath=r["Ath_no"],
                              team=aths.get(r["Ath_no"], {}).get("team")))
    for r in t["Relay"]:
        lg = legs.get(r["Relay_no"], {})
        entries.append(_entry(r, "R", f"R:{r['Relay_no']}", relay=r["Relay_no"], team=r["Team_no"],
                              ltr=_s(r["Team_ltr"]), legs=[lg.get(i) for i in range(1, 5)],
                              alts=[lg.get(i) for i in range(5, 9)], rel_sex=_s(r.get("Rel_sex"))))
    sessions = [{"ptr": s["Sess_ptr"], "no": s.get("Sess_no") or 0, "ltr": _s(s.get("Sess_ltr")), "name": _s(s.get("Sess_name")),
                 "day": s.get("Sess_day") or 1, "start": s.get("Sess_starttime") or 0, "interval": s.get("Sess_interval") or 0,
                 "back": s.get("Sess_backinterval") or 0, "course": _s(s.get("Sess_course")) or "Y",
                 "items": sorted(({"event": it["Event_ptr"], "order": it.get("Sess_order") or 0, "rnd": _s(it.get("Sess_rnd")) or "F",
                                   "delay": it.get("Delay_seconds") or 0, "delay_desc": _s(it.get("Delay_desc"))}
                                  for it in t.get("Sessitem", []) if it["Sess_ptr"] == s["Sess_ptr"]), key=lambda x: x["order"])}
                for s in sorted(t.get("Session", []), key=lambda s: (s.get("Sess_day") or 1, s.get("Sess_no") or 0))]
    return {"sessions": sessions, "meet": {"name": _s(meet.get("Meet_name1")), "start": (meet.get("Meet_start") or "")[:10],
                     "end": (meet.get("Meet_end") or "")[:10], "location": _s(meet.get("Meet_location")),
                     "calc_date": (meet.get("Calc_date") or "")[:10], "city": _s(meet.get("Meet_city")), "state": _s(meet.get("Meet_state")),
                     "zip": _s(meet.get("Meet_zip")), "country": _s(meet.get("Meet_country")), "addr1": _s(meet.get("Meet_addr1")), "addr2": _s(meet.get("Meet_addr2")),
                     "header1": _s(meet.get("Meet_header1")), "header2": _s(meet.get("Meet_header2")), "altitude": meet.get("Meet_altitude"), "idformat": meet.get("Meet_idformat") or 1,
                     "style": meet.get("meet_meetstyle") or 1, "course": meet.get("Meet_course") or 3, "mtype": meet.get("Meet_meettype") or 1,
                     "lanes": meet.get("meet_numlanes") or 8, "style": meet.get("meet_meetstyle") or 1,
                     "ind_max": meet.get("indmax_perath") or 0, "total_max": meet.get("entrymax_total") or 0,
                     "mm_scoring": {"ind_max": meet.get("indmaxscorers_perteam") or 0, "rel_max": meet.get("relmaxscorers_perteam") or 0,
                                    "fastest_heat": bool(meet.get("score_fastestheatonly"))}},
            "teams": teams, "athletes": aths, "events": events, "entries": entries}


def _entry(r, kind, key, **kw):
    return {"key": key, "kind": kind, "event": r["Event_ptr"], "seed": r.get("ActualSeed_time") or 0, "conv": r.get("ConvSeed_time") or 0,
            "seed_course": _s(r.get("ActSeed_course")) or "Y", "seed_crs": _s(r.get("ConvSeed_course")), "fin_course": _s(r.get("Fin_course")),
            "dq_official": r.get("fin_dqofficial"),
            "adj": None if r.get("fin_adjuststat") is None else _s(r.get("fin_adjuststat")), "scr": bool(r.get("Scr_stat")),
            "heat": r.get("Fin_heat") or 0, "lane": r.get("Fin_lane") or 0, "time": r.get("Fin_Time") or 0,
            "stat": _s(r.get("Fin_stat")), "dq": _s(r.get("Fin_dqcode")), "place": r.get("Fin_place") or 0,
            "heatplace": r.get("Fin_heatplace") or 0, "points": r.get("Ev_score") or 0,
            "dq2": _s(r.get("Fin_dqcodeSecond")),
            "exh": _s(r.get("Fin_exh")) == "X" or _s(r.get("Pre_exh")) == "X",
            "nonscoring": (r.get("Fin_ptsplace") or 0) == 999, "ptsplace": r.get("Fin_ptsplace") or 0,
            "backup": r.get("Fin_back1") or 0, "back2": r.get("Fin_back2") or 0, "back3": r.get("Fin_back3") or 0, "pad": r.get("Fin_pad") or 0, "watch": r.get("Fin_watch1") or 0, "watch2": r.get("Sem_watch1") or 0, **kw}


def json_safe(m: dict) -> dict:
    return {**m, "teams": {str(k): v for k, v in m["teams"].items()}, "athletes": {str(k): v for k, v in m["athletes"].items()}}


# ---- changes ----------------------------------------------------------------
def _match(e):
    return {"Event_ptr": e["event"], "Ath_no": e["ath"]} if e["kind"] == "I" else {"Relay_no": e["relay"]}


def _table(e):
    return "Entry" if e["kind"] == "I" else "Relay"


def find(m, key):
    for e in m["entries"]:
        if e["key"] == key:
            return e
    raise KeyError(f"entry {key} not found")


def who(m, e):
    if e["kind"] == "I":
        a = m["athletes"].get(e["ath"], {})
        return f"{a.get('first', '?')} {a.get('last', '')}"
    return f"{m['teams'].get(e['team'], {}).get('abbr', '?')} \"{e['ltr']}\" relay"


def ev_label(m, ptr):
    e = next((x for x in m["events"] if x["ptr"] == ptr), None)
    return f"#{e['no']} {e['label']}" if e else f"event {ptr}"


def op_scratch(m, key, on=True):
    e = find(m, key)
    s = {"Scr_stat": bool(on)}
    if on:
        s.update({"Fin_heat": 0, "Fin_lane": 0})
    return [{"op": "update", "table": _table(e), "match": _match(e), "set": s}], \
        f"{'Scratched' if on else 'Un-scratched'} {who(m, e)} in {ev_label(m, e['event'])}"


def op_scratch_athlete(m, ath, on=True):
    ops, n = [], 0
    for e in m["entries"]:
        if e["kind"] == "I" and e["ath"] == ath and e["scr"] != on:
            ops += op_scratch(m, e["key"], on)[0]
            n += 1
    removed = []
    if on:   # take them off relays too; the leg is left open for a replacement
        for e in m["entries"]:
            if e["kind"] == "R" and ath in e["legs"]:
                ops.append({"op": "delete", "table": "RelayNames", "match": {"Relay_no": e["relay"], "Ath_no": ath}})
                removed.append(ev_label(m, e["event"]))
    a = m["athletes"][ath]
    msg = f"{'Scratched' if on else 'Un-scratched'} {a['first']} {a['last']} from {n} event(s)"
    if removed:
        msg += f" and removed from relays in {', '.join(removed)}"
    return ops, msg


def op_move(m, key, heat, lane):
    e = find(m, key)
    heat, lane = int(heat), int(lane)
    ops = []
    other = next((x for x in m["entries"] if x["event"] == e["event"] and x["key"] != key and not x["scr"]
                  and x["heat"] == heat and x["lane"] == lane and heat and lane), None)
    if other:   # swap
        ops.append({"op": "update", "table": _table(other), "match": _match(other),
                    "set": {"Fin_heat": e["heat"], "Fin_lane": e["lane"]}})
    ops.append({"op": "update", "table": _table(e), "match": _match(e), "set": {"Fin_heat": heat, "Fin_lane": lane}})
    msg = f"Moved {who(m, e)} in {ev_label(m, e['event'])} to heat {heat} lane {lane}"
    if other:
        msg += f" (swapped with {who(m, other)})"
    return ops, msg


def op_seed(m, key, seed):
    e = find(m, key)
    t = parse_time(seed)
    return [{"op": "update", "table": _table(e), "match": _match(e),
             "set": {"ActualSeed_time": t, "ConvSeed_time": t, "ActSeed_course": "Y", "ConvSeed_course": "Y"}}], \
        f"Seed time for {who(m, e)} in {ev_label(m, e['event'])} set to {fmt_time(t) or 'NT'}"


def timers_time(t1, t2):
    """NFHS 6-4-1b for hand timing: two valid watch times are averaged with the thousandths dropped
    (no rounding); one valid time stands on its own."""
    h = [round(float(t) * 100) for t in (t1, t2) if t]
    if not h:
        return 0
    return (sum(h) // len(h)) / 100


def op_result(m, key, time_s=None, stat="", dq="", t1_s=None, t2_s=None):
    e = find(m, key)
    stat = (stat or "").upper()
    timers = t1_s is not None or t2_s is not None
    if timers:
        # two timers on the lane: keep both watch times; timer 2 goes in Sem_watch1, which Meet Manager
        # leaves unused for timed-final events
        t1 = parse_time(t1_s if t1_s is not None else (fmt_time(e.get("watch")) if e.get("watch") else ""))
        t2 = parse_time(t2_s if t2_s is not None else (fmt_time(e.get("watch2")) if e.get("watch2") else ""))
        t = timers_time(t1, t2)
    else:
        t = parse_time(time_s)
    s = {"Fin_Time": t, "Fin_stat": stat or " ", "Fin_dqcode": (dq or "").upper() or None, "Fin_course": "Y"}
    if timers:
        s.update({"Fin_watch1": t1 or 0, "Sem_watch1": t2 or 0})
    if stat in ("R", "F"):
        s["Fin_Time"] = 0
    e2 = {**e, "time": s["Fin_Time"], "stat": stat}
    import results          # Meet Manager's timing letter (A / K / blank), kept in fin_adjuststat
    s["fin_adjuststat"] = results.time_code({k: v for k, v in e2.items() if k != "adj"}) or " "
    ops = [{"op": "update", "table": _table(e), "match": _match(e), "set": s}]
    ops += places_ops(m, e["event"], override={key: e2})
    desc = {"Q": "DQ", "F": "DQ (no time)", "R": "No show", "": ""}.get(stat, stat)
    how = f" (timers {fmt_time(s['Fin_watch1']) or '-'} / {fmt_time(s['Sem_watch1']) or '-'})" if timers else ""
    return ops, f"Result for {who(m, e)} in {ev_label(m, e['event'])}: {fmt_time(s['Fin_Time']) or '-'}{how} {desc}".strip()


def places_ops(m, ptr, override=None):
    """Re-place an event from its finals times (ties share a place). Points are left to Meet Manager's scoring."""
    ents = [(override or {}).get(e["key"], e) for e in m["entries"] if e["event"] == ptr]
    ok = [e for e in ents if not e["scr"] and e["time"] and e["stat"] in ("", " ") and not e["exh"]]
    ok.sort(key=lambda e: e["time"])
    place, heatp, ops = {}, {}, []
    for i, e in enumerate(ok):
        prev = ok[i - 1] if i else None
        place[e["key"]] = place[prev["key"]] if prev and abs(prev["time"] - e["time"]) < 0.001 else i + 1
    for h in {e["heat"] for e in ok}:
        hs = [e for e in ok if e["heat"] == h]
        for i, e in enumerate(hs):
            prev = hs[i - 1] if i else None
            heatp[e["key"]] = heatp[prev["key"]] if prev and abs(prev["time"] - e["time"]) < 0.001 else i + 1
    for e in ents:
        p, hp = place.get(e["key"], 0), heatp.get(e["key"], 0)
        s = {"Fin_place": p, "Fin_heatplace": hp}
        if not p:
            s["Ev_score"] = 0
        if p != e["place"] or hp != e["heatplace"] or (not p and e["points"]):
            ops.append({"op": "update", "table": _table(e), "match": _match(e), "set": s})
    return ops


def op_heat_results(m, ptr, heat, lanes, overwrite=True):
    """Times from the timing console for one heat. lanes: [{lane, final, backup, place, splits:[...]}]
    (seconds). An entered lane with no time becomes a no-show; place -1 from the console = DQ."""
    ptr, heat = int(ptr), int(heat)
    ents = {e["lane"]: e for e in m["entries"] if e["event"] == ptr and e["heat"] == heat and not e["scr"] and e["lane"]}
    ops, override, done, ns, dq, skipped, used = [], {}, 0, [], [], [], []
    for ln in lanes:
        e = ents.get(int(ln["lane"]))
        if not e:
            continue
        if not overwrite and (e["time"] or (e["stat"] or "").strip()):
            skipped.append(e["lane"])
            continue
        pad, backup = float(ln.get("pad", ln.get("final")) or 0), float(ln.get("backup") or 0)
        w1, w2 = float(ln.get("watch") or 0), float(ln.get("watch2") or 0)
        watch = timers_time(w1, w2) if w1 and w2 else (w1 or w2)       # two watches: averaged, thousandths dropped
        use = ln.get("use") or "pad"
        final = {"pad": pad, "backup": backup, "watch": watch}.get(use, pad) or 0
        if use != "pad" and final:
            used.append(f"lane {e['lane']} {'backup button' if use == 'backup' else 'timers'}")
        stat = "R" if not final else ("Q" if int(ln.get("place") or 0) == -1 else "")
        # keep every time the console and the timers gave, so the official time can be changed later:
        # each button in Fin_back1-3 (the console's backup when it sent no buttons), both watches
        btns = [float(b) for b in (ln.get("buttons") or []) if b][:3] or ([backup] if backup else [])
        btns += [0] * (3 - len(btns))
        s = {"Fin_Time": final, "Fin_pad": pad, "Fin_back1": btns[0], "Fin_back2": btns[1], "Fin_back3": btns[2],
             "Fin_watch1": w1 or (w2 if not w1 else 0), "Sem_watch1": w2 if w1 else 0,
             "Fin_stat": stat or " ", "Fin_course": "Y"}
        ops.append({"op": "update", "table": _table(e), "match": _match(e), "set": s})
        override[e["key"]] = {**e, "time": final, "stat": stat}
        ops.append({"op": "delete", "table": "Split", "match": {**_match(e), "Rnd_ltr": "F"} if e["kind"] == "I" else {"Relay_no": e["relay"], "Rnd_ltr": "F"}})
        for i, t in enumerate(ln.get("splits") or [], 1):
            if t:
                row = {"Event_ptr": ptr, "Rnd_ltr": "F", "Split_no": i, "Split_Time": float(t), "Team_no": e["team"] or 0}
                row.update({"Ath_no": e["ath"]} if e["kind"] == "I" else {"Relay_no": e["relay"], "Team_ltr": e["ltr"]})
                ops.append({"op": "insert", "table": "Split", "row": row})
        done += 1
        (ns if stat == "R" else dq if stat == "Q" else []).append(e["lane"])
    if not done:
        raise ValueError("No entered lanes in that heat matched the console's lanes" + (" (all already have results)" if skipped else ""))
    ops += places_ops(m, ptr, override)
    msg = f"Console times for {ev_label(m, ptr)} heat {heat}: {done} lane(s)"
    if ns:
        msg += f", no-show lane {', '.join(map(str, ns))}"
    if dq:
        msg += f", DQ lane {', '.join(map(str, dq))}"
    if used:
        msg += "; used " + ", ".join(used)
    if skipped:
        msg += f" (kept existing results in lane {', '.join(map(str, skipped))})"
    return ops, msg


def op_dq(m, key, code, code2="", keep_time=True):
    """Disqualify an entry. keep_time: the swimmer finished and the time stays on record (Meet Manager 'Q');
    otherwise no official time ('F', e.g. a declared false start)."""
    import dqcodes
    e = find(m, key)
    code, code2 = (code or "").strip().upper(), (code2 or "").strip().upper()
    if code not in dqcodes.BY_CODE:
        raise ValueError(f"Unknown DQ code {code}")
    if code2 and code2 not in dqcodes.BY_CODE:
        raise ValueError(f"Unknown DQ code {code2}")
    keep = bool(keep_time) and bool(e["time"])
    stat = "Q" if keep else "F"
    s = {"Fin_stat": stat, "Fin_dqcode": code, "Fin_dqcodeSecond": code2 or None, "dq_type": None}
    if not keep:
        s["Fin_Time"] = 0
    ops = [{"op": "update", "table": _table(e), "match": _match(e), "set": s}]
    ops += places_ops(m, e["event"], override={key: {**e, "stat": stat, "time": e["time"] if keep else 0}})
    ev = next((x for x in m["events"] if x["ptr"] == e["event"]), {})
    desc = dqcodes.describe(code, ev.get("stroke", ""), e["kind"] == "R")
    msg = f"DQ {who(m, e)} in {ev_label(m, e['event'])}: {code} {desc}"
    if code2:
        msg += f" + {code2} {dqcodes.describe(code2, ev.get('stroke', ''), True)}"
    return ops, msg + ("" if keep else " (no time)")


def op_undq(m, key):
    e = find(m, key)
    s = {"Fin_stat": " ", "Fin_dqcode": None, "Fin_dqcodeSecond": None}
    ops = [{"op": "update", "table": _table(e), "match": _match(e), "set": s}]
    ops += places_ops(m, e["event"], override={key: {**e, "stat": ""}})
    return ops, f"Removed DQ for {who(m, e)} in {ev_label(m, e['event'])}" + ("" if e["time"] else " (no time on record - enter it)")


def op_delete(m, key):
    e = find(m, key)
    ops = [{"op": "delete", "table": _table(e), "match": _match(e)}]
    if e["kind"] == "R":
        ops.append({"op": "delete", "table": "RelayNames", "match": {"Relay_no": e["relay"]}})
    return ops, f"Deleted {who(m, e)} from {ev_label(m, e['event'])}"


def op_add_entry(m, ptr, ath=None, team=None, ltr=None, seed="", heat=0, lane=0):
    ev = next(x for x in m["events"] if x["ptr"] == ptr)
    t = parse_time(seed)
    base = {"Event_ptr": ptr, "ActualSeed_time": t, "ConvSeed_time": t, "ActSeed_course": "Y", "ConvSeed_course": "Y",
            "Fin_heat": int(heat or 0), "Fin_lane": int(lane or 0)}
    if ev["ind_rel"] == "R":
        team = int(team)
        if any(e["event"] == ptr and e["kind"] == "R" and e["team"] == team and e["ltr"] == ltr for e in m["entries"]):
            raise ValueError("That team already has that relay letter in this event")
        row = {**base, "Team_no": team, "Team_ltr": ltr or "A", "Rel_sex": ev["gender"]}
        return [{"op": "insert", "table": "Relay", "row": row}], \
            f"Added {m['teams'][team]['abbr']} \"{ltr}\" relay to {ev_label(m, ptr)}"
    ath = int(ath)
    if any(e["event"] == ptr and e["kind"] == "I" and e["ath"] == ath for e in m["entries"]):
        raise ValueError("That swimmer is already entered in this event")
    a = m["athletes"][ath]
    row = {**base, "Ath_no": ath, "event_age": a.get("age") or 0}
    return [{"op": "insert", "table": "Entry", "row": row}], f"Entered {a['first']} {a['last']} in {ev_label(m, ptr)}"


def op_athlete(m, ath, fields):
    a = m["athletes"][int(ath)]
    cols = {"first": "First_name", "last": "Last_name", "pref": "Pref_name", "sex": "Ath_Sex", "age": "Ath_age",
            "yr": "Schl_yr", "team": "Team_no", "initial": "Initial"}
    s = {cols[k]: (int(v) if k in ("age", "team") else v) for k, v in fields.items() if k in cols}
    return [{"op": "update", "table": "Athlete", "match": {"Ath_no": int(ath)}, "set": s}], \
        f"Updated {a['first']} {a['last']}: " + ", ".join(f"{k} → {v}" for k, v in fields.items())


def op_add_athlete(m, fields):
    row = {"First_name": fields["first"], "Last_name": fields["last"], "Ath_Sex": fields.get("sex", "F"),
           "Team_no": int(fields["team"]), "Ath_age": int(fields.get("age") or 0), "Schl_yr": fields.get("yr") or None,
           "Pref_name": fields.get("pref") or None,
           "Comp_no": max([a.get("comp") or 0 for a in m["athletes"].values()] + [0]) + 1}
    return [{"op": "insert", "table": "Athlete", "row": row}], f"Added swimmer {fields['first']} {fields['last']}"


def op_team(m, team, fields):
    cols = {"name": "Team_name", "short": "Team_short", "abbr": "Team_abbr"}
    s = {cols[k]: v for k, v in fields.items() if k in cols}
    return [{"op": "update", "table": "Team", "match": {"Team_no": int(team)}, "set": s}], \
        f"Updated team {m['teams'][int(team)]['abbr']}: " + ", ".join(f"{k} → {v}" for k, v in fields.items())


# meet header: our key -> (Meet column, kind, max length / range)
MEET_FIELDS = {"name": ("Meet_name1", "text", 45), "location": ("Meet_location", "text", 45),
               "header1": ("Meet_header1", "text", 75), "header2": ("Meet_header2", "text", 75),
               "start": ("Meet_start", "date", 0), "end": ("Meet_end", "date", 0), "calc_date": ("Calc_date", "date", 0),
               "addr1": ("Meet_addr1", "text", 30), "addr2": ("Meet_addr2", "text", 30), "city": ("Meet_city", "text", 30),
               "state": ("Meet_state", "text", 3), "zip": ("Meet_zip", "text", 10), "country": ("Meet_country", "text", 3),
               "altitude": ("Meet_altitude", "int", (0, 15000)), "course": ("Meet_course", "int", (1, 3)),
               "lanes": ("meet_numlanes", "int", (1, 10))}
MEET_LABELS = {"name": "name", "location": "location", "header1": "header line 1", "header2": "header line 2",
               "start": "start date", "end": "end date", "calc_date": "age-up date", "addr1": "address", "addr2": "address line 2",
               "city": "city", "state": "state", "zip": "zip", "country": "country", "altitude": "altitude",
               "course": "course", "lanes": "lanes"}


def op_meet(m, fields):
    import datetime as _dt
    s, said = {}, []
    for k, v in fields.items():
        if k not in MEET_FIELDS:
            raise ValueError(f"unknown meet field {k}")
        col, kind, lim = MEET_FIELDS[k]
        v = ("" if v is None else str(v)).strip()
        if kind == "text":
            if k == "name" and not v:
                raise ValueError("The meet needs a name")
            v = v[:lim]
            s[col] = v if v else " "          # Meet Manager keeps blank text fields as a single space
        elif kind == "date":
            try:
                _dt.date.fromisoformat(v)
            except ValueError:
                raise ValueError(f"{MEET_LABELS[k]} must be a date")
            s[col] = v
        else:
            try:
                n = int(float(v or 0))
            except ValueError:
                raise ValueError(f"{MEET_LABELS[k]} must be a number")
            if not lim[0] <= n <= lim[1]:
                raise ValueError(f"{MEET_LABELS[k]} must be {lim[0]}-{lim[1]}")
            s[col] = n
        shown = {"course": {1: "LCM", 2: "SCM", 3: "SCY"}}.get(k, {}).get(s[col], s[col]) if kind == "int" else v
        said.append(f"{MEET_LABELS[k]} → {shown or '(blank)'}")
    st = s.get("Meet_start", m["meet"]["start"])
    en = s.get("Meet_end", m["meet"]["end"] or st)
    if st and en and en < st:
        if "Meet_end" in s:
            raise ValueError("The end date is before the start date")
        s["Meet_end"] = st                    # moving the start past the end drags the end along
    if not s:
        return [], ""
    return [{"op": "update", "table": "Meet", "set": s}], "Meet header: " + ", ".join(said)


def op_legs(m, key, legs):
    e = find(m, key)
    ops = [{"op": "delete", "table": "RelayNames", "match": {"Relay_no": e["relay"]}}]
    names = []
    for pos, ath in enumerate(legs, 1):
        if ath:
            ops.append({"op": "insert", "table": "RelayNames",
                        "row": {"Event_ptr": e["event"], "Team_no": e["team"], "Team_ltr": e["ltr"], "Ath_no": int(ath),
                                "Pos_no": pos, "Event_round": "F", "Relay_no": e["relay"]}})
            a = m["athletes"].get(int(ath), {})
            names.append(f"{a.get('first', '?')} {a.get('last', '')}")
    return ops, f"Relay legs for {who(m, e)} in {ev_label(m, e['event'])}: {', '.join(names) or 'none'}"


def check(m) -> list:
    """Problems in the database as it stands (lane clashes, over-entered swimmers)."""
    out = []
    seen = {}
    for e in m["entries"]:
        if e["scr"] or not e["heat"] or not e["lane"]:
            continue
        k = (e["event"], e["heat"], e["lane"])
        if k in seen:
            out.append(f"{ev_label(m, e['event'])}: heat {e['heat']} lane {e['lane']} has {who(m, seen[k])} and {who(m, e)}")
        seen[k] = e
    count = {}
    for e in m["entries"]:
        if e["scr"]:
            continue
        ids = [e["ath"]] if e["kind"] == "I" else [x for x in e["legs"] if x]
        for a in ids:
            c = count.setdefault(a, [0, 0])
            c[0] += e["kind"] == "I"
            c[1] += 1
    mi, mt = m["meet"]["ind_max"] or 2, m["meet"]["total_max"] or 4
    for a, (i, tot) in count.items():
        if i > mi or tot > mt:
            at = m["athletes"].get(a, {})
            out.append(f"{at.get('first', '?')} {at.get('last', '')}: {i} individual / {tot} total events (max {mi} / {mt})")
    return out


# ---- scoring (NFHS Rule 9 tables, used by UHSAA) ------------------------------
CHAMP16 = [20, 17, 16, 15, 14, 13, 12, 11, 9, 7, 6, 5, 4, 3, 2, 1]
SCORING = {
    "dual3": {"name": "Dual meet, 3 entries per team (6-4-3-2-1 / 8-4-2)", "ind": [6, 4, 3, 2, 1], "rel": [8, 4, 2], "ind_max": 3, "rel_max": 2},
    "dual2": {"name": "Dual meet, 2 entries per team (4-3-1 / 6-3-1)", "ind": [4, 3, 1], "rel": [6, 3, 1], "ind_max": 2, "rel_max": 1},
    "dual4": {"name": "Dual meet, 4 entries per team (8-6-5-4-3-2-1 / 10-5-3)", "ind": [8, 6, 5, 4, 3, 2, 1], "rel": [10, 5, 3], "ind_max": 4, "rel_max": 2},
    "tri": {"name": "Triangular meet (7-5-4-3-2-1 / 14-10-8-6-4-2)", "ind": [7, 5, 4, 3, 2, 1], "rel": [14, 10, 8, 6, 4, 2], "ind_max": 2, "rel_max": 2},
    "champ": {"name": "Championship / invitational, 16 places (20-17-16...1, relays double)", "ind": CHAMP16, "rel": [p * 2 for p in CHAMP16], "ind_max": 4, "rel_max": 1},
    "doubledual": {"name": "Double / triple dual - each pair of teams scored as a dual meet (6-4-3-2-1 / 8-4-2)", "ind": [6, 4, 3, 2, 1], "rel": [8, 4, 2], "ind_max": 3, "rel_max": 2, "pairs": True},
}


def default_scoring(m, kind: str = "dual") -> str:
    """Regular season: 2 teams = dual meet, 3 teams = double dual (each pair scored as a dual meet).
    Invitational / championship (or 4+ teams): championship scoring."""
    if kind in ("invitational", "championship"):
        return "champ"
    n = len({e["team"] for e in m["entries"] if not e["scr"]})
    return "dual3" if n <= 2 else "doubledual" if n == 3 else "champ"


def event_sig(m, ptr) -> str:
    import hashlib
    rows = sorted((e["key"], round(e["time"] or 0, 2), (e["stat"] or "").strip(), e["scr"], e["exh"], e["dq"])
                  for e in m["entries"] if e["event"] == ptr)
    return hashlib.md5(repr(rows).encode()).hexdigest()[:12]


def _eligible(e):
    return not e["scr"] and e["time"] and (e["stat"] or "").strip() == "" and not e["exh"]


def _score_list(ents, table, team_max):
    """-> {key: (points, ptsplace)} for one event. Over-limit swimmers get ptsplace 999 (non-scoring)."""
    out = {e["key"]: (0, 0) for e in ents}
    cands = sorted((e for e in ents if _eligible(e)), key=lambda e: e["time"])
    count, scorers = {}, []
    for e in cands:
        if team_max and count.get(e["team"], 0) >= team_max:
            out[e["key"]] = (0, 999)
            continue
        count[e["team"]] = count.get(e["team"], 0) + 1
        scorers.append(e)
    i = 0
    while i < len(scorers):
        j = i
        while j + 1 < len(scorers) and abs(scorers[j + 1]["time"] - scorers[i]["time"]) < 0.001:
            j += 1
        pts = [table[k] if k < len(table) else 0 for k in range(i, j + 1)]
        share = round(sum(pts) / len(pts), 2)
        for k in range(i, j + 1):
            out[scorers[k]["key"]] = (share if share else 0, 0)
        i = j + 1
    return out


def score_events(m, method, ind_max, rel_max, targets=None, only_timed=True, fastest=False):
    """Score the given events (default: all). -> (ops, scored_ptrs, skipped, sigs).
    fastest: only the fastest (last) heat scores, like Meet Manager's "score fastest heat only"."""
    cfg = SCORING[method]
    ops, scored, skipped, sigs = [], [], [], {}
    for v in m["events"]:
        if targets is not None and v["ptr"] not in targets:
            continue
        ents = [e for e in m["entries"] if e["event"] == v["ptr"]]
        act = [e for e in ents if not e["scr"] and e["heat"]]
        if not act:
            continue
        unresolved = [e for e in act if not (e["time"] or (e["stat"] or "").strip() in ("Q", "F", "D", "R"))]
        if only_timed and unresolved:
            skipped.append(f"#{v['no']} {v['label']} ({len(unresolved)} lane(s) without a result)")
            continue
        table = cfg["rel"] if v["ind_rel"] == "R" else cfg["ind"]
        tmax = rel_max if v["ind_rel"] == "R" else ind_max
        pool = ents
        if fastest:
            top = max(e["heat"] for e in act)
            pool = [e for e in ents if e["heat"] == top]
        res = {e["key"]: (0, 0) for e in ents} if cfg.get("pairs") else {**{e["key"]: (0, 0) for e in ents}, **_score_list(pool, table, tmax)}
        for e in ents:
            pts, pp = res.get(e["key"], (0, 0))
            if abs((e["points"] or 0) - pts) > 0.001 or (e["ptsplace"] or 0) != pp:
                ops.append({"op": "update", "table": _table(e), "match": _match(e), "set": {"Ev_score": pts, "Fin_ptsplace": pp}})
        scored.append(v["ptr"])
        sigs[str(v["ptr"])] = event_sig(m, v["ptr"])
    return ops, scored, skipped, sigs


def score_totals(m, summary) -> dict:
    """Team totals over the scored events (from the points in the database), and dual results per pair."""
    cfg = SCORING[summary["method"]]
    gender_of = {v["ptr"]: ("F" if v["gender"] in ("F", "W") else v["gender"]) for v in m["events"]}
    done = set(summary["events"])
    teams = {}
    for e in m["entries"]:
        if e["event"] in done and e["points"]:
            t = teams.setdefault(str(e["team"]), {"F": 0, "M": 0, "X": 0, "total": 0})
            g = gender_of.get(e["event"]) if gender_of.get(e["event"]) in ("F", "M") else "X"
            t[g] = round(t[g] + e["points"], 2)
            t["total"] = round(t["total"] + e["points"], 2)
    pairs = []
    if cfg.get("pairs"):
        all_teams = sorted({e["team"] for e in m["entries"] if not e["scr"]})
        for i, a in enumerate(all_teams):
            for b in all_teams[i + 1:]:
                tot = {a: {"F": 0, "M": 0}, b: {"F": 0, "M": 0}}
                for v in m["events"]:
                    if v["ptr"] not in done:
                        continue
                    ents = [e for e in m["entries"] if e["event"] == v["ptr"] and e["team"] in (a, b)]
                    table = cfg["rel"] if v["ind_rel"] == "R" else cfg["ind"]
                    res = _score_list(ents, table, summary["rel_max"] if v["ind_rel"] == "R" else summary["ind_max"])
                    g = "F" if gender_of[v["ptr"]] == "F" else "M"
                    for e in ents:
                        tot[e["team"]][g] = round(tot[e["team"]][g] + res[e["key"]][0], 2)
                pairs.append({"a": a, "b": b, "a_pts": tot[a], "b_pts": tot[b]})
    return {"teams": teams, "pairs": pairs}


def score_meet(m, method="champ", ind_max=None, rel_max=None, only_timed=True, fastest=False):
    """Whole-meet scoring in one go (kept for scripts/tests)."""
    cfg = SCORING[method]
    ind_max = cfg["ind_max"] if ind_max is None else int(ind_max)
    rel_max = cfg["rel_max"] if rel_max is None else int(rel_max)
    ops, scored, skipped, sigs = score_events(m, method, ind_max, rel_max, None, only_timed, fastest)
    summary = {"method": method, "method_name": cfg["name"], "ind_max": ind_max, "rel_max": rel_max,
               "events": scored, "skipped": skipped, "sigs": sigs, "when": time.strftime("%Y-%m-%d %H:%M")}
    # totals as they will be after the ops are applied
    pts = {}
    for o in ops:
        mt = o["match"]
        k = f"E:{mt['Event_ptr']}:{mt['Ath_no']}" if "Ath_no" in mt else f"R:{mt['Relay_no']}"
        pts[k] = o["set"]["Ev_score"]
    m2 = {**m, "entries": [{**e, "points": pts.get(e["key"], e["points"])} for e in m["entries"]]}
    summary.update(score_totals(m2, summary))
    msg = f"Scored {len(scored)} event(s) - {cfg['name'].split(' (')[0]}" + (f"; skipped {len(skipped)} not fully timed" if skipped else "")
    return ops, msg, summary


def race_numbers(m: dict, overrides: dict | None = None) -> dict:
    """Console race number for every heat ('ptr:heat' -> n): counts up in event order, one per heat.
    A heat given its own number restarts the count from there for the heats after it."""
    overrides = {k: int(v) for k, v in (overrides or {}).items() if v}
    out, n = {}, 0
    for v in sorted(m["events"], key=lambda v: (v.get("order") or (99, v["no"]), v["no"])):
        heats = sorted({e["heat"] for e in m["entries"] if e["event"] == v["ptr"] and not e["scr"] and e.get("heat")})
        for h in heats:
            k = f"{v['ptr']}:{h}"
            n = overrides.get(k, n + 1)
            out[k] = n
    return out
