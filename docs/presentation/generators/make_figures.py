"""Generate the four diagrams the synopsis template requires.

Drawn from the real system. In particular the class diagram shows only
relationships that exist as declared foreign keys in
``backend/app/models`` -- there is deliberately **no** association between
the SAR candidate cluster and the monitoring regions, because
``sar_candidates`` declares no foreign keys at all. Drawing one would
invent a link the database does not have, which is the same mistake the
knowledge graph is built to avoid.

**Sizing.** Font sizes are absolute points in the saved figure while the
shapes scale with the canvas, so a figure authored at one width and placed
at another renders its labels at ``size * placed / authored``. Every figure
is placed in the document at ``PLACED_IN`` inches wide; each one declares
its authored width, and ``pt()`` solves for the size that lands at the
intended point size on the page. Shapes are then sized to hold the text at
that scale, which is why the first attempt -- shrinking the canvas and
enlarging the type at the same time -- pushed the labels out of their
boxes.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

OUT = Path(__file__).resolve().parent / "figures"
OUT.mkdir(parents=True, exist_ok=True)

#: Width the figures are placed at in the document, in inches.
PLACED_IN = 6.4

INK = "#1A1A1A"
MUTED = "#4C5661"
LINE = "#6E7B8A"
FILL = "#EEF3F8"
FILL2 = "#E3ECF4"
ACCENT = "#1F5F8B"

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif"],
    "savefig.dpi": 200,
    "savefig.bbox": "tight",
    "savefig.pad_inches": 0.10,
    "savefig.facecolor": "white",
})

_authored_width = 1.0


def pt(on_page: float) -> float:
    """The size to author with, so it lands at ``on_page`` pt in the doc."""
    return on_page * _authored_width / PLACED_IN


def _blank(w, h):
    """An axes whose data units are inches at the authored size."""
    global _authored_width
    _authored_width = w
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.set_aspect("equal")
    ax.axis("off")
    return fig, ax


def _arrow(ax, p0, p1, *, label=None, size=7.0, style="-|>", dashed=False,
           label_dx=0.0, label_dy=0.14):
    ax.add_patch(FancyArrowPatch(
        p0, p1, arrowstyle=style, mutation_scale=pt(9),
        linewidth=pt(0.8), color=LINE,
        linestyle="--" if dashed else "-",
        shrinkA=2, shrinkB=2,
    ))
    if label:
        ax.text((p0[0] + p1[0]) / 2 + label_dx,
                (p0[1] + p1[1]) / 2 + label_dy, label,
                ha="center", va="bottom", fontsize=pt(size), color=MUTED,
                bbox=dict(boxstyle="round,pad=0.16", fc="white", ec="none"))


# --------------------------------------------------------------------------
# Figure 5.1 - Use case diagram        authored 11.0 x 7.6 in
# --------------------------------------------------------------------------
def use_case() -> None:
    """Actors and the use cases the API actually exposes.

    The reviewer generalises the viewer, so the viewer's cases need no
    second set of lines and nothing crosses the diagram to reach them.
    """
    fig, ax = _blank(11.0, 7.6)
    lw = pt(0.9)

    def stick(cx, cy, label):
        ax.add_patch(mpatches.Circle((cx, cy + 0.34), 0.13, fill=True,
                                     fc="white", ec=INK, lw=lw))
        ax.plot([cx, cx], [cy + 0.21, cy - 0.14], color=INK, lw=lw)
        ax.plot([cx - 0.28, cx + 0.28], [cy + 0.10, cy + 0.10], color=INK, lw=lw)
        ax.plot([cx, cx - 0.23], [cy - 0.14, cy - 0.52], color=INK, lw=lw)
        ax.plot([cx, cx + 0.23], [cy - 0.14, cy - 0.52], color=INK, lw=lw)
        ax.text(cx, cy - 0.68, label, ha="center", va="top",
                fontsize=pt(8.5), color=INK, linespacing=1.3)

    ax.add_patch(mpatches.Rectangle((2.95, 0.42), 5.3, 6.60, fill=False,
                                    edgecolor=LINE, lw=pt(1.1)))
    ax.text(5.60, 6.80, "OceanAI Platform", ha="center", va="center",
            fontsize=pt(10.5), fontweight="bold", color=ACCENT)

    reviewer_cases = [
        "Review a SAR candidate against\nits Sentinel-2 optical evidence",
        "Record a review decision\n(append-only, never overwritten)",
        "Run an agent analysis and\ngenerate an evidence-tiered report",
    ]
    viewer_cases = [
        "View a water body's condition,\nor why it cannot be established",
        "Ask a question about water\n(refused when unsupported)",
        "Inspect detections and layers\non the Ocean Map",
        "Read measured model performance\nand drift status",
        "Check each source's freshness\nand attribution",
    ]
    ys_r, ys_v, y = [], [], 6.26
    for group, store in ((reviewer_cases, ys_r), (viewer_cases, ys_v)):
        for text in group:
            ax.add_patch(mpatches.Ellipse((5.60, y), 4.55, 0.64,
                                          facecolor=FILL, edgecolor=LINE,
                                          lw=pt(0.85)))
            ax.text(5.60, y, text, ha="center", va="center",
                    fontsize=pt(7.4), color=INK, linespacing=1.3)
            store.append(y)
            y -= 0.78
        y -= 0.10

    stick(1.30, 5.60, "Analyst /\nReviewer")
    stick(1.30, 2.10, "Viewer")
    stick(9.85, 5.60, "Scheduled\ningestion job")
    stick(9.85, 2.10, "External data\nproviders")

    for yy in ys_r:
        _arrow(ax, (1.82, 5.46), (3.38, yy), style="-")
    for yy in ys_v:
        _arrow(ax, (1.82, 1.96), (3.38, yy), style="-")

    ax.add_patch(FancyArrowPatch(
        (1.30, 4.30), (1.30, 2.86), arrowstyle="-|>", mutation_scale=pt(14),
        linewidth=lw, color=INK, fc="white", shrinkA=0, shrinkB=0))
    ax.text(1.46, 3.56, "is a", fontsize=pt(7.0), color=MUTED, ha="left")

    _arrow(ax, (9.33, 5.46), (7.82, ys_v[-1]), style="-")
    _arrow(ax, (9.33, 5.46), (7.82, ys_v[-2]), style="-")
    _arrow(ax, (9.33, 1.96), (7.82, ys_v[-1]), style="-")

    ax.text(5.50, 0.04,
            "Providers: CPCB · CWC · Copernicus Sentinel-1/2 · "
            "Copernicus Marine · Open-Meteo · Global Fishing Watch · "
            "PANGAEA 980773",
            ha="center", va="bottom", fontsize=pt(6.6), color=MUTED)

    fig.savefig(OUT / "fig_5_1_use_case.png")
    plt.close(fig)


# --------------------------------------------------------------------------
# Figure 5.2 - Class diagram           authored 8.6 x 10.4 in (portrait)
# --------------------------------------------------------------------------
def class_diagram() -> None:
    """Core persistent entities and only their declared foreign keys.

    Laid out portrait in two columns, and stacked by computation: see
    ``class_fig`` for why the coordinates are derived rather than typed.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import class_fig

    class_fig.render(sys.modules[__name__])


