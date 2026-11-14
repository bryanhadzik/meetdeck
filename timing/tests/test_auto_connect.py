"""The bridge remembers the console's port, connects to it by itself, notices when it goes away,
and Reconnect opens it again."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bridge, cts
from sim import SimConsole


class Port(SimConsole):
    is_open, port = True, "COM1"
    def close(self): self.is_open = False


def rig(monkeypatch, tmp_path, ports=("COM1",)):
    monkeypatch.setattr(bridge, "PREF_PATH", str(tmp_path / "bridge.json"))
    monkeypatch.setattr(bridge, "LOG_PATH", str(tmp_path / "cts-log.txt"))
    monkeypatch.setattr(cts, "list_ports", lambda detail=False: [{"port": p, "desc": ""} for p in ports])
    opened = []
    def fake_open(port, **s):
        p = Port(); opened.append((port, s)); return p
    monkeypatch.setattr(cts, "open_serial", fake_open)
    bridge.disconnect()
    return opened


def test_remembers_and_auto_connects(monkeypatch, tmp_path):
    opened = rig(monkeypatch, tmp_path)
    assert not bridge.auto_connect_once()                     # nothing remembered yet
    bridge.connect({"port": "COM1"})                          # someone connects once
    assert bridge.pref()["port"] == "COM1" and bridge.pref()["auto"]
    bridge.disconnect()                                       # e.g. MeetDeck restarted
    assert bridge.auto_connect_once() and bridge.STATE["port"] == "COM1"
    assert opened[-1][1] == bridge.pref()["settings"]          # same settings, no probing


def test_hand_disconnect_turns_auto_off(monkeypatch, tmp_path):
    rig(monkeypatch, tmp_path)
    bridge.connect({"port": "COM1"})
    bridge.disconnect(); bridge.save_pref(auto=False)         # what the Disconnect button does
    assert not bridge.auto_connect_once()


def test_only_the_remembered_port(monkeypatch, tmp_path):
    rig(monkeypatch, tmp_path, ports=("COM3",))
    bridge.save_pref(port="COM1", settings={"baudrate": 9600, "parity": "O", "stopbits": 1}, auto=True)
    assert not bridge.auto_connect_once() and bridge.STATE["console"] is None


def test_heartbeat_drops_a_silent_console_and_reconnect_restores(monkeypatch, tmp_path):
    rig(monkeypatch, tmp_path)
    bridge.connect({"port": "COM1"})
    def dead(self, timeout=2.0): raise cts.CTSError("no reply")
    monkeypatch.setattr(cts.Console, "who_are_you", dead)
    bridge.heartbeat_once(); assert bridge.STATE["console"]   # one miss is forgiven
    bridge.heartbeat_once(); assert bridge.STATE["console"] is None
    monkeypatch.undo()
    rig(monkeypatch, tmp_path)
    bridge.save_pref(port="COM1", settings={"baudrate": 9600, "parity": "O", "stopbits": 1}, auto=True)
    st = bridge.reconnect({})
    assert st["connected"] and st["port"] == "COM1"
    bridge.disconnect()
