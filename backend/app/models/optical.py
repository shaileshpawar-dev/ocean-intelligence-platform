"""Stored Sentinel-2 water-quality indices.

One row per (region cell, acquisition date). These are measurements, not
demonstration data: every row came from a Copernicus scene on the date it
names, and carries ``OBSERVED``.

Kept apart from :class:`SatelliteObservation`, which holds SAR backscatter
statistics from the synthetic provider. Mixing real optical indices into a
table whose other rows are simulated would make the distinction a matter of
reading a column correctly, which is exactly the kind of thing that stops
being done.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class OpticalIndexObservation(Base, TimestampMixin):
    """NDCI, NDTI and FDI for one cell from one Sentinel-2 acquisition."""

    __tablename__ = "optical_index_observations"
    __table_args__ = (
        # One reading per cell per day. Re-running the fetch over a window
        # already stored updates nothing and inserts nothing.
        UniqueConstraint("region_id", "observed_on", name="uq_optical_cell_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="CASCADE"), index=True
    )
    observed_on: Mapped[date] = mapped_column(Date, index=True)

    #: Normalised Difference Chlorophyll Index. Mishra & Mishra (2012).
    ndci_mean: Mapped[float] = mapped_column(Float)
    ndci_p50: Mapped[float] = mapped_column(Float)
    #: Normalised Difference Turbidity Index. Lacaux et al. (2007).
    ndti_mean: Mapped[float] = mapped_column(Float)
    ndti_p50: Mapped[float] = mapped_column(Float)
    #: Floating Debris Index. Biermann et al. (2020). Responds to floating
    #: material of any kind; it does not identify what the material is.
    fdi_mean: Mapped[float] = mapped_column(Float)
    fdi_p90: Mapped[float] = mapped_column(Float)

    #: Pixels the statistics were computed from, after the SCL water mask,
    #: and the grid total. Their ratio is how much sea was in frame.
    water_pixels: Mapped[int] = mapped_column(Integer)
    total_pixels: Mapped[int] = mapped_column(Integer)
    max_cloud_pct: Mapped[int] = mapped_column(Integer)

    evidence_level: Mapped[str] = mapped_column(String(32), default="OBSERVED")
    source: Mapped[str] = mapped_column(String(160))
    #: When this platform fetched it, as distinct from when it was acquired.
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
