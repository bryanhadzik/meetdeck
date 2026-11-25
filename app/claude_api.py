"""Claude API calls from MeetDeck (reading scanned referee sheets and other handwriting).

The API key is typed into Setup on this computer and kept in MeetDeck's settings file (never in the code, the repo or
the meet backups). Plain HTTPS - no SDK to install."""
import json
import time
import urllib.error
import urllib.request

API = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-5-5"


class ClaudeError(Exception):
    pass


def call(key: str, content, model: str = "", max_tokens: int = 1024, system: str = "", timeout: int = 60, tool: dict | None = None) -> dict:
    """One message to Claude. content: a string, or a list of content blocks (text / image / document). tool: a tool
    definition Claude must answer with (structured output) - its input comes back as "data". Returns
    {"text", "data", "model", "usage", "ms"}."""
    if not key:
        raise ClaudeError("No Claude API key yet - add it under Setup")
    body = {"model": model or MODEL, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}]}
    if system:
        body["system"] = system
    if tool:
        body["tools"] = [tool]
        body["tool_choice"] = {"type": "tool", "name": tool["name"]}
    req = urllib.request.Request(API, json.dumps(body).encode(), {
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = (json.load(e).get("error") or {}).get("message") or ""
        except Exception:
            msg = ""
        if e.code == 401:
            raise ClaudeError("The API key wasn't accepted - check it was pasted whole, or make a new one")
        if e.code == 403:
            raise ClaudeError("This API key isn't allowed to do that" + (f": {msg}" if msg else ""))
        if e.code == 429:
            raise ClaudeError("Too many requests or the spend limit was reached - try again shortly" + (f" ({msg})" if msg else ""))
        if e.code == 400 and "credit" in msg.lower():
            raise ClaudeError("The Claude account is out of credit - add some under Billing")
        raise ClaudeError(f"Claude API error {e.code}" + (f": {msg}" if msg else ""))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ClaudeError(f"Couldn't reach the Claude API - is this computer on the internet? ({getattr(e, 'reason', e)})")
    text = "".join(b.get("text", "") for b in j.get("content") or [] if b.get("type") == "text")
    data = next((b.get("input") for b in j.get("content") or [] if b.get("type") == "tool_use"), None)
    return {"text": text, "data": data, "model": j.get("model"), "usage": j.get("usage") or {}, "ms": int((time.time() - t0) * 1000)}


def test(key: str, model: str = "") -> dict:
    r = call(key, "Reply with just the word OK.", model=model, max_tokens=5, timeout=30)
    return {"ok": True, "model": r["model"], "ms": r["ms"], "reply": r["text"].strip()}
