"""Scanned paper from the timing table (referee programs first): kept with the meet, read by Claude, and checked
against the meet - finish order against the times, DQs the referee wrote against what's in the meet. Nothing changes
in the meet by itself; the run page's Scans tab shows what was read and the operator applies it.

Storage: <meet>/scans/<id>.<ext> and <meet>/scans/index.json (its own file, so reading a scan in the background
never races the meet's meta.json)."""
import base64
import io
import json
import secrets
import threading
import time
from pathlib import Path

import claude_api
import dqcodes
import meetdb

EXTS = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".tif": "image/tiff", ".tiff": "image/tiff"}
_LOCK = threading.Lock()


# ---------------- storage ----------------
def _dir(d: Path) -> Path:
    p = d / "scans"
    p.mkdir(exist_ok=True)
    return p


def load(d: Path) -> dict:
    f = d / "scans" / "index.json"
    try:
        idx = json.loads(f.read_text()) if f.exists() else {}
    except ValueError:
        idx = {}
    idx.setdefault("scans", [])
    idx.setdefault("marks", {})
    return idx


def _write(d: Path, idx: dict):
    f = _dir(d) / "index.json"
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, indent=1))
    tmp.replace(f)


def update(d: Path, fn):
    """Change the index under the lock: fn(idx) edits it in place."""
    with _LOCK:
        idx = load(d)
        out = fn(idx)
        _write(d, idx)
        return out


def add(d: Path, data: bytes, name: str, source: str) -> dict:
    ext = Path(name).suffix.lower()
    if ext not in EXTS:
        raise ValueError("Scans can be PDF, JPG, PNG or TIFF")
    sid = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
    (_dir(d) / f"{sid}{ext}").write_bytes(data)
    rec = {"id": sid, "name": name, "ext": ext, "bytes": len(data), "source": source,
           "received": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "new", "pages": [], "error": ""}
    update(d, lambda idx: idx["scans"].append(rec))
    return rec


def path_of(d: Path, rec: dict) -> Path:
    return d / "scans" / f"{rec['id']}{rec['ext']}"


# ---------------- reading with Claude ----------------
SYSTEM = """You read scanned paper forms from a high school swim meet's timing table. Most are the referee's program:
printed event titles ("Event 12  Girls 100 Yard Freestyle"), "Heat N of M" headings, a row per lane with the swimmer or
relay team, a small DQ checkbox, one or two Code boxes and an Infraction box, and under each heat an order-of-finish row
of boxes labelled 1st, 2nd, 3rd... where the referee writes lane numbers. Older referee programs have no boxes: there the
referee writes DQ notes and codes by hand beside the lane.

Report every page. For each heat printed on a page give the printed event number and heat number, every lane the
referee marked as a DQ (box checked, a code written, an infraction written, or a handwritten DQ note) with exactly what
is written, and the order of finish as the lane numbers written in the place boxes (only boxes with something in them,
in place order). Copy handwriting as written - never invent a DQ or a lane. When a mark, letter or digit is hard to read,
give your best reading and set unsure. List every heat on the page even when nothing is written (empty dqs and finish),
so it's clear the page was read. A page that isn't a referee program (a timer sheet, a note, a blank page) gets the
matching kind and a short note.

Give your answer only by calling the report_pages tool, once, with every page."""

TOOL = {
    "name": "report_pages",
    "description": "What is written on each scanned page.",
    "input_schema": {
        "type": "object",
        "properties": {"pages": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "description": "1-based page number in the file"},
                "kind": {"type": "string", "enum": ["referee", "timer", "other", "blank"]},
                "note": {"type": "string", "description": "anything else written on the page worth knowing"},
                "heats": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "event": {"type": "integer"},
                        "heat": {"type": "integer"},
                        "dqs": {"type": "array", "items": {
                            "type": "object",
                            "properties": {
                                "lane": {"type": "integer"},
                                "box_checked": {"type": "boolean"},
                                "code": {"type": "string", "description": "DQ code as written, e.g. 7B; empty if none"},
                                "code2": {"type": "string", "description": "second code (medley events), empty if none"},
                                "infraction": {"type": "string", "description": "words written, empty if none"},
                                "unsure": {"type": "boolean"}},
                            "required": ["lane", "code", "infraction", "unsure"]}},
                        "finish": {"type": "array", "items": {
                            "type": "object",
                            "properties": {"place": {"type": "integer"}, "lane": {"type": "integer"}, "unsure": {"type": "boolean"}},
                            "required": ["place", "lane"]}},
                        "note": {"type": "string"}},
                    "required": ["event", "heat", "dqs", "finish"]}}},
            "required": ["page", "kind", "heats"]}}},
        "required": ["pages"]},
}


