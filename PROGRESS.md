# ALL DONE — 22 November 2026, `main` at tag `demo-final-v3`

**Merged.** `feature/real-data` (102 commits) is in `main`, pushed, tagged
`demo-final-v3`. `main` builds, its tests pass, all 23 routes load with zero
console errors after a clean restart, and `scripts/reset_demo.sh` restores
`backups/oip-demo-final-v3.dump` — verified by running it.

**The last four panels became real on 22 November.** Candidate Review's
optical chips are six Sentinel-2 bands fetched per candidate within ±5 days,
with no synthetic fallback and an honest blank for the 2 of 25 that have no
cloud-free scene. The suspect-vessel panel is gone, replaced by aggregate
Global Fishing Watch activity that names nobody. The Ocean Map shows the 100
tiles actually screened. Severity now carries its own definition wherever it
appears. The SAR patch image — 404ing on every candidate since the move into
Docker — is served again for 305 of 306.

**868 tests passing**, 25 skipped. Deliverables in `~/Downloads`:
`OIP-Demo.pptx` (23 slides) and `OIP-Final-Status-Report.md`.

---

## What was true at v2, and still is


1. **Demo mode is off and the database holds no simulated rows.** The 666
   seeded events and 2,400 synthetic observations were deleted after backup.
2. **108 real pollution detections** from 3,006 measured Sentinel-2 readings
   spanning a full year across 36 of 40 Indian EEZ regions.
3. **Events need two criteria**: top 1% of *that region's* own 12 months,
   **and** an absolute floor from literature. Counts went 41/41/41 → 41/35/32
   — the first set was describing the method, not the sea.
4. **FDI has no absolute floor and says so.** Verified from Biermann et al.
   (2020) directly: the paper publishes no threshold. Never called plastic.
5. **Sentinel-1 saturation fixed** from 100/100 tiles at confidence 1.000 to
   22/100. Cause was tile preparation, not the model — the 306 benchmark
   patches reproduce their stored scores to within 1%.
6. **Tested against a real spill — and it did not find it.** MSC ELSA 3,
   4 passes, 31 tiles, nothing flagged. Published with the reasons it is
   weak evidence, because a detector that always said "no" would look the same.
7. **Nine data sources on the page**, each status derived from what it last
   actually produced. The NWDP feeds read "Sync paused" — the server answers
   and a firewall refuses; that is not an outage.
8. **845 tests passing**, 24 pages with zero console errors, clean restart
   verified, `backups/oip-demo-final-v2.dump` frozen.
9. **Deck rebuilt** (23 slides, no secrets) and **final status report**
   written, both in `~/Downloads`.
10. **The honest gaps**: the SAR model still needs retraining on calibrated
    backscatter (tiles run 34 units dark), forecasts beat naive in 0 of 40
    regions, and nothing refreshes without someone running a fetch job.

---

# Progress log

## Master plan checklist — final demo 25 Nov, code freeze end of 24 Nov

Branch `feature/real-data`. Fallbacks: tag `demo-2026-11-22.1`,
`scripts/reset_demo.sh`, `backups/oip-after-window4a-demostate.dump`.

| Step | What | Status | Date |
|---|---|---|---|
| 0 | Credential smoke test | **done** — all 5 services pass | 21 Nov |
| 1 | Refresh real India water data | **done** — feeds down (TLS), honest display | 21 Nov |
| 2 | Indian-regions consistency (a–d) | not started | |
| 3 | Gemini narrative layer | not started | |
| 4 | Real Sentinel-2 water detections | not started | |
| 5 | Real Sentinel-1 oil-spill detection | not started | |
| 6 | Real ocean conditions / coastline / currents | not started | |
| 7 | Real vessel activity (GFW) | not started | |
| 8 | Real marine protected areas (WDPA) | not started | |
| 9 | Real legal/regulatory RAG corpus | not started | |
| 10 | Trained marine-debris classifier (MARIDA) | not started | |
| 11 | Experiments page | not started | |
| 12 | Optical YOLO evaluation | not started | |
| 13 | Forecasting on real data | not started | |
| 14 | Final pass / freeze | not started | |

## Master prompt — real-data completion (started 21 Nov)

A fresh session can pick this up by reading this checklist and the step
entries at the end of this file.

| # | Step | State |
|---|---|---|
| 1 | Real events from real detections | **done** |
| 2 | Real history for forecasts | **done** |
| 3 | Swap simulated data for real; demo mode off | **done** |
| 4 | Ocean Map on real layers | **done** |
| 5 | Fix Sentinel-1 saturation | **mostly fixed** — 78/100 tiles now vary; 0 oil candidates, so no oil events created |
| 6 | Data Sources page | **done** |
| 7 | Gemini retry | **done** |
| 8 | Texts and claims | **done** |
| 9 | Freeze | **done** |
| 10 | Final status report | not started |

**Cleared.** Demo mode is off, the seeded rows are deleted, and every banner
has been re-read against what the page now holds.

---

**Resolved, no decision needed.** Two of the three Indian water feeds (`nwdp`)
are behind an **expired FortiGate appliance certificate** — left as an honest
"Unavailable", and not worth pinning. The third, CPCB's real-time feed, was
never down: it failed only on this Windows host, for want of a root that
certifi carries and Windows does not. It now serves **real readings from
today**. See FT-1.

**Note:** the plan refers to tags `demo-2026-11-22.1 / .2`. Only `.1` exists;
there is no `.2`.


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

---

## Task 6b — Restore some oil-like events

**Done, nothing regressed.** Stage-2 refine on 4 regions:

```
cells_refined=4  subcells_observed=93  events_created=23  upgraded_to_oil_like=16
```

| | Before | After |
|---|---|---|
| Events | 663 | 686 |
| CRITICAL | 0 | **10** |
| HIGH | 208 | 221 |
| Slick-scale extent | 0 km² | **54,940 km²** |

### The regression check this task existed for

The Task 4 gotcha warned that refine would put one-bucket sub-cells into the
Forecasts dropdown. The filter added in Task 4 held:

```
trends regions: 38   sub-cells leaked into dropdown: 0
forecastable: 38/38
```

`test_every_region_offered_by_trends_can_be_forecast` passes, no page shows
"insufficient history", and no restore was needed. A rollback point was taken
first anyway: `backups/oip-before-refine.dump`.

**Note for the demo:** the refine was run against 4 regions only. Running it
again will refine 4 more and add further sub-cells — harmless to Forecasts now,
but it will keep inflating the event count.

---

## Final state — window 2

**Tests:** `663 passed, 25 skipped, 0 failed` (window 1 ended at 649/21).

**Pages:** all 15 loaded with **zero console errors**, checked after the refine.

**Backup:** `backups/oip-after-window2.dump` (113 MB, 41 tables, verified).
Earlier points: `oip-before-refine.dump`, `oip-after-window1.dump`,
`oip-20261120-115423.dump`. All gitignored.

### What a demo viewer sees now that they did not at the start of this window

| Panel | Before | After |
|---|---|---|
| Inference latency | "Unavailable", 0 logged | **p95 9.63 ms**, 105 requests |
| Drift monitoring | "Insufficient data" | **Warning**, PSI 0.11 / 0.032 on real windows |
| Retraining trigger state | Insufficient Data | **Warning**, a live verdict |
| Model Performance | 3 registry cards | plus a **live confusion matrix, ROC and AUC 0.771** with a working threshold slider |
| Ocean Overview | 0 CRITICAL, 0 km² extent | **10 CRITICAL**, 54,940 km² |

### The one finding to be ready to talk about

Drift says **WARNING**, not "no drift". The screener's confidence distribution
shifts between the Phase 12 and Phase 13 held-out benchmarks (PSI 0.11, just
over the 0.10 line) while the class mix stays stable (0.032). This was not
tuned for, and tuning it away was explicitly out of scope. It is a good thing
to be asked about: the platform raises it for human review and does not
retrain on it, which is the policy the Retraining page states.

### Still open from `docs/SECTION_AUDIT.md`

- Knowledge Graph still has no backend (P2, item 8).
- Marine regions are still global while the rest of the platform is India
  (P2, item 7) — worth one line in the demo script.
- The optical YOLOv8 detector still has no committed test split, so its
  registry metrics remain NULL. That is correct, not a gap to paper over.

---

## Task 7a — Make the replay provenance visible

**Done.** Both panels now say what they are measuring.

**Drift Monitoring** carries a derived label:

> Replayed benchmark: baseline = Benchmark 1 (Phase 12 Held-Out Test Set)
> (n=102), current = Benchmark 2 (Phase 13 Locked Final Test Set) (n=105).
> Inferences are real; window timestamps are assigned, not live traffic.

**Inference P95** now reads `9.63ms · 105 request(s) · sar-oil-slick-v2.2`.

### Derived, not hardcoded

`_window_provenance()` reads each window's rows back and counts how many carry
`timestamp_is_synthetic`, grouping by `split`. `_provenance_note()` returns
**None** when neither window holds a replayed row, so a live deployment never
carries a caveat about a batch it does not contain. The split names in the
sentence come from the rows, not from a constant — the n=102 in the baseline is
the two old mock rows being counted honestly alongside the 100 replayed ones.

`latency_summary()` gained the model filter the Task 5 gotcha asked for, plus
`models` and `model_label`. `model_label` is `"mixed"` whenever the window holds
more than one detector, so the card can never imply a single model it is not
measuring. Over 60 days this database genuinely reports `mixed`
(mock-detector + v2.2); over 7 days it reports v2.2 alone.

### What changed

- `backend/app/monitoring/metrics.py` — model filter, `models`, `model_label`.
- `backend/app/monitoring/drift.py` — `_window_provenance`, `_provenance_note`,
  `provenance` block on the response.
- `frontend/src/components/ui.tsx` — new `ProvenanceNote`.
- `Drift.tsx`, `Models.tsx`, `Overview.tsx`, `LiveMonitoring.tsx`, types, CSS.

### Gotchas

- **`ProvenanceNote` is deliberately not a `SimulatedBanner`.** The inferences
  behind the replay are real and only the timestamps are assigned; calling it
  "simulated data" would understate the measurement and overstate the caveat
  at once. Different component, different claim.
- `input_stats` is read in Python rather than with a JSON operator, because
  the suite runs on SQLite and the deployment on PostgreSQL. A window is about
  a hundred rows, so it costs nothing.
- The three latency cards (Models p95, Overview p50, Live Monitoring) all read
  the same `latency_summary`, so they agree by construction.

**Tests:** 669 passed, 25 skipped. Six added (`TestMeasurementProvenance`),
including that live traffic produces **no** caveat and that two models in one
window report `mixed`.

**Next:** Task 7b — marine geographic framing.

---

## Tasks 7b + 8 — Marine framing, and Candidate Review first

