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


def configured() -> bool:
    return bool(os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD"))


def _connect():
    if os.environ.get("GMAIL_IMAP_PLAIN") == "1":      # test server only
        M = imaplib.IMAP4(HOST, PORT)
    else:
        M = imaplib.IMAP4_SSL(HOST, PORT)
    M.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"].replace(" ", ""))
    return M


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
