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
        assert frame(b"Rs" + bytes((slot,))) == bytes((7, 0, 0x52, 0x73, slot, 0x33 - slot, 0xFF))
    for race in (1, 7, 40):
        assert frame(b"SR" + bytes((race, 0))) == bytes((8, 0, 0x53, 0x52, race, 0, 0x52 - race, 0xFF))
    assert frame(b"SSBIC")[:7] == H("09 00 53 53 42 49 43")
    assert frame(b"SSBIE" + bytes((2, 5)))[:9] == H("0B 00 53 53 42 49 45 02 05")
    assert check_ok(frame(b"anything at all"))


def make():
    sim = SimConsole(lanes=8, times_per_lane=5, buttons=1)   # 3 splits + final + button/backup
    sim.TROUBLE = {"no_pad": 0, "early_button": 0, "late_pad": 0, "few_buttons": 0}
    sim.add_race(1, 1, {3: 132.62, 4: 128.4, 5: 130.11, 6: None})
    sim.add_race(2, 1, {2: 151.0, 4: 140.05, 5: 139.99, 7: 149.5}, dq={7})
    sim.add_race(2, 2, {4: 120.0, 5: 121.5})
    return sim, Console(sim, settle=0)


def test_identity_and_races():
    sim, c = make()
    assert c.who_are_you().startswith("1.234")
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
    out = c.download_meet(1, evs, "Millard @ Grantsvill")
    assert out["events"] == 3 and sim.active_slot == 1 and sim.titles[1] == "Millard @ Grantsvill"
    assert sim.labels[(0, 3)] == "Girls" and sim.labels[(2, 0)] == "Freestyle" and sim.labels[(3, 0)] == "Final"
    assert sim.events[(1, 3)] == bytes.fromhex("c8 00 04 0a 27 28 00 00 00")
    assert c.sequence_title(1) == "Millard @ Grantsvill"
    c.clear_event(1, 3)
    assert (1, 3) not in sim.events


# ---- byte-for-byte against Meet Manager talking to a real System 6 (HHD capture, 2026-11-10) ----
REAL_MM = """
07 00 52 73 01 32 ff
18 00 49 74 00 00 4d 65 6e 73 00 00 00 00 00 00 00 00 00 00 00 00 97 fd
18 00 49 74 02 09 50 6c 61 74 66 6f 72 6d 20 44 69 76 69 6e 67 00 59 f9
18 00 49 74 01 13 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 16 ff
1c 00 49 73 01 4d 69 6c 6c 61 72 64 20 40 20 47 72 61 6e 74 73 76 69 6c 6c 00 bb f7
12 00 49 75 01 20 00 00 00 00 00 00 00 00 00 00 0e ff
12 00 49 75 01 01 00 c8 00 04 0f 10 27 28 00 00 f3 fd
12 00 49 75 01 0d 00 f4 01 04 0a 27 28 00 00 00 cf fd
12 00 49 75 01 16 00 90 01 03 0a 10 27 28 00 00 1b fe
07 00 49 72 01 3c ff
"""


def test_download_bytes_match_meet_manager():
    sim, c = make()
    evs = [{"no": 1, "distance": 200, "gender": "F", "stroke": "Medley Relay"},
           {"no": 13, "distance": 500, "gender": "F", "stroke": "Free"},
           {"no": 22, "distance": 400, "gender": "M", "stroke": "Free Relay"}]
    c.sequence_title(1)
    c.download_meet(1, evs, "Millard @ Grantsville High")
    sent = {w.hex(" ") for w in sim.writes}
    for line in REAL_MM.strip().splitlines():
        assert line in sent, line
    # same order as Meet Manager: labels, name, clears, events, Ir last
    kinds = [w[2:4] for w in sim.writes]
    assert kinds[-1] == b"Ir" and kinds.index(b"Is") > max(i for i, k in enumerate(kinds) if k == b"It")


