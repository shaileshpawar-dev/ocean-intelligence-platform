# OceanAI Reference Repositories & Algorithmic Foundations
**Project:** OceanAI — India Water Intelligence & Marine Intelligence Platform  
**Location:** `docs/architecture/REFERENCE_REPOSITORIES.md`  
**Status:** Approved Reference Specification  
**Last Updated:** November 12, 2026  

---

## 1. Purpose and Policy

To develop OceanAI into an advanced Marine Intelligence Platform, we study proven open-source implementations in satellite earth observation, radar processing, vessel tracking, and particle trajectory simulation. 

> [!IMPORTANT]
> **Strict Intellectual Property & Licensing Compliance Policy:**
> - Under no circumstances shall external code, weights, or datasets be blindly copied or incorporated without explicit license review.
> - Code licenses do not necessarily grant rights to accompanying pre-trained weights or underlying datasets.
> - Where licenses impose strong copyleft restrictions (e.g., GPL-2.0, GPL-3.0) or share-alike constraints (CC BY-SA 4.0), OceanAI adopts a **clean-room implementation approach**: we study the published mathematical formulations, spectral equations, and data flows, and implement native, clean-room Python/FastAPI and React/TypeScript architectures.

---

## 2. Technical Reference Repositories

### 2.1 SAR Oil-Spill Detection & Full-Scene Processing
- **Repository:** [`https://github.com/m7mdehab/oil-spill-detection`](https://github.com/m7mdehab/oil-spill-detection)
- **Primary Authors/Maintainers:** Mohamed Ehab et al.
- **Key Concepts to Study:**
  - Semantic segmentation architectures for radar backscatter: SegFormer, U-Net, DeepLabV3+.
  - Sentinel-1 GRD (Ground Range Detected) preprocessing: thermal noise removal, radiometric calibration ($\sigma^0$), speckle filtering (Lee filter), and range Doppler terrain correction.
  - Tiled inference across large SAR footprints ($250\text{ km} \times 250\text{ km}$) using sliding windows with 25%–50% overlap to prevent tile-boundary edge artifacts.
  - Post-processing: confidence thresholding, raster-to-polygon vectorization, and geospatial reconstruction into standard GeoTIFF and GeoJSON formats.
- **OceanAI Application:** Guides the transition from patch-level CNN classification (SAR V2.2) to full-scene overlapping-window inference (Phase 14.2).

### 2.2 Modular Earth-Observation Framework
- **Repository:** [`https://github.com/sentinel-hub/eo-learn`](https://github.com/sentinel-hub/eo-learn)
- **Primary Authors/Maintainers:** Sentinel Hub / Sinergise
- **License:** MIT License
- **Key Concepts to Study:**
  - Modular EOPatch data structures encapsulating multi-temporal feature rasters (DATA), masks (MASK), scalar metrics (SCALAR), and vector features (VECTOR).
  - Spatial/temporal co-registration pipelines matching heterogeneous sensors (Sentinel-1 SAR, Sentinel-2 MSI, Landsat 8/9).
  - Workflow graph abstraction executing idempotent transformations across caching tiers.
- **OceanAI Application:** Informs the multi-sensor evidence fusion pipeline (Phase 14.3) and standardized raster caching conventions.

### 2.3 Sentinel-2 Water Quality & Spectral Indices
- **Repository:** [`https://github.com/iliasmachairas/WaterQual`](https://github.com/iliasmachairas/WaterQual)
- **Primary Authors/Maintainers:** Ilias Machairas
- **License:** GPL-2.0-or-later
- **Key Concepts to Study:**
  - Sentinel-2 Level-2A Bottom-of-Atmosphere (BOA) reflectance band extraction.
  - Normalized Difference Chlorophyll Index (NDCI):
    $$\text{NDCI} = \frac{\rho_{705} - \rho_{665}}{\rho_{705} + \rho_{665}} = \frac{B05 - B04}{B05 + B04}$$
  - Normalized Difference Turbidity Index (NDTI):
    $$\text{NDTI} = \frac{\rho_{665} - \rho_{560}}{\rho_{665} + \rho_{560}} = \frac{B04 - B03}{B04 + B03}$$
  - Automated Scene Classification Layer (SCL) pixel masking for water isolation (class 6).
- **OceanAI Application:** Forms the algorithmic basis for the `MarineOpticalScreener` (Phase 14.1). Note: In OceanAI, NDCI is strictly treated as an environmental indicator of algal biomass and turbidity, **never** an automated confirmation of petroleum hydrocarbons.

### 2.4 Cloud Detection & Preprocessing
- **Repository:** [`https://github.com/sentinel-hub/sentinel2-cloud-detector`](https://github.com/sentinel-hub/sentinel2-cloud-detector) (`s2cloudless`)
- **Primary Authors/Maintainers:** Sentinel Hub
- **License:** CC BY-SA 4.0
- **Key Concepts to Study:**
  - Multi-spectral pixel classification for cloud probability mapping using VNIR and SWIR bands (B01, B02, B04, B05, B08, B8A, B09, B10, B11, B12).
  - Cloud shadow projection based on sun azimuth and zenith angles.
  - Distinguishing cloud from highly reflective sea surfaces (sunglint) using SWIR band absorption.
- **OceanAI Application:** Informs sunglint detection and local candidate pixel-buffer masking.

### 2.5 SAR and AIS Vessel Association
- **Repository:** [`https://github.com/gSulpizio/sat_tracker`](https://github.com/gSulpizio/sat_tracker)
- **Primary Authors/Maintainers:** Giorgio Sulpizio
- **Key Concepts to Study:**
  - Automated association between SAR bright-point targets (vessels) and broadcast Automatic Identification System (AIS) messages.
  - Spatial-temporal gating: interpolating vessel trajectories between AIS pings to match the exact SAR acquisition millisecond.
  - Global optimal assignment using the Hungarian (Munkres) algorithm under distance and heading velocity constraints.
  - Interactive analyst review interfaces for inspecting matched vessel identities, MMSI/IMO, vessel types, and flag states.
- **OceanAI Application:** Directly guides Phase 15 AIS intelligence architecture.

### 2.6 Maritime Anomaly Intelligence
- **Repository:** [`https://github.com/Korunil/navisight`](https://github.com/Korunil/navisight)
- **Primary Authors/Maintainers:** Korunil
- **License:** Apache-2.0
- **Key Concepts to Study:**
  - Vessel trajectory sequence encoding and trajectory representation learning.
  - Anomaly detection: identifying suspicious behavior (AIS transponder spoofing, unexpected mid-ocean stops, loitering, dark-vessel rendezvous).
  - Fast nearest-neighbor vector similarity search using Hierarchical Navigable Small World (HNSW) graphs.
- **OceanAI Application:** Enhances Phase 15 vessel risk scoring and source attribution analysis.

### 2.7 Oil-Spill Trajectory & Particle Modelling
- **Repository:** [`https://github.com/OpenDrift/opendrift`](https://github.com/OpenDrift/opendrift)
- **Primary Authors/Maintainers:** Norwegian Meteorological Institute (MET Norway)
- **License:** GPLv2
- **Key Concepts to Study:**
  - Lagrangian particle trajectory simulation in oceanographic velocity fields.
  - Environmental forcing: integration of surface ocean currents ($u, v$), atmospheric wind drag (3% wind factor with leeway angle), and Stokes wave drift.
  - Weathering processes: evaporation, emulsification, natural dispersion, dissolution, and shoreline stranding (beaching).
  - Ensemble simulation accounting for meteorological and current forecast uncertainties.
- **OceanAI Application:** Defines the computational requirements and input specifications for Phase 16 drift simulation.

---

## 3. License Assessment and Architecture Strategy

| Reference Repository | Stated License | Code Ingestion Permitted? | Architecture Strategy |
|---|---|---|---|
| `oil-spill-detection` | MIT / Academic | Clean-room study | Study tiled inference and segmentation logic; implement native OceanAI pipeline. |
| `eo-learn` | MIT | Permitted | Utilize concepts for feature structuring and spatial co-registration. |
| `WaterQual` | GPL-2.0-or-later | No (Copyleft) | Independent clean-room implementation of NDCI, NDTI, and SCL masking in FastAPI. |
| `s2cloudless` | CC BY-SA 4.0 | No (Share-Alike) | Rely on official CDSE Level-2A pre-computed SCL and SWIR ratios natively. |
| `sat_tracker` | Unspecified / Open | Clean-room study | Re-implement spatial gating, track interpolation, and Hungarian assignment natively. |
| `navisight` | Apache-2.0 | Permitted with notice | Incorporate trajectory embedding algorithms and distance metrics. |
| `opendrift` | GPLv2 | Isolated CLI / API Only | Do not link directly as a library; build clean-room numerical particle integration or invoke via external process. |

---

## 4. Verification Checkpoint

All mathematical formulas, band wavelengths, and spatial algorithms in OceanAI are verified against peer-reviewed remote sensing literature and official ESA Copernicus documentation.
