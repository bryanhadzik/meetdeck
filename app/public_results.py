"""Public, phone-friendly live results.

MeetDeck builds results.json from the meet database and publishes it, with the page in
static/public-results.html, to a public GitHub Pages site (default: bryanhadzik/swim-results).
Each publish replaces the gh-pages branch with a single fresh commit (no history), so the site
only ever holds the current meet's results.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import threading
import time
import urllib.request
from pathlib import Path

import results as results_mod

PAGE = Path(__file__).parent / "static" / "public-results.html"
BRANCH = "gh-pages"
DEFAULT_REPO = "bryanhadzik/swim-results"
MIN_GAP = 45           # a GitHub Actions deploy takes ~30-40 s; changes inside the gap go out together after it
DEFAULT_DOMAIN = "swim.hadzik.org"


def _date(s: str) -> str:
    try:
        d = datetime.date.fromisoformat(str(s)[:10])
        return f"{d:%b} {d.day}, {d.year}"
    except Exception:
        return str(s or "")


def build(m: dict, scoring: dict | None = None) -> dict:
    """results.json for the public page: meet, team scores and every event's results so far."""
    meet = m["meet"]
    teams = m["teams"]
    names = {t.get("abbr", ""): t.get("name", "") for t in teams.values()}
    events, latest = [], None
    with_rows = {v["ptr"]: rows for v, rows in results_mod._rows(m)}
    for v in m["events"]:
        rows = [r for r in with_rows.get(v["ptr"], []) if r["place"] or r["result"]]
        out = []
        for r in rows:
            seed = r["seed"] if r["seed"] != "NT" else ""
            ok = r["time_v"] and r["seed_v"] and not r["result"].startswith(("DQ", "NS"))
            out.append({"place": r["place"], "name": r["name"], "yr": r["yr"], "team": r["team"], "team_name": names.get(r["team"], ""),
                        "result": r["result"], "points": r["points"], "legs": r["legs"], "dqtxt": r["dqtxt"], "exh": bool(r["exh"]),
                        "seed": seed, "drop": round(r["seed_v"] - r["time_v"], 2) if ok else None})   # + = faster than seed
        sig = hashlib.sha1(json.dumps(out, sort_keys=True).encode()).hexdigest()[:10] if out else ""
        if out:
            latest = v["no"]
        events.append({"no": v["no"], "label": v["label"], "rows": out, "sig": sig})
    scores = []
    sc = scoring or {}
    if sc.get("pairs"):
        many = len(sc["pairs"]) > 1
        for p in sc["pairs"]:
            a, b = teams.get(p["a"], {}), teams.get(p["b"], {})
            for t, o, pts in ((a, b, p["a_pts"]), (b, a, p["b_pts"])):
                scores.append({"name": t.get("name", "") + (f" (vs {o.get('abbr', '')})" if many else ""),
                               "F": round(pts["F"], 1), "M": round(pts["M"], 1), "total": round(pts["F"] + pts["M"], 1)})
    elif sc.get("teams"):
        for t, v in sorted(sc["teams"].items(), key=lambda x: -x[1]["total"]):
            scores.append({"name": teams.get(int(t), {}).get("name", ""), "F": round(v["F"], 1), "M": round(v["M"], 1),
                           "total": round(v["total"], 1)})
    for s in scores:
        for k in ("F", "M", "total"):
            s[k] = int(s[k]) if float(s[k]).is_integer() else s[k]
    return {"meet": {"name": meet.get("name", ""), "location": meet.get("location", ""), "date": _date(meet.get("start"))},
            "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "scored": len(sc.get("events") or []) or sum(1 for e in events if e["rows"]),
            "latest": latest, "scores": scores, "events": events}


