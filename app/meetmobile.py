"""Meet Mobile (Active Network) publishing, the way Hy-Tek Meet Manager does it.

Meet Manager talks SOAP to https://awapi.active.com (worked out from a capture of Meet Manager 8.0Gh's
"Meet Mobile" upload, Nov 2026):
  /swimming-meet-manager-service   checkAgencyExists(appToken, licenseName)
  /sports-swimming-management-service
      uploadMeetManagerData(appToken, intPoint=ResultsMeet, activeMeetId, meetData)  -> activeMeetId
      savePplFile(appToken, activeMeetId, file)        teams + athletes
      saveStdFile(appToken, activeMeetId, file)        record lists (one call), time standards (another)
      saveHyiFileSync(appToken, activeMeetId, file)    one event: heats, lanes, results, relay swimmers, splits
Every file is Hy-Tek's semicolon text, base64 encoded. The appToken comes from the Meet Manager license and is
kept only in this PC's settings.
"""
import base64
import datetime as dt
import hashlib
import re
import urllib.request
from xml.sax.saxutils import escape

import meetdb

API = "https://awapi.active.com"
STROKE = {"A": "Free", "B": "Back", "C": "Breast", "D": "Fly", "E": "IM"}
REL_STROKE = {"A": "Free Relay", "E": "Medley Relay"}
COURSE_WORD = {"Y": "Yard", "S": "Meter", "L": "Meter"}


# ---------------------------------------------------------------- formatting helpers
def _d(iso) -> str:
    """'2026-11-20...' -> '11/20/2026'"""
    s = str(iso or "")[:10]
    return f"{s[5:7]}/{s[8:10]}/{s[0:4]}" if len(s) == 10 and s[4] == "-" else ""


def _num(x) -> str:
    """Meet Manager's plain number: 121.1, 25.08, 120, 0"""
    x = round(float(x or 0), 2)
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def _t(x) -> str:
    return meetdb.fmt_time(x) if x else ""


