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


def _cache(f: Path) -> Path:
    return f.with_suffix(f.suffix + ".json")


def pages(f: Path) -> list[str]:
    c = _cache(f)
    if c.exists() and c.stat().st_mtime >= f.stat().st_mtime:
        return json.loads(c.read_text())
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
    c = f.with_suffix(f.suffix + ".toc.json")
    if c.exists() and c.stat().st_mtime >= f.stat().st_mtime:
        return json.loads(c.read_text())
    pg = pages(f)
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
    docs = []
    for f in sorted(RULES.glob("*.pdf")):
        pg = pages(f)
        docs.append({"name": f.name, "pages": len(pg), "size": f.stat().st_size,
                     "searchable": any(len(t.strip()) > 40 for t in pg), "sections": sections(f)})
    return docs


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
    for f in sorted(RULES.glob("*.pdf")):
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
            bp, exact = book_page(text, i, secs)
            hits.append({"file": f.name, "page": i + 1, "book_page": bp, "book_exact": exact,
                         "snippet": snip, "score": score, "section": sec})
    hits.sort(key=lambda h: -h["score"])
    return hits[:limit]
