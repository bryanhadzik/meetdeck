"""Pull entry files from Google Drive share links (no Google account needed for
"Anyone with the link" files and folders)."""
import csv
import html
import io
import re
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (X11; Linux x86_64) SwimMeet/1.0"
ID = r"[A-Za-z0-9_-]{10,}"


class NotShared(Exception):
    pass


def parse_link(url: str):
    """-> (kind, id) where kind is folder | doc | sheet | file, or None."""
    u = url.strip()
    for kind, pat in (("folder", rf"/folders/({ID})"), ("folder", rf"embeddedfolderview\?id=({ID})"),
                      ("doc", rf"docs\.google\.com/document/(?:u/\d+/)?d/({ID})"),
                      ("sheet", rf"docs\.google\.com/spreadsheets/(?:u/\d+/)?d/({ID})"),
                      ("file", rf"/file/(?:u/\d+/)?d/({ID})"), ("file", rf"[?&]id=({ID})")):
        m = re.search(pat, u)
        if m:
            return kind, m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{25,}", u):
        return "file", u
    return None


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        r = urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 404):
            raise NotShared("Google says this item isn't shared publicly (or doesn't exist)")
        raise
    data = r.read(60 * 1024 * 1024)
    if "accounts.google.com" in r.geturl() or "ServiceLogin" in r.geturl():
        raise NotShared("this item isn't shared as 'Anyone with the link'")
    return data, r.headers, r.geturl()


