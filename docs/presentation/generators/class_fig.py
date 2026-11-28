"""The class diagram, laid out by computation rather than by hand.

Box heights depend on how many attributes each class carries, so stacking
them against hand-picked coordinates silently overlaps the moment an
attribute is added. Here the heights are computed first and the column is
then stacked top-down with a fixed gap, which is also what makes the
canvas height a result rather than a guess.
"""

from __future__ import annotations

import matplotlib.patches as mpatches

ROW = 0.255
HEAD = 0.46
PAD = 0.18
GAP = 0.62
W = 3.85


def box_height(attrs, methods) -> float:
    """Total height of a class box with these compartments."""
    h = HEAD + ROW * len(attrs) + PAD
    if methods:
        h += ROW * len(methods) + PAD
    return h


LEFT = [
    ("WaterBody",
     ["+ slug : str", "+ name : str", "+ state : str",
      "+ category : enum", "+ geometry : Geometry"],
     ["+ current_status()"]),
    ("WaterQualityObservation",
     ["+ water_body_id : FK", "+ parameter : str", "+ value : float",
      "+ unit : str", "+ observed_at : datetime", "+ source_id : FK",
      "+ evidence_level : enum"], []),
    ("ReferenceStandard",
     ["+ authority : str", "+ parameter : str", "+ limit_value : float",
      "+ designated_use : str"],
     ["+ applies_to()"]),
    ("SARCandidate",
     ["+ candidate_id : str", "+ image_name : str", "+ p_oil : float",
      "+ wind_speed_ms : float", "+ review_status : enum"], []),
    ("SARCandidateReview",
     ["+ candidate_id : FK", "+ reviewer_id : str", "+ decision : enum"], []),
]

RIGHT = [
    ("MonitoringRegion",
     ["+ cell_code : str", "+ name : str", "+ bbox : Geometry",
      "+ is_coastal : bool"], []),
    ("OpticalIndexObservation",
     ["+ region_id : FK", "+ scene_id : str", "+ index_name : enum",
      "+ value : float", "+ water_pixels : int",
      "+ acquired_at : datetime"], []),
    ("PollutionEvent",
     ["+ region_id : FK", "+ signature : enum", "+ severity : enum",
      "+ detection_method : enum", "+ evidence_level : enum",
      "+ region_p99 : float", "+ absolute_floor : float | None"], []),
    ("SARCandidateOpticalEvidence",
     ["+ candidate_id : FK", "+ scene_id : str",
      "+ mean_ndci : float | None", "+ mean_ndti : float | None",
      "+ local_water_fraction : float"], []),
]

CAPTION_SPACE = 0.72
TOP_PAD = 0.10


def column_extent(classes) -> float:
    """Total height a stacked column occupies, gaps included."""
    return (sum(box_height(a, m) for _, a, m in classes)
            + GAP * (len(classes) - 1))


