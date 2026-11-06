"""Meet Manager database access on Windows, without Java.

Uses Windows' own Microsoft Access (Jet) ODBC driver - the same database engine Meet Manager itself
uses, built into every Windows 10/11 PC (32-bit). Same requests and answers as the Java service
(mmdb/Svc.java + Builder.java), so the rest of MeetDeck doesn't care which one runs:

    read(db, tables)            -> {table: {columns: [...], rows: [...]}}
    apply(db, ops)              -> [{count} | {row}]     ops: update / delete / insert
    build(tpl, spec, out)       -> report dict           (Builder.java main)
    read_master(mdb)            -> dict                  (Builder.java --read-master)
    write_master(mdb, changes)  -> dict                  (Builder.java --write-master)
"""
import datetime as dt
import decimal
import json
import threading
from pathlib import Path

import pyodbc

LOCK = threading.RLock()
_CONN = {}            # db path -> connection
_COLS = {}            # (db, table) -> [col dicts]
_LEARNED = {}         # (db, table) -> (defaults, padded)
PROFILE_FILE = Path(__file__).parent / "mmdb_profile.json"
PROFILE = json.loads(PROFILE_FILE.read_text()) if PROFILE_FILE.exists() else {}

KIND = {"VARCHAR": "TEXT", "CHAR": "TEXT", "LONGCHAR": "MEMO", "BIT": "BOOLEAN", "BYTE": "BYTE", "SMALLINT": "INT",
        "INTEGER": "LONG", "COUNTER": "LONG", "REAL": "FLOAT", "DOUBLE": "DOUBLE", "CURRENCY": "MONEY",
        "DECIMAL": "NUMERIC", "NUMERIC": "NUMERIC", "DATETIME": "SHORT_DATE_TIME"}


def _driver() -> str:
    ds = pyodbc.drivers()
    for want in ("Microsoft Access Driver (*.mdb)", "Microsoft Access Driver (*.mdb, *.accdb)"):
        if want in ds:
            return want
    for d in ds:
        if "(*.mdb" in d:
            return d
    raise RuntimeError("Windows' Microsoft Access database driver wasn't found (needed to open Meet Manager files)")


def conn(path) -> pyodbc.Connection:
    path = str(Path(path).resolve())
    c = _CONN.get(path)
    if c is None:
        import mdbpass        # Meet Manager files carry a database password in their header
        pw = mdbpass.password(path)           # the Jet driver takes it as-is (no {} quoting)
        c = pyodbc.connect(f"DRIVER={{{_driver()}}};DBQ={path};PWD={pw};ExtendedAnsiSQL=1;", autocommit=False)
        _CONN[path] = c
    return c


def close(path):
    with LOCK:
        path = str(Path(path).resolve())
        c = _CONN.pop(path, None)
        for k in [k for k in _COLS if k[0] == path] + [k for k in _LEARNED if k[0] == path]:
            _COLS.pop(k, None)
            _LEARNED.pop(k, None)
        if c is not None:
            try:
                c.close()
            except Exception:
                pass


def close_all():
    for p in list(_CONN):
        close(p)


def q(name: str) -> str:
    return "[" + name.replace("]", "]]") + "]"


# ---- table info --------------------------------------------------------------------------
def tables(path) -> list:
    cur = conn(path).cursor()
    return [r.table_name for r in cur.tables(tableType="TABLE")]


def columns(path, table) -> list:
    key = (str(Path(path).resolve()), table)
    if key not in _COLS:
        cur = conn(path).cursor()
        cols = []
        for r in cur.columns(table=table):
            tn = (r.type_name or "").upper()
            cols.append({"name": r.column_name, "type": KIND.get(tn, "BINARY" if "BINARY" in tn else tn),
                         "auto": tn == "COUNTER", "len": int(r.column_size or 0) if KIND.get(tn) == "TEXT" else 0,
                         "pos": r.ordinal_position})
        cols.sort(key=lambda c: c["pos"])
        if not cols:
            raise ValueError(f"no table {table}")
        _COLS[key] = cols
    return _COLS[key]


