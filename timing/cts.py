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
CMD_SEQ_READ = b"Rs"           # + slot -> [slot][21-byte meet name]       (verified, capture 2026-11-10)
CMD_SEQ_NAME = b"Is"           # + slot + 21-byte meet name -> ACK          (verified)
CMD_SEQ_SELECT = b"Ir"         # + slot -> ACK; ends a download, makes that meet active (verified)
CMD_LABEL_READ = b"Rt"         # + label table, index
CMD_LABEL_WRITE = b"It"        # + label table, index, 16-byte text -> ACK  (verified)
CMD_EVENT_READ = b"Ru"         # + slot, event LE16
CMD_EVENT_WRITE = b"Iu"        # + slot, event LE16, distance LE16, 7 label tokens -> ACK (verified)
ACK = b"\x06\x00"              # the console's answer to every write: 06 00 06 00 f3 ff

# Label tables on the console (used by event download)
LABEL_SEX, LABEL_AGE, LABEL_EVENT_TYPE, LABEL_BRACKET = 0, 1, 2, 3
LABEL_LEN, NAME_LEN, TOKENS = 16, 21, 7
# An event's description is up to 7 tokens; token = table base + label index (0 = none).
# Sizes and bases as Meet Manager writes them (HHD capture of a real System 6, 2026-11-10).
TABLE_SIZE = {LABEL_SEX: 9, LABEL_EVENT_TYPE: 10, LABEL_AGE: 20, LABEL_BRACKET: 10}
TOKEN_BASE = {LABEL_SEX: 0x01, LABEL_EVENT_TYPE: 0x0A, LABEL_AGE: 0x14, LABEL_BRACKET: 0x28}
# Meet Manager's standard label tables, sent in this order on every download
MM_LABELS = [
    (LABEL_SEX, ["Mens", "Womens", "Boys", "Girls", "Mixed", "Masters"]),
    (LABEL_EVENT_TYPE, ["Freestyle", "Backstroke", "Breaststroke", "Butterfly", "IM", "Medley", "Relay",
                        "1 Mtr Diving", "3 Mtr Diving", "Platform Diving"]),
    (LABEL_AGE, ["6 & Under", "8 & Under", "10 & Under", "9-10", "11-12", "13-14", "15-16", "15-18", "17-18", "Open"]),
    (LABEL_BRACKET, ["Final", "Prelim", "Semi-Final", "Consolation", "Bonus", "Consols/Finals", "Championship"]),
]
MM_CLEAR_EVENTS = 32           # Meet Manager clears events 1-32 before writing the meet


def token(table: int, label: str) -> int:
    names = dict(MM_LABELS)[table]
    return TOKEN_BASE[table] + names.index(label)


SEX_WORD = {"F": "Girls", "M": "Boys", "X": "Mixed", "W": "Womens"}
STROKE_WORDS = {"Free": ["Freestyle"], "Back": ["Backstroke"], "Breast": ["Breaststroke"], "Fly": ["Butterfly"],
                "IM": ["IM"], "Free Relay": ["Freestyle", "Relay"], "Medley Relay": ["Medley", "Relay"]}
NO_AGE = TOKEN_BASE[LABEL_AGE] + TABLE_SIZE[LABEL_AGE] - 1   # 0x27: a blank age label; MM uses it for open events


