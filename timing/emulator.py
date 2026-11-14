"""CTS System 6 console EMULATOR on a real (or virtual) COM port.

Plays the console's side of the computer interface (COM PORT 1) so that
Meet Manager - or MeetDeck's timing bridge - can be pointed at it as if it
were the real console. Every byte both ways is logged and decoded, and what
was sent to it (event sequences, label tables, titles) is saved as a capture.

    python emulator.py COM6                    act as the console on COM6
    python emulator.py COM6 --parity E         if the other side uses 8-E-1
    python emulator.py COM6 --practice         preload a few stored races to read back
    python emulator.py COM6 --listen-only      never answer; just record what arrives
    python emulator.py --list                  list COM ports
    python emulator.py COM1 --forward COM5     TAP: Meet Manager on COM2 talks THROUGH this to the
                                               real console on COM5; both directions are recorded

Hooking it up (the program on the other side needs a COM port too):
  * two USB-serial adapters joined by a NULL-MODEM cable (or a null-modem adapter), or
  * a virtual pair from com0com: e.g. COM6 <-> COM7. Run the emulator on COM6 and
    point Meet Manager (or the bridge) at COM7.

Files written next to this script:
  emulator-log.txt        every message, time-stamped, hex + text + what it means
  emulator-capture.json   what the other side stored in the "console": event sequences,
                          labels, titles, plus a count of every command it used and any
                          bytes it sent that weren't a valid console message
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cts  # noqa: E402
from sim import SimConsole  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def timing_dir() -> str:
    """Logs and captures live in Documents\\MeetDeck\\timing (MEETDECK_DATA) so an update,
    which replaces the app folder, doesn't throw them away. Run on its own: next to this file."""
    d = os.path.join(os.environ["MEETDECK_DATA"], "timing") if os.environ.get("MEETDECK_DATA") else HERE
    os.makedirs(d, exist_ok=True)
    return d


LOG = os.path.join(timing_dir(), "emulator-log.txt")
CAPTURE = os.path.join(timing_dir(), "emulator-capture.json")
TABLES = {0: "sex", 1: "age group", 2: "stroke", 3: "bracket"}


def token_words(tokens) -> str:
    """Event label tokens -> words using Meet Manager's standard tables (e.g. 04 0f 10 27 28 -> Girls Medley Relay Final)."""
    out = []
    for t in tokens:
        if not t:
            continue
        for table, base in sorted(cts.TOKEN_BASE.items(), key=lambda kv: -kv[1]):
            if t >= base:
                names = dict(cts.MM_LABELS)[table]
                i = t - base
                out.append(names[i] if i < len(names) else "")
                break
    return " ".join(w for w in out if w)


def ts():
    t = time.time()
    return time.strftime("%H:%M:%S", time.localtime(t)) + ".%03d" % int((t % 1) * 1000)


def printable(b: bytes) -> str:
    return "".join(chr(c) if 32 <= c < 127 else "." for c in b)