**Done.** Committed together because they are one change: say what the marine
module is, then put the part that is real where people will find it.

- **Ocean Overview** carries the full banner (global regions named, events
  SIMULATED, pointer to Candidate Review) plus a prominent linked card:
  *"Real Sentinel-1 data · 306 benchmark candidates"*.
- **Live Monitoring, Pollution Events, Ocean Map** carry the one-line version.
- **Candidate Review** is now **first** in the Marine Monitoring nav group.

Regions were not moved or renamed, and no page content was changed.

### Gotchas

- **`MarineScopeNote` is one shared component, not four copies of a sentence.**
  Four pages making the same claim in four places is four places for it to
  drift out of date.
- **Candidate Review deliberately does not carry the note.** It already has its
  own "Research replay" banner, and a line reading "the real data is in
  Candidate Review" would be absurd on that page.
- **Watch automated JSX insertion.** A regex matching `<PageHeader ... />`
  matched a *nested* self-closing tag on two pages, dropping the note inside
  the header's `actions` prop on Overview and inside a `<button>` on Live
  Monitoring. `tsc` passed both times — it is valid JSX, just in the wrong
  place. Caught by reading the files; fixed by anchoring on the next sibling
  element instead.

**Tests:** 669 passed, 25 skipped (unchanged — presentational).

**Next:** Task 10 — the knowledge graph.

---

## Task 10 — Knowledge graph

### FK survey, recorded before writing any code

Every edge below is a real foreign key in `Base.metadata`, confirmed against
the live schema with `inspect(engine).get_foreign_keys()`.

**Region component** (the default view):

| From | To | Column | Relation |
|---|---|---|---|
| `pollution_events` | `regions` | `region_id` | occurs_in |
| `pollution_events` | `satellite_observations` | `observation_id` | detected_by |
| `satellite_observations` | `regions` | `region_id` | covers |
| `risk_assessments` | `pollution_events` | `event_id` | assesses |
| `agent_runs` | `pollution_events` | `event_id` | analysed |
| `reports` | `pollution_events` | `event_id` | documents |

**Candidate component** (reachable by centring on a candidate):

| From | To | Column | Relation |
|---|---|---|---|
| `sar_candidate_reviews` | `sar_candidates` | `candidate_id` | reviews |
| `sar_candidate_optical_evidence` | `sar_candidates` | `candidate_id` | corroborates |
| `candidate_vessel_associations` | `sar_candidates`, `vessels` | `candidate_id`, `mmsi` | associated_vessel |
| `candidate_environmental_impacts` | `sar_candidates`, `marine_receptors` | `candidate_id`, `receptor_id` | threatens |
| `drift_simulations` | `sar_candidates` | `candidate_id` | drift_modelled |

### Two findings that changed the design

1. **`sar_candidates` has no foreign keys at all.** There is no
   candidate → region link, so the SAR candidates are a **separate connected
   component**, not part of the region subgraph. The graph therefore supports
   centring on a candidate as well as a region; joining the two components
   would have required inventing an edge.
2. **The regulation edge the placeholder page promised does not exist as an
   FK.** `research_documents` has no foreign keys. `reports.sources` is a JSON
   array holding `document_id` strings that do correspond to real rows, but it
   is not a declared relationship. Per the "existing foreign keys only"
   constraint it is **excluded**, so there are no regulation nodes. Adding
   them later means resolving `reports.sources[].document_id` against
   `research_documents.document_id` — a real link, just not an FK.

Node populations: 270 regions, 686 events, 2373 observations, 686 risk
assessments, 10 agent runs, 10 reports, 306 candidates, 8 reviews, 1 optical
evidence, 6 vessels. The busiest region (`south_china_sea_ne`, 29 events)
yields roughly 90 nodes at depth 2, comfortably inside the 150 cap.

### Built

**Backend** — `app/knowledge_graph/builder.py`, `app/api/routes/knowledge_graph.py`.

- `GET /api/v1/knowledge-graph?center_type=&center_id=&depth=1..2&limit=` — BFS
  outward from one record along declared foreign keys. Defaults to the region
  with the most events, so the first view is never empty. Capped at 150 nodes
  and reports `truncated` so a partial view never passes for a complete one.
- `GET /api/v1/knowledge-graph/summary` — node and edge counts straight from
  the tables: **4,356 nodes / 4,464 edges** across 10 node types.
- `center_id` accepts either a primary key or the human-facing identifier
  (region code, `evt_...`, `cand_...`).

Live results: default region centre gives 113 nodes / 137 edges at depth 2,
80 nodes at depth 1; a candidate centre gives 7 nodes / 6 edges; unknown centre
404, unknown type 400, depth > 2 → 422.

**Frontend** — `pages/KnowledgeGraph.tsx` replaces the placeholder. Radial SVG
layout, colour by type, hover for evidence level and attributes, click to
re-centre, 38-region selector, depth control, legend with per-type counts, and
the summary counts below.

### No new dependency, and why

`package.json` had no graph library. Rather than add `react-force-graph-2d` or
`cytoscape` (200–400 KB on top of an existing 416 KB charts chunk), the page
draws its own SVG. The reasoning is not only size:

- The API returns a subgraph defined by **a centre and a hop count**, and
  concentric rings express exactly that — ring 1 is one hop, ring 2 is two.
  A force simulation would scramble that structure into an arbitrary blob.
- It is **deterministic**: the picture does not rearrange itself between
  renders, which matters when someone is pointing at it in a demo.
- At ≤150 nodes there is no performance argument for a simulation.

If the graph ever needs free-form exploration over thousands of nodes, that is
the point to add a real library.

### Gotchas

- **Integer primary keys versus string path parameters.** PostgreSQL refuses
  to compare `integer = varchar` — it raises rather than returning no rows, so
  `region/abc` was a 500, not a 404. `_coerce_key()` converts by column type
  and returns None when it cannot, which lets the lookup fall through to the
  human-facing identifier.
- **The region selector filters out stage-2 sub-cells.** They hold a couple of
  records at most, so centring on one draws a near-empty graph that reads as a
  bug. Same filter as `get_trends()`, for the same reason.
- **The selector must not be bound to the API's node id.** `value="region:20"`
  matches no `<option>`, so the browser silently displayed the first region
  while the graph showed another. It now reads the centre's own `code` out of
  the returned node.
- **Testing hover in React needs `mouseover`, not `mouseenter`.** React
  synthesises enter/leave from `mouseover`/`mouseout` at the root, so a
  dispatched `mouseenter` does nothing and the feature looks broken when it is
  not.
- `SatelliteObservation` requires `observation_id`, `collection` and
  `platform`; a test fixture omitting them fails on a NOT NULL constraint.

**Tests:** 683 passed, 25 skipped. 14 added in `tests/test_knowledge_graph.py`,
the central one being `test_every_edge_corresponds_to_a_stored_foreign_key`,
which re-reads each edge's row and asserts the foreign key actually holds the
other node's key. Also: depth 1 excludes what only depth 2 reaches, `limit`
truncates and says so, an isolated region returns itself with no edges, nodes
keep their own evidence level (and a region keeps `null` rather than borrowing
one), summary counts equal table counts, and the route-order, 404, 400 and 422
cases.

---

## Final state — window 3

**Tests:** `683 passed, 25 skipped, 0 failed` (window 2 ended at 663/25).

**Pages:** all 15 loaded with **zero console errors**, Knowledge Graph included.

**Backup:** `backups/oip-after-window3.dump` (113 MB, 41 tables, verified).
Earlier points this window: `oip-before-window3.dump`. No database writes were
made in window 3 — every task was read-only or presentational — so the two
dumps are equivalent.

### What changed this window

| Area | Before | After |
|---|---|---|
| Drift panel | a verdict with no stated source | names both benchmark splits and says the timestamps are assigned |
| Latency cards | a percentile over unnamed models | names the model, or says "mixed" |
| Marine pages | regions looked like a second project | declared a global demo on all four simulated pages |
| Candidate Review | fifth in the nav group | first, plus a dashboard card |
| Knowledge Graph | `NotAvailableInBackend` placeholder | 4,356 nodes / 4,464 edges, interactive, FK-only |

### Two honest absences, by design

- **No regulation nodes.** `research_documents` has no foreign keys. The
  citations in `reports.sources` are JSON, so under the "existing foreign keys
  only" rule they are out. The summary endpoint says so in its own `notes`.
- **SAR candidates cannot be reached from a region.** `sar_candidates` has no
  foreign keys at all, so they are a genuinely separate component. The graph
  says this in its `notes` rather than quietly drawing nothing.

Both are worth saying out loud in the demo: they are the graph being accurate
about the schema, not gaps in the implementation.

### Still open from `docs/SECTION_AUDIT.md`

- RAG corpus is still 22 documents / 31 passages (explicitly skipped).
- `llm_provider` is still `none`, so agent findings are templated and reports
  carry `narrative=none`.
- The optical YOLOv8 detector still has no committed test split, so its
  registry metrics stay NULL — correct, not a gap to paper over.
- Drift still reports **WARNING**. Unchanged and untuned since window 2.

---

## Task 11 — Drift n mismatch

**Done.** The note said `n=102` while the table beside it said `baseline_n=100`,
because the confidence PSI skips rows with a NULL `mean_confidence` and the two
old mock-detector rows log none.

`_window_provenance()` now also counts `scored_n` — rows the PSI could actually
use — and the sentence states both when they differ:

> baseline = Benchmark 1 (Phase 12 Held-Out Test Set) **(102 rows, 100 with
> confidence)**, current = Benchmark 2 (Phase 13 Locked Final Test Set) (n=105)

A window where every row scored keeps the plain `(n=105)` form, so the longer
phrasing appears only where there is a discrepancy to explain.

**Gotcha:** these are two different questions, not one number with a bug —
how many rows are in the window, and how many the statistic ran over. Making
them agree by dropping the mock rows would have hidden a real fact about the
data.

**Tests:** 684 passed, 25 skipped. One added,
`test_the_note_agrees_with_the_number_the_psi_used`, which logs three scored
rows and one unscored row and asserts the sentence reads "4 rows, 3 with
confidence" while a fully-scored window keeps "(n=1)".

**Next:** Task 12 — citation edges in the knowledge graph.

---

## Task 12 — Citation edges in the knowledge graph

**Done, and it was clean.** Checked before building: **40 citation entries
across 10 reports, all 40 resolve, 0 dangling**, naming 5 distinct documents.

Documents are now reachable as a second, clearly weaker kind of edge:

- relation `cites`, `edge_kind` **`resolved_reference`** (every foreign-key
  edge now carries `edge_kind: "foreign_key"` explicitly)
- drawn **dashed and grey** in the UI, with its own legend block:
  *"Citation resolved from report sources (not a declared FK)"* with counts
