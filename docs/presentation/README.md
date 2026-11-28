# Presentation and submission documents

Everything produced for the major-project submission and the demonstration
on 25 November 2026. Figures were drawn from this codebase; every number
quoted was read from the running application or its database, and the date
it was read is printed in each document.

## What is here

| File | What it is |
|---|---|
| `OceanAI-Synopsis.docx` / `.pdf` | The 24-page synopsis, built on the department's template. Chapters 1–7, references, four generated figures. |
| `OceanAI-Presentation.pptx` / `.pdf` | The 13-slide college presentation, built on the department's template. |
| `OceanAI-Demo.pptx` / `.pdf` | The 19-slide live-demonstration deck, with screenshots of the running application. |
| `OceanAI-Terms-Explained.pdf` / `.docx` | 21 pages, 89 terms, divided by the four modules the team presents. |
| `OceanAI-Page-by-Page-Guide.pdf` / `.docx` | 40 pages: a primer plus all 21 application pages — what each does, how it works, and every term on it. |
| `figures/` | The four synopsis diagrams plus a landscape class diagram for the deck. |
| `generators/` | The scripts that produce the figures and the two written guides. |

**The synopsis and the college presentation still carry the template's
placeholders** for student names, enrolment numbers and the supervisor —
`<Name>`, `<Enrolment No.>`, `Dr. <________>`. Those are filled in by hand
before submission; they are not generated.

## Regenerating

The figure and guide generators are self-contained:

```powershell
python docs/presentation/generators/make_figures.py
python docs/presentation/generators/build_terms.py
python docs/presentation/generators/build_guide.py
```

They need `python-docx`, `matplotlib` and `Pillow`. Output lands beside
the script.

`build_synopsis.py` additionally needs the department's blank template,
which is not redistributed here. Point at your own copy:

```powershell
$env:OCEANAI_SYNOPSIS_TEMPLATE = "path\to\B. Tech CSE Synopsis ... .docx"
python docs/presentation/generators/build_synopsis.py
```

It runs in two passes: build once, render to PDF, run `measure_pages.py`
to record where each heading landed, then build again so the contents page
and the lists of figures and tables carry real page numbers.

The two PowerPoint decks were assembled from the department's `.pptx`
template using a local toolchain that is not part of this repository, so
their build scripts are not included. The finished decks are.

## A note on the figures

`make_figures.py` authors each diagram at a declared width and solves for
the font size that lands at the intended size once the figure is placed in
the document. This matters: font sizes are absolute points in a saved
figure while the shapes scale with the canvas, so shrinking the canvas and
enlarging the type at the same time pushes labels out of their boxes. The
`pt()` helper exists for that reason.

The class diagram draws only relationships that exist as declared foreign
keys. There is deliberately no association between the SAR candidate
cluster and `regions`, because `sar_candidates` declares none — see
`docs/anomaly-method.md` and the knowledge-graph section of
`docs/FINAL_STATUS_REPORT.md`.
