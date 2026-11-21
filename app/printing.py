"""Print a PDF straight to a Windows printer - no browser, no print dialog.

Uses SumatraPDF (bundled in app/tools, free/GPL) in its silent print mode:
    SumatraPDF.exe -print-to "<printer>" -print-settings "2x,noscale" -silent file.pdf
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

NO_WINDOW = 0x08000000          # CREATE_NO_WINDOW: no console flashing up on the pool PC


def available() -> bool:
    return sys.platform == "win32" and sumatra() is not None


def sumatra() -> Path | None:
    here = Path(__file__).resolve().parent
    for p in (here / "tools" / "SumatraPDF.exe", here.parent / "tools" / "SumatraPDF.exe"):
        if p.exists():
            return p
    return None


def printers() -> list[dict]:
    """[{name, default}] from Windows (empty anywhere else)."""
    if sys.platform != "win32":
        return []
    ps = ("Get-CimInstance Win32_Printer | Select-Object Name, Default, WorkOffline, PrinterStatus "
          "| ConvertTo-Json -Compress")
    try:
        out = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                             capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW).stdout.strip()
        rows = json.loads(out) if out else []
    except Exception as e:
        print("printers:", e)
        return []
    if isinstance(rows, dict):
        rows = [rows]
    skip = ("Microsoft Print to PDF", "Microsoft XPS Document Writer", "OneNote", "Fax")
    out = [{"name": r.get("Name") or "", "default": bool(r.get("Default")), "offline": bool(r.get("WorkOffline"))}
           for r in rows if r.get("Name")]
    # real printers first, the default one at the top
    return sorted(out, key=lambda p: (any(p["name"].startswith(s) for s in skip), not p["default"], p["name"].lower()))


def print_pdf(pdf: bytes, printer: str = "", copies: int = 1, name: str = "MeetDeck") -> dict:
    """Send the PDF to `printer` (blank: Windows' default printer). Returns {ok, printer, copies, secs}."""
    exe = sumatra()
    if sys.platform != "win32" or not exe:
        raise RuntimeError("Direct printing works on the Windows PC running MeetDeck (SumatraPDF isn't here)")
    copies = max(1, min(50, int(copies or 1)))
    tmp = Path(tempfile.gettempdir()) / "MeetDeck-print"
    tmp.mkdir(exist_ok=True)
    for old in tmp.glob("*.pdf"):               # tidy up earlier jobs (already spooled)
        try:
            if time.time() - old.stat().st_mtime > 3600:
                old.unlink()
        except OSError:
            pass
    safe = "".join(c for c in name if c.isalnum() or c in " -_.@").strip() or "MeetDeck"
    f = tmp / f"{safe} {int(time.time() * 1000) % 100000}.pdf"
    f.write_bytes(pdf)
    cmd = [str(exe)] + (["-print-to", printer] if printer else ["-print-to-default"]) + \
          ["-print-settings", f"{copies}x,noscale", "-silent", str(f)]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"The printer didn't take the job (SumatraPDF exit {r.returncode}){': ' + r.stderr.strip() if r.stderr.strip() else ''}")
    return {"ok": True, "printer": printer or "default printer", "copies": copies, "secs": round(time.time() - t0, 1)}
