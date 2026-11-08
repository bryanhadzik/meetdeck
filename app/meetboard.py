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


def startlist(m: dict, source: str = "MeetDeck") -> dict:
    """The meet's start lists from a meetdb.load() model. Scratched and unseeded entries are left out."""
    teams, aths = m["teams"], m["athletes"]
    course = "Y"
    for s in m.get("sessions") or []:
        course = (s.get("course") or "Y")[:1].upper()
        break
    used_teams = set()
    events = []
    for v in m["events"]:                     # already in session order
        heats = {}
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
            heats.setdefault(int(e["heat"]), []).append(lane)
        if not heats:
            continue
        events.append({
            "number": v["no"], "gender": v.get("gender") or v.get("sex") or "", "distance": v.get("dist") or 0,
            "stroke": v.get("stroke", ""), "relay": v.get("ind_rel") == "R", "course": course,
            "heats": [{"heat": h, "lanes": sorted(ls, key=lambda x: x["lane"])} for h, ls in sorted(heats.items())],
        })
    meet = m.get("meet") or {}
    return {
        "format": FORMAT, "version": 1, "source": source,
        "meet": {"name": meet.get("name", ""), "facility": meet.get("location", ""), "date": meet.get("start", "")},
        "teams": {(teams.get(t) or {}).get("abbr", ""): (teams.get(t) or {}).get("name", "")
                  for t in used_teams if (teams.get(t) or {}).get("abbr")},
        "events": events,
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
