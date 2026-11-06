"""Generate synthetic coach entry files (.zip with .hy3) for testing."""
import io, sys, zipfile
sys.path.insert(0, "/app")
from hy3 import make_line

def put(buf, col, s):
    buf[col - 1:col - 1 + len(s)] = list(s)

def rec(rt, fields):
    b = list(rt.ljust(128))
    for col, s in fields:
        put(b, col, s)
    return make_line("".join(b))

EVENTS = {  # event_no: (distance, stroke)
    1: ("200", "E", True), 3: ("200", "A", False), 5: ("200", "E", False), 7: ("50", "A", False),
    9: ("100", "D", False), 11: ("100", "A", False), 13: ("500", "A", False), 15: ("200", "A", True),
    17: ("100", "B", False), 19: ("100", "C", False), 21: ("400", "A", True),
}

def team_file(code, name, swimmers, relays):
    lines = [rec("A1", [(3, "02"), (5, "Meet Entries"), (30, "Hy-Tek, Ltd"), (45, "TM 8.0")]),
             rec("B1", [(3, "Fixture Dual Meet")]),
             rec("C1", [(3, code.ljust(5)), (8, name.ljust(30))])]
    for i, (first, last, g, events) in enumerate(swimmers, 1):
        lines.append(rec("D1", [(3, g), (4, f"{i:5d}"), (9, last.ljust(20)), (29, first.ljust(20)),
                                (97, " 16"), (100, "Jr")]))
        for ev, seed in events:
            d, s, _ = EVENTS[ev]
            lines.append(rec("E1", [(3, g), (4, f"{i:5d}"), (9, last[:5].ljust(5)), (14, g), (15, g),
                                    (16, d.rjust(6)), (22, s), (39, str(ev).rjust(4)),
                                    (43, f"{seed:8.2f}"), (51, "Y"), (52, f"{seed:8.2f}"), (60, "Y")]))
    for ev, letter, g, legs, seed in relays:
        d, s, _ = EVENTS[ev]
        lines.append(rec("F1", [(3, code.ljust(5)), (8, letter), (14, g), (15, g), (16, d.rjust(6)), (22, s),
                                (39, str(ev).rjust(4)), (43, f"{seed:8.2f}"), (51, "Y"), (52, f"{seed:8.2f}"), (60, "Y")]))
        f3 = [(3, " ")]
        for slot, sid in enumerate(legs):
            f3 += [(4 + 13 * slot, f"{sid:5d}"), (15 + 13 * slot, str(slot + 1))]
        lines.append(rec("F3", f3))
    hy3 = b"".join(lines)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"Meet Entries-{code}-Fixture.hy3", hy3)
    return buf.getvalue()

tooe = team_file("TOOE", "Tooele High School", [
    ("Alice", "Anders", "F", [(3, 130.1), (7, 27.5), (11, 59.9)]),          # 3 individual -> error
    ("Bella", "Brown", "F", [(9, 68.2), (17, 70.4)]),                        # 2 ind + 3 relays -> error
    ("Cara", "Cole", "F", [(7, 28.9), (7, 28.9)]),                           # duplicate event -> error
    ("Dana", "Diaz", "F", [(19, 80.0)]),
    ("Evan", "Ellis", "M", [(7, 24.8), (11, 53.1)]),
], [(1, "A", "F", [2, 4, 1, 3], 125.0), (15, "A", "F", [2, 1, 4, 3], 110.0), (21, "A", "F", [2, 4, 1, 3], 245.0)])

stan = team_file("STAN", "Stansbury High School", [
    ("Faye", "Ford", "F", [(7, 27.9), (11, 61.0)]),
    ("Gina", "Gray", "F", [(17, 66.6)]),
    ("Hal", "Hunt", "M", [(7, 25.5), (9, 0.0)]),
], [(1, "A", "F", [1, 2, 1, 2], 130.0)])                                      # same swimmer on two legs

open("/tmp/TOOE.zip", "wb").write(tooe)
open("/tmp/STAN.zip", "wb").write(stan)
print("ok")
