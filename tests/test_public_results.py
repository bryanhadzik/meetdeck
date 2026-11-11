"""Phone results page: results.json shape, no history on publish, throttle."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import public_results as pr


def meet():
    return {"meet": {"name": "Test Meet", "location": "Pool", "start": "2026-11-05"},
            "teams": {1: {"name": "Home High", "abbr": "HOME"}, 2: {"name": "Away High", "abbr": "AWAY"}},
            "athletes": {10: {"first": "Pat", "last": "Swimmer", "yr": "11", "team": 1}, 11: {"first": "Lee", "last": "Racer", "yr": "10", "team": 2}},
            "events": [{"ptr": 1, "no": 1, "label": "Girls 50 Free", "stroke": "A"}, {"ptr": 2, "no": 2, "label": "Boys 50 Free", "stroke": "A"}],
            "entries": [{"event": 1, "kind": "I", "ath": 10, "scr": False, "place": 1, "time": 27.5, "seed": 28.0, "stat": "", "points": 6, "dq": "", "legs": [], "exh": False},
                        {"event": 1, "kind": "I", "ath": 11, "scr": False, "place": 2, "time": 28.1, "seed": 0, "stat": "", "points": 4, "dq": "", "legs": [], "exh": False},
                        {"event": 2, "kind": "I", "ath": 11, "scr": False, "place": 0, "time": 0, "seed": 30.0, "stat": "", "points": 0, "dq": "", "legs": [], "exh": False}]}


def test_build():
    d = pr.build(meet(), {"teams": {"1": {"F": 6, "M": 0, "total": 6}, "2": {"F": 4, "M": 0, "total": 4}}, "events": [1]})
    assert d["meet"] == {"name": "Test Meet", "location": "Pool", "date": "Nov 5, 2026"}
    assert d["scores"][0] == {"name": "Home High", "F": 6, "M": 0, "total": 6}
    e1, e2 = d["events"]
    assert [r["name"] for r in e1["rows"]] == ["Swimmer, Pat", "Racer, Lee"] and e1["rows"][0]["team_name"] == "Home High"
    assert e1["sig"] and e2["rows"] == [] and d["latest"] == 1 and d["scored"] == 1


def test_files_and_url():
    f = pr.files({"meet": {"name": "x"}, "updated": "now"}, "swim.example.org")
    assert set(f) == {"index.html", "results.json", ".nojekyll", "robots.txt", "CNAME"} and f["CNAME"] == "swim.example.org\n"
    assert "Disallow: /" in f["robots.txt"] and 'name="robots" content="noindex' in f["index.html"]
    assert pr.site_url("bryanhadzik/swim-results") == "https://bryanhadzik.github.io/swim-results/" and pr.DEFAULT_DOMAIN == "swim.hadzik.org"
    assert pr.site_url("a/b", "swim.example.org") == "https://swim.example.org/"


def test_publish_has_no_history(monkeypatch):
    calls = []
    def api(token, method, path, body=None):
        calls.append((method, path, body))
        return {"sha": "abc1234567"} if method == "POST" else {}
    monkeypatch.setattr(pr, "_api", api)
    pr.publish({"meet": {"name": "x"}, "updated": "t"}, "o/r", "tok")
    commit = next(b for m, p, b in calls if p.endswith("/git/commits"))
    assert commit["parents"] == []
    ref = next(b for m, p, b in calls if m == "PATCH")
    assert ref["force"] is True
    assert ("POST", "/repos/o/r/dispatches", {"event_type": "publish"}) in calls      # Actions deploy


def test_throttle(monkeypatch):
    monkeypatch.setattr(pr, "MIN_GAP", 0.3)
    p = pr.Publisher()
    runs = []
    assert p.request("m", lambda: runs.append(1) or {"url": "u"})["ok"]
    q = p.request("m", lambda: runs.append(2) or {"url": "u"})
    assert q["queued"] and runs == [1]
    p.request("m", lambda: runs.append(3) or {"url": "u"})      # folds into the queued one
    time.sleep(0.6)
    assert runs == [1, 2]
