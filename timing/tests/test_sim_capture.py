"""Sending to the Simulator saves an emulator-style capture that compare() can use."""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bridge, emulator


def test_simulator_download_saves_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(emulator, "CAPTURE", str(tmp_path / "emulator-capture.json"))
    monkeypatch.setattr(emulator, "LOG", str(tmp_path / "emulator-log.txt"))
    monkeypatch.setattr(emulator, "timing_dir", lambda: str(tmp_path))
    monkeypatch.setattr(bridge, "LOG_PATH", str(tmp_path / "cts-log.txt"))
    bridge.connect({"sim": True})
    evs = [{"no": n, "distance": 400 if n > 20 else 100, "gender": "F" if n % 2 else "M",
            "stroke": "Free Relay" if n > 20 else "Free"} for n in range(1, 23)]
    r = bridge.download({"slot": 1, "events": evs, "title": "BL DP RH @ GHS"})
    cap = json.load(open(r["capture"]))
    assert cap["event_sequences"]["1"]["21"]["description"] == "Girls Freestyle Relay Final"
    assert cap["event_sequences"]["1"]["22"]["distance"] == 400
    assert cap["messages"][-1][2].startswith("FINISH DOWNLOAD")
    # a second send rotates the first, and the two compare as the same
    bridge.download({"slot": 1, "events": evs, "title": "BL DP RH @ GHS"})
    caps = emulator.captures()
    assert len(caps) == 2
    assert "SAME" in "\n".join(emulator.compare(caps[1], caps[0]))
    bridge.disconnect()
