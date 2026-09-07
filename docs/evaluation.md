# Evaluation

## The rule

**A metric is null until it is measured.**

No registry entry, API response, README table or dashboard tile may display a
performance number that no evaluation run produced. The `/models` endpoint
returns `null` for unmeasured metrics, and
`test_unevaluated_metrics_are_null_not_invented` enforces it in CI.

This exists because the predecessor advertised `mAP50: 0.87, Precision: 0.89,
Recall: 0.83` with no evaluation behind them. Those numbers survive exactly
one question: *"show me the run."*

## Detector evaluation

```bash
python -m ml.evaluation.evaluate_detector \
    --model-path /path/to/best.pt \
    --dataset /path/to/data.yaml \
    --dataset-version v1 \
    --register
```

Without `--register` it prints and writes nothing. With it, the metrics land
in `model_versions` alongside `metrics_source`, which records what produced
them and when.

Measured: mAP@50, mAP@50-95, precision, recall, F1, per-class AP@50, and mean
single-image latency timed over real passes.

### Metrics that matter here

| Metric | Why |
|---|---|
| **Recall** | Missing a real spill is the expensive error. Prioritise this. |
| **Precision** | False alarms erode operator trust; a system that cries wolf gets ignored. |
| mAP@50 | Standard comparator, loose localisation criterion. |
| mAP@50-95 | Stricter; matters less here since exact boxes are not the deliverable. |
| Latency | Sets the ceiling on ingestion throughput. |

For an imbalanced monitoring problem, the precision–recall curve is far more
informative than mAP alone, and the operating point should be chosen
deliberately rather than left at the training default.

## The SAR detector cannot currently be evaluated

This is the significant gap, and it is worth stating plainly.

`SARDarkFormationDetector` is rule-based. Its thresholds (−22 dB darkness,
3 dB minimum contrast, 5,000 km² plausibility gate) are derived from published
SAR oil-spill literature and physical reasoning, **not fitted to data**. Its
confidence is an uncalibrated heuristic score, and every response says so.

To evaluate it, the platform needs cells with **known ground truth**:

| Source | Notes |
|---|---|
| EMSA CleanSeaNet | Confirmed detections with verification outcomes; access is restricted |
| NOAA incident archives | Historical US spills with dates and locations |
| Published SAR benchmarks | Several oil-spill segmentation datasets exist; licensing varies |
| Manual annotation | Expert-labelled Sentinel-1 scenes; slow but tractable |

With such a set, the evaluation would be:

1. **Detection quality** — precision/recall/F1 at cell level, and a
   precision–recall curve swept over the darkness threshold.
2. **Look-alike discrimination** — the metric that actually matters. Of cells
   flagged `oil_like_signature`, what fraction were confirmed oil versus low
   wind, biogenic slick, or rain cell? This is where SAR pipelines succeed or
   fail.
3. **Calibration** — reliability diagram of predicted score against observed
   frequency, then Platt scaling or isotonic regression. Only after this may
   `confidence_is_calibrated` become `True`.
4. **Threshold sensitivity** — how the operating point moves with the darkness
   and contrast thresholds, so they are chosen rather than inherited.
5. **Stage-2 lift** — does refinement improve precision over screening alone,
   and by how much per unit of Earth Engine cost?

Until that dataset exists, the honest position is: the detector is a
physically-motivated screening heuristic with unvalidated performance, and the
platform says exactly that everywhere it reports a detection.

## Forecast evaluation

Unlike the detector, forecasting **is** evaluated — automatically, on every
call, because the ground truth is the series itself.

```
backtest_mae  one-step-ahead MAE for the fitted model
naive_mae     the same for last-value-carried-forward
beats_naive   backtest_mae < naive_mae
```

A model that does not beat the naive baseline is reported as such, in the API
response, with a message saying the trend is weakly supported.

Planned additions: rolling-origin cross-validation for multi-step horizons,
MASE for cross-region comparability, and interval coverage (does the nominal
80% interval actually contain 80% of outcomes?).

## Risk-engine evaluation

The risk engine is deterministic, so "accuracy" is not the right frame. What
is testable, and is tested:

| Property | Test |
|---|---|
| Determinism | Identical inputs give identical scores |
| Reconstructibility | Contributions sum to the score exactly |
| Monotonicity | Higher confidence, larger area, worsening trend, closer coast all raise the score |
| Bounds | Score stays in [0, 100] across the input range |
| Safe failure | Missing factors renormalise rather than zero-fill |
| Provenance | Simulated inputs yield simulated assessments |

What is **not** validated: whether the weights reflect real environmental
harm. That would require expert assessments of real incidents to compare
against, and is documented as a limitation. The weights are versioned and
transparent so a domain expert can disagree with a specific number rather than
with a black box.

## Operational metrics

`/metrics` reports measured latency percentiles (p50/p95/max), request volume,
success rate and class mix from `prediction_logs`. With no traffic it returns
`n: 0` and `null` percentiles — not zeros.

`/drift` reports PSI over confidence and class distributions, and
`insufficient_data` below 30 samples per window.

## Test suite

138 tests. The subset that guards the claims above runs as its own CI job:

```
TestHonestyContract      confidence never claims calibration; scores capped
TestSignatureGuardrail   SAR cannot emit optical-only signatures
TestPlausibilityGate     implausible extents downgraded
TestProvenanceContract   simulated data always labelled
TestMissingDataHandling  unknown never reads as safe
TestInsufficientData     thin history refuses rather than extrapolates
TestTwoStagePipeline     screening never claims oil; refinement makes it reachable
```

Coverage is above 90% for the domain, risk, forecasting, schema and service
layers. It is low for `gee/earth_engine.py` (~23%), which requires live
credentials — that path is exercised manually and guarded by the provider
abstraction so its absence cannot break the platform.