class Recorder:
    def __init__(self, path=LOG):
        self.f = open(path, "a", encoding="utf-8")
        self.f.write("\n===== emulator started %s =====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        self.f.flush()

    def line(self, text: str, echo=True):
        self.f.write(text + "\n")
        self.f.flush()
        if echo:
            print(text)

    def msg(self, direction: str, data: bytes, meaning: str = ""):
        self.line("%s %s %-4d %s" % (ts(), direction, len(data), meaning), echo=True)
        for i in range(0, len(data), 24):
            chunk = data[i:i + 24]
            self.line("              %-72s %s" % (chunk.hex(" "), printable(chunk)), echo=False)


def describe(cmd: bytes) -> str:
    """Plain words for a console command (payload between length and checksum)."""
    if not cmd:
        return "empty"
    two = cmd[:2]
    if cmd == b"W":
        return "WHO ARE YOU (version)"
    if cmd == b"T":
        return "CURRENT MEET"
    if cmd in (b"M+", b"M-"):
        return "NEXT MEET" if cmd == b"M+" else "PREVIOUS MEET"
    if two == b"SR" and len(cmd) >= 4:
        return "EVENT/HEAT OF STORED RACE %d" % cts.u16(cmd[2], cmd[3])
    if cmd[:4] == b"SSBI":
        m = cmd[4:5]
        if m == b"E" and len(cmd) >= 7:
            return "RACE DATA for event %d heat %d" % (cmd[6], cmd[5])
        if m == b"R" and len(cmd) >= 7:
            return "RACE DATA for race #%d" % ((cmd[5] << 8) | cmd[6])
        return "RACE DATA (%s)" % {b"C": "current", b"L": "last", b"N": "next"}.get(m, m.decode("latin-1", "replace"))
    if two == b"Rs" and len(cmd) >= 3:
        return "READ MEET NAME slot %d" % cmd[2]
    if two == b"Is" and len(cmd) >= 3:
        return "WRITE MEET NAME slot %d = %r" % (cmd[2], cmd[3:].split(b"\x00")[0].decode("latin-1"))
    if two == b"Ir" and len(cmd) >= 3:
        return "FINISH DOWNLOAD / MAKE MEET %d ACTIVE" % cmd[2]
    if two == b"Rt" and len(cmd) >= 4:
        return "READ LABEL %s #%d" % (TABLES.get(cmd[2], "table %d" % cmd[2]), cmd[3])
    if two == b"It" and len(cmd) >= 4:
        text = cmd[4:].split(b"\x00")[0].decode("latin-1")
        return "WRITE LABEL %s #%d = %r" % (TABLES.get(cmd[2], "table %d" % cmd[2]), cmd[3], text)
    if two == b"Ru" and len(cmd) >= 5:
        return "READ EVENT %d in slot %d" % (cts.u16(cmd[3], cmd[4]), cmd[2])
    if two == b"Iu" and len(cmd) >= 5:
        slot, ev = cmd[2], cts.u16(cmd[3], cmd[4])
        rest = cmd[5:]
        if rest == bytes(8) or not any(rest):
            return "CLEAR EVENT %d in slot %d" % (ev, slot)
        dist = cts.u16(rest[0], rest[1]) if len(rest) >= 2 else 0
        return "WRITE EVENT %d in slot %d: %d %s" % (ev, slot, dist, token_words(rest[2:]))
    return "UNKNOWN %r" % printable(cmd[:12])


class Emulator:
    def __init__(self, ser, rec: Recorder, listen_only=False, sim=None, delay_ms=0, pace_baud=0):
        self.ser, self.rec, self.listen_only = ser, rec, listen_only
        self.delay_ms, self.pace_baud = delay_ms, pace_baud     # act like a real console: think, then send at line speed
        self.sim = sim or SimConsole()
        self.buf = b""
        self.last_rx = 0.0
        self.counts: dict[str, int] = {}
        self.unknown: list[str] = []
        self.garbage: list[str] = []
        self.started = time.strftime("%Y-%m-%d %H:%M:%S")
        self.t0 = None
        self.messages: list[list] = []          # [ms since the first message, hex, meaning] in arrival order

    # ---- framing: [len lo][len hi][command...][check lo][check hi] ----
    def feed(self, data: bytes, now: float):
        if data:
            self.buf += data
            self.last_rx = now
        while len(self.buf) >= 2:
            n = cts.u16(self.buf[0], self.buf[1])
            if n < 5 or n > 4096:                      # not a length: unknown format, wait for a pause
                break
            if len(self.buf) < n:
                if now - self.last_rx > 0.5:           # stopped short: not a frame after all
                    break
                return
            msg, self.buf = self.buf[:n], self.buf[n:]
            if not cts.check_ok(msg):
                self.raw(msg, "BAD CHECKSUM (serial settings wrong? try --parity E or O)")
                continue
            self.message(msg)
        # anything left that isn't a message: record it once the line goes quiet
        if self.buf and now - self.last_rx > 0.15:
            self.raw(self.buf, "NOT A CONSOLE MESSAGE")
            self.buf = b""

    def raw(self, data: bytes, why: str):
        self.rec.msg("<<", data, why)
        self.garbage.append(data.hex(" "))
        self.bump("(not a console message)")

    def message(self, msg: bytes):
        cmd = msg[2:-2]
        what = describe(cmd)
        self.bump(re.sub(r"\d+", "#", what.split(":")[0].split(" = ")[0]) if not what.startswith("UNKNOWN")
                  else "UNKNOWN " + printable(cmd[:2]))
        self.rec.msg("<<", msg, what)
        now = time.time()
        self.t0 = self.t0 or now
        if len(self.messages) < 5000:
            self.messages.append([round((now - self.t0) * 1000), msg.hex(" "), what])
        if what.startswith("UNKNOWN"):
            self.unknown.append(msg.hex(" "))
        if self.listen_only:
            return
        self.sim.write(msg)
        reply = self.sim.read(1 << 16)
        if reply:
            meaning = ("ACK" if reply[2:4] == cts.ACK else "error reply") if len(reply) == 6 else "reply"
            if self.delay_ms:
                time.sleep(self.delay_ms / 1000.0)
            if self.pace_baud:                  # one byte at a time, ~10 bits each, like a real 9600 line
                gap = 10.0 / self.pace_baud
                for b in reply:
                    self.ser.write(bytes((b,)))
                    self.ser.flush()
                    time.sleep(gap)
            else:
                self.ser.write(reply)
            self.rec.msg(">>", reply, meaning)
        else:
            self.rec.line("%s    (no reply - the real console doesn't answer this one, as far as we know)" % ts())
        if cmd[:2] in (b"Iu", b"It", b"Ir", b"Is"):
            self.save()

    def bump(self, k):
        self.counts[k] = self.counts.get(k, 0) + 1

    # ---- capture ----
    def save(self):
        s = self.sim
        events = {}
        for (slot, ev), data in sorted(s.events.items()):
            d = data + bytes(8)
            events.setdefault(str(slot), {})[str(ev)] = {
                "distance": cts.u16(d[0], d[1]), "bytes": data.hex(" "),
                "description": token_words(d[2:2 + cts.TOKENS]), "tokens": list(d[2:2 + cts.TOKENS]),
            }
        labels = {}
        for (t, i), text in sorted(s.labels.items()):
            labels.setdefault(TABLES.get(t, "table %d" % t), {})[str(i)] = text
        out = {"started": self.started, "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
               "active_sequence": s.active_slot, "meet_names": s.titles, "event_sequences": events, "labels": labels,
               "commands_seen": self.counts, "unknown_commands": self.unknown[-50:],
               "not_console_messages": self.garbage[-50:], "messages": self.messages}
        with open(CAPTURE, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)


class Framer:
    """Splits one direction of traffic into console messages (or raw chunks) and records them."""
    def __init__(self, rec, arrow, describe_fn):
        self.rec, self.arrow, self.describe = rec, arrow, describe_fn
        self.buf, self.last = b"", 0.0
        self.messages = []

    def feed(self, data: bytes, now: float):
        if data:
            self.buf += data
            self.last = now
        while len(self.buf) >= 2:
            n = cts.u16(self.buf[0], self.buf[1])
            if n < 5 or n > 4096 or (len(self.buf) < n and now - self.last > 0.5):
                break
            if len(self.buf) < n:
                return
            msg, self.buf = self.buf[:n], self.buf[n:]
            what = self.describe(msg) if cts.check_ok(msg) else "BAD CHECKSUM"
            self.rec.msg(self.arrow, msg, what)
            self.messages.append({"t": ts(), "dir": self.arrow, "hex": msg.hex(" "), "what": what})
        if self.buf and now - self.last > 0.15:
            self.rec.msg(self.arrow, self.buf, "NOT A CONSOLE MESSAGE")
            self.messages.append({"t": ts(), "dir": self.arrow, "hex": self.buf.hex(" "), "what": "raw"})
            self.buf = b""


def tap(a, rec):
    """Sit between Meet Manager and the REAL console: pass every byte through, record both directions."""
    mm = cts.open_serial(a.port, baudrate=a.baud, parity=a.parity, stopbits=a.stopbits, timeout=0)
    con = cts.open_serial(a.forward, baudrate=a.baud, parity=a.parity, stopbits=a.stopbits, timeout=0)
    to_con = Framer(rec, "MM>", lambda m: describe(m[2:-2]))
    to_mm = Framer(rec, "<CTS", lambda m: ("error reply %d" % cts.u16(m[2], m[3])) if len(m) == 6 else "console reply (%d bytes)" % len(m))
    rec.line("TAP: Meet Manager side %s  <->  real console %s  (%d %s-%d). Ctrl+C to stop."
             % (a.port, a.forward, a.baud, a.parity, a.stopbits))
    path = os.path.join(HERE, "tap-capture.json")

    def write():
        msgs = sorted(to_con.messages + to_mm.messages, key=lambda m: m["t"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"saved": time.strftime("%Y-%m-%d %H:%M:%S"), "settings": "%d %s-%d" % (a.baud, a.parity, a.stopbits),
                       "messages": msgs}, f, indent=1)
        return msgs
    last_save, seen = 0.0, 0
    try:
        while True:
            x = mm.read(4096)
            if x:
                con.write(x)
            y = con.read(4096)
            if y:
                mm.write(y)
            now = time.time()
            to_con.feed(x, now)
            to_mm.feed(y, now)
            n = len(to_con.messages) + len(to_mm.messages)
            if n != seen and now - last_save > 2:
                write(); last_save, seen = now, n
            if not x and not y:
                time.sleep(0.002)
    except KeyboardInterrupt:
        pass
    finally:
        to_con.feed(b"", time.time() + 1); to_mm.feed(b"", time.time() + 1)
        msgs = write()
        rec.line("Stopped. %d messages. Send %s and %s" % (len(msgs), LOG, path))
        mm.close(); con.close()


def rotate():
    """Keep the last run's log and capture under their time stamp, so each run starts clean
    and two runs (Meet Manager, then MeetDeck) can be compared."""
    for path in (CAPTURE, LOG):
        if os.path.exists(path) and os.path.getsize(path):
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(os.path.getmtime(path)))
            base, ext = os.path.splitext(path)
            try:
                os.replace(path, "%s-%s%s" % (base, stamp, ext))
            except OSError:
                pass


