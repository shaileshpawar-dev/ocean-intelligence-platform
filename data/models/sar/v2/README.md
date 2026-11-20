# Model Card: `sar-oil-slick-v2`

## 1. Model Overview
- **Model Key**: `sar-oil-slick-v2`
- **Model Version**: `2.0.0-experimental`
- **Framework**: PyTorch 2.13.0 (CPU / CUDA compatible)
- **Architecture**: `SAROilSlickCNN` (4-block convolutional network with batch normalization, adaptive pooling, and dropout)
- **Parameters**: 101,826 trainable parameters
- **FLOPs**: ~0.15 GFLOPs
- **Input Resolution**: $224 \times 224$ pixels, 1-channel grayscale (Sentinel-1 C-SAR amplitude, normalized to $[-1, 1]$)
- **Task**: Deep-learning candidate oil-slick screening vs. natural look-alikes on spaceborne Synthetic Aperture Radar (SAR) imagery.
- **Rigor Classification**: `EVALUATED_ON_LABELED_TEST_DATA`

---

## 2. Dataset & Provenance
- **Dataset Source**: PANGAEA Dataset 980773 / DARTIS 2019
  - **DOI**: [10.1594/PANGAEA.980773](https://doi.org/10.1594/PANGAEA.980773)
  - **Publication**: Yang, Y.-J., Singha, S., Goldman, R., & Schütte, F. (2025). *Dataset of oil slicks, look-alikes and remarkable SAR signatures obtained from Sentinel-1 data in the Eastern Mediterranean Sea*. Earth System Science Data (ESSD), 17(12), 6807–6837. DOI: [10.5194/essd-17-6807-2025](https://doi.org/10.5194/essd-17-6807-2025).
- **License**: Creative Commons Attribution 4.0 International (**CC BY 4.0**).
- **Sensor**: Copernicus Sentinel-1 C-band SAR Level-1 Ground Range Detected (GRD) in Interferometric Wide (IW) swath mode, VV polarization.
- **Data Integrity & Leakage Prevention**:
  - Samples are strictly partitioned by `Sentinel_ID` (distinct satellite acquisition events). No overlapping tiles or temporal re-visits are shared across train, validation, and test splits.
  - Manifest file: [`data/training/sar_oil_v2/sar_splits_manifest.json`](file:///c:/Users/Shailesh/New%20folder%20%282%29/ocean-intelligence-platform/data/training/sar_oil_v2/sar_splits_manifest.json).

---

## 3. Training Protocol
- **Device**: Local Host CPU (Intel/AMD x86_64, Windows)
- **Random Seed**: `42` (fixed across Python, NumPy, and PyTorch)
- **Optimizer**: AdamW ($\text{lr} = 10^{-3}$, weight decay $= 10^{-4}$)
- **Learning Rate Schedule**: Cosine Annealing over 25 epochs
- **Batch Size**: 8
- **Training Epochs**: 25 epochs (completed in 79.9 seconds on local CPU)
- **Validation Criteria**: Model selection was governed strictly by validation F1 score; the independent test set was never accessed during hyperparameter tuning or checkpoint selection.

---

## 4. Evaluation Results on Independent Held-Out Test Split

Evaluated on 30 independent test patches (15 positive oil slick candidates, 15 look-alike dark formations from completely held-out Sentinel-1 SAFE scenes):

| Metric | Baseline Heuristic (Contrast Thresholding) | `sar-oil-slick-v2` (CNN Texture Screener) | Delta / Improvement |
|:---|:---:|:---:|:---:|
| **Test Accuracy** | $60.00\%$ ($18/30$) | $\mathbf{70.00\%}$ ($21/30$) | $+10.00\%$ |
| **Test Precision** | $\mathbf{80.00\%}$ | $63.64\%$ | $-16.36\%$ (tradeoff for sensitivity) |
| **Test Recall** | $26.67\%$ ($4/15$) | $\mathbf{93.33\%}$ ($14/15$) | $\mathbf{+66.66\%}$ (missed spills dropped from 11 to 1) |
| **Test F1 / Dice** | $0.4000$ | $\mathbf{0.7568}$ | $\mathbf{+0.3568}$ |
| **True Positives (TP)** | 4 | **14** | $+10$ detected slicks |
| **False Negatives (FN)** | 11 | **1** | **-10 missed spills** |
| **False Positives (FP)** | **1** | 8 | $+7$ candidate false alarms |
| **True Negatives (TN)** | **14** | 7 | $-7$ |
| **Average CPU Latency** | $0.8\text{ ms}$ | $\mathbf{5.55\text{ ms}}$ | $+4.75\text{ ms}$ (p95: $6.66\text{ ms}$) |

---

## 5. Scientific Limitations & Operational Guidance
1. **Candidate Screener, Not Confirmed Oil Identifier**:
   - In accordance with physical principles, surface tension damping in C-band SAR is caused by mineral oil, biogenic surfactants, and low-wind areas.
   - The model achieves very high sensitivity ($93.3\%$ recall) but exhibits false alarms on look-alikes ($8$ false positives out of $15$ look-alike scenes). It must be operated as an **early-warning candidate screener**.
2. **Mandatory Look-alike Caveats**:
   - All detections carry explicit `LOOKALIKE_CAVEAT` and uncalibrated confidence notifications.
   - Detections should be correlated with in-situ wind speed ($3\text{--}12\text{ m/s}$) and optical satellite evidence.
3. **Operational Default Stance**:
   - `sar-detector-v1` (deterministic rule-based regional screener) remains the default operational baseline.
   - `sar-oil-slick-v2` is registered as an experimental option toggled via `settings.sar_model_version = "v2"` or `get_sar_detector(force="sar-v2")`.
