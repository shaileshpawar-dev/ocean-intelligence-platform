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

---

## Task 4 — Give the forecaster real history

**Done.** The Forecasts page works for every region it offers: **38 of 38
forecastable**, zero failures. The forecaster itself was not touched — it was
correct all along, and was refusing to invent a curve it could not fit.

### What was actually wrong

Not "all events fall in 3 days" alone. The 49 events were spread across **49
distinct regions, one event each**, so no region had more than a single daily
bucket and none could ever reach the 7 that Holt needs. `zone_history` is built
from `PollutionEvent` grouped by region-day, so one event per region means one
bucket per region, whatever the date range.

### What changed

- **`app/demo/seed.py`** — default span `45 → 60` days (`DEFAULT_DEMO_DAYS`).
  Measured, not guessed: each of the 38 monitored cells is observed once per
  simulated day and only some observations yield a detection, so *distinct
  event days* grows more slowly than the day count. At 45 days one cell
  (`gulf_of_mexico_nw`) lands on 6 buckets, one short; at 60 every cell is on
  at least 9.
- **`app/demo/seed.py`** — the seeder now writes a `RiskAssessment` row per
  event. It had always computed risk and stored the score on the event, but
  never persisted the assessment, so a reseeded database showed an empty Risk
  Analysis page and `/risk/{id}` returned 404 for every event it had just
  created. 663 events, 663 assessments.
- **`app/demo/seed.py`** — the returned summary now reports `forecastable`
  and `regions_below_forecast_minimum`, so a short seed says so instead of
  being discovered as "insufficient history" on the page.
- **`app/api/routes/analytics.py`** — `/forecast/{code}` returns **400** with
  the parent code for a stage-2 refined sub-cell.
- **`app/services/analytics_service.py`** — `get_trends()` excludes refined
  sub-cells. See the gotcha below; this one matters for the demo.

### Reseed result

```
days=60  observations=2280  events=663  history_buckets=663
regions_with_history=38  regions_below_forecast_minimum=[]  forecastable=true
events span 2026-09-21 .. 2026-11-19 (60 distinct days)
buckets per region: min=9 median=17 max=29
```

Forecast now returns real verdicts, including honest negative ones —
`java_sea_se` beats the naive baseline, `gulf_of_mexico_ne` and `north_sea_se`
do not, and the page says so.

### Dependents, as warned

- **Risk assessments:** the old 49 were deleted with their events and 663 new
  ones were written by the seeder (see above).
- **Agent runs and reports:** the FK is `ondelete="SET NULL"`, so all 6 of each
  survived the reseed with `event_id = NULL`, pointing at nothing. Their
  narrative describes the deleted event's region and signature, so re-pointing
  them would have attached the wrong text to the wrong detection. They were
  deleted and **5 fresh runs and reports generated across 5 distinct regions**
  (Persian Gulf SE/SW, Yellow Sea NW, North Sea SE, Gulf of Mexico SE) — which
  also fixes the audit finding that every report targeted one event.

### Gotchas

- **Do not click "Stage-2 refine" on Live Monitoring before the demo without
  reading this.** Refining mints sub-cell regions, each of which gets a
  `zone_history` row immediately and therefore appeared in `/trends` — which is
  what builds the Forecasts dropdown. That would have put regions with one or
  two buckets into the dropdown and brought "insufficient history" straight
  back on a page that now works. `get_trends()` now filters them out, and
  `test_every_region_offered_by_trends_can_be_forecast` guards it.
- **`Region.parent_code` is not a region code.** It holds a display name
  ("Gulf of Mexico"), and *every* region has one including the top-level
  monitored cells. The structural marker for a sub-cell is the code suffix
  `__r{row}c{col}` that `refinement_service.py:112` writes. A first attempt at
  the 400 used `parent_code` and would have rejected every forecast.
- **The sub-cell 400 is checked before the region is looked up**, because it
  is a statement about the shape of the code, not about one row. A sub-cell
  code that has not been refined yet still gets the helpful 400 rather than a
  bare 404.
- **Event count went 49 → 663**, which is well beyond "roughly the same".
  It is unavoidable: 49 events in 49 distinct regions cannot produce 7 buckets
  anywhere. 60 days × 38 cells at the demo provider's hit rate is 663. Dial it
  with `seed_demo_data(days=N)`, but below 60 some region stops being
  forecastable and the summary will name it.
- **"Slick-scale extent" now reads 0 km² and there are 0 CRITICAL events.**
  Not a regression in the metric — that card deliberately sums only
  `oil_like_signature`, and all 663 seeded events are `dark_formation` from the
  rule-based SAR baseline, which is the honest label for what it detects. The
  previous oil-like events came from the refine step. If you want them back for
  the demo, run refine *after* reading the first gotcha.

**Tests:** 649 passed, 21 skipped. Three added:
`test_forecast_of_a_refined_subcell_explains_itself`,
`test_every_region_offered_by_trends_can_be_forecast`, plus the two from Task 3.

**Next:** nothing outstanding from the four tasks. Remaining audit items are in
`docs/SECTION_AUDIT.md` under P1–P2 (real prediction logs to revive drift, the
knowledge graph, marine geographic coherence).

