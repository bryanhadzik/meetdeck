import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import reseed  # noqa: E402


def ent(key, ptr, team, seed, heat=0, lane=0, time=0, scr=False):
    return {"key": key, "kind": "I", "event": ptr, "ath": key, "team": team, "seed": seed, "conv": seed,
            "heat": heat, "lane": lane, "time": time, "stat": "", "scr": scr}


def meet(teams, entries):
    return {"meet": {"lanes": 8}, "teams": {i + 1: {"abbr": t, "name": t} for i, t in enumerate(teams)},
            "events": [{"ptr": 1, "no": 1, "label": "Girls 50 Free"}, {"ptr": 2, "no": 2, "label": "Boys 50 Free"}],
            "entries": entries, "athletes": {}}


def test_standard_seed_fastest_heat_last_center_lanes():
    ents = [{"id": i, "team": "A", "seed": 20 + i} for i in range(10)]
    out = reseed.standard_seed(ents, list(range(1, 9)))
    assert out[0] == (2, 4) and out[1] == (2, 5)            # fastest two in lanes 4 and 5 of the last heat
    assert sum(1 for h, _ in out.values() if h == 1) == 3   # slow heat borrows up to the 3-swimmer minimum


def test_review_flags_changed_unswum_events_only():
    teams = ["T1", "T2", "T3", "T4"]                          # invitational: standard seeding
    e1 = [ent(i, 1, 1 + i % 4, 25 + i, heat=1 + (i >= 8) * 0, lane=0) for i in range(6)]
    for i, e in enumerate(e1):
        e["heat"], e["lane"] = 1, [4, 5, 3, 6, 2, 7][i]
    e2 = [ent(100 + i, 2, 1 + i % 4, 24 + i, heat=1, lane=[4, 5, 3, 6, 2, 7][i], time=30.0) for i in range(6)]
    m = meet(teams, e1 + e2)
    base = {"1": reseed.sig(m, 1), "2": reseed.sig(m, 2)}
    assert reseed.review(m, base, [], list(range(1, 9))) == []
    m["entries"].append(ent(50, 1, 1, 22.0))                 # a late add with no heat or lane
    m["entries"].append(ent(150, 2, 1, 22.0))                # same in an event that's already swum
    got = reseed.review(m, base, [], list(range(1, 9)))
    assert [g["ptr"] for g in got] == [1]
    assert "no heat or lane" in got[0]["reasons"][0]
    ops, moved = reseed.ops(m, 1, [], list(range(1, 9)))
    assert len(ops) == 7 and moved >= 1


def test_unseeded_event_is_flagged_even_when_unchanged():
    m = meet(["T1", "T2"], [ent(i, 1, 1 + i % 2, 25 + i) for i in range(5)])   # no heats or lanes at all
    base = {"1": reseed.sig(m, 1)}
    got = reseed.review(m, base, ["T1", "T2"], list(range(1, 9)))
    assert [g["ptr"] for g in got] == [1] and "no heat or lane" in got[0]["reasons"][0]
