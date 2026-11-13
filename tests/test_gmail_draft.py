"""Gmail draft: the message lands in the \\Drafts box with recipients, Bcc and attachments; nothing is sent."""
import email
import email.policy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import gmail  # noqa: E402


class FakeIMAP:
    def __init__(self):
        self.appended = []

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\Drafts \\HasNoChildren) "/" "[Gmail]/Drafts"']

    def append(self, box, flags, when, data):
        self.appended.append((box, flags, data))
        return "OK", [b"done"]

    def logout(self):
        pass


def test_make_draft(monkeypatch):
    fake = FakeIMAP()
    monkeypatch.setattr(gmail, "_connect", lambda: fake)
    monkeypatch.setattr(gmail, "creds_fn", lambda: ("me@example.org", "abcdabcdabcdabcd"))
    monkeypatch.delenv("GMAIL_USER", raising=False)
    r = gmail.make_draft([], ["ref@example.org"], ["c1@example.org", "c2@example.org"], "Initial results - Test",
                         "Results attached.", [("Test results.pdf", b"%PDF-1.4 x", "application/pdf"),
                                               ("Test.zip", b"PK\x03\x04", "application/zip")])
    assert r["ok"] and r["box"] == "[Gmail]/Drafts"
    box, flags, data = fake.appended[0]
    assert box == '"[Gmail]/Drafts"' and flags == "(\\Draft)"
    msg = email.message_from_bytes(data, policy=email.policy.default)
    assert msg["From"] == "me@example.org" and msg["Cc"] == "ref@example.org"
    assert msg["Bcc"] == "c1@example.org, c2@example.org" and msg["To"] is None
    names = [p.get_filename() for p in msg.iter_attachments()]
    assert names == ["Test results.pdf", "Test.zip"]
    assert msg.get_body(("plain",)).get_content().strip() == "Results attached."


def test_env_wins(monkeypatch):
    monkeypatch.setattr(gmail, "creds_fn", lambda: ("set@example.org", "x" * 16))
    monkeypatch.setenv("GMAIL_USER", "env@example.org")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "y" * 16)
    assert gmail.creds()[0] == "env@example.org" and gmail.configured()
    monkeypatch.delenv("GMAIL_USER")
    assert gmail.creds()[0] == "set@example.org"