---

## Final state

All four tasks done. Verified on the final code, not on an intermediate state.

**Tests:** `649 passed, 21 skipped, 0 failed` (started at 643 passed / 2 failed).

**Pages:** all 15 across Marine Monitoring, Intelligence, AI Research, Machine
Learning and System loaded with **zero console errors**.

**What a demo viewer will now see that they could not before:**

| Page | Before | After |
|---|---|---|
| Forecasts | "Insufficient history" for every region | 38 of 38 regions forecast, with honest beats-naive verdicts |
| Model Performance | EVALUATED MODELS: 0 | EVALUATED MODELS: 3, with measured P/R/F1, latency, confusion matrices and baselines |
| `/models/detectors` | 7 fields, metrics silently dropped | full `test_metrics` and `baseline_comparison` |
| Risk Analysis | 49 assessments | 663, one per event, regenerated by the real engine |
| Reports / Agents | 4 runs + 4 reports, all one event | 5 runs + 5 reports across 5 distinct regions |
| Ocean Overview chart | 3 days | 60 days |
| Test suite | 2 failures | green |

**Still open, from `docs/SECTION_AUDIT.md` — not attempted, by design:**

- Inference latency is still "Unavailable" and drift still "Insufficient data":
  both need real `prediction_logs`, which means running the detector over the
  306 stored SAR patches (audit P1, item 5).
- Knowledge Graph still has no backend (audit P2, item 8).
- Marine regions are still global (Gulf of Mexico, North Sea, Malacca) while
  the rest of the platform is India (audit P2, item 7). Worth a sentence in
  the demo script if nothing else.

**Before the demo, read the Task 4 gotchas above** — particularly the one about
the "Stage-2 refine" button, and the one explaining why "Slick-scale extent"
now reads 0 km².

**Restore point:** `backups/oip-20261120-115423.dump` (taken before any of this
work; `backups/` is gitignored).

---

## Task 5 — Real prediction logs

**Done.** Inference latency and drift both show real numbers.

- **Inference P95: 9.63 ms** over 105 requests (was "Unavailable", 0 logged)
- **Drift: WARNING** (was "Insufficient data")

### Where the patches were

`data/training/sar_oil_v2/images`, resolved by
`candidate_service.IMAGES_DIR / cand.image_name`. **305 of 306 load.** The
missing one is `cand_test_missing_image_006`, an acceptance fixture that points
at `missing_nonexistent_patch_9999.jpg` on purpose to exercise the 404 path —
so 305 is the correct number, not a failure. The script reports it by name
rather than skipping silently.

### What changed

- **`backend/app/monitoring/prediction_log.py`** (new) — `log_prediction()`,
  now the single writer of `prediction_logs`. It was a private helper inside
  `satellite.py` that hardcoded `created_at` and the endpoint label, so it was
  only reachable from one route. `endpoint`, `created_at`, `input_stats` and
  `commit` are now parameters; the defaults reproduce the live endpoint's
  behaviour exactly.
- **`backend/app/api/routes/satellite.py`** — `_log_prediction` is now a thin
  wrapper over it, so the live path and the batch replay write identically.
- **`scripts/log_sar_inferences.py`** (new) — idempotent, `--dry-run`,
  `--replace`.

### The drift verdict, reported as found

```
OVERALL: warning
  mean_confidence              warning   PSI 0.1100   baseline_n=100  current_n=105
  predicted_class_distribution ok        PSI 0.0322   baseline_n=100  current_n=105
    baseline: oil_like_signature=65, no_anomaly=19, dark_formation=16
    current:  oil_like_signature=67, dark_formation=23, no_anomaly=15
```

The screener's **confidence distribution shifts modestly between the two
independent held-out benchmarks** (PSI 0.11, just over the 0.10 warning line)
while the **predicted class mix stays stable** (PSI 0.032). This was not tuned
for and has not been adjusted. It is a plausible and useful finding: the model
is about equally decisive overall but distributes its confidence differently on
the Phase 13 set, which is exactly the kind of signal drift monitoring exists
to raise for a human.

### Timestamps — read this before defending the panel

All 305 inferences physically run within about three seconds of each other, but
drift compares two *time* windows, so each row's `created_at` is **assigned**.
The measurements are real (latency and confidence are what the detector
produced); the placement in a window is not.

The assignment is deliberately meaningful rather than convenient:

| Window | Days back | Contents | n |
|---|---|---|---|
| baseline | 8–36 | Benchmark 1 (Phase 12 held-out) | 100 |
| current | 0–6 | Benchmark 2 (Phase 13 locked final) + acceptance fixtures | 105 |
| outside both | 40–55 | Phase 13 dev + validation sets | 100 |

Dev and validation sit **outside** both windows on purpose: they are
training-adjacent, and drift-comparing against data the model was tuned on
would measure nothing. So the comparison is Benchmark 1 vs Benchmark 2 — two
genuinely independent held-out sets.

Every row carries `timestamp_is_synthetic: true` plus its true wall-clock
`executed_at` in `input_stats`, and the endpoint label is
`BATCH /sar-candidates/replay`, so these cannot be mistaken for live traffic.

