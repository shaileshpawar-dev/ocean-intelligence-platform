"""A landscape class diagram for the slide deck.

The report's portrait version is the complete one. A 16:9 slide gives about
4.6 inches of height, and a portrait diagram scaled to fit that is only
about 4 inches wide -- unreadable from the back of a room. This variant
keeps the same entities and the same relationships but lays them out in
three columns and carries the three or four attributes that matter, so it
is legible when projected. The report, not the slide, is where the full
attribute list belongs.
"""

from __future__ import annotations

import matplotlib.patches as mpatches

ROW = 0.30
HEAD = 0.52
PAD = 0.20
W = 4.60


def box_height(attrs) -> float:
    return HEAD + ROW * len(attrs) + PAD


COLUMNS = [
    [
        ("WaterBody",
         ["+ slug : str", "+ name : str", "+ geometry : Geometry"]),
        ("WaterQualityObservation",
         ["+ water_body_id : FK", "+ value : float",
          "+ observed_at : datetime", "+ evidence_level : enum"]),
        ("ReferenceStandard",
         ["+ authority : str", "+ limit_value : float",
          "+ designated_use : str"]),
    ],
    [
        ("MonitoringRegion",
         ["+ cell_code : str", "+ bbox : Geometry",
          "+ is_coastal : bool"]),
        ("OpticalIndexObservation",
         ["+ region_id : FK", "+ index_name : enum", "+ value : float",
          "+ acquired_at : datetime"]),
        ("PollutionEvent",
         ["+ region_id : FK", "+ severity : enum", "+ region_p99 : float",
          "+ absolute_floor : float | None"]),
    ],
    [
        ("SARCandidate",
         ["+ candidate_id : str", "+ p_oil : float",
          "+ wind_speed_ms : float"]),
        ("SARCandidateOpticalEvidence",
         ["+ candidate_id : FK", "+ mean_ndci : float | None",
          "+ mean_ndti : float | None",
          "+ local_water_fraction : float"]),
        ("SARCandidateReview",
         ["+ candidate_id : FK", "+ reviewer_id : str",
          "+ decision : enum"]),
    ],
]

GAP = 0.30
TOP_PAD = 0.12
CAPTION_SPACE = 0.42


def render(mod, out_name="fig_5_2_class_wide.png") -> None:
    """Draw the wide variant with the shared helpers from ``make_figures``."""
    column_heights = [
        sum(box_height(a) for _, a in col) + GAP * (len(col) - 1)
        for col in COLUMNS
    ]
    height = max(column_heights) + TOP_PAD + CAPTION_SPACE
    width = 16.0
    fig, ax = mod._blank(width, round(height, 2))
    pt, LINE, INK, MUTED, FILL2 = (mod.pt, mod.LINE, mod.INK, mod.MUTED,
                                   mod.FILL2)

    xs = [0.50, 5.70, 10.90]

    def uml(x, top, name, attrs):
        h = box_height(attrs)
        ax.add_patch(mpatches.Rectangle((x, top - h), W, h, facecolor="white",
                                        edgecolor=LINE, lw=pt(0.9), zorder=3))
        ax.add_patch(mpatches.Rectangle((x, top - HEAD), W, HEAD,
                                        facecolor=FILL2, edgecolor=LINE,
                                        lw=pt(0.9), zorder=4))
        ax.text(x + W / 2, top - HEAD / 2, name, ha="center", va="center",
                fontsize=pt(8.5), fontweight="bold", color=INK, zorder=5)
        ty = top - HEAD - 0.21
        for a in attrs:
            ax.text(x + 0.15, ty, a, ha="left", va="center",
                    fontsize=pt(7.4), color=INK, zorder=5)
            ty -= ROW
        return {"x": x, "top": top, "bottom": top - h, "cx": x + W / 2,
                "right": x + W}

    top = height - TOP_PAD
    placed = []
    for x, column in zip(xs, COLUMNS):
        y, col = top, {}
        for name, attrs in column:
            col[name] = uml(x, y, name, attrs)
            y = col[name]["bottom"] - GAP
        placed.append(col)

    def vlink(a, b, one="1", many="0..*", dashed=False, label=None):
        """One combined cardinality label: the gap is too small to stack."""
        x = a["cx"]
        ax.plot([x, x], [a["bottom"], b["top"]], color=LINE, lw=pt(0.9),
                linestyle="--" if dashed else "-", zorder=2)
        mid = (a["bottom"] + b["top"]) / 2
        text = label or (f"{one}  →  {many}" if one or many else "")
        if text:
            ax.text(x + 0.14, mid, text, fontsize=pt(7.0), color=MUTED,
                    va="center", ha="left")

    water, marine, sar = placed
    vlink(water["WaterBody"], water["WaterQualityObservation"])
    vlink(water["WaterQualityObservation"], water["ReferenceStandard"],
          one="", many="", dashed=True, label="« applies » (no FK)")
    vlink(marine["MonitoringRegion"], marine["OpticalIndexObservation"])
    vlink(marine["OpticalIndexObservation"], marine["PollutionEvent"],
          one="", many="", dashed=True, label="derived, not keyed")
    vlink(sar["SARCandidate"], sar["SARCandidateOpticalEvidence"])
    vlink(sar["SARCandidateOpticalEvidence"], sar["SARCandidateReview"],
          one="", many="")

    # MonitoringRegion also keys PollutionEvent directly; route it outside
    # the column so it does not pass through OpticalIndexObservation.
    reg, pe = marine["MonitoringRegion"], marine["PollutionEvent"]
    # Routed on the left of its own column: on the right it ran beside the
    # SAR column and read as if it connected to it.
    xr = reg["x"] + 0.30
    out = xr - 0.36
    ax.plot([xr, xr], [reg["bottom"], reg["bottom"] - 0.16], color=LINE,
            lw=pt(0.9))
    ax.plot([xr, out], [reg["bottom"] - 0.16, reg["bottom"] - 0.16],
            color=LINE, lw=pt(0.9))
    ax.plot([out, out], [reg["bottom"] - 0.16, pe["top"]], color=LINE,
            lw=pt(0.9))
    ax.plot([out, xr], [pe["top"], pe["top"]], color=LINE, lw=pt(0.9))
    ax.text(out - 0.14, (reg["bottom"] + pe["top"]) / 2, "1 │ 0..*",
            fontsize=pt(7.0), color=MUTED, va="center", rotation=90,
            ha="center")

    for x, label in zip(xs, ("India water quality",
                             "Marine regions and detections",
                             "SAR candidate review")):
        ax.text(x + W / 2, 0.12, label, ha="center", va="bottom",
                fontsize=pt(8.0), fontweight="bold", color=mod.ACCENT)

    fig.savefig(mod.OUT / out_name)
    import matplotlib.pyplot as plt
    plt.close(fig)