def _filename(headers, fallback: str) -> str:
    cd = headers.get("Content-Disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
    if m:
        return urllib.parse.unquote(m.group(1))
    m = re.search(r'filename="([^"]+)"', cd)
    return m.group(1) if m else fallback


def _is_html(headers, data: bytes) -> bool:
    return "text/html" in headers.get("Content-Type", "") or data[:15].lstrip().lower().startswith((b"<!doctype", b"<html"))


def fetch(kind: str, fid: str, name_hint: str = ""):
    """-> (filename, bytes) for a file, Google Doc (as .docx) or Google Sheet (as tab-separated .txt)."""
    if kind == "doc":
        data, h, _ = _get(f"https://docs.google.com/document/d/{fid}/export?format=docx")
        if _is_html(h, data):
            raise NotShared("this Google Doc isn't shared as 'Anyone with the link'")
        name = _filename(h, (name_hint or fid) + ".docx")
        return (name if name.lower().endswith(".docx") else name + ".docx"), data
    if kind == "sheet":
        data, h, _ = _get(f"https://docs.google.com/spreadsheets/d/{fid}/export?format=csv")
        if _is_html(h, data):
            raise NotShared("this Google Sheet isn't shared as 'Anyone with the link'")
        rows = csv.reader(io.StringIO(data.decode("utf-8", errors="replace")))
        text = "\n".join("\t".join(c for c in row).rstrip() for row in rows)
        name = re.sub(r"\.csv$", "", _filename(h, name_hint or fid), flags=re.I)
        return name + ".txt", text.encode()
    data, h, _ = _get(f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t")
    if _is_html(h, data):
        txt = data.decode("utf-8", errors="replace")
        if "accounts.google.com" in txt or "Sign in" in txt:
            raise NotShared("this file isn't shared as 'Anyone with the link'")
        raise NotShared("Google returned a web page instead of the file (it may be private or too big)")
    return _filename(h, name_hint or fid), data


def list_folder(fid: str):
    """Files in a public folder: [{id, name, kind}] (kind: file | doc | sheet | folder | other)."""
    data, h, _ = _get(f"https://drive.google.com/embeddedfolderview?id={fid}")
    page = data.decode("utf-8", errors="replace")
    if "flip-entry" not in page and ("accounts.google.com" in page or "Sign in" in page):
        raise NotShared("this folder isn't shared as 'Anyone with the link'")
    out = []
    for m in re.finditer(r'<div class="flip-entry" id="entry-([^"]+)".*?<a href="([^"]+)".*?'
                         r'<div class="flip-entry-title">(.*?)</div>', page, re.S):
        eid, href, title = m.group(1), html.unescape(m.group(2)), html.unescape(m.group(3)).strip()
        kind = ("folder" if "/folders/" in href else "doc" if "/document/" in href else
                "sheet" if "/spreadsheets/" in href else "file" if "/file/" in href else "other")
        out.append({"id": eid, "name": title, "kind": kind})
    return out


SUPPORTED = (".hy3", ".zip", ".cl2", ".sd3", ".docx", ".txt")


def importable(item: dict) -> bool:
    return item["kind"] in ("doc", "sheet") or (item["kind"] == "file" and item["name"].lower().endswith(SUPPORTED))



# ---- write access through Bryan's own Apps Script ("bridge") -----------------
import base64
import json as _json

APPS_SCRIPT = r"""// MeetDeck <-> Google Drive bridge.
// Runs as you, and only works inside your swim meets folder. It never deletes anything.
const ROOT_ID = "__ROOT__";
const TOKEN = "__TOKEN__";

// Run this once from the editor (Run button) to grant access before deploying.
function authorize() {
  var root = DriveApp.getFolderById(ROOT_ID);
  Logger.log("OK - this script can reach: " + root.getName());
}

function doPost(e) {
  var req;
  try { req = JSON.parse(e.postData.contents); } catch (err) { return out({error: "bad request"}); }
  if (req.token !== TOKEN) return out({error: "bad token"});
  var root = DriveApp.getFolderById(ROOT_ID);
  try {
    if (req.action === "ping") return out({ok: true, name: root.getName()});
    if (req.action === "ensure") return out({id: ensure(root, req.path).getId()});
    if (req.action === "move") {
      var it = req.folder ? DriveApp.getFolderById(req.id) : DriveApp.getFileById(req.id);
      if (!inside(it)) return out({error: "not inside the swim folder"});
      it.moveTo(ensure(root, req.path));
      return out({ok: true});
    }
    if (req.action === "upload") {
      var dest = ensure(root, req.path);
      var blob = Utilities.newBlob(Utilities.base64Decode(req.data), req.mime || "application/octet-stream", req.name);
      return out({id: dest.createFile(blob).getId()});
    }
    return out({error: "unknown action"});
  } catch (err) { return out({error: String(err)}); }
}

function ensure(root, path) {
  var f = root;
  (path || []).forEach(function (p) {
    var it = f.getFoldersByName(p);
    f = it.hasNext() ? it.next() : f.createFolder(p);
  });
  return f;
}

function inside(item) {
  var queue = [item], seen = {};
  for (var depth = 0; depth < 12 && queue.length; depth++) {
    var next = [];
    for (var i = 0; i < queue.length; i++) {
      var ps = queue[i].getParents();
      while (ps.hasNext()) {
        var p = ps.next();
        if (p.getId() === ROOT_ID) return true;
        if (!seen[p.getId()]) { seen[p.getId()] = true; next.push(p); }
      }
    }
    queue = next;
  }
  return false;
}

function out(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
"""


def script_for(root_id: str, token: str) -> str:
    return APPS_SCRIPT.replace("__ROOT__", root_id).replace("__TOKEN__", token)


def bridge(url: str, token: str, action: str, **kw) -> dict:
    body = _json.dumps({"token": token, "action": action, **kw}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        r = urllib.request.urlopen(req, timeout=120)   # Apps Script answers through a redirect; urllib follows it
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("Google wants a sign-in for the script - its deployment access must be 'Anyone' "
                               "(Deploy > Manage deployments > edit > Who has access: Anyone > New version > Deploy)")
        raise
    txt = r.read().decode("utf-8", errors="replace")
    try:
        res = _json.loads(txt)
    except ValueError:
        raise RuntimeError("The Drive script didn't answer properly - check it's deployed as a web app with access 'Anyone'")
    if res.get("error"):
        raise RuntimeError(res["error"])
    return res


def upload(url: str, token: str, path: list, name: str, data: bytes, mime: str = "application/zip") -> dict:
    return bridge(url, token, "upload", path=path, name=name, mime=mime, data=base64.b64encode(data).decode())


# ---- organizing the folder ----------------------------------------------------
def tidy_name(n: str) -> str:
    """'Morgan@Grantsvillemeet24' -> 'Morgan @ Grantsville' (the folder already starts with the date)."""
    n = (n or "").strip()
    n = re.sub(r"(?<=[a-z])meet(?=\d*$)", "", n)              # 'Grantsvillemeet24'
    n = re.sub(r"[\s-]*(?:\d{1,2}-\d{1,2}-\d{2,4})$", "", n)  # trailing date like -1-22-26
    n = re.sub(r"(?<=[A-Za-z])\s*(?:19|20)?\d{2}$", "", n)    # trailing year 24 / 2025
    n = re.sub(r"\s*@\s*", " @ ", n)
    n = re.sub(r"\s*&\s*", " & ", n)
    n = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n)                # MelRoberts -> Mel Roberts
    small = {"and", "of", "the", "at", "vs"}
    words = [w if (w.isupper() or not w.isalpha() or w.lower() in small) else w[:1].upper() + w[1:] for w in n.split()]
    return re.sub(r"\s+", " ", " ".join(words)).strip(" -") or "Meet"


def season_of(date: str) -> str:
    y, m = int(date[:4]), int(date[5:7])
    y = y if m >= 7 else y - 1
    return f"{y}-{(y + 1) % 100:02d}"


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def plan(inventory: list) -> dict:
    """Where every file in the folder should live: <season>/<YYYY-MM-DD Meet name>/."""
    meets = {}                       # date -> {name, names}
    for it in inventory:
        if it.get("start") and it.get("meet"):
            d = it["start"][:10]
            m = meets.setdefault(d, {"date": d, "names": []})
            m["names"].append(it["meet"])
    for m in meets.values():         # prefer a real name over "Demo Meet" and the most common spelling
        good = [n for n in m["names"] if "demo" not in n.lower()] or m["names"]
        m["name"] = tidy_name(max(set(good), key=lambda n: (good.count(n), len(n))))
        m["folder"] = [season_of(m["date"]), f"{m['date']} {m['name']}"]
        m["keys"] = {_key(n) for n in m["names"]} | {_key(m["name"])}
    def find(it):
        if it.get("start"):
            return meets.get(it["start"][:10])
        k = _key(it.get("meet") or "")
        for m in meets.values():
            if k and k in m["keys"]:
                return m
        fk = _key(it.get("name") or it["path"].rsplit("/", 1)[-1])
        for m in sorted(meets.values(), key=lambda m: -len(max(m["keys"], key=len))):
            if any(len(x) >= 8 and x in fk for x in m["keys"]):
                return m
        return None
    moves, unsorted = [], []
    top_folders = {it["path"]: it for it in inventory if it["kind"] == "folder"}
    handled_folders = set()
    for it in inventory:
        parent = it["path"].rsplit("/", 1)[0]
        if it["kind"] == "folder":
            name = it["path"].rsplit("/", 1)[-1]
            # season folders ("2025-26", "25-26") and meet folders ("2025-01-09 ...") are ours - never move them
            if re.fullmatch(r"\d{2,4}-\d{2}", name) or re.match(r"\d{4}-\d{2}-\d{2} ", name):
                continue
            # a folder of extracted entry files ("Meet Entries-...-001") moves as one piece
            m = find({"path": it["path"], "name": name})
            if m:
                handled_folders.add(it["path"])
                if "/".join(m["folder"]) != parent.strip("/"):
                    moves.append({"id": it["id"], "folder": True, "from": it["path"], "to": m["folder"]})
            continue
        if parent in handled_folders:
            continue
        if any(re.match(r"\d{4}-\d{2}-\d{2} ", seg) for seg in parent.strip("/").split("/")):
            continue    # already filed in a meet folder (by Organize or by a backup upload) - leave it there
        m = find(it)
        if m:
            if "/".join(m["folder"]) != parent.strip("/"):
                moves.append({"id": it["id"], "folder": False, "from": it["path"], "to": m["folder"]})
        else:
            unsorted.append(it["path"])
    meets_out = sorted(({"date": m["date"], "name": m["name"], "folder": "/".join(m["folder"])} for m in meets.values()),
                       key=lambda m: m["date"])
    return {"meets": meets_out, "moves": moves, "unsorted": unsorted}


def walk(fid: str, path: str = "", depth: int = 0):
    for it in list_folder(fid):
        p = f"{path}/{it['name']}"
        if it["kind"] == "folder":
            yield {"path": p, "id": it["id"], "kind": "folder", "name": it["name"]}
            if depth < 4:
                yield from walk(it["id"], p, depth + 1)
        else:
            yield {"path": p, "id": it["id"], "kind": it["kind"], "name": it["name"]}


def _hy3_meet(data: bytes) -> dict:
    t = data.decode("latin-1", errors="replace")
    b1 = next((l for l in t.splitlines() if l.startswith("B1")), "")
    return {"meet": b1[2:47].strip(), "teams": sorted({l[2:7].strip() for l in t.splitlines() if l.startswith("C1")})}


def inventory(root: str, read_mdb, progress=None) -> list:
    """Every file under the folder with the meet it belongs to (read from inside the file)."""
    import zipfile as _zf
    out = []
    for it in walk(root):
        if it["kind"] == "file":
            n = it["name"].lower()
            try:
                if n.endswith((".zip", ".mdb", ".hy3")):
                    _, data = fetch("file", it["id"], it["name"])
                    if n.endswith(".mdb"):
                        it.update(read_mdb(data))
                    elif n.endswith(".hy3"):
                        it.update(_hy3_meet(data))
                    else:
                        z = _zf.ZipFile(io.BytesIO(data))
                        names = z.namelist()
                        mdbs = [x for x in names if x.lower().endswith(".mdb")]
                        hy3s = [x for x in names if x.lower().endswith(".hy3")]
                        if mdbs:
                            it.update(read_mdb(z.read(mdbs[0])))
                        elif hy3s:
                            it.update(_hy3_meet(z.read(hy3s[0])))
            except Exception as e:
                it["error"] = str(e)[:200]
        out.append(it)
        if progress:
            progress(len(out), it["path"])
    return out
