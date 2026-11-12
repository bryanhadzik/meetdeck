"""Whole-meet backups: everything MeetDeck keeps for one meet (setup, entry files, originals, documents,
meet database and its change history) in a single zip that can be restored on any MeetDeck.

Backups live in <data>/meet-backups as  "<date> <meet> - MeetDeck backup <when>.zip"  with a small
"<zip>.json" beside each (what it is, and whether it has been copied to Google Drive yet).
"""
from __future__ import annotations

import io
import json
import re
import secrets
import shutil
import time
import zipfile
from pathlib import Path

FORMAT = 1
MANIFEST = "meetdeck-backup.json"
KEEP_AUTO = 30            # automatic backups kept per meet (manual / before-delete / before-restore ones are never pruned)
REASONS = {"auto": "automatic", "manual": "backed up by hand", "delete": "before the meet was deleted",
           "restore": "before a restore replaced it", "import": "restored from a file"}


def safe(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9 @&_.,()-]", "", s or "")).strip() or "meet"


def is_backup_name(name: str) -> bool:
    return "meetdeck backup" in (name or "").lower() and name.lower().endswith(".zip")


def last_change(d: Path) -> float:
    t = 0.0
    for f in d.rglob("*"):
        if f.is_file():
            t = max(t, f.stat().st_mtime)
    return t


def make(d: Path, root: Path, reason: str, version: str = "") -> dict:
    meta = json.loads((d / "meta.json").read_text())
    now = time.time()
    stamp = time.strftime("%Y-%m-%d %H%M%S", time.localtime(now))
    base = f"{meta.get('date') or 'no date'} {safe(meta.get('name', ''))} - MeetDeck backup {stamp}"
    name, n = base + ".zip", 1
    while (root / name).exists():           # two backups in the same second (e.g. a restore right after a backup)
        n += 1
        name = f"{base} ({n}).zip"
    files = [f for f in sorted(d.rglob("*")) if f.is_file()]
    man = {"format": FORMAT, "id": d.name, "name": meta.get("name", ""), "date": meta.get("date", ""),
           "host": meta.get("host", ""), "season": meta.get("season", ""), "made": now, "reason": reason,
           "version": version, "files": len(files)}
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / (name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(MANIFEST, json.dumps(man, indent=1))
        for f in files:
            try:
                z.write(f, "meet/" + f.relative_to(d).as_posix())
            except FileNotFoundError:          # removed while we were copying (old database version pruned)
                pass
    tmp.replace(root / name)
    info = {**man, "file": name, "size": (root / name).stat().st_size, "drive": None}
    _write_info(root, info)
    prune(root, d.name)
    return info


def _write_info(root: Path, info: dict):
    p = root / (info["file"] + ".json")
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(info, indent=1))
    tmp.replace(p)


def update_info(root: Path, name: str, **kw) -> dict:
    info = get_info(root, name)
    info.update(kw)
    _write_info(root, info)
    return info


def get_info(root: Path, name: str) -> dict:
    return json.loads((root / (name + ".json")).read_text())


def check_name(root: Path, name: str) -> Path:
    if "/" in name or "\\" in name or not is_backup_name(name):
        raise ValueError("not a MeetDeck backup")
    p = root / name
    if not p.exists():
        raise FileNotFoundError(name)
    return p


def listing(root: Path) -> list[dict]:
    out = []
    for j in root.glob("*.zip.json") if root.exists() else []:
        try:
            info = json.loads(j.read_text())
        except ValueError:
            continue
        if (root / info.get("file", "")).exists():
            out.append(info)
    out.sort(key=lambda i: -i.get("made", 0))
    return out


def prune(root: Path, mid: str):
    autos = [i for i in listing(root) if i.get("id") == mid and i.get("reason") == "auto"]
    for i in autos[KEEP_AUTO:]:
        delete(root, i["file"])


def delete(root: Path, name: str):
    for p in (root / name, root / (name + ".json")):
        if p.exists():
            p.unlink()


def read(data: bytes) -> tuple[dict, zipfile.ZipFile]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("That isn't a zip file")
    if MANIFEST not in z.namelist():
        raise ValueError("That zip isn't a MeetDeck backup (no meetdeck-backup.json inside). "
                         "For a Meet Manager backup (Swmm8Bkup…zip), open it from Run the meet instead.")
    man = json.loads(z.read(MANIFEST))
    if man.get("format", 0) > FORMAT:
        raise ValueError("This backup was made by a newer MeetDeck - update MeetDeck first")
    for n in z.namelist():
        if n == MANIFEST or n.endswith("/"):
            continue
        parts = n.split("/")
        if parts[0] != "meet" or ".." in parts or n.startswith("/") or ":" in n:
            raise ValueError(f"Unexpected file in the backup: {n}")
    if "meet/meta.json" not in z.namelist():
        raise ValueError("The backup has no meet setup (meta.json) inside")
    return man, z


def restore(data: bytes, meets: Path, mid: str | None = None, rename: str = "") -> str:
    """Unpack a backup as meet `mid` (the folder must not exist). Returns the meet id."""
    man, z = read(data)
    mid = mid or man.get("id") or secrets.token_hex(4)
    if not re.fullmatch(r"[a-z0-9]{8}", mid):
        mid = secrets.token_hex(4)
    target = meets / mid
    if target.exists():
        raise FileExistsError(mid)
    tmp = meets / f".restore-{mid}-{secrets.token_hex(3)}"
    tmp.mkdir(parents=True)
    try:
        for n in z.namelist():
            if n == MANIFEST or n.endswith("/"):
                continue
            dest = tmp / n[len("meet/"):]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(n))
        if rename:
            mp = tmp / "meta.json"
            meta = json.loads(mp.read_text())
            meta["name"] = rename
            mp.write_text(json.dumps(meta, indent=1))
        tmp.rename(target)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return mid