def event_tokens(gender: str, stroke: str, round_: str = "Final") -> bytes:
    """The 7 label tokens Meet Manager sends for an event, e.g. girls 200 medley relay -> 04 0f 10 27 28 00 00."""
    t = [token(LABEL_SEX, SEX_WORD.get(gender, "Mixed"))]
    t += [token(LABEL_EVENT_TYPE, w) for w in STROKE_WORDS.get(stroke, ["Freestyle"])]
    t += [NO_AGE, token(LABEL_BRACKET, round_)]
    return bytes(t + [0] * (TOKENS - len(t)))

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
    Verified on a real System 6 (5 times, 3 buttons): [pad, button 1, button 2, button 3, backup]."""
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
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code            # console error code when the console refused the request


class Console:
    """Talks to the console over any object with read(n), write(b), reset_input_buffer()
    (a pyserial Serial, or sim.SimConsole for testing)."""

    def __init__(self, port, log=None, settle=0.15):
        self.port = port
        self.log = log            # callable(direction, bytes) or None
        self.settle = settle
        # traffic counters for the debug panel
        self.stats = {"requests": 0, "replies": 0, "timeouts": 0, "bad_checksum": 0, "console_errors": 0, "partial": 0,
                      "bytes_out": 0, "bytes_in": 0, "last_tx": None, "last_rx": None, "last_rtt_ms": None, "last_error": None}

    def _err(self, text: str):
        self.stats["last_error"] = f"{time.strftime('%H:%M:%S')} {text}"

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
        self.stats["requests"] += 1
        self.stats["bytes_out"] += len(msg)
        self.stats["last_tx"] = time.strftime("%H:%M:%S")
        t0 = time.time()
        time.sleep(self.settle)
        r = self.read_reply(timeout)
        self.stats["last_rtt_ms"] = round((time.time() - t0) * 1000)
        return r

    def send(self, payload: bytes):
        """Write without waiting for a reply (event/label writes may not answer)."""
        msg = frame(payload)
        if self.log:
            self.log(">", msg)
        self.port.write(msg)
        self.stats["bytes_out"] += len(msg)
        self.stats["last_tx"] = time.strftime("%H:%M:%S")
        time.sleep(self.settle)

    def read_reply(self, timeout: float = 2.0) -> bytes:
        end = time.time() + timeout
        buf = b""
        while time.time() < end:
            chunk = self.port.read(512)
            if chunk:
                buf += chunk
                self.stats["bytes_in"] += len(chunk)
                self.stats["last_rx"] = time.strftime("%H:%M:%S")
                if len(buf) >= 2:
                    n = u16(buf[0], buf[1])
                    if 4 <= n <= 4096 and len(buf) >= n:
                        msg, extra = buf[:n], buf[n:]
                        if self.log:
                            self.log("<", msg)
                            if extra:
                                self.log("<extra", extra)
                        if not check_ok(msg):
                            self.stats["bad_checksum"] += 1
                            self._err("bad checksum in reply")
                            raise CTSError(f"bad checksum in reply: {msg.hex(' ')} (wrong baud/parity, or line noise)")
                        if n == 6 and msg[2:4] == ACK:
                            self.stats["replies"] += 1
                            return msg
                        if n == 6:
                            self.stats["console_errors"] += 1
                            self._err(f"console error code {u16(msg[2], msg[3])}")
                            raise CTSError(f"console error code {u16(msg[2], msg[3])}", code=u16(msg[2], msg[3]))
                        self.stats["replies"] += 1
                        return msg
            else:
                time.sleep(0.02)
        if buf and self.log:
            self.log("<partial", buf)
        if buf:
            self.stats["partial"] += 1
            self._err(f"incomplete reply ({len(buf)} bytes)")
            raise CTSError(f"incomplete reply from the console: got {len(buf)} bytes ({buf[:40].hex(' ')}) - "
                           "garbage bytes usually mean the wrong baud rate or parity")
        self.stats["timeouts"] += 1
        self._err(f"no reply within {timeout:g}s")
        raise CTSError(f"no reply from the console within {timeout:g}s - nothing came back on the serial line")

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
        """By stored race number. UNVERIFIED byte order (the real console refused hi,lo with code 50 once),
        so try both and keep only a reply whose header carries that race number."""
        n, last = race_number, None
        for arg in (bytes((n >> 8 & 0xFF, n & 0xFF)), bytes((n & 0xFF, n >> 8 & 0xFF))):
            try:
                r = parse_race(self.request(CMD_SWIM_DATA + b"R" + arg, timeout=3))
            except CTSError as e:
                if e.code is None:
                    raise
                last = e
                continue
            if r.race_number == n:
                return r
        raise CTSError(f"the console wouldn't give race {n} by number" + (f" (console error code {last.code})" if last else ""),
                       code=last.code if last else None)

    heat_order = None              # which byte order of SSBI E the console understood (learned on first success)

    def race_by_heat(self, event: int, heat: int) -> Race:
        """Times for one event/heat. The byte order of SSBI E isn't verified yet (captures only asked for 1/1),
        so try both and accept a reply only when its own header says the right event and heat."""
        orders = ["he", "eh"] if self.heat_order != "eh" else ["eh", "he"]
        refused = None
        for o in orders:
            arg = bytes((heat & 0xFF, event & 0xFF)) if o == "he" else bytes((event & 0xFF, heat & 0xFF))
            try:
                r = parse_race(self.request(CMD_SWIM_DATA + b"E" + arg, timeout=3))
            except CTSError as e:
                if e.code is None:
                    raise
                refused = e
                continue
            if (r.event, r.heat) == (event, heat):
                self.heat_order = o
                return r
            if event == heat:
                break
        code = f" (console error code {refused.code})" if refused else ""
        raise CTSError(f"the console has no stored race for event {event} heat {heat}{code}. Check the event and heat "
                       f"match the console (the console's race list shows what it has), or enter the console's race number.",
                       code=refused.code if refused else None)

    def race_current(self) -> Race:
        return parse_race(self.request(CMD_SWIM_DATA + b"C", timeout=3))

    def race_last(self) -> Race:
        return parse_race(self.request(CMD_SWIM_DATA + b"L", timeout=3))

    # -- event sequences (sending the meet to the console) --
    def sequence_title(self, slot: int) -> str:
        """Name of the meet stored in slot 1-8 (Meet Manager reads all 8 before a download)."""
        r = self.request(CMD_SEQ_READ + bytes((slot,)))
        return r[3:-2].split(b"\x00")[0].decode("latin-1", errors="replace").strip()

    def sequence_titles(self) -> dict:
        return {s: self.sequence_title(s) for s in range(1, 9)}

    def write_sequence_title(self, slot: int, name: str):
        self.request(CMD_SEQ_NAME + bytes((slot,)) + fixed(name, NAME_LEN))

    def select_sequence(self, slot: int):
        return self.request(CMD_SEQ_SELECT + bytes((slot,)))

    def read_label(self, table: int, index: int) -> str:
        r = self.request(CMD_LABEL_READ + bytes((table, index)))
        return r[4:-2].decode("latin-1", errors="replace").strip("\x00 ")

    def write_label(self, table: int, index: int, text: str):
        self.request(CMD_LABEL_WRITE + bytes((table, index)) + fixed(text, LABEL_LEN))

    def write_event(self, slot: int, event_no: int, distance: int, tokens: bytes):
        self.request(CMD_EVENT_WRITE + bytes((slot,)) + le16(event_no) + le16(distance) + (bytes(tokens) + bytes(TOKENS))[:TOKENS])

    def clear_event(self, slot: int, event_no: int):
        self.request(CMD_EVENT_WRITE + bytes((slot,)) + le16(event_no) + bytes(2 + TOKENS))

    def read_event(self, slot: int, event_no: int) -> bytes:
        return self.request(CMD_EVENT_READ + bytes((slot,)) + le16(event_no))

    def download_meet(self, slot: int, events: list[dict], title: str | None = None, progress=None) -> dict:
        """Send a meet to console slot 1-8 exactly as Meet Manager does (HHD capture, 2026-11-10):
        the four label tables, the meet name, clear events 1-32, each event, then Ir to finish.
        events: [{no, distance, gender ('F'/'M'/'X'), stroke ('Free','Back','Breast','Fly','IM','Free Relay',
        'Medley Relay'), round ('Final' default)}]. Every write is acknowledged by the console."""
        if not 1 <= slot <= 8:
            raise ValueError("console meet slot must be 1-8")
        evs = sorted(events, key=lambda e: int(e["no"]))
        total = sum(TABLE_SIZE.values()) + 1 + max(MM_CLEAR_EVENTS, len(evs)) + len(evs) + 1
        done = [0]

        def tick():
            done[0] += 1
            if progress:
                progress(done[0], total)

        for table, names in MM_LABELS:
            for i in range(TABLE_SIZE[table]):
                self.write_label(table, i, names[i] if i < len(names) else "")
                tick()
        self.write_sequence_title(slot, title or "MeetDeck meet")
        tick()
        for n in range(1, max(MM_CLEAR_EVENTS, max((int(e["no"]) for e in evs), default=0)) + 1):
            self.clear_event(slot, n)
            tick()
        for e in evs:
            self.write_event(slot, int(e["no"]), int(e["distance"]),
                             event_tokens(e.get("gender", "X"), e.get("stroke", "Free"), e.get("round", "Final")))
            tick()
        self.select_sequence(slot)
        tick()
        return {"slot": slot, "events": len(evs), "title": title or "MeetDeck meet"}


def fixed(text: str, n: int) -> bytes:
    """Text in a fixed n-byte field: up to n-1 characters, NUL padded."""
    return (text.encode("latin-1", errors="replace")[:n - 1]).ljust(n, b"\x00")


# ---- serial helpers ----------------------------------------------------------------
SETTINGS_TO_TRY = [  # the pool's System 6 answers at 9600 8-O-1 (probe, 2026-11-10)
    {"baudrate": 9600, "parity": "O", "stopbits": 1},
    {"baudrate": 9600, "parity": "N", "stopbits": 1},
    {"baudrate": 9600, "parity": "E", "stopbits": 1},
    {"baudrate": 19200, "parity": "N", "stopbits": 1},
    {"baudrate": 2400, "parity": "N", "stopbits": 1},
]


def open_serial(port: str, baudrate=9600, parity="N", stopbits=1, timeout=0.1):
    import serial  # pyserial
    return serial.Serial(port, baudrate=baudrate, bytesize=8, parity=parity, stopbits=stopbits, timeout=timeout)


def list_ports(detail: bool = False) -> list[dict]:
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        return []
    out = []
    for p in lp.comports():
        if not detail and not (p.description and p.description != "n/a"):
            continue
        d = {"port": p.device, "desc": p.description}
        if detail:
            d.update(hwid=p.hwid, vid=f"{p.vid:04X}" if p.vid is not None else None, pid=f"{p.pid:04X}" if p.pid is not None else None,
                     serial_number=p.serial_number, manufacturer=p.manufacturer, product=p.product,
                     location=p.location, interface=p.interface, chip=usb_chip(p.vid, p.pid))
        out.append(d)
    return out


USB_CHIPS = {(0x0403, None): "FTDI", (0x067B, None): "Prolific PL2303", (0x10C4, None): "Silicon Labs CP210x",
             (0x1A86, None): "WCH CH340/CH341", (0x0557, None): "ATEN", (0x2341, None): "Arduino"}


def usb_chip(vid, pid) -> str | None:
    """Name the USB-serial chip from its vendor id (driver problems are usually chip-specific)."""
    return USB_CHIPS.get((vid, None)) if vid is not None else None


def explain_open_error(port: str, e: Exception) -> str:
    t = f"{type(e).__name__}: {e}"
    low = t.lower()
    if "permission" in low or "access is denied" in low or "busy" in low:
        return f"can't open {port}: it's in use by another program (Meet Manager's timing interface, CTS software, or a second bridge). Close that, then try again. [{t}]"
    if "filenotfound" in low or ("could not open port" in low and "cannot find" in low) or "no such file" in low:
        return f"can't open {port}: the computer says the port isn't there - unplug and replug the USB-serial adapter and pick the port again. [{t}]"
    if "semaphore" in low or "device attached to the system is not functioning" in low:
        return f"can't open {port}: the adapter's driver isn't working (try another USB port or reinstall the driver). [{t}]"
    return f"can't open {port}: {t}"


def port_details(ser) -> dict:
    """Live settings and modem lines of an open pyserial port."""
    d = {}
    for k in ("port", "baudrate", "bytesize", "parity", "stopbits", "timeout", "write_timeout", "xonxoff", "rtscts", "dsrdtr", "is_open"):
        try:
            d[k] = getattr(ser, k)
        except Exception as e:
            d[k] = f"? {e}"
    for k in ("cts", "dsr", "ri", "cd", "rts", "dtr"):     # CTS/DSR high usually means a live device on the other end
        try:
            d[k] = bool(getattr(ser, k))
        except Exception:
            d[k] = None
    try:
        d["in_waiting"] = ser.in_waiting
    except Exception:
        d["in_waiting"] = None
    return d


def probe(port: str, log=None, attempts: list | None = None) -> dict | None:
    """Try each setting with the identity request; returns the first that answers.
    `attempts` (if given) gets one line per setting tried, for the debug panel."""
    attempts = attempts if attempts is not None else []
    for s in SETTINGS_TO_TRY:
        label = f"{s['baudrate']} {s['parity']}{s['stopbits']}"
        try:
            ser = open_serial(port, **s)
        except Exception as e:
            attempts.append({"settings": label, "result": explain_open_error(port, e)})
            return {"error": explain_open_error(port, e), "attempts": attempts}
        c = Console(ser, log=log)
        t0 = time.time()
        try:
            ident = c.who_are_you()
            attempts.append({"settings": label, "result": f"answered: '{ident}'", "ms": round((time.time() - t0) * 1000)})
            return {**s, "identity": ident, "serial": ser, "attempts": attempts}
        except Exception as e:
            attempts.append({"settings": label, "result": str(e), "bytes_in": c.stats["bytes_in"], "ms": round((time.time() - t0) * 1000)})
            ser.close()
    return {"error": None, "attempts": attempts}