# ---- GitHub ----------------------------------------------------------------------
def _api(token: str, method: str, path: str, body=None):
    req = urllib.request.Request("https://api.github.com" + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "User-Agent": "MeetDeck", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        if e.code == 401:
            raise RuntimeError("GitHub didn't accept the token (expired or mistyped?)")
        if e.code in (403, 404):
            raise RuntimeError(f"GitHub refused ({e.code}): the token needs Contents read/write on this repository. {detail}")
        raise RuntimeError(f"GitHub error {e.code}: {detail}")


def site_url(repo: str, domain: str = "") -> str:
    if domain:
        return "https://" + domain.strip().strip("/").removeprefix("https://").removeprefix("http://") + "/"
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


def files(doc: dict, domain: str = "") -> dict:
    f = {"index.html": PAGE.read_text(encoding="utf-8"), "results.json": json.dumps(doc, separators=(",", ":")),
         ".nojekyll": "", "robots.txt": "User-agent: *\nDisallow: /\n"}
    if domain:
        f["CNAME"] = domain.strip().removeprefix("https://").removeprefix("http://").strip("/") + "\n"
    return f


def publish(doc: dict, repo: str, token: str, domain: str = "") -> dict:
    """Replace the site with one new commit holding the page and these results."""
    body = {"tree": [{"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in files(doc, domain).items()]}
    try:
        tree = _api(token, "POST", f"/repos/{repo}/git/trees", body)
    except RuntimeError as e:
        if "empty" not in str(e).lower():
            raise
        # a brand-new repository has no commits, and the git API needs one: add a README first
        import base64
        _api(token, "PUT", f"/repos/{repo}/contents/README.md",
             {"message": "Start", "content": base64.b64encode(b"Live swim meet results, published by MeetDeck to the gh-pages branch.\n").decode()})
        tree = _api(token, "POST", f"/repos/{repo}/git/trees", body)
    commit = _api(token, "POST", f"/repos/{repo}/git/commits",
                  {"message": f"Results {doc['meet']['name']} {doc['updated']}", "tree": tree["sha"], "parents": []})
    try:
        _api(token, "PATCH", f"/repos/{repo}/git/refs/heads/{BRANCH}", {"sha": commit["sha"], "force": True})
    except RuntimeError as e:
        if "422" not in str(e) and "404" not in str(e):
            raise
        _api(token, "POST", f"/repos/{repo}/git/refs", {"ref": f"refs/heads/{BRANCH}", "sha": commit["sha"]})
    _ensure_pages(repo, token, domain)
    _api(token, "POST", f"/repos/{repo}/dispatches", {"event_type": "publish"})
    return {"url": site_url(repo, domain), "commit": commit["sha"][:7], "updated": doc["updated"]}


def _ensure_pages(repo: str, token: str, domain: str):
    try:
        _api(token, "GET", f"/repos/{repo}/pages")
    except RuntimeError:
        try:
            _api(token, "POST", f"/repos/{repo}/pages", {"build_type": "workflow"})
        except RuntimeError:
            pass        # a token without Pages permission: turn Pages on (Source: GitHub Actions) in the repo settings


# ---- throttled auto-publish --------------------------------------------------------
class Publisher:
    """At most one publish every MIN_GAP seconds; changes in between go out together at the end of the gap."""

    def __init__(self):
        self.lock = threading.Lock()
        self.last = {}            # meet id -> time of last publish
        self.timer = {}
        self.status = {}          # meet id -> {ok, at, url | error}

    def request(self, mid: str, job, force=False):
        with self.lock:
            wait = 0 if force else max(0, self.last.get(mid, 0) + MIN_GAP - time.time())
            if mid in self.timer and not force:
                return {"queued": True, "in": round(wait)}
            if mid in self.timer:
                self.timer.pop(mid).cancel()
            if wait <= 0:
                return self._run(mid, job)
            t = threading.Timer(wait, self._timed, (mid, job))
            t.daemon = True
            self.timer[mid] = t
            t.start()
            return {"queued": True, "in": round(wait)}

    def _timed(self, mid, job):
        with self.lock:
            self.timer.pop(mid, None)
            self._run(mid, job)

    def _run(self, mid, job):
        self.last[mid] = time.time()
        try:
            out = job()
            self.status[mid] = {"ok": True, "at": time.strftime("%H:%M:%S"), **out}
        except Exception as e:
            self.status[mid] = {"ok": False, "at": time.strftime("%H:%M:%S"), "error": str(e)}
        return self.status[mid]


PUBLISHER = Publisher()
