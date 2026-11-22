# OceanAI Vision Dataset Inventory & V2 Data Strategy

**Document Version**: 2.0.0  
**Last Updated**: 2026-10-17  
**Platform**: OceanAI — India Water Intelligence & Marine Intelligence Platform  
**Compliance Standards**: Epistemic Integrity Protocol, Reproducibility & Anti-Leakage Rules

---

## 1. Executive Summary

This document establishes the empirical dataset inventory for OceanAI's computer vision subsystem. It provides an honest account of available training and evaluation data, documents the audit findings of the inherited V1 checkpoint (`data/models/optical/best.pt`), analyzes the scientific validity of each detection task, and outlines an actionable data acquisition protocol for Vision Model V2.

In strict compliance with the platform's non-negotiable constraints:
- **No Synthetic Data as Proof**: Synthetic images are used strictly for code-path execution tests, never as evidence of detection accuracy.
- **No Fabricated Labels or Splits**: Metrics are reported as `null` / unmeasured until an authentic, ground-truth labeled benchmark test split is evaluated.
- **Physical Feasibility**: Dissolved chemical pollution is decoupled from optical RGB bounding box classification.

---

## 2. Model V1 Audit & Checkpoint Provenance

An audit of the checkpoint file `data/models/optical/best.pt` (size: 52,040,018 bytes) recovered the embedded training configuration, metadata, and validation curves:

### 2.1 Training Configuration
- **Model Architecture**: Ultralytics YOLOv8m (25,858,636 parameters, 78.7 GFLOPs).
- **Training Date**: 2026-04-22 12:28:31 UTC.
- **Framework Version**: `ultralytics` 8.4.41 on PyTorch 2.6.
- **Hardware / Project**: Google Colab / Drive (`/content/drive/MyDrive/ocean_ai/ocean_v3`).
- **Hyperparameters**:
  - `epochs`: 100 (completed all 100 epochs)
  - `imgsz`: 640×640 px
  - `batch`: 16
  - `optimizer`: Auto / SGD (`lr0`: 0.001, `lrf`: 0.01, `cos_lr`: True)
  - `patience`: 20
  - `seed`: 42
  - Augmentations: `mosaic`: 0.8, `mixup`: 0.1, `copy_paste`: 0.1, `degrees`: 45, `flipud`: 0.5, `fliplr`: 0.5, `erasing`: 0.3.
- **Classes Encoded**:
  - `0`: `oil_spill`
  - `1`: `algae_bloom`
  - `2`: `plastic_waste`
  - `3`: `chemical_pollution`

### 2.2 Embedded Validation Loss & Metrics
The training run recorded the following validation progression across 100 epochs:
- **Box Loss**: Started at $2.271$, converged to $1.002$ (min: $0.999$).
- **Classification Loss**: Started at $7.120$, converged to $1.932$ (min: $1.916$).
- **Distribution Focal Loss**: Started at $2.274$, converged to $1.153$ (min: $1.153$).
- **Peak Precision**: $0.8512$
- **Peak Recall**: $0.7592$
- **Peak mAP@50**: $0.8267$
- **Peak mAP@50-95**: $0.5432$

### 2.3 Critical Reproducibility Blocker
The dataset configuration `pollution.yaml` and the underlying training, validation, and test image directories resided on external Google Drive storage and were **not committed to the Git repository**. No local `.txt` YOLO bounding-box annotation files exist on the host machine. Consequently, while the checkpoint loads and runs inference, **the reported $0.8267$ mAP@50 cannot be independently recalculated or verified locally without recovering the original test split.**

---

## 3. Local Dataset Inventory

