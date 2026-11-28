"""Read the rendered PDF and record which page each heading landed on.

The contents page, the list of figures and the list of tables all need page
numbers, and a figure's height depends on the renderer rather than on
anything this script can predict. So the document is built once with
placeholders, rendered, measured here, and built again with the result.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
PDF = HERE / "render" / "OceanAI-Synopsis.pdf"
OUT = HERE / "page_numbers.json"

#: Headings to locate, as they appear in the body (not the contents page).
HEADINGS = [
    "1. INTRODUCTION", "1.1 Background", "1.2 Motivation", "1.3 Objectives",
    "1.4 Scope of the Work",
    "2. LITERATURE SURVEY", "2.1 Introduction", "2.2 Existing Methodologies",
    "2.3 Comparative Analysis",
    "3. PROBLEM STATEMENT",
    "4. SYSTEM ANALYSIS", "4.1 Existing System and its Limitations",
    "4.2 Proposed System", "4.3 Functional Requirements",
    "4.4 Non-Functional Requirements",
    "4.5 Hardware and Software Requirements", "4.6 Feasibility Study",
    "5. SYSTEM DESIGN", "5.1 Architectural Overview",
    "5.2 Design Model — Use Case Diagram",
    "5.3 Class Diagram (Detailed Design)",
    "5.4 Function Specification — Data Flow Diagram",
    "5.5 Detection Methodology",
    "6. PROJECT TIMELINE", "6.1 Gantt Chart",
    "6.2 Milestones and Deliverables",
    "7. CONCLUSION AND FUTURE SCOPE", "7.1 Conclusion", "7.2 Future Scope",
    "REFERENCES", "PUBLICATIONS AND CERTIFICATES",
]

CAPTIONS = ["Fig. 5.1", "Fig. 5.2", "Fig. 5.3", "Fig. 6.1",
            "Table 2.1", "Table 4.1", "Table 5.1", "Table 6.1"]

#: The body starts after the front matter, so a heading's own occurrence is
#: found from here rather than from its echo on the contents page.
BODY_STARTS_AFTER = "ABBREVIATIONS"


def normalise(text: str) -> str:
    """Collapse whitespace so a line break inside a heading still matches."""
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    if not PDF.exists():
        print(f"missing {PDF}", file=sys.stderr)
        return 1

    doc = pymupdf.open(PDF)
    pages = [normalise(page.get_text()) for page in doc]

    first_body = 0
    for i, text in enumerate(pages):
        if BODY_STARTS_AFTER in text:
            first_body = i + 1
    # The contents page echoes every heading, so start the search past it.
    for i, text in enumerate(pages):
        if "TABLE OF CONTENTS" in text:
            first_body = max(first_body, i + 1)

    found: dict[str, int] = {}
    missing: list[str] = []

    for label in HEADINGS:
        needle = normalise(label)
        # The contents page reproduces "1.1 Background" too, so look only
        # at pages after the front matter.
        for i in range(first_body, len(pages)):
            if needle in pages[i]:
                key = label.split(" ", 1)[1] if label[0].isdigit() else label
                found.setdefault(key, i + 1)
                found.setdefault(label, i + 1)
                break
        else:
            missing.append(label)

    for label in CAPTIONS:
        for i in range(first_body, len(pages)):
            if label in pages[i]:
                found[label] = i + 1
                break
        else:
            missing.append(label)

    OUT.write_text(json.dumps(found, indent=2, ensure_ascii=False), "utf-8")
    print(f"measured {len(found)} entries across {doc.page_count} pages")
    if missing:
        print("NOT FOUND:", ", ".join(missing))
    for label in ("INTRODUCTION", "LITERATURE SURVEY", "PROBLEM STATEMENT",
                  "SYSTEM ANALYSIS", "SYSTEM DESIGN", "PROJECT TIMELINE",
                  "CONCLUSION AND FUTURE SCOPE", "REFERENCES"):
        print(f"  {label:32} p.{found.get(label, '?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