def _clock(sec, space=True) -> str:
    h, mi = divmod(int(sec or 0) // 60, 60)
    return f"{(h - 1) % 12 + 1:02d}:{mi:02d}{' ' if space else ''}{'AM' if h % 24 < 12 else 'PM'}"


def _gword(g) -> str:
    return "Women" if g in ("F", "W", "G") else ("Mixed" if g == "X" else "Men")


def _gsex(g) -> str:
    return "W" if g in ("F", "W", "G") else ("X" if g == "X" else "M")


def event_name(v, course="Y", short=False) -> str:
    """'Women 200 Yard Medley Relay' (short: 'Women 200 Medley Relay')."""
    st = REL_STROKE.get(v["stroke"], "Relay") if v["ind_rel"] == "R" else STROKE.get(v["stroke"], v["stroke"])
    mid = "" if short else f" {COURSE_WORD.get(course, 'Yard')}"
    return f"{_gword(v['gender'] or v['sex'])} {v['dist']}{mid} {st}"


def _team(name) -> str:
    """Meet Manager writes an all-capitals word in a team name in mixed case: '(UT)' -> '(Ut)'."""
    return re.sub(r"[A-Z]{2,}", lambda w: w.group(0).capitalize(), name or "")


def _first(a) -> str:
    return a.get("pref") or a.get("first", "")


def _b64(text: str) -> str:
    b = base64.b64encode(text.encode("latin-1", "replace")).decode()
    return "\n".join(b[i:i + 72] for i in range(0, len(b), 72))


# ---------------------------------------------------------------- the files
def _sess_of(m):
    out = {}
    for s in m.get("sessions", []):
        for it in s["items"]:
            out.setdefault(it["event"], (s, it["order"]))
    return out


def meet_data(m, raw_meet: dict, licensee: str, est: dict | None = None, today=None) -> str:
    """uploadMeetManagerData's meetData: the meet line, then one line per event (in session order)."""
    mt, r = m["meet"], raw_meet or {}
    today = today or dt.date.today()
    course = {1: "L", 2: "S", 3: "Y"}.get(mt.get("course") or 3, "Y")
    imax, rmax = r.get("indmaxscorers_perteam") or 0, r.get("relmaxscorers_perteam") or 0
    head = [mt["name"], mt["location"], _d(mt["start"]), _d(mt["end"] or mt["start"]), _d(mt.get("calc_date")) or _d(mt["start"]),
            "Y", "0", "0", "0", mt.get("header1") or "Created by Hy-Tek's MEET MANAGER", licensee, "8.0Gh",
            today.strftime("%m/%d/%Y"), "A", "", str(int(mt.get("altitude") or 0)), "01/01/1970", "0",
            str(imax), str(rmax), str(mt.get("course") or 3), str(mt.get("style") or 1), "H",
            _d(mt.get("calc_date")) or _d(mt["start"]), mt.get("addr1", ""), mt.get("addr2", ""), mt.get("city", ""),
            mt.get("state", ""), mt.get("zip", ""), mt.get("country", "") or "USA", (r.get("Meet_hostlsc") or mt.get("state") or "").strip(),
            "N", "N", "0", _d(r.get("athlete_earlysurchargedate")) or _d(mt["start"]), "0", _d(r.get("athlete_latesurchargedate")) or _d(mt["start"]),
            "MW", "0.00", "0", "6204u"]
    lines = [";".join(str(x) for x in head)]
    sess = _sess_of(m)
    for v in m["events"]:
        s, order = sess.get(v["ptr"], ({"no": 1, "day": 1, "start": 0, "course": course}, v["no"]))
        relay = v["ind_rel"] == "R"
        lines.append(";".join(str(x) for x in [
            v["ptr"], v["no"], "F", 1, v["ind_rel"], _gsex(v["gender"] or v["sex"]), 0, 109, v["dist"], v["stroke"], 0, "", "", "N", 0,
            "", "", "", "", "", "", s["no"], order, s.get("day") or 1, _clock(s.get("start"), False), s.get("course") or course,
            imax, rmax, mt.get("course") or 3, (v.get("legs") or 4) if relay else 0, s["no"], "", "",
            (est or {}).get(v["ptr"]) or _clock(s.get("start")), _gword(v["gender"] or v["sex"]), event_name(v, course)]))
    return "".join(x + "*>\r\n" for x in lines)


def ppl_file(m) -> str:
    """savePplFile: every team ($T) with its athletes ($A), teams by name, athletes by last/first name."""
    out = []
    for t in sorted(m["teams"].values(), key=lambda t: (t["name"] or "").lower()):
        out.append(f"$T;{t['no']};{_team(t['name'])};{t['abbr']};{t['lsc']}")
        aths = sorted((a for a in m["athletes"].values() if a["team"] == t["no"]),
                      key=lambda a: ((a["last"] or "").lower(), (a["first"] or "").lower()))
        for a in aths:
            out.append(f"$A;{a['no']};{a['last']};{_first(a)};{a['initial']};{a['sex']};{a['yr']};{t['no']}")
    return "".join(x + "\r\n" for x in out)


def std_file(m, records: list, tags: list) -> str:
    """saveStdFile: record lists ($B tag, $D one line per event that has a record)."""
    out = []
    for n, tag in enumerate(sorted(tags, key=lambda t: t.get("tag_order") or 0), 1):
        out.append(f"$B;{tag['tag_name']};R;{n:02d}")
        for v in m["events"]:
            g = _gsex(v["gender"] or v["sex"])
            rec = next((r for r in records if r["tag_ptr"] == tag["tag_ptr"] and _gsex((r.get("tag_gender") or "").strip()) == g
                        and (r.get("tag_indrel") or "").strip() == v["ind_rel"] and int(r.get("tag_dist") or 0) == v["dist"]
                        and (r.get("tag_stroke") or "").strip() == v["stroke"] and r.get("Record_Time")), None)
            if rec:
                t = float(rec["Record_Time"])
                out.append(f"$D;{_t(t)};{_num(t)};{v['no']};{event_name(v, short=True)};{_gword(v['gender'] or v['sex'])};; ;0;109;S")
    return "".join(x + "\r\n" for x in out)


NO_STANDARDS = "$B;No Standards;T;01\r\n"


def _special(e):
    st = (e["stat"] or "").strip()
    if st in ("Q",) or (st in ("F", "D") and not e["time"] and (e.get("dq") or "").upper() not in ("",) and st != "F"):
        return "DQ", 1
    if st == "F":
        return "DFS", 3
    if st == "D":
        return "DQ", 1
    if st == "R":
        return "NS", 4
    return None, 0


def hyi_file(m, v, splits: dict, course="Y") -> str:
    """saveHyiFileSync: one event - $H per heat, $L per lane (finishers by heat place, then the rest), $N relay
    swimmers, $S splits."""
    sess = _sess_of(m).get(v["ptr"], ({"no": 1}, 0))[0]
    ents = [e for e in m["entries"] if e["event"] == v["ptr"] and not e["scr"] and e["heat"]]
    heats = sorted({e["heat"] for e in ents})
    relay = v["ind_rel"] == "R"
    aths, teams = m["athletes"], m["teams"]
    name = event_name(v, course)
    counters = {}
    out = []
    for h in heats:
        out.append(f"$H;{v['no']} ;1;{h};{len(heats)};1;{name};F;{v['ind_rel']};0;109;{v['dist']};{v['stroke']};{course};{sess['no']};Y")
        hs = [e for e in ents if e["heat"] == h]
        fin = sorted((e for e in hs if e["time"] and not _special(e)[0] and not e.get("exh")), key=lambda e: (e["heatplace"] or 99, e["time"]))
        rest = [e for e in hs if e not in fin]
        for e in fin + sorted(rest, key=lambda e: e["lane"]):
            sp, kind = _special(e)
            if e.get("exh") and not sp:
                sp, kind = "EXH", 0
            seed = e["seed"] or 0
            if sp and sp != "EXH":
                counters[kind] = counters.get(kind, 0) + 1
                hp, over, fstr, fsec, diff = sp, 10000 + kind * 100 + counters[kind], sp, str(50000 + kind), "0"
            else:
                if sp == "EXH":
                    counters[0] = counters.get(0, 0) + 1
                    hp, over = "EXH", 10000 + counters[0]
                else:
                    hp, over = e["heatplace"] or "", e["place"] or ""
                fstr, fsec = _t(e["time"]), _num(e["time"])
                diff = _num(e["time"] - seed) if seed and e["time"] else "0"
            pts = _num(e.get("points") or 0)
            tail = f"{_t(seed) or 'NT'};{seed:.2f};;{fstr};{fsec}; ;{pts};;{diff};S; 01; "
            if relay:
                t = teams.get(e["team"], {})
                g = "F" if _gsex(v["gender"] or v["sex"]) == "W" else ("X" if _gsex(v["gender"] or v["sex"]) == "X" else "M")
                out.append(f"$L;{hp};0;{e['lane']};{over};{_team(t.get('name', ''))};{e.get('ltr') or 'A'};;{g};0;{t.get('no', '')};"
                           f"{_team(t.get('name', ''))};{t.get('abbr', '')};{t.get('lsc', '')};{tail}")
                legs = []
                for a in (e.get("legs") or [])[:4]:
                    p = aths.get(a)
                    legs.append(f"{p['no']};{p['last']};{_first(p)};{p['initial']};{p['sex']};{p['yr']}" if p else ";;;;;")
                if legs:      # Meet Manager: the first two legs run together, the others are set apart by "; ;"
                    out.append(f"$N;{e['lane']};" + ";".join(legs[:2]) + ("; ;" + "; ;".join(legs[2:]) if legs[2:] else "") + "; ")
                key = f"R:{e['relay']}"
            else:
                a = aths.get(e["ath"], {})
                t = teams.get(a.get("team"), {})
                out.append(f"$L;{hp};{a.get('no', '')};{e['lane']};{over};{a.get('last', '')};{_first(a)};{a.get('initial', '')};"
                           f"{a.get('sex', '')};{a.get('yr', '')};{t.get('no', '')};{_team(t.get('name', ''))};{t.get('abbr', '')};{t.get('lsc', '')};{tail}")
                key = f"E:{e['event']}:{e['ath']}"
            cum = [x for _, x in splits.get(key, []) if x]
            if e["time"] and not (sp and sp != "EXH"):
                if not cum or abs(cum[-1] - e["time"]) > 0.001:
                    cum = cum + [e["time"]]
                if len(cum) > 1:
                    step = v["dist"] // len(cum)
                    parts, prev = [], 0.0
                    for i, c in enumerate(cum, 1):
                        parts.append(f"{step * i};{_t(c)};({_t(round(c - prev, 2))})")
                        prev = c
                    out.append(f"$S;{e['lane']};{len(cum)};" + ";".join(parts))
    return "".join(x + "\r\n" for x in out)


def signature(text: str) -> str:
    return hashlib.sha1(text.encode("latin-1", "replace")).hexdigest()[:12]


# ---------------------------------------------------------------- talking to Active
def _soap(path: str, op: str, token: str, fields: list, timeout=60) -> str:
    body = "".join(f"<{k}>{v if k in ('meetData', 'file') else escape(str(v))}</{k}>" for k, v in fields)
    env = ('<?xml version="1.0"?>\n<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
           'xmlns:api="https://awapi.active.com"><soap:Header/><soap:Body>'
           f'<api:{op}><context><appToken>{escape(token)}</appToken></context>{body}</api:{op}></soap:Body></soap:Envelope>')
    req = urllib.request.Request(API + path, data=env.encode("utf-8"), method="POST",
                                 headers={"Content-Type": "text/xml; charset=utf-8", "Accept": "text/xml"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        f = re.search(r"<faultstring>(.*?)</faultstring>", txt, re.S)
        raise RuntimeError(f"Meet Mobile said: {f.group(1).strip() if f else e}")
    f = re.search(r"<faultstring>(.*?)</faultstring>", txt, re.S)
    if f:
        raise RuntimeError(f"Meet Mobile said: {f.group(1).strip()}")
    r = re.search(r"<return>(.*?)</return>", txt, re.S)
    return r.group(1) if r else ""


def check_agency(token: str, license_name: str) -> dict:
    ret = _soap("/swimming-meet-manager-service", "checkAgencyExists", token, [("licenseName", license_name)])
    p = ret.split(";")
    if not ret or not p[0].isdigit():
        raise RuntimeError(f"Meet Mobile doesn't know the license '{license_name}'")
    return {"agency": p[0], "name": p[3] if len(p) > 3 else "", "facility": p[5] if len(p) > 5 else ""}


SVC = "/sports-swimming-management-service"


def upload_meet(token, meet_id, meet_text) -> str:
    ret = _soap(SVC, "uploadMeetManagerData", token, [("intPoint", "ResultsMeet"), ("activeMeetId", meet_id or ""), ("meetData", _b64(meet_text))])
    return ret.strip() or str(meet_id or "")


def upload_file(token, meet_id, op, text):
    _soap(SVC, op, token, [("activeMeetId", meet_id), ("file", _b64(text))])
