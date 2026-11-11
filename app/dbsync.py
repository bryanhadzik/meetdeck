"""Keep a meet database built from the team entries in step with later changes to those entries.

The database is a copy made when it was built ("built from the team entries"). Coaches' files keep
changing afterwards (new files, removed entries, relay swimmers), and Changes at the table also edits
the database directly. So the sync only carries over what changed in the *entries* since the last
sync (a baseline kept in the database's info.json), never undoing changes made at the table:
  - an entry added in the files       -> added to the database (the swimmer too, if they're new)
  - an entry removed from the files   -> scratched in the database (only if it has no result yet)
  - a relay's swimmers changed        -> the database relay gets the new swimmers
Without a baseline (databases built before this existed) only additions are carried over.
"""
from __future__ import annotations

import meetdb


def _who(sw: dict, key: str) -> str:
    s = sw.get(key) or {}
    return "%s|%s" % ((s.get("last") or "").strip().lower(), (s.get("first") or "").strip().lower())


def entry_sigs(st: dict) -> dict:
    """{"ind": {sig: {...}}, "rel": {sig: {...}}} for the active entries in the files."""
    sw = st["swimmers"]
    ind, rel = {}, {}
    for e in st["entries"]:
        if e.get("removed"):
            continue
        if e["kind"] == "ind":
            if not e["swimmers"]:
                continue
            k = e["swimmers"][0]
            ind["%s|%s" % (e["event_no"], _who(sw, k))] = {"event_no": str(e["event_no"]), "swimmer": k, "seed": e.get("seed") or 0}
        else:
            legs = e.get("legs") or {}
            lk = [legs.get(i) or legs.get(str(i)) or "" for i in range(1, 5)]
            rel["%s|%s|%s" % (e["event_no"], e["team"], e.get("relay") or "A")] = {
                "event_no": str(e["event_no"]), "team": e["team"], "ltr": e.get("relay") or "A", "seed": e.get("seed") or 0,
                "legs": [_who(sw, k) if k else "" for k in lk], "leg_keys": lk}
    return {"ind": ind, "rel": rel}


def baseline(sigs: dict) -> dict:
    return {"ind": sorted(sigs["ind"]), "rel": {k: v["legs"] for k, v in sigs["rel"].items()}}


def plan(st: dict, m: dict, base: dict | None) -> dict:
    """What to change in the database: {"add_ath": [...], "add_ind": [...], "scr": [keys], "add_rel": [...], "legs": [...]}"""
    sigs = entry_sigs(st)
    sw = st["swimmers"]
    evno = lambda v: f"{v['no']}{v.get('ltr') or ''}"
    ptr = {evno(v): v["ptr"] for v in m["events"]}
    ath = {}
    for no, a in m["athletes"].items():
        ath.setdefault("%s|%s" % ((a["last"] or "").strip().lower(), (a["first"] or "").strip().lower()), no)
    team_no = {}
    for no, t in m["teams"].items():
        team_no.setdefault(t["abbr"], no)
        team_no.setdefault(f"{t['abbr']}{no}", no)
    db_ind = {(e["event"], e["ath"]): e for e in m["entries"] if e["kind"] == "I"}
    db_rel = {(e["event"], e["team"], e["ltr"] or "A"): e for e in m["entries"] if e["kind"] == "R"}
    out = {"add_ath": [], "add_ind": [], "scr": [], "add_rel": [], "legs": [], "skipped": []}
    base_ind = set(base["ind"]) if base else None
    base_rel = base["rel"] if base else None

    def need_ath(key):
        w = _who(sw, key)
        if w in ath or w in [x["who"] for x in out["add_ath"]]:
            return
        s = sw.get(key) or {}
        t = team_no.get(s.get("team"))
        if t is None:
            out["skipped"].append(f"{s.get('first')} {s.get('last')}: team {s.get('team')} isn't in the meet database")
            return
        out["add_ath"].append({"who": w, "first": s.get("first", ""), "last": s.get("last", ""), "sex": "F" if s.get("gender") == "F" else "M",
                               "team": t, "age": s.get("age") or 0, "yr": s.get("class") or "", "pref": s.get("pref") or ""})

    # individual entries added in the files (all of them when there's no baseline)
    for sig, x in sigs["ind"].items():
        if base_ind is not None and sig in base_ind:
            continue
        p = ptr.get(x["event_no"])
        if p is None:
            out["skipped"].append(f"event {x['event_no']} isn't in the meet database")
            continue
        a = ath.get(_who(sw, x["swimmer"]))
        e = db_ind.get((p, a)) if a is not None else None
        if e and not e["scr"]:
            continue
        if e and e["scr"]:
            if base_ind is not None:        # re-entered in the files since the last sync; without a baseline a
                out["scr"].append((e["key"], False))   # scratch in the database may be a change made at the table
            continue
        if a is None:
            need_ath(x["swimmer"])
        out["add_ind"].append({"ptr": p, "who": _who(sw, x["swimmer"]), "seed": x["seed"]})
    # relays added, or whose swimmers changed
    for sig, x in sigs["rel"].items():
        p, t = ptr.get(x["event_no"]), team_no.get(x["team"])
        if p is None or t is None:
            out["skipped"].append(f"relay {x['event_no']} {x['team']} {x['ltr']}: not in the meet database")
            continue
        e = db_rel.get((p, t, x["ltr"]))
        new = base_rel is None and e is None or (base_rel is not None and sig not in base_rel)
        changed = base_rel is not None and sig in base_rel and base_rel[sig] != x["legs"]
        for k in x["leg_keys"]:
            if k and (new or changed) and _who(sw, k) not in ath:
                need_ath(k)
        if e is None and (new or changed):
            out["add_rel"].append({"ptr": p, "team": t, "ltr": x["ltr"], "seed": x["seed"], "legs": x["legs"]})
        elif e is not None and (new or changed):
            if e["scr"]:
                out["scr"].append((e["key"], False))
            out["legs"].append({"ptr": p, "team": t, "ltr": x["ltr"], "legs": x["legs"]})
    # removed from the files since the last sync
    if base_ind is not None:
        for sig in base_ind - set(sigs["ind"]):
            no, who = sig.split("|", 1)
            p, a = ptr.get(no), ath.get(who)
            e = db_ind.get((p, a))
            if e and not e["scr"] and not (e["time"] or (e["stat"] or "").strip()):
                out["scr"].append((e["key"], True))
    if base_rel is not None:
        for sig in set(base_rel) - set(sigs["rel"]):
            no, team, ltr = sig.split("|", 2)
            e = db_rel.get((ptr.get(no), team_no.get(team), ltr))
            if e and not e["scr"] and not (e["time"] or (e["stat"] or "").strip()):
                out["scr"].append((e["key"], True))
    return out