def render(mod) -> None:
    """Draw the figure using the shared helpers from ``make_figures``."""
    height = (max(column_extent(LEFT), column_extent(RIGHT))
              + CAPTION_SPACE + TOP_PAD)
    fig, ax = mod._blank(8.6, round(height, 2))
    pt, LINE, INK, MUTED, FILL2 = mod.pt, mod.LINE, mod.INK, mod.MUTED, mod.FILL2
    LX, RX = 0.15, 4.55

    def uml(x, top, name, attrs, methods):
        bodyh = ROW * len(attrs) + PAD
        meth = ROW * len(methods) + PAD if methods else 0.0
        h = HEAD + bodyh + meth
        ax.add_patch(mpatches.Rectangle((x, top - h), W, h, facecolor="white",
                                        edgecolor=LINE, lw=pt(0.9), zorder=3))
        ax.add_patch(mpatches.Rectangle((x, top - HEAD), W, HEAD,
                                        facecolor=FILL2, edgecolor=LINE,
                                        lw=pt(0.9), zorder=4))
        ax.text(x + W / 2, top - HEAD / 2, name, ha="center", va="center",
                fontsize=pt(8.0), fontweight="bold", color=INK, zorder=5)
        ty = top - HEAD - 0.19
        for a in attrs:
            ax.text(x + 0.13, ty, a, ha="left", va="center",
                    fontsize=pt(7.0), color=INK, zorder=5)
            ty -= ROW
        if methods:
            yl = top - HEAD - bodyh
            ax.plot([x, x + W], [yl, yl], color=LINE, lw=pt(0.9), zorder=5)
            ty = yl - 0.19
            for m in methods:
                ax.text(x + 0.13, ty, m, ha="left", va="center",
                        fontsize=pt(7.0), color=MUTED, style="italic",
                        zorder=5)
                ty -= ROW
        return {"x": x, "top": top, "bottom": top - h, "cx": x + W / 2,
                "right": x + W}

    def stack(classes, x, top):
        placed, y = {}, top
        for name, attrs, methods in classes:
            placed[name] = uml(x, y, name, attrs, methods)
            y = placed[name]["bottom"] - GAP
        return placed

    top = height - TOP_PAD
    L = stack(LEFT, LX, top)
    R = stack(RIGHT, RX, top)

    def vlink(a, b, one="1", many="0..*", dashed=False, label=None):
        x = a["cx"]
        ax.plot([x, x], [a["bottom"], b["top"]], color=LINE, lw=pt(0.9),
                linestyle="--" if dashed else "-", zorder=2)
        if one:
            ax.text(x + 0.10, a["bottom"] - 0.18, one, fontsize=pt(6.4),
                    color=MUTED)
        if many:
            ax.text(x + 0.10, b["top"] + 0.10, many, fontsize=pt(6.4),
                    color=MUTED)
        if label:
            ax.text(x + 0.12, (a["bottom"] + b["top"]) / 2, label,
                    fontsize=pt(6.4), color=MUTED, va="center",
                    linespacing=1.3)

    vlink(L["WaterBody"], L["WaterQualityObservation"])
    vlink(L["WaterQualityObservation"], L["ReferenceStandard"],
          one="", many="", dashed=True,
          label="« applies »\n(by rule, no FK)")
    vlink(L["SARCandidate"], L["SARCandidateReview"])
    vlink(R["MonitoringRegion"], R["OpticalIndexObservation"])

    # MonitoringRegion -> PollutionEvent skips a box, so route it outside
    # the column rather than through OpticalIndexObservation.
    reg, pe = R["MonitoringRegion"], R["PollutionEvent"]
    xr = reg["right"] - 0.34
    out = xr + 0.52
    ax.plot([xr, xr], [reg["bottom"], reg["bottom"] - 0.20], color=LINE,
            lw=pt(0.9))
    ax.plot([xr, out], [reg["bottom"] - 0.20, reg["bottom"] - 0.20],
            color=LINE, lw=pt(0.9))
    ax.plot([out, out], [reg["bottom"] - 0.20, pe["top"]], color=LINE,
            lw=pt(0.9))
    ax.plot([out, xr], [pe["top"], pe["top"]], color=LINE, lw=pt(0.9))
    ax.text(out + 0.16, (reg["bottom"] + pe["top"]) / 2, "1  │  0..*",
            fontsize=pt(6.4), color=MUTED, va="center", rotation=90,
            ha="center")

    # SARCandidate -> its optical evidence, across the two columns.
    sc, soe = L["SARCandidate"], R["SARCandidateOpticalEvidence"]
    ymid = max(sc["bottom"], soe["bottom"]) + 0.55
    ax.plot([sc["right"], soe["x"]], [ymid, ymid], color=LINE, lw=pt(0.9))
    ax.text(sc["right"] + 0.09, ymid + 0.09, "1", fontsize=pt(6.4),
            color=MUTED)
    ax.text(soe["x"] - 0.36, ymid + 0.09, "0..*", fontsize=pt(6.4),
            color=MUTED)

    ax.text(4.30, 0.30,
            "Only declared foreign keys are drawn. There is deliberately no "
            "association between the SAR candidate cluster\nand "
            "MonitoringRegion: sar_candidates declares none, and inventing "
            "one is what the knowledge graph exists to refuse.",
            ha="center", va="bottom", fontsize=pt(6.4), color=MUTED,
            linespacing=1.45)
    ax.text(4.30, 0.00,
            "Every observation carries an evidence level (OBSERVED · "
            "MEASURED · DETECTED · INFERRED · FORECAST · RETRIEVED) "
            "and the time it was measured.",
            ha="center", va="bottom", fontsize=pt(6.4), color=MUTED)

    fig.savefig(mod.OUT / "fig_5_2_class.png")
    import matplotlib.pyplot as plt
    plt.close(fig)
