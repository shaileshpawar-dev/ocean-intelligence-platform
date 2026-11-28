"""Build the OceanAI page-by-page guide as a Word file, for export to PDF.

A primer for someone who has not seen the project, then all 21 pages of
the application in navigation order, each with what it is for, what is on
the screen, how it works, every term that appears on it, and the questions
it attracts.
"""

from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import guide_content as C  # noqa: E402

OUT = HERE / "OceanAI-Page-by-Page-Guide.docx"

FONT = "Times New Roman"
INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x4C, 0x56, 0x61)
ACCENT = RGBColor(0x1F, 0x5F, 0x8B)
WARM = RGBColor(0x8A, 0x5A, 0x16)
PANEL = "EEF3F8"
TINT = "F6F9FC"
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
         align=None, before=0, after=5, left=0.0, hanging=0.0,
         keep_next=False):
    p = doc.add_paragraph()
    p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.left_indent = Inches(left)
    if hanging:
        pf.first_line_indent = Inches(-hanging)
    pf.keep_with_next = keep_next
    if text:
        set_font(p.add_run(text), size=size, bold=bold, italic=italic,
                 color=color)
    return p


def shade(paragraph, fill=PANEL, border=True):
    ppr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    ppr.append(shd)
    if border:
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


def start_page(paragraph):
    """Begin a new sheet at this paragraph, without an empty one before it.

    An inserted break character after content that already ended at a page
    boundary leaves a blank page behind; page_break_before does not.
    """
    paragraph.paragraph_format.page_break_before = True
    return paragraph