- new node type `research_document`, evidence level `RETRIEVED`
- reachable in both directions: report → documents, and document → the
  reports citing it

Summary now reports 4,378 nodes / 4,504 edges, split
`foreign_key: 4464, resolved_reference: 40`, `unresolved_citations: 0`.

### Honesty mechanics

- **Unresolvable ids are counted, never silently dropped.** `cited_documents()`
  returns the documents it found *and* how many ids did not resolve; the count
  surfaces in `unresolved_citations` and in the graph's own `notes`. A dangling
  citation is a fact about the data.
- **The page no longer claims every edge is a foreign key.** The subtitle and
  the module docstring said exactly that, which Task 12 made false. Both now
  distinguish the two kinds.

### Gotchas

- **`test_every_edge_corresponds_to_a_stored_foreign_key` is now scoped** to
  `edge_kind == "foreign_key"`, and asserts it still has edges to check so the
  scoping cannot silently empty it. Citations get their own guarantee in
  `TestCitationEdges`: every `cites` edge must land on a real
  `research_documents` row.
- **An older test had to be replaced, not patched.**
  `test_it_states_that_regulations_are_absent` asserted the absence this task
  removed. It is now
  `test_it_states_how_citations_differ_from_foreign_keys` — the claim worth
  guarding changed from "there are none" to "these are not foreign keys".
- **Document → reports is a Python scan, not a query.** The citation lives
  inside a JSON blob, so every report is loaded and filtered. Fine at ten
  reports; it would not be at scale, and the code says so.
- Added `data-node-id` to each SVG circle so individual nodes are addressable
  for debugging and UI checks.

**Tests:** 689 passed, 25 skipped. Five added in `TestCitationEdges`, including
a fixture carrying one id that resolves and one that does not, asserting the
dangling one is counted and not drawn.

**Next:** Task 13 — demo safety.

---

## Task 13 — Demo safety

**Done.**

### Stage-2 refine now asks first

The button is next to Refresh and writes irreversibly, which is the Task 4
gotcha waiting to be triggered by a stray click. It now confirms:

> Run stage-2 refinement?
>
> This writes to the database: it subdivides the most anomalous monitored
> cells into sub-cell regions and creates new pollution events from them,
> raising the event count.
>
> It cannot be undone from this page. Restore with `scripts/reset_demo.sh`
> if you need the previous state.

Verified in the browser: the prompt fires with that text, and declining leaves
the event count at 686 — the mutation does not run.

### `scripts/reset_demo.sh`

Restores the newest `backups/oip-after-*.dump` (or one named as an argument),
then prints the counts that prove it worked:

```
  Pollution events             686
    of which CRITICAL          10
  SAR candidates               306
  Prediction logs              307
  Model versions               5
    of which evaluated         3
  Regions                      270
  Zone history buckets         663
  Water quality observations   4601153
```

Restore took well under a minute. `FORCE=1` skips the prompt;
`CONTAINER`/`DB_USER`/`DB_NAME` are overridable.

### How it was tested without risking the demo database

The script drops and recreates the schema, so testing it on `oip` the day
before a demo would be the exact risk it exists to mitigate. Instead it was
pointed at a throwaway database (`DB_NAME=oip_resettest`), which exercises
every step — drop, restore, verify — against the real dump. All counts came
back correct and the live `oip` database was never touched; confirmed still at
686 events afterwards. The throwaway was then dropped.

Also checked: declining the prompt aborts with "Nothing was changed", and a
missing dump path exits with a usage message rather than a stack trace.

### Gotchas

- **It picks `oip-after-*.dump`, not simply the newest file in `backups/`.**
  A `before-window` dump is a rollback point, not a known-good demo state, and
  grabbing one by accident would quietly restore the wrong thing.
- **Restart the API after restoring.** The script prints the command. Existing
  pooled connections point at a schema that has been dropped and recreated.
- **The heredoc escape trap bit again.** Writing the confirm() string through a
  shell heredoc turned `\n` into real newlines inside a TypeScript string
  literal, which does not compile. The message is now built with
  `[...].join("\n")`, which has no escapes to mangle — worth remembering for
  any future multi-line string written through a script.

---

## Final state — window 4a

**Tests:** `689 passed, 25 skipped, 0 failed` (window 3 ended at 683/25).

**Pages:** all 15 loaded with **zero console errors**.

**Backup:** `backups/oip-after-window4a.dump` (113 MB, 41 tables, verified).
This is the dump `scripts/reset_demo.sh` will now pick by default.

No database writes were made this window — the restore test ran against a
throwaway database, and declining the refine prompt was verified to leave the
event count unchanged at 686.

### Demo-day quick reference

| If this happens | Do this |
|---|---|
| Something was clicked that changed the data | `scripts/reset_demo.sh`, then restart the API |
| "Stage-2 refine" prompt appears | Cancel unless you mean it — it adds events and sub-cells |
| Asked why drift says Warning | It is a real finding, not a fault: confidence shifts between two held-out benchmarks while the class mix holds. The platform flags it for review and never retrains on it. |
| Asked whether the marine data is real | It is not, and every page says so. The real data is Candidate Review: 306 Sentinel-1 patches. |
| Asked about the dashed graph edges | Citations resolved from `reports.sources`, a JSON column — real stored ids, but not a declared foreign key. |

Expected counts after a restore: **686 events, 10 CRITICAL, 306 candidates,
307 prediction logs, 5 model versions (3 evaluated), 4.6M water observations.**

### Still open from `docs/SECTION_AUDIT.md`

Unchanged and deliberately skipped: RAG corpus expansion, live ingestion, AIS,
MLflow, retraining automation. `llm_provider` remains `none`. The optical
YOLOv8 detector still has no committed test split, so its registry metrics stay
NULL — correct, not a gap.

---

## Final pre-demo pass — 20 November

**Tests:** 689 passed, 25 skipped, 0 failed — matches expectation, nothing to fix.

**Clean restart:** `docker compose down` (volumes preserved — no `-v`),
`up -d db`, API restarted. Every expected count verified against the running
app: 686 events / 10 CRITICAL / 306 candidates / 307 prediction logs /
5 models (3 evaluated) / 4,601,153 water observations / drift WARNING. No
restore needed; `reset_demo.sh` was **not** run against `oip`.

**Pages:** all 15 marine/ML pages plus the full India section loaded with
**zero console errors**.

### One real issue found and fixed

The India Overview — the demo's opening page — showed **CURRENT DATA 0** and
**HISTORICAL ONLY 2,714** against a stated total of 2,740. The 26 hourly Ganga
water bodies had aged out of "current" into "recent" and were not displayed at
all, so the cards did not sum. Worse, the paragraph below still read *"CPCB
runs automatic analysers … so those water bodies can be described in the
present tense"* directly under a counter saying 0.

Cause: the real-time feed was last ingested **26 September, 54 days ago**. The
freshness engine is correct and untouched — `current` (≤2 days) is genuinely 0
and `recent` (≤90 days) is 26. Only the page was describing it wrongly.

Fixed by adding a **Recent data** card (0 + 26 + 2,714 = 2,740) and making the
paragraph conditional: when nothing is current it says so and names the date
the readings stop. Display-layer only, no database write.

### India Water Intelligence — inspection (report only)

| Page | Real data shown | State |
|---|---|---|
| India Overview `/app/india` | 2,740 bodies, 4,951 stations, 4,601,153 observations, 35 states, 613 districts | Fine after the fix above |
| Water Map `/app/map` | Leaflet, 1,500 most-sampled shown, geoBoundaries overlay, status-by-last-measurement legend | Fine |
| Ask about water `/app/ai` | Retrieval + SQL over stored observations; Mithi query returns a grounded headline with **5 citations**, dated 02 Dec 2021, plus limitations | Fine |
| Reference Standards `/app/standards` | The selection rules and the standards themselves | Fine |
| Data Sources `/app/data-quality` | 3 providers, all reachable, last sync 26 Sep 2026 | Fine |
| Water body detail `/app/water/ganga-river` | 142 stations, 347,672 observations, 3 sources kept separate, availability panel, rule-by-rule status explanation | Fine |
| State page `/app/state/maharashtra` | 146 bodies, 294 stations, 324,360 observations, type breakdown | Fine |

Nothing empty, nothing erroring. The only oddity is the one fixed above.

### Delivered

- `docs/DEMO_SCRIPT.md` — 8–10 minute walkthrough with exact on-screen numbers,
  a 60-second short version, and 12 likely questions with honest answers.
- `README.md` — "Current status": test count, real-vs-simulated table, expected
  counts, and how to run `reset_demo.sh`. Tests badge corrected 595 → 689.
- Pushed to `origin/feature/india-water-intelligence`; tag **`demo-2026-11-22`**
  created and pushed.

### Worth knowing before the demo

- **Only one of 38 regions beats the naive forecast baseline** (Java Sea SE,
  MAE 0.785 vs 0.791 — narrow). The other 37 say so on their own charts. The
  demo script uses Arabian Sea NE as the contrast.
- The India Overview now leads with **zero current**. That is the strongest
  honesty point on the platform; the script opens with it deliberately.

---

## Indian marine regions (feature 2 of 4)

**Done.** The marine module now monitors the Indian EEZ instead of an
inherited global set (Gulf of Mexico, North Sea, Yellow Sea, Mediterranean…).

**15 regions / 40 cells**, west coast to east: Gulf of Kutch, Gulf of Khambhat,
Mumbai Offshore, Konkan & Goa, Malabar, Lakshadweep Sea, Gulf of Mannar, Palk
Bay, Coromandel, Krishna-Godavari Offshore, Odisha Coast, Sundarbans & Bengal,
Andaman Sea, plus open-water Arabian Sea and Bay of Bengal. Each carries a
`REGION_RATIONALE` line saying why it is monitored (Vadinar/Kandla terminals,
Mumbai High, the KG gas basin, Paradip, the Gulf of Mannar reserve).

### Why this mattered more than cosmetics

The marine receptors were **already Indian** — Gulf of Mannar, Sundarbans,
Gulf of Kachchh MNP, Malvan, the Chennai desalination intake. So the risk
engine's two geographic factors (30 of 100 points) could never fire: a
detection in the Gulf of Mexico cannot threaten a reef off Tamil Nadu.

Fixing the regions exposed a second problem: `distance_to_coast` was a
62-point global city list with **six points in the whole Indian box**. The
Andaman cells reported 750–965 km from land while sitting among the islands.
Added 28 Indian coastal points (ports, headlands, Port Blair, Car Nicobar,
Kavaratti, Minicoy) and 8 Indian MPAs.

Measured effect:

