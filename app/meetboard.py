"""Start lists for the pool's meet-board (github.com/bryanhadzik/meet-board).

meet-board shows the heat in the water and the next heat on the spectator TVs and the
stream overlay. It can read Meet Manager's CTS .scb start lists, but those carry no relay
swimmers; this sends the same start lists straight from the meet database, with each
relay's swimmers (last names, in leg order).

The document is meet-board's "meetdeck-startlist" format (meet-board startlist_json.py),
posted to <meet-board>/api/startlists.
"""
import json
import re
import urllib.error
import urllib.request

FORMAT = "meetdeck-startlist"


def normalize_url(u: str) -> str:
    """'192.168.8.243' / '192.168.8.243:5000' / 'http://pc:5000/web/meetboard' -> 'http://host:port'."""
    u = (u or "").strip()
    if not u:
        return ""
    if not re.match(r"^https?://", u, re.I):
        u = "http://" + u
    m = re.match(r"^(https?://[^/\s?#]+)", u, re.I)
    if not m:
        raise ValueError("That doesn't look like an address, e.g. http://192.168.8.243:5000")
    base = m.group(1)
    host = base.split("://", 1)[1]
    if ":" not in host.split("]")[-1]:
        base += ":5000"                       # meet-board's own port
    return base


def startlist(m: dict, source: str = "MeetDeck", store=None) -> dict:
    """The meet's start lists from a meetdb.load() model. Scratched and unseeded entries are left out."""
    teams, aths = m["teams"], m["athletes"]
    course = "Y"
    for s in m.get("sessions") or []:
        course = (s.get("course") or "Y")[:1].upper()
        break
    used_teams = set()
    events = []
    import public_results
    for v in m["events"]:                     # already in session order
        heats = {}
        k = public_results._ev_key(v) if store else None
        classes = []
        for e in m["entries"]:
            if e["event"] != v["ptr"] or e["scr"] or not e.get("heat") or not e.get("lane"):
                continue
            t = teams.get(e.get("team")) or {}
            code = t.get("abbr", "")
            used_teams.add(e.get("team"))
            lane = {"lane": int(e["lane"]), "team": code, "seed": round(float(e["seed"]), 2) if e.get("seed") else None}
            if e["kind"] == "R":
                lane["letter"] = e.get("ltr", "")
                lane["legs"] = [(aths.get(a) or {}).get("last", "") for a in (e.get("legs") or []) if a]
                lane["legs"] = [x for x in lane["legs"] if x]
            else:
                a = aths.get(e.get("ath")) or {}
                lane.update({"first": a.get("pref") or a.get("first", ""), "last": a.get("last", ""),
                             "age": a.get("age") or 0, "sex": a.get("sex", "")})
                if e.get("exh"):
                    lane["exhibition"] = True
            if k:
                if e["kind"] == "R":
                    st = store.standing(k, t.get("name", "")) if (e.get("ltr") or "A") == "A" else {"cls": store.school_class(t.get("name", ""))}
                else:
                    a = aths.get(e.get("ath")) or {}
                    st = store.standing(k, t.get("name", ""), a.get("last", ""), a.get("first") or a.get("pref", ""))
                if st and st.get("cls"):
                    if st["cls"] not in classes:
                        classes.append(st["cls"])
                    if st.get("rank"):
                        lane["state"] = {"cls": st["cls"], "rank": st["rank"], "sb": st["sb"], "sb_date": st.get("sb_date", "")}
            heats.setdefault(int(e["heat"]), []).append(lane)
        if not heats:
            continue
        events.append({
            "number": v["no"], "gender": v.get("gender") or v.get("sex") or "", "distance": v.get("dist") or 0,
            "stroke": v.get("stroke", ""), "relay": v.get("ind_rel") == "R", "course": course,
            "heats": [{"heat": h, "lanes": sorted(ls, key=lambda x: x["lane"])} for h, ls in sorted(heats.items())],
        })
        if k and classes:
            # this season's state line / #1 / record per class swimming the event (utahswimcoach.com)
            events[-1]["state_now"] = [x for x in (store.event_line(k, c) for c in classes) if x]
    meet = m.get("meet") or {}
    return {
        "format": FORMAT, "version": 1, "source": source,
        "meet": {"name": meet.get("name", ""), "facility": meet.get("location", ""), "date": meet.get("start", ""),
                 "start": meet.get("start_time", "")},
        "teams": {(teams.get(t) or {}).get("abbr", ""): (teams.get(t) or {}).get("name", "")
                  for t in used_teams if (teams.get(t) or {}).get("abbr")},
        "events": events,
        **({"state_src": {"name": "utahswimcoach.com", "season": store.data.get("season", ""), "as_of": store.data.get("fetched_at", "")}}
           if store and store.data else {}),
    }


def summary(doc: dict) -> dict:
    heats = sum(len(e["heats"]) for e in doc["events"])
    relays = [ln for e in doc["events"] if e["relay"] for h in e["heats"] for ln in h["lanes"]]
    return {"events": len(doc["events"]), "heats": heats, "relays": len(relays),
            "relays_with_swimmers": sum(1 for r in relays if r.get("legs"))}


