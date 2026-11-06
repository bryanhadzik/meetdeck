"""A pretend CTS System 6 for testing without a console. Speaks the same messages as cts.py expects,
holds stored races (event/heat/lane times) and accepts event-sequence downloads."""
from __future__ import annotations

import random
import time

from cts import frame, check_ok, u16, HEADER_LEN, DATE_AT, time_slots


class SimConsole:
    def __init__(self, lanes=8, times_per_lane=3, buttons=1, seed=7):
        self.lanes, self.tpl, self.buttons = lanes, times_per_lane, buttons
        self.rng = random.Random(seed)
        self.out = b""
        self.races = []            # [{event, heat, lanes:[(place, [ms...])]}]
        self.labels = {}           # (table, index) -> text
        self.events = {}           # (slot, event) -> bytes
        self.active_slot = 9
        self.titles = {s: f"SEQUENCE {s}" for s in range(2, 10)}
        self.writes = []           # every message received (for tests)

    # ---- serial-like interface ----
    def write(self, b: bytes):
        self.writes.append(bytes(b))
        if not check_ok(b):
            self.out += frame(b"\x01\x00")           # error reply (len 6)
            return len(b)
        cmd = b[2:-2]
        self.out += self.handle(cmd)
        return len(b)

    def read(self, n: int) -> bytes:
        r, self.out = self.out[:n], self.out[n:]
        return r

    def reset_input_buffer(self):
        self.out = b""

    def close(self):
        pass

    # ---- test helpers ----
    def add_race(self, event: int, heat: int, results: dict[int, float | None], dq: set[int] = frozenset()):
        """results: lane -> seconds (None = empty lane)."""
        lanes = []
        finishers = sorted((t, ln) for ln, t in results.items() if t)
        place_of = {ln: i + 1 for i, (t, ln) in enumerate(finishers)}
        for ln in range(1, self.lanes + 1):
            t = results.get(ln)
            if not t:
                lanes.append((0, [0] * self.tpl))
                continue
            ms = int(round(t * 1000))
            final_i, btn_i, back_i = time_slots(self.tpl, self.buttons)
            times = [0] * self.tpl
            for k in range(final_i):                   # even splits leading up to the finish
                times[k] = int(ms * (k + 1) / (final_i + 1))
            # buttons usually land within a few hundredths of the pad; now and then one is well off
            btn = [ms + (self.rng.choice([-1, 1]) * self.rng.randint(80, 250) if self.rng.random() < 0.15 else self.rng.randint(-25, 25)) for _ in btn_i]
            for k, i in enumerate(btn_i):
                times[i] = btn[k]
            times[final_i] = ms
            times[back_i] = int(round(sum(btn) / len(btn))) if btn else ms
            lanes.append((0xFF if ln in dq else place_of[ln], times))
        self.races.append({"event": event, "heat": heat, "lanes": lanes})

    # ---- protocol ----
    def handle(self, cmd: bytes) -> bytes:
        if cmd == b"W":
            return frame(b"System 6 Swimming 1.233 (SIM)\x00")
        if cmd in (b"T", b"M+", b"M-"):
            return frame(b"T" + self._date_block(pad_to=HEADER_LEN - 3))
        if cmd[:2] == b"SR":
            n = u16(cmd[2], cmd[3])
            r = self.races[min(n, len(self.races)) - 1] if self.races and n >= 1 else None
            return frame(bytes((r["event"], r["heat"])) + bytes(4)) if r else frame(b"\x02\x00")
        if cmd[:4] == b"SSBI":
            mode = cmd[4:5]
            r = None
            if mode == b"E":
                heat, ev = cmd[5], cmd[6]
                r = next((x for x in self.races if x["event"] == ev and x["heat"] == heat), None)
            elif mode == b"R":
                n = (cmd[5] << 8) | cmd[6]
                r = self.races[n - 1] if 1 <= n <= len(self.races) else None
            elif mode in (b"C", b"L"):
                r = self.races[-1] if self.races else None
            if not r:
                return frame(b"\x03\x00")            # error: no such race
            return self._race_reply(r, self.races.index(r) + 1)
        if cmd[:2] == b"Rs":
            return frame(b"R" + self.titles.get(cmd[2], "").encode() + b"\x00")
        if cmd[:2] == b"Ir":
            self.active_slot = cmd[2]
            return frame(b"Ir\x00")
        if cmd[:2] == b"It":
            self.labels[(cmd[2], cmd[3])] = cmd[4:].split(b"\x00")[0].decode("latin-1")
            return b""
        if cmd[:2] == b"Rt":
            return frame(b"Rt" + self.labels.get((cmd[2], cmd[3]), "").encode() + b"\x00")
        if cmd[:2] == b"Iu":
            slot, ev = cmd[2], u16(cmd[3], cmd[4])
            if cmd[5:] == bytes(8):
                self.events.pop((slot, ev), None)
            else:
                self.events[(slot, ev)] = cmd[5:]
            return b""
        if cmd[:2] == b"Ru":
            v = self.events.get((cmd[2], u16(cmd[3], cmd[4])), b"")
            return frame(b"Ru" + v)
        return frame(b"\x09\x00")                    # unknown command

    def _date_block(self, pad_to: int) -> bytes:
        t = time.localtime()
        block = bytearray(pad_to)
        d = bytes((t.tm_sec or 1, t.tm_min or 1, t.tm_hour or 1, t.tm_wday, t.tm_mon, t.tm_mday, t.tm_year % 100))
        block[DATE_AT - 3:DATE_AT - 3 + 7] = d
        return bytes(block)

    def _race_reply(self, r: dict, race_no: int) -> bytes:
        # header is HEADER_LEN bytes including the 2 length bytes; payload starts at byte 2
        hdr = bytearray(HEADER_LEN)
        hdr[2], hdr[3] = r["event"], r["heat"]
        hdr[6], hdr[7] = race_no & 0xFF, race_no >> 8
        t = time.localtime()
        hdr[DATE_AT:DATE_AT + 7] = bytes((t.tm_sec or 1, t.tm_min or 1, t.tm_hour or 1, t.tm_wday, t.tm_mon, t.tm_mday, t.tm_year % 100))
        hdr[16], hdr[17] = self.lanes, self.tpl
        hdr[40], hdr[41] = t.tm_year & 0xFF, t.tm_year >> 8
        hdr[44], hdr[45] = r["event"] & 0xFF, r["event"] >> 8
        hdr[46], hdr[47], hdr[48] = 1, 0, self.buttons
        body = bytes(hdr[2:])
        for place, times in r["lanes"]:
            body += bytes((place,)) + b"".join(int(ms).to_bytes(4, "little") for ms in times)
        return frame(body)
