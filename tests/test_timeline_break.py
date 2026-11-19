import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import heatsheet  # noqa: E402


def model():
    ev = lambda ptr, no: {"ptr": ptr, "no": no, "ltr": "", "stroke": "A", "ind_rel": "I", "dist": 50, "sex": "F", "gender": "F", "lo": 0, "hi": 109}
    ents = [{"event": p, "scr": False, "kind": "I", "ath": i, "legs": [], "heat": 1, "lane": i, "seed": 30.0, "conv": None}
            for p in (1, 2) for i in range(1, 7)]
    sess = lambda no, start, ptr: {"no": no, "ltr": "", "name": str(no), "day": 1, "start": start, "interval": 30, "back": 30,
                                   "course": "Y", "items": [{"event": ptr, "rnd": "F", "delay": 0, "delay_desc": ""}]}
    return {"meet": {"lanes": 6}, "events": [ev(1, 1), ev(2, 2)], "entries": ents,
            "sessions": [sess(1, 15 * 3600, 1), sess(2, 16 * 3600, 2)]}


def test_break_moves_later_sessions_to_previous_finish_plus_gap():
    m = model()
    plain = heatsheet.timeline(m)
    assert plain[1]["start"] == 16 * 3600                       # Meet Manager's start time
    tl = heatsheet.timeline(m, 15)
    assert tl[0]["start"] == 15 * 3600
    assert tl[1]["start"] == tl[0]["finish"] + 15 * 60
    assert tl[1]["rows"][0]["start"] == tl[1]["start"]


def test_nt_swimmer_adds_time_to_their_heat():
    m = model()
    base = heatsheet.timeline(m)[0]["finish"]
    m["entries"][0]["seed"] = 0                      # one first-time swimmer in event 1's heat
    tl = heatsheet.timeline(m)[0]
    assert tl["finish"] >= base                      # the heat lasts at least as long as an NT swim
    nt = max(heatsheet._nt_estimate(m["events"][0], "Y") * heatsheet.NT_PAD_IND, 30.0)
    assert tl["finish"] == 15 * 3600 + -(-(nt + 30) // 60) * 60