def captures() -> list:
    """Every capture in the timing folder, newest first."""
    d = timing_dir()
    fs = [os.path.join(d, n) for n in os.listdir(d) if n.startswith("emulator-capture") and n.endswith(".json")]
    return sorted(fs, key=os.path.getmtime, reverse=True)


def compare(path_a: str, path_b: str) -> list:
    """Differences between two captures: what each side left on the console (meet names, labels,
    events per slot, active meet) and how each sent it (order of messages, timing)."""
    a, b = (json.load(open(p, encoding="utf-8")) for p in (path_a, path_b))
    na, nb = os.path.basename(path_a), os.path.basename(path_b)
    out = ["A = %s (%s)" % (na, a.get("saved", "")), "B = %s (%s)" % (nb, b.get("saved", ""))]

    def diff(title, x, y):
        keys = sorted(set(x) | set(y), key=lambda k: (len(str(k)), str(k)))
        rows = [(k, x.get(k), y.get(k)) for k in keys if x.get(k) != y.get(k)]
        if rows:
            out.append("")
            out.append(title + ":")
            for k, va, vb in rows:
                out.append("  %-6s A: %s" % (k, va if va is not None else "(missing)"))
                out.append("  %-6s B: %s" % ("", vb if vb is not None else "(missing)"))
        return bool(rows)

    same = True
    same &= not diff("Active meet slot", {"slot": a.get("active_sequence")}, {"slot": b.get("active_sequence")})
    same &= not diff("Meet names", {k: v for k, v in (a.get("meet_names") or {}).items() if v},
                     {k: v for k, v in (b.get("meet_names") or {}).items() if v})
    for t in sorted(set(a.get("labels", {})) | set(b.get("labels", {}))):
        same &= not diff("Labels - " + t, a.get("labels", {}).get(t, {}), b.get("labels", {}).get(t, {}))
    ea, eb = a.get("event_sequences", {}), b.get("event_sequences", {})
    for slot in sorted(set(ea) | set(eb)):
        fa = {k: "%s  %s" % (v["bytes"], v["description"]) for k, v in ea.get(slot, {}).items()}
        fb = {k: "%s  %s" % (v["bytes"], v["description"]) for k, v in eb.get(slot, {}).items()}
        same &= not diff("Events in meet slot " + slot, fa, fb)
        out.append("")
        out.append("Meet slot %s: A has %d events, B has %d" % (slot, len(fa), len(fb)))
    ma, mb = a.get("messages") or [], b.get("messages") or []
    if ma and mb:
        out.append("")
        out.append("Messages: A sent %d in %.1f s, B sent %d in %.1f s" % (len(ma), ma[-1][0] / 1000, len(mb), mb[-1][0] / 1000))
        for i, (x, y) in enumerate(zip(ma, mb)):
            if x[1] != y[1]:
                same = False
                out.append("First difference at message %d:" % (i + 1))
                out.append("  A: %s   %s" % (x[1], x[2]))
                out.append("  B: %s   %s" % (y[1], y[2]))
                break
        else:
            if len(ma) != len(mb):
                same = False
                longer, who = (ma, "A") if len(ma) > len(mb) else (mb, "B")
                out.append("Same messages in the same order, but %s went on with:" % who)
                for m in longer[min(len(ma), len(mb)):][:10]:
                    out.append("  %s   %s" % (m[1], m[2]))
            else:
                out.append("Every message is the same, in the same order.")

        def gaps(ms):
            g = sorted(y[0] - x[0] for x, y in zip(ms, ms[1:]))
            return "median %d ms, longest %d ms" % (g[len(g) // 2], g[-1]) if g else "-"
        out.append("Gap between messages: A %s; B %s" % (gaps(ma), gaps(mb)))
    out.append("")
    out.append("SAME: both left the console identical." if same else "DIFFERENT - see above.")
    return out


def practice(sim: SimConsole):
    import random
    rng = random.Random(3)
    for ev in (1, 2, 3, 4):
        for heat in (1, 2):
            sim.add_race(ev, heat, {ln: round(rng.uniform(25, 70) * (4 if ev in (1, 2) else 1), 2) for ln in range(1, 8)})


def main():
    ap = argparse.ArgumentParser(description="CTS System 6 console emulator")
    ap.add_argument("port", nargs="?")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--parity", default="N", choices=["N", "E", "O"])
    ap.add_argument("--stopbits", type=int, default=1, choices=[1, 2])
    ap.add_argument("--listen-only", action="store_true", help="record but never answer")
    ap.add_argument("--practice", action="store_true", help="preload stored races (events 1-4, heats 1-2)")
    ap.add_argument("--lanes", type=int, default=8)
    ap.add_argument("--delay", type=int, default=40, help="ms to wait before answering (a real console isn't instant)")
    ap.add_argument("--no-pace", action="store_true", help="send replies in one burst instead of at line speed")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--compare", nargs="*", metavar="CAPTURE",
                    help="compare two captures (default: the two newest) and print the differences")
    ap.add_argument("--forward", metavar="CONSOLE_PORT",
                    help="TAP mode: pass everything through to the REAL console on this port and record both ways")
    a = ap.parse_args()
    if a.compare is not None:
        fs = a.compare or captures()[:2][::-1]
        if len(fs) < 2:
            print("Need two captures to compare (found %d in %s)." % (len(fs), timing_dir()))
        else:
            text = "\n".join(compare(fs[0], fs[1]))
            print(text)
            with open(os.path.join(timing_dir(), "emulator-compare.txt"), "w", encoding="utf-8") as f:
                f.write(text + "\n")
        if sys.stdin and sys.stdin.isatty():
            input("\nPress Enter to close.")
        return
    interactive = not a.port and sys.stdin and sys.stdin.isatty()
    if a.list or not a.port:
        ports = cts.list_ports(detail=True)
        print("COM ports on this PC:")
        for p in ports:
            print("  %-6s %s" % (p.get("port") or p.get("device") or "", p.get("description") or p.get("desc") or ""))
        if not ports:
            print("  (none - plug in the USB-serial adapters or set up the com0com pair first)")
        if a.list:
            return
        if not interactive:
            print("\nUsage: python emulator.py COM6   (see the top of this file for hook-up)")
            return
        # double-clicked / started with no port: ask instead of closing straight away
        print("\nThe emulator takes ONE end of the pair; point Meet Manager at the OTHER end.")
        a.port = input("COM port for the emulator (e.g. COM6): ").strip().upper()
        if not a.port:
            return
        if a.port.isdigit():
            a.port = "COM" + a.port
        a.practice = a.practice or input("Load practice races so 'get times' has something to read? [Y/n]: ").strip().lower() != "n"
        par = input("Parity N, E or O [N]: ").strip().upper()[:1]
        if par in ("E", "O"):
            a.parity = par
    if a.forward:
        try:
            tap(a, Recorder())
        except Exception as e:
            print(cts.explain_open_error(a.forward, e) if "could not open" in str(e) else e)
        if interactive:
            input("\nPress Enter to close.")
        return
    try:
        ser = cts.open_serial(a.port, baudrate=a.baud, parity=a.parity, stopbits=a.stopbits, timeout=0.02)
    except Exception as e:
        print(cts.explain_open_error(a.port, e))
        if interactive:
            input("\nPress Enter to close.")
        sys.exit(1)
    rotate()
    sim = SimConsole(lanes=a.lanes)
    if a.practice:
        practice(sim)
    rec = Recorder()
    emu = Emulator(ser, rec, listen_only=a.listen_only, sim=sim, delay_ms=a.delay,
                   pace_baud=0 if a.no_pace else a.baud)
    try:
        rec.line("Lines from the other side: CTS=%s DSR=%s CD=%s (all True on a null-modem cable/pair)"
                 % (ser.cts, ser.dsr, ser.cd))
    except Exception:
        pass
    rec.line("CTS System 6 emulator on %s %d %s-%d%s%s" % (a.port, a.baud, a.parity, a.stopbits,
             " (listen only)" if a.listen_only else "", " with %d practice races" % len(sim.races) if a.practice else ""))
    rec.line("Point Meet Manager / the bridge at the OTHER end of the cable or com0com pair. Ctrl+C to stop.")
    rec.line("Log: %s   Capture: %s" % (LOG, CAPTURE))
    last_save, seen = 0.0, None
    try:
        while True:
            data = ser.read(4096)
            now = time.time()
            emu.feed(data, now)
            if now - last_save > 2 and seen != (sum(emu.counts.values()), len(emu.garbage)):
                # saved as it goes, so stopping it from the launcher (a hard stop) keeps everything
                emu.save(); last_save = now; seen = (sum(emu.counts.values()), len(emu.garbage))
            if not data:
                time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        emu.feed(b"", time.time() + 1)
        emu.save()
        rec.line("Stopped. Commands seen: %s" % (emu.counts or "none"))
        rec.line("Send these two files: %s and %s" % (LOG, CAPTURE))
        ser.close()
        if interactive:
            try:
                input("\nPress Enter to close.")
            except (EOFError, KeyboardInterrupt):
                pass


if __name__ == "__main__":
    main()
