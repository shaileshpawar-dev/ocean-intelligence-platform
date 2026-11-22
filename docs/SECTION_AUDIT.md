# Section audit: Marine Monitoring, Intelligence, AI Research, Machine Learning

Audit date: 20 November 2026. Scope: everything outside India Water Intelligence.
Method: row counts on the live database, one call to every endpoint behind these
four sections, every page loaded in a browser with the console captured, and the
test suite run.

**Headline.** The code is in better shape than the data. Every page renders, no
page throws a console error, and the honesty labelling ("SIMULATED", "Not
evaluated", "Insufficient data") is applied consistently and correctly. What is
missing is almost entirely **data and wiring**, not architecture — which is good
news, because wiring is cheap and architecture is not.

One section is outright broken (Forecasts). One section is far weaker than the
work behind it deserves (Machine Learning), and the fix is mostly moving numbers
that already exist on disk into the database.

---

## Current state at a glance

| Section | Page | Renders | Has real data | Verdict |
|---|---|---|---|---|
| Marine | Ocean Overview | yes | no — all SIMULATED | Works, nothing real behind it |
| Marine | Live Monitoring | yes | no — all SIMULATED | Works; detector is `mock-detector` |
| Marine | Pollution Events | yes | no — 49/49 SIMULATED | Works |
| Marine | Candidate Review | yes | **yes — 306 real samples** | **Best page in the project** |
| Marine | Ocean Map | yes | mixed | Works |
| Intelligence | Forecasts | yes | **no history** | **Broken — always "insufficient"** |
| Intelligence | Risk Analysis | yes | 49 assessments | Works |
| Intelligence | Knowledge Graph | yes | no endpoint exists | Honest placeholder |
| AI Research | RAG Research | yes | 22 docs / 31 passages | Works, thin corpus |
| AI Research | Agent Analysis | yes | 4 runs, `llm_provider=none` | Works, no narrative |
| AI Research | Reports | yes | 4 reports, all one event | Works |
| ML | Model Performance | yes | **0 evaluated models** | **Understates the real work** |
| ML | Drift Monitoring | yes | baseline n=0, current n=0 | No data to measure |
| ML | Experiments | yes | no endpoint | Honest placeholder |
| ML | Retraining | yes | n/a by design | Fine as-is |

Test suite: **643 passed, 2 failed, 21 skipped.**

---

## 1. Machine Learning — the biggest gap, and the easiest win

This is where the project undersells itself most badly.

**What the UI says:** "EVALUATED MODELS: 0", "mAP@50: Not evaluated", "Precision:
Not evaluated", "INFERENCE P95: Unavailable", "Drift: Insufficient data".

**What is actually true:** three SAR models have complete, rigorous, on-disk
evaluations against a leakage-free test split, including confusion matrices,
baseline comparisons, threshold sweeps and measured latency:

| Model | Precision | Recall | F1 | FPR | Test set |
|---|---|---|---|---|---|
| `sar-oil-slick-v2` | 0.636 | 0.933 | 0.757 | — | 30 samples |
| `sar-oil-slick-v2.1-expanded` | 0.721 | 0.880 | 0.793 | 0.34 | 100, scene-stratified |
| `sar-oil-slick-v2.2` | 0.677 | 0.880 | 0.765 | 0.42 | 100, leakage-free |

Sources: `data/models/sar/{v2,v2_expanded,v2_2_scene_clean}/eval_metrics.json`.

These three models **are not in the model registry at all**. The registry holds
only `yolo-pollution-detector` and `sar-dark-formation`, both with every metric
`NULL`. So the page truthfully reports zero evaluated models while three
evaluated models sit in the repository.

It gets better: I called `get_sar_v2_2_detector().describe()` directly, and it
**already returns** `test_metrics` and `baseline_comparison` in full — precision
0.6769, recall 0.88, F1 0.7652, 22.1 ms average latency. The
`GET /api/v1/models/detectors` endpoint strips those fields before serialising.
The numbers are already in the process; the API drops them on the floor.

I also confirmed the model genuinely runs: `predict()` on a 224×224 patch
returned a real detection in **21 ms**.

Three other ML facts worth knowing:

- `prediction_logs` has **2 rows**, both from `mock-detector`, both with zero
  detections. That is why inference latency is "Unavailable".
- Drift needs 30 samples per window and has 0 in both, so all 76 drift reports
  say `insufficient_data`. Drift is not broken — it is correctly refusing to
  issue a verdict it cannot support. It just has nothing to chew on.
- A labelled dataset is present (`data/training/sar_oil_v2`: 881 JPGs, 338
  Pascal-VOC XMLs) but there is no YOLO `data.yaml`, so
  `ml/evaluation/evaluate_detector.py` cannot be pointed at it without a
  conversion step.

**Fixes, in order of value per hour of work:**

1. **Register the three evaluated SAR models with their real metrics.** Read the
   three `eval_metrics.json` files into `model_versions`. The Model Performance
   page goes from "0 evaluated" to three models with measured numbers *and* a
   baseline comparison showing v2.2 beating the rule-based baseline (F1 0.765 vs
   0.222). This is the single highest-value change in the whole audit.
2. **Stop stripping metrics in `/models/detectors`.** Pass through the
   `test_metrics` and `baseline_comparison` that `describe()` already returns.
3. **Generate real prediction logs.** Run the v2.2 detector over the 306 stored
   candidate patches and log each inference. This fixes inference latency and
   gives drift monitoring enough samples to issue an actual verdict — two dead
   panels revived by one script.
4. **Compute a live confusion matrix from the database.** `sar_candidates` holds
   306 rows with `raw_confidence` *and* ground-truth `subset` labels (`ow`/`oc`
   = oil, `nw`/`nc` = not oil). Precision, recall and a ROC curve can be computed
   from data already in Postgres, with no new dataset and no retraining.

---

## 2. Intelligence — Forecasts is the one genuine breakage

Every region in the dropdown returns "Insufficient history". This is not a
display problem; no forecast can ever be produced with the current data.

**Root cause, confirmed by query:** the Holt model requires 7 daily observations.
`zone_history` holds exactly **10 rows — one per region**, because all 49
pollution events fall inside a **3-day window** (13–15 Nov 2026). Daily
aggregation of events clustered into three days cannot produce seven daily
buckets for any region.

```
zone_history rows per region: 1   (needed: >= 7)
pollution_events distinct days: 3  (14 + 17 + 18 events)
```

**Fix:** spread the seeded events across at least 60 days, then rebuild
`zone_history`. This is a change to the demo seeder, not to the forecaster — the
forecaster is correct and is refusing to fabricate a curve, which is the right
behaviour. Once there is history, the existing `beats_naive` backtest will also
start producing a meaningful verdict.

A smaller note: `/forecast/{region_code}` accepts *cell* codes like
`gulf_of_mexico_ne__r3c4` but history is aggregated at the *parent* level
(`gulf_of_mexico_ne`), so a cell code silently returns "No stored history". The
UI happens to pass parent codes so it never hits this, but anyone calling the API
directly will. Worth either aggregating at both levels or rejecting cell codes
with a clear message.

**Risk Analysis** works correctly — 49 assessments from a deterministic six-factor
engine, no LLM involvement, renormalised when factors are missing.

**Knowledge Graph** has no backend at all: `backend/app/knowledge_graph/__init__.py`
is a single docstring line. The page says so honestly rather than drawing invented
nodes. Worth building, because it needs **no new data** — the edges already exist
as foreign keys (event → region → observation → risk assessment → regulation).
For a college project this is a strong, self-contained feature with a good visual
payoff.

---

## 3. Marine Monitoring — works, but it is entirely a simulation

Mechanically sound; every page loads and the pipeline controls respond. The issue
is that essentially none of it is real, and two structural choices undercut the
project's story.

- **All 49 pollution events and all 202 satellite observations are tagged
  `SIMULATED`.** The UI does say so, clearly and in several places — that is to
  the project's credit.
- **The live detector is `mock-detector`** (`detector_backend = "mock"`,
  `demo_mode = True`, `gee_enabled = False`). The three real SAR models are
  loadable and fast but are not in the live path.
- **The data is frozen.** Newest event is 16 Nov; "Live Monitoring" has shown the
  same records for five days.
- **Geographic incoherence.** Marine regions are the Gulf of Mexico, North Sea,
  Strait of Malacca and Yellow Sea, while the rest of the platform is India. For
  a college submission this reads as two unrelated projects stitched together.
  Either re-centre the marine regions on Indian waters (Arabian Sea, Bay of
  Bengal, Gulf of Kutch, Gulf of Mannar — two already exist) or state plainly on
  the Ocean Overview that the marine module is a global demonstration.
- **Vessels/AIS is six hand-written ships** with 28 positions.

**The exception, and it is a big one: Candidate Review.** 306 real Sentinel-1
patches from a peer-reviewed benchmark (PANGAEA 980773, CC BY 4.0), collocated
with real ERA5 wind, with an exhaustive and self-consistent triage funnel
(136 + 70 + 0 + 1 + 99 = 306) and correct caveats about uncalibrated scores. This
is the most defensible page in the entire application and deserves to be the
centrepiece of a demo, not the fifth item in a nav group.

---

## 4. AI Research — functional, honest, thin

- RAG retrieval works and cites sources: 22 documents, 31 passages, BM25 lexical
  retrieval with a feature-based reranker. Mean passage length 518 characters.
- `llm_provider = "none"`, so agent findings are templated and reports carry
  `narrative=none`. The reports are well structured by evidence level and are not
  fabricated — they are simply not written in prose.
- All 4 agent runs and all 4 reports target the **same event**, so the section
  looks emptier than it is.
- The corpus is "platform-authored scope summaries, not verbatim legal text",
  which the page states explicitly. Honest, but it limits what the retriever can
  do.

For a college project this is acceptable as-is. If you want the section to look
stronger cheaply: expand the corpus to 60–80 passages and generate reports for a
handful of different events.

---

## 5. Two failing tests

```
FAILED tests/test_wind_screener.py::TestMultiSensorIntegrator::test_multi_sensor_conflicting_algae
FAILED tests/test_wind_screener.py::TestMultiSensorIntegrator::test_multi_sensor_supporting_sunglint
TypeError: MultiSensorIntegrator.integrate() missing 2 required arguments: 'model_version' and 'sar_time'
```

These are **stale tests, not broken production code**. `integrate()` gained
`model_version` and `sar_time`; the real caller
(`candidate_service.py:796`) and `tests/test_multi_sensor_fusion.py` were both
updated, and these two in `test_wind_screener.py` were missed. A red suite on a
submitted project is an unnecessary own goal — fix first, it is a ten-minute job.

---

## Recommended order of work

Given "make it functionally work first, college project, not production":

**P0 — correctness and the worst contradictions**
1. Fix the two stale tests. (~10 min)
2. Register the three evaluated SAR models with their real metrics. (~1–2 h)
3. Give the forecaster real history so Forecasts stops saying "insufficient". (~1–2 h)

**P1 — make the ML section show the work that already exists**
4. Stop stripping `test_metrics` in `/models/detectors`. (~30 min)
5. Log real inferences over the 306 candidate patches — revives both inference
   latency and drift monitoring. (~2 h)
6. Compute a confusion matrix and ROC from `sar_candidates` ground truth. (~2–3 h)

**P2 — coherence and completeness**
7. Decide and state the marine story (India-centred, or explicitly a global demo).
8. Build the Knowledge Graph from existing foreign keys — no new data needed.
9. Broaden the RAG corpus; generate reports for several different events.

**P3 — explicitly not worth it for a college project**
Live satellite ingestion (GEE/Copernicus), real AIS feeds, an automated retraining
pipeline, MLflow integration. These are production concerns, they cost money or
credentials, and none of them makes the project demonstrate better.

---

## What is already good and should not be touched

- The evidence ladder (OBSERVED / DETECTED / INFERRED / FORECAST / RETRIEVED) is
  applied consistently across every page.
- Null metrics are shown as "Not evaluated" rather than filled with plausible
  numbers. Drift reports "insufficient data" rather than "no drift". These are
  the right calls and are rarer than they should be.
- `NotAvailableInBackend` placeholders (Experiments, Knowledge Graph) state what
  is missing and why instead of rendering invented content.
- Candidate Review's triage funnel is exhaustive and arithmetically self-checking.
- Zero console errors across fifteen pages.