def _codes_hint() -> str:
    return "DQ codes this meet uses (code: meaning): " + "; ".join(f"{c['code']}: {c['desc']}" for c in dqcodes.CODES)


def _content(path: Path, ext: str) -> list:
    data = path.read_bytes()
    if ext == ".pdf":
        if len(data) > 30_000_000:
            raise claude_api.ClaudeError("That PDF is over 30 MB - scan fewer pages per file, or at a lower resolution")
        return [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                "data": base64.b64encode(data).decode()}}]
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    frames = []
    try:
        for i in range(getattr(im, "n_frames", 1)):     # multi-page TIFF
            im.seek(i)
            frames.append(im.copy())
    except EOFError:
        pass
    out = []
    for fr in frames[:20]:
        fr = fr.convert("L") if fr.mode not in ("L", "RGB") else fr
        fr.thumbnail((2200, 2200))
        b = io.BytesIO()
        fr.save(b, "JPEG", quality=88)
        out.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(b.getvalue()).decode()}})
    return out


def read(d: Path, sid: str, key: str, model: str = ""):
    """Send one scan to Claude and keep what it read (runs in a background thread)."""
    rec = next((s for s in load(d)["scans"] if s["id"] == sid), None)
    if not rec:
        return

    def mark(**kw):
        def fn(idx):
            for s in idx["scans"]:
                if s["id"] == sid:
                    s.update(kw)
        update(d, fn)
    mark(status="reading", error="")
    try:
        content = _content(path_of(d, rec), rec["ext"]) + [{"type": "text", "text": _codes_hint() + "\n\nReport every page of this scan."}]
        r = claude_api.call(key, content, model=model, max_tokens=16000, system=SYSTEM, timeout=240, tool=TOOL)
        pages = (r.get("data") or {}).get("pages") or []
        mark(status="done", pages=pages, model=r.get("model"), read_at=time.strftime("%Y-%m-%d %H:%M:%S"),
             usage=r.get("usage"), ms=r.get("ms"))
    except Exception as e:
        mark(status="error", error=str(e))


def read_async(d: Path, sid: str, key: str, model: str = ""):
    threading.Thread(target=read, args=(d, sid, key, model), daemon=True).start()


# ---------------- checking against the meet ----------------
def _event(m, no):
    for v in m["events"]:
        try:
            if int(v["no"]) == int(no):
                return v
        except (TypeError, ValueError):
            continue
    return None


