# Model Card: `sar-oil-slick-v2.2` (Leakage-Free SAR Oil Slick Screener)

## 1. Model Overview

| Property | Value |
|---|---|
| **Model Key** | `sar-oil-slick-v2.2` |
| **Model Version** | `2.2.0-experimental` |
| **Architecture** | `SAROilSlickMultiScaleCNN` |
| **Parameter Count** | 133,466 parameters |
| **Input Modality** | Grayscale Sentinel-1 C-SAR GRD (VV amplitude) |
| **Input Resolution** | 224×224 px, normalized to $[-1, 1]$ |
| **Output Classes** | `look_alike` (0), `oil_slick_candidate` (1) |
| **Framework** | PyTorch 2.6 |
| **Checkpoint Path** | `data/models/sar/v2_2_scene_clean/best.pt` (548 KB) |
| **Training Date** | 2026-11-03 |
| **License** | CC BY 4.0 |
| **Role & Stance** | Experimental candidate screener. Default baseline remains `sar-detector-v1`. |

---

## 2. Dataset Provenance & Leakage-Free Partitioning

### 2.1 Benchmark Origin
Trained and evaluated on the peer-reviewed benchmark dataset:
> **Yang & Singha (2025)**, *"Dataset of oil slicks, look-alikes and remarkable SAR signatures obtained from Sentinel-1 data in the Eastern Mediterranean Sea"*, Earth System Science Data (ESSD), DOI: [10.5194/essd-17-6807-2025](https://doi.org/10.5194/essd-17-6807-2025). Hosted on PANGAEA: DOI [10.1594/PANGAEA.980773](https://doi.org/10.1594/PANGAEA.980773).

### 2.2 Canonical SAFE Identifier Parsing & Graph Partitioning
The full PANGAEA annotation table (3,655 patches) was parsed using a canonical Sentinel-1 SAFE parser that splits semicolon-separated composite strings (`SceneA;SceneB`).

An indivisible bipartite connected-component graph was constructed where each connected component represents an isolated cluster of patches sharing one or more Sentinel-1 acquisition footprints:
- **Total Patches in Dataset**: 3,655
- **Unique SAFE Identifiers**: 1,063
- **Total Connected Components**: 867
- **Phase 9 / 10 Development Components**: 412
- **Strictly Unseen Components**: 455

### 2.3 Partition Guarantees

| Partition | Patches | Oil Slicks | Look-Alikes | Connected Components | Unique SAFEs | Unseen Origin |
|---|---|---|---|---|---|---|
| **Train** | 501 | 248 | 253 | 346 | 483 | Development pool |
| **Validation** | 80 | 40 | 40 | 66 | 73 | Development pool |
| **Test** | 100 | 50 | 50 | 43 | 46 | **100% Unseen** |

**Zero-Leakage Audit:**
- Patch Overlap across Train / Val / Test: **0** ($0.0\%$)
- Sentinel-1 SAFE Overlap across Train / Val / Test: **0** ($0.0\%$)
- Connected-Component Overlap: **0** ($0.0\%$)
- Test Partition Unseen Proof: None of the 43 test connected components or 46 test SAFEs were ever exposed in Phase 9 or Phase 10.

Manifest saved at: `data/training/sar_oil_v2/sar_splits_v2_2_clean_manifest.json`.

---

## 3. Training & Validation

- **Hardware**: Host CPU (Windows)
- **Schedule**: 25 epochs, batch size 16, Adam optimizer ($\text{lr}=10^{-3}$, weight decay $10^{-4}$), Cross-Entropy Loss with class weighting ($w_{\text{oil}} = 1.0202, w_{\text{look}} = 1.0000$).
- **Total Training Duration**: 784.0s (13.07 min).
- **Peak Validation**: Epoch 16 (Val Loss: 0.5331, Val Accuracy: 78.75%, Val F1: 0.8172).
- **Decision Threshold Sweep**: Swept over thresholds $0.35$ to $0.70$ on validation data only. Selected optimal threshold: **0.50** ($\text{Val F1} = 0.8172$).

---

## 4. Fair 4-Model Test Evaluation (Same 100 Unseen Samples)

All four models evaluated on the exact same 100 held-out unseen test samples (50 oil slicks, 50 look-alikes):

| Model | Architecture / Method | TP | FP | TN | FN | Accuracy | Precision | Recall | F1 Score | FPR | FNR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Baseline Heuristic (v1)** | Backscatter contrast threshold | 7 | 6 | 44 | 43 | 51.00% | 53.85% | 14.00% | 0.2222 | 12.00% | 86.00% |
| **Historical SAR V2 (120-patch)** | `SAROilSlickCNN` (101k params) | 46 | 20 | 30 | 4 | 76.00% | 69.70% | 92.00% | 0.7931 | 40.00% | 8.00% |
| **Expanded SAR V2.1 (500-patch)** | `SAROilSlickMultiScaleCNN` (133k params) | 46 | 20 | 30 | 4 | 76.00% | 69.70% | 92.00% | 0.7931 | 40.00% | 8.00% |
| **New SAR V2.2 (Scene-Clean)** | `SAROilSlickMultiScaleCNN` (133k params) | 44 | 21 | 29 | 6 | 73.00% | 67.69% | 88.00% | 0.7652 | 42.00% | 12.00% |

---

## 5. Statistical Significance Testing (McNemar's Test)

- **V2.2 vs Expanded V2.1**:
  - Contingency: $b = 4$ (V2.2 correct, V2.1 incorrect), $c = 7$ (V2.1 correct, V2.2 incorrect).
  - McNemar Statistic with continuity correction: $\chi^2 = 0.3636$, **$p = 0.5488$**.
  - **Conclusion**: The difference between V2.2 and V2.1 is **not statistically significant**.
- **V2.2 vs Historical V2**:
  - Contingency: $b = 7$, $c = 10$.
  - McNemar Statistic: $\chi^2 = 0.2353$, **$p = 0.6291$**.
  - **Conclusion**: The difference between V2.2 and Historical V2 is **not statistically significant**.
- **V2.2 vs Baseline Heuristic (v1)**:
  - Contingency: $b = 38$, $c = 16$.
  - McNemar Statistic: $\chi^2 = 8.3519$, **$p = 0.0038$**.
  - **Conclusion**: V2.2 significantly outperforms the baseline heuristic in slick detection ($p < 0.01$).

---

## 6. Physical Look-Alike Error Analysis

On the 100 held-out unseen test samples, V2.2 generated 21 false positives across the 50 look-alike patches:
- **Biogenic Algal Films (`nw_c06`)**: 4 false positives
- **Low-Wind Calm Sea Surfaces (`nw_c03`, `nw_c05`)**: 6 false positives (3 each)
- **Coastal Wind Shadows (`nc_c00`, `nc_c04`)**: 4 false positives (2 each)
- **Atmospheric Fronts / Internal Waves (`nw_c02`, `nw_c07`, `nw_c08`, `nw_c10`, `nc_c01`, `nc_c02`)**: 7 false positives (1 each)

**Physical Boundary Finding**:
These errors demonstrate that single-polarization (VV) radar backscatter texture alone cannot physically separate organic surface slicks from mineral oil spills without external 10m wind speed context ($< 3\text{ m/s}$) or optical confirmation.

---

## 7. Latency Benchmark (Host CPU)

Measured across all 100 test samples:

| Stage | Mean Latency | Median Latency | P95 Latency |
|---|---|---|---|
| **Preprocessing (224×224 grayscale normalization)** | 4.54 ms | 3.33 ms | 9.80 ms |
| **CNN Inference (`SAROilSlickMultiScaleCNN`)** | 17.57 ms | 11.54 ms | 69.24 ms |
| **Total End-to-End Latency** | **22.10 ms** | **15.59 ms** | **73.82 ms** |

---

## 8. Operational Integration & Guardrails

1. **Production Default**: `sar-detector-v1` remains the active production baseline.
2. **Experimental Screener**: `sar-oil-slick-v2.2` can be activated via configuration:
   ```python
   settings.sar_model_version = "v2.2"
   ```
   or via the registry:
   ```python
   from app.vision.registry import get_sar_v2_2_detector
   detector = get_sar_v2_2_detector()
   ```
3. **Mandatory Look-Alike Caveat**: All positive detections from `sar-oil-slick-v2.2` carry explicit caveats indicating that dark formations require multi-source wind speed and optical verification.
