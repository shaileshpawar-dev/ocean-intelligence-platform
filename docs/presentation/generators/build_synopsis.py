"""Fill the B.Tech synopsis template with the OceanAI project content.

The template's front matter (title page, declaration, approval, certificate,
acknowledgement) and its styles are kept exactly as supplied. Student names,
enrolment numbers and the supervisor's name are deliberately left as the
template's own placeholders -- those go on a declaration of academic
integrity and are not ours to invent.

Body formatting follows the instruction line in the template: Times New
Roman, chapter title 16 pt bold, subtitle 12 pt bold, text 12 pt.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import (
    WD_ALIGN_PARAGRAPH,
    WD_BREAK,
    WD_TAB_ALIGNMENT,
    WD_TAB_LEADER,
)
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

HERE = Path(__file__).resolve().parent
FIGS = HERE / "figures"

#: The department's blank synopsis template. It is not redistributed here,
#: so point at your own copy: either drop it beside this script under the
#: name below, or set OCEANAI_SYNOPSIS_TEMPLATE to its path.
TEMPLATE_NAME = "B. Tech CSE Synopsis for Major Project Report format_2026-27.docx"
TEMPLATE = Path(os.environ.get("OCEANAI_SYNOPSIS_TEMPLATE",
                               HERE / TEMPLATE_NAME))

OUT = HERE / "OceanAI-Synopsis.docx"

TITLE = "OceanAI"
FONT = "Times New Roman"


# ---------------------------------------------------------------- helpers --
def set_font(run, *, size=12, bold=False, italic=False, color=None):
    """Force Times New Roman on a run, including the east-asian slot.

    Word falls back to the theme font for characters it classifies as
    east-asian unless ``w:eastAsia`` is set too, which shows up as a
    different typeface on the stray em dash.
    """
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    if color is not None:
        run.font.color.rgb = color
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = rpr.makeelement(qn("w:rFonts"), {})
        rpr.insert(0, rfonts)
    for slot in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(slot), FONT)


def para(doc, text="", *, size=12, bold=False, italic=False, align=None,
         space_before=0, space_after=6, indent=0.0, style="Normal",
         keep_with_next=False):
    """One paragraph, fully specified so no theme default leaks in."""
    p = doc.add_paragraph(style=style)
    p.alignment = align
    pf = p.paragraph_format
    pf.space_before = Pt(space_before)
    pf.space_after = Pt(space_after)
    pf.left_indent = Inches(indent)
    pf.keep_with_next = keep_with_next
    if text:
        set_font(p.add_run(text), size=size, bold=bold, italic=italic)
    return p


def chapter(doc, number, title, *, page_break=True):
    """A numbered chapter heading: 16 pt bold, new page."""
    label = f"{number}. {title}" if number != "" else title
    heading = para(doc, label, size=16, bold=True,
                   space_before=0, space_after=12, keep_with_next=True)
    # page_break_before rather than an inserted break character: a break
    # after content that already ended at a page boundary leaves an empty
    # page behind, which is what chapter 5 was doing.
    heading.paragraph_format.page_break_before = page_break
    return heading


def section(doc, number, title):
    """A numbered sub-heading: 12 pt bold."""
    return para(doc, f"{number} {title}", size=12, bold=True,
                space_before=10, space_after=6, keep_with_next=True)


def body(doc, text):
    """Justified 12 pt body text."""
    return para(doc, text, size=12, align=WD_ALIGN_PARAGRAPH.JUSTIFY,
                space_after=8)


def bullet(doc, text, *, indent=0.35):
    p = doc.add_paragraph(style="Normal")
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf = p.paragraph_format
    pf.left_indent = Inches(indent + 0.25)
    pf.first_line_indent = Inches(-0.25)
    pf.space_after = Pt(4)
    set_font(p.add_run("\u2022\t"), size=12)
    set_font(p.add_run(text), size=12)
    return p


def figure(doc, filename, caption, *, width=6.4, own_page=False):
    """A centred figure with its numbered caption underneath.

    ``own_page`` is for a figure too tall to share a page with text; a
    portrait class diagram at readable size is one.
    """
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(8)
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.page_break_before = own_page
    p.add_run().add_picture(str(FIGS / filename), width=Inches(width))
    return para(doc, caption, size=11, bold=True,
                align=WD_ALIGN_PARAGRAPH.CENTER, space_after=12)


def table(doc, caption, headers, rows, *, widths=None, caption_above=True,
          font_size=10.5):
    """A bordered table with a numbered caption."""
    if caption_above:
        para(doc, caption, size=11, bold=True,
             align=WD_ALIGN_PARAGRAPH.CENTER, space_before=8, space_after=4,
             keep_with_next=True)
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for cell, text in zip(t.rows[0].cells, headers):
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_font(cell.paragraphs[0].add_run(text), size=font_size, bold=True)
    for row in rows:
        cells = t.add_row().cells
        for cell, text in zip(cells, row):
            cell.paragraphs[0].paragraph_format.space_after = Pt(2)
            set_font(cell.paragraphs[0].add_run(text), size=font_size)
    if widths:
        for row in t.rows:
            for cell, w in zip(row.cells, widths):
                cell.width = Inches(w)
    if not caption_above:
        para(doc, caption, size=11, bold=True,
             align=WD_ALIGN_PARAGRAPH.CENTER, space_before=4, space_after=10)
    else:
        para(doc, "", space_after=6)
    return t


def fill_grid(tbl, rows, *, size=11):
    """Write into an existing template table, one row at a time."""
    for i, values in enumerate(rows, start=1):
        while len(tbl.rows) <= i:
            tbl.add_row()
        for cell, text in zip(tbl.rows[i].cells, values):
            cell.text = ""
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            set_font(p.add_run(text), size=size)


def replace_everywhere(doc, old, new):
    """Swap a placeholder wherever it appears, keeping the run's format."""
    hits = 0
    targets = list(doc.paragraphs)
    for tbl in doc.tables:
        for row in tbl.rows:
            for cell in row.cells:
                targets.extend(cell.paragraphs)
    for p in targets:
        if old not in p.text:
            continue
        for run in p.runs:
            if old in run.text:
                run.text = run.text.replace(old, new)
                hits += 1
        if old in p.text:  # split across runs: collapse into the first
            keep, *rest = p.runs
            keep.text = p.text.replace(old, new)
            for r in rest:
                r.text = ""
            hits += 1
    return hits



