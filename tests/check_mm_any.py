"""Compare our results export with Meet Manager's for any meet folder: python3 check_mm_any.py <dir>
<dir> holds the .mdb and Meet Manager's .cl2/.hy3. Prints a per-record-type summary of differences."""
import collections, datetime as dt, glob, sys
sys.path.insert(0, "/app")
import meetdb, results
d = sys.argv[1]
db = glob.glob(f"{d}/*.mdb")[0]
m = meetdb.load(db)
out = {}
for ext in ("cl2", "hy3"):
    f = glob.glob(f"{d}/*.{ext}")
    if not f:
        continue
    exp = open(f[0], "rb").read()
    if ext == "cl2":
        h = exp[105:113].decode()
        ours = results.cl2(m, db, dt.datetime(int(h[4:8]), int(h[0:2]), int(h[2:4])))
    else:
        ours = results.hy3(m, db, exp[75:128].decode("latin-1").strip())
    E, O = exp.split(b"\r\n"), ours.split(b"\r\n")
    diff = [(i, a, b) for i, (a, b) in enumerate(zip(E, O)) if a != b and i > 0]
    types = collections.Counter(a[:2].decode() for i, a, b in diff)
    print(f"{ext}: MM {len(E)} lines, us {len(O)}, {len(diff)} differ (header excluded) {dict(types)}")
    for i, a, b in diff[:int(sys.argv[2]) if len(sys.argv) > 2 else 6]:
        cs = [c for c in range(max(len(a), len(b))) if a[c:c + 1] != b[c:c + 1]]
        print(f"  line {i} cols {cs[:14]}\n   MM: {a.decode('latin-1')[:165]}\n   us: {b.decode('latin-1')[:165]}")
