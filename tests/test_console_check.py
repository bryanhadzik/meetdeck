import meetboard


def _m():
    ev = [{"ptr": 1, "no": 12}]
    ents = [
        {"key": "a", "event": 1, "heat": 6, "lane": 4, "scr": False, "pad": 49.73, "backup": 49.69, "time": 59.58, "stat": ""},
        {"key": "b", "event": 1, "heat": 6, "lane": 5, "scr": False, "pad": 54.79, "backup": 54.80, "time": 54.79, "stat": ""},
        {"key": "c", "event": 1, "heat": 6, "lane": 6, "scr": False, "pad": 55.04, "backup": 55.0, "time": 55.04, "stat": ""},
        {"key": "d", "event": 1, "heat": 7, "lane": 4, "scr": False, "pad": 0, "backup": 0, "time": 0, "stat": ""},
    ]
    return {"events": ev, "entries": ents}


def test_flags_unplaced_mismatch_and_order():
    heats = {"12:6": {"lanes": {"4": {"time": "53.60", "place": "1"}, "5": {"time": "54.79", "place": ""},
                                "6": {"time": "55.04", "place": "2"}}},
             "12:7": {"lanes": {"4": {"time": "49.73", "place": "1"}}},     # MeetDeck has no times yet: skipped
             "40:1": {"lanes": {"1": {"time": "30.00", "place": "1"}}}}     # not an event here
    r = meetboard.console_check(_m(), heats)
    assert list(r) == ["1:6"]
    n = " | ".join(r["1:6"]["notes"])
    assert "Lane 4: the console showed 53.60, MeetDeck's pad time is 49.73" in n
    assert "Lane 5: the console gave 54.79 but no place" in n
    assert "lane 4 console 1, MeetDeck 2" in n and not r["1:6"]["ok"]


def test_clean_heat():
    heats = {"12:6": {"lanes": {"4": {"time": "49.73", "place": "1"}, "5": {"time": "54.79", "place": "2"},
                                "6": {"time": "55.04", "place": "3"}}}}
    m = _m()
    m["entries"][0]["time"] = 49.73
    assert meetboard.console_check(m, heats)["1:6"] == {"ok": True, "notes": []}
