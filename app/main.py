import io
import os
import json
import re
import secrets
import time
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from hy3 import POOL_LANES, _list, checksum, clean_hy3, combine_plan, lane_plan, parse_hy3, read_upload, seed_meet, validate

from paths import DATA_ROOT
DATA = DATA_ROOT / "meets"
DATA.mkdir(parents=True, exist_ok=True)
STATIC = Path(__file__).parent / "static"
DEFAULT_RULES = {"max_individual": 2, "max_total": 4, "team_cap_per_event": 0, "meet_type": "regular"}

app = FastAPI(title="Swim Meet Entries")


def _dir(mid: str) -> Path:
    if not re.fullmatch(r"[a-z0-9]{8}", mid):
        raise HTTPException(404)
    d = DATA / mid
    if not d.exists():
        raise HTTPException(404, "meet not found")
    return d


def _meta(d: Path) -> dict:
    return json.loads((d / "meta.json").read_text())


def _save(d: Path, meta: dict):
    (d / "meta.json").write_text(json.dumps(meta, indent=1))


SETTINGS = DATA.parent / "settings.json"


def season_of(date_str: str = "", ts: float | None = None) -> str:
    """High school swim season label, e.g. '2026-27' (a season starts in July)."""
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(date_str) if date_str else _dt.date.fromtimestamp(ts or time.time())
    except ValueError:
        d = _dt.date.today()
    y = d.year if d.month >= 7 else d.year - 1
    return f"{y}-{(y + 1) % 100:02d}"


def _meet_season(m: dict) -> str:
    return season_of(m["date"]) if m.get("date") else (m.get("season") or season_of(ts=m.get("created")))


def _write_settings(st: dict):
    tmp = SETTINGS.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    os.replace(tmp, SETTINGS)        # all-or-nothing, so a crash can't leave an empty file


def _settings() -> dict:
    try:
        s = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    except ValueError:          # half-written file (PC switched off mid-save): start from defaults
        s = {}
    s.setdefault("season", season_of())
    s.setdefault("time_tolerance", 0.30)   # seconds: pad / backup / timers differing by more than this is highlighted
    return s


def _hy3s(d: Path):
    return sorted(f for f in (d / "files").iterdir() if f.suffix.lower() == ".hy3")


def _parsed(d: Path):
    files = _hy3s(d)
    return [parse_hy3(f.read_bytes(), f.name) for f in files]


def _nice_date(s):
    import datetime
    try:
        d = datetime.date.fromisoformat(s)
        return f"{d:%A}, {d:%B} {d.day}"
    except Exception:
        return s


def _apply_seed_moves(moves: dict, entries: list, removed: set, seed_lanes: dict, combo_lanes: dict) -> set:
    """Hand moves made in the Seeding section, laid over the automatic seeding. A swimmer sitting in a
    moved-to spot (that wasn't moved by hand itself) is swapped into the mover's old spot."""
    by_id = {e["id"]: e for e in entries}
    moved = set()
    for eid, hl in moves.items():
        e = by_id.get(eid)
        if not e or eid in removed:
            continue
        pos = combo_lanes if eid in combo_lanes else seed_lanes
        old = tuple(pos.get(eid) or ())
        new = (int(hl[0]), int(hl[1]))
        if old == new:
            moved.add(eid)
            continue
        for oid, ohl in list({**seed_lanes, **combo_lanes}.items()):
            if oid != eid and tuple(ohl) == new and by_id.get(oid, {}).get("event_no") == e["event_no"] and oid not in moves:
                opos = combo_lanes if oid in combo_lanes else seed_lanes
                if old:
                    opos[oid] = old
                else:
                    opos.pop(oid, None)
        pos[eid] = new
        moved.add(eid)
    return moved


