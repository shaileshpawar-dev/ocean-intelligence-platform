"""Marine Optical Quality Screener and Spectral Index Engine.

Calculates water, cloud, cirrus, and shadow fractions using Sentinel-2 L2A SCL.
Computes NDCI (Normalized Difference Chlorophyll Index) and NDTI proxies.
Generates true-colour RGB, false-colour SWIR, SCL quality mask, and NDCI map visualizations.

SCIENTIFIC GUARDRAIL:
NDCI = (B05 - B04) / (B05 + B04)
NDCI is an environmental chlorophyll-a / algal indicator, NOT proof of oil.
High NDCI suggests natural biogenic surfactant films or algal blooms.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

# Sentinel-2 Scene Classification Layer (SCL) constants
SCL_NO_DATA = 0
SCL_SATURATED_OR_DEFECTIVE = 1
SCL_DARK_AREA_PIXELS = 2
SCL_CLOUD_SHADOWS = 3
SCL_VEGETATION = 4
SCL_NOT_VEGETATED = 5
SCL_WATER = 6
SCL_UNCLASSIFIED = 7
SCL_CLOUD_MEDIUM_PROB = 8
SCL_CLOUD_HIGH_PROB = 9
SCL_THIN_CIRRUS = 10
SCL_SNOW_OR_ICE = 11

SCL_CLOUD_CLASSES = (SCL_CLOUD_MEDIUM_PROB, SCL_CLOUD_HIGH_PROB, SCL_THIN_CIRRUS)

# Color lookup table for SCL visualization (RGB tuples)
SCL_COLOR_LUT: dict[int, tuple[int, int, int]] = {
    SCL_NO_DATA: (0, 0, 0),                       # Black
    SCL_SATURATED_OR_DEFECTIVE: (255, 0, 0),      # Red
    SCL_DARK_AREA_PIXELS: (40, 40, 40),           # Dark grey
    SCL_CLOUD_SHADOWS: (70, 70, 70),              # Shadow grey
    SCL_VEGETATION: (34, 139, 34),                # Forest green
    SCL_NOT_VEGETATED: (189, 154, 122),           # Soil tan
    SCL_WATER: (26, 92, 171),                     # Ocean blue
    SCL_UNCLASSIFIED: (130, 130, 130),            # Mid grey
    SCL_CLOUD_MEDIUM_PROB: (220, 220, 220),       # Light cloud
    SCL_CLOUD_HIGH_PROB: (255, 255, 255),         # Dense cloud
    SCL_THIN_CIRRUS: (180, 210, 230),             # Cirrus light blue
    SCL_SNOW_OR_ICE: (200, 240, 255),             # Ice cyan
}


@dataclass(slots=True)
class OpticalQualityMetrics:
    """Quantitative quality metrics derived from Sentinel-2 L2A raster window."""

    water_fraction: float
    cloud_fraction: float
    shadow_fraction: float
    cirrus_fraction: float
    valid_pixel_fraction: float
    total_pixels: int
    water_pixels: int
    mean_ndci: float | None
    p90_ndci: float | None
    min_ndci: float | None
    max_ndci: float | None
    mean_ndti: float | None
    mean_swir_ratio: float | None
    optical_quality_flag: str
    quality_summary: str
    scientific_disclaimer: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_optical_quality_and_indices(
    b02: np.ndarray,
    b03: np.ndarray,
    b04: np.ndarray,
    b05: np.ndarray,
    b08: np.ndarray,
    b11: np.ndarray,
    scl: np.ndarray,
) -> tuple[OpticalQualityMetrics, np.ndarray, np.ndarray]:
    """Compute SCL quality fractions, NDCI, and NDTI.

    Returns:
        (metrics, ndci_water_array, ndti_water_array)
    """
    total_pixels = scl.size
    if total_pixels == 0:
        raise ValueError("Empty SCL array provided.")

    valid_mask = (scl != SCL_NO_DATA) & (scl != SCL_SATURATED_OR_DEFECTIVE)
    valid_count = int(np.sum(valid_mask))
    norm_denom = max(valid_count, 1)

    water_mask = (scl == SCL_WATER)
    cloud_mask = np.isin(scl, (SCL_CLOUD_MEDIUM_PROB, SCL_CLOUD_HIGH_PROB))
    cirrus_mask = (scl == SCL_THIN_CIRRUS)
    all_cloud_mask = cloud_mask | cirrus_mask
    shadow_mask = (scl == SCL_CLOUD_SHADOWS)

    water_pixels = int(np.sum(water_mask))
    water_fraction = round(water_pixels / norm_denom, 4)
    cloud_fraction = round(int(np.sum(all_cloud_mask)) / norm_denom, 4)
    cirrus_fraction = round(int(np.sum(cirrus_mask)) / norm_denom, 4)
    shadow_fraction = round(int(np.sum(shadow_mask)) / norm_denom, 4)
    valid_fraction = round(valid_count / total_pixels, 4)

    # 1. NDCI over water pixels: (B05 - B04) / (B05 + B04)
    ndci_water = np.full(scl.shape, np.nan, dtype=np.float32)
    denom_ndci = b05 + b04
    calc_ndci_mask = water_mask & (denom_ndci > 0.001)

    mean_ndci: float | None = None
    p90_ndci: float | None = None
    min_ndci: float | None = None
    max_ndci: float | None = None

    if np.any(calc_ndci_mask):
        ndci_values = (b05[calc_ndci_mask] - b04[calc_ndci_mask]) / denom_ndci[calc_ndci_mask]
        ndci_values = np.clip(ndci_values, -1.0, 1.0)
        ndci_water[calc_ndci_mask] = ndci_values

        mean_ndci = round(float(np.mean(ndci_values)), 4)
        p90_ndci = round(float(np.percentile(ndci_values, 90)), 4)
        min_ndci = round(float(np.min(ndci_values)), 4)
        max_ndci = round(float(np.max(ndci_values)), 4)

    # 2. NDTI over water pixels: (B04 - B03) / (B04 + B03)
    ndti_water = np.full(scl.shape, np.nan, dtype=np.float32)
    denom_ndti = b04 + b03
    calc_ndti_mask = water_mask & (denom_ndti > 0.001)

    mean_ndti: float | None = None
    if np.any(calc_ndti_mask):
        ndti_values = (b04[calc_ndti_mask] - b03[calc_ndti_mask]) / denom_ndti[calc_ndti_mask]
        ndti_values = np.clip(ndti_values, -1.0, 1.0)
        ndti_water[calc_ndti_mask] = ndti_values
        mean_ndti = round(float(np.mean(ndti_values)), 4)

    # 3. SWIR / NIR ratio over water (sunglint / surface film indicator)
    denom_swir = b08 + 1e-4
    mean_swir_ratio: float | None = None
    if water_pixels > 0:
        swir_values = b11[water_mask] / denom_swir[water_mask]
        mean_swir_ratio = round(float(np.mean(np.clip(swir_values, 0.0, 10.0))), 4)

    # 4. Optical Quality Flag Determination
    if cloud_fraction >= 0.35 or (cloud_fraction + shadow_fraction) >= 0.45:
        flag = "OPTICAL_CLOUD_OBSCURED"
        summary = f"Severe cloud/shadow obscuration ({cloud_fraction:.0%} cloud, {shadow_fraction:.0%} shadow). Surface invisible."
    elif water_fraction < 0.25:
        flag = "OPTICAL_LOW_WATER_FRACTION"
        summary = f"Low water fraction ({water_fraction:.0%}). Candidate window overlaps coastal land or reefs."
    elif mean_ndci is not None and mean_ndci >= 0.15:
        flag = "OPTICAL_HIGH_ALGAL_CONTEXT"
        summary = f"High NDCI ({mean_ndci:.3f}). Active phytoplankton/algal bloom detected; SAR dark patch likely biogenic."
    elif cloud_fraction >= 0.15:
        flag = "OPTICAL_PARTIALLY_CLOUDED"
        summary = f"Moderate clouds ({cloud_fraction:.0%}). Partial sea surface visible through cloud breaks."
    else:
        flag = "OPTICAL_VALID_CLEAR"
        summary = f"Pristine clear sea surface ({water_fraction:.0%} water, {cloud_fraction:.0%} cloud). Highly suitable for analyst review."

    disclaimer = (
        "SCIENTIFIC GUARDRAIL: Sentinel-2 optical reflectance is independent corroborative context. "
        "NDCI is an environmental algal/turbidity indicator, NOT proof of oil. "
        "Never use optical scores alone to confirm or reject an oil spill."
    )

    metrics = OpticalQualityMetrics(
        water_fraction=water_fraction,
        cloud_fraction=cloud_fraction,
        shadow_fraction=shadow_fraction,
        cirrus_fraction=cirrus_fraction,
        valid_pixel_fraction=valid_fraction,
        total_pixels=total_pixels,
        water_pixels=water_pixels,
        mean_ndci=mean_ndci,
        p90_ndci=p90_ndci,
        min_ndci=min_ndci,
        max_ndci=max_ndci,
        mean_ndti=mean_ndti,
        mean_swir_ratio=mean_swir_ratio,
        optical_quality_flag=flag,
        quality_summary=summary,
        scientific_disclaimer=disclaimer,
    )

    return metrics, ndci_water, ndti_water


def render_true_colour(
    b04: np.ndarray,
    b03: np.ndarray,
    b02: np.ndarray,
    output_path: Path,
) -> Path:
    """Render 10m True-Colour RGB image (Red=B04, Green=B03, Blue=B02)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # BOA reflectance typically ranges 0.0 to 0.3 for oceanic water and clouds
    # Apply a 2% to 98% percentile stretch or fixed radiometric scaling [0.0, 0.28] with gamma=1.2
    rgb = np.stack([b04, b03, b02], axis=-1)
    
    # Clip and scale
    scaled = np.clip(rgb / 0.28, 0.0, 1.0)
    # Apply gamma correction for oceanic shadow detail
    gamma_corrected = np.power(scaled, 1.0 / 1.3)
    uint8_img = (gamma_corrected * 255.0).astype(np.uint8)

    img = Image.fromarray(uint8_img, mode="RGB")
    img.save(output_path, format="PNG", optimize=True)
    return output_path


