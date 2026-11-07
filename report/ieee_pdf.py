"""Minimal IEEE-conference-style two-column PDF renderer (reportlab).

Mirrors the IEEEtran conference layout closely enough for a progress report:
US Letter, Times, 24 pt title, 10 pt body, two 3.5 in columns, roman-numeral
small-caps section headings, 8 pt captions and tables.  The final paper should
use the accompanying LaTeX source (report/milestone.tex) with IEEEtran.
"""
from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (BaseDocTemplate, Frame, FrameBreak, Image, KeepTogether, NextPageTemplate,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

PAGE_W, PAGE_H = letter
LM = RM = 0.625 * inch
TM, BM = 0.75 * inch, 1.0 * inch
GAP = 0.25 * inch
COL_W = (PAGE_W - LM - RM - GAP) / 2

S = {
    "title": ParagraphStyle("title", fontName="Times-Roman", fontSize=24, leading=28, alignment=TA_CENTER, spaceAfter=10),
    "authors": ParagraphStyle("authors", fontName="Times-Roman", fontSize=11, leading=13, alignment=TA_CENTER),
    "affil": ParagraphStyle("affil", fontName="Times-Italic", fontSize=10, leading=12, alignment=TA_CENTER, spaceAfter=14),
    "abstract": ParagraphStyle("abstract", fontName="Times-Bold", fontSize=9, leading=10.5, alignment=TA_JUSTIFY, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="Times-Roman", fontSize=10, leading=11.6, alignment=TA_JUSTIFY,
                           firstLineIndent=10, spaceAfter=1.5),
    "bodyni": ParagraphStyle("bodyni", fontName="Times-Roman", fontSize=10, leading=11.6, alignment=TA_JUSTIFY, spaceAfter=1.5),
    "bullet": ParagraphStyle("bullet", fontName="Times-Roman", fontSize=10, leading=11.6, alignment=TA_JUSTIFY,
                             leftIndent=11, bulletIndent=2, spaceAfter=1),
    "h1": ParagraphStyle("h1", fontName="Times-Roman", fontSize=10, leading=12, alignment=TA_CENTER, spaceBefore=7, spaceAfter=3),
    "h2": ParagraphStyle("h2", fontName="Times-Italic", fontSize=10, leading=12, alignment=TA_LEFT, spaceBefore=4, spaceAfter=2),
    "caption": ParagraphStyle("caption", fontName="Times-Roman", fontSize=8, leading=9.4, alignment=TA_JUSTIFY, spaceBefore=3, spaceAfter=6),
    "tcaption": ParagraphStyle("tcaption", fontName="Times-Roman", fontSize=8, leading=9.4, alignment=TA_CENTER, spaceBefore=4, spaceAfter=3),
    "cell": ParagraphStyle("cell", fontName="Times-Roman", fontSize=7.4, leading=8.4, alignment=TA_LEFT),
    "cellc": ParagraphStyle("cellc", fontName="Times-Roman", fontSize=7.4, leading=8.4, alignment=TA_CENTER),
    "ref": ParagraphStyle("ref", fontName="Times-Roman", fontSize=8, leading=9.4, alignment=TA_JUSTIFY, leftIndent=14,
                          firstLineIndent=-14, spaceAfter=2),
}

ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


def small_caps(text: str) -> str:
    out = []
    for word in text.split(" "):
        if not word:
            continue
        out.append(word[0].upper() + (f'<font size="8">{word[1:].upper()}</font>' if len(word) > 1 else ""))
    return " ".join(out)


class Doc:
    def __init__(self, path: str, title: str, meta_author: str):
        self.story: list = []
        self.sec = 0
        self.sub = 0
        self.doc = BaseDocTemplate(path, pagesize=letter, leftMargin=LM, rightMargin=RM, topMargin=TM,
                                   bottomMargin=BM, title=title, author=meta_author)
        head_h = 1.75 * inch
        body_h = PAGE_H - TM - BM
        first = [Frame(LM, PAGE_H - TM - head_h, PAGE_W - LM - RM, head_h, id="head", leftPadding=0, rightPadding=0,
                       topPadding=0, bottomPadding=0),
                 Frame(LM, BM, COL_W, body_h - head_h, id="c1", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0),
                 Frame(LM + COL_W + GAP, BM, COL_W, body_h - head_h, id="c2", leftPadding=0, rightPadding=0,
                       topPadding=0, bottomPadding=0)]
        later = [Frame(LM, BM, COL_W, body_h, id="l1", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0),
                 Frame(LM + COL_W + GAP, BM, COL_W, body_h, id="l2", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)]
        self.doc.addPageTemplates([PageTemplate("first", first, onPage=self._footer),
                                   PageTemplate("later", later, onPage=self._footer)])

    @staticmethod
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Times-Roman", 8)
        canvas.drawCentredString(PAGE_W / 2, 0.55 * inch, str(doc.page))
        canvas.restoreState()

    # -- content helpers ---------------------------------------------------
    def header(self, title: str, authors: str, affil: str):
        self.story += [Paragraph(title, S["title"]), Paragraph(authors, S["authors"]), Paragraph(affil, S["affil"]),
                       NextPageTemplate("later"), FrameBreak()]

    def abstract(self, text: str, keywords: str):
        self.story.append(Paragraph(f"<i>Abstract</i>—{text}", S["abstract"]))
        self.story.append(Paragraph(f"<i>Index Terms</i>—{keywords}", S["abstract"]))

    def h1(self, text: str):
        self.sub = 0
        self.story.append(Paragraph(f"{ROMAN[self.sec]}. {small_caps(text)}", S["h1"]))
        self.sec += 1

    def h2(self, text: str):
        self.story.append(Paragraph(f"{chr(65 + self.sub)}. {text}", S["h2"]))
        self.sub += 1

    def p(self, text: str, indent: bool = True):
        self.story.append(Paragraph(text, S["body"] if indent else S["bodyni"]))

    def bullets(self, items: list[str]):
        for it in items:
            self.story.append(Paragraph(it, S["bullet"], bulletText="•"))

    def figure(self, path: str, caption: str, width: float = COL_W):
        img = Image(path)
        img.drawHeight = width * img.imageHeight / img.imageWidth
        img.drawWidth = width
        self.story.append(KeepTogether([Spacer(1, 3), img, Paragraph(caption, S["caption"])]))

    def table(self, caption: str, rows: list[list[str]], col_widths: list[float], align_first_left: bool = True,
              bold_rows: tuple[int, ...] = ()):
        data = []
        for i, r in enumerate(rows):
            line = []
            for j, c in enumerate(r):
                txt = f"<b>{c}</b>" if i == 0 or i in bold_rows else c
                line.append(Paragraph(txt, S["cell"] if (j == 0 and align_first_left) else S["cellc"]))
            data.append(line)
        t = Table(data, colWidths=col_widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.black),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
            ("LINEBELOW", (0, -1), (-1, -1), 0.8, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 1.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2),
            ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ]))
        self.story.append(KeepTogether([Paragraph(caption, S["tcaption"]), t, Spacer(1, 6)]))

    def references(self, refs: list[str]):
        self.story.append(Paragraph(small_caps("References"), S["h1"]))
        for i, r in enumerate(refs, 1):
            self.story.append(Paragraph(f"[{i}]&nbsp;&nbsp;{r}", S["ref"]))

    def build(self):
        self.doc.build(self.story)
