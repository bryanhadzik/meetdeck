"""MeetDeck for Windows: runs the MeetDeck server on this PC and opens it in the browser.

- Data lives in Documents\\MeetDeck (first run copies the starter data that ships with the app).
- The timing-console bridge runs inside the app, so the console just plugs into this laptop.
- A tray icon (bottom-right) has Open MeetDeck, Open data folder and Quit.
"""
import os
import shutil
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # ...\MeetDeck
APP = ROOT / "app"
DATA = Path(os.environ.get("MEETDECK_DATA") or (Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents" / "MeetDeck"))
PORT = int(os.environ.get("MEETDECK_PORT", "8001"))
BRIDGE_PORT = 8766
URL = f"http://127.0.0.1:{PORT}/"

DATA.mkdir(parents=True, exist_ok=True)
LOG = open(DATA / "meetdeck.log", "a", encoding="utf-8", buffering=1)
if sys.stdout is None or "pythonw" in sys.executable.lower():
    sys.stdout = sys.stderr = LOG


def log(msg):
    LOG.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")


def first_run():
    """Copy the starter data (host schools' master meets, rules library, settings) on first start."""
    seed = ROOT / "seed"
    if not seed.exists():
        return
    for item in seed.iterdir():
        dst = DATA / item.name
        if dst.exists():
            continue
        if item.is_dir():
            shutil.copytree(item, dst)
        else:
            shutil.copy2(item, dst)
        log(f"seeded {item.name}")


def load_env():
    """Optional settings file Documents\\MeetDeck\\meetdeck.env (KEY=value lines), e.g. GMAIL_USER / GMAIL_APP_PASSWORD."""
    f = DATA / "meetdeck.env"
    if not f.exists():
        f.write_text("# MeetDeck settings - KEY=value, one per line. Restart MeetDeck after changing.\n"
                     "# Gmail inbox for coaches' entry files (use a Google app password):\n"
                     "# GMAIL_USER=you@gmail.com\n# GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx\n", encoding="utf-8")
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def fonts():
    """Meet Manager prints in Cambria, which every Windows PC already has."""
    mine = DATA / "fonts"
    if (mine / "cambria.ttc").exists() and (mine / "cambriab.ttf").exists():
        return str(mine)
    win = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    return str(win) if (win / "cambria.ttc").exists() else str(mine)


def running() -> bool:
    try:
        with urllib.request.urlopen(URL + "api/settings", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def port_free(p) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", p)) != 0


def shortcut():
    """Desktop + Start menu shortcuts on first run."""
    try:
        pyw = ROOT / "python" / "pythonw.exe"
        start = ROOT / "start.py"
        icon = APP / "static" / "meetdeck.ico"
        for folder in (Path(os.environ["USERPROFILE"]) / "Desktop",
                       Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"):
            if not folder.exists():
                continue
            lp = folder / "MeetDeck Launcher.lnk"      # the launcher window: MeetDeck Launcher.exe (has the icon)
            lexe = ROOT / "MeetDeck Launcher.exe"
            if lexe.exists() and (not lp.exists() or str(lexe) not in _lnk_target(lp)):
                ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lp}');$s.TargetPath='{lexe}';"
                      f"$s.WorkingDirectory='{ROOT}';$s.IconLocation='{lexe},0';$s.Description='Start, stop and update MeetDeck';$s.Save()")
                import subprocess
                subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=0x08000000, timeout=30)
            lnk = folder / "MeetDeck.lnk"
            if lnk.exists() and str(ROOT) in _lnk_args(lnk):
                continue
            ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');$s.TargetPath='{pyw}';"
                  f"$s.Arguments='-X utf8 \"{start}\"';$s.WorkingDirectory='{ROOT}';"
                  + (f"$s.IconLocation='{icon}';" if icon.exists() else "") + "$s.Description='MeetDeck';$s.Save()")
            import subprocess
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], creationflags=0x08000000, timeout=30)
    except Exception:
        log("shortcut: " + traceback.format_exc())


def _lnk_target(lnk) -> str:
    try:
        import subprocess
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}').TargetPath"],
                           capture_output=True, text=True, creationflags=0x08000000, timeout=20)
        return r.stdout
    except Exception:
        return ""


def launcher_exe():
    """Copy app/tools/MeetDeck Launcher.exe (updates bring it) to the MeetDeck folder when it's new or changed."""
    try:
        for name in ("MeetDeck Launcher.exe", "MeetDeck.exe"):
            src, dst = APP / "tools" / name, ROOT / name
            if src.exists() and (not dst.exists() or dst.read_bytes() != src.read_bytes()):
                shutil.copy2(src, dst)
    except Exception:
        log("launcher exe: " + traceback.format_exc())