def _state(d: Path) -> dict:
    meta = _meta(d)
    parsed = _parsed(d)
    teams, swimmers, entries, files = {}, {}, [], []
    for p in parsed:
        teams.update(p["teams"])
        swimmers.update(p["swimmers"])
        entries.extend(p["entries"])
        sc = _sidecar(d / "files" / p["source"])
        files.append({"name": p["source"], "teams": list(p["teams"]), "entries": len(p["entries"]),
                      "bad_checksums": p["bad_checksums"], "kind": sc.get("kind", "hy3"),
                      "kind_label": KIND_LABEL.get(sc.get("kind", "hy3"), ""), "original": sc.get("original", p["source"]),
                      "source": sc.get("source", "upload"), "received": sc.get("received", ""),
                      "warnings": sc.get("warnings", [])})
    entries.extend(_added_entries(meta, swimmers))
    valid_ids = {e["id"] for e in entries}
    removed = set(meta.get("removed", [])) & valid_ids
    rules = {**DEFAULT_RULES, **meta.get("rules", {})}
    issues = validate(swimmers, entries, removed, rules, {c: t.get("name", c) for c, t in teams.items()})
    lanes = meta.get("lanes", {})
    # Teams with no swimmers (e.g. a stray parent-team block) don't get lanes.
    racing = [t for t in teams if any(s["team"] == t for s in swimmers.values())] or list(teams)
    order = [t for t in lanes.get("order", []) if t in racing] + [t for t in racing if t not in lanes.get("order", [])]
    for t in teams:
        if t not in racing:
            n = sum(1 for e in entries if e["team"] == t and e["id"] not in removed)
            if n:
                issues.append({"level": "warn", "swimmer": None, "teams": [], "coach": "",
                               "entries": [e["id"] for e in entries if e["team"] == t and e["id"] not in removed],
                               "msg": f"{teams[t]['name']} ({t}) has {n} entr{'y' if n == 1 else 'ies'} but no swimmers - probably a stray; remove unless you want it in the meet"})
    lanes = {"order": order, "count": POOL_LANES, "first": 1}      # every pool we run is 8 lanes
    # same swimmer name on two different teams
    by_name: dict[str, set] = {}
    shown: dict[str, str] = {}
    for s_ in swimmers.values():
        k_ = f"{s_['first'].lower()} {s_['last'].lower()}"
        by_name.setdefault(k_, set()).add(s_["team"])
        shown.setdefault(k_, f"{s_['first']} {s_['last']}")
    for nm, tms in by_name.items():
        if len(tms) > 1:
            ids = [e["id"] for e in entries if e["id"] not in removed and any(
                f"{swimmers[k]['first'].lower()} {swimmers[k]['last'].lower()}" == nm for k in e["swimmers"] if k in swimmers)]
            issues.append({"level": "warn", "swimmer": None, "entries": ids, "teams": sorted(tms),
                           "coach": f"{shown[nm]} is entered for both {_list(sorted(teams[x].get('name', x) for x in tms))}. Please confirm which team they swim for.",
                           "msg": f"{shown[nm]} appears on {len(tms)} teams ({', '.join(sorted(tms))}) - same swimmer entered twice?"})
    # per-team status board
    team_status = []
    act = [e for e in entries if e["id"] not in removed]
    for code, t in teams.items():
        sw = [x for x in swimmers.values() if x["team"] == code]
        te = [e for e in act if e["team"] == code]
        tids = {e["id"] for e in entries if e["team"] == code}
        tsw = {x["key"] for x in sw}
        ti = [i for i in issues if (set(i["entries"]) & tids) or (i.get("swimmer") in tsw)]
        f = next((f for f in files if code in f["teams"]), {})
        team_status.append({"code": code, "name": t.get("name", code), "girls": sum(x["gender"] in "FWG" for x in sw),
                            "boys": sum(x["gender"] not in "FWG" for x in sw),
                            "individual": sum(e["kind"] == "ind" for e in te), "relays": sum(e["kind"] == "relay" for e in te),
                            "removed": sum(1 for e in entries if e["team"] == code and e["id"] in removed),
                            "errors": sum(i["level"] == "error" for i in ti), "warnings": sum(i["level"] == "warn" for i in ti),
                            "file": f.get("name", ""), "original": f.get("original", ""), "kind_label": f.get("kind_label", ""),
                            "received": f.get("received", ""), "parse_warnings": len(f.get("warnings", []))})
    coach_msgs = []
    for ts in team_status:
        code = ts["code"]
        mine = [i for i in issues if code in i.get("teams", []) and i.get("coach")]
        notes = [w for f in files if code in f["teams"] for w in f.get("warnings", [])
                 if not w.startswith("line") or "read as" not in w]
        if not mine and not notes:
            continue
        lines = [f"Hi Coach,", "",
                 f"Thanks for sending {ts['name']}'s entries for {meta['name']}" + (f" on {_nice_date(meta.get('date'))}" if meta.get("date") else "") + ".",
                 "Before I can finish the meet, please take a look at the following and send back a corrected entry file (or just reply with the changes):", ""]
        n = 0
        for i in sorted(mine, key=lambda x: x["level"] != "error"):
            n += 1
            lines.append(f"{n}. {i['coach']}")
        if notes:
            lines += ["", "A few things from your entry list I'd like you to double-check:"]
            lines += [f"- {re.sub(r'^line \d+: ', '', w)}" for w in notes]
        lines += ["", "Thanks!"]
        coach_msgs.append({"team": code, "name": ts["name"], "count": len(mine) + len(notes),
                           "errors": sum(i["level"] == "error" for i in mine), "text": "\n".join(lines)})
    expected = []
    for ex in meta.get("expected_teams", []):
        hit = next((ts["code"] for ts in team_status if ex.lower() in (ts["code"].lower(), ts["name"].lower())
                    or ex.lower() in ts["name"].lower()), None)
        expected.append({"name": ex, "received": hit})
    for e in entries:
        e["removed"] = e["id"] in removed
        e.pop("lines", None)
    combos, combo_lanes = combine_plan(entries, removed, int(lanes["count"]), int(lanes["first"]),
                                       meta.get("combine_low", "F"), set(meta.get("combine", [])))
    for c in combos:
        if c["selected"] and not c["fits"]:
            issues.append({"level": "error", "swimmer": None, "entries": [], "teams": [], "coach": "",
                           "msg": f"Combined {c['label']} no longer fits in one heat ({c.get('why', '')}) - it will be seeded normally"})
    plan = lane_plan(order, POOL_LANES, 1)
    preseed = meta.get("preseed", bool(meta.get("seed_moves")))   # seeded only after "Seed heats" is clicked
    min_heat = 3          # fixed: every heat gets at least 3 swimmers
    seed_lanes, seed_info = ({}, [])
    if preseed and plan:
        seed_lanes, seed_info = seed_meet(entries, removed, plan, min_heat, skip=set(combo_lanes))
    seed_moved = _apply_seed_moves(meta.get("seed_moves", {}), entries, removed, seed_lanes, combo_lanes)
    host = next((h for h in _hosts() if h["id"] == meta.get("host", "THS")), None) or {"id": "THS", "team_codes": [], "short": "?"}
    st_lanes = {"order": order}
    auto_rt = _record_team({"lanes": st_lanes}, host, {})
    return {"id": d.name, "name": meta["name"], "date": meta.get("date", ""), "location": meta.get("location", ""), "season": _meet_season(meta), "rules": rules,
            "store": _store(d), "imported_drive": meta.get("imported_drive", []),
            "run": meta.get("run", {}), "ended": meta.get("ended", ""), "contacts": meta.get("contacts", {}),
            "coach_emails": sorted({e.lower() for x in [t.get("email", "") for t in teams.values()] + [f.get("source", "") for f in files]
                                    for e in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", x or "")}),
            "drive_uploads": meta.get("drive_uploads", []),
            "has_db": (d / "db" / "meet.mdb").exists(),
            "host": host["id"], "host_name": host.get("name", ""),
            "record_team": meta.get("record_team"), "record_team_auto": auto_rt,
            "files": files, "teams": teams, "swimmers": swimmers, "entries": entries,
            "issues": issues, "lanes": lanes,
            "combos": combos, "combine_low": meta.get("combine_low", "F"),
            "team_status": team_status, "expected_teams": expected, "coach_msgs": coach_msgs,
            "combo_lanes": {k: list(v) for k, v in combo_lanes.items()},
            "preseed": preseed, "min_heat": min_heat, "seed_info": seed_info,
            "seed_lanes": {k: list(v) for k, v in seed_lanes.items()}, "seed_moved": sorted(seed_moved),
            "lane_plan": plan}


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/meets")
def list_meets():
    out = []
    for d in sorted(DATA.iterdir(), reverse=True):
        if (d / "meta.json").exists():
            m = _meta(d)
            out.append({"id": d.name, "name": m["name"], "date": m.get("date", ""), "host": m.get("host", "THS"),
                        "season": _meet_season(m),
                        "created": m.get("created", 0),
                        "files": len(_hy3s(d))})
    return sorted(out, key=lambda m: m["created"], reverse=True)


@app.get("/api/settings")
def get_settings():
    st = _settings()
    cur = season_of()
    y = int(cur[:4])
    seasons = {f"{y + i}-{(y + i + 1) % 100:02d}" for i in (-1, 0, 1)} | {m["season"] for m in list_meets()} | {st["season"]}
    pub = {k: v for k, v in st.items() if k != "drive_token"}
    return {**pub, "current": cur, "seasons": sorted(seasons, reverse=True), "drive_write": bool(st.get("drive_url"))}


@app.put("/api/settings")
def put_settings(body: dict):
    st = _settings()
    if re.fullmatch(r"\d{4}-\d{2}", body.get("season", "")):
        st["season"] = body["season"]
    if "drive_folder" in body:
        import drive as _d
        got = _d.parse_link(body["drive_folder"] or "")
        if body["drive_folder"] and (not got or got[0] != "folder"):
            raise HTTPException(400, "That isn't a Google Drive folder link")
        st["drive_folder"] = got[1] if got else ""
    if "time_tolerance" in body:
        try:
            v = round(float(body["time_tolerance"]), 2)
        except (TypeError, ValueError):
            raise HTTPException(400, "Enter the tolerance in seconds, e.g. 0.30")
        if not 0 < v <= 5:
            raise HTTPException(400, "Pick a tolerance between 0.01 and 5 seconds")
        st["time_tolerance"] = v
    if "drive_url" in body:
        u = (body["drive_url"] or "").strip()
        if u and not re.match(r"https://script\.google\.com/(?:a/macros/[\w.-]+|macros)/s/[\w-]+/exec", u):
            raise HTTPException(400, "Paste the web app URL from Apps Script (it ends in /exec)")
        st["drive_url"] = u
    _write_settings(st)
    return get_settings()


@app.post("/api/meets")
def create_meet(body: dict):
    mid = secrets.token_hex(4)
    d = DATA / mid
    (d / "files").mkdir(parents=True)
    _save(d, {"name": body.get("name") or "Untitled meet", "date": body.get("date", ""),
              "host": body.get("host") or "THS", "season": body.get("season") or _settings()["season"],
              "created": time.time(), "removed": [], "rules": DEFAULT_RULES})
    return {"id": mid}


@app.get("/api/meets/{mid}")
def get_meet(mid: str):
    return _state(_dir(mid))


@app.delete("/api/meets/{mid}")
def delete_meet(mid: str):
    import shutil as _sh
    _sh.rmtree(_dir(mid))
    return {"ok": True}


KIND_LABEL = {"hy3": "Team Manager export (.hy3)", "sdif": "Team Manager/SDIF (.cl2/.sd3)",
              "docx": "Word entry list", "text": "Typed entry list", "paste": "Pasted entry list"}


def _sidecar(f: Path) -> dict:
    j = f.with_name(f.name + ".json")
    return json.loads(j.read_text()) if j.exists() else {"kind": "hy3", "original": f.name, "warnings": []}


def _master_events(hid: str) -> list[dict]:
    m = _read_master(hid)
    if not m.get("loaded"):
        raise HTTPException(400, "The host school has no master file yet - it's needed to number events in Word/SDIF entries")
    return m["events"]


def ingest(d: Path, filename: str, data: bytes, source: str = "upload", kind_hint: str | None = None) -> dict:
    """Add one received file (any supported format) to a meet. Returns {added, replaced, skipped, warnings}."""
    from importers import detect, docx_text, parse_entry_list, parse_sdif, to_hy3
    out = {"added": [], "replaced": [], "skipped": [], "warnings": []}
    try:
        found = [(kind_hint, filename, data)] if kind_hint else detect(filename, data)
    except zipfile.BadZipFile:
        found = []
    if any(k == "hy3" for k, _, _ in found):     # a Team Manager zip often carries the same entries twice
        found = [x for x in found if x[0] != "sdif"]
    if not found:
        out["skipped"].append(f"{filename}: not an entry file I can read (.hy3, .zip, .cl2, .sd3, .docx or .txt)")
        _keep_as_doc(d, filename, data, out)
        return out
    meta = _meta(d)
    orig_dir = d / "originals"
    orig_dir.mkdir(exist_ok=True)
    orig_name = re.sub(r"[^A-Za-z0-9._ &-]", "_", filename)
    (orig_dir / orig_name).write_bytes(data)
    for kind, name, content in found:
        warnings: list[str] = []
        if kind == "hy3":
            hy3 = content
        else:
            try:
                if kind == "sdif":
                    parsed = parse_sdif(content)
                elif kind == "docx":
                    parsed = parse_entry_list(docx_text(content))
                else:   # "text" / "paste"
                    parsed = parse_entry_list(content.decode("utf-8", errors="replace"))
            except Exception as e:  # unreadable file: report, don't crash the upload
                out["skipped"].append(f"{name}: couldn't read it ({e})")
                continue
            warnings = parsed["warnings"]
            if not parsed["teams"] or not any(t["swimmers"] for t in parsed["teams"]):
                out["skipped"].append(f"{name}: no teams/swimmers found" + (f" - {warnings[0]}" if warnings else ""))
                continue
            hy3, w2 = to_hy3(parsed, _master_events(meta.get("host", "THS")), meta["name"])
            warnings += w2
        safe = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(name).stem if kind != "hy3" else name)
        if kind != "hy3":
            safe = f"{safe} ({kind}).hy3"
        new_teams = set(parse_hy3(hy3, safe)["teams"])
        if not new_teams:
            out["skipped"].append(f"{name}: no team (C1) record found")
            continue
        for old in _hy3s(d):     # a revised file from the same team replaces the old one
            if old.name != safe and set(parse_hy3(old.read_bytes(), old.name)["teams"]) & new_teams:
                _archive(d, old, "replaced by " + safe)
                out["replaced"].append(old.name)
        if (d / "files" / safe).exists():
            _archive(d, d / "files" / safe, "replaced by a newer copy")
        (d / "files" / safe).write_bytes(hy3)
        (d / "files" / (safe + ".json")).write_text(json.dumps({
            "kind": kind, "original": name, "original_file": orig_name, "source": source,
            "received": time.strftime("%Y-%m-%d %H:%M"),
            "warnings": warnings}))
        out["added"].append(safe)
        out["warnings"] += [f"{name}: {w}" for w in warnings]
    if not out["added"] and kind_hint != "paste":
        (orig_dir / orig_name).unlink(missing_ok=True)
        _keep_as_doc(d, filename, data, out)
    return out


def _keep_as_doc(d: Path, filename: str, data: bytes, out: dict):
    """A file that isn't an entry list (meet invite, results...) is kept under Documents instead."""
    (d / "docs").mkdir(exist_ok=True)
    name = re.sub(r"[^A-Za-z0-9._ &()-]", "_", Path(filename).name) or "file"
    (d / "docs" / name).write_bytes(data)
    out["skipped"].append(f"{filename}: kept under Meet files > Documents")


@app.post("/api/meets/{mid}/upload")
async def upload(mid: str, files: list[UploadFile] = File(...)):
    d = _dir(mid)
    res = {"added": [], "replaced": [], "skipped": [], "warnings": []}
    for uf in files:
        r = ingest(d, uf.filename or "upload", await uf.read())
        for k in res:
            res[k] += r[k]
    return res


@app.post("/api/meets/{mid}/paste")
def paste(mid: str, body: dict):
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "nothing pasted")
    name = re.sub(r"[^A-Za-z0-9 _-]", "", body.get("name") or "") or f"pasted-{time.strftime('%H%M%S')}"
    return ingest(_dir(mid), name + ".txt", text.encode(), source="paste", kind_hint="paste")


@app.delete("/api/meets/{mid}/files/{name}")
def delete_file(mid: str, name: str):
    """Take an entry file out of the meet. It goes to the archive, where it can be restored."""
    d = _dir(mid)
    f = d / "files" / Path(name).name
    if f.exists():
        _archive(d, f, "removed")
    return {"ok": True}


# ---- meet file management ----------------------------------------------------
AREAS = {"originals": "originals", "archive": "archive", "backups": "backups", "docs": "docs"}


def _archive(d: Path, f: Path, why: str):
    a = d / "archive"
    a.mkdir(exist_ok=True)
    side = _sidecar(f)
    dest = a / f"{time.strftime('%Y%m%d-%H%M%S')}__{f.name}"
    f.rename(dest)
    f.with_name(f.name + ".json").unlink(missing_ok=True)
    dest.with_name(dest.name + ".json").write_text(json.dumps({**side, "archived": time.strftime("%Y-%m-%d %H:%M"), "why": why}))