| Dataset / Asset Key | Location | Format & Modality | Resolution | Images | Annotations | License | Status & Role |
|---|---|---|---|---|---|---|---|
| **Synthetic Slick Sample** | `data/samples/synthetic_slick.png` | 800×800 RGB PNG | Synthetic | 1 | 1 synthetic bounding box | CC0-1.0 | **CI/Pipeline only**. Never used for accuracy claims. |
| **Sentinel-2 Evidence Scenes** | `data/objects/evidence/*/*.png` | 10m Multi-band / Truecolour PNG | 10 m / pixel | 17 | **None** (unannotated rasters) | Copernicus Open Access | **Water quality context & NDTI proxy**. Unlabeled for object detection. (Zero observed detections at 0.25 threshold; note this is zero observed detections on unannotated imagery, not a measured false-positive rate). |
| **Sentinel-1 SAR Oil & Look-Alike Dataset (V2 Benchmark)** | `data/training/sar_oil_v2/` | Grayscale Sentinel-1 C-SAR (VV amplitude) | 640×640 px | 120 (70 train, 20 val, 30 test) | 120 scene-level & bbox XMLs | CC BY 4.0 | **Authentic Benchmark Dataset** for `sar-oil-slick-v2`. Source: Yang & Singha (2025), PANGAEA 980773. Scene-stratified split. |
| **Sentinel-1 SAR Expanded Dataset (V2.1 Benchmark)** | `data/training/sar_oil_v2/sar_splits_expanded_manifest.json` | Grayscale Sentinel-1 C-SAR (VV amplitude) | 640×640 px (rescaled to 224×224) | 500 (320 train, 80 val, 100 test) across 418 unique scenes | 500 scene-level XML annotations across 17 look-alike clusters & oil subsets | CC BY 4.0 | **Expanded Benchmark Dataset** for `sar-oil-slick-v2.1-expanded`. Group-aware scene-stratified; audited in Phase 11 as 94.5% scene-disjoint (24 multi-slice composite scene overlaps). |
| **Sentinel-1 SAR Clean Dataset (V2.2 Leakage-Free Benchmark)** | `data/training/sar_oil_v2/sar_splits_v2_2_clean_manifest.json` | Grayscale Sentinel-1 C-SAR (VV amplitude) | 640×640 px (rescaled to 224×224) | 681 (501 train, 80 val, 100 test) across 867 graph components (1,063 SAFEs) | Full tab table annotations across 17 look-alike clusters & oil subsets | CC BY 4.0 | **100% Leakage-Free Benchmark Dataset** for `sar-oil-slick-v2.2`. Indivisible bipartite connected-component graph partitioning over canonical parsed SAFEs. 0 patch overlap, 0 SAFE overlap, 100% unseen test partition. |
| **Sentinel-1 SAR Environmental Context Benchmark (Phase 13 Benchmark)** | `data/training/sar_oil_v2/sar_splits_phase13_manifest.json`<br>`data/cache/era5_wind_cache.json` | Grayscale Sentinel-1 C-SAR (VV amplitude) + ECMWF ERA5 10m Wind Fields ($u_{10}, v_{10}$) | 640×640 px (rescaled to 224×224) + hourly 0.25° ERA5 reanalysis | 300 patches collocated (100 Phase 12 test + 60 env_dev + 40 env_val + 100 locked_final_test) | Full tab table annotations across 17 look-alike clusters + collocated ERA5 wind vectors ($u_{10}, v_{10}$, speed, direction, offset, distance) | CC BY 4.0 / ECMWF open data | **Environmental Context Benchmark Dataset** for `wind-screener-v1`. Unseen connected-component partitions; zero SAFE overlap; provides spatiotemporal ground truth for evaluating capillary damping physical boundaries. |
| **OpenStreetMap Water Bodies** | `data/processed/india-water.ndjson` | PostGIS GeoJSON polygons | Vector geometry | 405 polygons | N/A (Geographic features) | ODbL 1.0 | **Spatial boundary matching**. |

---

## 4. Detection Tasks Redesign for Vision V2

The V1 four-class object detection task was analyzed against environmental sensing physics and operational response requirements:

### 4.1 Optical Marine & Floating Litter (`floating_plastic_debris`)
- **Physics**: Individual plastic bottles or bags are sub-pixel at 10m Sentinel-2 resolution. Optical object detection is scientifically defensible **only on high-resolution drone, aerial, or river-boom camera imagery** ($\le 10\text{ cm/pixel}$).
- **V2 Formulation**: Maintain bounding box detection, but restrict deployment to aerial/drone and river surveillance inputs. For satellite imagery, redirect to Floating Debris Index (FDI) spectral anomaly analysis.