def _lnk_args(lnk) -> str:
    try:
        import subprocess
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            f"(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}').Arguments"],
                           capture_output=True, text=True, creationflags=0x08000000, timeout=20)
        return r.stdout
    except Exception:
        return ""


LAUNCHER_CMD = ('@echo off\r\nrem Start/stop MeetDeck and the CTS console tools.\r\n'
                'start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
                '-File "%~dp0app\\tools\\MeetDeck-Launcher.ps1"\r\n')


def refresh_start():
    """An update may bring a newer start.py (and the launcher); keep the MeetDeck folder's copies current."""
    try:
        src, dst = APP / "start.py", ROOT / "start.py"
        if src.exists() and (not dst.exists() or src.read_bytes() != dst.read_bytes()):
            shutil.copy2(src, dst)
        cmd = ROOT / "MeetDeck Launcher.cmd"
        if (APP / "tools" / "MeetDeck-Launcher.ps1").exists() and (not cmd.exists() or cmd.read_text(errors="ignore") != LAUNCHER_CMD):
            cmd.write_text(LAUNCHER_CMD, newline="")
    except Exception:
        log("start.py: " + traceback.format_exc())


def start_bridge():
    """The CTS timing-console bridge (same as timing\\bridge.py, inside the app)."""
    if not port_free(BRIDGE_PORT):
        return
    try:
        sys.path.insert(0, str(APP / "timing"))
        import bridge
        from http.server import ThreadingHTTPServer
        srv = ThreadingHTTPServer(("127.0.0.1", BRIDGE_PORT), bridge.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        log("timing bridge on 8766")
    except Exception:
        log("bridge: " + traceback.format_exc())


def serve():
    import uvicorn
    sys.path.insert(0, str(APP))
    os.chdir(ROOT)
    import main  # noqa: F401  (MeetDeck server)
    # every network card (0.0.0.0), so phones / other laptops on the same network can open it at
    # http://<this PC's IP>:8001 - MEETDECK_HOST=127.0.0.1 in meetdeck.env keeps it to this PC only
    uvicorn.run(main.app, host=os.environ.get("MEETDECK_HOST", "0.0.0.0"), port=PORT, log_level="warning", log_config=None)


def lan_urls() -> list:
    """http://<ip>:8001/ for this PC's network addresses (not loopback / link-local)."""
    ips = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:   # the address used to reach the network
            s.connect(("192.0.2.1", 9))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except OSError:
        pass
    ips = sorted(ip for ip in ips if not ip.startswith(("127.", "169.254.")))
    return [f"http://{ip}:{PORT}/" for ip in ips]


def tray(stop):
    try:
        import pystray
        from PIL import Image, ImageDraw
        ico = APP / "static" / "meetdeck.png"
        if ico.exists():
            img = Image.open(ico)
        else:
            img = Image.new("RGB", (64, 64), (31, 111, 235))
            ImageDraw.Draw(img).text((14, 20), "MD", fill="white")
        others = [pystray.MenuItem(f"Other devices: {u}", (lambda u: lambda: webbrowser.open(u))(u))
                  for u in (lan_urls() if os.environ.get("MEETDECK_HOST", "0.0.0.0") != "127.0.0.1" else [])]
        menu = pystray.Menu(pystray.MenuItem("Open MeetDeck", lambda: webbrowser.open(URL), default=True),
                            *others,
                            pystray.MenuItem("Open data folder", lambda: os.startfile(DATA)),
                            pystray.MenuItem("Quit MeetDeck", lambda icon: (icon.stop(), stop())))
        pystray.Icon("MeetDeck", img, "MeetDeck", menu).run()
    except Exception:
        log("tray: " + traceback.format_exc())
        while True:
            time.sleep(3600)


def main():
    if running():                      # already open: just show it
        webbrowser.open(URL)
        return
    log("starting MeetDeck")
    first_run()
    launcher_exe()
    load_env()
    os.environ["MEETDECK_DATA"] = str(DATA)
    os.environ.setdefault("FONT_DIR", fonts())
    if (APP / "cacert.pem").exists():   # HTTPS (Gmail, Google Drive, updates) also trusts the standard CA list
        os.environ.setdefault("SSL_CERT_FILE", str(APP / "cacert.pem"))
    os.environ.pop("TZ", None)     # Windows' C runtime misreads Olson names as UTC; the PC's own clock is right
    refresh_start()
    shortcut()
    start_bridge()
    threading.Thread(target=lambda: _guard(serve), daemon=True).start()
    for _ in range(120):
        if running():
            break
        time.sleep(0.25)
    if "--no-browser" not in sys.argv and "--restart" not in sys.argv:   # after an update the page reloads itself
        webbrowser.open(URL)
    tray(lambda: os._exit(0))
    os._exit(0)


def _guard(fn):
    try:
        fn()
    except Exception:
        log(traceback.format_exc())


if __name__ == "__main__":
    main()
