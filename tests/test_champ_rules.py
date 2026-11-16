import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, "/app")
import main


def test_four_teams_optional():
    assert not main._is_champ({}, 4)
    assert main._is_champ({"championship": True}, 4)
    assert main._team_lanes({}, ["A", "B", "C", "D"])[1] == ""
    assert main._team_lanes({"championship": True}, ["A", "B", "C", "D"]) == (None, "championship")


def test_seed_by_time_without_championship():
    for order in (["A", "B"], ["A", "B", "C"], ["A", "B", "C", "D"]):
        assert main._team_lanes({"lane_mode": "seed"}, order) == (None, "chosen")
    assert main._champ_rules({"lane_mode": "seed"}, {"x": 1}, 4) == {"x": 1}   # no entry caps


def test_small_meets_follow_setting():
    assert not main._is_champ({}, 2)
    assert main._is_champ({"kind": "invitational"}, 3)
    assert not main._is_champ({"kind": "invitational", "championship": False}, 3)
    assert main._champ_rules({"championship": True}, {}, 2)["team_cap_per_event"] == 4


def test_coach_emails_match_school_names(monkeypatch):
    monkeypatch.setattr(main, "_contacts", lambda: [
        {"role": "Head coach", "school": "Ben Lomond", "email": "a@x.org"},
        {"role": "Meet referee", "school": "Ben Lomond", "email": "ref@x.org"},
        {"role": "Head coach", "school": "Deseret Peak High School", "email": "b@x.org"},
        {"role": "Head coach", "school": "Logan", "email": "c@x.org"}])
    monkeypatch.setattr(main, "_hosts", lambda: [])
    teams = [{"name": "Ben Lomond High School", "code": "BLHS", "email": "coach@ogden.org"},
             {"name": "Deseret Peak", "code": "DPHS"}]
    assert main._coach_emails(teams) == ["a@x.org", "b@x.org", "coach@ogden.org"]
