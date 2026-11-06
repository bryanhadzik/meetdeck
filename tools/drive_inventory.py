"""Read every meet file in Bryan's Drive swim folder and record what meet it belongs to.
Run inside the swimmeet container: python /work/tools/drive_inventory.py <folder_id>"""
import io, json, re, subprocess, sys, tempfile, zipfile
from pathlib import Path
sys.path[:0] = ["/app"]
import drive

MMDB = "/opt/mmdb"


def read_mdb(data: bytes) -> dict:
    with tempfile.TemporaryDirectory() as t:
        p = Path(t) / "m.mdb"
        p.write_bytes(data)
        r = subprocess.run(["java", "-cp", f"{MMDB}/lib/*:{MMDB}", "Builder", "--read-master", str(p)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode:
            return {"error": r.stderr.strip().splitlines()[-1:]}
        info = json.loads(r.stdout.strip().splitlines()[-1])
        m = info.get("meet", {})
        return {"meet": m.get("Meet_name1"), "start": m.get("Meet_start"), "location": m.get("Meet_location")}


def hy3_info(data: bytes) -> dict:
    t = data.decode("latin-1", errors="replace")
    a1 = next((l for l in t.splitlines() if l.startswith("B1")), "")
    teams = sorted({l[2:7].strip() for l in t.splitlines() if l.startswith("C1")})
    m = re.search(r"(\d{8})", a1[45:100])
    return {"meet": a1[2:47].strip(), "date_raw": a1[47:55].strip(), "teams": teams}


def walk(fid, path=""):
    for it in drive.list_folder(fid):
        p = f"{path}/{it['name']}"
        if it["kind"] == "folder":
            yield {"path": p, "id": it["id"], "kind": "folder"}
            yield from walk(it["id"], p)
        else:
            yield {"path": p, "id": it["id"], "kind": it["kind"], "name": it["name"]}


out = []
for it in walk(sys.argv[1]):
    if it["kind"] != "folder":
        n = it["name"].lower()
        try:
            if n.endswith((".zip", ".mdb", ".hy3")):
                _, data = drive.fetch("file", it["id"], it["name"])
                it["size"] = len(data)
                if n.endswith(".mdb"):
                    it.update(read_mdb(data))
                elif n.endswith(".hy3"):
                    it.update(hy3_info(data))
                else:
                    z = zipfile.ZipFile(io.BytesIO(data))
                    it["contents"] = z.namelist()
                    mdbs = [x for x in z.namelist() if x.lower().endswith(".mdb")]
                    hy3s = [x for x in z.namelist() if x.lower().endswith(".hy3")]
                    if mdbs:
                        it.update(read_mdb(z.read(mdbs[0])))
                    elif hy3s:
                        it.update(hy3_info(z.read(hy3s[0])))
        except Exception as e:
            it["error"] = str(e)[:200]
    out.append(it)
    print(json.dumps(it), flush=True)
Path("/data/drive-inventory.json").write_text(json.dumps(out, indent=1))
