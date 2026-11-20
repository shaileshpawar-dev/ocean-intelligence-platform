# Progress log

Work towards the demo, following `docs/SECTION_AUDIT.md`. Newest entry last.

Database backup taken before any of this work: `backups/oip-20261120-115423.dump`
(113 MB, custom format, 41 tables with data). Restore with:

```bash
docker exec -i ocean-intelligence-platform-db-1 pg_restore -U oip -d oip --clean < backups/oip-20261120-115423.dump
```

---

## Task 1 — Fix the two stale wind-screener tests

**Done.** `tests/test_wind_screener.py::TestMultiSensorIntegrator` — both tests
now call `integrate()` the way `tests/test_multi_sensor_fusion.py` and
`app/services/candidate_service.py:796` call it. No production code changed.

Three things had drifted, not one:

1. `integrate()` takes the candidate's own fields as keywords
   (`sar_confidence`, `screening_status`, `model_version`, `sar_time`,
   `wind_speed_ms`) instead of a packed `sar_result` dict.
2. `optical_evidence` takes real Sentinel-2 band metrics (`mean_ndci`,
   `p90_ndci`, `mean_swir_ratio`, cloud/water fractions) instead of
   pre-interpreted booleans (`ndci_algae_detected`, `sunglint_slick_detected`).
3. Two result fields were renamed: `optical_cross_verification_status` →
   `optical_verification_status`, and `overall_confidence_level` →
   `concordance_level` (now a `ConcordanceLevel` enum, not a string).

The assertions keep their original intent — chlorophyll contradicts the oil
reading, glint supports it — because both status strings
(`biogenic_lookalike_confirmed`, `multi_sensor_slick_concordance`) still exist
in `app/vision/multi_sensor.py`. I also added an evidence-consistency assertion
to the sunglint test so both cases check the same two things.

**Tests:** `645 passed, 21 skipped, 0 failed` (was 643 passed / 2 failed).

**Gotcha:** the NDCI threshold that decides biogenic-vs-oil is
`MultiSensorIntegrator.ALGAL_BLOOM_NDCI_THRESHOLD`. The test uses
`mean_ndci=0.15 / p90_ndci=0.23` to sit clearly above it. If that constant is
ever retuned, these tests are the ones that will tell you.

**Next:** Task 2 — register the three evaluated SAR models in `model_versions`.

---

## Task 2 — Register the three evaluated SAR models

**Done.** New script `scripts/register_sar_models.py` reads the three
`data/models/sar/*/eval_metrics.json` files and upserts them into
`model_versions`. Model Performance now reads **EVALUATED MODELS: 3**
(was 0); five models are registered in total.

| Model | Version | Precision | Recall | F1 | Mean latency |
|---|---|---|---|---|---|
| sar-oil-slick-v2 | 2.0.0-experimental | 0.636 | 0.933 | 0.757 | 5.6 ms |
| sar-oil-slick-v2.1-expanded | 2.1.0-experimental | 0.721 | 0.880 | 0.793 | 38.4 ms |
| sar-oil-slick-v2.2 | 2.2.0-experimental | 0.677 | 0.880 | 0.765 | 22.1 ms |

Every value is read from the JSON files; nothing is derived or invented.
Idempotent — verified by running twice (`3 created, 0 updated`, then
`0 created, 3 updated`). `--dry-run` prints without writing.

**Gotchas, in case you touch this again:**

- **The three files disagree on key spelling.** v2 and v2.1 use
  `precision` / `f1_score` / `avg_cpu_latency_ms`; v2.2 uses `Precision` / `F1`
  and keeps latency in a separate `latency_benchmark_ms.total.mean` block.
  `_first()` normalises this. Add a fourth model and you will probably meet a
  fourth spelling.
- **`map50`, `map50_95` and `iou` are deliberately NULL.** These are binary
  scene classifiers (P(oil) for a 224×224 patch), not object detectors, so
  those metrics do not exist for them. The page shows "Not evaluated" for
  those rows, which is correct — do not be tempted to fill them.
- **FPR, confusion matrix, test-set size and the baseline comparison have no
  columns** in `model_versions`. They go into `notes` verbatim rather than
  adding a migration before the demo. The structured version reaches the UI
  through `/models/detectors` (Task 3).
- `metrics_source` is the field the UI counts as "evaluated"
  (`Models.tsx:41`), not the presence of metrics. If a future row has metrics
  but no `metrics_source`, it will not be counted.
- v2 and v2.1 are registered as `archived` (superseded on the same benchmark
  lineage) and v2.2 as `staging` — `sar-detector-v1` is still the deployed
  baseline, so none of the three is `is_deployed`.

**Tests:** 645 passed, 21 skipped.

**Next:** Task 3 — stop stripping `test_metrics` / `baseline_comparison` in
`GET /api/v1/models/detectors`.

---

## Task 3 — Stop dropping detector metrics in the API

**Done.** `DetectorInfoOut` (`backend/app/schemas/analytics.py`) listed seven
fields while the evaluated SAR screeners' `describe()` returns fifteen, so
Pydantic silently discarded `test_metrics`, `baseline_comparison` and six
other fields. The API therefore said nothing about models that had been
scored on a held-out split.

Added nine optional fields: `architecture`, `modality`, `input_resolution`,
`evaluation_status`, `dataset_provenance`, `is_default`, `role`,
`test_metrics`, `baseline_comparison`. All default to `None`, so the mock and
rule-based detectors still validate and still report null.

Verified live:

```
mock-detector        eval=None                            metrics=none
sar-dark-formation   eval=None                            metrics=none
sar-oil-slick-v2     eval=evaluated_on_labeled_test_data  metrics=yes  baselines=yes
sar-oil-slick-v2.2   eval=evaluated_on_labeled_test_data  metrics=yes  baselines=yes
```

**Tests:** two added in `tests/test_api.py` —
`test_evaluated_detectors_report_their_measured_metrics` (the evaluated ones
carry metrics and a baseline) and `test_unevaluated_detectors_report_null_not_zero`
(the mock one reports null, not zero). 647 passed, 21 skipped.

**Gotchas:**

- **No route change was needed.** `list_detectors()` already did
  `DetectorInfoOut(**d)`; the loss was entirely in the schema. Pydantic drops
  unknown keys without complaining, which is why this was invisible.
- `test_metrics` key spelling differs per checkpoint (`precision` vs
  `Precision`), so the payload is passed through as the detector wrote it
  rather than normalised. The new test accepts either spelling. If you render
  these in the UI, handle both.
- Only v2 and v2.2 are exposed as detectors; v2.1-expanded exists in the
  registry (Task 2) but has no runtime detector, so it does not appear here.

**Next:** Task 4 — give the forecaster real history.