def count(p: dict) -> int:
    return len(p["add_ind"]) + len(p["scr"]) + len(p["add_rel"]) + len(p["legs"])


def apply(db, p: dict) -> list[str]:
    """Carry the plan into the database (athletes first, then entries, then relay swimmers). Returns what changed."""
    done = []
    m = meetdb.load(db)
    if p["add_ath"]:
        ops = []
        for a in p["add_ath"]:
            o, _ = meetdb.op_add_athlete(m, a)
            ops += o
        meetdb.apply(db, ops)
        done.append(f"{len(p['add_ath'])} new swimmer(s)")
        m = meetdb.load(db)
    ath = {}
    for no, a in m["athletes"].items():
        ath.setdefault("%s|%s" % ((a["last"] or "").strip().lower(), (a["first"] or "").strip().lower()), no)
    ops, n_add, n_scr, n_unscr = [], 0, 0, 0
    for x in p["add_ind"]:
        a = ath.get(x["who"])
        if a is None:
            continue
        o, _ = meetdb.op_add_entry(m, x["ptr"], ath=a, seed=meetdb.fmt_time(x["seed"]) if x["seed"] else "")
        ops += o
        n_add += 1
    for key, on in p["scr"]:
        o, _ = meetdb.op_scratch(m, key, on)
        ops += o
        n_scr += on
        n_unscr += not on
    for x in p["add_rel"]:
        taken = {e["ltr"] for e in m["entries"] if e["kind"] == "R" and e["event"] == x["ptr"] and e["team"] == x["team"]}
        ltr = x["ltr"] if x["ltr"] not in taken else next((c for c in "ABCDEFGH" if c not in taken), None)
        if not ltr:
            continue
        o, _ = meetdb.op_add_entry(m, x["ptr"], team=x["team"], ltr=ltr,
                                   seed=meetdb.fmt_time(x["seed"]) if x["seed"] else "")
        ops += o
        x["ltr"] = ltr
        n_add += 1
    if ops:
        meetdb.apply(db, ops)
        m = meetdb.load(db)
    if n_add:
        done.append(f"{n_add} entr{'y' if n_add == 1 else 'ies'} added")
    if n_scr:
        done.append(f"{n_scr} scratched")
    if n_unscr:
        done.append(f"{n_unscr} put back")
    ops, n_legs = [], 0
    for x in p["add_rel"] + p["legs"]:
        if not any(x["legs"]):
            continue
        e = next((e for e in m["entries"] if e["kind"] == "R" and e["event"] == x["ptr"] and e["team"] == x["team"]
                  and (e["ltr"] or "A") == x["ltr"]), None)
        if not e:
            continue
        o, _ = meetdb.op_legs(m, e["key"], [ath.get(w) if w else None for w in x["legs"]])
        ops += o
        n_legs += 1
    if ops:
        meetdb.apply(db, ops)
        done.append(f"swimmers on {n_legs} relay(s)")
    return done