def test_ack_is_not_an_error():
    sim, c = make()
    assert c.request(b"Ir\x01") == bytes.fromhex("06 00 06 00 f3 ff")


def test_real_race_reply_parses():
    # event 1 heat 1 from the real console, only lane 1 touched (16.42).
    # The capture stopped 5 bytes short; the rest is lane 8's zero time + the checksum.
    head = bytes.fromhex("db 00 01 01 01 01 04 00 22 31 11 03 0b 0a 1a 01 08 05" + " 00" * 22 +
                         " ea 07 00 01 01 00 01 00 03")
    body = head + bytes((1,)) + (16420).to_bytes(4, "little") + bytes(16) + bytes(21 * 7)
    from cts import frame
    msg = frame(body[2:])
    assert msg[:len(head)] == head and len(msg) == 0xDB
    r = parse_race(msg)
    assert (r.event, r.heat, r.race_number, r.lanes_in_pool, r.times_per_lane, r.buttons) == (1, 1, 4, 8, 5, 3)
    assert r.when == "2026-11-10 17:49:34"
    assert r.lanes[0].final_ms == 16420 and r.lanes[0].place == 1
    assert all(l.final_ms == 0 for l in r.lanes[1:])


def test_bad_length_rejected():
    import pytest
    with pytest.raises(ValueError):
        parse_race(frame(b"x" * 60))


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and name != "test_bad_length_rejected":
            fn(); print("ok", name)


def test_who_are_you_reply_matches_real_console():
    # bytes the real System 6 sent to Meet Manager's 'W' (HHD capture, 2026-11-10)
    sim = SimConsole()
    sim.write(frame(b"W"))
    assert sim.read(64) == bytes.fromhex("0a 00 31 2e 32 33 34 00 fd fe")


def test_real_race_reply_with_button_and_backup():
    # complete reply from the real console (HHD capture 2026-11-10 18:03): lane 1 pad 10.59, one button 13.05
    lane1 = bytes((1,)) + b"".join(t.to_bytes(4, "little") for t in (10590, 13050, 0, 0, 13050))
    msg = bytes.fromhex("db 00 01 01 01 01 06 00 15 00 12 03 0b 0a 1a 01 08 05" + " 00" * 22 +
                        " ea 07 00 01 01 00 01 00 03") + lane1 + bytes(21 * 7) + bytes.fromhex("dc fa")
    from cts import check_ok
    assert check_ok(msg) and len(msg) == 0xDB
    r = parse_race(msg)
    assert r.race_number == 6 and r.when == "2026-11-10 18:00:21"
    l1 = r.lanes[0]
    assert l1.final_ms == 10590 and l1.buttons_ms == [13050, 0, 0] and l1.backup_ms == 13050 and l1.splits_ms == []


def test_missing_heat_gives_clear_message():
    import pytest
    from cts import CTSError
    sim, c = make()
    with pytest.raises(CTSError) as e:
        c.race_by_heat(4, 1)
    assert "no stored race for event 4 heat 1" in str(e.value)
    assert c.race_by_heat(2, 2).heat == 2      # still works after a miss


def test_sim_real_life_trouble():
    sim = SimConsole()                                     # like the pool's console: pad, 3 buttons, backup
    sim.add_race(5, 1, {1: 60.0, 2: 61.0, 3: 62.0, 4: 63.0},
                 trouble={1: "no_pad", 2: "early_button", 3: "late_pad", 4: ""})
    c = Console(sim, settle=0)
    byl = {l.lane: l for l in c.race_by_heat(5, 1).lanes}
    assert byl[1].final_ms == 0 and byl[1].backup_ms > 60000           # missed the pad: backup only
    assert 600 <= byl[2].final_ms - byl[2].backup_ms <= 1400              # backup about a second fast
    assert byl[3].final_ms - 62000 >= 400 and byl[3].backup_ms < byl[3].final_ms   # pad late, buttons earlier
    assert 63050 <= byl[4].backup_ms <= 63300 and byl[4].final_ms == 63000         # normal: buttons just after the pad