#: Chapter and section entries for the contents page. Page numbers are
#: resolved in a second pass from the rendered PDF, because a figure's
#: height depends on the renderer and guessing them makes the contents
#: page wrong in exactly the way a reader will check first.
TOC_ENTRIES = [
    ("1.", "INTRODUCTION", "INTRODUCTION"),
    ("1.1", "Background", None),
    ("1.2", "Motivation", None),
    ("1.3", "Objectives", None),
    ("1.4", "Scope of the Work", None),
    ("2.", "LITERATURE SURVEY", "LITERATURE SURVEY"),
    ("2.1", "Introduction", None),
    ("2.2", "Existing Methodologies", None),
    ("2.3", "Comparative Analysis", None),
    ("3.", "PROBLEM STATEMENT", "PROBLEM STATEMENT"),
    ("4.", "SYSTEM ANALYSIS", "SYSTEM ANALYSIS"),
    ("4.1", "Existing System and its Limitations", None),
    ("4.2", "Proposed System", None),
    ("4.3", "Functional Requirements", None),
    ("4.4", "Non-Functional Requirements", None),
    ("4.5", "Hardware and Software Requirements", None),
    ("4.6", "Feasibility Study", None),
    ("5.", "SYSTEM DESIGN", "SYSTEM DESIGN"),
    ("5.1", "Architectural Overview", None),
    ("5.2", "Design Model — Use Case Diagram", None),
    ("5.3", "Class Diagram (Detailed Design)", None),
    ("5.4", "Function Specification — Data Flow Diagram", None),
    ("5.5", "Detection Methodology", None),
    ("6.", "PROJECT TIMELINE", "PROJECT TIMELINE"),
    ("6.1", "Gantt Chart", None),
    ("6.2", "Milestones and Deliverables", None),
    ("7.", "CONCLUSION AND FUTURE SCOPE", "CONCLUSION AND FUTURE SCOPE"),
    ("7.1", "Conclusion", None),
    ("7.2", "Future Scope", None),
    ("", "REFERENCES", "REFERENCES"),
    ("", "PUBLICATIONS AND CERTIFICATES", "PUBLICATIONS AND CERTIFICATES"),
]

#: Written where a page number is not yet known.
PAGE_TBD = "–"


def write_toc(doc, pages=None):
    """Replace the template's stub contents list with the real one."""
    pages = pages or {}
    paragraphs = doc.paragraphs
    start = next(i for i, p in enumerate(paragraphs)
                 if p.text.strip() == "TABLE OF CONTENTS")
    stop = next(i for i, p in enumerate(paragraphs)
                if i > start and p.text.strip() == "LIST OF FIGURES")

    anchor = paragraphs[start]._element
    for p in paragraphs[start + 1:stop]:
        if p.text.strip():
            p._element.getparent().remove(p._element)

    header = doc.add_paragraph(style="Normal")
    header.paragraph_format.space_before = Pt(8)
    header.paragraph_format.space_after = Pt(8)
    set_font(header.add_run("CHAPTER NO."), size=12, bold=True)
    set_font(header.add_run("	"), size=12)
    set_font(header.add_run("TITLE"), size=12, bold=True)
    set_font(header.add_run("	"), size=12)
    set_font(header.add_run("PAGE NO."), size=12, bold=True)
    # Past the width of "CHAPTER NO." itself, or the first tab skips to the
    # right-hand stop and TITLE lands against PAGE NO.
    header.paragraph_format.tab_stops.add_tab_stop(
        Inches(1.60), WD_TAB_ALIGNMENT.LEFT)
    header.paragraph_format.tab_stops.add_tab_stop(
        Inches(6.45), WD_TAB_ALIGNMENT.RIGHT)
    anchor.addnext(header._element)
    prev = header._element

    for number, title, key in TOC_ENTRIES:
        chapter_level = key is not None
        p = doc.add_paragraph(style="Normal")
        pf = p.paragraph_format
        pf.space_after = Pt(3)
        pf.left_indent = Inches(0.0 if chapter_level else 0.30)
        pf.tab_stops.add_tab_stop(Inches(0.95), WD_TAB_ALIGNMENT.LEFT)
        pf.tab_stops.add_tab_stop(Inches(6.45), WD_TAB_ALIGNMENT.RIGHT,
                                  WD_TAB_LEADER.DOTS)
        set_font(p.add_run(number), size=12, bold=chapter_level)
        set_font(p.add_run("	"), size=12)
        set_font(p.add_run(title), size=12, bold=chapter_level)
        set_font(p.add_run("	"), size=12)
        page = pages.get(key or title, PAGE_TBD)
        set_font(p.add_run(str(page)), size=12, bold=chapter_level)
        prev.addnext(p._element)
        prev = p._element