def _orig_for(d: Path, side: dict) -> str:
    if side.get("original_file") and (d / "originals" / side["original_file"]).exists():
        return side["original_file"]
    want = re.sub(r"[^A-Za-z0-9._ &-]", "_", side.get("original", ""))
    od = d / "originals"
    if want and (od / want).exists():
        return want
    stem = Path(want).stem.lower()
    for f in sorted(od.iterdir()) if od.exists() else []:
        if stem and Path(f.name).stem.lower().rstrip("_1") .startswith(stem[:20]):
            return f.name
    return ""


def _store(d: Path) -> dict:
    def ls(area):
        p = d / area
        return sorted((f for f in p.iterdir() if f.is_file() and not f.name.endswith(".json")), key=lambda f: -f.stat().st_mtime) if p.exists() else []
    stamp = lambda f: time.strftime("%Y-%m-%d %H:%M", time.localtime(f.stat().st_mtime))
    entry = []
    for f in _hy3s(d):
        side = _sidecar(f)
        try:
            teams = list(parse_hy3(f.read_bytes(), f.name)["teams"])
        except Exception:
            teams = []
        entry.append({"name": f.name, "teams": teams, "kind": KIND_LABEL.get(side.get("kind", "hy3"), side.get("kind")),
                      "original": side.get("original", f.name), "original_file": _orig_for(d, side),
                      "source": side.get("source", "upload"), "received": side.get("received") or stamp(f),
                      "size": f.stat().st_size})
    archived = []
    for f in ls("archive"):
        j = f.with_name(f.name + ".json")
        side = json.loads(j.read_text()) if j.exists() else {}
        try:
            teams = list(parse_hy3(f.read_bytes(), f.name)["teams"])
        except Exception:
            teams = []
        archived.append({"name": f.name, "shown": f.name.split("__", 1)[-1], "teams": teams,
                         "kind": KIND_LABEL.get(side.get("kind", "hy3"), ""), "original_file": _orig_for(d, side),
                         "archived": side.get("archived") or stamp(f), "why": side.get("why", ""),
                         "received": side.get("received", "")})
    simple = lambda area: [{"name": f.name, "size": f.stat().st_size, "when": stamp(f)} for f in ls(area)]
    return {"entry": entry, "archived": archived, "backups": simple("backups"), "docs": simple("docs"),
            "originals": simple("originals")}


def _area_file(d: Path, area: str, name: str) -> Path:
    if area not in AREAS:
        raise HTTPException(404)
    f = d / AREAS[area] / Path(name).name
    if not f.is_file():
        raise HTTPException(404, "file not found")
    return f


@app.get("/api/meets/{mid}/store/{area}/{name}")
def store_download(mid: str, area: str, name: str):
    f = _area_file(_dir(mid), area, name)
    shown = f.name.split("__", 1)[-1] if area == "archive" else f.name
    return FileResponse(f, filename=shown)


@app.delete("/api/meets/{mid}/store/{area}/{name}")
def store_delete(mid: str, area: str, name: str):
    """Permanent delete - only offered for archived files, backups and documents."""
    if area == "originals":
        raise HTTPException(400, "originals are kept")
    f = _area_file(_dir(mid), area, name)
    f.unlink()
    f.with_name(f.name + ".json").unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/meets/{mid}/archive/{name}/restore")
def archive_restore(mid: str, name: str):
    d = _dir(mid)
    f = _area_file(d, "archive", name)
    shown = f.name.split("__", 1)[-1]
    teams = set(parse_hy3(f.read_bytes(), shown)["teams"])
    for cur in _hy3s(d):     # whatever the restored file replaces goes to the archive
        if cur.name == shown or set(parse_hy3(cur.read_bytes(), cur.name)["teams"]) & teams:
            _archive(d, cur, "replaced by restored " + shown)
    j = f.with_name(f.name + ".json")
    side = json.loads(j.read_text()) if j.exists() else {}
    for k in ("archived", "why"):
        side.pop(k, None)
    f.rename(d / "files" / shown)
    (d / "files" / (shown + ".json")).write_text(json.dumps(side))
    j.unlink(missing_ok=True)
    return {"ok": True, "restored": shown}


@app.post("/api/meets/{mid}/docs")
async def docs_upload(mid: str, files: list[UploadFile] = File(...)):
    d = _dir(mid)
    (d / "docs").mkdir(exist_ok=True)
    saved = []
    for uf in files:
        name = re.sub(r"[^A-Za-z0-9._ &()-]", "_", uf.filename or "document")
        (d / "docs" / name).write_bytes(await uf.read())
        saved.append(name)
    return {"saved": saved}


@app.get("/api/meets/{mid}/export")
def export_all(mid: str):
    """Everything for the meet in one zip: checked entry files, originals, documents, latest backup."""
    d = _dir(mid)
    meta = _meta(d)
    removed = set(meta.get("removed", []))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in _hy3s(d):
            z.writestr(f"entry files (checked)/{f.name}", _clean_file(d, f, removed))
        for area, folder in (("originals", "as received"), ("docs", "documents")):
            p = d / area
            for f in sorted(p.iterdir()) if p.exists() else []:
                if f.is_file():
                    z.write(f, f"{folder}/{f.name}")
        bk = sorted((d / "backups").glob("*.zip"), key=lambda f: f.stat().st_mtime) if (d / "backups").exists() else []
        if bk:
            z.write(bk[-1], f"meet manager backup/{bk[-1].name}")
        z.writestr("meet.json", json.dumps(meta, indent=1))
    safe = re.sub(r"[^A-Za-z0-9 _-]", "", meta["name"]) or "meet"
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{safe} - all files.zip"'})


# ---- Google Drive ------------------------------------------------------------
import drive as drive_mod


def _drive_import(d: Path, kind: str, fid: str, name: str = "") -> dict:
    fn, data = drive_mod.fetch(kind, fid, name)
    r = ingest(d, fn, data, source=f"Google Drive: {fn}"[:200])
    meta = _meta(d)
    meta["imported_drive"] = sorted(set(meta.get("imported_drive", [])) | {fid})
    _save(d, meta)
    return r


@app.post("/api/meets/{mid}/drive")
def drive_link(mid: str, body: dict):
    """A pasted Drive link: files and Google Docs/Sheets are imported; folders are listed to pick from."""
    d = _dir(mid)
    got = drive_mod.parse_link(body.get("url", ""))
    if not got:
        raise HTTPException(400, "That doesn't look like a Google Drive link")
    kind, fid = got
    try:
        if kind == "folder":
            done = set(_meta(d).get("imported_drive", []))
            items = drive_mod.list_folder(fid)
            for it in items:
                it["importable"] = drive_mod.importable(it)
                it["imported"] = it["id"] in done
            return {"folder": fid, "items": items}
        return _drive_import(d, kind, fid)
    except drive_mod.NotShared as e:
        raise HTTPException(403, f"Couldn't open it: {e}. Ask the coach to set sharing to 'Anyone with the link', or download it and drop it in.")


@app.post("/api/meets/{mid}/drive/import")
def drive_import(mid: str, body: dict):
    d = _dir(mid)
    res = {"added": [], "replaced": [], "skipped": [], "warnings": []}
    for it in body.get("items", []):
        try:
            r = _drive_import(d, it.get("kind", "file"), it["id"], it.get("name", ""))
        except drive_mod.NotShared as e:
            r = {"added": [], "replaced": [], "skipped": [f"{it.get('name', it['id'])}: {e}"], "warnings": []}
        for k in res:
            res[k] += r[k]
    return res


@app.post("/api/meets/{mid}/seed-move")
def seed_move(mid: str, body: dict):
    """Move an entry to heat/lane in the seeding (swap if someone in the same event is there).
    body: {id, heat, lane} | {reset: true} | {reset_event: "<event no>"}"""
    d = _dir(mid)
    meta = _meta(d)
    moves = meta.get("seed_moves", {})
    if body.get("reset"):
        moves = {}
    elif body.get("reset_event"):
        st = _state(d)
        ids = {e["id"] for e in st["entries"] if e["event_no"] == str(body["reset_event"])}
        moves = {k: v for k, v in moves.items() if k not in ids}
    else:
        st = _state(d)
        pos = {**st.get("seed_lanes", {}), **st["combo_lanes"]}
        eid, heat, lane = body["id"], int(body["heat"]), int(body["lane"])
        if not 1 <= lane <= POOL_LANES or heat < 1:
            raise HTTPException(400, "No such heat or lane")
        e = next((x for x in st["entries"] if x["id"] == eid), None)
        if not e:
            raise HTTPException(404, "Entry not found")
        old = pos.get(eid)
        other = next((x["id"] for x in st["entries"] if x["id"] != eid and x["event_no"] == e["event_no"] and not x["removed"]
                      and tuple(pos.get(x["id"]) or ()) == (heat, lane)), None)
        moves[eid] = [heat, lane]
        if other:
            if old:
                moves[other] = list(old)
            else:
                moves.pop(other, None)
    meta["seed_moves"] = moves
    _save(d, meta)
    return _state(d)


@app.put("/api/meets/{mid}/state")
def put_state(mid: str, body: dict):
    d = _dir(mid)
    meta = _meta(d)
    for k in ("removed", "rules", "lanes", "name", "date", "location", "host", "combine", "combine_low", "expected_teams", "preseed", "min_heat",
              "run", "ended", "contacts"):
        if k in body:
            meta[k] = body[k]
    if "record_team" in body:
        if body["record_team"] is None:
            meta.pop("record_team", None)   # back to automatic
        else:
            meta["record_team"] = body["record_team"]
    _save(d, meta)
    return _state(d)


def _clean_file(d: Path, f: Path, removed: set[str]) -> bytes:
    data = f.read_bytes()
    p = parse_hy3(data, f.name)
    drop = set()
    for e in p["entries"]:
        if e["id"] in removed:
            drop.update(e["lines"])
    adds = [a for a in _meta(d).get("added", []) if a["file"] == f.name and a["id"] not in removed]
    if not adds:
        return clean_hy3(data, drop)
    lines = data.splitlines(keepends=True)
    eol = b"\r\n" if lines and lines[0].endswith(b"\r\n") else b"\n"
    ins: dict[int, list[bytes]] = {}
    for a in adds:
        ins.setdefault(_insert_at(lines, a), []).extend(l.encode("latin-1") + eol for l in a["lines"])
    out = []
    for i, l in enumerate(lines):
        if i not in drop:
            out.append(l)
        out.extend(ins.get(i, []))
    return b"".join(out)


