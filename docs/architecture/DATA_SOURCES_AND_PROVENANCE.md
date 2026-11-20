# OceanAI Data Sources, Acquisition & Provenance Specification
**Project:** OceanAI — India Water Intelligence & Marine Intelligence Platform  
**Document:** `docs/architecture/DATA_SOURCES_AND_PROVENANCE.md`  
**Status:** Living Engineering Reference  
**Last Updated:** November 12, 2026  

---

## 1. Overview & Data Provenance Philosophy

OceanAI combines heterogeneous Earth Observation (EO) data streams, meteorological reanalysis, vessel tracking, and geospatial boundaries. Scientific integrity requires that each data stream maintains its own provenance records, calibration flags, and physical unit conventions.

---

## 2. Integrated Data Sources

### 2.1 Sentinel-1 C-Band Synthetic Aperture Radar (SAR)
- **Agency:** European Space Agency (ESA) / Copernicus Programme
- **Instrument:** C-band Synthetic Aperture Radar (5.405 GHz)
- **Product Type:** Level-1 Ground Range Detected (GRD), Interferometric Wide Swath (IW), 10m spatial resolution.
- **Polarizations:** VV + VH (dual-pol).
- **Physical Phenomenon:** Bragg wave scattering suppression by viscous surface films. Capillary waves ($1.7 - 7\text{ cm}$) are damped by thin monomolecular or thicker petroleum slicks, resulting in reduced backscatter (radar dark patches).
- **Provenance Record:** Stored in database table `sar_candidates` with original scene identifiers, acquisition timestamps, and spatial coordinates.

### 2.2 ECMWF ERA5 Atmospheric Reanalysis
- **Agency:** European Centre for Medium-Range Weather Forecasts (ECMWF) / Copernicus Climate Change Service (C3S)
- **Product:** ERA5 hourly estimates of 10m atmospheric wind components ($u_{10}, v_{10}$).
- **Spatial Resolution:** $0.25^\circ \times 0.25^\circ$ regular lat-lon grid (~31 km).
- **Temporal Resolution:** 1 hour.
- **Physical Interpretation:**
  - $w < 3.0\text{ m/s}$: **Low-Wind Ambiguity**. Natural calm water produces specular reflection away from the radar antenna, creating widespread dark lookalikes indistinguishable from oil.
  - $3.0 \le w \le 12.0\text{ m/s}$: **Diagnostic Window**. Optimal wind range where sea clutter provides contrast and oil films reliably damp waves.
  - $w > 12.0\text{ m/s}$: **High-Wind Ambiguity**. Intense wave breaking physically disperses surface slicks into droplets.
- **Provenance Record:** Stored in `sar_candidates` columns (`wind_speed_ms`, `wind_direction_deg`, `grid_latitude`, `grid_longitude`, `grid_distance_km`, `temporal_offset_minutes`).

### 2.3 Copernicus Sentinel-2 Multi-Spectral Instrument (MSI)
- **Agency:** European Space Agency (ESA) / Copernicus Programme
- **Endpoint:** Copernicus Data Space Ecosystem (CDSE) STAC v1 (`https://stac.dataspace.copernicus.eu/v1/`)
- **Collection:** `sentinel-2-l2a` (Bottom-of-Atmosphere surface reflectance).
- **Spectral Bands:**
  - 10m VNIR: B02 (Blue), B03 (Green), B04 (Red), B08 (NIR)
  - 20m Red-Edge / SWIR: B05, B06, B07, B11, B12, SCL (Scene Classification Layer)
- **Physical Role:** Provides corroborative multispectral context:
  - Visual true-colour RGB (B04, B03, B02).
  - Scene Classification Layer (SCL) for automated water (class 6), cloud (classes 8-10), and cloud shadow (class 3) masking.
  - Normalized Difference Chlorophyll Index (NDCI):
    $$\text{NDCI} = \frac{B05 - B04}{B05 + B04}$$
    Strictly utilized as an indicator of algal blooms and suspended vegetation, never as proof of an oil spill.

### 2.4 Automatic Identification System (AIS) Vessel Data (Phase 15)
- **Sources:** Terrestrial receivers and satellite AIS (S-AIS) records.
- **Data Elements:** MMSI, IMO, vessel name, ship type, timestamp (UTC), latitude, longitude, Speed Over Ground (SOG), Course Over Ground (COG), heading.
- **Matching Window:** Gated spatio-temporal interpolation aligned to SAR acquisition timestamps.

### 2.5 Oceanographic Current Models (Phase 16)
- **Sources:** Copernicus Marine Service (CMEMS) Global Ocean Physics Analysis and Forecast ($1/12^\circ$ resolution, ~9 km).
- **Variables:** Surface zonal ($u$) and meridional ($v$) current velocities.
- **Role:** Driving hydrodynamic forcing for Lagrangian oil drift particles.

---

## 3. Data Integrity & Storage Rules

1. **Local Object Storage:** Native imagery chips and visualizations are persisted in:
   `data/objects/evidence/marine/{candidate_id}/{scene_id}/`
2. **Immutability of Historical Evidence:** Once an optical evidence record or ERA5 reanalysis point is captured, it is linked immutably to the SAR candidate.
3. **Additive Migrations:** Database schema enhancements use additive Alembic scripts without deleting or mutating historical benchmark evaluations.