def check(m: dict, idx: dict) -> list:
    """Each scan with what it read, checked against the meet: per heat, the finish order next to the order of the
    times, and each DQ next to the swimmer and what the meet already has."""
    out = []
    marks = idx.get("marks") or {}
    for s in idx["scans"]:
        pages = []
        for p in s.get("pages") or []:
            heats = []
            for h in p.get("heats") or []:
                v = _event(m, h.get("event"))
                hh = {"event": h.get("event"), "heat": h.get("heat"), "note": h.get("note") or "", "found": bool(v)}
                if not v:
                    hh["problem"] = f"No event {h.get('event')} in this meet"
                    heats.append(hh)
                    continue
                hh["label"] = meetdb.ev_label(m, v["ptr"])
                ents = [e for e in m["entries"] if e["event"] == v["ptr"] and e.get("heat") == h.get("heat") and not e.get("scr")]
                by_lane = {e["lane"]: e for e in ents}
                if not ents:
                    hh["problem"] = f"Event {h.get('event')} has no heat {h.get('heat')}"
                # finish order: the referee's lanes against the lanes in time order (DQs with a time still swam)
                ref = [f for f in sorted(h.get("finish") or [], key=lambda f: f.get("place") or 99) if f.get("lane")]
                timed = sorted((e for e in ents if (e.get("time") or 0) > 0 and (e.get("stat") or "").strip() not in ("F", "D", "R")),
                               key=lambda e: e["time"])
                fin = {"ref": [{"lane": f["lane"], "unsure": bool(f.get("unsure")), "who": meetdb.who(m, by_lane[f["lane"]]) if f["lane"] in by_lane else ""}
                               for f in ref],
                       "times": [{"lane": e["lane"], "t": e["time"], "who": meetdb.who(m, e)} for e in timed]}
                # compare the lanes the referee wrote that have a time: their order by time against the referee's order
                tl = [e["lane"] for e in timed]
                ref_t = [f["lane"] for f in ref if f["lane"] in tl]
                tl_f = [ln for ln in tl if ln in ref_t]
                fin["empty_lanes"] = [f["lane"] for f in ref if f["lane"] not in by_lane]
                fin["untimed"] = [f["lane"] for f in ref if f["lane"] in by_lane and f["lane"] not in tl]
                by_t = {e["lane"]: e for e in timed}
                fin["times"] = [{"lane": ln, "t": by_t[ln]["time"], "who": meetdb.who(m, by_t[ln])} for ln in tl_f]
                if not ref:
                    fin["verdict"] = "none"
                elif not ref_t:
                    fin["verdict"] = "no_times"
                else:
                    fin["diffs"] = [i for i in range(len(ref_t)) if ref_t[i] != tl_f[i]]
                    fin["ref"] = [r for r in fin["ref"] if r["lane"] in tl] + [r for r in fin["ref"] if r["lane"] not in tl]
                    fin["verdict"] = "agree" if not fin["diffs"] and not fin["empty_lanes"] else "differs"
                    ts = fin["times"]   # close finishes the pads may have split differently
                    fin["close"] = [i for i in range(len(ts) - 1) if ts[i + 1]["t"] - ts[i]["t"] <= 0.10]
                hh["finish"] = fin
                dqs = []
                for i, q in enumerate(h.get("dqs") or []):
                    lane = q.get("lane")
                    e = by_lane.get(lane)
                    code = (q.get("code") or "").strip().upper().replace(" ", "")
                    code2 = (q.get("code2") or "").strip().upper().replace(" ", "")
                    item = f"{s['id']}:{p.get('page')}:{h.get('event')}:{h.get('heat')}:{lane}"
                    dd = {"item": item, "lane": lane, "code": code, "code2": code2, "infraction": q.get("infraction") or "",
                          "box": bool(q.get("box_checked")), "unsure": bool(q.get("unsure")), "state": marks.get(item, "")}
                    dd["code_ok"] = code in dqcodes.BY_CODE
                    dd["code2_ok"] = not code2 or code2 in dqcodes.BY_CODE
                    if dd["code_ok"]:
                        dd["desc"] = dqcodes.describe(code, v.get("stroke", ""), v.get("ind_rel") == "R")
                        dd["no_time"] = code in dqcodes.NO_TIME
                    if code2 and dd["code2_ok"]:
                        dd["desc2"] = dqcodes.describe(code2, v.get("stroke", ""), True)
                    if not e:
                        dd["problem"] = f"Nobody in lane {lane} in this heat"
                    else:
                        st = (e.get("stat") or "").strip()
                        dd.update(key=e["key"], who=meetdb.who(m, e), time=e.get("time") or 0,
                                  meet_dq=(e.get("dq") or "").upper() if st in ("Q", "F", "D") else "", meet_ns=st == "R")
                        if dd["meet_dq"] and dd["meet_dq"] == code:
                            dd["already"] = True
                    dqs.append(dd)
                hh["dqs"] = dqs
                heats.append(hh)
            pages.append({"page": p.get("page"), "kind": p.get("kind"), "note": p.get("note") or "", "heats": heats})
        out.append({**{k: s.get(k) for k in ("id", "name", "ext", "bytes", "source", "received", "status", "error", "model", "read_at")},
                    "pages": pages})
    return out[::-1]                       # newest first