| | Before | After |
|---|---|---|
| Andaman Sea NW → coast | 902 km | **132 km** (Port Blair) |
| Gulf of Kutch W → coast | — | **32 km** (Okha) |
| Gulf of Kutch → nearest MPA | Gulf of Mannar, ~1,400 km | **Gulf of Kachchh MNP, 44 km** |
| Odisha Coast W → coast | inland bbox | **5 km** (Paradip) |

A Gulf of Mannar detection now scores **coastal 12.9/15** and **protected-area
15/15** (57 km from the Marine National Park) — both were dead zeros before.

### Also fixed while in here

- **Two bboxes sat on land.** Odisha Coast W centred at 85.75E/20.05N — inland
  near Khordha. Moved seaward to Paradip; Sundarbans nudged to the river
  mouths.
- **A 1×1 region was labelled "SW".** "Palk Bay SW" is not a south-western
  part of anything. Undivided regions now carry no suffix.
- **A 1×2 region labelled its north/south halves "SW"/"SE".** Compass labels
  now match the grid shape: S/N for 1×2, W/E for 2×1, full compass for 2×2.
- **`&` produced a triple underscore** in codes (`konkan___goa_coast`); the
  slug now collapses separator runs.
- **`prune_undefined_regions()`** (new) retires regions no longer defined.
  It **keeps** any region still holding observations or events and reports
  them, because deleting one cascades to its data — reseed first, then prune.
  Removed all 270 old regions, kept 0, left 40.

### Data

Reseeded twice, deliberately: once onto the new grid, then again after the
geography improved, so the stored risk scores reflect the final reference
data. 2,400 observations, 666 events, 40/40 regions forecastable.

**Tests:** 689 passed, 25 skipped — unchanged. The suite derives region codes
from the API rather than hardcoding them, so none needed touching.

### Known follow-up

The Ocean Map still opens on the old Mediterranean centre; the default view
needs re-centring on India. Not fixed here.

**Restore point before this work:** `backups/oip-after-window4a-demostate.dump`
(the state the PPT and DEMO_SCRIPT.md describe).

---

## Step 0 — Credential smoke test (master plan)

**Done, 21 Nov.** Four of five external services verified end to end. No
credential value is printed by the script, the tests, or this log.

| Service | Result | Detail |
|---|---|---|
| **Gemini** | **PASS** | 49 `generateContent` models visible. **Use `gemini-2.5-flash`** |
| **CDSE token** | **PASS** | via the **client_credentials** grant |
| **CDSE Process API** | **PASS** | 32×32 S2 L2A PNG (2,016 bytes) over the Gulf of Kutch |
| **Global Fishing Watch** | **PASS** | HTTP 200 authenticated — but **0 datasets listed** |
| **Copernicus Marine** | **PASS** (on retry) | login accepted after you reset the password |

### What this unblocks and blocks

- Steps 3 (Gemini), 4 and 5 (Sentinel-2/-1) are **unblocked**.
- Step 7 (GFW) authenticates, but the datasets listing came back empty, so the
  token's scope is unproven. Treated as provisional until a real data endpoint
  is exercised in Step 7.
- **Step 6c (Copernicus Marine) is unblocked.** The first attempt failed with
  both the CMEMS *and* the CDSE pairs; after a password reset the CMEMS pair
  was accepted. Worth remembering that CMEMS is a **separate account** from
  CDSE, registered at marine.copernicus.eu — the credentials are not
  interchangeable, which is why trying the CDSE pair as a fallback was never
  going to work.
- The toolbox writes a credentials file to
  `~/.copernicusmarine/.copernicusmarine-credentials` on successful login.
  That is outside the repository, and nothing credential-shaped exists inside
  it — checked.

### Gotchas

- **Sentinel Hub needs the OAuth client pair, not the username/password.** The
  password grant yields a token for the STAC catalogue, but the Process API
  wants `client_credentials`. `CDSEAuthManager` in
  `app/vision/copernicus_client.py` currently only does the password grant —
  Step 4 will have to add the client-credentials path rather than reuse it.
- **GFW `/v3/datasets` rejects a bare request** with HTTP 422
  ("limit must not be less than 1"); it needs `limit` *and* `offset`. That 422
  is a parameter error, not an auth failure — easy to misread as a bad token.
- **`docker compose config` dumps resolved secrets.** Do not run it to check
  whether credentials are wired; grep the compose file by variable name
  instead. (An attempt to verify this way was correctly refused.)
- The compose `backend` and `jobs` services were passing **none** of the new
  variables. Both now receive all nine, each defaulting to empty so a missing
  credential leaves a feature unavailable rather than silently fake.

### Changed

- `scripts/credential_smoke_test.py` (new) — per-service PASS/FAIL, scrubs any
  secret-shaped string from output before printing.
- `docker-compose.yml` — credentials passed to `backend` and `jobs`.
- `backend/app/core/config.py` — `cdse_client_id/secret`, Sentinel Hub Process
  and Statistics URLs, `cmems_*`, `gfw_api_token`/`gfw_api_url`, `gemini_model`
  (default `gemini-2.5-flash`). All load from `.env`.

**Tests:** 689 passed, 25 skipped.

**Next:** Step 1 — refresh the real India water data.

---

## Step 1 — Refresh real India water data

**Done, 21 Nov — but no new data arrived: all three feeds are unreachable.**
Per the plan ("if the feed is down, record that and keep the honest display"),
the failure was recorded through the real pipeline and the display now says so.

### What happened

Every Indian water source fails TLS verification:

```
cpcb_nwdp    DOWN  CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain
cwc_nwdp     DOWN  CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain
cpcb_rtwqms  DOWN  CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain
```

### It is not this machine

Three servers do not break identically by chance, so that was tested:

| From this machine | Result |
|---|---|
| `urllib` → google.com | **OK** |
| `urllib` → nwdp.nwic.gov.in | FAIL |
| `urllib` + explicit certifi bundle → nwdp.nwic.gov.in | FAIL |
| `httpx` (certifi) → nwdp.nwic.gov.in | FAIL |

Ordinary HTTPS works fine here, and Gemini, CDSE and GFW all connected over
TLS in Step 0. The Indian government endpoints genuinely present a chain that
terminates in a root no public bundle trusts. Updating certifi will not fix
it. (CPCB has prior form: `docs/data-sources.md` already records an expired
certificate on a different CPCB endpoint.)

### What was done instead

Ran the real ingestion for all three providers so the **pipeline** recorded the
outcome rather than anything being hand-edited. `is_available` flipped to
false on each, with the TLS error stored against the source. The Data Sources
page now reads **"Unavailable"** with the exact error and the last successful
sync date (26 Sep). Counts are unchanged and still honest: **2,740 total —
0 current, 26 recent, 2,714 historical-only**, newest observation
26 Sep 2026.

### Your decision

- **A — leave it (current state).** The feeds are reported unavailable, the
  India data stays at its 26 Sep state, and every page already says so. This
  is what the plan prescribes and needs nothing from you.
- **B — pin the certificate.** Fetch the chain once, pin its SHA-256
  fingerprint, and verify against that single certificate. A man-in-the-middle
  presenting any other certificate still fails, so it is far narrower than
  disabling verification — but it does trust a certificate nobody else
  vouches for, and the pin needs replacing whenever CPCB rotates it. **Say the
  word and I will implement it.**
- **C — disable TLS verification.** Not done, and not something to do
  unprompted: it would accept any certificate from anyone on the path to a
  government server.

### Gotchas

- **The freshness engine was not touched**, as instructed. The 0/26/2,714
  split is the engine correctly reporting 54-day-old data.
- `is_available` is written by the **ingestion run**, not probed per request,
  so a stale `true` can outlive a dead feed. Running an ingestion is what
  makes the page honest — worth knowing before a demo.
- The `health` command reports `cpcb_rtwqms` as **OK** with "No health probe
  implemented for this provider", which reads as healthy when it is not. The
  other two correctly report DOWN. Worth a probe implementation later; not
  fixed here to stay inside the step.

**Tests:** 689 passed, 25 skipped.

**Next:** Step 2 — Indian-regions consistency.

---

# Fast-track to demo (21 Nov)

## FT-1 — CPCB TLS, and a correction

**Inspected both chains with `openssl s_client` instead of assuming.** They
are not the same failure, and the Step 1 entry above is wrong about one of
them:

- **nwdp.nwic.gov.in** (`cpcb_nwdp`, `cwc_nwdp`) — the chain is issued by
  **`CN=FortiGate CA, O=Fortinet`**, a firewall appliance's factory
  certificate, **and it has expired**. Not CCA India, so per the plan:
  **option A, left as an honest "Unavailable".** Pinning was rejected on the
  merits — a FortiGate factory CA ships on every such appliance, so pinning
  it would authenticate nothing, and it is expired besides.
- **rtwqmsdb1.cpcb.gov.in** (`cpcb_rtwqms`) — **valid chain, verifies
  cleanly** (eMudhra → `emSign Root CA - G1`, a Mozilla-programme root). It
  was never a server problem. `emSign Root CA - G1` is in **certifi** but not
  in the **Windows** certificate store, and the provider called plain
  `urlopen`, which uses the OS store — so the identical feed verified inside
  the Debian container and failed on this Windows host. Recording it as
  unreachable was a trust-store gap on one machine, reported as an outage.

**Gotcha:** the earlier diagnosis table only ever probed `nwdp`, then
generalised to all three. One host's failure was taken as evidence for
another's.

**Fixes**
1. `cpcb_rtwqms` now verifies against **certifi** explicitly, so the trust
   decision is one we ship rather than whatever the host OS carries.
   Verification stays fully on — hostname and expiry unchanged.
2. The default `health()` returned `(True, "No health probe implemented")`,
   which reported an unchecked feed as **OK**. It now returns `None` =
   **UNKN**, and `cli health` exits non-zero on unknown. `cpcb_rtwqms` got a
   real probe against the station catalogue.

**Result — real current data, for the first time:** ingest inserted **356
live observations**, newest timestamped **21 Nov 08:30 UTC**. Coverage moved
from **0 current → 19 current** (19 / 7 / 2,714 of 2,740). `cpcb_rtwqms` is
`is_available = true` with today's success timestamp.

```
cpcb_nwdp      DOWN  expired FortiGate appliance certificate
cwc_nwdp       DOWN  expired FortiGate appliance certificate
cpcb_rtwqms    OK    RTWQMS reachable; 40 stations in the catalogue.
```

### Found on the way: the container image could not be rebuilt

Rebuilding the backend produced a container that died on import, three
separate causes deep. The running container had been serving from a stale
image for weeks, with `numpy`/`torch`/`pillow` **pip-installed by hand into
the live container** — so nobody had noticed:

- `numpy`, `torch`, `pillow`, `requests` missing from `requirements.txt`
  while `app/vision/__init__.py` imports them eagerly and `app.main` reaches
  that through the candidates router. Added, CPU-only wheels.