def _req(url, data=None, timeout=8):
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        if e.code == 404:
            body.setdefault("error", "this meet-board is too old to take start lists from MeetDeck - update it")
        return e.code, body


def ping(base: str) -> dict:
    """What the meet-board says about itself. Raises OSError if it can't be reached."""
    code, body = _req(base + "/api/startlists")
    if code != 200:
        raise RuntimeError(body.get("error") or f"meet-board answered {code}")
    return body


def send(base: str, doc: dict) -> dict:
    code, body = _req(base + "/api/startlists", json.dumps(doc).encode(), timeout=20)
    if code != 200 or not body.get("ok"):
        raise RuntimeError(body.get("error") or f"meet-board answered {code}")
    return body


def console_results(base: str) -> dict:
    """Each heat's lane times/places as the console showed them ({"event:heat": {"lanes": {...}}})."""
    code, body = _req(base + "/api/console_results", timeout=4)
    if code == 404:
        raise RuntimeError("this meet-board is too old for the console cross-check - update it")
    if code != 200:
        raise RuntimeError(body.get("error") or f"meet-board answered {code}")
    return body.get("heats") or {}


def console_check(m: dict, heats: dict) -> dict:
    """Compare what the console showed with MeetDeck's times. Returns {"ptr:heat": {"ok", "notes": [...]}}
    for every heat the console recorded that MeetDeck has times for. A cross-check only - nothing is changed.
    Notes: a lane the console timed but didn't place (usually no pad touch), a console time that isn't the
    lane's pad (or button) time, a lane timed on one side only, and a finish order that differs."""
    from meetdb import parse_time, fmt_time
    no2ptr = {v["no"]: v["ptr"] for v in m["events"]}
    by = {}
    for e in m["entries"]:
        if not e["scr"] and e.get("heat") and e.get("lane"):
            by.setdefault((e["event"], e["heat"]), {})[e["lane"]] = e
    out = {}
    for k, rec in (heats or {}).items():
        try:
            evno, h = (int(x) for x in k.split(":"))
        except ValueError:
            continue
        ptr = no2ptr.get(evno)
        lanes = (rec or {}).get("lanes") or {}
        if ptr is None or not lanes:
            continue
        ents = by.get((ptr, h), {})
        if not any((e.get("pad") or 0) or (e.get("backup") or 0) for e in ents.values()):
            continue                    # MeetDeck has no times for this heat yet
        notes, cons = [], {}
        for ln, x in lanes.items():
            t = parse_time(x.get("time") or "")
            if t:
                cons[int(ln)] = (t, (x.get("place") or "").strip())
        for ln in sorted(set(cons) | set(ents)):
            e, c = ents.get(ln), cons.get(ln)
            mine = float((e or {}).get("pad") or 0) or float((e or {}).get("backup") or 0)
            if c and not e:
                notes.append(f"Lane {ln}: the console timed {fmt_time(c[0])}, but MeetDeck has nobody in this lane")
            elif c and not mine:
                notes.append(f"Lane {ln}: the console showed {fmt_time(c[0])}, MeetDeck has no pad or button time")
            elif e and mine and not c and not (e.get("stat") or "").strip():
                notes.append(f"Lane {ln}: MeetDeck has {fmt_time(mine)}, the console showed no time")
            elif c and abs(c[0] - mine) > 0.015:
                src = "pad" if (e.get("pad") or 0) else "button"
                notes.append(f"Lane {ln}: the console showed {fmt_time(c[0])}, MeetDeck's {src} time is {fmt_time(mine)}")
            if c and not c[1]:
                notes.append(f"Lane {ln}: the console gave {fmt_time(c[0])} but no place - likely no pad touch")
        # finish order: the console's places vs the order of MeetDeck's official times, same lanes
        placed = {ln: int(p) for ln, (t, p) in cons.items() if p.isdigit() and ln in ents and (ents[ln].get("time") or 0)}
        if len(placed) > 1:
            off = [(ln, placed[ln], 1 + sum(1 for o in placed if ents[o]["time"] < ents[ln]["time"] - 0.001))
                   for ln in sorted(placed)]
            off = [x for x in off if x[1] != x[2]]
            if off:
                notes.append("Finish order differs: " + ", ".join(f"lane {ln} console {p}, MeetDeck {q}" for ln, p, q in off))
        out[f"{ptr}:{h}"] = {"ok": not notes, "notes": notes}
    return out


def video_times(base: str, date: str) -> list:
    """meet-board's video times for every heat recorded on `date`: [{event, heat, start_src, lanes: {lane: {t, src}}}]."""
    import urllib.parse
    code, body = _req(base + "/api/video/times?date=" + urllib.parse.quote(date), timeout=6)
    if code == 404:
        raise RuntimeError("this meet-board is too old to send video times - update it")
    if code != 200:
        raise RuntimeError((body or {}).get("error") if isinstance(body, dict) else f"meet-board answered {code}")
    return body if isinstance(body, list) else []
