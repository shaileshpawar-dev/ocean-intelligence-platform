"""Real Sentinel-2 indices: the grid, the water floor, and the word.

Three things here are easy to get wrong in ways that look fine:

The sampling grid. A fixed grid is 330 m per pixel on the Gulf of Kutch and
4.4 km on Bay of Bengal Z3, and Copernicus refuses anything coarser than
1500 m -- which is how the first sweep failed on 31 of 40 cells.

The water floor. An index computed over eight water pixels is arithmetically
valid and describes nothing. One such reading was an order of magnitude from
every other cell.

The word. FDI responds to floating material of any kind. Calling it plastic
is the single most likely way this platform could mislead someone, so the
label is pinned by a test rather than by good intentions.

No test here calls Copernicus. The parser is exercised against a recorded
response shape.
"""

from __future__ import annotations

from datetime import date

from app.vision.sentinel2_indices import (
    FDI_LABEL,
    MAX_METRES_PER_PIXEL,
    MIN_WATER_PIXELS,
    IndexReading,
    Sentinel2IndexClient,
    grid_for,
)

_METRES_PER_DEGREE = 111_320.0


def _resolution(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    """Metres per pixel each way for the grid this bbox would get."""
    import math

    width, height = grid_for(bbox)
    mean_lat = math.radians((bbox[1] + bbox[3]) / 2)
    x = abs(bbox[2] - bbox[0]) * _METRES_PER_DEGREE * math.cos(mean_lat) / width
    y = abs(bbox[3] - bbox[1]) * _METRES_PER_DEGREE / height
    return x, y


class TestTheSamplingGrid:
    """Derived per cell, because one grid cannot fit cells this different."""

    def test_every_configured_cell_is_within_the_resolution_limit(self):
        """The check Copernicus actually performs, over the real cells."""
        from app.gee.regions import all_cells

        offenders = []
        for cell in all_cells():
            bbox = (cell.min_lon, cell.min_lat, cell.max_lon, cell.max_lat)
            x, y = _resolution(bbox)
            if x > MAX_METRES_PER_PIXEL or y > MAX_METRES_PER_PIXEL:
                offenders.append((cell.code, round(x), round(y)))

        assert not offenders, f"cells over {MAX_METRES_PER_PIXEL} m/px: {offenders}"

    def test_a_large_cell_gets_a_larger_grid_than_a_small_one(self):
        small = grid_for((69.0, 22.2, 69.3, 22.5))  # Gulf of Kutch, 0.3 deg
        large = grid_for((87.0, 10.5, 89.5, 14.5))  # Bay of Bengal Z3, 4 deg

        assert large[1] > small[1]

    def test_longitude_is_scaled_by_latitude(self):
        """A degree of longitude is not a degree of distance."""
        equatorial = grid_for((0.0, 0.0, 4.0, 1.0))
        polar = grid_for((0.0, 60.0, 4.0, 61.0))

        assert polar[0] < equatorial[0]


class TestTheWaterFloor:
    """A reading over a handful of pixels is not a regional measurement."""

    @staticmethod
    def _reading(water_pixels: int) -> IndexReading:
        return IndexReading(
            cell_code="odisha_coast_w",
            observed_on=date(2026, 11, 17),
            ndci_mean=0.131,
            ndci_p50=0.130,
            ndti_mean=0.02,
            ndti_p50=0.02,
            fdi_mean=-0.2084,
            fdi_p90=-0.2,
            water_pixels=water_pixels,
            total_pixels=16_884,
            max_cloud_pct=30,
        )

    def test_a_reading_from_eight_pixels_does_not_characterise_a_region(self):
        """The real case: FDI -0.2084, ten times any other cell, from 8 px."""
        reading = self._reading(8)

        assert not reading.characterises_region
        assert reading.caveat is not None
        assert "8 water pixels" in reading.caveat

    def test_a_reading_with_enough_water_characterises_the_region(self):
        reading = self._reading(MIN_WATER_PIXELS)

        assert reading.characterises_region
        assert reading.caveat is None

    def test_a_single_pixel_reads_as_singular(self):
        assert "1 water pixel of" in (self._reading(1).caveat or "")

    def test_the_flag_travels_with_the_payload(self):
        payload = self._reading(8).to_dict()

        assert payload["characterises_region"] is False
        assert payload["caveat"]


class TestWhatFDIIsCalled:
    """FDI responds to floating material. It does not identify it."""

    def test_the_label_is_possible_floating_material(self):
        assert FDI_LABEL == "possible floating material"

    def test_the_label_does_not_claim_plastic(self):
        """Pinned deliberately. The index cannot support the word, and a
        confident label is how a band ratio becomes a headline."""
        assert "plastic" not in FDI_LABEL.lower()

    def test_every_reading_carries_the_label(self):
        reading = IndexReading(
            cell_code="gulf_of_mannar",
            observed_on=date(2026, 11, 20),
            ndci_mean=-0.099,
            ndci_p50=-0.1,
            ndti_mean=-0.05,
            ndti_p50=-0.05,
            fdi_mean=0.0133,
            fdi_p90=0.02,
            water_pixels=6300,
            total_pixels=10_000,
            max_cloud_pct=30,
        )

        assert reading.to_dict()["fdi_label"] == FDI_LABEL


class TestParsingAResponse:
    """Days the satellite did not see water are absences, not zeroes."""

    @staticmethod
    def _interval(day: str, sample: int, no_data: int) -> dict:
        def stats(mean: float, pct_key: str, pct: float) -> dict:
            return {
                "stats": {
                    "mean": mean,
                    "sampleCount": sample,
                    "noDataCount": no_data,
                    "percentiles": {pct_key: pct},
                }
            }

        return {
            "interval": {"from": f"{day}T00:00:00Z", "to": f"{day}T23:59:59Z"},
            "outputs": {
                "ndci": {"bands": {"B0": stats(-0.09, "50.0", -0.1)}},
                "ndti": {"bands": {"B0": stats(-0.24, "50.0", -0.25)}},
                "fdi": {"bands": {"B0": stats(0.019, "90.0", 0.03)}},
            },
        }

    def test_an_interval_with_no_water_is_dropped_not_recorded_as_zero(self):
        """The most misleading thing this module could do is log a cloudy day
        as a measurement of zero chlorophyll."""
        payload = {
            "data": [
                self._interval("2026-11-20", 10_000, 7_800),
                self._interval("2026-11-18", 10_000, 10_000),  # all cloud
            ]
        }

        readings = Sentinel2IndexClient._parse("gulf_of_kutch_w", payload, 30)

        assert [r.observed_on for r in readings] == [date(2026, 11, 20)]
        assert readings[0].water_pixels == 2_200

    def test_readings_come_back_newest_first(self):
        payload = {
            "data": [
                self._interval("2026-11-04", 10_000, 5_000),
                self._interval("2026-11-20", 10_000, 5_000),
                self._interval("2026-11-12", 10_000, 5_000),
            ]
        }

        readings = Sentinel2IndexClient._parse("palk_bay", payload, 30)

        assert [r.observed_on.day for r in readings] == [20, 12, 4]

    def test_a_malformed_interval_is_skipped_rather_than_guessed_at(self):
        payload = {"data": [{"interval": {"from": "2026-11-20T00:00:00Z"}}]}

        assert Sentinel2IndexClient._parse("palk_bay", payload, 30) == []
