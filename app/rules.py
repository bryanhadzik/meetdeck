"""Rules library: PDFs (NFHS / UHSAA documents) kept on file and searchable by page."""
import json
import re
from pathlib import Path

from paths import DATA_ROOT
RULES = DATA_ROOT / "rules"
SEED = Path(__file__).parent / "rules_seed"     # official / free documents that ship with the app


def ensure_seed() -> None:
    """Copy shipped documents this copy doesn't have yet. Each is offered once, so one you
    removed stays removed (rules/.seeded lists what was already offered)."""
    import shutil
    if not SEED.is_dir():
        return
    RULES.mkdir(parents=True, exist_ok=True)
    mark = RULES / ".seeded"
    done = set(mark.read_text().splitlines()) if mark.exists() else set()
    new = False
    for f in sorted(SEED.glob("*.pdf")):
        if f.name in done:
            continue
        if not (RULES / f.name).exists():
            shutil.copy2(f, RULES / f.name)
        done.add(f.name)
        new = True
    if new:
        mark.write_text("\n".join(sorted(done)))


HTML_EXT = (".htm", ".html")
HEAD_RE = re.compile(r"<h[1-4]\b", re.I)
PAGE_RE = re.compile(r'<[a-z0-9]+\b[^>]*data-page-start="true"', re.I)   # NFHS Digital marks each printed page


def _split_re(raw: str):
    """Pages saved from the NFHS Digital reader mark where each printed page starts - split there.
    Other web pages are split at their headings."""
    return PAGE_RE if PAGE_RE.search(raw) else HEAD_RE


def is_html(f) -> bool:
    return str(f).lower().endswith(HTML_EXT)


def docs() -> list[Path]:
    """Every document in the library: PDFs, and web pages saved as .htm / .html."""
    return sorted(f for f in RULES.glob("*") if f.suffix.lower() in (".pdf",) + HTML_EXT)


def _html_text(fragment: str) -> str:
    import html as _h
    t = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", fragment)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6]|section|article)>", "\n", t)
    t = _h.unescape(re.sub(r"<[^>]+>", " ", t))
    return "\n".join(ln.strip() for ln in re.sub(r"[ \t\r\f\v]+", " ", t).splitlines() if ln.strip())