### Gotchas

- **The detector silently rejects raw bytes.** `SAROilSlickDetectorV2.predict`
  takes a path, a PIL image, a numpy array or a dict — passing
  `path.read_bytes()` logs `sar_v2_invalid_payload_format` and returns **zero
  detections in under 0.1 ms** without raising. The first dry run looked like a
  clean success (`failures: 0`) and was entirely empty. If latency ever reads
  ~0.0 ms with no predicted classes, this is why.
- **The 2 mock-detector rows were left in place and do not contaminate
  anything.** They are 34 days old, so they fall outside the 7-day latency
  window (verified: every row inside it is `sar-oil-slick-v2.2`). They *are*
  inside the drift baseline window, but their `mean_confidence` is NULL and
  their `predicted_classes` is `[]`, so they contribute nothing to either PSI —
  which is why `baseline_n` is exactly 100 and not 102.
- **`latency_summary()` has no model filter**; it aggregates whatever is in the
  window. Today that is only the SAR model. If something logs a second model
  within 7 days, the P95 becomes a mixture and the card will not say so.
- Re-running without `--replace` is a no-op by design.

**Tests:** 651 passed, 21 skipped. Two added for the extracted writer
(`TestPredictionLogWriter`), covering the detection summary and the
batch-caller parameters a replay depends on.

**Next:** Task 6 — confusion matrix and ROC from `sar_candidates` ground truth.

---

## Task 6 — Confusion matrix and ROC from stored ground truth

**Done.** Model Performance now carries a panel computed live from the database
rather than read back from a metrics file.

**Headline: AUC 0.771** over all 306 candidates, at threshold 0.50
precision 65.7%, recall 88.3%, F1 0.753, FPR 46.7%.

```
                 Predicted oil   Predicted clean
Actually oil         136              18
Actually clean        71              81
```

### Score provenance — checked, as asked

All 306 rows carry `detector_name = sar-oil-slick-v2.2`,
`model_version = 2.2.0-experimental`, and `confidence_is_calibrated = false`
for every one. So the panel is labelled with v2.2 and states on every response
that the scores are uncalibrated. 154 positives (`ow` 104 + `oc` 50), 152
negatives (`nw` 122 + `nc` 30).

**Independent check that the labelling is right:** these live figures
(P 0.657 / R 0.883 / F1 0.754 / FPR 0.467 over 306) land within a couple of
points of the registered v2.2 metrics (P 0.677 / R 0.880 / F1 0.765 / FPR 0.42
over the locked 100-sample split). Two separately-derived computations over
overlapping data agreeing this closely is good evidence neither is inverted.
The panel says in plain text that the two differ because they are different
sample sets, so a viewer does not read it as a contradiction.

### What changed

- **`backend/app/monitoring/candidate_evaluation.py`** (new) — labels, matrix,
  ROC and AUC. **sklearn is not installed** and was not added for two textbook
  formulas two days before a demo; numpy is present but the computation is
  plain Python and clearer for it.
- **`backend/app/api/routes/ml.py`** —
  `GET /api/v1/models/sar-candidates/evaluation?threshold=`.
- **`frontend/src/components/CandidateEvaluationPanel.tsx`** (new) — 2×2
  matrix, ROC with the chance diagonal and a threshold marker, live slider.
- **`frontend/src/styles/app.css`**, `api.ts`, `types.ts`, `Models.tsx`.

### Gotchas

- **Route order matters.** `/models/sar-candidates/evaluation` must be declared
  **before** `/models/{name}/{version}`, which would otherwise swallow it as
  `name="sar-candidates", version="evaluation"` and return 404. There is a test
  for exactly this (`test_it_is_not_swallowed_by_the_model_detail_route`).
- **The dual `test_metrics` spelling from Task 3 does not arise here.** Nothing
  in the frontend renders `test_metrics` — I grepped. This panel computes
  everything itself from the evaluation endpoint, so there was no spelling to
  handle; I did not invent a use for it. If you later surface detector
  `test_metrics` in the UI, that is when you need `precision` **and**
  `Precision`.
- **The 4 real-database tests skip during a normal run.** `conftest.py` forces
  `DATABASE_URL` at its own temp SQLite file — that is the isolation guard that
  exists because the suite once destroyed the live database. So those cases
  skip by design; I verified their assertions against Postgres directly
  (n=306, skipped=0, model named correctly, AUC invariant to threshold).
- **AUC is threshold-independent and the panel says so.** If you move the
  slider in the demo and the AUC changes, something is wrong.
- Thresholds outside [0, 1] are rejected with 422 by FastAPI's validation.

**Tests:** 663 passed, 25 skipped. 16 added in
`tests/test_candidate_evaluation.py` — hand-worked confusion matrices,
perfect / inverted / tied-score AUC cases (1.0, 0.0, 0.5), a hand-checked
intermediate AUC of 0.75, curve endpoints, the one-class case returning no
curve rather than a fabricated diagonal, plus the endpoint and route-order
cases.

**Next:** Task 6b — stage-2 refine on a few regions.
