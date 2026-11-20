# Model Card: sar-oil-slick-v2.1-expanded

## 1. Overview & Architecture

- **Model Name:** `sar-oil-slick-v2.1-expanded`
- **Architecture:** `SAROilSlickMultiScaleCNN`
- **Parameter Count:** 133,466 parameters
- **Modality:** Single-channel grayscale Sentinel-1 C-SAR GRD (VV amplitude)
- **Input Resolution:** $224 \times 224$ pixels, amplitude normalized to $[-1, 1]$
- **Model Checkpoint:** [`data/models/sar/v2_expanded/best.pt`](file:///c:/Users/Shailesh/New%20folder%20%282%29/ocean-intelligence-platform/data/models/sar/v2_expanded/best.pt) (548,549 bytes)
- **Evaluation Metrics Artifact:** [`data/models/sar/v2_expanded/eval_metrics.json`](file:///c:/Users/Shailesh/New%20folder%20%282%29/ocean-intelligence-platform/data/models/sar/v2_expanded/eval_metrics.json)
- **Operational Role:** Experimental candidate screener. The rule-based `sar-detector-v1` remains the default baseline detector.

### Architecture Design Rationale
The Phase 9 `SAROilSlickCNN` (101,826 parameters) suffered from look-alike false alarms because standard $3 \times 3$ receptive fields struggle to separate sharp, localized oil slick damping boundaries from broad, gradual wind-shadow depressions. 

`SAROilSlickMultiScaleCNN` introduces a dual-branch initial layer combining parallel $3 \times 3$ (12 filters) and $5 \times 5$ (8 filters) convolutions. This structure simultaneously captures fine edge gradients along film boundaries and surrounding contextual sea-surface roughness, reducing false positive rate on natural look-alikes.

---

## 2. Dataset Provenance & Group-Aware Partitioning

### Data Source
- **Benchmark:** PANGAEA DOI [10.1594/PANGAEA.980773](https://doi.org/10.1594/PANGAEA.980773) (CC BY 4.0).
- **Publication:** Yang & Singha (2025), *"Dataset of oil slicks, look-alikes and remarkable SAR signatures obtained from Sentinel-1 data in the Eastern Mediterranean Sea"*, *Earth System Science Data* (ESSD), 17, 6807–6825.
- **Acquisitions:** Authentic Sentinel-1 C-SAR IW GRD products acquired across 2019.

### Dataset Expansion (500 Authentic Patches)
To overcome the 120-patch limitation of Phase 9, 500 verified patches were acquired from PANGAEA:
- **250 Oil Slicks (Label = 1):** 187 open-water petroleum discharges (`subset="ow"`, oil/water) and 63 coastal/port slicks (`subset="oc"`, oil/coast).
- **250 Look-Alikes (Label = 0):** 213 open-water look-alikes (`subset="nw"`, no_oil/water) and 37 near-coast look-alikes (`subset="nc"`, no_oil/coast) distributed across 17 fine-grained PANGAEA clusters:
  - 8 Normal Water clusters (`nw_c00` to `nw_c07`): low-wind calm sea surfaces, biogenic algal films, internal solitary waves, grease ice / upwelling.
  - 9 Near-Coast clusters (`nc_c00` to `nc_c08`): coastal wind shadows, sheltered bays, shallow bathymetry, organic coastal runoff.

*(Note: The Phase 10 draft report inadvertently contained a documentation typo referencing near-coast oil slicks as `nc` instead of `oc`. The underlying manifest and training data were audited in Phase 11 and verified to have 0 label mismatches against PANGAEA ground truth).*

### Scene-Stratified Group Splitting Audit
All 500 patches were assigned to Sentinel-1 SAFE acquisition footprints:
- **Train:** 320 patches (160 oil, 160 look-alike) across 297 unique SAFE scenes.
- **Validation:** 80 patches (40 oil, 40 look-alike) across 76 unique SAFE scenes.
- **Held-Out Test:** 100 patches (50 oil, 50 look-alike) across 90 unique SAFE scenes.
- **Leakage Audit Findings:** While primary acquisition scenes were partitioned, 24 out of 439 individual SAFE product slices ($5.5\%$) appear across partition boundaries (10 Train/Val, 10 Train/Test, 4 Val/Test) due to multi-slice composite scene strings (`SceneA;SceneB`). Consequently, strict scene independence was only partially achieved ($94.5\%$ disjoint), and the checkpoint remains strictly experimental.

---

## 3. Training Protocol & Validation Threshold Tuning

- **Optimizer:** AdamW ($\text{lr} = 10^{-3}$, weight decay $= 10^{-4}$).
- **Scheduler:** CosineAnnealingLR over 25 epochs.
- **Augmentation:** Random horizontal flips, vertical flips, and $90^\circ$ orthogonal rotations.
- **Hardware:** Local CPU execution (`torch 2.13.0+cpu`).
- **Validation Comparison:**
  - Standard `SAROilSlickCNN`: Peak Val F1 = 0.7742 (Val Acc = 0.7375) at epoch 11.
  - MultiScale `SAROilSlickMultiScaleCNN`: Peak Val F1 = 0.7778 (Val Acc = 0.7500) at epoch 16.
  - MultiScale selected on empirical validation performance.

### Threshold Optimization (Validation Data ONLY)
Decision thresholds from $0.35$ to $0.70$ were swept strictly across the 80 validation samples:

| Threshold | Val Accuracy | Val Precision | Val Recall | Val F1 | FP (out of 40) | FN (out of 40) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| 0.35 | 0.7000 | 0.6333 | 0.9500 | 0.7600 | 22 | 2 |
| 0.40 | 0.7125 | 0.6545 | 0.9000 | 0.7579 | 19 | 4 |
| 0.45 | 0.7375 | 0.6792 | 0.9000 | 0.7742 | 17 | 4 |
| **0.50** | **0.7500** | **0.7000** | **0.8750** | **0.7778** | **15** | **5** |
| 0.55 | 0.7375 | 0.7317 | 0.7500 | 0.7407 | 11 | 10 |
| 0.60 | 0.7125 | 0.7297 | 0.6750 | 0.7013 | 10 | 13 |
| 0.65 | 0.7125 | 0.7429 | 0.6500 | 0.6933 | 9 | 14 |
| 0.70 | 0.6500 | 0.7500 | 0.4500 | 0.5625 | 6 | 22 |

Optimal validation threshold **0.50** was chosen. The test set was NOT touched during hyperparameter or threshold selection.

---

## 4. Independent Held-Out Test Evaluation (100 Samples)

The 100 held-out test patches (50 oil slicks, 50 natural look-alikes from 82 distinct Sentinel-1 acquisitions) were evaluated once at the selected threshold of 0.50.

### Test Metrics
- **Test Set Size:** 100 patches
- **Actual Positives (Oil):** 50
- **Actual Negatives (Look-Alikes):** 50
- **True Positives (TP):** 44
- **False Positives (FP):** 17
- **True Negatives (TN):** 33
- **False Negatives (FN):** 6
- **Accuracy:** 77.00% (77/100)
- **Precision:** 72.13% (44/61)
- **Recall (Sensitivity):** 88.00% (44/50 slicks detected)
- **F1 / Dice Score:** 0.7928
- **False Positive Rate ($\text{FPR} = \frac{\text{FP}}{\text{FP} + \text{TN}}$):** 34.00% (17 of 50 actual look-alikes misclassified)
- **False Negative Rate ($\text{FNR} = \frac{\text{FN}}{\text{FN} + \text{TP}}$):** 12.00% (6 of 50 actual slicks missed)
- **Inference Latency:** 38.36 ms mean (96.82 ms p95) on CPU

---

## 5. Comparative Ablation on the Same 100 Test Samples

All three candidate detectors were evaluated on the exact same 100 held-out test patches:

| Detector | Accuracy | Precision | Recall | F1 / Dice | FPR | FNR | Missed Slicks | False Alarms |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Baseline Heuristic** (v1) | 55.00% | 64.71% | 22.00% | 0.3284 | 12.00% | 78.00% | 39 / 50 | 6 / 50 |
| **Historical V2** (120 patches) | 76.00% | 70.31% | 90.00% | 0.7895 | 38.00% | 10.00% | 5 / 50 | 19 / 50 |
| **Expanded V2.1** (500 patches) | **77.00%** | **72.13%** | 88.00% | **0.7928** | **34.00%** | 12.00% | 6 / 50 | **17 / 50** |

### Key Observations:
1. **The Heuristic Baseline Trap:** While the baseline heuristic has a low FPR (12.00%), it suffers a catastrophic 78.00% false negative rate, missing 39 of 50 real oil slicks. It achieves low false alarms solely by predicting negative on almost every input.
2. **Expansion Reduces False Alarms:** The expanded multi-scale V2.1 model reduces the false alarm rate from 38.00% to 34.00% on the 100-sample test set (and down from 53.33% on the historical 30-sample set), while improving precision to 72.13% and maintaining strong candidate recall (88.00%).

---

## 6. Physical Look-Alike Breakdown & Error Analysis

The 17 test false alarms occurred in the following look-alike categories:

| Look-Alike Category | Cluster Code | Count | Physical Damping Mechanism |
| :--- | :---: | :---: | :--- |
| Near-Coast Sheltered Bays | `nc_c01` | 3 | Coastal terrain blocks wind; specular reflection resembles slick. |
| Open-Water Low-Wind Sea | `nw_c03` | 2 | Wind speed $<3\text{ m/s}$ generates zero capillary waves. |
| Biogenic Algal Films | `nw_c06` | 2 | Organic surfactant films dampen high-frequency surface ripple. |
| Coastal Wind Shadows | `nc_c04` | 2 | Headlands cast wind shadow over lee water surface. |
| Open-Water Low Wind Cells | `nw_c05` | 2 | Localized calm cells within open-sea wind field. |
| Internal Solitary Waves | `nw_c02` | 2 | Wave troughs modulate surface tension and damp roughness. |
| Open-Water Low Wind | `nw_c04` | 1 | Calm patch in open sea. |
| Open-Water Low Wind | `nw_c01` | 1 | Calm water patch. |
| Near-Coast Wind Shadow | `nc_c00` | 1 | Land breeze interface. |
| Near-Coast Harbor Area | `nc_c02` | 1 | Shallow water and harbor breakwater calm zone. |

### Operational Guidance:
Radar backscatter physics dictates that single-polarization (VV) SAR amplitude cannot definitively distinguish biogenic films or low wind from petroleum without auxiliary physical data. Therefore, `sar-oil-slick-v2.1-expanded` must be deployed with:
1. **ECMWF 10m Wind Speed Downgrade:** If local 10m wind speed $<3.0\text{ m/s}$, any candidate detection confidence is halved.
2. **Optical Triangulation:** Positive candidates must trigger cross-examination against Sentinel-2 MSI / Landsat-8 RGB and NDVI/NDWI indices.
3. **Geographic Limitation:** This model was trained on Eastern Mediterranean Sentinel-1 passes. It has NOT been validated on Indian coastal waters (e.g. Mumbai High, Gulf of Khambhat) without local ground-truth benchmarks.