# ---- entries added here (kept in meta, never written into the coach's file) ----
def _hline(body: str) -> str:
    b = body.ljust(128)[:128]
    return b + checksum(b.encode("latin-1")).decode()


def _put(line: str, col: int, val: str) -> str:
    """Overwrite 1-based column `col` with val."""
    line = line.ljust(128)
    return line[:col - 1] + val + line[col - 1 + len(val):]


def _added_entries(meta: dict, swimmers: dict) -> list[dict]:
    by_mid = {(s["team"], s["meet_id"]): k for k, s in swimmers.items()}
    out = []
    for a in meta.get("added", []):
        mini = "\r\n".join([_hline("C1" + a["team"].ljust(5))] + a["lines"]).encode("latin-1") + b"\r\n"
        p = parse_hy3(mini, a["file"])
        if not p["entries"]:
            continue
        e = p["entries"][0]
        fix = lambda k: by_mid.get((a["team"], k.split("|")[-1]), k)
        e["swimmers"] = [fix(k) for k in e["swimmers"]]
        e["legs"] = {leg: fix(k) for leg, k in e["legs"].items()}
        e.update(id=a["id"], added=True, lines=[])
        out.append(e)
    return out


def _insert_at(lines: list[bytes], a: dict) -> int:
    """Index of the line the added entry goes after: end of the swimmer's block (individual) or of the team block (relay)."""
    rt = lambda i: lines[i][:2]
    c1 = next((i for i in range(len(lines)) if rt(i) == b"C1" and lines[i][2:7].decode("latin-1").strip() == a["team"]), None)
    if c1 is None:
        return len(lines) - 1
    end = c1
    while end + 1 < len(lines) and rt(end + 1) not in (b"C1", b"Z0"):
        end += 1
    if a["kind"] == "relay":
        return end
    for i in range(c1, end + 1):
        if rt(i) == b"D1" and lines[i][3:8].decode("latin-1").strip() == a["mid"]:
            j = i
            while j + 1 <= end and rt(j + 1) not in (b"D1", b"F1", b"C1") and lines[j + 1][:1] in b"DEGH":
                j += 1
            return j
    return end


def _parse_time(v) -> float:
    try:
        return meetdb.parse_time(v)
    except ValueError as e:
        raise HTTPException(400, f"{e} - use 1:05.32, 65.32, 10532 or NT")


@app.post("/api/meets/{mid}/entries")
def add_entry(mid: str, body: dict):
    """body: {event_no, seed, exh, swimmer: key} for an individual swim, or {event_no, seed, team, relay} for a relay."""
    d = _dir(mid)
    meta = _meta(d)
    files = _hy3s(d)
    parsed = [(f, f.read_bytes()) for f in files]
    ps = [(f, data, parse_hy3(data, f.name)) for f, data in parsed]
    st = _state(d)
    ev = str(body.get("event_no", "")).strip()
    seed = _parse_time(body.get("seed"))
    relay = not body.get("swimmer")
    # template: an existing entry line for this event (same file first) so the event fields match exactly
    cands = []
    for f, data, p in ps:
        raw = data.splitlines()
        for e in p["entries"]:
            if e["event_no"] == ev and (e["kind"] == "relay") == relay:
                cands.append((f.name, raw[e["lines"][0]].decode("latin-1"), e))
    if not cands:
        raise HTTPException(400, f"No team has entered event {ev}, so I don't know its details")
    if relay:
        team = body.get("team", "")
        if team not in st["teams"]:
            raise HTTPException(400, "Unknown team")
        fname = st["teams"][team].get("source") or cands[0][0]
        taken = {e.get("relay") for e in st["entries"] if e["team"] == team and e["event_no"] == ev and e["kind"] == "relay" and not e["removed"]}
        letter = (body.get("relay") or next((c for c in "ABCDEFGH" if c not in taken), "")).upper()[:1]
        if not letter or letter in taken:
            raise HTTPException(400, f"{team} already has relay {letter or 'A-H'} in event {ev}")
        tpl = next((c for c in cands if c[0] == fname), cands[0])[1]
        line = _put(_put(tpl, 3, team.ljust(5)[:5]), 8, letter)
        lines_ = [line, _hline("F3")]
        rec = {"kind": "relay", "team": team, "mid": "", "label": f"{team} {letter}"}
    else:
        key = body["swimmer"]
        s = st["swimmers"].get(key)
        if not s:
            raise HTTPException(400, "Unknown swimmer")
        if any(e["event_no"] == ev and key in e["swimmers"] and e["kind"] == "ind" and not e["removed"] for e in st["entries"]):
            raise HTTPException(400, f"{s['first']} {s['last']} is already in event {ev}")
        evg = cands[0][2]["gender"]
        if evg in "FMWB" and s["gender"] and {"W": "F", "B": "M"}.get(evg, evg) != s["gender"]:
            raise HTTPException(400, f"Event {ev} is {cands[0][2]['event']}")
        fname = key.split("|")[0] if "|" in key else cands[0][0]
        tpl = next((c for c in cands if c[0] == fname), cands[0])[1]
        line = _put(tpl, 3, s["gender"][:1] or tpl[2])
        line = _put(line, 4, s["meet_id"].rjust(5)[:5])
        line = _put(line, 9, s["last"][:5].ljust(5))
        line = _put(line, 84, "X" if body.get("exh") else " ")
        lines_ = [line]
        team = s["team"]
        rec = {"kind": "ind", "team": team, "mid": s["meet_id"], "label": f"{s['first']} {s['last']}"}
    for i, l in enumerate(lines_[:1]):
        l = _put(l, 43, f"{seed:8.2f}")
        l = _put(l, 52, f"{seed:8.2f}")
        lines_[0] = _hline(l)
    n = max([int(a["id"].split("-")[1]) for a in meta.get("added", [])] + [0]) + 1
    meta.setdefault("added", []).append({"id": f"add-{n}", "file": fname, "lines": lines_, "event_no": ev,
                                         "when": time.strftime("%Y-%m-%d %H:%M"), **rec})
    _save(d, meta)
    return _state(d)


@app.delete("/api/meets/{mid}/entries/{aid}")
def delete_added(mid: str, aid: str):
    d = _dir(mid)
    meta = _meta(d)
    meta["added"] = [a for a in meta.get("added", []) if a["id"] != aid]
    meta["removed"] = [r for r in meta.get("removed", []) if r != aid]
    _save(d, meta)
    return _state(d)


def _zip_one(name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, content)
    return buf.getvalue()


