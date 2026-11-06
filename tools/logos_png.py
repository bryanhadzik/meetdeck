"""raw logos (gif/png/svg) -> logos/png/<Class> R<region> <School>.png (transparent, max 512px) + contact sheet."""
import io, json, sys, html
from pathlib import Path
from PIL import Image

raw, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
idx = json.loads((raw / "schools.json").read_text())
files = {p.stem: p for p in raw.iterdir() if p.suffix.lower() in (".gif", ".png", ".svg", ".jpg")}
rows = []
for r in idx:
    stem = f"{r['class']} R{r['region']} {r['school']}"
    src = files.get(stem)
    if not src:
        rows.append((r, None)); continue
    if src.suffix.lower() == ".svg":
        import cairosvg
        img = Image.open(io.BytesIO(cairosvg.svg2png(url=str(src), output_width=512)))
    else:
        img = Image.open(src)
    img = img.convert("RGBA")
    img.thumbnail((512, 512))
    img.save(out / f"{stem}.png")
    r["png"] = f"{stem}.png"
    rows.append((r, f"{stem}.png"))
(out / "schools.json").write_text(json.dumps(idx, indent=1))
cells = "".join(f"""<div class=c><div class=i style="background:{'#1f3b5a' if r['school'] in ('Utah Arts Academy','Vista School') else '#fff'}">{f'<img src="{html.escape(f)}">' if f else 'missing'}</div>
<b>{html.escape(r['school'])}</b><span>{r['class']} Region {r['region']}</span></div>""" for r, f in rows)
(out / "index.html").write_text(f"""<!doctype html><meta charset=utf-8><title>Utah 3A & 4A logos</title>
<style>body{{font:13px system-ui;margin:16px;background:#f3f4f6}}.g{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}}
.c{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:8px;text-align:center}}.i{{height:110px;display:flex;align-items:center;justify-content:center;border-radius:6px}}
.i img{{max-height:100px;max-width:130px}}b{{display:block;margin-top:4px}}span{{color:#666;font-size:12px}}</style>
<h2>Utah 3A & 4A high school logos (UHSAA 2025-27)</h2><div class=g>{cells}</div>""")
print(sum(1 for _, f in rows if f), "converted")
