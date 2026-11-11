"""Decode an HHD Device Monitoring Studio / Free Serial Analyzer capture (.dmslog8) of a serial port:
every write and read between the program (Meet Manager) and the device (the CTS console), in order,
with CTS messages joined across reads and described.

    python dmslog.py capture.dmslog8            print the conversation
    python dmslog.py capture.dmslog8 --json     same, as JSON

The .dmslog8 layout is HHD's own; this reads only the records it needs - each write as it was
sent (the request) and each read as it came back (the completion) - and ignores the rest
(status polls, wait masks). Worked out from a real capture on 2026-11-10.
"""
import datetime
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cts  # noqa: E402

STAMP = bytes.fromhex("7571dd01")   # top bytes of a 2020s-era FILETIME (Windows timestamp)
WRITE, READ = 4, 3                 # IRP_MJ_WRITE / IRP_MJ_READ


def _ft(b):
    return datetime.datetime(1601, 1, 1) + datetime.timedelta(microseconds=struct.unpack("<Q", b)[0] / 10)


def records(data):
    """[(time, 'W'|'R', bytes)]: writes as sent, reads as received."""
    out = []
    for m in re.finditer(re.escape(STAMP), data):
        q = m.start() - 4                             # the request's timestamp inside a record
        if q < 24:
            continue
        size, typ = struct.unpack("<II", data[q - 8:q])
        if not (0x18 <= size < 0x2000) or (typ & 0x7FFFFFFF) != 1:
            continue                                  # 1 = a data transfer (read or write)
        done = bool(typ >> 31)
        code = struct.unpack("<I", data[q + 13:q + 17])[0]
        if not ((code == WRITE and not done) or (code == READ and done)):
            continue
        start = q - 24                                # 16-byte record header, then size/type
        n = size - (q + 17 - start)
        if n <= 0:
            continue
        out.append((_ft(data[q - 16:q - 8]), "W" if code == WRITE else "R", data[q + 17:q + 17 + n]))
    out.sort(key=lambda r: r[0])
    return out


def _describe(d, m):
    body = m[2:-2]
    if d == "W":
        try:
            import emulator
            return emulator.describe(body)
        except Exception:
            return repr(body)
    text = body.rstrip(b"\x00")
    if text and all(32 <= c < 127 for c in text):
        return "text %r" % text.decode("latin-1")
    return "%d data bytes" % len(body)


def conversation(recs):
    """Join each direction's chunks into CTS messages (length-prefixed, checksummed)."""
    msgs, buf = [], {"W": b"", "R": b""}
    t0 = recs[0][0] if recs else None
    for t, d, b in recs:
        buf[d] += b
        while len(buf[d]) >= 2:
            n = cts.u16(buf[d][0], buf[d][1])
            if n < 5 or n > 4096:
                msgs.append((t, d, buf[d], "not a CTS message"))
                buf[d] = b""
                break
            if len(buf[d]) < n:
                break
            m, buf[d] = buf[d][:n], buf[d][n:]
            msgs.append((t, d, m, _describe(d, m) if cts.check_ok(m) else "BAD CHECKSUM"))
    for d in buf:
        if buf[d]:
            msgs.append((recs[-1][0], d, buf[d], "incomplete at end of capture"))
    return t0, msgs


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    data = open(sys.argv[1], "rb").read()
    t0, msgs = conversation(records(data))
    if "--json" in sys.argv:
        print(json.dumps([{"ms": round((t - t0).total_seconds() * 1000, 1),
                           "dir": "to console" if d == "W" else "from console",
                           "hex": m.hex(" "), "what": w} for t, d, m, w in msgs], indent=1))
        return
    if not msgs:
        print("No reads or writes in this capture.")
    for t, d, m, w in msgs:
        print("%8.1f ms  %s  %-4d %s\n            %s" % ((t - t0).total_seconds() * 1000,
              "MM  > CTS" if d == "W" else "CTS > MM ", len(m), w, m.hex(" ")))


if __name__ == "__main__":
    main()
