"""Run: python -m pytest timing/tests  (or python timing/tests/test_cts.py)"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cts import frame, check_ok, Console, parse_race
from sim import SimConsole

H = bytes.fromhex


def test_reference_packets():
    # byte-for-byte the messages documented for the System 5 interface
    assert frame(b"W") == H("05 00 57 A3 FF")
    assert frame(b"T") == H("05 00 54 A6 FF")
    assert frame(b"M+") == H("06 00 4D 2B 81 FF")
    assert frame(b"M-") == H("06 00 4D 2D 7F FF")
    for t, s in [(0, 1), (2, 5), (1, 9)]:
        assert frame(b"Rt" + bytes((t, s))) == bytes((8, 0, 0x52, 0x74, t, s, 0x31 - (t + s), 0xFF))
    for slot in (2, 8, 9):
        assert frame(b"Ir" + bytes((slot,))) == bytes((7, 0, 0x49, 0x72, slot, 0x3D - slot, 0xFF))
        assert frame(b"Rs" + bytes((slot, 0, 0))) == bytes((9, 0, 0x52, 0x73, slot, 0, 0, 0x31 - slot, 0xFF))
    for race in (1, 7, 40):
        assert frame(b"SR" + bytes((race, 0))) == bytes((8, 0, 0x53, 0x52, race, 0, 0x52 - race, 0xFF))
    assert frame(b"SSBIC")[:7] == H("09 00 53 53 42 49 43")
    assert frame(b"SSBIE" + bytes((2, 5)))[:9] == H("0B 00 53 53 42 49 45 02 05")
    assert check_ok(frame(b"anything at all"))


def make():
    sim = SimConsole(lanes=8, times_per_lane=5, buttons=1)   # 3 splits + final + button/backup
    sim.add_race(1, 1, {3: 132.62, 4: 128.4, 5: 130.11, 6: None})
    sim.add_race(2, 1, {2: 151.0, 4: 140.05, 5: 139.99, 7: 149.5}, dq={7})
    sim.add_race(2, 2, {4: 120.0, 5: 121.5})
    return sim, Console(sim, settle=0)


def test_identity_and_races():
    sim, c = make()
    assert "System 6" in c.who_are_you()
    assert c.meet(0).get("when")
    assert c.race_list() == [{"race": 1, "event": 1, "heat": 1}, {"race": 2, "event": 2, "heat": 1}, {"race": 3, "event": 2, "heat": 2}]
    r = c.race_by_heat(2, 1)
    assert (r.event, r.heat, r.race_number, r.lanes_in_pool) == (2, 1, 2, 8)
    byl = {l.lane: l for l in r.lanes}
    assert byl[5].final_ms == 139990 and byl[5].place == 1
    assert byl[4].place == 2 and byl[7].place == -1
    assert byl[1].final_ms == 0 and byl[1].place == 0
    assert byl[5].backup_ms and len(byl[5].buttons_ms) == 1 and len(byl[5].splits_ms) == 3
    assert byl[5].splits_ms[0] < byl[5].splits_ms[2] < byl[5].final_ms
    assert c.race(3).heat == 2 and c.race_last().race_number == 3


def test_download_meet():
    sim, c = make()
    evs = [{"no": 1, "distance": 200, "gender": "F", "stroke": "Medley Relay"},
           {"no": 2, "distance": 200, "gender": "M", "stroke": "Medley Relay"},
           {"no": 3, "distance": 200, "gender": "F", "stroke": "Free"}]
    out = c.download_meet(8, evs)
    assert out["events"] == 3 and sim.active_slot == 8
    assert sim.labels[(0, 0)] == "Girls" and sim.labels[(2, 1)] == "Free"
    assert sim.events[(8, 3)] == bytes((200, 0, 0, 1))
    c.clear_event(8, 3)
    assert (8, 3) not in sim.events


def test_bad_length_rejected():
    import pytest
    with pytest.raises(ValueError):
        parse_race(frame(b"x" * 60))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and name != "test_bad_length_rejected":
            fn(); print("ok", name)
