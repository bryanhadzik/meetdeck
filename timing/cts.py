"""Colorado Time Systems System 5/6 - computer (meet management) interface, console COM PORT 1.

Written from the protocol facts in claude/cts-system6-computer-interface.md (not from any vendor code).
NOT YET TESTED ON A REAL CONSOLE - see UNVERIFIED notes. Every byte sent and received can be logged
(hex) so the first session at the pool settles the open questions.

Message (both directions):
    [len lo][len hi][command bytes][data...][check lo][check hi]
    len   = total message length, including the two check bytes
    check = 0xFFFF - (sum of every byte before it), as 16 bits, low byte first
For short messages the high check byte is always 0xFF, so it looks like an end marker.
A reply whose length is 6 is an error reply: error code = word(byte2, byte3).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict

# ---- framing -------------------------------------------------------------------


def checksum(body: bytes) -> bytes:
    c = (0xFFFF - sum(body)) & 0xFFFF
    return bytes((c & 0xFF, c >> 8))


def frame(payload: bytes) -> bytes:
    """payload = command bytes + data. Adds length and checksum."""
    n = len(payload) + 4
    body = bytes((n & 0xFF, n >> 8)) + payload
    return body + checksum(body)


def check_ok(msg: bytes) -> bool:
    return len(msg) >= 4 and checksum(msg[:-2]) == msg[-2:]


def u16(lo: int, hi: int) -> int:
    return lo | (hi << 8)


def s16(lo: int, hi: int) -> int:
    v = u16(lo, hi)
    return v - 0x10000 if v & 0x8000 else v


def u32(b: bytes, i: int) -> int:
    return b[i] | (b[i + 1] << 8) | (b[i + 2] << 16) | (b[i + 3] << 24)


def le16(v: int) -> bytes:
    return bytes((v & 0xFF, (v >> 8) & 0xFF))


# ---- commands (payload = command + data; frame() adds length + checksum) -------
CMD_WHO = b"W"                 # version / identity
CMD_MEET_CURRENT = b"T"        # current meet header
CMD_MEET_NEXT = b"M+"
CMD_MEET_PREV = b"M-"
CMD_RACE_INFO = b"SR"          # + race number (LE16) -> event / heat of that stored race
CMD_SWIM_DATA = b"SSBI"        # + mode: C current, L last, N next, E heat event, R 00 race
CMD_SEQ_READ = b"Rs"           # + slot, 0, 0  -> sequence title
CMD_SEQ_SELECT = b"Ir"         # + slot        -> make that event sequence active
CMD_LABEL_READ = b"Rt"         # + label table, index
CMD_LABEL_WRITE = b"It"        # + label table, index, text, 0
CMD_EVENT_READ = b"Ru"         # + slot, event LE16
CMD_EVENT_WRITE = b"Iu"        # + slot, event LE16, distance LE16, label indexes...

# Label tables on the console (used by event download)
LABEL_SEX, LABEL_AGE, LABEL_EVENT_TYPE, LABEL_BRACKET = 0, 1, 2, 3

HEADER_LEN = 49                # race header bytes before the lane data
DATE_AT = 8                    # sec, min, hour, weekday, month, day, year(2-digit)


# ---- parsed data ---------------------------------------------------------------
@dataclass
class Lane:
    lane: int
    place: int                 # 0 = no finish / blank, -1 = DQ, else place
    times_ms: list[int]        # every time the console keeps for the lane, in order
    final_ms: int = 0          # official (touch pad) finish
    splits_ms: list[int] = field(default_factory=list)   # cumulative split times before the finish
    buttons_ms: list[int] = field(default_factory=list)
    backup_ms: int = 0         # console's backup / calculated time (last slot)

    def secs(self, ms: int) -> float:
        return round(ms / 1000.0, 2) if ms else 0.0


@dataclass
class Race:
    event: int
    heat: int
    race_number: int
    lanes_in_pool: int
    times_per_lane: int
    buttons: int
    individual_buttons: bool
    relay_judging: bool
    when: str
    lanes: list[Lane]
    raw: str = ""              # hex of the reply, kept for checking against the console

    def as_dict(self):
        d = asdict(self)
        for ln in d["lanes"]:
            ln["final"] = round(ln["final_ms"] / 1000, 2) if ln["final_ms"] else 0
            ln["backup"] = round(ln["backup_ms"] / 1000, 2) if ln["backup_ms"] else 0
            ln["buttons"] = [round(t / 1000, 2) for t in ln["buttons_ms"]]
            ln["splits"] = [round(t / 1000, 2) for t in ln["splits_ms"]]
        return d


def time_slots(times_per_lane: int, buttons: int) -> tuple[int, list[int], int]:
    """Positions in a lane's time list: [splits..., final, buttons..., backup].
    Follows the System 5 layout (UNVERIFIED on System 6). With one button the button time is the backup."""
    n = times_per_lane
    if n <= 0:
        return 0, [], 0
    backup = n - 1
    if buttons <= 0:
        return max(n - 1, 0), [], backup
    if buttons == 1:
        return max(n - 2, 0), [n - 1], backup
    final = n - buttons - 2
    return max(final, 0), [i for i in range(final + 1, final + 1 + buttons) if 0 <= i < n], backup


def parse_race(msg: bytes) -> Race:
    if len(msg) <= HEADER_LEN + 2:
        raise ValueError(f"race reply too short ({len(msg)} bytes)")
    lanes_n, tpl = msg[16], msg[17]
    want = HEADER_LEN + lanes_n * (1 + 4 * tpl) + 2
    if want != len(msg):
        raise ValueError(f"race reply is {len(msg)} bytes, expected {want} for {lanes_n} lanes x {tpl} times")
    buttons = msg[48]
    final_i, btn_i, back_i = time_slots(tpl, buttons)
    d = msg[DATE_AT:DATE_AT + 7]
    yr = d[6] + (2000 if d[6] < 70 else 1900)
    when = f"{yr:04d}-{d[4]:02d}-{d[5]:02d} {d[2]:02d}:{d[1]:02d}:{d[0]:02d}" if 1 <= d[4] <= 12 else ""
    lanes, p = [], HEADER_LEN
    for i in range(lanes_n):
        place = msg[p]
        place = -1 if place == 0xFF else place
        times = [u32(msg, p + 1 + 4 * k) for k in range(tpl)]
        times = [0 if t in (0xFFFFFFFF,) else t for t in times]
        lanes.append(Lane(lane=i + 1, place=place, times_ms=times, final_ms=times[final_i] if tpl else 0,
                          splits_ms=times[:final_i],
                          buttons_ms=[times[k] for k in btn_i], backup_ms=times[back_i] if tpl else 0))
        p += 1 + 4 * tpl
    return Race(event=msg[2], heat=msg[3], race_number=u16(msg[6], msg[7]), lanes_in_pool=lanes_n, times_per_lane=tpl,
                buttons=buttons, individual_buttons=bool(msg[46]), relay_judging=bool(msg[47]), when=when,
                lanes=lanes, raw=msg.hex(" "))


# ---- transport -------------------------------------------------------------------
class CTSError(Exception):
    pass


class Console:
    """Talks to the console over any object with read(n), write(b), reset_input_buffer()
    (a pyserial Serial, or sim.SimConsole for testing)."""

    def __init__(self, port, log=None, settle=0.15):
        self.port = port
        self.log = log            # callable(direction, bytes) or None
        self.settle = settle

    # -- low level --
    def request(self, payload: bytes, timeout: float = 2.0) -> bytes:
        msg = frame(payload)
        try:
            self.port.reset_input_buffer()
        except Exception:
            pass
        if self.log:
            self.log(">", msg)
        self.port.write(msg)
        time.sleep(self.settle)
        return self.read_reply(timeout)

    def send(self, payload: bytes):
        """Write without waiting for a reply (event/label writes may not answer)."""
        msg = frame(payload)
        if self.log:
            self.log(">", msg)
        self.port.write(msg)
        time.sleep(self.settle)

    def read_reply(self, timeout: float = 2.0) -> bytes:
        end = time.time() + timeout
        buf = b""
        while time.time() < end:
            chunk = self.port.read(512)
            if chunk:
                buf += chunk
                if len(buf) >= 2:
                    n = u16(buf[0], buf[1])
                    if 4 <= n <= 4096 and len(buf) >= n:
                        msg, extra = buf[:n], buf[n:]
                        if self.log:
                            self.log("<", msg)
                            if extra:
                                self.log("<extra", extra)
                        if not check_ok(msg):
                            raise CTSError(f"bad checksum in reply: {msg.hex(' ')}")
                        if n == 6:
                            raise CTSError(f"console error code {u16(msg[2], msg[3])}")
                        return msg
            else:
                time.sleep(0.02)
        if buf and self.log:
            self.log("<partial", buf)
        raise CTSError("no reply from the console" + (f" (got {len(buf)} bytes: {buf[:40].hex(' ')})" if buf else ""))

    # -- identity / meets --
    def who_are_you(self) -> str:
        r = self.request(CMD_WHO)
        return r[2:-2].decode("latin-1", errors="replace").strip("\x00 ").strip()

    def meet(self, direction: int = 0) -> dict:
        """Header of the current (0), next (+1) or previous (-1) meet stored on the console."""
        r = self.request({0: CMD_MEET_CURRENT, 1: CMD_MEET_NEXT, -1: CMD_MEET_PREV}[direction])
        d = r[DATE_AT:DATE_AT + 7] if len(r) >= DATE_AT + 7 else b""
        out = {"raw": r.hex(" ")}
        if d and 1 <= d[4] <= 12:
            yr = d[6] + (2000 if d[6] < 70 else 1900)
            out["when"] = f"{yr:04d}-{d[4]:02d}-{d[5]:02d} {d[2]:02d}:{d[1]:02d}"
        return out

    # -- races --
    def race_info(self, race_number: int) -> tuple[int, int] | None:
        r = self.request(CMD_RACE_INFO + le16(race_number))
        return (r[2], r[3]) if len(r) > 6 else None

    def race_list(self, limit: int = 500) -> list[dict]:
        """Stored races in this meet: [{race, event, heat}]. The console repeats the last race past the end."""
        out, last = [], None
        for n in range(1, limit + 1):
            try:
                eh = self.race_info(n)
            except CTSError:
                break
            if not eh or eh == last:
                break
            out.append({"race": n, "event": eh[0], "heat": eh[1]})
            last = eh
        return out

    def race(self, race_number: int) -> Race:
        # UNVERIFIED: race number is sent as one byte after a 0; races above 255 may need the high byte there.
        return parse_race(self.request(CMD_SWIM_DATA + b"R" + bytes((race_number >> 8 & 0xFF, race_number & 0xFF)), timeout=3))

    def race_by_heat(self, event: int, heat: int) -> Race:
        return parse_race(self.request(CMD_SWIM_DATA + b"E" + bytes((heat & 0xFF, event & 0xFF)), timeout=3))

    def race_current(self) -> Race:
        return parse_race(self.request(CMD_SWIM_DATA + b"C", timeout=3))

    def race_last(self) -> Race:
        return parse_race(self.request(CMD_SWIM_DATA + b"L", timeout=3))

    # -- event sequences (sending the meet to the console) --
    def sequence_title(self, slot: int) -> str:
        r = self.request(CMD_SEQ_READ + bytes((slot, 0, 0)))
        return r[3:-2].decode("latin-1", errors="replace").strip("\x00 ")

    def select_sequence(self, slot: int):
        return self.request(CMD_SEQ_SELECT + bytes((slot,)))

    def read_label(self, table: int, index: int) -> str:
        r = self.request(CMD_LABEL_READ + bytes((table, index)))
        return r[4:-2].decode("latin-1", errors="replace").strip("\x00 ")

    def write_label(self, table: int, index: int, text: str):
        self.send(CMD_LABEL_WRITE + bytes((table, index)) + text.encode("latin-1", errors="replace")[:20] + b"\x00")

    def write_event(self, slot: int, event_no: int, distance: int, sex: int | None = None, stroke: int | None = None,
                    age: int | None = None, session: int | None = None):
        labels = bytes(v for v in (sex, stroke, age, session) if v is not None)
        self.send(CMD_EVENT_WRITE + bytes((slot,)) + le16(event_no) + le16(distance) + labels)

    def clear_event(self, slot: int, event_no: int):
        self.send(CMD_EVENT_WRITE + bytes((slot,)) + le16(event_no) + bytes(8))

    def read_event(self, slot: int, event_no: int) -> bytes:
        return self.request(CMD_EVENT_READ + bytes((slot,)) + le16(event_no))

    def download_meet(self, slot: int, events: list[dict], title: str | None = None, progress=None) -> dict:
        """events: [{no, distance, gender ('F'/'M'/'X'), stroke ('Free','Back','Breast','Fly','IM','Free Relay',
        'Medley Relay')}]. Writes sex and stroke label tables, then each event, then makes the slot active.
        UNVERIFIED: label table indexes/meaning and whether the title is label table 'bracket'."""
        sexes = sorted({e["gender"] for e in events})
        strokes = []
        for e in events:
            if e["stroke"] not in strokes:
                strokes.append(e["stroke"])
        sex_text = {"F": "Girls", "M": "Boys", "X": "Mixed", "W": "Women"}
        for i, s in enumerate(sexes):
            self.write_label(LABEL_SEX, i, sex_text.get(s, s))
        for i, s in enumerate(strokes):
            self.write_label(LABEL_EVENT_TYPE, i, s)
        done = []
        for k, e in enumerate(sorted(events, key=lambda e: e["no"])):
            self.write_event(slot, int(e["no"]), int(e["distance"]), sexes.index(e["gender"]), strokes.index(e["stroke"]))
            done.append(e["no"])
            if progress:
                progress(k + 1, len(events))
        self.select_sequence(slot)
        return {"slot": slot, "events": len(done), "sex_labels": sexes, "stroke_labels": strokes}


# ---- serial helpers ----------------------------------------------------------------
SETTINGS_TO_TRY = [  # UNVERIFIED which one the System 6 uses; probe() finds out
    {"baudrate": 9600, "parity": "N", "stopbits": 1},
    {"baudrate": 9600, "parity": "O", "stopbits": 1},
    {"baudrate": 9600, "parity": "E", "stopbits": 1},
    {"baudrate": 19200, "parity": "N", "stopbits": 1},
    {"baudrate": 2400, "parity": "N", "stopbits": 1},
]


def open_serial(port: str, baudrate=9600, parity="N", stopbits=1, timeout=0.1):
    import serial  # pyserial
    return serial.Serial(port, baudrate=baudrate, bytesize=8, parity=parity, stopbits=stopbits, timeout=timeout)


def list_ports() -> list[dict]:
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        return []
    return [{"port": p.device, "desc": p.description} for p in lp.comports() if p.description and p.description != "n/a"]


def probe(port: str, log=None) -> dict | None:
    """Try each setting with the identity request; returns the first that answers."""
    for s in SETTINGS_TO_TRY:
        try:
            ser = open_serial(port, **s)
        except Exception as e:
            return {"error": f"can't open {port}: {e}"}
        try:
            c = Console(ser, log=log)
            ident = c.who_are_you()
            return {**s, "identity": ident, "serial": ser}
        except Exception:
            ser.close()
    return None
