import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, "/app")
import hy3

PLAN = hy3.lane_plan(["TOO", "FRE"], 8)          # Tooele odd, Fremont even


def ents(team, n, start=60.0):
    return [{"id": f"{team}{i}", "team": team, "seed": start + i} for i in range(n)]


def test_strict_keeps_team_lanes_in_every_heat():
    es = ents("FRE", 10) + ents("TOO", 3, 61.5)
    out, info = hy3.seed_event(es, PLAN, 3, strict=True)
    assert len(out) == 13
    for e in es:
        heat, lane = out[e["id"]]
        assert lane % 2 == (1 if e["team"] == "TOO" else 0), (e, heat, lane)
    lanes_used = {}
    for i, (h, l) in out.items():
        assert (h, l) not in lanes_used, "two swimmers in one lane"
        lanes_used[(h, l)] = i


def test_strict_one_team_heat_uses_own_lanes_fastest_in_middle():
    es = ents("FRE", 6) + ents("TOO", 1)
    out, _ = hy3.seed_event(es, PLAN, 1, strict=True)
    assert all(l % 2 == 0 for k, (h, l) in out.items() if k.startswith("FRE"))
    assert out["TOO0"][1] % 2 == 1
    assert out["FRE0"][1] == 4                      # fastest Fremont swimmer nearest the middle


def test_loose_mode_unchanged():
    es = ents("FRE", 6) + ents("TOO", 1)
    a, _ = hy3.seed_event(es, PLAN, 3)
    b, _ = hy3.seed_event(es, PLAN, 3, strict=False)
    assert a == b