@app.get("/api/meets/{mid}/download/{name}")
def download_one(mid: str, name: str):
    d = _dir(mid)
    f = d / "files" / Path(name).name
    if not f.exists():
        raise HTTPException(404)
    content = _clean_file(d, f, set(_meta(d).get("removed", [])))
    zname = f.stem + " (checked).zip"
    return Response(_zip_one(f.name, content), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{zname}"'})


@app.get("/api/meets/{mid}/download-all")
def download_all(mid: str):
    d = _dir(mid)
    meta = _meta(d)
    removed = set(meta.get("removed", []))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for f in _hy3s(d):
            z.writestr(f.stem + " (checked).zip", _zip_one(f.name, _clean_file(d, f, removed)))
    safe = re.sub(r"[^A-Za-z0-9 _-]", "", meta["name"]) or "meet"
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{safe} - MM entry files.zip"'})


# ---- Meet Manager database (restore-ready backup) -----------------------------
import shutil
import subprocess
import tempfile
from datetime import datetime
import meetdb

MMDB = Path(os.environ.get("MMDB_DIR", "/opt/mmdb"))
HOSTS_DIR = DATA_ROOT / "hosts"
HOSTS_DIR.mkdir(parents=True, exist_ok=True)
HOSTS_FILE = DATA_ROOT / "hosts.json"
DEFAULT_HOSTS = [
    {"id": "THS", "name": "Tooele High School", "short": "Tooele", "team_codes": ["TOOEL", "THS", "TOOE"], "team_tags": [3]},
    {"id": "SHS", "name": "Stansbury High School", "short": "Stansbury", "team_codes": ["SHS", "STAN", "STANS"], "team_tags": []},
    {"id": "GHS", "name": "Grantsville High School", "short": "Grantsville", "team_codes": ["GHS", "GRANT", "GRAN"], "team_tags": []},
    {"id": "DPHS", "name": "Deseret Peak High School", "short": "Deseret Peak", "team_codes": ["DPHS", "DPEAK", "DP", "DESE"], "team_tags": []},
]


def _hosts() -> list[dict]:
    if not HOSTS_FILE.exists():
        HOSTS_FILE.write_text(json.dumps(DEFAULT_HOSTS, indent=1))
    return json.loads(HOSTS_FILE.read_text())


def _host(hid: str) -> dict:
    h = next((h for h in _hosts() if h["id"] == hid), None)
    if not h:
        raise HTTPException(404, "unknown school")
    return h


def _save_host(h: dict):
    hs = [h if x["id"] == h["id"] else x for x in _hosts()]
    HOSTS_FILE.write_text(json.dumps(hs, indent=1))


def _mpath(hid: str) -> Path:
    d = HOSTS_DIR / hid
    d.mkdir(parents=True, exist_ok=True)
    return d / "master.zip"


# one-time migration: the single template from before becomes Tooele's master
_old = DATA_ROOT / "template" / "backup.zip"
if _old.exists() and not _mpath("THS").exists():
    shutil.copy(_old, _mpath("THS"))


def _unpack(z: Path):
    """(mdb_name, mdb_bytes, hybackup_text) of a Meet Manager backup zip."""
    with zipfile.ZipFile(z) as zf:
        mdb = next((n for n in zf.namelist() if n.lower().endswith(".mdb")), None)
        hyb = next((n for n in zf.namelist() if n.lower() == "hybackup.txt"), None)
        if not mdb:
            raise HTTPException(400, "That backup has no Meet Manager database (.mdb) inside")
        return mdb, zf.read(mdb), (zf.read(hyb).decode("latin-1") if hyb else "")


def _java(*args, timeout=120) -> str:
    """Meet Manager database tool: Builder.java on the server, the Python port (mdbjet) on Windows."""
    if meetdb.JET:
        import mdbjet
        try:
            if args[0] == "--read-master":
                return json.dumps(mdbjet.read_master(args[1]))
            if args[0] == "--write-master":
                return json.dumps(mdbjet.write_master(args[1], args[2]))
            return json.dumps(mdbjet.build(args[0], args[1], args[2]))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Meet Manager database tool failed: {type(e).__name__}: {e}")
    r = subprocess.run(["java", "-cp", f"{MMDB}/lib/*:{MMDB}", "Builder", *map(str, args)],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        lines = [l for l in r.stderr.strip().splitlines() if "WARN" not in l]
        raise HTTPException(500, "Meet Manager database tool failed: " + (lines[0] if lines else "?"))
    return r.stdout.strip().splitlines()[-1]


def _hybackup(tpl_text: str, mdb_name: str, size: int) -> str:
    t = (tpl_text.rstrip("\r\n") or "WIN-MM  8.0".ljust(28)).ljust(340)
    old_path = t[100:200].strip()
    folder = old_path.rsplit("\\", 1)[0] if "\\" in old_path else "C:\\Hy-Sport\\SwMM8"
    now = datetime.now()
    t = (t[:78] + now.strftime("%m/%d/%Y") + now.strftime("%I:%M:%S %p").ljust(12)
         + f"{folder}\\{mdb_name}".ljust(100)[:100] + str(size).ljust(140))
    return t[:340] + "\r\n"


def _pack(mdb_name: str, mdb: bytes, hyb: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("hybackup.txt", _hybackup(hyb, mdb_name, len(mdb)))
        z.writestr(mdb_name, mdb)
    return buf.getvalue()


def _stem(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9@&_ -]", "", name).strip().replace(" ", "")[:40] or "Meet"


def _read_master(hid: str) -> dict:
    z = _mpath(hid)
    if not z.exists():
        return {"loaded": False}
    name, data, hyb = _unpack(z)
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "m.mdb"
        p.write_bytes(data)
        info = json.loads(_java("--read-master", p))
    for r in info["records"]:
        r["time"] = round(r["time"], 2)
    meta = json.loads((z.parent / "info.json").read_text()) if (z.parent / "info.json").exists() else {}
    return {"loaded": True, "mdb": name, "version": hyb[8:18].strip(), "licensee": hyb[28:78].strip(),
            "file": meta.get("file", f"Swmm8Bkup{Path(name).stem}-01.zip"), "updated": meta.get("updated", ""), **info}


def _write_master(hid: str, changes: dict, src: Path | None = None, note: str = "") -> dict:
    """Apply changes to a school's master (or to src, then store it as the master)."""
    z = src or _mpath(hid)
    name, data, hyb = _unpack(z)
    with tempfile.TemporaryDirectory() as tmp:
        p, c = Path(tmp) / "m.mdb", Path(tmp) / "c.json"
        p.write_bytes(data)
        c.write_text(json.dumps(changes))
        _java("--write-master", p, c)
        newname = name
        if changes.get("meet", {}).get("Meet_name1"):
            newname = _stem(changes["meet"]["Meet_name1"]) + ".mdb"
        packed = _pack(newname, p.read_bytes(), hyb)
    mp = _mpath(hid)
    if mp.exists():   # keep the previous version, just in case
        hist = mp.parent / "history"
        hist.mkdir(exist_ok=True)
        shutil.copy(mp, hist / f"master-{time.strftime('%Y%m%d-%H%M%S')}.zip")
    mp.write_bytes(packed)
    (mp.parent / "info.json").write_text(json.dumps({"file": f"Swmm8Bkup{Path(newname).stem}-01.zip",
                                                     "updated": time.strftime("%Y-%m-%d %H:%M") + (f" ({note})" if note else "")}))
    return _read_master(hid)


@app.get("/api/hosts")
def list_hosts():
    out = []
    for h in _hosts():
        z = _mpath(h["id"])
        meta = json.loads((z.parent / "info.json").read_text()) if (z.parent / "info.json").exists() else {}
        out.append({**h, "has_master": z.exists(), "master_updated": meta.get("updated", "")})
    return out


@app.put("/api/hosts/{hid}")
def update_host(hid: str, body: dict):
    h = _host(hid)
    for k in ("name", "short"):
        if k in body:
            h[k] = str(body[k]).strip()
    if "team_codes" in body:
        h["team_codes"] = [c.strip().upper() for c in body["team_codes"] if c.strip()]
    if "team_tags" in body:
        h["team_tags"] = [int(x) for x in body["team_tags"]]
    _save_host(h)
    return h


@app.get("/api/hosts/{hid}/master")
def get_master(hid: str):
    return {"host": _host(hid), **_read_master(hid)}


@app.put("/api/hosts/{hid}/master")
def put_master(hid: str, body: dict):
    _host(hid)
    if not _mpath(hid).exists():
        raise HTTPException(400, "This school has no master yet")
    m = _write_master(hid, body, note="edited")
    return {"host": _host(hid), **m}


@app.post("/api/hosts/{hid}/master")
async def upload_master(hid: str, file: UploadFile = File(...), clean: str = "1"):
    """Upload a Meet Manager backup as this school's master. clean=1 strips teams/athletes/entries."""
    h = _host(hid)
    data = await file.read()
    try:
        zipfile.ZipFile(io.BytesIO(data)).testzip()
    except zipfile.BadZipFile:
        raise HTTPException(400, "Upload the Meet Manager backup .zip (File > Backup in Meet Manager)")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "up.zip"
        src.write_bytes(data)
        _unpack(src)
        changes = {"clear_people": clean == "1"}
        if clean == "1":
            changes["meet"] = {"Meet_name1": f"{h['short']} HS Home Meet - MASTER"}
        m = _write_master(hid, changes, src=src, note=f"uploaded {file.filename}")
    return {"host": h, **m}


@app.post("/api/hosts/{hid}/master/clone")
def clone_master(hid: str, body: dict):
    """Start a school's master from another school's: same events/scoring/settings, its own (empty) records."""
    h, src = _host(hid), _host(body.get("from", "THS"))
    if not _mpath(src["id"]).exists():
        raise HTTPException(400, f"{src['name']} has no master to copy")
    changes = {"clear_people": True,
               "meet": {"Meet_name1": f"{h['short']} HS Home Meet - MASTER", "Meet_location": body.get("location", ""),
                        "Meet_addr1": "", "Meet_city": body.get("city", ""), "Meet_zip": ""},
               "tags": [{"tag_ptr": 1, "order": 1, "name": f"{h['id']} Record"[:12], "flag": "$"},
                        {"tag_ptr": 2, "order": 2, "name": "Pool Record", "flag": "@"}],
               "records": []}
    m = _write_master(hid, changes, src=_mpath(src["id"]), note=f"copied from {src['short']}")
    h["team_tags"] = [1]
    _save_host(h)
    return {"host": h, **m}


@app.get("/api/hosts/{hid}/master/download")
def download_master(hid: str):
    z = _mpath(hid)
    if not z.exists():
        raise HTTPException(404, "no master")
    name, _, _ = _unpack(z)
    return Response(z.read_bytes(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="Swmm8Bkup{Path(name).stem}-01.zip"'})


def _record_team(st: dict, host: dict, meta: dict) -> str:
    if "record_team" in meta:
        return meta["record_team"]
    racing = st["lanes"]["order"]
    match = [t for t in racing if t.upper() in host["team_codes"]]
    return match[0] if len(match) == 1 else ""   # none/several (e.g. intrasquad): records count for everyone


def _spec(d: Path) -> dict:
    st = _state(d)
    meta = _meta(d)
    host = _host(meta.get("host", "THS"))
    active = [e for e in st["entries"] if not e["removed"]]
    used_teams = {e["team"] for e in active} | {s["team"] for s in st["swimmers"].values()}
    teams = [t for t in st["teams"].values() if t["code"] in used_teams]
    spec_teams = [{"key": t["code"], "abbr": t["code"], "name": t.get("name", ""), "short": t.get("short", ""),
                   "lsc": t.get("lsc", ""), "addr1": t.get("addr1", ""), "addr2": t.get("addr2", ""),
                   "city": t.get("city", ""), "state": t.get("state", ""), "zip": t.get("zip", ""),
                   "country": t.get("country", "USA"), "phone": t.get("phone", ""), "email": t.get("email", "")}
                  for t in teams]
    sw = sorted(st["swimmers"].values(), key=lambda s: (s["team"], s["last"], s["first"]))
    athletes = [{"key": s["key"], "team": s["team"], "last": s["last"], "first": s["first"],
                 "initial": s.get("initial", ""), "pref": s.get("pref", ""), "sex": s["gender"],
                 "class": s.get("class", ""), "age": s.get("age") or 0, "dob": s.get("dob", "")} for s in sw]

    def who(e):
        s = st["swimmers"].get(e["swimmers"][0]) if e["swimmers"] else None
        return f"{s['first']} {s['last']}" if s else e["team"]

    common = lambda e: {"event_no": int(e["event_no"] or 0), "gender": e["gender"], "distance": int(e["distance"] or 0),
                        "stroke": e["stroke"], "seed": e["seed"] or 0, "course": e.get("course", "Y"),
                        "conv_seed": e.get("conv_seed") or 0, "conv_course": e.get("conv_course", "Y"),
                        "label": e["event"]}
    cl = {**st.get("seed_lanes", {}), **st["combo_lanes"]}
    pos = lambda e: ({"heat": cl[e["id"]][0], "lane": cl[e["id"]][1]} if e["id"] in cl else {})
    entries = [{**common(e), **pos(e), "athlete": e["swimmers"][0], "exh": e["exhibition"], "who": who(e)}
               for e in active if e["kind"] == "ind"]
    relays = [{**common(e), **pos(e), "team": e["team"], "letter": e.get("relay", "A"),
               "legs": {str(k): v for k, v in e["legs"].items()}} for e in active if e["kind"] == "relay"]
    notes = {}
    for c in st["combos"]:
        if c["selected"] and c["fits"]:
            for mine, other in ((c["girls_event"], c["boys_event"]), (c["boys_event"], c["girls_event"])):
                notes[mine] = f"Swims with Ev {other}: G ln {c['girls_lanes']}, B ln {c['boys_lanes']}"[:36]
    return {"meet": {"name": st["name"], "date": st["date"], "location": st.get("location", "")},
            "teams": spec_teams, "athletes": athletes, "entries": entries, "relays": relays,
            "scoring_teams": st["lanes"]["order"],
            "lanes": {"count": int(st["lanes"]["count"]), "plan": st["lane_plan"]},
            "team_tags": host.get("team_tags", []), "record_team": _record_team(st, host, meta),
            "event_notes": notes}


def build_mm(d: Path) -> tuple[bytes, str, dict]:
    meta = _meta(d)
    host = _host(meta.get("host", "THS"))
    z = _mpath(host["id"])
    if not z.exists():
        raise HTTPException(400, f"{host['name']} has no master meet file yet - set one up under Schools")
    _, tpl_bytes, hyb = _unpack(z)
    db_stem = _stem(meta["name"])
    mdb_name = f"{db_stem}.mdb"
    with tempfile.TemporaryDirectory() as tmp:
        tp = Path(tmp)
        (tp / "tpl.mdb").write_bytes(tpl_bytes)
        (tp / "spec.json").write_text(json.dumps(_spec(d)))
        report = json.loads(_java(tp / "tpl.mdb", tp / "spec.json", tp / "out.mdb"))
        out = (tp / "out.mdb").read_bytes()
    return _pack(mdb_name, out, hyb), f"Swmm8Bkup{db_stem}-01.zip", {**report, "host": host["short"]}


@app.get("/api/meets/{mid}/mm-report")
def mm_report(mid: str):
    _, name, report = build_mm(_dir(mid))
    return {**report, "file": name}


@app.get("/api/meets/{mid}/mm-backup")
def mm_backup(mid: str):
    d = _dir(mid)
    data, name, report = build_mm(d)
    bk = d / "backups"
    bk.mkdir(exist_ok=True)
    (bk / f"{time.strftime('%Y-%m-%d %H%M')} {name}").write_bytes(data)
    for old in sorted(bk.glob("*.zip"), key=lambda f: f.stat().st_mtime)[:-15]:   # keep the 15 newest
        old.unlink()
    _drive_upload_async(d, name, data)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"',
                             "X-Build-Report": json.dumps(report)[:4000]})


# ---- Gmail scan ---------------------------------------------------------------
import gmail as gmail_mod


@app.get("/api/gmail/status")
def gmail_status():
    return {"configured": gmail_mod.configured(), "user": os.environ.get("GMAIL_USER", "")}


@app.get("/api/meets/{mid}/gmail")
def gmail_scan(mid: str, days: int = 14, words: str = ""):
    d = _dir(mid)
    if not gmail_mod.configured():
        return {"configured": False, "messages": []}
    try:
        msgs = gmail_mod.scan(days=max(1, min(days, 90)), words=words)
    except Exception as e:
        raise HTTPException(502, f"Gmail scan failed: {e}")
    done = set(_meta(d).get("imported_mail", []))
    for m in msgs:
        for a in m["attachments"]:
            a["imported"] = a["id"] in done
    return {"configured": True, "messages": msgs}


@app.post("/api/meets/{mid}/gmail/import")
def gmail_import(mid: str, body: dict):
    d = _dir(mid)
    try:
        fn, data, info = gmail_mod.cached(body.get("id", ""))
    except FileNotFoundError:
        raise HTTPException(404, "attachment not in cache - scan again")
    r = ingest(d, fn, data, source=f"Gmail: {info.get('from', '')} — {info.get('subject', '')}"[:200])
    meta = _meta(d)
    meta["imported_mail"] = sorted(set(meta.get("imported_mail", [])) | {body["id"]})
    _save(d, meta)
    return r



# ---- Google Drive folder: setup, inventory, organize, backups -------------------
import threading

INV_FILE = DATA.parent / "drive-inventory.json"
INV_STATE = {"running": False, "done": 0, "current": "", "error": ""}


def _read_mdb_meet(data: bytes) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "m.mdb"
        p.write_bytes(data)
        info = json.loads(_java("--read-master", p))
    m = info.get("meet", {})
    return {"meet": m.get("Meet_name1"), "start": m.get("Meet_start")}


def _drive_cfg(write=False) -> dict:
    st = _settings()
    if not st.get("drive_folder"):
        raise HTTPException(400, "Set the Google Drive folder on the Setup page first")
    if write and not st.get("drive_url"):
        raise HTTPException(400, "Drive write access isn't set up yet (Setup page)")
    return st


@app.get("/api/drive/script")
def drive_script():
    st = _drive_cfg()
    if not st.get("drive_token"):
        st["drive_token"] = secrets.token_urlsafe(24)
        _write_settings(st)
    return {"script": drive_mod.script_for(st["drive_folder"], st["drive_token"])}


@app.post("/api/drive/test")
def drive_test():
    st = _drive_cfg(write=True)
    try:
        return drive_mod.bridge(st["drive_url"], st.get("drive_token", ""), "ping")
    except Exception as e:
        raise HTTPException(502, f"Drive script check failed: {e}")


@app.get("/api/drive/folder")
def drive_folder():
    st = _drive_cfg()
    try:
        items = drive_mod.list_folder(st["drive_folder"])
    except drive_mod.NotShared as e:
        raise HTTPException(403, f"Couldn't open the folder: {e}")
    return {"id": st["drive_folder"], "items": items}


def _run_inventory(root: str):
    INV_STATE.update(running=True, done=0, current="", error="")
    try:
        inv = drive_mod.inventory(root, _read_mdb_meet, lambda n, p: INV_STATE.update(done=n, current=p))
        INV_FILE.write_text(json.dumps({"root": root, "when": time.strftime("%Y-%m-%d %H:%M"), "items": inv}, indent=1))
    except Exception as e:
        INV_STATE["error"] = str(e)
    finally:
        INV_STATE["running"] = False


@app.post("/api/drive/inventory")
def drive_inventory_start():
    st = _drive_cfg()
    if not INV_STATE["running"]:
        threading.Thread(target=_run_inventory, args=(st["drive_folder"],), daemon=True).start()
        INV_STATE["running"] = True
    return INV_STATE


@app.get("/api/drive/plan")
def drive_plan():
    st = _drive_cfg()
    inv = json.loads(INV_FILE.read_text()) if INV_FILE.exists() else None
    if inv and inv.get("root") != st["drive_folder"]:
        inv = None
    return {"scan": INV_STATE, "when": inv and inv["when"], "files": inv and len([i for i in inv["items"] if i["kind"] != "folder"]),
            **(drive_mod.plan(inv["items"]) if inv else {"meets": [], "moves": [], "unsorted": []})}


@app.post("/api/drive/organize")
def drive_organize():
    st = _drive_cfg(write=True)
    p = drive_plan()
    done, failed = [], []
    for mv in p["moves"]:
        try:
            drive_mod.bridge(st["drive_url"], st["drive_token"], "move", id=mv["id"], folder=mv["folder"], path=mv["to"])
            done.append(mv)
        except Exception as e:
            failed.append({**mv, "error": str(e)})
    if done:
        threading.Thread(target=_run_inventory, args=(st["drive_folder"],), daemon=True).start()
        INV_STATE["running"] = True
    return {"moved": len(done), "failed": failed}


def _meet_drive_path(meta: dict) -> list:
    date = meta.get("date") or time.strftime("%Y-%m-%d")
    return [_meet_season(meta), f"{date} {drive_mod.tidy_name(meta['name'])}"]


def _drive_upload_async(d: Path, name: str, data: bytes):
    st = _settings()
    if not (st.get("drive_folder") and st.get("drive_url")):
        return
    meta = _meta(d)
    if meta.get("no_drive"):
        return
    path = _meet_drive_path(meta)
    def go():
        try:
            drive_mod.upload(st["drive_url"], st["drive_token"], path, name, data)
            res = {"file": name, "folder": "/".join(path), "when": time.strftime("%Y-%m-%d %H:%M"), "ok": True}
        except Exception as e:
            res = {"file": name, "folder": "/".join(path), "when": time.strftime("%Y-%m-%d %H:%M"), "ok": False, "error": str(e)}
        m = _meta(d)
        m["drive_uploads"] = (m.get("drive_uploads", []) + [res])[-10:]
        _save(d, m)
    threading.Thread(target=go, daemon=True).start()


@app.get("/api/meets/{mid}/drive-files")
def meet_drive_files(mid: str):
    """Entry files in the saved Drive folder, this meet's folder first."""
    d = _dir(mid)
    meta = _meta(d)
    st = _drive_cfg()
    try:
        items = list(drive_mod.walk(st["drive_folder"]))
    except drive_mod.NotShared as e:
        raise HTTPException(403, f"Couldn't open the Drive folder: {e}")
    want = "/".join(_meet_drive_path(meta))
    key = re.sub(r"[^a-z0-9]", "", meta["name"].lower())
    done = set(meta.get("imported_drive", []))
    out = []
    for it in items:
        if it["kind"] == "folder" or not drive_mod.importable(it):
            continue
        low = it["name"].lower()
        if low.startswith(("swmm8bkup", "meet results", "merge meet results", "hybackup")) or low.endswith(".mdb"):
            continue
        flat = re.sub(r"[^a-z0-9]", "", it["path"].lower())
        it["mine"] = it["path"].lstrip("/").startswith(want) or (len(key) >= 6 and key in flat)
        it["imported"] = it["id"] in done
        out.append(it)
    out.sort(key=lambda i: (not i["mine"], i["path"].lower()))
    return {"meet_folder": want, "files": out}


# ---- the meet's working Meet Manager database (edit, correct, later run the meet) --------
import gzip
import meetdb


@app.on_event("startup")
def _start_mmdb():
    threading.Thread(target=meetdb.start, daemon=True).start()


def _dbdir(d: Path) -> Path:
    p = d / "db"
    p.mkdir(exist_ok=True)
    return p


def _dbfile(d: Path) -> Path:
    return _dbdir(d) / "meet.mdb"


def _dbinfo(d: Path) -> dict:
    f = _dbdir(d) / "info.json"
    return json.loads(f.read_text()) if f.exists() else {}


def _dblog(d: Path, msg: str, kind: str = "change"):
    with open(_dbdir(d) / "log.jsonl", "a") as f:
        f.write(json.dumps({"when": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, "msg": msg}) + "\n")


def _snapshot(d: Path, label: str):
    """Keep a compressed copy before every change (undo / history). Newest 60 kept."""
    db = _dbfile(d)
    if not db.exists():
        return
    meetdb.close(db)
    vd = _dbdir(d) / "versions"
    vd.mkdir(exist_ok=True)
    name = f"{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.mdb.gz"
    with gzip.open(vd / name, "wb", compresslevel=5) as g:
        g.write(db.read_bytes())
    (vd / (name + ".txt")).write_text(label)
    for old in sorted(vd.glob("*.mdb.gz"))[:-60]:
        old.unlink()
        old.with_name(old.name + ".txt").unlink(missing_ok=True)


def _install_db(d: Path, mdb_name: str, mdb: bytes, hyb: str, source: str):
    if _dbfile(d).exists():
        _snapshot(d, f"before replacing the database ({source})")
    meetdb.close(_dbfile(d))
    _dbfile(d).write_bytes(mdb)
    (_dbdir(d) / "info.json").write_text(json.dumps({"mdb_name": mdb_name, "hyb": hyb, "source": source,
                                                      "created": time.strftime("%Y-%m-%d %H:%M")}))
    _dblog(d, f"Database loaded: {source}", "load")


@app.get("/api/meets/{mid}/db")
def db_get(mid: str):
    d = _dir(mid)
    info = _dbinfo(d)
    if not _dbfile(d).exists():
        return {"exists": False, "meet": _meta(d)["name"]}
    m = meetdb.load(_dbfile(d))
    logf = _dbdir(d) / "log.jsonl"
    log = [json.loads(l) for l in logf.read_text().splitlines()[-200:]] if logf.exists() else []
    vd = _dbdir(d) / "versions"
    versions = sorted(vd.glob("*.mdb.gz"), reverse=True) if vd.exists() else []
    scoring = info.get("scoring") or {}
    return {"exists": True, "info": {k: v for k, v in info.items() if k not in ("hyb", "scoring", "scoring_stack")}, "meet_name": _meta(d)["name"],
            "model": meetdb.json_safe(m), "problems": meetdb.check(m), "log": log[::-1],
            "races": meetdb.race_numbers(m, info.get("races")), "race_overrides": info.get("races") or {},
            "scoring": scoring, "event_sigs": {str(v["ptr"]): meetdb.event_sig(m, v["ptr"]) for v in m["events"]},
            "scoring_methods": {k: {"name": c["name"], "ind_max": c["ind_max"], "rel_max": c["rel_max"]} for k, c in meetdb.SCORING.items()},
            "scoring_default": scoring.get("method") or meetdb.default_scoring(m),
            "versions": [{"id": v.name, "label": (v.with_name(v.name + ".txt").read_text() if v.with_name(v.name + ".txt").exists() else ""),
                          "when": datetime.strptime(v.name[:15], "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M:%S")} for v in versions[:30]]}


@app.post("/api/meets/{mid}/db/create")
def db_create(mid: str):
    """Build the database from the checked entries (same file as the step 5 download)."""
    d = _dir(mid)
    data, name, report = build_mm(d)
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "b.zip").write_bytes(data)
        mdb_name, mdb, hyb = _unpack(Path(tmp) / "b.zip")
    _install_db(d, mdb_name, mdb, hyb, "built from the team entries")
    return db_get(mid)


def _import_backup(d: Path, data: bytes, label: str):
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "b.zip").write_bytes(data)
        try:
            mdb_name, mdb, hyb = _unpack(Path(tmp) / "b.zip")
        except zipfile.BadZipFile:
            raise HTTPException(400, "That isn't a Meet Manager backup (.zip)")
    _install_db(d, mdb_name, mdb, hyb, label)


@app.post("/api/open-meet-file")
async def open_meet_file(file: UploadFile = File(...)):
    """Open an existing Meet Manager meet (Swmm8Bkup....zip or .mdb) as a new MeetDeck meet:
    name, date and location come from the file; the database is ready on Run the meet."""
    data = await file.read()
    fn = Path(file.filename or "meet").name
    mid = secrets.token_hex(4)
    d = DATA / mid
    (d / "files").mkdir(parents=True)
    _save(d, {"name": Path(fn).stem, "date": "", "host": "THS", "season": _settings()["season"], "created": time.time(),
              "removed": [], "rules": DEFAULT_RULES, "opened_file": fn})
    try:
        if fn.lower().endswith(".mdb"):
            _install_db(d, fn, data, "", f"opened {fn}")
        else:
            _import_backup(d, data, f"opened {fn}")
        mm = meetdb.load(_dbfile(d))["meet"]
    except HTTPException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, f"Couldn't open {fn} as a Meet Manager meet: {e}")
    meta = _meta(d)
    meta.update(name=mm.get("name") or meta["name"], date=mm.get("start") or "", location=mm.get("location") or "")
    if meta["date"]:
        meta["season"] = season_of(meta["date"])
    host = next((h["id"] for h in _hosts() for t in meetdb.load(_dbfile(d))["teams"].values()
                 if t["abbr"].upper() in [c.upper() for c in h.get("team_codes", [])]), None)
    if host:
        meta["host"] = host
    _save(d, meta)
    return {"id": mid, "name": meta["name"], "date": meta["date"], "season": meta["season"]}


