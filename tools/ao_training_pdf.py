"""AO training slides (text) -> a searchable PDF in the rules library, one page per slide, with a contents
file so the Rules page can jump to each slide.   python3 ao_training_pdf.py slides.json out.pdf"""
import json, sys
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether
from reportlab.lib import colors
from xml.sax.saxutils import escape

slides = json.load(open(sys.argv[1]))
out = sys.argv[2]
T = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=22, leading=27, textColor=colors.HexColor("#1f3b6f"), spaceAfter=10)
B = ParagraphStyle("b", fontName="Helvetica", fontSize=14, leading=19, leftIndent=16, bulletIndent=2, spaceAfter=5)
N = ParagraphStyle("n", fontName="Helvetica-Oblique", fontSize=11, leading=14, textColor=colors.HexColor("#555555"),
                   backColor=colors.HexColor("#f2f4f7"), borderPadding=6, spaceBefore=12)
F = ParagraphStyle("f", fontName="Helvetica", fontSize=9, textColor=colors.HexColor("#888888"))
story = []
for i, s in enumerate(slides):
    story.append(Paragraph(escape(f"Slide {s['n']}: {s['title']}"), T))
    for ln in s["lines"]:
        story.append(Paragraph(escape(ln), B, bulletText="•"))
    if s.get("notes"):
        story.append(Paragraph("Presenter notes: " + escape(s["notes"]), N))
    story.append(Spacer(1, 10))
    story.append(Paragraph("UHSAA Administrative Official Training, High School Swimming 2026–27 (slides by Sharen Portillo, presented by Braxton Evans)", F))
    if i < len(slides) - 1:
        story.append(PageBreak())
doc = SimpleDocTemplate(out, pagesize=landscape(letter), leftMargin=54, rightMargin=54, topMargin=46, bottomMargin=40,
                        title="2026-27 UHSAA AO Training (slides)", author="UHSAA")
doc.build(story)
toc = [{"title": f"Slide {s['n']}: {s['title']}", "book": i + 1, "page": i + 1} for i, s in enumerate(slides)]
open(out + ".toc.json", "w").write(json.dumps(toc, indent=1))
print("pages:", len(slides))