def render_false_colour(
    b11: np.ndarray,
    b08: np.ndarray,
    b04: np.ndarray,
    output_path: Path,
) -> Path:
    """Render False-Colour SWIR composite (R=SWIR1/B11, G=NIR/B08, B=Red/B04)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    swir = np.clip(b11 / 0.35, 0.0, 1.0)
    nir = np.clip(b08 / 0.30, 0.0, 1.0)
    red = np.clip(b04 / 0.25, 0.0, 1.0)

    composite = np.stack([swir, nir, red], axis=-1)
    gamma_corrected = np.power(composite, 1.0 / 1.2)
    uint8_img = (gamma_corrected * 255.0).astype(np.uint8)

    img = Image.fromarray(uint8_img, mode="RGB")
    img.save(output_path, format="PNG", optimize=True)
    return output_path


def render_scl_mask(
    scl: np.ndarray,
    output_path: Path,
) -> Path:
    """Render Scene Classification Layer (SCL) as an RGB color-coded quality map."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    h, w = scl.shape
    color_img = np.zeros((h, w, 3), dtype=np.uint8)

    for class_id, color in SCL_COLOR_LUT.items():
        mask = (scl == class_id)
        if np.any(mask):
            color_img[mask] = color

    img = Image.fromarray(color_img, mode="RGB")
    img.save(output_path, format="PNG", optimize=True)
    return output_path


