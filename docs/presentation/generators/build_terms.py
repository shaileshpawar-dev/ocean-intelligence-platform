"""Build the OceanAI terminology guide as a Word file, for export to PDF.

Four sections, one per person, preceded by the terms everyone needs. Each
entry gives the definition, how the platform actually uses it, and the
figure or sentence to have ready if an examiner pushes.
"""

from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Inches, Pt, RGBColor

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from terms_content import SECTIONS, SHARED  # noqa: E402

OUT = HERE / "OceanAI-Terms-Explained.docx"

FONT = "Times New Roman"
INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x4C, 0x56, 0x61)
ACCENT = RGBColor(0x1F, 0x5F, 0x8B)
WARM = RGBColor(0x8A, 0x5A, 0x16)
PANEL = "EEF3F8"
RULE = "C9D6E2"


def set_font(run, *, size=11, bold=False, italic=False, color=INK):
    f = run.font
    f.name = FONT
    f.size = Pt(size)
    f.bold = bold
    f.italic = italic
    f.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.insert(0, rfonts)
    for slot in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(slot), FONT)


def para(doc, text="", *, size=11, bold=False, italic=False, color=INK,
         align=None, before=0, after=5, left=0.0, first_line=0.0,
         keep_next=False):
    p = doc.add_paragraph()
    p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.left_indent = Inches(left)
    pf.first_line_indent = Inches(first_line)
    pf.keep_with_next = keep_next
    if text:
        set_font(p.add_run(text), size=size, bold=bold, italic=italic,
                 color=color)
    return p


def shade(paragraph, fill=PANEL):
    """A tinted background behind a paragraph, used instead of a rule."""
    ppr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    ppr.append(shd)
    borders = OxmlElement("w:pBdr")
    for edge in ("top", "left", "bottom", "right"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), "4")
        el.set(qn("w:space"), "6")
        el.set(qn("w:color"), RULE)
        borders.append(el)
    ppr.append(borders)
    return paragraph


def page_break(doc):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.add_run().add_break(WD_BREAK.PAGE)


