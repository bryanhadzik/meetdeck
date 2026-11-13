"""Read-only Gmail scan for coach entry files (IMAP + app password).

Setup (done by Bryan, never stored in code): put these in /home/bryan/claude/swimmeet/.env
    GMAIL_USER=bryan@hadzik.org
    GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx     (Google Account > Security > App passwords)
then `docker compose up -d`.

The mailbox is opened with EXAMINE (read-only): nothing is marked read, moved or deleted.
"""
from __future__ import annotations

import email
import email.header
import email.policy
import hashlib
import imaplib
import json
import os
import re
import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

from paths import DATA_ROOT
CACHE = DATA_ROOT / "gmail-cache"
EXTS = (".hy3", ".zip", ".cl2", ".sd3", ".docx", ".txt")
HOST = os.environ.get("GMAIL_IMAP_HOST", "imap.gmail.com")
PORT = int(os.environ.get("GMAIL_IMAP_PORT", "993"))


# Setup > Gmail can store the address + app password in settings; .env still wins when it's set.
creds_fn = lambda: ("", "")   # noqa: E731  (main.py replaces this)


def creds() -> tuple[str, str]:
    if os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD"):
        return os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"]
    u, pw = creds_fn()
    return (u or "").strip(), (pw or "").strip()


def configured() -> bool:
    return all(creds())


def _connect():
    if os.environ.get("GMAIL_IMAP_PLAIN") == "1":      # test server only
        M = imaplib.IMAP4(HOST, PORT)
    else:
        M = imaplib.IMAP4_SSL(HOST, PORT)
    u, pw = creds()
    M.login(u, pw.replace(" ", ""))
    return M


def make_draft(to: list, cc: list, bcc: list, subject: str, body: str, files: list) -> dict:
    """Put a ready-to-send draft (with attachments) in the Gmail Drafts folder. Nothing is sent.
    files: [(filename, bytes, mime)]"""
    from email.message import EmailMessage
    from email.utils import formatdate
    u, _ = creds()
    msg = EmailMessage()
    msg["From"] = u
    if to:
        msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(body)
    for name, data, mime in files:
        mt, st = (mime or "application/octet-stream").split("/", 1)
        msg.add_attachment(data, maintype=mt, subtype=st, filename=name)
    M = _connect()
    try:
        box = None
        typ, rows = M.list()
        for r in rows or []:
            line = r.decode(errors="replace")
            if "\\Drafts" in line:
                box = line.rsplit(' "/" ', 1)[-1].strip()
                break
        box = box or '"[Gmail]/Drafts"'
        if not box.startswith('"'):
            box = '"%s"' % box
        typ, res = M.append(box, "(\\Draft)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
        if typ != "OK":
            raise RuntimeError("Gmail didn't accept the draft: %s" % res)
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return {"ok": True, "box": box.strip('"'), "user": u, "size": len(msg.as_bytes())}


def _select_all(M) -> None:
    for box in ('"[Gmail]/All Mail"', '"[Google Mail]/All Mail"', "INBOX"):
        typ, _ = M.select(box, readonly=True)
        if typ == "OK":
            return
    raise RuntimeError("couldn't open the mailbox")


def _decode(s) -> str:
    return str(email.header.make_header(email.header.decode_header(s or "")))


def scan(days: int = 14, words: str = "", limit: int = 40) -> list[dict]:
    """Recent messages that carry entry-file attachments, newest first. Caches the attachments."""
    CACHE.mkdir(parents=True, exist_ok=True)
    M = _connect()
    try:
        _select_all(M)
        ids = None
        raw = f"has:attachment newer_than:{days}d (filename:hy3 OR filename:zip OR filename:cl2 OR filename:sd3 OR filename:docx OR filename:txt)"
        if words.strip():
            raw += " " + words.strip()
        if any(c in (b"X-GM-EXT-1", "X-GM-EXT-1") for c in M.capabilities):   # real Gmail: use its search
            try:
                typ, data = M.search(None, "X-GM-RAW", f'"{raw}"')
                if typ == "OK":
                    ids = data[0].split()
            except imaplib.IMAP4.error:
                ids = None
        if ids is None:      # non-Gmail server: plain date search
            since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
            typ, data = M.search(None, "SINCE", since)
            ids = data[0].split() if typ == "OK" else []
        out = []
        for num in reversed(ids[-limit * 3:]):
            typ, data = M.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not data or not isinstance(data[0], tuple):
                continue
            msg = email.message_from_bytes(data[0][1], policy=email.policy.default)
            atts = []
            for part in msg.walk():
                fn = part.get_filename()
                if not fn or not fn.lower().endswith(EXTS):
                    continue
                payload = part.get_payload(decode=True) or b""
                mid = hashlib.sha1((msg.get("Message-ID", "") + fn).encode()).hexdigest()[:16]
                (CACHE / f"{mid}.bin").write_bytes(payload)
                atts.append({"id": mid, "filename": _decode(fn), "size": len(payload)})
            if not atts:
                continue
            try:
                when = parsedate_to_datetime(msg.get("Date")).astimezone().strftime("%Y-%m-%d %H:%M")
            except Exception:
                when = msg.get("Date", "")
            item = {"from": _decode(msg.get("From")), "subject": _decode(msg.get("Subject")), "date": when, "attachments": atts}
            for a in atts:
                (CACHE / f"{a['id']}.json").write_text(json.dumps({**item, "filename": a["filename"]}))
            out.append(item)
            if len(out) >= limit:
                break
        return out
    finally:
        try:
            M.logout()
        except Exception:
            pass


def cached(att_id: str) -> tuple[str, bytes, dict]:
    if not re.fullmatch(r"[0-9a-f]{16}", att_id):
        raise FileNotFoundError(att_id)
    meta = json.loads((CACHE / f"{att_id}.json").read_text())
    return meta["filename"], (CACHE / f"{att_id}.bin").read_bytes(), meta
