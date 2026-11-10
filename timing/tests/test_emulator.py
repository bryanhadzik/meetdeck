"""The console emulator over a real serial device (a Linux pty pair standing in for com0com).

Run: python -m pytest timing/tests/test_emulator.py   (needs pyserial; Linux/macOS for the pty)
"""
import json, os, select, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
serial = pytest.importorskip("serial")
import cts, emulator
from cts import Console, frame


class FdPort:
    """The 'Meet Manager' end of the cable: a pty master fd with a serial-like face."""
    def __init__(self, fd):
        self.fd = fd

    def write(self, b):
        return os.write(self.fd, b)

    def read(self, n):
        r, _, _ = select.select([self.fd], [], [], 0.05)
        return os.read(self.fd, n) if r else b""

    def reset_input_buffer(self):
        while self.read(4096):
            pass


@pytest.fixture
def rig(tmp_path, monkeypatch):
    if not hasattr(os, "openpty"):
        pytest.skip("needs a pty")
    monkeypatch.setattr(emulator, "CAPTURE", str(tmp_path / "capture.json"))
    master, slave = os.openpty()
    import tty
    tty.setraw(master); tty.setraw(slave)
    ser = serial.Serial(os.ttyname(slave), 9600, timeout=0.02)
    rec = emulator.Recorder(str(tmp_path / "log.txt"))
    emu = emulator.Emulator(ser, rec)
    emulator.practice(emu.sim)
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            emu.feed(ser.read(4096), time.time())
    t = threading.Thread(target=loop, daemon=True); t.start()
    yield emu, FdPort(master), tmp_path
    stop.set(); t.join(1); ser.close(); os.close(master); os.close(slave)


def test_bridge_talks_to_emulator(rig):
    emu, port, tmp = rig
    con = Console(port)
    assert "System 6" in con.who_are_you()
    races = con.race_list()
    assert len(races) == 8 and races[0]["event"] == 1
    r = con.race_by_heat(3, 2)
    assert r.event == 3 and r.heat == 2 and any(ln.final_ms for ln in r.lanes)
    # download events the way MeetDeck does; the emulator keeps them and writes the capture
    con.write_label(2, 1, "Free")
    con.write_event(9, 5, 200, sex=1, stroke=1, age=0, session=1)
    con.select_sequence(9)
    time.sleep(0.4)
    cap = json.load(open(tmp / "capture.json"))
    assert cap["event_sequences"]["9"]["5"]["distance"] == 200
    assert cap["labels"]["stroke"]["1"] == "Free"
    assert cap["active_sequence"] == 9
    log = open(tmp / "log.txt").read()
    assert "WHO ARE YOU" in log and "WRITE EVENT 5 in slot 9" in log


def test_records_bytes_that_are_not_console_messages(rig):
    emu, port, tmp = rig
    port.write(b"HELLO CTS\r\n")
    time.sleep(0.5)
    emu.feed(b"", time.time() + 1)
    assert emu.garbage and "48 45 4c 4c 4f" in emu.garbage[-1]
    assert "NOT A CONSOLE MESSAGE" in open(tmp / "log.txt").read()


def test_bad_checksum_is_flagged(rig):
    emu, port, tmp = rig
    bad = bytearray(frame(b"W")); bad[-2] ^= 0x55
    port.write(bytes(bad))
    time.sleep(0.4)
    assert "BAD CHECKSUM" in open(tmp / "log.txt").read()


def test_unknown_command_is_logged_and_kept(rig):
    emu, port, tmp = rig
    port.write(frame(b"ZQ\x01\x02"))
    time.sleep(0.4)
    assert emu.unknown and emu.counts.get("UNKNOWN ZQ") == 1
