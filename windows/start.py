"""MeetDeck for Windows - start here (MeetDeck.bat and the shortcuts run this).

Stays the same across updates: if an update was downloaded (app.new), it swaps it in for the
current app folder - keeping the old one as app.old - and then runs app\\launcher.py.
"""
import os
import runpy
import shutil
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("MEETDECK_PORT", "8001"))


def port_busy() -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def swap():
    new, app, old = ROOT / "app.new", ROOT / "app", ROOT / "app.old"
    if not new.exists():
        return
    if "--restart" in sys.argv:                 # let the old MeetDeck finish exiting
        for _ in range(40):
            if not port_busy():
                break
            time.sleep(0.25)
        time.sleep(0.5)
    for attempt in range(20):
        try:
            shutil.rmtree(old, ignore_errors=True)
            if app.exists():
                app.rename(old)
            new.rename(app)
            return
        except OSError:
            if old.exists() and not app.exists():        # half-way: put the old one back
                old.rename(app)
            time.sleep(0.5)


swap()
sys.argv = [str(ROOT / "app" / "launcher.py")] + sys.argv[1:]
runpy.run_path(str(ROOT / "app" / "launcher.py"), run_name="__main__")