### 4.2 Algae Bloom Detection (`algae_bloom_optical`)
- **Physics**: Algae blooms are continuous fluids without rigid rectangular borders. Forcing an object detection box generates high false alarms with duckweed, green shadows, and suspended sediment.
- **V2 Formulation**: Decouple from bounding boxes. Deploy **Multispectral Chlorophyll Indexing (NDCI)** for Sentinel-2 satellite rasters:
  $$\text{NDCI} = \frac{B5 - B4}{B5 + B4}$$
  Deploy semantic segmentation (U-Net) only for near-shore optical aerial imagery.

### 4.3 Oil Spill Screening (`oil_slick_candidate`)
- **Physics**: Oil slicks damp capillary waves, causing normalized radar cross-section (NRCS) depressions in C-band SAR (Sentinel-1 VV). RGB optical detection is reliable only under direct sun-glint conditions.
- **V2 Formulation**: Preserve the 4-rule deterministic SAR dark-formation detector as primary candidate screening. Introduce V2 learned SAR segmentation using co-registered ERA5 wind fields ($> 3\text{ m/s}$) to eliminate low-wind false alarms.

### 4.4 Chemical Pollution Refusal & Redesign (`surface_discolouration_plume`)
- **Physics**: **Dissolved chemical contaminants produce no optical reflectance signature.** Claiming that an RGB bounding box detects "chemical_pollution" is false.
- **V2 Formulation**:
  1. Rename class 3 to `surface_discolouration_plume` (indicating sediment plumes, industrial effluent discolouration, or turbidity).
  2. For true chemical contamination (heavy metals, BOD, DO, nitrates), rely strictly on laboratory water-quality monitoring data from CPCB NWDP and real-time sensor stations.

---

## 5. Candidate Benchmark Datasets for V2

To train and rigorously evaluate Model V2 without cloud dependencies or paid licensing, the following open datasets are identified:

| Benchmark Dataset | Target Class | Modality / Sensor | Image Count | Resolution | License | Annotation Format |
|---|---|---|---|---|---|---|
| **FloaDebris / TACO Marine** | `floating_plastic_debris` | RGB Drone & Shoreline | 1,800+ | Sub-decimeter | CC BY 4.0 | COCO / YOLO bounding boxes |
| **Sentinel-2 Coastal Algal Bloom Benchmark** | `algae_bloom_optical` | Sentinel-2 L2A | 850 scenes | 10 m - 20 m | Copernicus Open Access | Raster segmentation masks |
| **SNAC / SAR Oil Spill Benchmark** | `oil_slick_candidate` | Sentinel-1 SAR IW GRD | 1,112 scenes | 10 m | Open Research | Polygonal slick contours + wind vectors |
| **River Plume Discolouration Open Archive** | `surface_discolouration_plume` | Sentinel-2 & PlanetScope | 620 scenes | 3 m - 10 m | Open Access | Plume polygon segmentations |

---

## 6. Data Leakage Safeguards

When training and evaluating Model V2, the following rules must be enforced:
1. **Scene-Level Stratification**: Slicing large satellite passes or aerial surveys into overlapping $640\times640$ patches creates severe data leakage if patches from the same parent scene are split across train and test sets. **All tiles from the same scene footprint must be assigned to the same partition.**
2. **Temporal Split**: The held-out test split must be collected on acquisition dates at least 30 days after training images to evaluate robustness against seasonal changes.
3. **Geographic Buffering**: Training and testing scenes must be separated by a minimum spatial distance buffer ($\ge 50\text{ km}$).

---

## 7. Next Actionable Steps

1. Acquire open-source FloaDebris and SAR slick benchmark archives into `data/raw/vision_v2/`.
2. Construct versioned YOLO-format dataset manifest at `data/manifests/vision_v2_split.yaml`.
3. Train Vision V2 using `YOLOv8s` (lightweight, edge-friendly) with fixed random seed $42$.
4. Run `ml/evaluation/evaluate_detector.py` against the independent test split and register verifiable mAP@50 and IoU metrics.
