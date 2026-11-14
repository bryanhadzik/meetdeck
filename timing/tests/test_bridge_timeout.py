"""A bridge request that hangs is cut off and its port released."""
import json, os, sys, threading, time, urllib.request, urllib.error
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import bridge, cts


def test_hung_connect_is_released(monkeypatch, tmp_path):
    monkeypatch.setattr(bridge, "LOG_PATH", str(tmp_path / "log.txt"))
    monkeypatch.setattr(bridge, "CONNECT_SECS", 1)
    closed = []

    class Port:
        is_open, port = True, "COM2"
        def close(self): closed.append(1); self.is_open = False
    cts.OPEN_PORTS[:] = [Port()]
    monkeypatch.setattr(bridge, "connect", lambda body: time.sleep(30))
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), bridge.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_port}/connect", data=b'{"port":"COM2"}', method="POST")
    t = time.time()
    try:
        urllib.request.urlopen(req, timeout=10)
        assert False
    except urllib.error.HTTPError as e:
        assert e.code == 504 and "released COM2" in json.loads(e.read())["error"]
    assert time.time() - t < 4 and closed
    srv.shutdown()
