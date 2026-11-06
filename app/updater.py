"""Updates for MeetDeck for Windows, from GitHub releases of bryanhadzik/meetdeck.

A release carries one asset, meetdeck-app-<version>.zip: the contents of the app folder (code only,
never meet data). Installing unpacks it next to the running app as `app.new`; start.py (in the
MeetDeck folder) swaps it in on the next start, keeping the previous version as `app.old`.
"""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = os.environ.get("MEETDECK_REPO", "bryanhadzik/meetdeck")
APP = Path(__file__).resolve().parent            # ...\MeetDeck\app
ROOT = APP.parent                                # ...\MeetDeck
UA = {"User-Agent": "MeetDeck-updater", "Accept": "application/vnd.github+json"}
STATE = {"busy": False, "msg": ""}


def version() -> str:
    f = APP / "VERSION"
    return f.read_text().strip() if f.exists() else "dev"


def supported() -> bool:
    """Only the stand-alone Windows app updates itself (the server is updated from plex)."""
    return os.name == "nt" and (ROOT / "start.py").exists()


def _key(v: str):
    return [int(x) for x in re.findall(r"\d+", v or "")] or [0]


def _ctx():
    """Windows' certificate store plus the standard CA list shipped with the app (cacert.pem):
    in the background (pythonw) Windows' store alone can be missing GitHub's issuer."""
    import ssl
    ctx = ssl.create_default_context()
    pem = APP / "cacert.pem"
    if pem.exists():
        ctx.load_verify_locations(cafile=str(pem))
    return ctx


def _get(url, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout, context=_ctx()) as r:
        return r.read()


def latest() -> dict:
    rel = json.loads(_get(f"https://api.github.com/repos/{REPO}/releases/latest"))
    asset = next((a for a in rel.get("assets", []) if a["name"].startswith("meetdeck-app-") and a["name"].endswith(".zip")), None)
    tag = (rel.get("tag_name") or "").lstrip("v")
    return {"version": tag, "name": rel.get("name") or tag, "notes": rel.get("body") or "",
            "published": (rel.get("published_at") or "")[:10], "url": asset and asset["browser_download_url"],
            "digest": asset and asset.get("digest"), "size": asset and asset.get("size"), "page": rel.get("html_url")}


_CACHE = {"at": 0, "val": None}


def check(fresh=False) -> dict:
    """Asks GitHub at most every 30 minutes unless asked fresh (Check for updates button)."""
    cur = version()
    out = {"current": cur, "supported": supported(), "repo": REPO, "pending": (ROOT / "app.new").exists()}
    try:
        if fresh or not _CACHE["val"] or time.time() - _CACHE["at"] > 1800:
            _CACHE.update(val=latest(), at=time.time())
        lt = _CACHE["val"]
    except urllib.error.HTTPError as e:
        out["error"] = "No updates published yet" if e.code == 404 else f"GitHub said {e.code}"
        return out
    except Exception as e:
        out["error"] = f"Couldn't reach GitHub - offline? ({getattr(e, 'reason', e)})"
        return out
    out["latest"] = lt
    out["available"] = bool(lt["url"]) and _key(lt["version"]) > _key(cur)
    return out


def install() -> dict:
    """Download the newest release into app.new, then restart MeetDeck onto it."""
    if not supported():
        raise RuntimeError("Updates install only in MeetDeck for Windows")
    if STATE["busy"]:
        raise RuntimeError("An update is already running")
    STATE.update(busy=True, msg="Downloading")
    try:
        lt = latest()
        if not lt["url"]:
            raise RuntimeError("The newest release has no MeetDeck app file")
        data = _get(lt["url"], timeout=300)
        if lt.get("digest", "").startswith("sha256:") and hashlib.sha256(data).hexdigest() != lt["digest"][7:]:
            raise RuntimeError("Download didn't match GitHub's checksum - try again")
        z = zipfile.ZipFile(io.BytesIO(data))
        names = z.namelist()
        if "main.py" not in names or "launcher.py" not in names or any(n.startswith(("/", "\\")) or ".." in n for n in names):
            raise RuntimeError("That release file isn't a MeetDeck app")
        new = ROOT / "app.new"
        shutil.rmtree(new, ignore_errors=True)
        z.extractall(new)
        (new / "VERSION").write_text(lt["version"])
        STATE["msg"] = "Restarting"
        threading.Thread(target=restart, daemon=True).start()
        return {"ok": True, "version": lt["version"]}
    finally:
        STATE["busy"] = False


def restart(delay=1.0):
    """Start a fresh MeetDeck (start.py swaps app.new in once this one has exited), then exit."""
    time.sleep(delay)
    pyw = ROOT / "python" / "pythonw.exe"
    exe = str(pyw if pyw.exists() else sys.executable)
    subprocess.Popen([exe, "-X", "utf8", str(ROOT / "start.py"), "--restart"], cwd=str(ROOT),
                     creationflags=0x00000008 | 0x00000200)     # DETACHED_PROCESS | NEW_PROCESS_GROUP
    time.sleep(0.5)
    os._exit(0)