def col(path, table, name):
    for c in columns(path, table):
        if c["name"].lower() == name.lower():
            return c
    return None


def has_table(path, table) -> bool:
    return table.lower() in {t.lower() for t in tables(path)}


# ---- values ------------------------------------------------------------------------------
def _iso(v: dt.datetime) -> str:
    """Like Java's LocalDateTime.toString(): 2025-12-19T00:00 (seconds only when present)."""
    s = v.strftime("%Y-%m-%dT%H:%M")
    if v.second or v.microsecond:
        s += v.strftime(":%S")
    return s


def out(v):
    if v is None:
        return None
    if isinstance(v, float):
        return round(v * 100.0) / 100.0 if v == v else None
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, dt.datetime):
        return _iso(v)
    if isinstance(v, dt.date):
        return v.isoformat() + "T00:00"
    if isinstance(v, (bytes, bytearray, memoryview)):
        return None
    return v


def _rows(path, table, where="", params=()):
    cur = conn(path).cursor()
    names = [c["name"] for c in columns(path, table)]
    cur.execute(f"SELECT {', '.join(q(n) for n in names)} FROM {q(table)} {where}", *params)
    return names, cur.fetchall()


# ---- read --------------------------------------------------------------------------------
def read(path, want=None) -> dict:
    with LOCK:
        have = {t.lower(): t for t in tables(path)}
        res = {}
        for tn in (want or list(have.values())):
            real = have.get(tn.lower())
            if not real:
                continue
            cols = columns(path, real)
            names, rows = _rows(path, real)
            res[tn] = {"columns": [{k: c[k] for k in ("name", "type", "auto", "len")} for c in cols],
                       "rows": [{n: out(v) for n, v in zip(names, r)} for r in rows]}
        conn(path).commit()
        return res


# ---- learn Meet Manager's defaults / padding from existing rows (Builder.learn) ------------
NULL = object()


def _blank(v) -> bool:
    if isinstance(v, bool):
        return not v
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (int, float, decimal.Decimal)):
        return v == 0
    return False


def _zero(c):
    return {"BOOLEAN": False, "BYTE": 0, "INT": 0, "LONG": 0, "FLOAT": 0.0, "DOUBLE": 0.0}.get(c["type"])


def _typed(t, v):
    return {"Boolean": lambda x: x == "true", "Byte": int, "Short": int, "Integer": int, "Float": float,
            "Double": float, "BigDecimal": decimal.Decimal}.get(t, lambda x: x)(v)


def learn(path, table, force=False):
    key = (str(Path(path).resolve()), table)
    if key in _LEARNED and not force:
        return _LEARNED[key]
    cols = columns(path, table)
    names, rows = _rows(path, table)
    if not rows and table in PROFILE:
        p = PROFILE[table]
        have = {c["name"] for c in cols}
        d = {k: _typed(v[0], v[1]) for k, v in p["defaults"].items() if k in have}
        _LEARNED[key] = (d, set(p["padded"]))
        return _LEARNED[key]
    counts = {n: {} for n in names}
    pad = {}
    for r in rows:
        for c, v in zip(cols, r):
            kv = NULL if v is None else v
            try:
                counts[c["name"]][kv] = counts[c["name"]].get(kv, 0) + 1
            except TypeError:           # unhashable (binary)
                pass
            if c["type"] == "TEXT" and isinstance(v, str) and v.strip():
                p = pad.setdefault(c["name"], [0, 0])
                p[0] += 1
                if len(v) == c["len"]:
                    p[1] += 1
    d, pads = {}, set()
    for c in cols:
        if c["auto"]:
            continue
        cnt = counts.get(c["name"])
        best = None
        if cnt:
            top = max(cnt.items(), key=lambda kv: kv[1])[0]
            if top is not NULL and _blank(top):
                best = top
            elif top is not NULL and c["type"] == "TEXT":
                best = None
            elif top is not NULL:
                best = _zero(c)
        if best is not None:
            d[c["name"]] = best
        p = pad.get(c["name"])
        if p and p[0] > 0 and p[1] * 2 >= p[0]:
            pads.add(c["name"])
    _LEARNED[key] = (d, pads)
    return _LEARNED[key]