@app.post("/api/meets/{mid}/db/import")
async def db_import(mid: str, file: UploadFile = File(...)):
    d = _dir(mid)
    data = await file.read()
    if (file.filename or "").lower().endswith(".mdb"):
        _install_db(d, Path(file.filename).name, data, "", f"uploaded {file.filename}")
    else:
        _import_backup(d, data, f"uploaded {file.filename}")
    return db_get(mid)


@app.get("/api/meets/{mid}/db/drive-backups")
def db_drive_backups(mid: str):
    d = _dir(mid)
    st = _drive_cfg()
    want = "/".join(_meet_drive_path(_meta(d)))
    items = [it for it in drive_mod.walk(st["drive_folder"]) if it["kind"] == "file"
             and (it["name"].lower().startswith("swmm8bkup") or it["name"].lower().endswith(".mdb"))]
    for it in items:
        it["mine"] = it["path"].lstrip("/").startswith(want)
    items.sort(key=lambda i: (not i["mine"], i["path"].lower()))
    return {"meet_folder": want, "files": items}


@app.post("/api/meets/{mid}/db/import-drive")
def db_import_drive(mid: str, body: dict):
    d = _dir(mid)
    fn, data = drive_mod.fetch("file", body["id"], body.get("name", ""))
    if fn.lower().endswith(".mdb"):
        _install_db(d, fn, data, "", f"Google Drive: {fn}")
    else:
        _import_backup(d, data, f"Google Drive: {fn}")
    return db_get(mid)


