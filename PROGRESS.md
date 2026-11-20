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
