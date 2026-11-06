"""Independent check of a built MM backup: read it with mdbtools (not Jackcess) and
compare every athlete / entry / relay / relay leg against the spec the app produced.

usage: python3 verify_mm.py <backup.zip> <spec.json>
Needs mdb-export (mdbtools) on PATH.
"""
import csv, io, json, subprocess, sys, tempfile, zipfile
from pathlib import Path

zp, specp = sys.argv[1], sys.argv[2]
spec = json.load(open(specp))
tmp = Path(tempfile.mkdtemp())
z = zipfile.ZipFile(zp)
names = z.namelist()
mdb = [n for n in names if n.lower().endswith(".mdb")][0]
z.extractall(tmp)
hyb = z.read("hybackup.txt").decode("latin-1")
size_ok = hyb[200:340].strip() == str(len(z.read(mdb)))


def table(t):
    out = subprocess.run(["mdb-export", "-D", "%Y-%m-%d", str(tmp / mdb), t], capture_output=True, text=True, check=True).stdout
    return list(csv.DictReader(io.StringIO(out)))


teams = {r["Team_no"]: r for r in table("Team")}
aths = {r["Ath_no"]: r for r in table("Athlete")}
events = {r["Event_ptr"]: r for r in table("Event")}
entries = table("Entry")
relays = {r["Relay_no"]: r for r in table("Relay")}
legs = table("RelayNames")
meet = table("Meet")[0]

problems = []
abbr = {no: t["Team_abbr"].strip() for no, t in teams.items()}
# athletes
spec_aths = {(a["team"], a["last"], a["first"]) for a in spec["athletes"]}
db_aths = {(abbr[a["Team_no"]], a["Last_name"].strip(), a["First_name"].strip()) for a in aths.values()}
if spec_aths != db_aths:
    problems.append(f"athlete mismatch: missing {spec_aths - db_aths}, extra {db_aths - spec_aths}")
for a in aths.values():
    if len(a["Last_name"]) != 20 or len(a["First_name"]) != 20:
        problems.append(f"name not padded like MM: {a['Last_name']!r}")
akey = {a["key"]: (a["team"], a["last"], a["first"]) for a in spec["athletes"]}


def ev(e):
    return (int(float(e["Event_no"])), e["Event_gender"], int(float(e["Event_dist"])), e["Event_stroke"])


# entries
spec_e = sorted((akey[e["athlete"]], (e["event_no"], "F" if e["gender"] == "W" else e["gender"], e["distance"], e["stroke"]),
                 round(float(e["seed"] or 0), 2)) for e in spec["entries"])
db_e = sorted(((abbr[aths[e["Ath_no"]]["Team_no"]], aths[e["Ath_no"]]["Last_name"].strip(), aths[e["Ath_no"]]["First_name"].strip()),
               ev(events[e["Event_ptr"]]), round(float(e["ActualSeed_time"] or 0), 2)) for e in entries)
if spec_e != db_e:
    problems.append(f"entry mismatch: {len(spec_e)} expected vs {len(db_e)} in db; "
                    f"diff {set(spec_e) ^ set(db_e)}")
want_lanes = sorted((akey[e["athlete"]], e["event_no"], e["lane"]) for e in spec["entries"] if "lane" in e)
got_lanes = sorted(((abbr[aths[e["Ath_no"]]["Team_no"]], aths[e["Ath_no"]]["Last_name"].strip(), aths[e["Ath_no"]]["First_name"].strip()),
                    int(float(events[e["Event_ptr"]]["Event_no"])), int(e["Fin_lane"])) for e in entries if e["Fin_heat"] not in ("0", ""))
if want_lanes != got_lanes:
    problems.append(f"pre-seeded lanes differ from plan: {set(want_lanes) ^ set(got_lanes)}")
# relays + legs
spec_r = sorted((r["team"], r["letter"], r["event_no"], round(float(r["seed"] or 0), 2),
                 tuple(akey[r["legs"][k]] for k in sorted(r["legs"], key=int))) for r in spec["relays"])
db_r = []
for no, r in relays.items():
    lg = sorted((int(l["Pos_no"]), l["Ath_no"]) for l in legs if l["Relay_no"] == no)
    db_r.append((abbr[r["Team_no"]], r["Team_ltr"].strip(), int(float(events[r["Event_ptr"]]["Event_no"])),
                 round(float(r["ActualSeed_time"] or 0), 2),
                 tuple((abbr[aths[a]["Team_no"]], aths[a]["Last_name"].strip(), aths[a]["First_name"].strip()) for _, a in lg)))
db_r.sort()
if spec_r != db_r:
    problems.append(f"relay mismatch: {set(spec_r) ^ set(db_r)}")

lanes = {i: meet.get(f"dualteam_lane{i}") for i in range(1, 13)}
print(json.dumps({
    "mdb": mdb, "hybackup_size_matches": size_ok,
    "meet": meet["Meet_name1"], "date": meet["Meet_start"], "style": meet["meet_meetstyle"],
    "use_lane_assignments": meet["dual_evenodd"], "anyone_onrelay": meet["anyone_onrelay"],
    "numlanes": meet["meet_numlanes"],
    "lanes": {k: abbr.get(v, v) for k, v in lanes.items() if v not in ("0", "", None)},
    "counts": {"teams": len(teams), "athletes": len(aths), "entries": len(entries), "relays": len(relays), "legs": len(legs)},
    "events_kept": len(events), "records_kept": len(table("Records")),
    "problems": problems,
}, indent=1))