def render_ndci_map(
    ndci_water: np.ndarray,
    scl: np.ndarray,
    output_path: Path,
) -> Path:
    """Render NDCI chlorophyll indicator overlay colormapped over water pixels."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    h, w = scl.shape
    out_rgb = np.zeros((h, w, 3), dtype=np.uint8)

    # Background: Dark blue for clear water, dark grey for non-water
    water_mask = (scl == SCL_WATER)
    non_water = ~water_mask
    out_rgb[non_water] = (45, 45, 45)
    out_rgb[water_mask] = (20, 45, 80)

    valid_ndci = ~np.isnan(ndci_water) & water_mask
    if np.any(valid_ndci):
        vals = ndci_water[valid_ndci]
        # Normalization range: -0.2 (low/oligotrophic) to +0.3 (dense bloom/eutrophic)
        norm = np.clip((vals - (-0.15)) / 0.40, 0.0, 1.0)

        # Simple 3-stop colormap: Deep Blue (0.0) -> Cyan (0.35) -> Yellow (0.7) -> Red (1.0)
        r = np.clip(np.where(norm < 0.5, 0.0, (norm - 0.5) * 2.0), 0.0, 1.0)
        g = np.clip(np.where(norm < 0.5, norm * 2.0, 1.0 - (norm - 0.7) * 2.0), 0.0, 1.0)
        b = np.clip(np.where(norm < 0.4, 1.0 - norm * 2.0, 0.0), 0.0, 1.0)

        ndci_colors = np.stack([r, g, b], axis=-1)
        out_rgb[valid_ndci] = (ndci_colors * 255.0).astype(np.uint8)

    img = Image.fromarray(out_rgb, mode="RGB")
    img.save(output_path, format="PNG", optimize=True)
    return output_path