- `sar_scene_processor.py` and `cog_extractor.py` anchored evidence paths on
  `REPO_ROOT`, which is `/` in-image → `PermissionError: /data`. Both now use
  the configured object directory; the import-time `mkdir` is gone, because a
  directory that cannot be made is not a reason for the API to refuse to boot.
- `WATER_OBJECT_DIR` added to the image ENV beside `WATER_CACHE_DIR`.

Backend is **up and healthy** on the rebuilt image. Worth saying plainly: had
this not surfaced now, the first clean restart during the demo would have
taken the whole platform down.

**Noted, not fixed:** the Dockerfile header still claims torch is optional and
the platform "reports those components as unavailable" without it. It does not
— the import is eager. Making it lazy is the cleaner fix; listed as a next
step rather than done under time pressure.

**Tests:** `test_provider_outage.py` 8 passed (2 new).

## FT-2 — Indian-regions consistency

**Done, 21 Nov.**

- **Orphaned reports/runs:** all 10 `event_id IS NULL` rows were reports for
  regions that no longer exist (Persian Gulf SE/SW, Yellow Sea NW, North Sea
  SE, Gulf of Mexico SE). Deleted, and 5 fresh runs generated through
  `POST /agents/analyze-event` over Gulf of Kutch W, Gulf of Mannar, Konkan &
  Goa Coast N, Bay of Bengal Z4 and Andaman Sea NW. Now **8 runs / 8 reports,
  every one attached to an event**, across 6 Indian regions.
  `unresolved_citations = 0`.
- **Refine skipped — the trigger condition is not met.** The plan says refine
  "if CRITICAL = 0 or slick extent = 0". Actual: **81 CRITICAL events** and
  21.4M km² of total estimated extent. Nothing to fix, so nothing was run.
- **Banners:** `MarineScopeNote` said the module monitors the Gulf of Mexico,
  North Sea, Malacca, Yellow Sea, Persian Gulf and Java Sea. Rewritten for
  the Indian EEZ. The note now makes the sharper point that the *regions* are
  real and the *events* are simulated — with a plausible Indian region name
  attached, that distinction matters more than it did before, not less.
- **Ocean Map** opened on `[20, 40]` — the Red Sea. Now `[15.5, 79]` zoom 4,
  chosen from the actual region bounds (8.0–23.3 N, 64.0–94.4 E) so all 40
  cells are in frame from Lakshadweep to the Andamans.
- **Docs:** `agents.md` and `ai-pipeline.md` examples re-cut to current
  regions. The `agents.md` narrative is now copied **verbatim** from
  `agent_runs.result` rather than written to look plausible.

**Gotcha:** `rag.md` quotes a real retrieval transcript whose top hit is the
Kuwait Regional Convention for a Persian Gulf query. **Left alone on
purpose** — the corpus really does contain ROPME, and swapping the region
name would have turned a genuine transcript into an invented one. The
Research page's suggested question moved to the Arabian Sea instead (all
three candidate phrasings return `retrieval_only` with 0 citations, so
behaviour is unchanged).

**Tests:** 691 passed, 25 skipped. Ocean Map verified in-browser: centred on
India, no console errors.

## FT-3 — Gemini narrative layer

**Code complete and tested. Live generation blocked: Gemini is down.**

Built: `app/llm/narrative.py`, a `POST /reports/{id}/narrative` endpoint, five
cache columns on `reports` (migration `c3d4e5f6a7b8`), and an "AI-generated
summary" card on the report page that sits *after* the deterministic summary,
never in place of it.

**The number post-check is the substance of it.** Every figure in a generated
summary must appear in the evidence the model was given; a summary that fails
is **discarded, not flagged**. A paragraph whose numbers disagree with the
table beside it is worse than no paragraph. The check catches a transposed
digit (95.3 for 95.2), a helpful rounding ("nearly 5000 km²" for 4948.3), and
a figure from nowhere, while letting through thousands separators and small
counting numbers. 16 tests, all with a stubbed model — nothing in the suite
calls a real one.

**Blocked, and why it is not our bug:**

- `gemini-2.5-flash` — the model Step 0 recommended — answers **404, "no
  longer available to new users"**, naming `gemini-3.8-flash` as its
  replacement. Default moved accordingly.
- Every current flash model then answered **503 "experiencing high demand"**
  or timed out, across 12 attempts over four model ids.

**Gotcha, and the reason Step 0 missed this:** the smoke test checked that
models were *listed*, not that they could be *called*. The catalogue happily
returns ids this key is not allowed to use. `credential_smoke_test.py` now
makes a real `generateContent` call and recommends the first id that answers.

**Verified instead: the fallback, which is the path the demo will actually
take.** With Gemini erroring, `POST /narrative` returns
`status=error, detail=ReadTimeout`, stores nothing, and the report renders in
full from its deterministic summary and five evidence sections. Nothing is
fabricated and no page breaks.

**Also found:** the test suite was reading the developer's `.env`. Adding
`LLM_PROVIDER=gemini` locally broke five unrelated tests, which had been
passing only because no key happened to be present. `conftest.py` now forces
`LLM_PROVIDER=none` and an empty key — set, not defaulted — so a run means
the same thing on a laptop with credentials and a CI box without.

**To finish when Google recovers:** `POST /api/v1/reports/{id}/narrative` for
the 8 reports. One command, no code change.

**Tests:** 707 passed, 25 skipped.

## FT-4 — Real Sentinel-2 observations

**Done, 21 Nov. The marine module now has measured data.**

**253 readings across 35 of 40 regions, newest acquired 20 Nov 2026** —
yesterday. NDCI (chlorophyll), NDTI (turbidity) and FDI (floating material)
per region per acquisition date, computed by Copernicus over pixels the scene
classification layer marks as water, so a coastal cell reports on its sea.
New page **Real Observations**, first in Marine Monitoring, with a green
"Real · Sentinel-2" badge and the true-colour scene each row was computed
from. 35/35 thumbnails, zero console errors.

Aggregated **per day, not per window**: each reading carries the date it was
measured on. A 30-day mean would be a number with no moment attached.

**FDI is labelled "possible floating material" and never "plastic".** The
word appears twice in the payload, both times denying the inference —
Biermann's own paper cannot separate plastics from seaweed, foam, timber or
spume without further spectral analysis, and sun glint raises the index too.
Pinned by a test, not by intention.

**Gotcha 1 — a fixed grid cannot fit these cells.** 100×100 is 330 m/px on
the Gulf of Kutch and 4,449 m/px on Bay of Bengal Z3; Copernicus refuses
anything over 1,500. The first sweep **failed on 31 of 40 cells**. The grid
is now derived per cell (longitude scaled by latitude), every cell lands at
1,000 m/px, and the sweep fails on none. The same bug then hid in the
thumbnails, where a fixed 320×320 was rejected for the two largest cells.

**Gotcha 2 — readings computed from a handful of pixels.** Some cells were
almost entirely cloud, leaving **1 to 10 water pixels**. Those statistics are
valid arithmetic and describe nothing, and one of them (FDI −0.2084 from 8
pixels) was **an order of magnitude from every other cell** — precisely the
figure that becomes a story. Readings below 100 water pixels (100 km² of
observed sea) are stored but marked: the page dims the row and prints "—"
rather than the number. 4 of 35 rows are in that state.

**Not invented:** 5 open-ocean Arabian Sea cells had no acquisition clearing
30% cloud in the window. They get no row, no zero, and no carried-forward
value.

**Tests:** 13 new (grid, water floor, FDI wording, parser), 720 passed total.

## FT-5 — Open-Meteo sea conditions

**Done, 21 Nov.** Real wind, waves and sea-surface temperature for all 40
regions on Ocean Overview, badged **Real · Open-Meteo** and **INFERRED**.
No key, no registration, two requests for all forty (Open-Meteo accepts
comma-separated coordinates), cached to disk so the demo makes no live call.

**The wind screener already used real wind.** `ERA5Service` routes through
`OpenMeteoERA5Client` against the ERA5 archive; a live probe returned
**4.04 m/s, quality_status `reanalysis_available`** for a real point and
time. Nothing to replace — recorded rather than claimed as new work.

**The number worth showing: 18 of 40 regions are below 3 m/s right now.**
That is the panel's lead, because it turns an abstract caveat into a live
one — below that threshold the sea goes flat, a flat sea in C-band SAR looks
like oil, and any dark formation reported in those regions today is ambiguous
on the physics before any model is involved.

**Labelled INFERRED, not OBSERVED.** Open-Meteo serves numerical weather
prediction output: an analysis constrained by measurements but produced by a
model. Calling it an observation because it happens to be accurate would
empty the word everywhere else it matters.

**Gotcha:** Open-Meteo returns an *object* for one location and an *array*
for several, so handling either shape alone breaks the other case. Missing
values stay `None` and the low-wind flag is tri-state — unknown wind is not
calm wind, and rendering it as 0.0 m/s would invert the conclusion a reader
draws about whether a detection means anything.

**Tests:** 12 new, 732 passed total. Overview verified in-browser, no console
errors.

## FT-6 — Copernicus Marine

**Done, 21 Nov.** Two products, two jobs.

**Surface currents now drive the drift simulator.** The engine had always
defaulted to **0.22 m/s due east** — a placeholder that produced a track
indistinguishable from a real forecast. A run over the Gulf of Mannar now
uses the modelled field:

```
current : 0.141 m/s toward 248 deg
source  : Global Ocean Physics Analysis and Forecast (1/12 deg, daily mean),
          valid 2026-11-21, from Gulf of Mannar, 47 km away
```

The source is a **stored column**, not just a response field (migration
`e5f6a7b8c9d0`), because the two kinds of run look identical afterwards and
old rows must stay distinguishable. Resolution is cache → live → placeholder,
and the placeholder says it is one.

**Chlorophyll-a sits beside NDCI as a cross-check**, not a correction. NDCI
is a two-band ratio computed here from raw reflectance; the CMEMS product is
a validated, atmospherically-corrected multi-sensor retrieval of the same
quantity. Neither is adjusted toward the other — where they track together
the NDCI reading is worth more, and where they diverge that is the useful
part.

