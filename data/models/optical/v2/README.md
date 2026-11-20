# OceanAI Optical Water Pollution Detector V2 — Architecture & Model Card Specification

This directory is designated for **Vision Model V2** artifacts, keeping them strictly separated from the inherited V1 baseline (`data/models/optical/best.pt`).

---

## 1. Directory Structure

```
data/models/optical/v2/
├── best.pt                 # (When trained/verified) Best checkpoint for V2
├── config.yaml             # Model architecture & hyperparameter configuration
├── dataset_manifest.json   # Exact dataset splits and provenance hashes
├── class_mapping.json      # Mapping from class index to V2 signatures
├── train_metrics.json      # Detailed epoch-by-epoch loss & validation metrics
├── test_evaluation.json    # Verified evaluation report against held-out test split
└── README.md               # Model card and operational guide (this file)
```

---

## 2. Redesigned Detection Task & Class Taxonomy

The V1 checkpoint was trained on four classes: `{0: 'oil_spill', 1: 'algae_bloom', 2: 'plastic_waste', 3: 'chemical_pollution'}`.

### Identified Deficiencies in V1:
1. **Chemical Pollution from RGB**: Dissolved chemical pollutants (e.g. nitrates, heavy metals, industrial solvents) cannot be identified from RGB pixel values. Labeling optical discolouration as "chemical_pollution" is scientifically indefensible.
2. **Algae Bloom Bounding Boxes**: Algal blooms are fluid, continuous phenomena. Forcing a bounding box produces arbitrary boundaries and high false-positive rates with duckweed, sediment, and water shadow.
3. **Resolution Mismatch**: Small plastic debris (bottles, bags) is invisible in 10-meter Sentinel-2 pixels; optical YOLO is only valid on sub-meter aerial/drone imagery or river boom surveillance.

### Vision V2 Proposed Taxonomy:
| V2 Class ID | Trained Label | Defensible Physical Signature | Sensing Modality & Context |
|---|---|---|---|
| `0` | `oil_slick_candidate` | `OIL_LIKE_SIGNATURE` | High-res optical glint or SAR C-band dark patch |
| `1` | `algae_bloom_optical` | `ALGAE_BLOOM_SIGNATURE` | High-chlorophyll optical reflectance (NDCI-correlated) |
| `2` | `floating_plastic_debris` | `PLASTIC_DEBRIS_SIGNATURE` | Macro-litter accumulation in high-res optical imagery |
| `3` | `surface_discolouration_plume` | `SURFACE_ANOMALY` | Suspended sediment / effluent plume (never chemical species) |

---

## 3. Data Requirements for V2 Training

Training V2 must strictly comply with the **Non-Negotiable Constraints**:
- **No Fabricated Labels**: Training must use verified real-world imagery with human-curated or sensor-verified annotations.
- **Scene-Level Stratification**: Training, validation, and test splits must be partitioned by satellite scene footprint / acquisition date to prevent spatial autocorrelation and data leakage.
- **Minimum Dataset Scale**:
  - Minimum 1,500 annotated scenes/tiles across diverse lighting, water turbidities, and geographic environments.
  - Balanced class distribution across the 4 redesigned classes.
- **Evaluation Gate**: The candidate model must outperform the baseline on an independent, non-overlapping test set with verified mAP@50 and IoU metrics before replacing V1 in production.

---

## 4. Current Status

- **Status**: `ARCHITECTURE_SPECIFIED_AWAITING_LABELED_DATASET`
- **Fallback**: System maintains `data/models/optical/best.pt` (V1 baseline) as the active operational detector, with graceful fallback to `mock-detector` if weights are absent.