# --------------------------------------------------------------------------
# Figure 5.3 - Data flow diagram       authored 11.6 x 7.4 in
# --------------------------------------------------------------------------
def dfd() -> None:
    """Level-1 DFD. The ingest/serve split is the architecture's rule."""
    fig, ax = _blank(11.6, 7.4)
    lw = pt(0.9)

    ax.text(5.80, 7.30, "Level-1 Data Flow Diagram", ha="center", va="top",
            fontsize=pt(9.5), fontweight="bold", color=ACCENT)

    def entity(x, y, w, h, name):
        ax.add_patch(mpatches.Rectangle((x, y - h / 2), w, h, facecolor=FILL2,
                                        edgecolor=LINE, lw=lw, zorder=3))
        ax.text(x + w / 2, y, name, ha="center", va="center",
                fontsize=pt(7.0), color=INK, linespacing=1.3, zorder=4)

    def process(cx, cy, name, r=0.86):
        ax.add_patch(mpatches.Circle((cx, cy), r, facecolor=FILL,
                                     edgecolor=LINE, lw=lw, zorder=3))
        ax.text(cx, cy, name, ha="center", va="center", fontsize=pt(6.8),
                color=INK, linespacing=1.35, zorder=4)

    def store(x, y, w, label):
        ax.add_patch(mpatches.Rectangle((x, y - 0.30), w, 0.60,
                                        facecolor="white", edgecolor="none",
                                        zorder=2))
        for yy in (y + 0.30, y - 0.30):
            ax.plot([x, x + w], [yy, yy], color=LINE, lw=lw, zorder=3)
        ax.plot([x, x], [y - 0.30, y + 0.30], color=LINE, lw=lw, zorder=3)
        ax.text(x + 0.14, y, label, ha="left", va="center",
                fontsize=pt(7.0), color=INK, zorder=4)

    entity(0.10, 5.80, 2.05, 0.86, "CPCB / CWC\n(via NWDP)")
    entity(0.10, 4.52, 2.05, 0.86, "Copernicus\nSentinel-1 / 2")
    entity(0.10, 3.24, 2.05, 0.86, "Copernicus Marine\n· Open-Meteo")
    entity(0.10, 1.96, 2.05, 0.86, "Global Fishing\nWatch")

    process(3.55, 5.40, "1.0\nIngest &\nnormalise")
    process(3.55, 2.80, "2.0\nCompute indices\n& screen tiles")
    process(6.70, 4.35, "3.0\nRaise detections\n(dual criteria)")
    process(6.70, 2.00, "4.0\nStatus, risk &\nforecast engines")
    process(9.45, 3.05, "5.0\nServe API\n& dashboard")

    store(4.30, 6.65, 5.10,
          "D1   PostgreSQL + PostGIS · observations, geometry, events")
    store(4.30, 0.62, 5.10,
          "D2   Response cache on disk · every external payload")

    _arrow(ax, (2.15, 5.80), (2.76, 5.64))
    _arrow(ax, (2.15, 4.52), (2.92, 3.42))
    _arrow(ax, (2.15, 3.24), (2.70, 3.02))
    _arrow(ax, (2.15, 1.96), (3.02, 2.12))

    _arrow(ax, (4.05, 6.05), (4.85, 6.32), label="validated rows",
           label_dy=-0.04)
    _arrow(ax, (4.34, 3.12), (5.94, 3.96), label="NDCI · NDTI · FDI",
           label_dy=-0.06)
    _arrow(ax, (6.70, 5.23), (6.70, 6.33), label="events")
    _arrow(ax, (6.70, 3.47), (6.70, 2.88))
    ax.text(6.86, 3.12, "anomalies", fontsize=pt(6.8), color=MUTED, ha="left")
    _arrow(ax, (7.48, 2.42), (8.74, 2.74), label="scored state",
           label_dy=-0.10)
    _arrow(ax, (9.10, 6.33), (9.76, 3.94), label="reads only", label_dy=0.0)

    # 4.0 reads stored readings and writes history and risk scores back.
    ax.add_patch(FancyArrowPatch(
        (5.45, 6.33), (5.45, 2.00), arrowstyle="<|-|>", mutation_scale=pt(9),
        linewidth=lw, color=LINE, shrinkA=2, shrinkB=2))
    ax.plot([5.45, 5.86], [2.00, 2.00], color=LINE, lw=lw)
    ax.text(5.31, 4.35, 'reads / writes', fontsize=pt(6.4), color=MUTED,
            ha='center', va='center', rotation=90,
            bbox=dict(boxstyle='round,pad=0.12', fc='white', ec='none'))

    _arrow(ax, (3.32, 1.94), (4.72, 0.95), dashed=True)
    _arrow(ax, (3.97, 4.68), (5.14, 0.95), dashed=True, label="cached",
           label_dx=0.80, label_dy=-0.60)

    entity(10.55, 3.05, 1.45, 0.86, "Analyst\n(browser)")
    _arrow(ax, (10.33, 3.05), (10.55, 3.05))

    ax.text(5.80, 0.00,
            "Processes 1.0 and 2.0 are scheduled jobs. Process 5.0 only "
            "reads: a freshly started container serves what the jobs "
            "produced and never ingests on request.",
            ha="center", va="bottom", fontsize=pt(6.6), color=MUTED)

    fig.savefig(OUT / "fig_5_3_dfd.png")
    plt.close(fig)


