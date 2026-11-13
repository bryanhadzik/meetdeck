import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import meetdb  # noqa: E402
import pytest  # noqa: E402


@pytest.mark.parametrize("v,secs", [("15:00", 54000), ("3:00 PM", 54000), ("3pm", 54000), ("4:15 p.m.", 58500),
                                    ("12:30 am", 1800), ("12 pm", 43200), ("9:05", 32700)])
def test_parse(v, secs):
    assert meetdb.parse_hhmm(v) == secs


def test_bad():
    with pytest.raises(ValueError):
        meetdb.parse_hhmm("25:99")


def test_ops_keep_spacing():
    m = {"sessions": [{"ptr": 1, "no": 1, "day": 1, "start": 54000}, {"ptr": 2, "no": 2, "day": 1, "start": 56700},
                      {"ptr": 3, "no": 3, "day": 2, "start": 32400}]}
    ops, msg = meetdb.start_time_ops(m, "4:15 PM")
    assert [(o["match"]["Sess_ptr"], o["set"]["Sess_starttime"]) for o in ops] == [(1, 58500), (2, 61200)]
    assert "4:15 PM" in msg
    assert meetdb.start_time_ops(m, "15:00") == ([], "")