def labelled(doc, label, text, *, color=ACCENT, size=11, left=0.26):
    """A run-in label followed by its sentence, e.g. 'In OceanAI. ...'."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf = p.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(4)
    pf.left_indent = Inches(left)
    set_font(p.add_run(label + "  "), size=size, bold=True, color=color)
    set_font(p.add_run(text), size=size)
    return p


def entry(doc, number, term, what, used, know):
    """One glossary entry."""
    head = doc.add_paragraph()
    pf = head.paragraph_format
    pf.space_before = Pt(11)
    pf.space_after = Pt(4)
    pf.keep_with_next = True
    set_font(head.add_run(f"{number}.  "), size=12, bold=True, color=MUTED)
    set_font(head.add_run(term), size=12, bold=True, color=INK)

    labelled(doc, "What it is.", what)
    labelled(doc, "In OceanAI.", used)
    if know:
        p = labelled(doc, "Know this.", know, color=WARM, size=10.5)
        shade(p)


def section_header(doc, name, module, blurb, count):
    page_break(doc)
    p = para(doc, name, size=26, bold=True, color=ACCENT, before=0, after=0,
             keep_next=True)
    para(doc, module, size=17, italic=True, color=MUTED, before=2, after=8,
         keep_next=True)
    para(doc, blurb, size=11.5, color=INK, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
         after=6)
    para(doc, f"{count} terms", size=10.5, bold=True, color=MUTED, after=10)


def add_page_numbers(section):
    """A centred page number in the footer."""
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    set_font(run, size=9.5, color=MUTED)
    for instr, kind in (("begin", "fldChar"), ("PAGE", "instrText"),
                        ("end", "fldChar")):
        el = OxmlElement(f"w:{kind}")
        if kind == "fldChar":
            el.set(qn("w:fldCharType"), instr)
        else:
            el.set(qn("xml:space"), "preserve")
            el.text = " PAGE "
        run._r.append(el)


def build() -> None:
    doc = Document()

    section = doc.sections[0]
    section.page_width = Inches(8.27)      # A4
    section.page_height = Inches(11.69)
    for attr, value in (("left_margin", 0.85), ("right_margin", 0.85),
                        ("top_margin", 0.80), ("bottom_margin", 0.75)):
        setattr(section, attr, Inches(value))
    add_page_numbers(section)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(11)

    # ---------------------------------------------------------- cover ----
    para(doc, "OceanAI", size=38, bold=True, color=ACCENT,
         align=WD_ALIGN_PARAGRAPH.CENTER, before=72, after=4)
    para(doc, "Terms explained", size=22, italic=True, color=MUTED,
         align=WD_ALIGN_PARAGRAPH.CENTER, after=10)
    para(doc,
         "A reference for the project demonstration and viva, divided by "
         "the part of the platform each of us owns.",
         size=12, color=INK, align=WD_ALIGN_PARAGRAPH.CENTER, after=28)

    table = doc.add_table(rows=len(SECTIONS) + 1, cols=3)
    table.style = "Table Grid"
    table.alignment = WD_ALIGN_PARAGRAPH.CENTER
    widths = (1.55, 2.5, 2.5)
    header = ("Name", "Module", "Covers")
    for c, text in enumerate(header):
        cell = table.rows[0].cells[c]
        cell.text = ""
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(cell.paragraphs[0].add_run(text), size=11, bold=True,
                 color=RGBColor(0xFF, 0xFF, 0xFF))
        shade(cell.paragraphs[0], fill="1F5F8B")
    covers = {
        "India Water Intelligence": "CPCB and CWC data, freshness rules, "
                                    "standards, question answering",
        "Marine Monitoring": "Sentinel-1 and Sentinel-2, spectral indices, "
                             "detection criteria, vessel activity",
        "Intelligence": "Risk scoring, forecasting, the knowledge graph, "
                        "reports",
        "AI Research": "The classifier, its metrics, drift monitoring, "
                       "retraining policy",
    }
    for r, (name, module, _blurb, items) in enumerate(SECTIONS, start=1):
        cells = table.rows[r].cells
        for c, text in enumerate((name, module, covers[module])):
            cells[c].text = ""
            p = cells[c].paragraphs[0]
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after = Pt(3)
            set_font(p.add_run(text), size=10.5,
                     bold=(c == 0), color=ACCENT if c == 0 else INK)
    for row in table.rows:
        for cell, w in zip(row.cells, widths):
            cell.width = Inches(w)

    para(doc, "", after=18)
    total = len(SHARED) + sum(len(items) for *_x, items in SECTIONS)
    para(doc,
         f"{total} terms in all · {len(SHARED)} shared, then "
         + ", ".join(f"{len(items)} for {name}"
                     for name, *_r, items in SECTIONS),
         size=11, color=MUTED, align=WD_ALIGN_PARAGRAPH.CENTER, after=6)
    para(doc,
         "Every figure quoted was read from the running application or its "
         "database on 24 November 2026, or from the source constant that "
         "produces it.",
         size=10.5, italic=True, color=MUTED,
         align=WD_ALIGN_PARAGRAPH.CENTER, after=0)

    # ------------------------------------------------------ how to use ----
    page_break(doc)
    para(doc, "How to use this", size=22, bold=True, color=ACCENT, after=8)
    # Built from runs: Word renders no markdown, so asterisks would print.
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    p.paragraph_format.space_after = Pt(8)
    for text, bold in (
        ("Each entry has the same three parts. ", False),
        ("What it is", True),
        (" is the definition you would give to someone outside the "
         "project. ", False),
        ("In OceanAI", True),
        (" is how this platform actually uses it, which is usually the part "
         "an examiner is really asking about. ", False),
        ("Know this", True),
        (" is the figure or the sentence to have ready if they push "
         "further.", False),
    ):
        set_font(p.add_run(text), size=11.5, bold=bold)
    para(doc,
         "Read your own section closely and the shared one twice. The "
         "shared terms are the ones any examiner can ask any of us, because "
         "they describe the idea the whole platform is built on rather than "
         "any one module.",
         size=11.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=8)

    p = para(doc,
             "Three answers are worth rehearsing together, because they are "
             "the ones most likely to sound like weaknesses and are in fact "
             "the strongest thing in the project: the radar detector found "
             "nothing over a real wreck; the forecaster beats the naive "
             "baseline in none of 40 regions; and the drift monitor is "
             "reporting drift. All three are on the screen deliberately. "
             "The answer to each is the same shape — here is the result, "
             "here is why it is weak or unfavourable, and here is why "
             "publishing it is the point.",
             size=11.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=8)
    shade(p)

    para(doc,
         "Two things never to say: never call a floating-material detection "
         "plastic, and never name a vessel as the source of anything. Both "
         "are claims the data cannot support, and both are the kind of "
         "mistake that is quoted back.",
         size=11.5, italic=True, color=WARM,
         align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=0)

    # ---------------------------------------------------------- shared ----
    page_break(doc)
    para(doc, "Shared", size=26, bold=True, color=ACCENT, after=0,
         keep_next=True)
    para(doc, "Everyone should be able to answer these", size=17,
         italic=True, color=MUTED, before=2, after=8, keep_next=True)
    para(doc,
         "These describe the design idea the platform is built on, so they "
         "can be asked of any of us regardless of which module we present.",
         size=11.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=6)
    para(doc, f"{len(SHARED)} terms", size=10.5, bold=True, color=MUTED,
         after=10)
    for i, (term, what, used, know) in enumerate(SHARED, start=1):
        entry(doc, i, term, what, used, know)

    # ----------------------------------------------------- per person ----
    for name, module, blurb, items in SECTIONS:
        section_header(doc, name, module, blurb, len(items))
        for i, (term, what, used, know) in enumerate(items, start=1):
            entry(doc, i, term, what, used, know)

    doc.save(str(OUT))
    print("written:", OUT)
    print(f"{total} terms")


if __name__ == "__main__":
    build()
