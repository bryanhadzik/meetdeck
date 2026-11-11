"""utahswimcoach.com top times: parsing, standings, phone results + meet-board start lists."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import utahswimcoach as usc
import public_results as pr
import meetboard

TOP = """<html><body><div>4A  Women  50 Free</div>
<table><tr><td>Order</td><td>Time</td><td>Name</td><td>Grade</td><td>School</td><td>Date</td><td>Meet</td></tr>
""" + "".join(f"<tr><td>{i}</td><td>{25 + i / 10:.2f}</td><td>Last{i}, First{i}</td><td>11</td><td>{'Stansbury' if i == 5 else 'Orem'}</td><td>2026-11-01</td><td>M</td></tr>"
              for i in range(1, 41)) + """</table>
<p>4A  Women 200 Medley Relay</p>
<table><tr><td>Order</td><td>Time</td><td>School</td><td>Date</td><td>Meet</td></tr>
<tr><td>1</td><td>1:55.42</td><td>Ridgeline</td><td>2026-10-30</td><td>X</td></tr>
<tr><td>2</td><td>2:01.00</td><td>Stansbury</td><td>2026-10-30</td><td>X</td></tr></table></body></html>"""

REC = """<table><tr><td>Women</td></tr><tr><td>Event</td><td>Record Holder</td><td>School</td><td>Time</td><td>Year</td><td></td></tr>
<tr><td>50 Free</td><td>Fast Person</td><td>Park City</td><td>23.10</td><td>2019</td><td></td></tr></table>"""


def store(tmp_path):
    s = usc.Store(tmp_path)
    s.data = {"season": usc.season(), "fetched": 1, "fetched_at": "2026-11-10T09:00",
              "top": {"4A": usc.parse_top(TOP)}, "records": {"4A": usc.parse_records(REC)},
              "school_class": {"stansbury": "4A", "orem": "4A", "ridgeline": "4A"}}
    s._index()
    return s


def test_parse():
    top = usc.parse_top(TOP)
    assert set(top) == {"F|50|A|I", "F|200|E|R"} and len(top["F|50|A|I"]) == 40
    assert top["F|50|A|I"][0] == {"rank": 1, "t": 25.1, "name": "Last1, First1", "yr": "11", "school": "Orem", "date": "2026-11-01", "meet": "M"}
    assert top["F|200|E|R"][1]["t"] == 121.0 and top["F|200|E|R"][1]["name"] == ""
    assert usc.parse_records(REC)["F|50|A|I"]["t"] == 23.1
    assert usc.event_key("4A  Men 200 I.M.") == "M|200|E|I" and usc.event_key("Women 400 Free Relay") == "F|400|A|R"
    assert usc.season(__import__("datetime").date(2027, 2, 1)) == "2627"


def test_standing_and_lines(tmp_path):
    s = store(tmp_path)
    assert s.school_class("Stansbury High School") == "4A"
    assert s.standing("F|50|A|I", "Stansbury High School", "Last5", "First5") == {"cls": "4A", "rank": 5, "sb": 25.5, "sb_date": "2026-11-01", "sb_meet": "M"}
    assert s.standing("F|50|A|I", "Stansbury", "Nobody", "X") == {"cls": "4A"}
    assert s.standing("F|200|E|R", "Stansbury")["sb"] == 121.0
    assert s.rank_of("F|50|A|I", "4A", 25.15) == 2
    ln = s.event_line("F|50|A|I", "4A")
    assert ln["line"] == 28.2 and ln["top"] == 25.1 and ln["record"] == 23.1 and ln["spots"] == 32


def test_phone_and_board(tmp_path):
    s = store(tmp_path)
    m = {"meet": {"name": "T", "location": "P", "start": "2026-11-12"},
         "teams": {1: {"name": "Stansbury High School", "abbr": "STAN"}},
         "athletes": {10: {"first": "First5", "last": "Last5", "yr": "11", "team": 1}},
         "events": [{"ptr": 1, "no": 1, "label": "Girls 50 Free", "gender": "F", "dist": 50, "stroke": "A", "ind_rel": "I"}],
         "entries": [{"event": 1, "kind": "I", "ath": 10, "team": 1, "scr": False, "place": 1, "time": 25.2, "seed": 25.5, "stat": "",
                      "points": 6, "dq": "", "legs": [], "exh": False, "heat": 1, "lane": 4}]}
    d = pr.build(m, None, s)
    st = d["events"][0]["rows"][0]["st"]
    assert st["rank"] == 5 and st["best"] and st["now"] == 2 and st["spots"] == 32
    assert d["events"][0]["state"][0]["cls"] == "4A" and d["state_src"]["name"] == "utahswimcoach.com"
    assert pr.build(m, None, None)["events"][0]["rows"][0]["st"] is None
    doc = meetboard.startlist(m, "x", s)
    ev = doc["events"][0]
    assert ev["heats"][0]["lanes"][0]["state"] == {"cls": "4A", "rank": 5, "sb": 25.5, "sb_date": "2026-11-01"}
    assert ev["state_now"][0]["line"] == 28.2