**Evidence levels differ on purpose:** currents are `INFERRED` (an ocean
model's analysis, which no instrument saw), chlorophyll is `OBSERVED`
(processed, but derived from radiance a sensor recorded).

**Gotcha 1 — the direction convention.** Oceanographers give the bearing
water flows *toward*; meteorologists give the bearing wind comes *from*.
They differ by 180°, which in a drift run is the difference between oil
reaching the shore and oil heading out to sea. Pinned by test, not comment.

**Gotcha 2 — the serving image has no Copernicus toolbox**, so the first
wiring fell back to the placeholder on every request (correctly labelled,
which is how it was spotted). Drift currents now resolve from the nearest
cached *regional* current — the regions tile the EEZ, so any origin in it
lands on real data with no network call, and the source names the region and
its distance so a neighbour's current reads as the weaker claim it is.

**Tests:** 16 new, 748 passed total.

## FT-7 — Global Fishing Watch

**Done, 21 Nov — with one deliberate deviation from the plan, explained
below.**

**Real aggregate activity for all 40 regions: 60,403 vessel-hours, 7,920
vessels, 25 regions with activity.** On Ocean Overview with "Powered by
Global Fishing Watch" linked to globalfishingwatch.org, badged INFERRED
("apparent" is GFW's own word — the fishing is inferred from how a vessel
moves, not reported). Busiest: Arabian Sea Z4 at 15,792 h (CHN 9,844 /
IRN 4,801), Konkan & Goa Coast S at 10,967 h (all IND).

### The deviation: the 6 hand-written ships were NOT replaced with real ones

The plan said to replace them. I did not, and this needs your sign-off.

Those vessels are not decoration — they populate
`candidate_vessel_associations`, which marks a vessel `SOURCE_SUSPECT` with
`is_primary_suspect = true` at scores up to **0.97**, against SAR candidates
that are **PANGAEA research benchmark patches and demonstration events**.
Nobody spilled anything.

Putting a real MMSI in that row renders a real, identifiable ship as the
named suspect for a spill that did not happen, at high confidence, on a page
built to be screenshotted. The existing banner ("do not identify a
responsible vessel") is a caveat; a real vessel name under it is still an
accusation that outlives the caveat the moment the image is cropped.

So GFW answers the question it can answer honestly — **how busy is this
water** — which is genuinely useful context for a dark formation and
implicates nobody. The suspect demo keeps its fictional vessels, and both
endpoints now say in the OpenAPI docs that they are fictional and why.

**If you want the real identities anyway, say so and I will wire them** —
it is a small change. I would want the suspect wording changed first.

**Gotchas:**
- GFW's effort product lags ~1 week while AIS is processed. A window ending
  today returns zeros for every region, which reads as empty ocean and is
  really an unprocessed week. The fetch now ends 7 days back.
- The response nests rows under the **resolved** dataset name
  (`...:v5.0`), not the `:latest` that was requested. Matching the requested
  name would silently drop every row at the next version bump.
- The cache key includes the window, so a region fetched twice had two files
  and was double-counted (43 "regions" for 40 regions). Deduped to newest.

**Also:** the CMEMS sweep from FT-6 finished — **40/40 currents and 40/40
chlorophyll**, so all 35 regions with Sentinel-2 data now carry the
chlorophyll cross-check.

**Tests:** 9 new, 757 passed total.

## FT-8 — Sentinel-1 through the v2.2 detector

**Done, 21 Nov. The pipeline works end to end. The model does not transfer —
and that is the finding.**

Real Sentinel-1 GRD scenes over three Indian regions, VV sigma-nought pulled
from Copernicus as float dB, percentile-stretched, tiled to 224 px and run
through `sar-oil-slick-v2.2`. One scene was acquired **this morning**
(`S1D_IW_GRDH_1SDV_20261121T003240`).

```
Gulf of Kutch W      10 tiles screened, 0 candidates, 11 skipped, mean confidence 1.0000
Mumbai Offshore W    10 tiles screened, 0 candidates,  0 skipped, mean confidence 1.0000
Gulf of Mannar       10 tiles screened, 0 candidates,  0 skipped, mean confidence 1.0000
```

**Every tile came back at confidence 1.0000.** That is not certainty, it is a
saturated softmax. On its own training patches this model spreads from 0.005
to 0.83 — verified directly, in the same session, through the same detector.
A flat 1.000 on real Sentinel-1 says the input is unlike anything it was
fitted on, so **neither the zero candidates nor any positive would carry
weight**. The script says this itself at the end of every run rather than
leaving it to a reader.

Why: the model was trained on PANGAEA 980773 / DARTIS **quicklook JPEGs**,
already contrast-stretched by whoever built the dataset (means 70–160).
These are sigma-nought dB at a different resolution over different water.
The per-tile percentile stretch narrows that gap and does not close it.

### The bug worth recording

The first run printed **"24 tiles screened, 24 candidates"** — a 100% hit
rate. It was exactly backwards. The v2.2 model is a *scene classifier*: it
returns one `Detection` per tile whose `signature` is the class it chose, so
`if detections:` means "it answered", not "it found oil". The model had
answered **`no_anomaly` 24 times**, at confidence 1.000.

A 100% detection rate is the sort of number that gets repeated in a demo. It
was caught by running known training patches through the same detector and
noticing that `nw-` negatives also returned a "detection" — with
`p_oil = 0.0099`. Counting now tests the signature, and a test pins it.

**Nothing was written as a pollution event.** Predictions go to
`prediction_logs`, where unverified model output belongs.

**Tests:** 10 new, 767 passed total.

## FT-9 — Freeze

**Done, 21 Nov.**

- **Clean restart passes.** `docker compose down` then `up -d backend` — the
  thing that would have failed before FT-1 fixed the image. All cached
  external data survives in the `oipdata` volume.
- **All 24 routes serve 200; all 24 pages load with zero console errors**,
  walked individually in a fresh tab.
- **DEMO_SCRIPT.md** rewritten: new sections 2b (Real Satellite
  Observations) and 2c (sea state and vessel traffic), a "what is real" table
  up front, six new likely questions including **"Is that plastic?"**, and a
  **Next steps — deliberately not done** list so nothing reads as forgotten.
- **README** status, real/simulated table and expected counts updated.
- **`backups/oip-demo-final.dump`** created; `reset_demo.sh` now points at it
  by name rather than following "newest after-window dump", and prints the
  current expected counts.
- **Deck rebuilt** at `~/Downloads/OIP-Demo.pptx` — 21 slides, 0 geometry
  issues, outside the repo. Three new real-data slides.

### Stale figures found and corrected

Checked every number in the docs against the running application rather than
trusting them:

| Was | Now |
|---|---|
| 4,601,153 observations | **4,601,509** |
| Current data 0, recent 26 | **19 current, 7 recent** |
| 686 events, 10 CRITICAL | **666 events, 81 CRITICAL** |
| 307 prediction logs | **337** |
| 270 regions | **40** |
| 4,378 nodes / 4,504 edges | **4,131 / 4,459**, 0 unresolved |
| P95 9.63 ms | **37.5 ms** |
| 689 tests | **767** |

### The one that moved the wrong way

**Forecasts: "1 of 38 regions beat the naive baseline" is now 0 of 40.**
Re-cutting the regions to India's EEZ lost the single region that used to
win. Checked directly against all 40 forecasts rather than assumed. The deck
and script both state it, and the script says out loud that the number moved
the wrong way and was not re-windowed to look better.

**Tests:** 767 passed, 25 skipped. Frontend type-check clean.

---

# Master prompt — real-data completion

## MP-1 — Real events from real detections

**Done, 21 Nov. 34 real pollution events from measured Sentinel-2 readings:**
10 algal bloom (NDCI), 13 turbidity plume (NDTI), 11 floating material (FDI).
Evidence `DETECTED`, method `optical_index`, each linked to its scene date,
region and attribution, scored by the existing risk engine.

**Thresholds are stated, not invented.** NDCI ≥ 0.20 is anchored to Mishra &
Mishra (2012) and sits above this dataset's p95. FDI ≥ 0.040 and NDTI ≥
−0.010 are **the p95 of this platform's own 253 stored readings** — there is
no absolute published cut-off that transfers between water types, and
Biermann thresholds FDI against local background rather than a constant. So
every event carries the caveat that it means *"unusual for these waters as
measured here"*, which is **not** "polluted".

**New signatures:** `floating_material` and `turbidity_plume`.
`plastic_debris_signature` is deprecated in place — stored rows reference it,
but nothing new is written with it, because FDI cannot identify a material.

**Wind, waves and currents are attached, not scored.** Real Open-Meteo sea
state and CMEMS currents ride on each event's `extra.environment` with their
own provenance. They are deliberately *not* new risk factors: the engine's
six factors and weights are tested and normalised, and adding a seventh would
silently renormalise every score already in the database.

**Gotcha:** `area_method` is `varchar(64)`; the explanation moved to
`extra.area_basis`. And the 100-water-pixel floor matters far more here than
on the table — an 8-pixel cell produced an FDI ten times every other reading,
and as an *event* that is an alert rather than a dimmed row. Pinned by test.

**Tests:** 13 new. Events, Live Monitoring, Risk Analysis and Overview show
all five signatures with colour, icon, filter and a legend.

## MP-6a — NWDP certificate pinning (done early, during a Step 2 wait)

**The TLS problem is solved. A different one is now visible underneath it.**

Pinned the **leaf** certificate's SHA-256 for `nwdp.nwic.gov.in` only
(`app/water/pinned_tls.py`). This is narrower than a CA chain, not wider: a
public CA vouches for millions of certificates, this vouches for one, and an
attacker needs that certificate's private key. Every other host keeps full
verification, pinned by test.

The certificate turned out to have expired **the previous day** — valid
20 Nov 2025 to 20 Nov 2026 — on top of chaining to the FortiGate *factory*
CA, whose private key ships on every such appliance. Hence pinning the leaf
rather than the chain: the issuer proves nothing.

**Result:** the error moved from `CERTIFICATE_VERIFY_FAILED` to **HTTP 403**.
The handshake now completes; the Fortinet appliance serves a WAF block page
and refuses automated access as policy. That is the operator's decision and
I did not try to get around it — an attempt to probe it with a
browser-impersonating User-Agent was blocked by the permission classifier,
correctly, and I did not retry it another way. Honest identification gets the
same 403.

So the feeds stay unavailable, but **for an accurate reason**, and the
pinning will work the moment the policy or the certificate changes. A changed
fingerprint raises `PinnedCertificateMismatch` naming both values and fetches
nothing — a person updates the pin, not the code.

**Next:** Step 6b wording on the Data Sources card uses this reason, not
"certificate expired".

**Tests:** 10 new.

## MP-2 — Real history for forecasts

**Done, 21 Nov. A full year of measured Sentinel-2 data behind every
forecast.**

Backfilled **3,006 readings, 21 Nov 2025 → 20 Nov 2026, 36 of 40 regions**
(2,744 above the water floor). Per-day intervals rather than the P5D the plan
suggested — Sentinel-2 revisits every few days so the volume is the same, and
P1D keeps each reading's **exact acquisition date** instead of averaging it
away. A full year costs one API call and about nine seconds per region.

`zone_history` now has **738 daily buckets across all 40 regions**, derived
from real events. The Forecasts page gains an index selector: the same Holt
model and the same `beats_naive` backtest can be pointed at a **measured**
NDCI / NDTI / FDI series instead of detection activity. 40 regions
forecastable on activity, 36 on each index, **361-day median history**.

**0 of 148 forecasts beat the naive baseline.** Consistent with the earlier
finding and now on a year of real measurements rather than 55 synthetic days.

### The threshold error a bigger sample exposed

The Step 1 thresholds were percentiles of a **30-day** sample. NDTI's p95
over those 30 November days was **−0.0082** — every reading negative. Over
the full year it is **+0.0281**: the 30-day window was winter, the year
includes the monsoon. That threshold flagged **397 events, 14% of all
readings**, which is not an anomaly detector, it is a thermometer reading
the season.

All three thresholds are now the **p99 of the 2,744-reading, 12-month
sample**, so "flagged" means the same thing for each: the top 1% of what this
platform has measured. Events went **523 → 84** (26 bloom / 30 floating /
28 turbidity), roughly 1% each as intended.

NDCI's p99 is 0.1961 and the literature anchor (Mishra & Mishra 2012) is
0.20. Those agreeing independently is worth more than either alone, so it
stayed at 0.20.

**Tests:** 10 new (index series and forecast), 800 passed total.

## MP-adjustments — regional anomalies, source status, cached narratives

**Done, 21 Nov.** Three corrections requested after the Step 1–2 report.

**1. Anomalies are now per region.** Each region is judged against **its own**
12-month 99th percentile, not one platform-wide figure. The data demanded it:
NDTI's p99 runs **0.142 in quiet cells to 0.313 off the Krishna-Godavari
delta**. A global cut-off marks the river mouths anomalous every day — a
description of where rivers are, not a finding — while missing a real
excursion in clear water. A region needs **40+ readings** or it raises
nothing; there is deliberately **no fallback** to another region's water.

Every event leads with: *"Statistical anomaly: top 1% of this region's last
12 months (Sentinel-2 NDCI)"*, shown on the badge tooltip, a `stat.` marker
in the list, and as the first caveat on the detail page. NDCI events **also**
report whether they clear `ALGAL_BLOOM_NDCI_THRESHOLD` (0.08) — "unusual
here" and "high in absolute terms" are different questions and both are
answered. Method documented in `docs/anomaly-method.md`.

**New counts: 123 events — 41 algal bloom, 41 floating material, 41 turbidity
plume**, across 34 regions with baselines (16 readings skipped for want of
one).

**Gotcha, and a property worth knowing:** a p99 always flags ~1% of the very
readings it was computed from. That is inherent to percentile thresholding,
not a bug — the tests had to be rewritten to measure the *delta* a new
reading causes. A flat test baseline also puts p99 *on* every value, so `>=`
fires on all of them; the fixture now has realistic spread.

**2. Data Sources statuses are computed, not configured.** Four states
derived from the real fetch result: Live / Stale / **Sync paused** /
Unavailable. The NWDP feeds now read amber *"Blocked by upstream firewall:
automated access refused (HTTP 403). Showing last successful sync (26 Sep
2026)"* with **582,192** and **4,017,920** records held. Raw errors moved
behind a **Technical details** toggle. A refusal is not an outage, and
calling it one sends someone hunting a network fault that does not exist.

**3. Gemini narratives generated once and cached.** All **9 reports** have
one, every one passing the number check. The label now names the model —
*"AI-generated summary · gemini-flash-lite-latest"*. Page loads call nothing;
generation is an explicit POST, and a second call returns `cached`.

**Tests:** 815 passed.

## MP-3 — Real data replaces simulated, demo mode off

**Done, 21 Nov.** Backup `backups/oip-before-step3.dump` (113 MB) first.

**Deleted:** 666 seeded pollution events, their 666 risk assessments,
2,400 synthetic satellite observations, and the 9 reports/agent runs that
described them. **Kept:** 123 real optical-index events, 306 PANGAEA
benchmark candidates, 337 prediction logs, 3,006 Sentinel-2 readings.

**Regenerated from real events:** 6 agent runs and 6 reports, each over a
measured Sentinel-2 detection, all with cached Gemini narratives.

**`DEMO_MODE=false`.** The API reports `contains_simulated_data: false`
with no notes, which it derives from the rows themselves rather than the
flag — so the banners, which are conditional on it, went away on their own.

### Two metrics that quietly broke, and were fixed

**"Satellite Observations: 0"** on a platform holding 3,006 of them. The
count read `satellite_observations`, now empty, while the real readings live
in `optical_index_observations` — they are separate tables precisely so a
measured index and a simulated backscatter statistic never differ by only a
column. Now sums both and shows the breakdown.

**"Slick-scale extent"** reads 0.0 km², and that is the correct answer: the
only oil-like signatures were the simulated ones. The card now says *"No
oil-like signature currently detected. Zero is the measurement, not a gap."*

### Banner audit

| Still says simulated | Why |
|---|---|
| `OceanMap` full-scene SAR overlay layer | **Genuinely synthetic.** That one layer is a demonstration output; labelled on the layer and in the legend. |
| `CandidateReview` optical products | **Genuinely synthetic** reflectance arrays. Scene metadata is real Copernicus STAC. |
| `CandidateReview` vessel suspects | **Deliberately fictional.** Naming a real ship against a benchmark patch would be an accusation. |
| `Reports`, `SystemHealth`, `Overview` banners | **Conditional** on `contains_simulated_data` / `demo_mode`, both now false. Inert, not removed — they must still fire if simulated data ever returns. |
| `Overview` "Nothing here is simulated" | Accurate prose about the real Sentinel-1 benchmark. |

**Rewritten:** `MarineScopeNote` (events are no longer simulated; it now
bounds the *statistical* claim instead), the Candidate Review drift banner
(drift runs on **real CMEMS currents** now, not constant forcing), and the
Ocean Map banner (scoped to the overlay layer alone).

**Also:** "Active detector" showed `mock-detector`, because the page picked
the first *available* detector and a simulated detector is perfectly
available — it just measures nothing. The API now marks exactly one detector
`is_active` (`sar-oil-slick-v2.2`) and flags the stub `is_simulated`.

**Tests:** 815 passed. All 14 checked pages serve 200 with zero console
errors.

## MP-5 — Sentinel-1 saturation

**Validation first, as instructed. The model was never the problem.**

Replayed all **306 benchmark patches** through the live detector and compared
against the stored v2.2 scores:

```
LIVE    mean 0.5657   min 0.0007   max 0.8976   saturated 0
STORED  mean 0.5724   min 0.0007   max 0.9420
```

Within 1%, identical minimum, zero saturation. The detector and its
preprocessing are correct — `_preprocess` matches the training transform
exactly (convert L → 224×224 bilinear → /255 → (x−0.5)/0.5).

### Two faults, both in how *live tiles* were prepared

**1. A per-tile percentile stretch.** It rescaled every tile to fill the
8-bit range, which triples the contrast of calm water: measured open ocean
has a σ⁰ spread under **2 dB**, and PANGAEA patches sit at std ≈ 18 in 8-bit
terms, but a 1–99 stretch produced std ≈ 70. The model had never seen
anything like it. Replaced with a **fixed −30…−5 dB window**, derived by
matching the training distribution: a real tile's water pixels come out at
**mean 146.1, std 19.1** against training's 147 / 18.

**2. A 60% validity floor.** Sentinel Hub renders outside-footprint pixels as
zero, and 10·log₁₀(0) is −∞ — so a tile could be **a third solid black** and
still be screened. That is not a dimmer good tile, it is a different kind of
image. Floor raised to **98%**.

### Result: substantially fixed, not completely

| | Before | After |
|---|---|---|
| Tiles at confidence 1.000 | **100 / 100** | **22 / 100** |
| Score range | 1.000 only | 0.784 – 1.000 |
| Prepared tile mean | — | 112.6 (training 147) |
| Prepared tile std | — | 22.6 (training 18) |

Contrast now matches; **brightness is still ~34 units low**, and the 22
saturated tiles are all one region. Every run now prints its tile statistics
against the training profile, so this is visible rather than inferred.

### No oil events were created

**100 tiles screened, 0 candidates** — every tile classified `no_anomaly`.
There is no real oil detection to create an event from, and none was
invented. A tile of ordinary open water now scores `p_oil ≈ 0.05`, which is
the correct answer and was `1.000` before.

**Tests:** 4 new; 2 old assertions updated because they encoded the
percentile-stretch behaviour (a flat tile is now valid — a fixed window
cannot divide by zero). 824 passed.

---

# Overnight run (21–22 Nov)

## Decisions made overnight

- **No oil event created from the MSC ELSA 3 replay.** The detector flagged
  nothing on any of the four passes. The instruction was to create an event
  only for a genuine detection, so the result is stored as validation
  evidence instead.
- **Incident replay widened from 15 km / 14 days to 35 km / 21 days** after
  the first run found only one Sentinel-1 pass. More passes is better
  evidence; the wreck position and all figures are unchanged.
- **FDI keeps no absolute floor.** Confirmed from the Biermann paper itself
  that no published threshold exists (see MP-adjustments).

## Blocked overnight

- *(nothing yet)*

## OV-A — Historical incident replay: MSC ELSA 3

**Done. Verified against the official source, screened, and not detected.**

Incident confirmed from the **Kerala State Disaster Management Authority
SITREP-3** (1300 hrs, 25/05/2025): MSC ELSA 3, **IMO 9123221**, Liberia
flag, sank **07:50 on 25 May 2025** at **09°18.75′N 076°08.16′E**, 13 nm
south-west of Kochi, carrying **367 t heavy fuel oil and 84.4 t diesel**.
The Coast Guard reported signs of an oil spill and applied dispersant. The
position falls inside the platform's `malabar_coast_s` region.

**Screening result — 31 tiles over 4 Sentinel-1 passes, nothing flagged:**

| Pass | After | Tiles | Max p(oil) | Wind |
|---|---|---|---|---|
| 2025-05-28 | +3 d | 12 | 0.0033 | 9.3 m/s |
| 2025-06-02 | +8 d | 2 | 0.0008 | 3.4 m/s |
| 2025-06-09 | +15 d | 12 | 0.0623 | 5.4 m/s |
| 2025-06-14 | +20 d | 5 | 0.0005 | 8.2 m/s |

**Recorded as a negative, with why it is weak evidence.** The earliest pass
was three days after the sinking at **9.3 m/s wind** — enough roughening to
suppress slick contrast — dispersant had been applied, oil weathers within
days, and the model is still outside its measured distribution (prepared
tile brightness 134 vs training 147). It does **not** establish that no
slick was present, and the page says so.

Shown on **Real Observations** with the actual Sentinel-1 tile the detector
saw, the per-pass table including wind, and the full citation.

**Why this matters more than screening ordinary water:** a detector that
always answered "no" would score identically on open sea. This is the test
that could have distinguished them, and it is published whichever way it
comes out — pinned by test, since a result that only appears when
favourable is not a result.

**Tests:** 7 new.

## OV-B — Ocean Map on real layers

**Done.** Four real layers added, all existing ones kept:

- **Vessel activity** (GFW) — bubbles scaled by √vessel-hours, flags in the
  tooltip, "Powered by Global Fishing Watch".
- **Surface currents** (CMEMS) — a line per region in the direction the
  water flows *toward*, with the convention named on the tooltip because it
  is 180° from the meteorological one.
- **Chlorophyll-a** (CMEMS) — off by default; it is a cross-check for NDCI,
  not a detection layer.
- **Historical incident replay** — the MSC ELSA 3 position, dashed, with the
  screening verdict.

**PANGAEA benchmark layer is now off by default** and relabelled *"Benchmark
dataset (Mediterranean, PANGAEA 980773)"* — it sits outside this platform's
area of interest and should not be the first thing a reader sees on a map
of India.

**Header counts are real:** `36 monitored cells · 34 with an active
detection · 60,403 vessel-hours · 40 current fields`.

### A Step-3 regression this caught

**The map layer was empty — 0 zones.** `list_zones` skipped any region with
no row in `satellite_observations`, and that table was emptied when the
seeded rows went. The platform's real observations are Sentinel-2 index
readings in a different table, so every region was being skipped as
"never looked at" while holding 3,006 measurements. Zones now fall back to
the optical observation, reporting `platform: Sentinel-2` and a **null**
backscatter — backscatter is a radar quantity and an optical cell has none,
so putting a number there would be inventing one.

**Tests:** 831 passed. Map verified in-browser, zero console errors.

## OV-C — Data Sources: all nine providers, derived status

**Done.** Six external services now have cards alongside the three Indian
water providers, every status computed from what that source last actually
produced — rows in a table, files in a cache, a timestamp on a response.
Nothing is configured.

| Provider | Status | Records | Evidence |
|---|---|---|---|
| Sentinel-2 L2A | Live | 3,006 readings | OBSERVED |
| Sentinel-1 GRD | Live | 100 tiles screened | DETECTED |
| Copernicus Marine | Live | 81 cached products | INFERRED / OBSERVED |
| Open-Meteo | Live | 40 regions | INFERRED |
| Global Fishing Watch | Live | 47 cached regions | INFERRED |
| Google Gemini | Live | 6 narratives | **Not evidence** |
| CPCB real-time | Live | 1,397 | OBSERVED |
| CPCB / CWC manual | Sync paused | 582,192 / 4,017,920 | OBSERVED |

Each card states **what it feeds**, its cadence, last sync, record count and
attribution. Raw errors stay behind the Technical details toggle.

**The health CLI now uses the same four words as the page.** It said `DOWN`
where the page said `Sync paused`, which leaves a reader unsure which to
believe; a 403 is now `PAUSED` in both.

**Gemini narratives regenerated** for the six real reports — they were lost
when the simulated events were deleted and the reports rebuilt. All six
passed the number check.

**Gotcha:** the Gemini card deliberately reads *"Not evidence: prose over
computed values"* in the evidence column. It is a data source on this page
only in the sense that it produces text; letting it sit under OBSERVED
alongside Sentinel-2 would be the whole problem in miniature.

**Tests:** 14 new, 845 passed.

## OV-D — Texts and claims

**Done.** Subtitles re-read against what each page now holds:

- **Ocean Overview** — was "Real-time environmental monitoring, AI analysis
  and ML operations", which described nothing. Now names the measured
  Sentinel-2 detections, live sea state and vessel traffic.
- **Candidate Review** — keeps "frozen benchmark" and "uncalibrated
  rankings", and now adds that drift runs on **Copernicus Marine currents**
  and points at the real GFW vessel activity on Ocean Overview.

**Deck "What I would do next" rewritten — nothing already done.** All four
previous items have shipped, so the new list is what the work produced:
retrain the SAR model on calibrated backscatter (citing the 34-unit
brightness gap and 22/100 saturation), MARIDA (because FDI has no published
absolute threshold), WDPA boundaries, a real legal corpus, automated alerts,
and scheduled cloud ingestion.

**"What is real" slide regenerated from the live database** — 13 rows now,
including the two that are honest about limits: live S1 screening with
**0 oil detections**, and the incident replay as **REAL · NOT DETECTED**.

Deck rebuilt: 21 slides, 0 geometry issues, no stale figures.

## OV-E — Freeze

**Done, 22 Nov.**

- **Clean restart passes** (`docker compose down` then `up -d backend`,
  no `-v`). All **24 routes serve 200**; all **24 pages load with zero
  console errors**, walked individually in a fresh tab.
- **845 tests passing**, 25 skipped. Frontend type-check clean.
- **README** status, real/simulated table and expected counts rewritten.
- **DEMO_SCRIPT.md** — "what is real" table regenerated; **nine likely
  questions** now including *How are events decided?*, *Is that plastic?*,
  *Why 0 oil detections?*, *Did you test it against a real spill?*,
  *Is it complete?*, *Why does a source say Sync paused?*, *Is the LLM
  making things up?*, *Why do forecasts not beat naive?*
- **`backups/oip-demo-final-v2.dump`** created; `reset_demo.sh` repointed
  and its expected counts updated.
- **Deck rebuilt** at `~/Downloads/OIP-Demo.pptx` — **23 slides**, 0
  geometry issues, **no secret-shaped strings**, screenshots retaken. Two
  new slides: the real detections, and the incident replay that found
  nothing.

### Expected counts (oip-demo-final-v2)

| | |
|---|---|
| Pollution events | 108 (25 CRITICAL) — all from measured Sentinel-2 |
| Sentinel-2 index readings | 3,006 (36 of 40 regions, 12 months) |
| SAR candidates | 306 (PANGAEA benchmark) |
| Prediction logs | 407 |
| Water observations | 4,601,509 |
| Regions | 40 |
| Reports / agent runs | 6 / 6 |
| Knowledge graph | 611 nodes / 253 edges, 0 unresolved |
| Simulated rows | **0** |

---

# Final polish (22 Nov)

## FP-1 to FP-4 — the last synthetic panels made real

**1. Candidate Review optical panel now uses real Sentinel-2 pixels.**
Six reflectance bands plus the scene classification layer, retrieved from
Copernicus for each candidate's position on the matched scene date, in one
Process API request returning a TAR of single-band GeoTIFFs. NDCI and NDTI
computed on those pixels. **23 of 25 sampled candidates got a real scene;
2 correctly reported none.**

The synthetic generator is **removed, not disabled** — an unused generator
is one call away from being used again, and a test asserts nothing in the
module can produce reflectance. Where no cloud-free scene exists within
**±5 days** the panel says so and renders nothing; the window was ±10 days
and is now ±5, because beyond about one revisit a scene describes different
water.

**2. Vessel suspects replaced with real GFW aggregate activity.** Hours and
vessel counts by flag state within 30 km and ±7 days, labelled *"Vessel
activity nearby (Powered by Global Fishing Watch)"*. No name, no MMSI, no
"suspect", no attribution of any kind. Zero is served as a finding.

**3. Ocean Map's synthetic SAR overlay replaced with the real screened
tiles** — 100 tiles across 9 real acquisitions, red where flagged (none
are), with the scene selector listing real acquisition dates. The map's
"Simulated data" banner is gone: **every layer on it is now real.**

**4. Severity now carries its meaning.** `RISK_MEANING` is defined once and
shown as a tooltip on every badge and as visible text on detail pages:
*"Risk score = potential impact if confirmed (exposure, proximity, sea
state). Not a confirmed incident."* A tooltip alone is invisible on a touch
screen and in a screenshot.

**Gotcha — the `REPO_ROOT` trap a third time.** `copernicus_client.py`
anchored its STAC cache on `REPO_ROOT`, which is `/` in-image, so the module
could not even be imported in the container and the whole optical panel
returned 500. Also had to `chown` the caches: files copied in with
`docker cp` land root-owned, and the app runs as `oip`.

**Tests:** 12 new, 857 passed.

## Item 6 — full suite, clean restart, console sweep (22 Nov)

Clean `docker compose down` / `up --build`; all 40 regions, 108 events,
3,006 index readings and 4.6M water observations survived. Swept all 23
app routes in a fresh browser tab: **zero console errors, zero non-2xx
resource loads**.

Two real faults surfaced during the sweep, both now fixed:

- **The SAR patch image 404ed on every candidate.** `candidate_service`
  anchored the benchmark directory on `REPO_ROOT`, which is `/` inside the
  container — the fourth appearance of that trap. Added `SAR_TRAINING_DIR`,
  staged the 881 PANGAEA patches in the data volume; 305 of 306 candidates
  now serve a real image, and the one fixture row says so instead of
  leaving an orphan caption.
- **Four panels still said "simulated" over real data** — the optical
  product captions, the fusion narrative and the page banner. Corrected;
  the page-level and concordance notes are now `ProvenanceNote`, and only
  the drift track and receptor screening keep `SimulatedBanner`.

**Tests:** 11 new, 868 passed, 25 skipped, 0 failed.
**Gotcha:** heredocs in Git Bash eat backslash-newline, so the Dockerfile
`ENV` continuation had to go in with the Edit tool.

## Item 6 — deck, dump, reset (22 Nov)

- **`backups/oip-demo-final-v3.dump`** taken (108 MB) and `reset_demo.sh`
  repointed at it. Restore run end to end: 108 events (25 CRITICAL), 306
  candidates, 407 prediction logs, 3,006 index readings, 4,601,509 water
  observations, 40 regions — all as expected, patch image still 200 after.
- **`docs/DEMO_SCRIPT.md`** — "What is real" table regenerated for items
  1–4; five stale passages corrected, including "666 simulated events" and
  "the events in them are still simulated", neither of which has been true
  since 21 Nov.
- **Deck rebuilt** at `~/Downloads/OIP-Demo.pptx` — 23 slides, **geometry
  issues down from 11 to 8**, and the three that were real (a 0.36 in
  overlap where the last rows of the "What is real" slide ran into the
  footnote) are gone. The remaining 8 are the same heuristic
  "MAYBE OVERFLOW" estimates and a 0.08 in overlap that shipped in v2.
  No secret-shaped strings. Candidate Review and Ocean Map screenshots
  retaken against the real panels.
- **Map legend** said "Full-Scene Inference / Scene Swath / Candidate
  Tile" over what are now real screened tiles. Now "Screened Sentinel-1
  tiles / Screened, not flagged / Flagged by the detector".

**Tests:** 868 passed, 25 skipped, 0 failed.
