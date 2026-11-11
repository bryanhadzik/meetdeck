"""Timing bridge: runs on the laptop at the timing table and connects the CTS System 6 (COM PORT 1)
to the Meet Entry Check database page in the browser.

    python bridge.py                 start; connect from the database page (Timing console panel)
    python bridge.py --sim           pretend console (no hardware) for practice and testing
    python bridge.py probe COM5      find the serial settings the console answers on
    python bridge.py races COM5      list stored races in the console's current meet

Needs Python 3.9+ and pyserial (pip install pyserial). Listens on http://localhost:8766 only.
Every byte to and from the console is logged in cts-log.txt next to this file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cts  # noqa: E402

VERSION = "0.1 (untested on hardware)"
LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cts-log.txt")
LOCK = threading.Lock()
STATE = {"console": None, "serial": None, "port": None, "settings": None, "identity": None, "sim": False,
         "last_probe": None, "connected_at": None, "last_connect_error": None}
STARTED = time.strftime("%Y-%m-%d %H:%M:%S")
RECENT: list[str] = []


def _ascii(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


def log(direction: str, data: bytes):
    line = f"{time.strftime('%H:%M:%S')} {direction:7} {data.hex(' ')}  |{_ascii(data)}| ({len(data)} B)"
    RECENT.append(line)
    del RECENT[:-400]
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def note(text: str):
    line = f"{time.strftime('%H:%M:%S')} ---     {text}"
    RECENT.append(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")


def disconnect():
    s = STATE.get("serial")
    if s:
        try:
            s.close()
        except Exception:
            pass
    STATE.update(console=None, serial=None, port=None, settings=None, identity=None, sim=False)


def connect(body: dict) -> dict:
    if body.get("sim") and STATE["sim"] and STATE["console"]:
        return status()             # already on the simulator - keep its stored races
    disconnect()
    if body.get("sim"):
        from sim import SimConsole
        sim = SimConsole(lanes=int(body.get("lanes", 8)), times_per_lane=int(body.get("times_per_lane", 5)), buttons=1)
        c = cts.Console(sim, log=log, settle=0)
        STATE.update(console=c, serial=sim, port="SIMULATOR", settings={}, identity=c.who_are_you(), sim=True)
        note("connected to simulator")
        return status()
    port = body.get("port")
    if not port:
        raise ValueError("pick a COM port")
    info = next((p for p in cts.list_ports(detail=True) if p["port"] == port), None)
    note(f"connect {port}: {info or 'not in the port list'}")
    if body.get("baudrate"):
        s = {"baudrate": int(body["baudrate"]), "parity": body.get("parity", "N"), "stopbits": float(body.get("stopbits", 1))}
        try:
            ser = cts.open_serial(port, **s)
        except Exception as e:
            STATE["last_connect_error"] = cts.explain_open_error(port, e)
            note(STATE["last_connect_error"])
            raise ValueError(STATE["last_connect_error"])
        c = cts.Console(ser, log=log)
        try:
            ident = c.who_are_you()
        except Exception as e:
            ser.close()
            STATE["last_connect_error"] = f"{port} {s}: {e}"
            note(STATE["last_connect_error"])
            raise ValueError(STATE["last_connect_error"])
    else:
        note(f"probing {port}")
        attempts = []
        found = cts.probe(port, log=log, attempts=attempts)
        STATE["last_probe"] = {"port": port, "when": time.strftime("%H:%M:%S"), "attempts": attempts}
        for a in attempts:
            note(f"probe {port} {a['settings']}: {a['result']}")
        if not found or "identity" not in found:
            err = (found or {}).get("error") or (
                f"the console didn't answer on {port} at any of the usual settings - check the cable is in COM PORT 1 and the console is on. "
                + ("Some bytes came back, so the line is live but the settings or protocol don't match. " if any(a.get("bytes_in") for a in attempts)
                   else "Nothing at all came back - usually the wrong port, a loose/unplugged cable, or a cable that needs a null-modem adapter. "))
            STATE["last_connect_error"] = err
            raise ValueError(err)
        ser = found.pop("serial")
        ident = found.pop("identity")
        found.pop("attempts", None)
        s = found
        c = cts.Console(ser, log=log)
    STATE.update(console=c, serial=ser, port=port, settings=s, identity=ident, sim=False,
                 connected_at=time.strftime("%H:%M:%S"), last_connect_error=None)
    note(f"connected {port} {s} '{ident}' {cts.port_details(ser)}")
    return status()


def debug() -> dict:
    """Everything useful for chasing a serial problem, in one place (Timing console > Serial debug)."""
    import platform
    try:
        import serial
        pyser = getattr(serial, "__version__", "?")
    except ImportError:
        pyser = "NOT INSTALLED (pip install pyserial)"
    c, ser = STATE["console"], STATE["serial"]
    real = ser is not None and not STATE["sim"]
    try:
        log_size = os.path.getsize(LOG_PATH)
    except OSError:
        log_size = 0
    return {**status(), "python": sys.version.split()[0], "platform": platform.platform(), "pyserial": pyser,
            "bridge_started": STARTED, "connected_at": STATE["connected_at"], "ports_detail": cts.list_ports(detail=True),
            "serial": cts.port_details(ser) if real else None, "stats": c.stats if c else None,
            "last_probe": STATE["last_probe"], "last_connect_error": STATE["last_connect_error"], "log_bytes": log_size}


def ping() -> dict:
    """Send the identity request once and time the answer."""
    c = need()
    t0 = time.time()
    ident = c.who_are_you()
    return {"identity": ident, "ms": round((time.time() - t0) * 1000), "stats": c.stats}


def listen(body: dict) -> dict:
    """Read whatever arrives on the line for a few seconds, without sending anything. Shows whether the
    console (or anything) is talking at all, and what it looks like at these settings."""
    secs = min(max(float(body.get("secs", 5)), 0.5), 30)
    own = None
    if STATE["serial"] is not None and not STATE["sim"]:
        ser = STATE["serial"]
    elif STATE["sim"]:
        raise ValueError("the simulator doesn't send anything on its own")
    else:
        port = body.get("port")
        if not port:
            raise ValueError("pick a COM port")
        s = {"baudrate": int(body.get("baudrate", 9600)), "parity": body.get("parity", "N"), "stopbits": float(body.get("stopbits", 1))}
        try:
            own = ser = cts.open_serial(port, **s)
        except Exception as e:
            raise ValueError(cts.explain_open_error(port, e))
    buf = b""
    end = time.time() + secs
    try:
        while time.time() < end:
            chunk = ser.read(512)
            if chunk:
                buf += chunk
            else:
                time.sleep(0.02)
        lines = cts.port_details(ser)
    finally:
        if own:
            own.close()
    if buf:
        log("<listen", buf)
    note(f"listened {secs:g}s on {lines.get('port')} {lines.get('baudrate')} {lines.get('parity')}{lines.get('stopbits')}: {len(buf)} bytes")
    return {"secs": secs, "bytes": len(buf), "hex": buf[:600].hex(" "), "ascii": _ascii(buf[:600]), "serial": lines}


def probe_only(body: dict) -> dict:
    """Try every usual setting on a port and report each one; doesn't stay connected."""
    port = body.get("port")
    if not port:
        raise ValueError("pick a COM port")
    if STATE["port"] == port and not STATE["sim"]:
        raise ValueError(f"already connected on {port} - disconnect first")
    attempts = []
    found = cts.probe(port, log=log, attempts=attempts)
    if found and found.get("serial"):
        found["serial"].close()
    STATE["last_probe"] = {"port": port, "when": time.strftime("%H:%M:%S"), "attempts": attempts}
    for a in attempts:
        note(f"probe {port} {a['settings']}: {a['result']}")
    return STATE["last_probe"]


