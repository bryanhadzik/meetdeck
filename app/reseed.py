"""Last-minute changes and re-seeding in the meet database.

After coaches turn in scratches, adds and seed changes, an event may need re-seeding: a swimmer with no
heat or lane, a heat that's too small, fewer heats than it needs, or swimmers out of seed order. Only
events that changed since they were last seeded are looked at, and never an event that has results
(day 2 of a two-day meet keeps day 1 as swum).

Two seeding styles:
  * dual/tri meets (3 or fewer teams): MeetDeck's dual-meet seeding - each team in its own lanes (hy3.seed_event)
  * invitationals: standard timed-finals seeding - fastest heat last, fastest swimmers in the middle lanes
"""
from __future__ import annotations

import math

import hy3

MIN_HEAT = 3


def _active(m, ptr):
    return [e for e in m["entries"] if e["event"] == ptr and not e["scr"]]


def swum(m, ptr) -> bool:
    return any(e["time"] or (e.get("stat") or "").strip() for e in m["entries"] if e["event"] == ptr)


def sig(m, ptr) -> list:
    """What seeding depends on: who is in the event and their seed times."""
    return sorted([e["key"], round(e["conv"] or e["seed"] or 0, 2)] for e in _active(m, ptr))


def standard_seed(ents: list[dict], lanes: list[int], min_heat: int = MIN_HEAT) -> dict:
    """Timed-finals seeding: {id: (heat, lane)}. Heat 1 is the slowest; the fastest heat swims last."""
    if not ents or not lanes:
        return {}
    n, L = len(ents), len(lanes)
    order = sorted(ents, key=hy3._seed_key)                 # fastest first, NT last
    h = math.ceil(n / L)
    sizes = [L] * h
    sizes[-1] = n - L * (h - 1)                              # the slowest heat gets what's left
    if h > 1 and sizes[-1] < min_heat:                       # borrow from the next-slowest heat
        need = min_heat - sizes[-1]
        if sizes[-2] - need >= min_heat:
            sizes[-2] -= need
            sizes[-1] += need
    srt = sorted(lanes)
    std = hy3.STD_ORDER.get(L, list(range(1, L + 1)))
    out, i = {}, 0
    for k, size in enumerate(sizes):                         # k = 0 is the fastest heat
        heat_no = h - k
        block = order[i:i + size]
        i += size
        for j, e in enumerate(block):                        # fastest of the heat in the center lane
            out[e["id"]] = (heat_no, srt[std[j] - 1])
    return out


def _ents(m, ptr):
    teams = m["teams"]
    return [{"id": e["key"], "team": (teams.get(e["team"]) or {}).get("abbr", ""), "seed": e["conv"] or e["seed"] or 0}
            for e in _active(m, ptr)]


class Std(list):
    """A team order for a meet that is seeded the standard way (invitational / championship), whatever the team count."""


def fresh(m, ptr, team_order: list[str], lanes: list[int], min_heat: int = MIN_HEAT) -> tuple[dict, str]:
    ents = _ents(m, ptr)
    in_meet = {(t or {}).get("abbr") for t in m["teams"].values()}
    order = [t for t in team_order if t in in_meet] + sorted(t for t in in_meet if t and t not in team_order)
    if not isinstance(team_order, Std) and 1 < len(order) <= 3:
        plan = hy3.lane_plan(order, len(lanes), min(lanes))
        res, _ = hy3.seed_event(ents, plan, min_heat)
        return res, "dual"
    return standard_seed(ents, lanes, min_heat), "standard"


def check(m, ptr, team_order, lanes, min_heat=MIN_HEAT) -> dict:
    """Why an event should be re-seeded (empty list = it's fine), and the new heats and lanes."""
    act = _active(m, ptr)
    new, style = fresh(m, ptr, team_order, lanes, min_heat)
    reasons = []
    unplaced = [e for e in act if not e["heat"] or not e["lane"]]
    if unplaced:
        reasons.append(f"{len(unplaced)} swimmer{'s' if len(unplaced) != 1 else ''} with no heat or lane")
    placed = [e for e in act if e["heat"] and e["lane"]]
    spots = {}
    for e in placed:
        spots.setdefault((e["heat"], e["lane"]), []).append(e)
    if any(len(v) > 1 for v in spots.values()):
        reasons.append("two swimmers in the same lane")
    cur = {}
    for e in placed:
        cur.setdefault(e["heat"], []).append(e)
    want = len({h for h, _ in new.values()})
    if cur and want < len(cur):
        reasons.append(f"fits in {want} heat{'s' if want != 1 else ''} (now {len(cur)})")
    small = [h for h, v in cur.items() if len(v) < min_heat]
    if len(cur) > 1 and small:
        reasons.append("heat " + ", ".join(str(h) for h in sorted(small)) + f" has fewer than {min_heat} swimmers")
    moves = [(e["key"], *new[e["key"]]) for e in act if e["key"] in new and (e["heat"], e["lane"]) != new[e["key"]]]
    heat_moves = sum(1 for e in act if e["key"] in new and e["heat"] != new[e["key"]][0])
    if heat_moves and not reasons:
        reasons.append(f"{heat_moves} swimmer{'s' if heat_moves != 1 else ''} would change heats")
    return {"reasons": reasons, "moves": moves, "style": style, "heats_now": len(cur), "heats_new": want}


def review(m, base: dict, team_order, lanes, skip_ptrs=(), min_heat=MIN_HEAT) -> list[dict]:
    """Events changed since they were seeded (base = {ptr: sig}) that should be re-seeded."""
    out = []
    for v in m["events"]:
        p = v["ptr"]
        if p in skip_ptrs or swum(m, p) or not _active(m, p):
            continue
        b = base.get(str(p))
        unplaced = any(not e["heat"] or not e["lane"] for e in _active(m, p))
        if (b is None or b == sig(m, p)) and not unplaced:     # a swimmer with no heat or lane always counts
            continue
        c = check(m, p, team_order, lanes, min_heat)
        if c["reasons"]:
            out.append({"ptr": p, "no": v["no"], "label": v["label"], **c, "moves": len(c["moves"])})
    return out


def ops(m, ptr, team_order, lanes, min_heat=MIN_HEAT) -> tuple[list, int]:
    """Database updates that re-seed one event, and how many entries moved."""
    import meetdb
    new, _ = fresh(m, ptr, team_order, lanes, min_heat)
    out, n = [], 0
    for e in _active(m, ptr):
        if e["key"] not in new:
            continue
        h, ln = new[e["key"]]
        if (e["heat"], e["lane"]) != (h, ln):
            n += 1
        out.append({"op": "update", "table": meetdb._table(e), "match": meetdb._match(e), "set": {"Fin_heat": h, "Fin_lane": ln}})
    return out, n