# ------------------------------------------------------------------ build --
def main(pages=None) -> None:
    doc = Document(str(TEMPLATE))

    # -- 1. Title placeholders -------------------------------------------
    for placeholder in (
        "<--------------------------------------------------->",
        "<\u201cTitle of Project\u201d>",
        "<Title of Project>",
    ):
        replace_everywhere(doc, placeholder, TITLE)

    # The template's title line carried no alignment, so the replacement
    # sat left of the rest of the page furniture.
    for p in doc.paragraphs[:20]:
        if p.text.strip() == TITLE:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            break

    write_toc(doc, pages)

    # -- 2. Abstract ------------------------------------------------------
    abstract_text = (
        "Public environmental data for Indian waters is abundant but rarely "
        "usable as evidence. Measurements arrive from different authorities "
        "on different schedules, satellite indices are published without the "
        "thresholds needed to act on them, and dashboards routinely present "
        "a five-year-old laboratory sample and a model's guess in the same "
        "typeface. The reader cannot tell which is which, so neither can be "
        "trusted.",

        "OceanAI is a monitoring platform built on the opposite premise: "
        "that a system is more useful when it states what it does not know. "
        "It ingests 4,601,509 water-quality measurements from the Central "
        "Pollution Control Board and the Central Water Commission across "
        "2,740 water bodies, and twelve months of Copernicus Sentinel-2 "
        "Level-2A imagery over 36 cells of India's exclusive economic zone. "
        "Every stored value carries an evidence level, the instrument that "
        "produced it and the time it was measured, and the interface refuses "
        "to describe present condition from a sample too old to support it.",

        "Marine detections are raised only where a spectral index is both a "
        "statistical anomaly against its own region's twelve-month "
        "distribution and past an absolute floor taken from published "
        "literature. Where no citable floor exists the detection is labelled "
        "a relative anomaly and nothing stronger is claimed. A "
        "convolutional classifier screens Sentinel-1 synthetic aperture "
        "radar tiles for dark formations; pointed at a documented oil spill "
        "it did not find it, and that negative result is published together "
        "with the physical reasons it is weak evidence rather than withheld.",

        "The implemented system comprises a FastAPI service over PostgreSQL "
        "with PostGIS, a React dashboard of 23 pages, and 868 automated "
        "tests. It demonstrates that an evidence-grounded design is "
        "practical at this scale, and that refusing to answer is a reportable "
        "result rather than a failure.",
    )
    for i, p in enumerate(doc.paragraphs):
        if p.text.strip() == "ABSTRACT":
            anchor = p
            break
    else:
        raise SystemExit("ABSTRACT heading not found")

    prev = anchor._element
    for text in abstract_text:
        new = doc.add_paragraph(style="Normal")
        new.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        new.paragraph_format.space_after = Pt(8)
        set_font(new.add_run(text), size=12)
        prev.addnext(new._element)
        prev = new._element

    kw = doc.add_paragraph(style="Normal")
    kw.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    kw.paragraph_format.space_before = Pt(6)
    set_font(kw.add_run("Keywords: "), size=12, bold=True)
    set_font(kw.add_run(
        "water quality monitoring; Sentinel-1; Sentinel-2; synthetic "
        "aperture radar; spectral indices; evidence grounding; anomaly "
        "detection; marine pollution."), size=12)
    prev.addnext(kw._element)

    # -- 3. Lists and abbreviations --------------------------------------
    figures_tbl, tables_tbl, abbrev_tbl = doc.tables[2], doc.tables[3], doc.tables[4]

    pg = (pages or {}).get
    fill_grid(figures_tbl, [
        ("1", "Fig. 5.1  Use case diagram of the OceanAI platform",
         str(pg("Fig. 5.1", PAGE_TBD))),
        ("2", "Fig. 5.2  Class diagram of the core persistent entities",
         str(pg("Fig. 5.2", PAGE_TBD))),
        ("3", "Fig. 5.3  Level-1 data flow diagram",
         str(pg("Fig. 5.3", PAGE_TBD))),
        ("4", "Fig. 6.1  Gantt chart of the project schedule",
         str(pg("Fig. 6.1", PAGE_TBD))),
    ])
    fill_grid(tables_tbl, [
        ("1", "Table 2.1  Comparative analysis of existing methodologies",
         str(pg("Table 2.1", PAGE_TBD))),
        ("2", "Table 4.1  Hardware and software requirements",
         str(pg("Table 4.1", PAGE_TBD))),
        ("3", "Table 5.1  Detection criteria applied to each spectral index",
         str(pg("Table 5.1", PAGE_TBD))),
        ("4", "Table 6.1  Project milestones and deliverables",
         str(pg("Table 6.1", PAGE_TBD))),
    ])
    fill_grid(abbrev_tbl, [
        ("AIS", "Automatic Identification System"),
        ("API", "Application Programming Interface"),
        ("CPCB", "Central Pollution Control Board"),
        ("CWC", "Central Water Commission"),
        ("EEZ", "Exclusive Economic Zone"),
        ("FDI", "Floating Debris Index"),
        ("GFW", "Global Fishing Watch"),
        ("GRD", "Ground Range Detected (Sentinel-1 product level)"),
        ("L2A", "Level-2A (atmospherically corrected Sentinel-2 product)"),
        ("NDCI", "Normalized Difference Chlorophyll Index"),
        ("NDTI", "Normalized Difference Turbidity Index"),
        ("NWDP", "National Water Data Portal"),
        ("PSI", "Population Stability Index"),
        ("RAG", "Retrieval-Augmented Generation"),
        ("SAR", "Synthetic Aperture Radar"),
        ("SCL", "Scene Classification Layer"),
    ])

    # -- 4. Replace the template's stub chapter with the real body -------
    bodyel = doc.element.body
    children = list(bodyel.iterchildren())
    for child in children:
        text = "".join(child.itertext()) if child.tag.endswith("}p") else ""
        if "1.INTRODUCTION" in text or "Follow same format for other chapters" in text:
            bodyel.remove(child)
    # Trailing empty paragraphs the stub left behind.
    for child in list(bodyel.iterchildren())[-4:]:
        if child.tag.endswith("}p") and not "".join(child.itertext()).strip():
            bodyel.remove(child)

    write_chapters(doc)

    doc.save(str(OUT))
    print("written:", OUT)