def status() -> dict:
    return {"bridge": VERSION, "connected": bool(STATE["console"]), "port": STATE["port"], "settings": STATE["settings"],
            "identity": STATE["identity"], "sim": STATE["sim"], "ports": cts.list_ports(), "log": LOG_PATH}


def need():
    if not STATE["console"]:
        raise ValueError("not connected to a console")
    return STATE["console"]


def get_race(q: dict) -> dict:
    c = need()
    if q.get("race"):
        r = c.race(int(q["race"]))
    elif q.get("event"):
        r = c.race_by_heat(int(q["event"]), int(q.get("heat", 1)))
    elif q.get("current"):
        r = c.race_current()
    else:
        r = c.race_last()
    return r.as_dict()


def sim_load(body: dict) -> dict:
    if not STATE["sim"]:
        raise ValueError("only for the simulator")
    sim = STATE["serial"]
    for r in body.get("races", []):
        sim.add_race(int(r["event"]), int(r["heat"]), {int(k): v for k, v in r["results"].items()}, set(r.get("dq", [])))
    return {"races": len(sim.races)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code: int, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self._cors()
        self.end_headers()
        self.wfile.write(b)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _run(self, fn, *a):
        try:
            with LOCK:
                self._send(200, fn(*a))
        except (ValueError, cts.CTSError) as e:
            note(f"error: {e}")
            self._send(400, {"error": str(e)})
        except Exception as e:  # keep the bridge alive
            note(f"error: {type(e).__name__}: {e}")
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        routes = {"/status": status, "/races": lambda: need().race_list(), "/race": lambda: get_race(q),
                  "/meet": lambda: need().meet(int(q.get("dir", 0))), "/log": lambda: {"lines": RECENT[-int(q.get("n", 200)):]},
                  "/sequence": lambda: {"slot": int(q.get("slot", 1)), "title": need().sequence_title(int(q.get("slot", 1)))},
                  "/debug": debug}
        if u.path not in routes:
            return self._send(404, {"error": "not found"})
        self._run(routes[u.path])

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        routes = {"/connect": lambda: connect(body), "/disconnect": lambda: (disconnect(), status())[1],
                  "/download": lambda: need().download_meet(int(body.get("slot", 1)), body["events"], body.get("title")),
                  "/sim/load": lambda: sim_load(body), "/ping": ping, "/listen": lambda: listen(body),
                  "/probe": lambda: probe_only(body)}
        if u.path not in routes:
            return self._send(404, {"error": "not found"})
        self._run(routes[u.path])


def main():
    ap = argparse.ArgumentParser(description="CTS System 6 timing bridge")
    ap.add_argument("cmd", nargs="?", default="serve", choices=["serve", "probe", "races"])
    ap.add_argument("port", nargs="?")
    ap.add_argument("--sim", action="store_true", help="connect to the pretend console at start-up")
    ap.add_argument("--listen", type=int, default=8766)
    ap.add_argument("--host", default="127.0.0.1", help="interface to listen on (keep 127.0.0.1 at a meet)")
    a = ap.parse_args()
    if a.cmd == "probe":
        found = cts.probe(a.port, log=lambda d, b: print(d, b.hex(" ")))
        print("RESULT:", {k: v for k, v in (found or {}).items() if k != "serial"} or "no answer")
        return
    if a.cmd == "races":
        connect({"port": a.port})
        for r in STATE["console"].race_list():
            print(r)
        return
    if a.sim:
        connect({"sim": True})
    srv = ThreadingHTTPServer((a.host, a.listen), Handler)
    print(f"Timing bridge {VERSION} on http://localhost:{a.listen}  (log: {LOG_PATH})")
    print("Open the meet database page and use the Timing console panel. Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        disconnect()


if __name__ == "__main__":
    main()
