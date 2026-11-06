"""Download MaxPreps logos for Utah 3A and 4A high schools (UHSAA 2025-27 alignment, all sports except football).
Crawls MaxPreps Utah team pages (they link their opponents) until every school is found.
    python3 tools/fetch_logos.py OUTDIR
"""
import json, re, sys, time, urllib.request
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "logos")
OUT.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}

# (classification, region, school, mascot as MaxPreps spells it in the URL)
SCHOOLS = [
    ("4A", 8, "Deer Creek", "chargers"), ("4A", 8, "Mountain View", "bruins"), ("4A", 8, "Orem", "tigers"),
    ("4A", 8, "Provo", "bulldogs"), ("4A", 8, "Summit Academy", "bears"), ("4A", 8, "Timpanogos", "timberwolves"),
    ("4A", 8, "Uintah", "utes"), ("4A", 8, "Wasatch", "wasps"),
    ("4A", 9, "Cedar", "reds"), ("4A", 9, "Crimson Cliffs", "mustangs"), ("4A", 9, "Desert Hills", "thunder"),
    ("4A", 9, "Dixie", "flyers"), ("4A", 9, "Hurricane", "tigers"), ("4A", 9, "Pine View", "panthers"),
    ("4A", 9, "Snow Canyon", "warriors"), ("4A", 9, "Utah Arts Academy", ""), ("4A", 9, "Vista School", ""),
    ("4A", 10, "Cottonwood", "colts"), ("4A", 10, "East", "leopards"), ("4A", 10, "Highland", "rams"),
    ("4A", 10, "Jordan", "beetdiggers"), ("4A", 10, "Juan Diego", "soaring-eagle"), ("4A", 10, "Judge Memorial", "bulldogs"),
    ("4A", 10, "Murray", "spartans"), ("4A", 10, "Park City", "miners"), ("4A", 10, "City Academy", ""),
    ("4A", 11, "Bear River", "bears"), ("4A", 11, "Deseret Peak", "pirates"), ("4A", 11, "Green Canyon", "wolves"),
    ("4A", 11, "Mountain Crest", "mustangs"), ("4A", 11, "Ridgeline", "riverhawks"), ("4A", 11, "Sky View", "bobcats"),
    ("4A", 11, "Stansbury", "stallions"), ("4A", 11, "Tooele", "buffaloes"),
    ("3A", 12, "Ben Lomond", "scots"), ("3A", 12, "Grantsville", "cowboys"), ("3A", 12, "Layton Christian Academy", "eagles"),
    ("3A", 12, "Logan", "grizzlies"), ("3A", 12, "Morgan", "trojans"), ("3A", 12, "Ogden", "tigers"), ("3A", 12, "Liahona", ""),
    ("3A", 13, "Carbon", "dinos"), ("3A", 13, "Emery", "spartans"), ("3A", 13, "Manti", "templars"),
    ("3A", 13, "North Sanpete", "hawks"), ("3A", 13, "Union", "cougars"),
    ("3A", 14, "Canyon View", "falcons"), ("3A", 14, "Delta", "rabbits"), ("3A", 14, "Juab", "wasps"),
    ("3A", 14, "Providence Hall", "patriots"), ("3A", 14, "Richfield", "wildcats"),
]
slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read()


def match(path):
    """'/ut/city/school-mascot/' -> index into SCHOOLS or None."""
    team = path.strip("/").split("/")[-1]
    for i, (_, _, name, mascot) in enumerate(SCHOOLS):
        s = slug(name)
        if mascot and team == f"{s}-{mascot}":
            return i
        if not mascot and team.startswith(s + "-"):
            rest = team[len(s) + 1:]
            if not any(team.startswith(slug(n) + "-") and len(slug(n)) > len(s) for _, _, n, _ in SCHOOLS):
                return i
    return None


found, seen, queue = {}, set(), ["/ut/tooele/tooele-buffaloes/"]
while queue and len(found) < len(SCHOOLS) and len(seen) < 400:
    p = queue.pop(0)
    if p in seen:
        continue
    seen.add(p)
    try:
        html = get("https://www.maxpreps.com" + p).decode("utf-8", "replace")
    except Exception as e:
        print("skip", p, e)
        continue
    i = match(p)
    if i is not None and i not in found:
        m = re.search(r"https://image\.maxpreps\.io/school-mascot/[^\"?\s]+", html)
        title = re.search(r"<title>([^<]*)", html)
        found[i] = {"page": "https://www.maxpreps.com" + p, "logo": m.group(0) if m else None, "title": title.group(1) if title else ""}
        print(f"found {SCHOOLS[i][2]:26} {p}")
    for q in re.findall(r'"(/ut/[a-z0-9-]+/[a-z0-9-]+/)"', html):
        if q not in seen:
            # schools we still need go to the front of the queue
            (queue.insert(0, q) if (match(q) is not None and match(q) not in found) else queue.append(q))
    time.sleep(0.4)

index = []
for i, (cls, reg, name, mascot) in enumerate(SCHOOLS):
    f = found.get(i)
    row = {"class": cls, "region": reg, "school": name, "maxpreps": f and f["page"], "file": None}
    if f and f["logo"]:
        ext = f["logo"].rsplit(".", 1)[-1].lower()
        fn = f"{cls} R{reg} {name}.{ext}"
        (OUT / fn).write_bytes(get(f["logo"]))
        row["file"] = fn
    index.append(row)
    print(f"{cls} R{reg:<3} {name:26} {row['file'] or 'NOT FOUND'}")
(OUT / "schools.json").write_text(json.dumps(index, indent=1))
print(f"{sum(1 for r in index if r['file'])} of {len(index)} logos; pages crawled: {len(seen)}")
