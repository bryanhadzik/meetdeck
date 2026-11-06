"""Sanity check against a second real meet: THS Mel Roberts Invitational, 19 Dec 2025 (MM 8.0Ga).
docker cp tests/fixtures/mm-melroberts-2025/. swimmeet:/tmp/mel && docker exec -i swimmeet python3 - < tests/check_mm_melroberts.py"""
import datetime as dt, glob, sys
sys.path.insert(0, "/app")
import meetdb, results
FX = "/tmp/mel"
db = f"{FX}/meet.mdb"
m = meetdb.load(db)
def cmp(name, exp, ours):
    exp, ours = exp.split(b"\r\n"), ours.split(b"\r\n")
    diffs = [(i, a, b) for i, (a, b) in enumerate(zip(exp, ours)) if a != b]
    print(f"{name}: MM {len(exp)} lines, us {len(ours)} lines, {len(diffs)} differing lines")
    for i, a, b in diffs[:12]:
        cols = [c for c in range(max(len(a), len(b))) if a[c:c+1] != b[c:c+1]]
        print(f" line {i} cols {cols[:12]}\n  MM: {a.decode('latin-1')}\n  us: {b.decode('latin-1')}")
    return diffs
exp = open(glob.glob(f"{FX}/*.cl2")[0], "rb").read()
cmp(".cl2", exp, results.cl2(m, db, dt.datetime(2025, 12, 20, 12, 5)))
exp = open(glob.glob(f"{FX}/*.hy3")[0], "rb").read()
cmp(".hy3", exp, results.hy3(m, db, "Tooele High School"))
