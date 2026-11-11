"""A pretend CTS System 6 for testing without a console. Speaks the same messages as cts.py expects,
holds stored races (event/heat/lane times) and accepts event-sequence downloads."""
from __future__ import annotations

import random
import time

from cts import frame, check_ok, u16, HEADER_LEN, DATE_AT, time_slots, ACK, NAME_LEN


class SimConsole:
    def __init__(self, lanes=8, times_per_lane=5, buttons=3, seed=7):
        self.lanes, self.tpl, self.buttons = lanes, times_per_lane, buttons
        self.rng = random.Random(seed)
        self.out = b""
        self.races = []            # [{event, heat, lanes:[(place, [ms...])]}]
        self.labels = {}           # (table, index) -> text
        self.events = {}           # (slot, event) -> bytes
        self.active_slot = 1
        self.titles = {s: f"Meet {s}" for s in range(1, 9)}
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
    # how often each real-life problem turns up in made-up races (per lane)
    TROUBLE = {"no_pad": 0.07, "early_button": 0.07, "late_pad": 0.05, "few_buttons": 0.25}

    def add_race(self, event: int, heat: int, results: dict[int, float | None], dq: set[int] = frozenset(),
                 trouble: dict[int, str] | None = None):
        """results: lane -> seconds (None = empty lane). Times look like a real meet:
        buttons land a little after the pad (reaction time), not every timer presses, and now and then
          no_pad        the swimmer missed the pad (soft touch): no pad time, buttons only
          early_button  a timer pressed about 3 s early, so the backup comes out about 1 s fast
          late_pad      the pad registered late (light touch, then a second touch): pad slower than the buttons
        `trouble` forces a problem for a lane (tests); otherwise it's random."""
        lanes = []
        finishers = sorted((t, ln) for ln, t in results.items() if t)
        place_of = {ln: i + 1 for i, (t, ln) in enumerate(finishers)}
        final_i, btn_i, back_i = time_slots(self.tpl, self.buttons)
        for ln in range(1, self.lanes + 1):
            t = results.get(ln)
            if not t:
                lanes.append((0, [0] * self.tpl))
                continue
            ms = int(round(t * 1000))
            what = (trouble or {}).get(ln)
            if what is None:
                r = self.rng.random()
                acc = 0.0
                for k in ("no_pad", "early_button", "late_pad"):
                    acc += self.TROUBLE[k]
                    if r < acc:
                        what = k
                        break
            times = [0] * self.tpl
            for k in range(final_i):                   # even splits leading up to the finish
                times[k] = int(ms * (k + 1) / (final_i + 1))
            # buttons: human reaction, usually 0.05-0.30 s after the touch
            n_btn = len(btn_i)
            pressed = n_btn if self.rng.random() > self.TROUBLE["few_buttons"] else self.rng.randint(1, max(1, n_btn - 1))
            btn = [ms + self.rng.randint(50, 300) for _ in range(pressed)]
            if what == "early_button" and btn:
                btn[0] = ms - self.rng.randint(800, 1200) * len(btn)    # pulls the backup (their average) ~1 s fast
            pad = ms
            if what == "no_pad":
                pad = 0
            elif what == "late_pad":
                pad = ms + self.rng.randint(400, 900)
            for k, i in enumerate(btn_i):
                times[i] = btn[k] if k < len(btn) else 0
            if self.tpl:
                times[final_i] = pad
                times[back_i] = int(round(sum(btn) / len(btn))) if btn else pad
            lanes.append((0xFF if ln in dq else place_of[ln], times))
        self.races.append({"event": event, "heat": heat, "lanes": lanes})

    # ---- protocol ----
    def handle(self, cmd: bytes) -> bytes:
        if cmd == b"W":
            # what the real console answered Meet Manager (capture 2026-11-10): 0a 00 "1.234" 00 fd fe
            return frame(b"1.234\x00")
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
        if cmd[:2] == b"Rs":       # real reply: [slot][21-byte name]
            return frame(bytes((cmd[2],)) + self.titles.get(cmd[2], "").encode("latin-1")[:NAME_LEN - 1].ljust(NAME_LEN, b"\x00"))
        if cmd[:2] == b"Is":
            self.titles[cmd[2]] = cmd[3:].split(b"\x00")[0].decode("latin-1")
            return frame(ACK)
        if cmd[:2] == b"Ir":
            self.active_slot = cmd[2]
            return frame(ACK)
        if cmd[:2] == b"It":
            self.labels[(cmd[2], cmd[3])] = cmd[4:].split(b"\x00")[0].decode("latin-1")
            return frame(ACK)
        if cmd[:2] == b"Rt":
            return frame(b"Rt" + self.labels.get((cmd[2], cmd[3]), "").encode() + b"\x00")
        if cmd[:2] == b"Iu":
            slot, ev = cmd[2], u16(cmd[3], cmd[4])
            if not any(cmd[5:]):
                self.events.pop((slot, ev), None)
            else:
                self.events[(slot, ev)] = cmd[5:]
            return frame(ACK)
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
