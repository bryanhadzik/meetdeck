import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from importers import parse_entry_list  # noqa: E402

REPORT = """Meet Entries Report
Blue @ Gold  12-Nov-26  Yards  Alt: 5000

WOMEN
Ann Able (12) - 200 Free 2:40.72Y; 100 Free 1:09.26Y; 200 Free Relay A1; 400 Free Relay B1
Bea Baker (10) - 200 Medley Relay A Back; 200 Free 2:46.63Y; 200 Free Relay A3
Cat Cole (1?) - 200 Medley Relay A Brst; 200 IM 2:37.36Y; 200 Free Relay A2
Dee Dunn (11) - 200 Medley Relay A Fly; 50 Free 29.98Y; 200 Free Relay A4
Eve Ezra (09) - 200 Medley Relay A Free; 100 Back 1:14.54Y

MEN
Sam Van Der Berg[e] (?) - 200 Medley Relay A Back; 100 Fly 1:02.66Y; 100 Breast 1:25.26Y; 400 Free Relay A1
"""


def test_tm_report_relays_are_not_individual_events():
    out = parse_entry_list(REPORT, default_team={"name": "Gold High School", "code": "GOLD"})
    (t,) = out["teams"]
    assert t["code"] == "GOLD" and t["name"] == "Gold High School"
    names = {s["first"] + " " + s["last"]: k for k, s in t["swimmers"].items()}
    sam = names["Sam Van Der Berge"]
    sam_ev = sorted((e["dist"], e["stroke"]) for e in t["entries"] if e["swimmer"] == sam)
    assert sam_ev == [(100, "C"), (100, "D")]                  # no 200 IM, no 400 free
    assert t["swimmers"][sam]["gender"] == "M" and t["swimmers"][sam]["age"] == 0
    assert t["swimmers"][names["Ann Able"]]["age"] == 12
    assert not any(e["dist"] == 200 and e["stroke"] == "E" and e["swimmer"] != names["Cat Cole"] for e in t["entries"])
    seeds = {(e["swimmer"], e["dist"], e["stroke"]): e["seed"] for e in t["entries"]}
    assert seeds[(names["Ann Able"], 200, "A")] == 160.72
    medley = next(r for r in t["relays"] if r["gender"] == "F" and r["stroke"] == "E")
    assert medley["letter"] == "A" and medley["legs"] == [names[n] for n in ("Bea Baker", "Cat Cole", "Dee Dunn", "Eve Ezra")]
    free = next(r for r in t["relays"] if r["gender"] == "F" and r["dist"] == 200 and r["stroke"] == "A")
    assert free["legs"] == [names[n] for n in ("Ann Able", "Cat Cole", "Bea Baker", "Dee Dunn")]
    assert not [w for w in out["warnings"] if "couldn't read" in w]


def test_generic_list_ignores_relay_pieces_and_ages():
    out = parse_entry_list("Gold Girls\nAnn Able (12) - 200 free 2:10.00, 200 Medley Relay A Back\n")
    (t,) = out["teams"]
    assert [(e["dist"], e["stroke"]) for e in t["entries"]] == [(200, "A")]