OPS = {"scratch": meetdb.op_scratch, "scratch_athlete": meetdb.op_scratch_athlete, "move": meetdb.op_move,
       "seed": meetdb.op_seed, "result": meetdb.op_result, "delete": meetdb.op_delete, "add_entry": meetdb.op_add_entry,
       "athlete": meetdb.op_athlete, "add_athlete": meetdb.op_add_athlete, "team": meetdb.op_team, "legs": meetdb.op_legs,
       "heat_results": meetdb.op_heat_results, "dq": meetdb.op_dq, "undq": meetdb.op_undq, "meet": meetdb.op_meet}


@app.get("/api/dqcodes")
def dq_codes():
    import dqcodes
    return {"groups": dqcodes.GROUPS, "codes": dqcodes.CODES, "no_time": sorted(dqcodes.NO_TIME)}


@app.post("/api/meets/{mid}/db/op")
def db_op(mid: str, body: dict):
    d = _dir(mid)
    db = _dbfile(d)
    if not db.exists():
        raise HTTPException(400, "No database yet")
    fn = OPS.get(body.get("op"))
    if not fn:
        raise HTTPException(400, "unknown change")
    m = meetdb.load(db)
    try:
        ops, msg = fn(m, **body.get("args", {}))
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e).strip("'"))
    if not ops:
        return db_get(mid)
    _snapshot(d, "before: " + msg)
    try:
        meetdb.apply(db, ops)
    except RuntimeError as e:
        raise HTTPException(500, f"Database change failed: {e}")
    _dblog(d, msg)
    if body.get("op") == "meet":            # keep the meet list (name / date / location) in step with the database
        f = body.get("args", {}).get("fields", {})
        meta = _meta(d)
        for k, mk in (("name", "name"), ("start", "date"), ("location", "location")):
            if k in f and str(f[k]).strip():
                meta[mk] = str(f[k]).strip()
        _save(d, meta)
    return db_get(mid)


@app.post("/api/meets/{mid}/db/race")
def db_race(mid: str, body: dict):
    """Set (or clear) a heat's console race number; later heats count up from it."""
    d = _dir(mid)
    ptr, heat = int(body["ptr"]), int(body["heat"])
    info = _dbinfo(d)
    ov = info.get("races") or {}
    k = f"{ptr}:{heat}"
    r = body.get("race")
    if r in (None, "", 0, "0"):
        ov.pop(k, None)
        msg = "back to automatic"
    else:
        try:
            r = int(r)
        except ValueError:
            raise HTTPException(400, "Race number must be a whole number")
        if not 1 <= r <= 999:
            raise HTTPException(400, "Race number must be 1-999")
        ov[k] = r
        msg = f"set to {r}"
    info["races"] = ov
    (_dbdir(d) / "info.json").write_text(json.dumps(info))
    m = meetdb.load(_dbfile(d))
    _dblog(d, f"Race number for {meetdb.ev_label(m, ptr)} heat {heat} {msg}")
    return db_get(mid)


@app.post("/api/meets/{mid}/db/timers")
def db_timers(mid: str, body: dict):
    """How many hand timers work each lane (1 or 2) - shapes the Timers column."""
    d = _dir(mid)
    n = int(body.get("timers") or 1)
    if n not in (1, 2):
        raise HTTPException(400, "Timers must be 1 or 2")
    info = _dbinfo(d)
    info["timers"] = n
    (_dbdir(d) / "info.json").write_text(json.dumps(info))
    _dblog(d, f"Timers per lane set to {n}")
    return db_get(mid)


