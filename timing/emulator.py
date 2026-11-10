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
LOG = os.path.join(HERE, "emulator-log.txt")
CAPTURE = os.path.join(HERE, "emulator-capture.json")
TABLES = {0: "sex", 1: "age group", 2: "stroke", 3: "bracket"}


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
        return "READ SEQUENCE TITLE slot %d" % cmd[2]
    if two == b"Ir" and len(cmd) >= 3:
        return "MAKE SEQUENCE %d ACTIVE" % cmd[2]
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
        idx = list(rest[2:])
        names = ["sex", "stroke", "age", "session"]
        extra = ", ".join("%s #%d" % (names[i] if i < len(names) else "b%d" % i, v) for i, v in enumerate(idx))
        return "WRITE EVENT %d in slot %d: %d, %s" % (ev, slot, dist, extra)
    return "UNKNOWN %r" % printable(cmd[:12])


class Emulator:
    def __init__(self, ser, rec: Recorder, listen_only=False, sim=None):
        self.ser, self.rec, self.listen_only = ser, rec, listen_only
        self.sim = sim or SimConsole()
        self.buf = b""
        self.last_rx = 0.0
        self.counts: dict[str, int] = {}
        self.unknown: list[str] = []
        self.garbage: list[str] = []
        self.started = time.strftime("%Y-%m-%d %H:%M:%S")

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
        if what.startswith("UNKNOWN"):
            self.unknown.append(msg.hex(" "))
        if self.listen_only:
            return
        self.sim.write(msg)
        reply = self.sim.read(1 << 16)
        if reply:
            meaning = "error reply" if len(reply) == 6 else "reply"
            self.ser.write(reply)
            self.rec.msg(">>", reply, meaning)
        else:
            self.rec.line("%s    (no reply - the real console doesn't answer this one, as far as we know)" % ts())
        if cmd[:2] in (b"Iu", b"It", b"Ir"):
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
                "sex": s.labels.get((0, d[2])), "stroke": s.labels.get((2, d[3])),
                "age": s.labels.get((1, d[4])), "session_or_more": list(d[5:len(data)]),
            }
        labels = {}
        for (t, i), text in sorted(s.labels.items()):
            labels.setdefault(TABLES.get(t, "table %d" % t), {})[str(i)] = text
        out = {"started": self.started, "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
               "active_sequence": s.active_slot, "event_sequences": events, "labels": labels,
               "commands_seen": self.counts, "unknown_commands": self.unknown[-50:],
               "not_console_messages": self.garbage[-50:]}
        with open(CAPTURE, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)


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
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
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
    try:
        ser = cts.open_serial(a.port, baudrate=a.baud, parity=a.parity, stopbits=a.stopbits, timeout=0.02)
    except Exception as e:
        print(cts.explain_open_error(a.port, e))
        if interactive:
            input("\nPress Enter to close.")
        sys.exit(1)
    sim = SimConsole(lanes=a.lanes)
    if a.practice:
        practice(sim)
    rec = Recorder()
    emu = Emulator(ser, rec, listen_only=a.listen_only, sim=sim)
    rec.line("CTS System 6 emulator on %s %d %s-%d%s%s" % (a.port, a.baud, a.parity, a.stopbits,
             " (listen only)" if a.listen_only else "", " with %d practice races" % len(sim.races) if a.practice else ""))
    rec.line("Point Meet Manager / the bridge at the OTHER end of the cable or com0com pair. Ctrl+C to stop.")
    rec.line("Log: %s   Capture: %s" % (LOG, CAPTURE))
    try:
        while True:
            data = ser.read(4096)
            emu.feed(data, time.time())
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
