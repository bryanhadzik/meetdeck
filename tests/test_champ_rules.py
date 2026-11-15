import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, "/app")
import main


def test_four_teams_always_championship():
    assert main._is_champ({}, 4)
    assert main._is_champ({"championship": False}, 4)
    assert main._team_lanes({"championship": False}, ["A", "B", "C", "D"]) == (None, "championship")
    assert main._champ_rules({}, {}, 4)["team_cap_per_event"] == 4


def test_expected_teams_count():
    assert main._is_champ({"expected_teams": ["A", "B", "C", "D"]}, 2)


def test_small_meets_follow_setting():
    assert not main._is_champ({}, 2)
    assert not main._is_champ({}, 3)
    assert main._is_champ({"kind": "invitational"}, 3)
    assert not main._is_champ({"kind": "invitational", "championship": False}, 3)
    assert main._is_champ({"championship": True}, 2)
    assert main._team_lanes({"championship": True}, ["A", "B"]) == (None, "championship")
    assert main._champ_rules({}, {"x": 1}, 2) == {"x": 1}
