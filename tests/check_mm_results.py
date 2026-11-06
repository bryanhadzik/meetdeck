"""Regression check: our results export must match Meet Manager's own "Export Results for Team Manager"
for a real meet (Stansbury Blue & Black, 30 Oct 2026, run in MM 8.0Gh).

Run from the project folder:   docker exec -i swimmeet python3 - < tests/check_mm_results.py
(the fixture is copied into the container first by the command in README)."""
import datetime as dt
import sys
sys.path.insert(0, "/app")
import meetdb, results

FX = "/tmp/mmfixture"
db = f"{FX}/BlueandBlack10302026.mdb"
m = meetdb.load(db)
ok = True
exp = open(f"{FX}/exp.cl2", "rb").read()
# MM wrote the file on 1 Nov 2026; the .cl2 carries only that date
ours = results.cl2(m, db, dt.datetime(2026, 11, 1, 10, 9))
print(".cl2:", "identical" if ours == exp else "DIFFERENT")
ok &= ours == exp
exp = open(f"{FX}/exp.hy3", "rb").read().split(b"\r\n")
ours = results.hy3(m, db, "Tooele High School").split(b"\r\n")
same = exp[1:] == ours[1:] and exp[0][:58] == ours[0][:58] and exp[0][75:128] == ours[0][75:128]
print(".hy3:", "identical (apart from export time)" if same else "DIFFERENT")
if not same:
    for i, (a, b) in enumerate(zip(exp, ours)):
        if a != b:
            print(i, "\n MM:", a.decode("latin-1"), "\n us:", b.decode("latin-1"))
ok &= same
sys.exit(0 if ok else 1)