def write_chapters(doc) -> None:
    """Chapters 1-7, references and the publications page."""

    # ================================================== 1. INTRODUCTION ==
    chapter(doc, 1, "INTRODUCTION", page_break=False)

    section(doc, "1.1", "Background")
    body(doc,
         "India monitors its surface water through two national programmes. "
         "The Central Pollution Control Board (CPCB) operates a manual "
         "sampling network and a smaller set of real-time analysers, while "
         "the Central Water Commission (CWC) maintains its own gauging and "
         "sampling stations on the major river systems. Between them they "
         "have produced several million parameter measurements, published "
         "through the National Water Data Portal. Separately, the European "
         "Union's Copernicus programme distributes Sentinel-1 synthetic "
         "aperture radar and Sentinel-2 multispectral imagery over Indian "
         "waters free of charge, on a revisit cycle of a few days.")
    body(doc,
         "The data therefore exists. What is scarce is a way to read it "
         "honestly. The two in-situ programmes sample on different "
         "schedules and report different parameter sets, so a single "
         "averaged figure for a river conceals which instrument measured "
         "what and when. Satellite spectral indices are published in the "
         "remote-sensing literature as relationships, not as operational "
         "thresholds, so a value computed over Indian coastal water cannot "
         "be converted into a verdict without a calibration that usually "
         "does not exist for that region. The result is that most public "
         "dashboards show a colour-coded status with no date attached to it, "
         "and the reader has no way to tell a laboratory measurement from "
         "an interpolation.")

    section(doc, "1.2", "Motivation")
    body(doc,
         "The failure mode that motivates this project is specific and "
         "common: a system presents a derived number with the same "
         "confidence as a measured one. A chlorophyll index computed from "
         "a partly clouded satellite scene, a five-year-old laboratory "
         "sample and a model's forecast all render as the same green or red "
         "badge. Because the interface cannot distinguish them, the reader "
         "learns to distrust all three, and the measurement loses the "
         "authority it had earned.")
    body(doc,
         "An environmental monitoring system is read by people who may act "
         "on it, so the cost of an unsupported claim is not symmetrical "
         "with the cost of silence. Reporting that a water body's condition "
         "cannot be established from the available data is a useful "
         "statement. Reporting a condition that the data does not support "
         "is not. This project treats that asymmetry as a design "
         "requirement rather than a caveat in a footnote.")

    section(doc, "1.3", "Objectives")
    for text in (
        "To ingest, validate and reconcile national water-quality data from "
        "CPCB and CWC without merging sources, preserving for every value "
        "its originating programme, station and measurement time.",
        "To compute established spectral indices from Copernicus Sentinel-2 "
        "Level-2A imagery over India's exclusive economic zone, restricted "
        "to pixels the scene classification layer identifies as water.",
        "To raise a detection only when a reading satisfies two independent "
        "criteria \u2014 a statistical anomaly against its own region's "
        "twelve-month distribution, and an absolute floor drawn from "
        "published literature \u2014 and to label it honestly when only the "
        "first is available.",
        "To screen Sentinel-1 synthetic aperture radar tiles for dark "
        "formations using a convolutional classifier, and to report the "
        "result of testing that classifier against a documented real spill "
        "whether or not the result is favourable.",
        "To attach an explicit evidence level and measurement time to every "
        "stored value, and to design the interface so that it refuses to "
        "describe present condition from data too old to support it.",
        "To deliver the whole system as a reproducible, tested application "
        "with its data provenance and attribution visible to the user.",
    ):
        bullet(doc, text)

    section(doc, "1.4", "Scope of the Work")
    body(doc,
         "The work covers ingestion, storage, analysis and presentation for "
         "Indian inland surface water and for 15 marine regions subdivided "
         "into 40 monitoring cells across India's exclusive economic zone. "
         "It covers optical index computation, radar screening, "
         "deterministic risk scoring, time-series forecasting with an "
         "honest baseline comparison, and retrieval-based question "
         "answering over the ingested corpus.")
    body(doc,
         "It does not extend to operational alerting of authorities, to "
         "real-time ingestion on a fixed schedule, or to legal "
         "determination of responsibility for any detected event. The "
         "marine radar classifier is trained on a published Mediterranean "
         "benchmark and is explicitly not calibrated for Indian waters; the "
         "system reports this rather than extrapolating its accuracy. "
         "These boundaries are stated in Section 7.2 as future work.")

    # ============================================== 2. LITERATURE SURVEY ==
    chapter(doc, 2, "LITERATURE SURVEY")

    section(doc, "2.1", "Introduction")
    body(doc,
         "The survey covers five areas the system depends on: optical "
         "spectral indices for water constituents, radar detection of "
         "surface films, vessel-activity data derived from automatic "
         "identification signals, Lagrangian drift modelling, and the "
         "classification framework used by Indian regulators. The purpose "
         "is less to find the most accurate published method than to "
         "establish, for each one, what it licenses a system to claim.")

    section(doc, "2.2", "Existing Methodologies")

    para(doc, "2.2.1  Optical spectral indices", size=12, bold=True,
         space_before=8, space_after=4, keep_with_next=True)
    body(doc,
         "Mishra and Mishra [1] introduced the Normalized Difference "
         "Chlorophyll Index (NDCI) for estimating chlorophyll-a in turbid "
         "productive coastal waters, using the red-edge and red bands. "
         "Calibrated against MERIS data the index reached a coefficient of "
         "determination near 0.9, but the authors are explicit that the "
         "regression is local: the index ranks chlorophyll reliably and "
         "flags blooms, while an absolute concentration requires regional "
         "calibration. Lacaux et al. [2] defined the Normalized Difference "
         "Turbidity Index (NDTI) from the red and green bands while mapping "
         "pond turbidity in the Ferlo region of Senegal for Rift Valley "
         "fever vector habitat; the sign convention, rather than any "
         "published numeric level, is what transfers to other waters.")
    body(doc,
         "Biermann et al. [3] proposed the Floating Debris Index (FDI), "
         "built on the near-infrared band against a baseline interpolated "
         "from the red-edge and short-wave infrared bands, and demonstrated "
         "separation of floating material from water in Sentinel-2 imagery. "
         "An important negative detail governs this project's use of it: "
         "the paper publishes no absolute threshold. Classification is "
         "performed by a Naive Bayes model over FDI together with NDVI, so "
         "there is no citable floor above which an FDI value may be called "
         "floating debris. Kikaki et al. [4] later released MARIDA, a "
         "Sentinel-2 benchmark that annotates marine debris against "
         "confusable classes such as Sargassum, ships and foam, which is "
         "the resource a trained classifier would need to replace a "
         "threshold.")

    para(doc, "2.2.2  Radar detection of surface films", size=12, bold=True,
         space_before=8, space_after=4, keep_with_next=True)
    body(doc,
         "Solberg [5] surveys the physics and practice of oil-spill remote "
         "sensing and sets out the central difficulty: oil damps capillary "
         "waves and so appears dark in synthetic aperture radar, but so do "
         "biogenic films, rain cells and, above all, low wind. Below "
         "roughly 3 m/s the sea surface is naturally flat and a dark "
         "formation carries little information. Krestenitis et al. [6] "
         "applied deep convolutional semantic segmentation to this problem "
         "and released a labelled SAR dataset so that detectors could be "
         "compared. Yang and Singha [7] published the benchmark used here "
         "as PANGAEA dataset 980773: Sentinel-1 patches over the Eastern "
         "Mediterranean, annotated at object level, with a deliberately "
         "large set of look-alike patches alongside the oil set.")
    body(doc,
         "Two consequences follow for any system built on these methods. "
         "First, wind speed at acquisition time is not optional metadata; "
         "it determines whether a detection means anything. Second, a "
         "detector trained on one sea does not automatically transfer to "
         "another, because backscatter statistics differ with sensor "
         "configuration, sea state and preprocessing.")

    para(doc, "2.2.3  Vessel activity and drift", size=12, bold=True,
         space_before=8, space_after=4, keep_with_next=True)
    body(doc,
         "Kroodsma et al. [8] reconstructed global fishing effort from "
         "automatic identification system broadcasts, establishing that "
         "vessel-derived activity can be aggregated into a reliable "
         "spatial picture of how heavily a body of water is used. The same "
         "work makes clear that the activity is inferred from a track by a "
         "model rather than reported by the vessel, which is why this "
         "project treats such data as context and never as attribution. "
         "Dagestad et al. [9] describe OpenDrift, the open Lagrangian "
         "framework that establishes the standard approach to trajectory "
         "modelling of a surface release under forcing from currents and "
         "wind; its design is the reference for the drift projection "
         "implemented here.")

    para(doc, "2.2.4  Regulatory classification in India", size=12,
         bold=True, space_before=8, space_after=4, keep_with_next=True)
    body(doc,
         "The Central Pollution Control Board [10] classifies inland "
         "surface waters into five categories, A to E, on the principle of "
         "designated best use: the use demanding the highest quality that a "
         "given water body is expected to support. Class A is a drinking "
         "water source requiring only disinfection, Class B organised "
         "outdoor bathing, Class C a drinking water source after "
         "conventional treatment, Class D propagation of wildlife and "
         "fisheries, and Class E irrigation, industrial cooling and "
         "controlled waste disposal. Each class carries its own numeric "
         "criteria for parameters such as dissolved oxygen, biochemical "
         "oxygen demand, pH and total coliform. This matters to the design "
         "because a measurement is only meaningful against the standard "
         "that applies to that water body's designated use, which is why "
         "the system records the standard it compared against rather than "
         "applying one universal limit.")

    section(doc, "2.3", "Comparative Analysis")
    body(doc,
         "Table 2.1 compares the methods on the question that determines "
         "how each may be used in an operational system: what a value "
         "licenses the system to claim on its own.")
    table(doc, "Table 2.1  Comparative analysis of existing methodologies",
          ["Method / source", "Input", "Strength", "Limitation for operational use"],
          [
              ("NDCI \u2014 Mishra & Mishra [1]",
               "Sentinel-2 B05, B04",
               "Robust ranking of chlorophyll-a in turbid Case-2 water; "
               "flags blooms without ground truth",
               "Absolute concentration needs regional calibration; a "
               "literature threshold is indicative, not a limit"),
              ("NDTI \u2014 Lacaux et al. [2]",
               "Sentinel-2 B04, B03",
               "Simple, sensor-portable turbidity contrast",
               "Published levels are local calibrations from Senegalese "
               "ponds; only the sign convention transfers"),
              ("FDI \u2014 Biermann et al. [3]",
               "Sentinel-2 B08, B06, B11",
               "Separates floating material from open water",
               "No absolute threshold is published; classification uses "
               "Naive Bayes over FDI and NDVI"),
              ("MARIDA \u2014 Kikaki et al. [4]",
               "Sentinel-2, labelled",
               "Benchmark distinguishing debris from Sargassum, ships, foam",
               "Requires a trained classifier; not a threshold rule"),
              ("SAR segmentation \u2014 Krestenitis et al. [6]",
               "Sentinel-1 GRD",
               "End-to-end learned detector with a public benchmark",
               "Accuracy measured on the training sea; does not transfer "
               "unchanged to another region"),
              ("PANGAEA 980773 \u2014 Yang & Singha [7]",
               "Sentinel-1, E. Mediterranean",
               "Object-level annotation with a large look-alike set",
               "Mediterranean acquisition geometry and sea state; not "
               "Indian waters"),
              ("AIS effort \u2014 Kroodsma et al. [8]",
               "AIS broadcasts",
               "Reliable aggregate picture of how heavily water is used",
               "Activity is model-inferred from a track; cannot attribute "
               "an event to a vessel"),
              ("OpenDrift \u2014 Dagestad et al. [9]",
               "Currents, wind",
               "Standard Lagrangian trajectory framework",
               "Output is a projection under an assumed release, not an "
               "observation"),
          ],
          widths=[1.45, 1.05, 1.9, 2.2], font_size=9.5)

    # ============================================== 3. PROBLEM STATEMENT ==
    chapter(doc, 3, "PROBLEM STATEMENT")
    body(doc,
         "Public water and marine monitoring systems present measured "
         "values, derived indices and model outputs in a single undated, "
         "undifferentiated view. A reader cannot determine which figures "
         "rest on an instrument reading, which on a satellite index whose "
         "operational threshold was never established for that region, and "
         "which on an interpolation across a gap in the record. Because "
         "every figure is presented with equal confidence, the reliable "
         "ones inherit the unreliability of the rest.")
    body(doc,
         "Two specific gaps follow from the literature. First, the spectral "
         "indices available for Indian coastal water are published as "
         "relationships rather than as limits; applying one global cut-off "
         "to them flags naturally turbid coastal cells permanently while "
         "missing genuine anomalies elsewhere. Second, radar oil-spill "
         "detectors report accuracy measured on the sea they were trained "
         "on, and that figure is routinely carried over to a different "
         "region where it has not been established.")
    body(doc,
         "The problem this project addresses is therefore to design and "
         "implement an integrated monitoring platform that fuses national "
         "in-situ water-quality data with Copernicus satellite "
         "observations, and that attaches to every value an explicit "
         "evidence level, an acquisition time and a named source \u2014 such "
         "that the system states the limits of what it can support, "
         "declines to describe conditions it cannot, and reports a negative "
         "validation result as readily as a positive one.")

    # ================================================= 4. SYSTEM ANALYSIS ==
    chapter(doc, 4, "SYSTEM ANALYSIS")

    section(doc, "4.1", "Existing System and its Limitations")
    body(doc,
         "The present arrangement is a set of separate portals. CPCB and "
         "CWC publish station data through the National Water Data Portal "
         "as periodic extracts; Copernicus distributes imagery through its "
         "own data space; weather and ocean forecast products come from "
         "further services. An analyst wishing to relate a satellite "
         "observation to a ground measurement must download from each, "
         "reconcile station identities by hand, and keep track mentally of "
         "which figure came from where.")
    for text in (
        "Measurement time is not surfaced with the value, so a current "
        "reading and a five-year-old sample are presented identically.",
        "Sources are averaged or silently preferred, which destroys the "
        "information that two programmes disagreed.",
        "Satellite indices are offered as raw values with no stated basis "
        "for deciding whether a value is unusual for that location.",
        "Model outputs and measurements share a visual language, so a "
        "forecast is read with the authority of an observation.",
        "Provenance and licence attribution are typically absent, making "
        "a figure impossible to audit back to its source.",
    ):
        bullet(doc, text)

    section(doc, "4.2", "Proposed System")
    body(doc,
         "The proposed system is a single application over one "
         "spatially-enabled database, in which provenance is a stored "
         "property of every row rather than a presentation choice. Four "
         "design rules define it.")
    for text in (
        "An evidence ladder. Every value is stored with one of OBSERVED, "
        "MEASURED, DETECTED, INFERRED, FORECAST or RETRIEVED, and the "
        "interface renders each tier distinctly.",
        "A refusal horizon. A water body whose newest reading is older "
        "than its source's own cadence is described by when it was last "
        "measured, never by what that measurement showed.",
        "Dual detection criteria. A marine detection requires both a "
        "regional statistical anomaly and an absolute floor from "
        "literature; where no floor is citable the detection is labelled a "
        "relative anomaly only.",
        "Separation of ingestion from serving. Scheduled jobs write to the "
        "database; the application only reads, so a freshly started "
        "instance serves what was produced and never fetches on request.",
    ):
        bullet(doc, text)

    section(doc, "4.3", "Functional Requirements")
    for text in (
        "Ingest and normalise CPCB and CWC station data, preserving source "
        "identity, station, parameter, unit and measurement time.",
        "Retrieve Sentinel-2 Level-2A reflectance and the scene "
        "classification layer for a given location and date window, and "
        "compute NDCI, NDTI and FDI over water pixels only.",
        "Maintain a twelve-month per-region baseline and evaluate each new "
        "reading against both that baseline and a literature floor.",
        "Screen Sentinel-1 ground-range-detected tiles with the "
        "convolutional classifier and record the score with the wind speed "
        "at acquisition.",
        "Record analyst review decisions as an append-only audit trail.",
        "Answer natural-language questions by retrieval over the ingested "
        "corpus, returning citations, and refuse when the corpus does not "
        "support an answer.",
        "Expose the freshness, record count and licence attribution of "
        "every external data source.",
    ):
        bullet(doc, text)

    section(doc, "4.4", "Non-Functional Requirements")
    for text in (
        "Reproducibility: the application must start from a database dump "
        "and serve identical figures without network access.",
        "Auditability: every displayed figure must be traceable to a "
        "stored row with its source and time.",
        "Correctness under absence: a missing or stale input must produce "
        "an explicit statement of absence, never a substituted value.",
        "Performance: interactive pages should render within about two "
        "seconds against the full four-million-row dataset.",
        "Security: credentials are held only in environment configuration "
        "and are never logged, printed or committed.",
        "Testability: behaviour is covered by an automated suite that runs "
        "without external network calls.",
    ):
        bullet(doc, text)

    section(doc, "4.5", "Hardware and Software Requirements")
    table(doc, "Table 4.1  Hardware and software requirements",
          ["Category", "Requirement"],
          [
              ("Processor", "x86-64, 4 cores or more"),
              ("Memory", "8 GB RAM minimum, 16 GB recommended for ingestion jobs"),
              ("Storage", "40 GB free (database, cached scenes, benchmark imagery)"),
              ("Operating system", "Windows 11 / Linux, with Docker Desktop or Docker Engine"),
              ("Backend", "Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic"),
              ("Database", "PostgreSQL 16 with the PostGIS 3.4 extension"),
              ("Frontend", "React 18, TypeScript, Vite, Leaflet, Recharts"),
              ("Machine learning", "PyTorch (convolutional SAR classifier), NumPy, Pillow"),
              ("External services",
               "Copernicus Data Space Ecosystem, Copernicus Marine Service, "
               "Open-Meteo, Global Fishing Watch"),
              ("Testing", "pytest; the suite runs without external network access"),
          ],
          widths=[1.7, 4.9], font_size=10.5)

    section(doc, "4.6", "Feasibility Study")
    body(doc,
         "Technical feasibility is established by the working "
         "implementation: the platform runs as a containerised service "
         "against a PostgreSQL and PostGIS database holding 4,601,509 "
         "water observations and 3,006 satellite index readings, with 868 "
         "automated tests passing. Economic feasibility follows from the "
         "input data being free at the point of use \u2014 CPCB and CWC "
         "extracts, Copernicus Sentinel imagery, Copernicus Marine "
         "products, Open-Meteo forecasts and Global Fishing Watch activity "
         "are all public, and the system runs on a single commodity "
         "machine. Operational feasibility is bounded honestly: the "
         "ingestion jobs are presently run manually rather than on a "
         "scheduler, and that limitation is recorded as future work rather "
         "than described as complete.")

    # ================================================== 5. SYSTEM DESIGN ==
    chapter(doc, 5, "SYSTEM DESIGN")

    section(doc, "5.1", "Architectural Overview")
    body(doc,
         "The system is organised in four layers. An ingestion layer of "
         "scheduled jobs fetches, validates and normalises external data, "
         "caching every external response to disk so that a demonstration "
         "never depends on a live call. A storage layer holds observations, "
         "geometry and derived events in PostgreSQL with PostGIS. An "
         "analysis layer computes spectral indices, screens radar tiles, "
         "raises detections, scores risk deterministically and produces "
         "forecasts. A presentation layer exposes a versioned REST API and "
         "serves a React dashboard of 23 pages from the same origin.")
    body(doc,
         "The separation between the first and last layers is enforced "
         "rather than conventional: the serving process performs no "
         "ingestion, so its behaviour is a function of the database "
         "contents alone. This is what makes the system reproducible from "
         "a dump.")

    section(doc, "5.2", "Design Model \u2014 Use Case Diagram")
    body(doc,
         "Figure 5.1 shows the actors and the use cases the API exposes. "
         "The reviewer generalises the viewer: every case available to a "
         "viewer is available to a reviewer, while recording a decision and "
         "running an analysis are restricted to the reviewer. The scheduled "
         "ingestion job and the external providers are modelled as actors "
         "because the data they supply, and the freshness of it, is visible "
         "to the user as a first-class part of the system.")
    figure(doc, "fig_5_1_use_case.png",
           "Fig. 5.1  Use case diagram of the OceanAI platform")

    section(doc, "5.3", "Class Diagram (Detailed Design)")
    body(doc,
         "Figure 5.2 shows the core persistent entities. Two properties of "
         "the model are deliberate. First, every observation entity carries "
         "an evidence level and a measurement timestamp, so provenance "
         "cannot be lost between the database and the screen. Second, only "
         "relationships that exist as declared foreign keys are drawn: "
         "there is no association between the radar candidate cluster and "
         "the monitoring regions, because the candidate table declares "
         "none. Drawing one would assert a link the database does not hold, "
         "which is precisely what the system's knowledge graph is built to "
         "refuse. The comparison of an observation against a reference "
         "standard is shown as a dependency rather than an association, "
         "since it is applied by rule at query time.")
    figure(doc, "fig_5_2_class.png",
           "Fig. 5.2  Class diagram of the core persistent entities",
           width=5.25)

    section(doc, "5.4", "Function Specification \u2014 Data Flow Diagram")
    body(doc,
         "Figure 5.3 gives the level-1 data flow. Processes 1.0 and 2.0 are "
         "the scheduled jobs; process 5.0, which serves the API and the "
         "dashboard, only reads from the database. Every external payload "
         "is written to a response cache (D2) as well as being processed, "
         "so the system can be demonstrated and tested with the network "
         "removed.")
    figure(doc, "fig_5_3_dfd.png",
           "Fig. 5.3  Level-1 data flow diagram")

    section(doc, "5.5", "Detection Methodology")
    body(doc,
         "A detection is raised only where two independent conditions hold. "
         "The first is statistical: the reading must fall in the top one "
         "per cent of that region's own distribution over the preceding "
         "twelve months, computed per region rather than globally so that a "
         "naturally turbid coastal cell is not flagged permanently. The "
         "second is physical: the reading must also exceed an absolute "
         "floor taken from published literature.")
    body(doc,
         "Where the literature publishes no floor, the system does not "
         "invent one. As established in Section 2.2.1, Biermann et al. [3] "
         "publish no FDI threshold, so floating-material detections satisfy "
         "the statistical criterion alone and are labelled \u201crelative "
         "anomaly only\u201d wherever they appear. Table 5.1 states the "
         "criteria applied to each index.")
    table(doc, "Table 5.1  Detection criteria applied to each spectral index",
          ["Index", "Bands", "Statistical criterion", "Absolute floor", "Source of floor"],
          [
              ("NDCI", "B05, B04",
               "Top 1% of the region's 12-month distribution",
               "0.08", "Literature-based bloom level [1]"),
              ("NDTI", "B04, B03",
               "Top 1% of the region's 12-month distribution",
               "0.0", "Sign convention of Lacaux et al. [2]"),
              ("FDI", "B08, B06, B11",
               "Top 1% of the region's 12-month distribution",
               "none",
               "No threshold is published [3]; labelled relative anomaly only"),
          ],
          widths=[0.75, 1.0, 2.1, 0.85, 1.9], font_size=10)
    body(doc,
         "A minimum of 40 baseline readings and 100 valid water pixels is "
         "required before either criterion is evaluated, so that an "
         "anomaly is never declared against a distribution too small to "
         "describe. Detections are presented as statistical anomalies "
         "against a regional baseline and never as confirmed pollution "
         "incidents; the severity shown alongside one is defined in the "
         "interface as potential impact if confirmed, not as certainty "
         "that an incident occurred.")

    # ================================================ 6. PROJECT TIMELINE ==
    chapter(doc, 6, "PROJECT TIMELINE")

    section(doc, "6.1", "Gantt Chart")
    body(doc,
         "Figure 6.1 shows the schedule across four phases. The dates are "
         "the project's actual working windows rather than a plan drawn "
         "after the fact. Phases overlap where a later activity could begin "
         "before the previous one closed \u2014 geometry import started while "
         "ingestion was still being hardened, and the radar calibration work "
         "ran alongside the real-data migration.")
    figure(doc, "fig_6_1_gantt.png",
           "Fig. 6.1  Gantt chart of the project schedule")

    section(doc, "6.2", "Milestones and Deliverables")
    table(doc, "Table 6.1  Project milestones and deliverables",
          ["Phase", "Period", "Milestone", "Deliverable"],
          [
              ("1 \u2014 Foundation", "07 Sep \u2013 12 Oct 2026",
               "Water data model, national ingestion, geometry, status engine",
               "4.6 M observations across 2,740 water bodies; evidence ladder"),
              ("2 \u2014 Detection and models", "06 Oct \u2013 08 Nov 2026",
               "SAR benchmark, convolutional classifier, triage funnel, "
               "risk and forecasting",
               "306 benchmark candidates; measured model metrics; "
               "deterministic risk engine"),
              ("3 \u2014 Intelligence and real data", "01 \u2013 22 Nov 2026",
               "Retrieval question answering, migration to real data, "
               "Sentinel-1 calibration",
               "3,006 index readings; 108 detections; incident replay result"),
              ("4 \u2014 Verification and delivery", "20 \u2013 25 Nov 2026",
               "Full verification, code freeze, documentation",
               "868 tests passing; synopsis, presentation and demonstration"),
          ],
          widths=[1.25, 1.3, 2.0, 2.05], font_size=9.5)

    # ====================================== 7. CONCLUSION AND FUTURE SCOPE ==
    chapter(doc, 7, "CONCLUSION AND FUTURE SCOPE")

    section(doc, "7.1", "Conclusion")
    body(doc,
         "The project delivers a working, tested monitoring platform that "
         "treats provenance as data rather than as presentation. It holds "
         "4,601,509 in-situ water-quality measurements across 2,740 water "
         "bodies, 4,951 stations and 35 states, together with 3,006 "
         "Sentinel-2 index readings spanning twelve months over 36 marine "
         "cells. From those readings it raises 108 detections \u2014 41 "
         "floating material, 35 algal bloom and 32 turbidity \u2014 each "
         "satisfying both a per-region statistical criterion and, where one "
         "is citable, an absolute floor from literature. The implementation "
         "comprises a FastAPI service, a PostgreSQL and PostGIS database, a "
         "23-page React dashboard and 868 automated tests.")
    body(doc,
         "Three results are worth stating plainly because they are "
         "negative. The Sentinel-1 classifier, pointed at the documented "
         "sinking of the MSC ELSA 3 off the Kerala coast on 25 May 2025, "
         "found nothing across four satellite passes; the result is "
         "published together with the physical reasons it is weak evidence "
         "\u2014 the first pass came three days later into a 9.3 m/s wind "
         "that roughens the sea enough to suppress slick contrast, "
         "dispersant had been applied, and the model is operating outside "
         "the distribution it was trained on. The forecasting component "
         "beats a naive baseline in none of the 40 regions, and reports "
         "that on every chart rather than omitting the comparison. Drift "
         "monitoring reports a warning state that has not been tuned away. "
         "A system that reported only its successes would have shown none "
         "of these, and would have been less informative for it.")

    section(doc, "7.2", "Future Scope")
    for text in (
        "Retraining the radar classifier on calibrated backscatter from "
        "Indian waters. Prepared tiles presently average about 34 "
        "brightness units darker than the training patches, so measured "
        "accuracy does not transfer. This is the single highest-value "
        "improvement and requires a labelled Sentinel-1 set over the "
        "Indian exclusive economic zone.",
        "Replacing the floating-material percentile with a classifier "
        "trained on the MARIDA benchmark [4], which would give "
        "floating-material detections the absolute criterion that the "
        "literature currently cannot supply.",
        "Integrating World Database on Protected Areas boundaries in place "
        "of the curated receptor centroids now used, so that proximity to "
        "large reserves is not understated in the risk score.",
        "Automating ingestion on a scheduler, and adding an alerting path "
        "to the relevant authority, so that a detection reaches a person "
        "rather than only a dashboard.",
        "Extending forecasting to the in-situ water series, which requires "
        "the daily-bucket aggregation to be reworked for a different "
        "sampling cadence.",
        "Restoring automated access to the National Water Data Portal "
        "feeds, which currently refuse automated clients at the network "
        "layer; this requires an arrangement with the data custodian "
        "rather than a technical workaround.",
    ):
        bullet(doc, text)

    # ===================================================== REFERENCES ====
    chapter(doc, "", "REFERENCES")
    refs = [
        "D. Mishra and S. Mishra, \u201cNormalized difference chlorophyll "
        "index: A novel model for remote estimation of chlorophyll-a "
        "concentration in turbid productive waters,\u201d Remote Sensing of "
        "Environment, vol. 117, pp. 394\u2013406, 2012. "
        "doi:10.1016/j.rse.2011.10.016",

        "J. P. Lacaux, Y. M. Tourre, C. Vignolles, J. A. Ndione and M. "
        "Lafaye, \u201cClassification of ponds from high-spatial resolution "
        "remote sensing: Application to Rift Valley Fever epidemics in "
        "Senegal,\u201d Remote Sensing of Environment, vol. 106, no. 1, pp. "
        "66\u201374, 2007.",

        "L. Biermann, D. Clewley, V. Martinez-Vicente and K. Topouzelis, "
        "\u201cFinding Plastic Patches in Coastal Waters using Optical "
        "Satellite Data,\u201d Scientific Reports, vol. 10, art. 5364, 2020. "
        "doi:10.1038/s41598-020-62298-z",

        "K. Kikaki, I. Kakogeorgiou, P. Mikeli, D. E. Raitsos and K. "
        "Karantzalos, \u201cMARIDA: A benchmark for Marine Debris detection "
        "from Sentinel-2 remote sensing data,\u201d PLOS ONE, vol. 17, no. 1, "
        "e0262247, 2022. doi:10.1371/journal.pone.0262247",

        "A. H. S. Solberg, \u201cRemote Sensing of Ocean Oil-Spill "
        "Pollution,\u201d Proceedings of the IEEE, vol. 100, no. 10, pp. "
        "2931\u20132945, 2012. doi:10.1109/JPROC.2012.2196250",

        "M. Krestenitis, G. Orfanidis, K. Ioannidis, K. Avgerinakis, S. "
        "Vrochidis and I. Kompatsiaris, \u201cOil Spill Identification from "
        "Satellite Images Using Deep Neural Networks,\u201d Remote Sensing, "
        "vol. 11, no. 15, art. 1762, 2019. doi:10.3390/rs11151762",

        "Y. Yang and S. Singha, \u201cA Sentinel-1 SAR dataset of oil slicks "
        "in the Eastern Mediterranean,\u201d PANGAEA, 2025. "
        "doi:10.1594/PANGAEA.980773 (CC BY 4.0)",

        "D. A. Kroodsma et al., \u201cTracking the global footprint of "
        "fisheries,\u201d Science, vol. 359, no. 6378, pp. 904\u2013908, 2018. "
        "doi:10.1126/science.aao5646",

        "K.-F. Dagestad, J. R\u00f6hrs, \u00d8. Breivik and B. \u00c5dlandsvik, "
        "\u201cOpenDrift v1.0: a generic framework for trajectory "
        "modelling,\u201d Geoscientific Model Development, vol. 11, no. 4, "
        "pp. 1405\u20131420, 2018. doi:10.5194/gmd-11-1405-2018",

        "Central Pollution Control Board, \u201cDesignated Best Use "
        "Classification of Inland Surface Waters and Primary Water Quality "
        "Criteria,\u201d Ministry of Environment, Forest and Climate Change, "
        "Government of India. [Online]. Available: "
        "https://cpcb.nic.in/water-quality-criteria/",

        "European Union, \u201cCopernicus Sentinel-1 and Sentinel-2 mission "
        "data,\u201d Copernicus Data Space Ecosystem. Contains modified "
        "Copernicus Sentinel data (2025\u201326).",

        "E.U. Copernicus Marine Service Information, \u201cGlobal Ocean "
        "Physics Analysis and Ocean Colour products.\u201d [Online]. "
        "Available: https://marine.copernicus.eu/",
    ]
    for i, ref in enumerate(refs, start=1):
        p = doc.add_paragraph(style="Normal")
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        pf = p.paragraph_format
        pf.left_indent = Inches(0.45)
        pf.first_line_indent = Inches(-0.45)
        pf.space_after = Pt(8)
        set_font(p.add_run(f"[{i}]\t"), size=12)
        set_font(p.add_run(ref), size=12)

    # ======================================= PUBLICATIONS AND CERTIFICATES ==
    chapter(doc, "", "PUBLICATIONS AND CERTIFICATES")
    body(doc,
         "No research paper arising from this work has been submitted or "
         "accepted for publication at the time of this synopsis. This "
         "section is retained for the certificate or the front page of a "
         "research paper, to be inserted before final submission.")
    para(doc, "", space_after=6)
    para(doc, "[Insert certificate / front page of research paper here]",
         size=12, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)


if __name__ == "__main__":
    import json

    measured = HERE / "page_numbers.json"
    main(json.loads(measured.read_text("utf-8")) if measured.exists() else None)