# --------------------------------------------------------------------------
# Figure 6.1 - Gantt chart             authored 10.0 x 4.9 in
# --------------------------------------------------------------------------
def gantt() -> None:
    """Phase windows taken from the project's own commit history."""
    global _authored_width
    _authored_width = 10.0

    tasks = [
        ("Requirement study & data-source survey", date(2026, 9, 7), date(2026, 9, 20), 0),
        ("Water data model, CPCB/CWC ingestion", date(2026, 9, 21), date(2026, 9, 27), 0),
        ("Geometry import & India water map", date(2026, 9, 24), date(2026, 10, 5), 0),
        ("Status engine & evidence ladder", date(2026, 9, 28), date(2026, 10, 12), 1),
        ("SAR benchmark, CNN v2.2 & triage", date(2026, 10, 6), date(2026, 10, 26), 1),
        ("Risk engine, forecasting, graph", date(2026, 10, 20), date(2026, 11, 8), 1),
        ("RAG question answering & reports", date(2026, 11, 1), date(2026, 11, 14), 2),
        ("Real-data migration (demo mode off)", date(2026, 11, 15), date(2026, 11, 21), 2),
        ("Sentinel-1 calibration & replay", date(2026, 11, 19), date(2026, 11, 22), 2),
        ("Verification, freeze & documentation", date(2026, 11, 20), date(2026, 11, 24), 3),
        ("Synopsis, presentation & demo", date(2026, 11, 22), date(2026, 11, 25), 3),
    ]
    colours = ["#2E6E9E", "#3E8A86", "#8A6E3E", "#7A4E6E"]
    labels = ["Phase 1 — Foundation",
              "Phase 2 — Detection & models",
              "Phase 3 — Intelligence & real data",
              "Phase 4 — Verification & delivery"]

    fig, ax = plt.subplots(figsize=(10.0, 4.9))
    for i, (name, start, end, grp) in enumerate(tasks):
        y = len(tasks) - i - 1
        ax.barh(y, (end - start).days + 1, left=start, height=0.56,
                color=colours[grp], edgecolor="white", linewidth=0.8)
        ax.text(end + timedelta(days=1), y, f"  {(end - start).days + 1} d",
                va="center", ha="left", fontsize=pt(6.4), color=MUTED)

    ax.set_yticks(range(len(tasks)))
    ax.set_yticklabels([t[0] for t in reversed(tasks)], fontsize=pt(7.6))
    ax.set_ylim(-0.7, len(tasks) - 0.3)
    ax.set_xlim(date(2026, 9, 1), date(2026, 12, 6))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO,
                                                     interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.tick_params(axis="x", labelsize=pt(7.0))
    ax.grid(axis="x", color="#D7DEE6", lw=0.7)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(LINE)

    ax.axvline(date(2026, 11, 25), color="#B91C1C", lw=1.1, ls="--")
    ax.text(date(2026, 11, 26), len(tasks) - 0.45, "Demo\n25 Nov",
            fontsize=pt(6.8), color="#B91C1C", va="top")

    ax.legend(handles=[mpatches.Patch(color=c, label=l)
                       for c, l in zip(colours, labels)],
              loc="lower center", bbox_to_anchor=(0.5, -0.24), ncol=2,
              frameon=False, fontsize=pt(7.4))

    fig.savefig(OUT / "fig_6_1_gantt.png")
    plt.close(fig)


if __name__ == "__main__":
    use_case()
    class_diagram()
    dfd()
    gantt()
    for f in sorted(OUT.glob("*.png")):
        print(f.name, f.stat().st_size // 1024, "KB")