@app.post("/api/meets/{mid}/db/score")
def db_score(mid: str, body: dict):
    """Score one race (body.events = [ptr]) or every finished race (body.all), with the meet's scoring settings.
    Saving new settings rescoring everything already scored, so totals stay consistent."""
    d = _dir(mid)
    db = _dbfile(d)
    if not db.exists():
        raise HTTPException(400, "No database yet")
    info = _dbinfo(d)
    prev = info.get("scoring") or {}
    m = meetdb.load(db)
    method = body.get("method") or prev.get("method") or meetdb.default_scoring(m)
    if method not in meetdb.SCORING:
        raise HTTPException(400, "Unknown scoring method")
    cfg = meetdb.SCORING[method]
    ind_max = int(body["ind_max"]) if body.get("ind_max") is not None else prev.get("ind_max", cfg["ind_max"]) if prev.get("method") == method else cfg["ind_max"]
    rel_max = int(body["rel_max"]) if body.get("rel_max") is not None else prev.get("rel_max", cfg["rel_max"]) if prev.get("method") == method else cfg["rel_max"]
    same = prev.get("method") == method and prev.get("ind_max") == ind_max and prev.get("rel_max") == rel_max
    kept = set(prev.get("events", [])) if same else set()
    if body.get("all"):
        targets = None
    else:
        targets = {int(x) for x in body.get("events", [])} | (set(prev.get("events", [])) if not same else set())
    if targets is not None and not targets and not body.get("settings_only"):
        raise HTTPException(400, "Pick an event to score")
    ops, scored, skipped, sigs = ([], [], [], {})
    if targets is None or targets:
        ops, scored, skipped, sigs = meetdb.score_events(m, method, ind_max, rel_max, targets, True)
    asked = {int(x) for x in body.get("events", [])}
    if asked and not (asked & set(scored)):
        raise HTTPException(400, "That event isn't finished yet - every lane needs a time, DQ or no-show" + (f": {skipped[0]}" if skipped else ""))
    if body.get("all") and not scored and not body.get("settings_only"):
        raise HTTPException(400, "No events are fully timed yet - finish entering times, DQs and no-shows first")
    labels = [f"#{v['no']}" for v in m["events"] if v["ptr"] in scored]
    if body.get("settings_only") and not scored:
        msg = f"Scoring set to {cfg['name'].split(' (')[0]}"
    elif len(scored) == 1:
        v = next(v for v in m["events"] if v["ptr"] == scored[0])
        msg = f"Scored #{v['no']} {v['label']}"
    else:
        msg = f"Scored {len(scored)} event(s) ({', '.join(labels[:12])}{'...' if len(labels) > 12 else ''})"
    if not same and prev.get("method"):
        msg += f" - scoring changed to {cfg['name'].split(' (')[0]}"
    _snapshot(d, "before: " + msg)
    if ops:
        meetdb.apply(db, ops)
    summary = {"method": method, "method_name": cfg["name"], "ind_max": ind_max, "rel_max": rel_max,
               "events": sorted(kept | set(scored)), "sigs": {**(prev.get("sigs", {}) if same else {}), **sigs},
               "skipped": skipped if body.get("all") else [], "when": time.strftime("%Y-%m-%d %H:%M")}
    summary.update(meetdb.score_totals(meetdb.load(db), summary))
    info = _dbinfo(d)
    info["scoring_stack"] = (info.get("scoring_stack", []) + [prev])[-40:]   # for undo
    info["scoring"] = summary
    (_dbdir(d) / "info.json").write_text(json.dumps(info))
    _dblog(d, msg, "score")
    return db_get(mid)


@app.post("/api/meets/{mid}/db/undo")
def db_undo(mid: str, body: dict | None = None):
    d = _dir(mid)
    vd = _dbdir(d) / "versions"
    versions = sorted(vd.glob("*.mdb.gz")) if vd.exists() else []
    vid = (body or {}).get("id")
    v = next((x for x in versions if x.name == vid), None) if vid else (versions[-1] if versions else None)
    if not v:
        raise HTTPException(400, "Nothing to undo")
    label = v.with_name(v.name + ".txt").read_text() if v.with_name(v.name + ".txt").exists() else ""
    meetdb.close(_dbfile(d))
    if vid:      # going back to an older version: keep the current one so this can be undone too
        _snapshot(d, "before restoring an earlier version")
    _dbfile(d).write_bytes(gzip.decompress(v.read_bytes()))
    if label.startswith(("before: Scored", "before: Scoring set")):   # undoing scoring: put the earlier summary back
        info = _dbinfo(d)
        stack = info.get("scoring_stack", [])
        back = stack.pop() if stack else {}
        info["scoring_stack"] = stack
        if back:
            info["scoring"] = back
        else:
            info.pop("scoring", None)
        (_dbdir(d) / "info.json").write_text(json.dumps(info))
    if not vid:
        v.unlink()
        v.with_name(v.name + ".txt").unlink(missing_ok=True)
    _dblog(d, ("Undid: " + label.replace("before: ", "")) if not vid else f"Restored version from {v.name[:15]}", "undo")
    return db_get(mid)


@app.get("/api/meets/{mid}/db/backup")
def db_backup(mid: str):
    """The working database as a Meet Manager backup (File > Restore)."""
    d = _dir(mid)
    info = _dbinfo(d)
    meetdb.close(_dbfile(d))
    mdb = _dbfile(d).read_bytes()
    name = info.get("mdb_name") or f"{_stem(_meta(d)['name'])}.mdb"
    hyb = info.get("hyb") or _hyb_default()
    data = _pack(name, mdb, hyb)
    zname = f"Swmm8Bkup{Path(name).stem}-{time.strftime('%m%d-%H%M')}.zip"
    bk = d / "backups"
    bk.mkdir(exist_ok=True)
    (bk / f"{time.strftime('%Y-%m-%d %H%M')} {zname}").write_bytes(data)
    _drive_upload_async(d, zname, data)
    _dblog(d, f"Downloaded Meet Manager backup {zname}", "export")
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{zname}"'})


def _hyb_default() -> str:
    for h in _hosts():
        z = _mpath(h["id"])
        if z.exists():
            return _unpack(z)[2]
    return ""


import results as results_mod


@app.get("/api/meets/{mid}/db/export/{fmt}")
def db_export(mid: str, fmt: str):
    d = _dir(mid)
    db = _dbfile(d)
    if not db.exists():
        raise HTTPException(400, "No database yet")
    m = meetdb.load(db)
    if fmt == "hy3":
        info = _dbinfo(d)
        seq = int(info.get("result_exports", 0)) + 1          # Meet Manager numbers its exports -001, -002 ...
        data, name = results_mod.hy3_zip(m, db, (info.get("hyb") or "")[28:78].strip(), seq)
        info["result_exports"] = seq
        (_dbdir(d) / "info.json").write_text(json.dumps(info))
        _dblog(d, f"Exported results for Team Manager ({name})", "export")
        return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})
    if fmt == "csv":
        return Response(results_mod.results_csv(m), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="{_stem(m["meet"]["name"])} results.csv"'})
    if fmt == "html":
        return Response(results_mod.results_html(m, _dbinfo(d).get("scoring")), media_type="text/html")
    raise HTTPException(404)


# ---- rules library ----
import rules as rules_mod


@app.get("/api/rules")
def rules_list():
    return {"docs": rules_mod.listing()}


@app.get("/api/rules/search")
def rules_search(q: str = ""):
    return {"q": q, "hits": rules_mod.search(q)}


@app.post("/api/rules")
async def rules_upload(file: UploadFile = File(...)):
    name = re.sub(r'[\\/:*?"<>|]', "-", Path(file.filename or "rules.pdf").name)
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Rules documents must be PDFs")
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "That file isn't a PDF")
    rules_mod.RULES.mkdir(parents=True, exist_ok=True)
    (rules_mod.RULES / name).write_bytes(data)
    return {"docs": rules_mod.listing()}


@app.delete("/api/rules/{name}")
def rules_delete(name: str):
    f = rules_mod.RULES / Path(name).name
    if f.exists():
        f.unlink()
    c = f.with_suffix(f.suffix + ".json")
    if c.exists():
        c.unlink()
    return {"docs": rules_mod.listing()}


@app.get("/api/rules/file/{name}")
def rules_file(name: str):
    f = rules_mod.RULES / Path(name).name
    if not f.exists():
        raise HTTPException(404)
    return FileResponse(f, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{f.name}"'})


FONT_NAMES = {"cambria.ttc", "cambriab.ttf"}


@app.get("/api/settings/font")
def font_get():
    import heatsheet
    return heatsheet.font_status()


@app.post("/api/settings/font")
async def font_upload(file: UploadFile = File(...)):
    """Add Cambria (from C:\\Windows\\Fonts on a Windows PC) so printed reports use Meet Manager's exact font."""
    import heatsheet
    name = Path(file.filename or "").name.lower()
    if name not in FONT_NAMES:
        raise HTTPException(400, "Expected cambria.ttc or cambriab.ttf from C:\\Windows\\Fonts")
    data = await file.read()
    if len(data) > 30_000_000 or data[:4] not in (b"ttcf", b"\x00\x01\x00\x00", b"true", b"OTTO"):
        raise HTTPException(400, "That doesn't look like a font file")
    d = Path(heatsheet.FONT_DIR)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)
    return heatsheet.font_status()


@app.get("/api/meets/{mid}/db/report/{kind}.pdf")
def db_report(mid: str, kind: str, download: int = 0, lane: int = 0):
    """Printable reports laid out like Meet Manager's: heatsheet (Meet Program), referee program, timer sheets."""
    import heatsheet
    d = _dir(mid)
    db = _dbfile(d)
    if not db.exists():
        raise HTTPException(400, "No database yet")
    m = meetdb.load(db)
    licensee = (_dbinfo(d).get("hyb") or "")[28:78].strip()
    if kind == "heatsheet":
        pdf, label = heatsheet.heat_sheet_pdf(m, licensee), "heat sheet"
    elif kind == "referee":
        pdf, label = heatsheet.referee_pdf(m, licensee), "referee program"
    elif kind == "results":
        pdf, label = heatsheet.results_pdf(m, db, licensee), "results"
    elif kind == "timer":
        pdf, label = heatsheet.timer_pdf(m, licensee, lane=lane or None), "timer sheets" + (f" lane {lane}" if lane else "")
    else:
        raise HTTPException(404)
    name = f"{_stem(m['meet']['name'])} {label}.pdf"
    disp = "attachment" if download else "inline"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'{disp}; filename="{name}"'})


TIMING = Path(__file__).parent / "timing"


import updater


@app.get("/api/version")
def app_version():
    return {"version": updater.version(), "windows": updater.supported()}


@app.get("/api/update")
def update_check(fresh: int = 0):
    return updater.check(bool(fresh))


@app.post("/api/update/install")
def update_install():
    try:
        return updater.install()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"Update failed: {e}")


@app.get("/download/MeetDeck-Windows.zip")
def windows_app():
    """The stand-alone Windows version (built by windows/build.sh into data/downloads)."""
    f = DATA_ROOT / "downloads" / "MeetDeck-Windows.zip"
    if not f.exists():
        raise HTTPException(404, "The Windows version hasn't been built yet")
    return FileResponse(f, filename="MeetDeck-Windows.zip", media_type="application/zip")


@app.get("/timing/bridge.zip")
def bridge_zip():
    """Everything the timing laptop needs (Python + pyserial)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in ("cts.py", "sim.py", "bridge.py", "README.txt"):
            if (TIMING / f).exists():
                z.write(TIMING / f, f"timing-bridge/{f}")
        z.writestr("timing-bridge/start-bridge.bat", "@echo off\r\ncd /d %~dp0\r\npython -m pip install --quiet pyserial\r\npython bridge.py\r\npause\r\n")
        z.writestr("timing-bridge/start-simulator.bat", "@echo off\r\ncd /d %~dp0\r\npython bridge.py --sim\r\npause\r\n")
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="timing-bridge.zip"'})


@app.get("/db")
def db_page():
    return FileResponse(STATIC / "db.html")