def base(path, table) -> dict:
    return dict(learn(path, table)[0])


def put_text(path, table, r: dict, name, v):
    """Builder.put: trim, cut to the column width, pad to width where Meet Manager pads."""
    c = col(path, table, name)
    if c is None:
        return
    v = (v or "").strip() if v is not None else ""
    w = c["len"] or 255
    v = v[:w]
    if not v:
        if c["name"] not in r:
            r[c["name"]] = None
        return
    if c["name"] in learn(path, table)[1]:
        v = v.ljust(w)
    r[c["name"]] = v


def put_raw(path, table, r: dict, name, v):
    c = col(path, table, name)
    if c is None:
        return
    w = c["len"] or 255
    r[c["name"]] = v[:w] if isinstance(v, str) else v


def _num(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    return float(s or 0)


def _date(s):
    s = str(s).replace("Z", "")
    if len(s) == 10:
        return dt.datetime.fromisoformat(s)
    return dt.datetime.fromisoformat(s[:19])


def put(path, table, r: dict, name, v):
    """Svc.put: a JSON value converted to the column's type."""
    c = col(path, table, name)
    if c is None:
        raise ValueError(f"no column {table}.{name}")
    n = c["name"]
    if v is None:
        r[n] = None
        return
    t = c["type"]
    if t in ("TEXT", "MEMO"):
        s = str(v) if not isinstance(v, bool) else ("true" if v else "false")
        if s == "":
            r[n] = None
        elif not s.strip():
            r[n] = s
        else:
            r.pop(n, None)
            put_text(path, table, r, n, s)
    elif t == "BOOLEAN":
        r[n] = v if isinstance(v, bool) else str(v).lower() == "true"
    elif t in ("BYTE", "INT", "LONG"):
        r[n] = int(round(_num(v)))
    elif t in ("FLOAT", "DOUBLE"):
        r[n] = _num(v)
    elif t in ("MONEY", "NUMERIC"):
        r[n] = decimal.Decimal(str(v))
    elif t == "SHORT_DATE_TIME":
        r[n] = v if isinstance(v, dt.datetime) else _date(v)
    else:
        r[n] = v


# ---- write -------------------------------------------------------------------------------
def _where(path, table, match):
    if not match:
        return "", []
    parts, params = [], []
    for k, want in match.items():
        c = col(path, table, k)
        if c is None:
            raise ValueError(f"no column {table}.{k}")
        n = q(c["name"])
        if want is None:
            parts.append(f"{n} IS NULL")
        elif c["type"] in ("BYTE", "INT", "LONG", "FLOAT", "DOUBLE", "MONEY", "NUMERIC") and not isinstance(want, str):
            parts.append(f"(Abs({n} - ?) < 0.0001)")
            params.append(float(want))
        elif c["type"] == "BOOLEAN":
            parts.append(f"{n} = ?")
            params.append(want if isinstance(want, bool) else str(want).lower() == "true")
        elif c["type"] in ("TEXT", "MEMO"):
            parts.append(f"Trim({n}) = ?")
            params.append(str(want).strip())
        elif c["type"] == "SHORT_DATE_TIME":
            parts.append(f"{n} = ?")
            params.append(_date(want))
        else:
            parts.append(f"{n} = ?")
            params.append(want)
    return "WHERE " + " AND ".join(parts), params


def _param(v):
    if isinstance(v, float):
        return float(v)
    return v


def update(path, table, match, setv: dict, raw=False) -> int:
    if not raw:
        learn(path, table)
        r = {}
        for k, v in setv.items():
            put(path, table, r, k, v)
    else:
        r = setv
    if not r:
        return 0
    w, wp = _where(path, table, match)
    cur = conn(path).cursor()
    cur.execute(f"UPDATE {q(table)} SET {', '.join(q(k) + ' = ?' for k in r)} {w}", *[_param(v) for v in r.values()], *wp)
    return cur.rowcount


def delete(path, table, match) -> int:
    if not match:
        raise ValueError("delete needs a match")
    w, wp = _where(path, table, match)
    cur = conn(path).cursor()
    cur.execute(f"DELETE FROM {q(table)} {w}", *wp)
    return cur.rowcount


def insert_row(path, table, r: dict) -> dict:
    cols = [k for k in r]
    cur = conn(path).cursor()
    cur.execute(f"INSERT INTO {q(table)} ({', '.join(q(k) for k in cols)}) VALUES ({', '.join('?' for _ in cols)})",
                *[_param(r[k]) for k in cols])
    auto = next((c for c in columns(path, table) if c["auto"]), None)
    if auto and auto["name"] not in r:
        cur.execute("SELECT @@IDENTITY")
        r[auto["name"]] = cur.fetchone()[0]
    return r


def insert(path, table, row: dict) -> dict:
    learn(path, table)
    r = base(path, table)
    for k, v in row.items():
        put(path, table, r, k, v)
    r = insert_row(path, table, r)
    return {k: out(v) for k, v in r.items()}


def apply(path, ops) -> list:
    with LOCK:
        have = {t.lower(): t for t in tables(path)}
        c = conn(path)
        res = []
        try:
            for op in ops:
                t = have.get(op["table"].lower())
                if not t:
                    raise ValueError("no table " + op["table"])
                kind = op["op"]
                if kind == "update":
                    res.append({"count": update(path, t, op.get("match"), op["set"])})
                elif kind == "delete":
                    res.append({"count": delete(path, t, op["match"])})
                elif kind == "insert":
                    res.append({"row": insert(path, t, op["row"])})
                else:
                    raise ValueError("bad op " + kind)
            c.commit()
        except Exception:
            c.rollback()
            raise
        return res


# ---- Builder.java: a meet database from a master + spec ------------------------------------
PROFILED = ["RelayNames", "Relay", "Entry", "Split", "Athlete", "TeamCoaches", "Team", "Dualteams", "Records", "RecordTags"]
CLEAR = ["RelayNames", "Relay", "Entry", "Split", "Athlete", "TeamCoaches", "Team", "Dualteams"]
MEET_FIELDS = ["Meet_name1", "Meet_location", "Meet_addr1", "Meet_city", "Meet_state", "Meet_zip"]


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def _ev_key(no, g, dist, stroke, ir):
    g = "F" if g == "W" else g
    return f"{int(no)}|{g}|{int(dist)}|{stroke}|{ir}"


def _clear(path):
    for t in CLEAR:
        learn(path, t)
    cur = conn(path).cursor()
    for t in CLEAR:
        cur.execute(f"DELETE FROM {q(t)}")


def reset_online(path):
    """A new meet must not inherit the template meet's Meet Mobile / online-entry ids or upload flags."""
    for tn in ("MEETMOBILE2OPTIONS", "OMEOPTIONS"):
        if not has_table(path, tn):
            continue
        u = {}
        for c in columns(path, tn):
            n = c["name"].lower()
            if n.endswith("meetid") and c["type"] == "LONG":
                u[c["name"]] = 0
            if (n.endswith("_uploaded") or n == "contract_agreed") and c["type"] == "BOOLEAN":
                u[c["name"]] = False
        if u:
            update(path, tn, None, u, raw=True)


def _seed(path, table, r, e):
    put_text(path, table, r, "ActSeed_course", e.get("course", "Y"))
    put_text(path, table, r, "ConvSeed_course", e.get("conv_course", e.get("course", "Y")))
    r["ActualSeed_time"] = float(e.get("seed", 0) or 0)
    r["ConvSeed_time"] = float(e.get("conv_seed", e.get("seed", 0)) or 0)


def build(tpl, spec, out_path) -> dict:
    import shutil
    if isinstance(spec, (str, Path)) and Path(spec).exists():
        spec = json.loads(Path(spec).read_text())
    shutil.copy(tpl, out_path)
    p = str(out_path)
    warnings = []
    with LOCK:
        try:
            _clear(p)
            cur = conn(p).cursor()
            # ---- events: map + reset per-meet run state ----
            events = {}
            notes = spec.get("event_notes") or {}
            names, rows = _rows(p, "Event")
            for row in rows:
                r = dict(zip(names, row))
                events[_ev_key(r["Event_no"], _s(r["Event_gender"]), r["Event_dist"], _s(r["Event_stroke"]), _s(r["Ind_rel"]))] = r["Event_ptr"]
                u = {}
                ev_no = str(int(r["Event_no"]))
                if ev_no in notes and col(p, "Event", "Comm_1"):
                    put_raw(p, "Event", u, "Comm_1", notes[ev_no])
                for cn in ("Fin_AwardsPrinted", "Pre_AwardsPrinted", "Sem_AwardsPrinted", "Is_locked"):
                    if col(p, "Event", cn):
                        u[col(p, "Event", cn)["name"]] = False
                for cn in ("fin_actualstarttime", "sem_actualstarttime", "pre_actualstarttime"):
                    if col(p, "Event", cn):
                        u[col(p, "Event", cn)["name"]] = 0
                if u:
                    update(p, "Event", {"Event_ptr": r["Event_ptr"]}, u, raw=True)
            # ---- teams ----
            team_no = {}
            for i, t in enumerate(spec["teams"]):
                no = i + 1
                r = base(p, "Team")
                r["Team_no"] = no
                for f, k in (("Team_name", "name"), ("Team_short", "short"), ("Team_abbr", "abbr"), ("Team_lsc", "lsc"),
                             ("Team_addr1", "addr1"), ("Team_addr2", "addr2"), ("Team_city", "city"), ("Team_statenew", "state"),
                             ("Team_zip", "zip"), ("Team_daytele", "phone"), ("Team_email", "email")):
                    put_text(p, "Team", r, f, t.get(k, ""))
                put_text(p, "Team", r, "Team_cntry", t.get("country", "USA"))
                insert_row(p, "Team", r)
                team_no[t["key"]] = no
            # ---- athletes ----
            ath_no, ath_age, ath_team = {}, {}, {}
            for i, s in enumerate(spec["athletes"]):
                tn = team_no.get(s["team"])
                if tn is None:
                    warnings.append(f"Athlete {s.get('last', '')} has unknown team {s['team']}")
                    continue
                no = i + 1
                r = base(p, "Athlete")
                r["Ath_no"] = no
                r["Comp_no"] = no
                for f, k in (("Last_name", "last"), ("First_name", "first"), ("Initial", "initial"), ("Pref_name", "pref"),
                             ("Ath_Sex", "sex"), ("Schl_yr", "class")):
                    put_text(p, "Athlete", r, f, s.get(k, ""))
                r["Team_no"] = tn
                if int(s.get("age") or 0) > 0:
                    r["Ath_age"] = int(s["age"])
                if s.get("dob"):
                    r["Birth_date"] = dt.datetime.fromisoformat(s["dob"][:10])
                insert_row(p, "Athlete", r)
                ath_no[s["key"]] = no
                ath_age[s["key"]] = int(s.get("age") or 0)
                ath_team[s["key"]] = tn
            # ---- individual entries ----
            n_ent = n_seeded = 0
            has_age = col(p, "Entry", "event_age") is not None
            for e in spec["entries"]:
                ptr = events.get(_ev_key(e["event_no"], e["gender"], e["distance"], e["stroke"], "I"))
                an = ath_no.get(e["athlete"])
                if ptr is None:
                    warnings.append(f"No matching event in the template for #{e['event_no']} {e.get('label', '')} ({e.get('who', '')}) - entry skipped")
                    continue
                if an is None:
                    warnings.append(f"Entry for unknown athlete {e['athlete']}")
                    continue
                r = base(p, "Entry")
                r["Event_ptr"] = ptr
                r["Ath_no"] = an
                _seed(p, "Entry", r, e)
                if ath_age.get(e["athlete"], 0) > 0 and has_age:
                    r[col(p, "Entry", "event_age")["name"]] = ath_age[e["athlete"]]
                if e.get("exh"):
                    put_text(p, "Entry", r, "Fin_exh", "X")
                if "lane" in e:
                    r["Fin_heat"], r["Fin_lane"] = int(e["heat"]), int(e["lane"])
                    n_seeded += 1
                insert_row(p, "Entry", r)
                n_ent += 1
            # ---- relays ----
            n_rel = rel_no = 0
            cross = False
            for e in spec["relays"]:
                ptr = events.get(_ev_key(e["event_no"], e["gender"], e["distance"], e["stroke"], "R"))
                tn = team_no.get(e["team"])
                if ptr is None:
                    warnings.append(f"No matching relay event in the template for #{e['event_no']} {e.get('label', '')} - relay skipped")
                    continue
                if tn is None:
                    warnings.append(f"Relay for unknown team {e['team']}")
                    continue
                rel_no += 1
                ltr = e.get("letter", "A")
                r = base(p, "Relay")
                r["Relay_no"], r["Event_ptr"], r["Team_no"] = rel_no, ptr, tn
                put_text(p, "Relay", r, "Team_ltr", ltr)
                put_text(p, "Relay", r, "Rel_sex", "F" if e["gender"] == "W" else e["gender"])
                if "lane" in e:
                    r["Fin_heat"], r["Fin_lane"] = int(e["heat"]), int(e["lane"])
                    n_seeded += 1
                _seed(p, "Relay", r, e)
                insert_row(p, "Relay", r)
                n_rel += 1
                for leg, who in (e.get("legs") or {}).items():
                    an = ath_no.get(who)
                    if an is None:
                        warnings.append(f"Relay leg athlete not found: {who}")
                        continue
                    if tn != ath_team.get(who):
                        cross = True
                    n = base(p, "RelayNames")
                    n["Event_ptr"], n["Team_no"] = ptr, tn
                    put_text(p, "RelayNames", n, "Team_ltr", ltr)
                    n["Ath_no"], n["Pos_no"] = an, int(leg)
                    put_text(p, "RelayNames", n, "Event_round", "F")
                    n["Relay_no"] = rel_no
                    insert_row(p, "RelayNames", n)
            # ---- dual pairings: every team vs every other, girls and boys ----
            scoring = [team_no[k] for k in spec.get("scoring_teams", []) if k in team_no]
            if len(scoring) >= 2:
                for g in ("F", "M"):
                    for x in range(len(scoring)):
                        for y in range(x + 1, len(scoring)):
                            r = base(p, "Dualteams")
                            r.update({"team_gender": g, "ateam_no": scoring[x], "bteam_no": scoring[y]})
                            insert_row(p, "Dualteams", r)
            # ---- team-record tags belong to the home team of THIS meet ----
            tags_given = spec.get("team_tags")
            team_tags = {int(k) for k in (tags_given or [])}
            rec_team = team_no.get(spec.get("record_team", ""), 0)
            names, rows = _rows(p, "RecordTags")
            for row in rows:
                r = dict(zip(names, row))
                cur_t = r.get("team_no")
                is_team = r["tag_ptr"] in team_tags or (tags_given is None and cur_t is not None and cur_t > 0)
                if is_team:
                    update(p, "RecordTags", {"tag_ptr": r["tag_ptr"]}, {"team_no": rec_team}, raw=True)
                elif cur_t is not None and cur_t > 0:
                    update(p, "RecordTags", {"tag_ptr": r["tag_ptr"]}, {"team_no": 0}, raw=True)
            # ---- meet record ----
            m = spec["meet"]
            mu = {}
            put_raw(p, "Meet", mu, "Meet_name1", m["name"])
            if m.get("date"):
                d = dt.datetime.fromisoformat(m["date"][:10])
                mu["Meet_start"] = mu["Meet_end"] = d
            if m.get("location"):
                put_raw(p, "Meet", mu, "Meet_location", m["location"])
            lanes = spec["lanes"]
            mu["meet_numlanes"] = int(lanes["count"])
            mu["meet_meetstyle"] = 3 if len(scoring) >= 3 else (2 if len(scoring) == 2 else 1)
            for i in range(1, 13):
                c = col(p, "Meet", f"dualteam_lane{i}")
                if c:
                    mu[c["name"]] = 0
            for l in lanes.get("plan", []):
                tn = team_no.get(l["team"])
                slot = 10 if int(l["lane"]) == 0 else int(l["lane"])     # MM: the lane-0 team goes in the Lane 10 slot
                c = col(p, "Meet", f"dualteam_lane{slot}")
                if tn is not None and c:
                    mu[c["name"]] = tn
            mu["dual_evenodd"] = len(lanes.get("plan", [])) > 0
            if cross:
                mu["anyone_onrelay"] = True
            now = dt.datetime.now()
            put_raw(p, "Meet", mu, "Last_updated", f"{now.month}/{now.day}/{now.year} {now.strftime('%I').lstrip('0')}:{now.strftime('%M:%S %p')}")
            mu = {col(p, "Meet", k)["name"]: v for k, v in mu.items() if col(p, "Meet", k)}
            update(p, "Meet", None, mu, raw=True)
            reset_online(p)
            conn(p).commit()
        except Exception:
            conn(p).rollback()
            raise
        finally:
            close(p)
    return {"teams": len(team_no), "athletes": len(ath_no), "entries": n_ent, "relays": n_rel,
            "meet_style": mu.get("meet_meetstyle"), "anyone_on_relay": cross, "preseeded": n_seeded, "warnings": warnings}


def read_master(mdb) -> dict:
    p = str(mdb)
    with LOCK:
        try:
            names, rows = _rows(p, "Meet")
            m = dict(zip(names, rows[0]))
            meet = {f: _s(m.get(f)) for f in MEET_FIELDS}
            meet["Meet_start"] = _iso(m["Meet_start"]) if isinstance(m.get("Meet_start"), dt.datetime) else _s(m.get("Meet_start"))
            names, rows = _rows(p, "RecordTags")
            tags = [{"tag_ptr": r["tag_ptr"], "order": r["tag_order"], "name": _s(r["tag_name"]), "flag": _s(r["tag_flag"]),
                     "team_no": r["team_no"] or 0} for r in (dict(zip(names, x)) for x in rows)]
            names, rows = _rows(p, "Records")
            recs = [{"tag_ptr": r["tag_ptr"], "gender": _s(r["tag_gender"]), "indrel": _s(r["tag_indrel"]), "dist": r["tag_dist"],
                     "stroke": _s(r["tag_stroke"]), "holder": _s(r["Record_Holder"]), "team": _s(r["Record_Holderteam"]),
                     "relay_names": _s(r["Relay_Names"]), "time": float(r["Record_Time"] or 0), "year": r["Record_year"] or 0,
                     "month": r["Record_month"] or 0, "day": r["Record_day"] or 0, "course": _s(r["Record_course"])}
                    for r in (dict(zip(names, x)) for x in rows)]
            names, rows = _rows(p, "Event")
            evs = [{"no": r["Event_no"], "gender": _s(r["Event_gender"]), "indrel": _s(r["Ind_rel"]), "dist": int(r["Event_dist"] or 0),
                    "stroke": _s(r["Event_stroke"])} for r in (dict(zip(names, x)) for x in rows)]
            cur = conn(p).cursor()
            cnt = {}
            for k, t in (("teams", "Team"), ("athletes", "Athlete"), ("entries", "Entry"), ("sessions", "Session"), ("officials", "Officials")):
                cur.execute(f"SELECT COUNT(*) FROM {q(t)}")
                cnt[k] = cur.fetchone()[0]
            return {"meet": meet, "tags": tags, "records": recs, "events": evs, "counts": cnt}
        finally:
            close(p)


def write_master(mdb, changes) -> dict:
    if isinstance(changes, (str, Path)) and Path(changes).exists():
        changes = json.loads(Path(changes).read_text())
    c = changes
    p = str(mdb)
    with LOCK:
        try:
            if c.get("clear_people"):
                _clear(p)
                reset_online(p)
            if "meet" in c:
                u = {}
                m = c["meet"]
                for f in MEET_FIELDS:
                    if f in m and col(p, "Meet", f):
                        v = str(m[f]).strip()
                        if v:
                            put_raw(p, "Meet", u, f, v)
                        else:
                            u[col(p, "Meet", f)["name"]] = None
                if c.get("clear_people"):
                    for i in range(1, 13):
                        cc = col(p, "Meet", f"dualteam_lane{i}")
                        if cc:
                            u[cc["name"]] = 0
                    u["meet_meetstyle"] = 1
                    u["dual_evenodd"] = False
                u = {col(p, "Meet", k)["name"]: v for k, v in u.items() if col(p, "Meet", k)}
                if u:
                    update(p, "Meet", None, u, raw=True)
            if "tags" in c:
                learn(p, "RecordTags")
                tags = c["tags"]
                keep = {int(t["tag_ptr"]) for t in tags}
                names, rows = _rows(p, "RecordTags")
                have = set()
                for row in rows:
                    ptr = dict(zip(names, row))["tag_ptr"]
                    if ptr not in keep:
                        delete(p, "RecordTags", {"tag_ptr": ptr})
                        continue
                    have.add(ptr)
                    j = next(t for t in tags if int(t["tag_ptr"]) == ptr)
                    u = {}
                    put_text(p, "RecordTags", u, "tag_name", j["name"])
                    put_text(p, "RecordTags", u, "tag_flag", j.get("flag") or "*")
                    u["tag_order"] = int(j.get("order", 1))
                    u["team_no"] = 0
                    update(p, "RecordTags", {"tag_ptr": ptr}, u, raw=True)
                for i, j in enumerate(tags):
                    if int(j["tag_ptr"]) in have:
                        continue
                    r = base(p, "RecordTags")
                    r["tag_ptr"] = int(j["tag_ptr"])
                    put_text(p, "RecordTags", r, "tag_name", j["name"])
                    put_text(p, "RecordTags", r, "tag_flag", j.get("flag") or "*")
                    r["tag_order"] = int(j.get("order", i + 1))
                    r["team_no"] = 0
                    r["allow_exh"] = True
                    insert_row(p, "RecordTags", r)
            if "records" in c:
                learn(p, "Records")
                conn(p).cursor().execute(f"DELETE FROM {q('Records')}")
                for j in c["records"]:
                    r = base(p, "Records")
                    r["tag_ptr"] = int(j["tag_ptr"])
                    put_text(p, "Records", r, "tag_gender", j["gender"])
                    put_text(p, "Records", r, "tag_indrel", j["indrel"])
                    r["tag_dist"] = int(j["dist"])
                    put_text(p, "Records", r, "tag_stroke", j["stroke"])
                    r["low_age"], r[col(p, "Records", "high_Age")["name"]] = 0, 109
                    put_text(p, "Records", r, "Record_Holder", j.get("holder", ""))
                    put_text(p, "Records", r, "Record_Holderteam", j.get("team", ""))
                    put_text(p, "Records", r, "Relay_Names", j.get("relay_names", ""))
                    r["Record_Time"] = float(j["time"])
                    put_text(p, "Records", r, "Record_course", j.get("course") or "Y")
                    r["Record_year"], r["Record_month"], r["Record_day"] = int(j.get("year", 0)), int(j.get("month", 0)), int(j.get("day", 0))
                    insert_row(p, "Records", r)
            conn(p).commit()
        except Exception:
            conn(p).rollback()
            raise
        finally:
            close(p)
    return read_master(mdb)