def page_break(doc):
    """Only for places with no following paragraph to hang the break on."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.add_run().add_break(WD_BREAK.PAGE)


def bullet(doc, text, *, size=11, left=0.30, after=3, bold_lead=None):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf = p.paragraph_format
    pf.left_indent = Inches(left + 0.22)
    pf.first_line_indent = Inches(-0.22)
    pf.space_after = Pt(after)
    set_font(p.add_run("•\t"), size=size, color=ACCENT)
    if bold_lead:
        set_font(p.add_run(bold_lead + "  "), size=size, bold=True)
    set_font(p.add_run(text), size=size)
    return p


def definition(doc, term, text, *, size=10.5):
    """A hanging-indent term followed by its explanation."""
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf = p.paragraph_format
    pf.left_indent = Inches(0.52)
    pf.first_line_indent = Inches(-0.30)
    pf.space_after = Pt(3)
    set_font(p.add_run(term + "  —  "), size=size, bold=True,
             color=ACCENT)
    set_font(p.add_run(text), size=size)
    return p


def sub(doc, text):
    return para(doc, text, size=12.5, bold=True, color=ACCENT, before=8,
                after=4, keep_next=True)


def add_page_numbers(section):
    footer = section.footer
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    set_font(run, size=9.5, color=MUTED)
    for kind, value in (("fldChar", "begin"), ("instrText", " PAGE "),
                        ("fldChar", "end")):
        el = OxmlElement(f"w:{kind}")
        if kind == "fldChar":
            el.set(qn("w:fldCharType"), value)
        else:
            el.set(qn("xml:space"), "preserve")
            el.text = value
        run._r.append(el)


# ---------------------------------------------------------------- build ---
def write_page(doc, page, number, total):
    head = doc.add_paragraph()
    start_page(head)
    head.paragraph_format.space_after = Pt(1)
    head.paragraph_format.keep_with_next = True
    set_font(head.add_run(f"{number}.  "), size=18, bold=True, color=MUTED)
    set_font(head.add_run(page["name"]), size=18, bold=True, color=ACCENT)

    para(doc, page["path"], size=10.5, italic=True, color=MUTED,
         after=7, keep_next=True)

    sub(doc, "What it is for")
    para(doc, page["purpose"], size=11.5,
         align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=4)

    sub(doc, "What you are looking at")
    for label, text in page["see"]:
        bullet(doc, text, bold_lead=label + ".")

    sub(doc, "How it works")
    for text in page["working"]:
        para(doc, text, size=11, align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=4)

    sub(doc, "Terms on this page")
    for term, text in page["terms"]:
        definition(doc, term, text)

    sub(doc, "If you are asked")
    for question, answer in page["asked"]:
        para(doc, question, size=11, bold=True, color=WARM, before=4,
             after=2, keep_next=True)
        a = para(doc, answer, size=11, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                 after=3, left=0.0)
        shade(a, fill=TINT)


def build() -> None:
    doc = Document()

    section = doc.sections[0]
    section.page_width = Inches(8.27)
    section.page_height = Inches(11.69)
    section.left_margin = section.right_margin = Inches(0.85)
    section.top_margin = Inches(0.80)
    section.bottom_margin = Inches(0.75)
    add_page_numbers(section)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(11)

    pages = [p for _n, _b, group in C.GROUPS for p in group]
    total = len(pages)

    # ------------------------------------------------------------ cover --
    para(doc, "OceanAI", size=38, bold=True, color=ACCENT,
         align=WD_ALIGN_PARAGRAPH.CENTER, before=84, after=4)
    para(doc, "A page-by-page guide", size=22, italic=True, color=MUTED,
         align=WD_ALIGN_PARAGRAPH.CENTER, after=12)
    para(doc,
         "Written for someone who has not seen this project before. Every "
         "screen in the application, what it does, how it works, and every "
         "term that appears on it.",
         size=12.5, align=WD_ALIGN_PARAGRAPH.CENTER, after=26)

    p = para(doc,
             f"A primer, then all {total} pages of the application in "
             "navigation order. You do not need to read it end to end: "
             "read the primer, then the pages you will be standing in "
             "front of.",
             size=11.5, align=WD_ALIGN_PARAGRAPH.CENTER, after=24)
    shade(p)

    for name, blurb, group in C.GROUPS:
        row = doc.add_paragraph()
        row.alignment = WD_ALIGN_PARAGRAPH.CENTER
        row.paragraph_format.space_after = Pt(5)
        set_font(row.add_run(name), size=12.5, bold=True, color=ACCENT)
        set_font(row.add_run("   ·   "), size=12.5, color=MUTED)
        set_font(row.add_run(" · ".join(p["name"] for p in group)),
                 size=11, color=INK)

    para(doc, "", after=22)
    para(doc,
         "Every figure quoted was read from the running application on "
         "24 November 2026.",
         size=10.5, italic=True, color=MUTED,
         align=WD_ALIGN_PARAGRAPH.CENTER, after=0)

    # ------------------------------------------------------- the primer --
    start_page(para(doc, "Start here", size=26, bold=True, color=ACCENT,
                    after=10, keep_next=True))

    sub(doc, "What this project is")
    for text in C.WHAT_IT_IS:
        para(doc, text, size=11.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
             after=6)

    sub(doc, "The one idea behind all of it")
    for i, text in enumerate(C.THE_ONE_IDEA):
        p = para(doc, text, size=11.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                 after=6)
        if i == len(C.THE_ONE_IDEA) - 1:
            shade(p)

    sub(doc, "How the system is put together")
    for label, text in C.HOW_BUILT:
        bullet(doc, text, bold_lead=label, size=11)

    start_page(para(doc, "The vocabulary you cannot avoid", size=26,
                    bold=True, color=ACCENT, after=6, keep_next=True))
    para(doc,
         "These twelve come up on almost every page. The rest of this "
         "guide defines terms where they appear; these are the ones worth "
         "reading first.",
         size=11.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=9)
    for term, text in C.VOCABULARY:
        definition(doc, term, text, size=11)

    sub(doc, "How to read the rest of this")
    for i, text in enumerate(C.READING_NOTE):
        if i == 0:
            # Built from runs: Word renders no markdown.
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.space_after = Pt(6)
            for chunk, bold in (
                ("Each page below is covered in five parts. ", False),
                ("What it is for", True),
                (" is one sentence you could say to anyone. ", False),
                ("What you are looking at", True),
                (" walks the screen top to bottom. ", False),
                ("How it works", True),
                (" is the mechanism behind the numbers. ", False),
                ("Terms on this page", True),
                (" defines every piece of jargon that appears there. ",
                 False),
                ("If you are asked", True),
                (" gives the questions that page tends to attract, with "
                 "answers.", False),
            ):
                set_font(p.add_run(chunk), size=11.5, bold=bold)
        else:
            para(doc, text, size=11.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                 after=6)

    # ------------------------------------------------------- the pages ---
    number = 0
    for name, blurb, group in C.GROUPS:
        start_page(para(doc, name, size=28, bold=True, color=ACCENT,
                        after=4, keep_next=True))
        para(doc, blurb, size=12, color=INK,
             align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=8, keep_next=True)
        para(doc,
             f"{len(group)} pages:  " + "  ·  ".join(
                 p["name"] for p in group),
             size=11, bold=True, color=MUTED, after=0)

        for page in group:
            number += 1
            write_page(doc, page, number, total)

    # ----------------------------------------------------- the closing ---
    start_page(para(doc, "Numbers worth remembering", size=26, bold=True,
                    color=ACCENT, after=6, keep_next=True))
    para(doc,
         "If you are asked for a figure and cannot find it on screen, "
         "these are the ones that carry the project.",
         size=11.5, after=9)
    table = doc.add_table(rows=len(C.NUMBERS), cols=2)
    table.style = "Table Grid"
    for r, (value, label) in enumerate(C.NUMBERS):
        cells = table.rows[r].cells
        for c, (text, bold, color, size) in enumerate((
                (value, True, ACCENT, 11.5), (label, False, INK, 10.5))):
            cells[c].text = ""
            p = cells[c].paragraphs[0]
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
            set_font(p.add_run(text), size=size, bold=bold, color=color)
        cells[0].width = Inches(1.7)
        cells[1].width = Inches(4.9)

    start_page(para(doc, "Three answers to rehearse", size=26, bold=True,
                    color=ACCENT, after=6, keep_next=True))
    para(doc,
         "These are the findings most likely to sound like weaknesses, and "
         "they are the strongest thing in the project. Each answer has the "
         "same shape: here is the result, here is why it is unfavourable, "
         "and here is why publishing it is the point.",
         size=11.5, align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=10)
    for claim, answer in C.THREE_ANSWERS:
        para(doc, claim, size=12.5, bold=True, color=WARM, before=6,
             after=3, keep_next=True)
        p = para(doc, answer, size=11,
                 align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=6)
        shade(p)

    para(doc, "Six things never to say", size=26, bold=True, color=ACCENT,
         before=18, after=6, keep_next=True)
    para(doc,
         "Each of these is a claim the data cannot support, and each is "
         "the kind of sentence that gets quoted back at you.",
         size=11.5, after=9)
    for wrong, right in C.NEVER_SAY:
        para(doc, wrong, size=11.5, bold=True, color=WARM, before=6,
             after=2, keep_next=True)
        para(doc, right, size=11, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
             after=4, left=0.26)

    doc.save(str(OUT))
    print("written:", OUT)
    print(f"{total} application pages documented")
    terms = sum(len(p["terms"]) for p in pages) + len(C.VOCABULARY)
    print(f"{terms} terms defined")


if __name__ == "__main__":
    build()