def _html_raw(f: Path) -> str:
    b = f.read_bytes()
    for enc in ("utf-8", "cp1252"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("utf-8", "replace")


def html_parts(f: Path) -> list[str]:
    """A saved web page split at its headings (h1-h4). Each part counts as one 'page' of the document;
    the served copy gets an anchor mdk-N at the start of part N, so search results open right there."""
    raw = _html_raw(f)
    body = re.search(r"(?is)<body\b[^>]*>(.*)</body>", raw)
    raw = body.group(1) if body else raw
    cuts = [m.start() for m in _split_re(raw).finditer(raw)]
    bounds = [0] + cuts + [len(raw)]
    parts = [raw[a:b] for a, b in zip(bounds, bounds[1:])]
    if parts and not _html_text(parts[0]).strip() and len(parts) > 1:
        parts[1] = parts[0] + parts[1]
        parts = parts[1:]
    return parts


def html_served(f: Path) -> str:
    """The saved page as served: scripts and event handlers removed, an anchor at every part."""
    raw = _html_raw(f)
    raw = re.sub(r"(?is)<script\b.*?</script>", "", raw)
    raw = re.sub(r"(?i)\son[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", raw)
    body = re.search(r"(?is)<body\b[^>]*>", raw)
    start = body.end() if body else 0
    n = [0]
    rx = _split_re(raw)
    m0 = rx.search(raw, start)
    first_text = bool(_html_text(raw[start:(m0.start() if m0 else len(raw))]).strip())
    def anchor(m):
        n[0] += 1
        k = n[0] + (1 if first_text else 0)
        return f'<a id="mdk-{k}"></a>' + m.group(0)
    head, rest = raw[:start], raw[start:]
    rest = '<a id="mdk-1"></a>' + rx.sub(anchor, rest)
    return head + rest


def html_book_offset(f: Path):
    """For a book saved page by page (NFHS Digital), the difference between page count and printed page number,
    found from the book's own cross-reference ("For comments on the rules changes, see page 99")."""
    if not is_html(f):
        return None
    pg = pages(f)
    if not PAGE_RE.search(_html_raw(f)[:2_000_000]):
        return None
    for t in pg[:6]:
        m = re.search(r"(?i)comments on the [\d-]+ rules changes, see page (\d+)", t)
        if m:
            k = next((i for i, x in enumerate(pg) if x.lstrip().upper().startswith("COMMENTS ON THE")), None)
            if k is not None:
                return (k + 1) - int(m.group(1))
    return None


def rules_book() -> Path | None:
    """The NFHS Swimming & Diving Rules Book, if it's in the library (PDF or saved web page)."""
    for f in docs():
        pg = pages(f)
        if any("RULE 8 - Swimming Events" in t or "RULE 8 - SWIMMING EVENTS" in t for t in pg) and \
                any("RULES BOOK" in t.upper() for t in pg[:3]):
            return f
    return None


def _norm_ws(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip().lower()


def rule_lines(f: Path) -> list[dict]:
    """Every line of the rules book with the rule-section-article it sits in and its page."""
    out, r, sec, art = [], None, None, None
    for i, t in enumerate(pages(f)):
        for ln in t.splitlines():
            m = re.match(r"RULE (\d+) - ", ln)
            if m:
                r, sec, art = m.group(1), None, None
            m = re.match(r"SECTION (\d+)\s", ln)
            if m:
                sec, art = m.group(1), None
            m = re.match(r"ART\. (\d+)", ln)
            if m:
                art = m.group(1)
            if re.match(r"(RULE \d+, SECTION|SITUATIONS? AND RULINGS?)", ln):
                art = "sit"                      # the rulings that follow each section are not the rule itself
            out.append({"ref": f"{r}-{sec}-{art}", "text": ln.strip(), "page": i + 1,
                        "situation": bool(re.match(r"\d+\.\d+(\.\d+)?\s+SITUATION", ln)) or art == "sit"})
    return out


def rule_text(ref: str, phrase: str = "") -> dict | None:
    """The rules-book text for a rule like '8-2-3' (optionally the line in it containing phrase)."""
    f = rules_book()
    if not f:
        return None
    nums = re.findall(r"\d+", ref)[:3]
    base = "-".join(nums)
    lines = [x for x in rule_lines(f) if not x["situation"] and
             (x["ref"] == base or (len(nums) == 2 and x["ref"].startswith(base + "-")))]
    if not lines:
        return None
    head = lines[0]
    hit = next((x for x in lines if phrase and _norm_ws(phrase) in _norm_ws(x["text"])), None)
    pick = hit or head
    off = html_book_offset(f) if is_html(f) else None
    if is_html(f):
        book = pick["page"] - off if off is not None else None
    else:
        bp, exact = book_page(pages(f)[pick["page"] - 1], pick["page"] - 1, sections(f))
        book = bp if exact else None
    return {"ref": ref, "head": head["text"] if hit and hit is not head else "", "text": pick["text"],
            "page": pick["page"], "book_page": book, "file": f.name, "html": is_html(f)}


HTML_CACHE_V = "v2"     # bump when the way saved web pages are split into pages changes


def _cache(f: Path) -> Path:
    return f.with_suffix(f.suffix + (f".{HTML_CACHE_V}.json" if is_html(f) else ".json"))


def pages(f: Path) -> list[str]:
    c = _cache(f)
    if c.exists() and c.stat().st_mtime >= f.stat().st_mtime:
        return json.loads(c.read_text())
    if is_html(f):
        out = [_html_text(p) for p in html_parts(f)]
        c.write_text(json.dumps(out))
        return out
    from pypdf import PdfReader
    out = []
    try:
        for p in PdfReader(str(f)).pages:
            try:
                out.append(re.sub(r"[ \t]+", " ", p.extract_text() or ""))
            except Exception:
                out.append("")
    except Exception:
        out = []
    c.write_text(json.dumps(out))
    return out


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def sections(f: Path) -> list[dict]:
    """[{title, page}] from the document's own table of contents (title lines followed by page numbers),
    each mapped to the PDF page where that heading actually appears. Falls back to the PDF outline."""
    c = f.with_suffix(f.suffix + (f".{HTML_CACHE_V}.toc.json" if is_html(f) else ".toc.json"))
    if c.exists() and c.stat().st_mtime >= f.stat().st_mtime:
        return json.loads(c.read_text())
    pg = pages(f)
    if is_html(f):
        off = html_book_offset(f)
        out = []
        for i, t in enumerate(pg):
            heads = [ln for ln in t.splitlines() if re.match(r"(RULE \d+ - |SECTION \d+\s|APPENDIX|INDEX$|STATE ASSOCIATION ADOPTION)", ln)]
            for h in heads:
                d = {"title": h[:90], "page": i + 1}
                if off is not None and i + 1 - off > 0:
                    d["book"] = i + 1 - off
                out.append(d)
        if not out:
            out = [{"title": (t.splitlines() or [""])[0][:90], "page": i + 1} for i, t in enumerate(pg) if t.strip()]
        c.write_text(json.dumps(out))
        return out
    toc, toc_pages = [], set()
    for i, text in enumerate(pg[:8]):
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        found = []
        for j, ln in enumerate(lines):
            m = re.match(r"^(.*?[A-Za-z].*?)[ .]{2,}(\d{1,3})$", ln)
            if m:
                found.append((m.group(1).strip(), int(m.group(2))))
            elif re.fullmatch(r"\d{1,3}", ln) and j and re.search(r"[A-Za-z]", lines[j - 1]) and not re.fullmatch(r"\d{1,3}", lines[j - 1]):
                found.append((lines[j - 1], int(ln)))
        if len(found) >= 5:
            toc += found
            toc_pages.add(i)
    out = []
    if toc:
        start = max(toc_pages) + 1
        normed = [_norm(t) for t in pg]
        toc.sort(key=lambda x: x[1])            # book order
        off = start - toc[0][1]                  # first guess: content starts right after the contents pages
        prev = start
        for title, book in toc:
            key = _norm(title)
            if len(key) < 3:
                continue
            guess = book + off
            lo, hi = max(prev, guess - 8), min(len(pg) - 1, guess + 14)
            hit = next((k for k in range(lo, hi + 1) if key in normed[k]), None)
            if hit is None:                      # heading not found (odd spacing): estimate, but don't anchor on it
                est = min(max(guess, prev), len(pg) - 1)
                out.append({"title": title, "book": book, "page": est + 1})
                continue
            off = hit - book                     # the offset drifts (reflowed / inserted pages); follow it
            prev = hit
            out.append({"title": title, "book": book, "page": hit + 1})
    else:
        try:
            from pypdf import PdfReader
            r = PdfReader(str(f))
            def walk(items):
                for it in items:
                    if isinstance(it, list):
                        walk(it)
                    else:
                        try:
                            out.append({"title": str(it.title), "page": r.get_destination_page_number(it) + 1})
                        except Exception:
                            pass
            walk(r.outline or [])
        except Exception:
            pass
    out.sort(key=lambda o: o["page"])
    c.write_text(json.dumps(out))
    return out


def section_of(secs: list[dict], page: int) -> str:
    cur = ""
    for s_ in secs:
        if s_["page"] <= page:
            cur = s_["title"]
        else:
            break
    return cur


def book_page(text: str, i: int, secs: list[dict]) -> tuple[str, bool]:
    """The page number printed in the physical book for PDF page i (0-based) -> (label, exact).
    Read off the page itself (running header / lone number at top or bottom); else estimated
    from the contents page of the nearest heading before it; slides give their slide number."""
    head = text[:200]
    m = re.search(r"HANDBOOK\s*\n?\s*(\d{1,4})\b", head)
    if m:
        return m.group(1), True
    m = re.match(r"\s*Slide (\d+):", text)
    if m:
        return "slide " + m.group(1), True
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines[:2] + lines[-2:]:
        if re.fullmatch(r"\d{1,3}", ln) and abs(int(ln) - (i + 1)) <= 40:
            return ln, True
    prev = [x for x in secs if x.get("book") and x["page"] <= i + 1]
    if prev:
        x = prev[-1]
        return str(x["book"] + (i + 1 - x["page"])), False
    return "", False


def listing() -> list[dict]:
    ensure_seed()
    out_docs = []
    for f in docs():
        pg = pages(f)
        out_docs.append({"name": f.name, "html": is_html(f), "pages": len(pg), "size": f.stat().st_size,
                     "searchable": any(len(t.strip()) > 40 for t in pg), "sections": sections(f)})
    return out_docs


def search(q: str, limit: int = 60) -> list[dict]:
    q = (q or "").strip()
    if not q:
        return []
    phrase = q[1:-1] if len(q) > 2 and q[0] == q[-1] == '"' else None
    words = [phrase] if phrase else [w for w in re.split(r"\s+", q) if w]
    # rule numbers like 6-4-1 also match 6.4.1 (the 2026-27 book uses both styles)
    def pat(w):
        if re.fullmatch(r"\d+(?:[-.]\d+)+[a-z]?", w, re.I):
            return re.compile(r"(?<![\d.-])" + r"[-.]".join(re.escape(p) for p in re.split(r"[-.]", w)) + r"(?![\d])", re.I)
        return re.compile(re.escape(w), re.I)
    pats = [pat(w) for w in words]
    ensure_seed()
    hits = []
    for f in docs():
        secs = sections(f)
        for i, text in enumerate(pages(f)):
            if not all(p.search(text) for p in pats):
                continue
            m = pats[0].search(text)
            a, b = max(0, m.start() - 160), min(len(text), m.end() + 220)
            snip = ("…" if a else "") + text[a:b].replace("\n", " ") + ("…" if b < len(text) else "")
            score = sum(len(p.findall(text)) for p in pats)
            run = re.match(r"\s*\d{4}-\d{2}\s+[A-Z]+\s+HANDBOOK\s+\d+\s+([A-Z][A-Z0-9 &/,'-]{2,40}?)\s*\n", text)
            sec = run.group(1).strip().title() if run else section_of(secs, i + 1)   # running page header wins
            if is_html(f):
                off = html_book_offset(f)
                bp, exact = (str(i + 1 - off), True) if off is not None and i + 1 - off > 0 else ("", False)
            else:
                bp, exact = book_page(text, i, secs)
            hits.append({"file": f.name, "page": i + 1, "html": is_html(f), "book_page": bp, "book_exact": exact,
                         "snippet": snip, "score": score, "section": sec})
    hits.sort(key=lambda h: -h["score"])
    return hits[:limit]
