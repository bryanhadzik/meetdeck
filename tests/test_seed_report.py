import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import reseed  # noqa: E402


def _model(lanes):
    """One event, teams A (no 1) and B (no 2); lanes = [(team_no, heat, lane, seed)]."""
    ents = [{"key": f"E:1:{i}", "kind": "I", "event": 1, "team": t, "ath": i, "heat": h, "lane": ln,
             "seed": sd, "conv": sd, "scr": False, "time": 0, "stat": ""} for i, (t, h, ln, sd) in enumerate(lanes)]
    return {"teams": {1: {"abbr": "A"}, 2: {"abbr": "B"}, 3: {"abbr": "EMPTY"}}, "athletes": {},
            "events": [{"ptr": 1, "no": 1, "label": "Girls 50 Free"}], "entries": ents}


def test_report_counts_swimmers_in_another_teams_lane():
    # dual meet: A odd lanes, B even lanes; one A swimmer sits in B's lane 4
    m = _model([(1, 1, 3, 30.0), (1, 1, 4, 31.0), (2, 1, 2, 32.0), (2, 1, 6, 33.0)])
    r = reseed.report(m, ["A", "B"], list(range(1, 9)))
    assert r["mode"] == "teams" and r["order"] == ["A", "B"]          # EMPTY has no entries: no lanes
    assert r["off_lane"] == 1 and r["events"][0]["off_lane"][0]["lane"] == 4


def test_report_strict_when_everyone_in_own_lanes():
    m = _model([(1, 1, 3, 30.0), (1, 1, 5, 31.0), (2, 1, 4, 32.0), (2, 1, 6, 33.0)])
    r = reseed.report(m, ["A", "B"], list(range(1, 9)))
    assert r["off_lane"] == 0


def test_report_time_seeded_has_no_lane_check():
    m = _model([(1, 1, 4, 30.0), (2, 1, 5, 31.0)])
    r = reseed.report(m, reseed.Std(["A", "B"]), list(range(1, 9)))
    assert r["mode"] == "time" and r["off_lane"] == 0 and r["plan"] == []
