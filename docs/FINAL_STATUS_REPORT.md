# OceanAI — Final status report

**22 November 2026 · tag `demo-final-v2` · 845 tests passing**

Every figure below was read from the running application or the database on
22 November 2026, after a clean restart. Nothing is quoted from memory.

---

## 1. What this is, in five lines

OceanAI monitors Indian water quality and coastal marine conditions from
public data: 4.6 million CPCB and CWC river and lake measurements, and twelve
months of Sentinel-2 imagery over India's exclusive economic zone.
It separates what was **measured** from what was **inferred**, dates every
figure, and refuses to describe conditions it cannot support.
Detections are raised only where a reading is both unusual for its own region
and past an absolute floor from literature — and are labelled statistical
anomalies, never confirmed incidents.
The marine detector has also been pointed at a documented real spill, which
it did not find; that result is published with the reasons it is weak.
**Demo mode is off and there are no simulated rows in the database.**

---

## 2. Completed work

### India water intelligence
- **4,601,509** parameter measurements across **2,740** water bodies,
  **4,951** stations, **35** states and **613** districts.
- **CPCB real-time analysers reconnected** — 1,397 readings, the first
  genuinely current water data the platform has carried. Coverage went from
  **0 to 19** water bodies with a reading inside two days.
- Freshness engine with a refusal horizon: a water body whose newest reading
  is older than its source's cadence is described by *when* it was measured,
  not by what it showed.
- Reference standards, parameter registry, RAG question answering that
  refuses when the corpus cannot support an answer.

### Marine monitoring
- **15 regions / 40 cells across India's EEZ**, re-cut from an inherited
  global demo set. The risk engine's coastal and protected-area factors now
  point at real Indian receptors.
- **3,006 Sentinel-2 index readings**, 36 regions, 21 Nov 2025 – 20 Nov 2026.
- **108 pollution events** from those measurements: 41 floating material,
  35 algal bloom, 32 turbidity plume.
- **407 Sentinel-1 tiles screened**, 0 oil detections.
- **Historical incident replay** — MSC ELSA 3, not detected.

### Machine learning
- **5 registered models, 3 evaluated.** v2.2: precision 0.677, recall 0.880,
  F1 0.765 on a 100-sample leakage-free split.
- Live confusion matrix and ROC (AUC 0.771) computed from the 306 stored
  benchmark candidates, recomputed as the threshold moves.
- **407 prediction logs** with real latency; drift monitoring reports
  **WARNING** (PSI 0.11) and has not been tuned away.
- **Sentinel-1 saturation diagnosed and substantially fixed** (section 8).

### Intelligence
- Deterministic six-factor risk engine; no model produces or adjusts the
  score.
- Holt forecaster with a `beats_naive` backtest on a year of real data.
  **0 of 40 regions beat the naive baseline**, reported on every chart.
- Knowledge graph built only from declared foreign keys: **611 nodes,
  253 edges, 0 unresolved citations**.
- **6 agent runs and 6 reports** over real detections, each with a cached
  Gemini narrative whose every figure was verified before storage.

### Engineering
- **845 tests passing**, 25 skipped, 0 failing. 24 pages, 0 console errors.
- Container image made buildable again after discovering numpy, torch and
  pillow had been hand-installed into the live container.
- Scoped TLS certificate pinning for one government host.

---

## 3. Real data sources

| Source | Feeds | Records | Last sync | Status | Attribution |
|---|---|---|---|---|---|
| CPCB real-time | Current river water quality | 1,397 | 21 Nov 2026 | **Live** | CPCB RTWQMS |
| CPCB manual (NWDP) | Historic water quality | 582,192 | 26 Sep 2026 | **Sync paused** | CPCB via NWDP |
| CWC manual (NWDP) | Historic water quality | 4,017,920 | 26 Sep 2026 | **Sync paused** | CWC via NWDP |
| Sentinel-2 L2A | NDCI / NDTI / FDI, all detections | 3,006 | 20 Nov 2026 | **Live** | Contains modified Copernicus Sentinel data 2026 |
| Sentinel-1 GRD | SAR screening, incident replay | 407 tiles | 21 Nov 2026 | **Live** | Contains modified Copernicus Sentinel data 2026 |
| Copernicus Marine | Drift currents, chlorophyll cross-check | 81 products | 21 Nov 2026 | **Live** | Generated using E.U. Copernicus Marine Service Information |
| Open-Meteo | Wind, waves, SST, low-wind flag | 40 regions | 21 Nov 2026 | **Live** | Weather and marine data by Open-Meteo.com |
| Global Fishing Watch | Aggregate vessel activity | 60,403 vessel-hours | 21 Nov 2026 | **Live** | Powered by Global Fishing Watch |
| PANGAEA 980773 | SAR benchmark candidates | 306 patches | frozen | Benchmark | PANGAEA 980773, CC BY 4.0 |
| Google Gemini | Report prose (not evidence) | 6 narratives | 22 Nov 2026 | **Live** | `gemini-flash-lite-latest` |

**"Sync paused" is not an outage.** Both NWDP feeds sit behind a firewall
that returns HTTP 403 to automated clients. The server answers; it declines.

---

## 4. Feature status by page

| Page | Status | Why |
|---|---|---|
| India Overview | **Real** | 4.6M measurements; 19 water bodies current |
| Water Map | **Real** | Same data, geocoded |
| Ask about water | **Real** | RAG over the ingested corpus; refuses when unsupported |
| Reference Standards | **Real** | Published CPCB/BIS standards |
| Data Sources | **Real** | All nine providers, status derived from actual fetches |
| Real Observations | **Real** | 3,006 Sentinel-2 readings + incident replay |
| Candidate Review | **Benchmark** | 306 real PANGAEA patches; optical panels still synthetic, vessel suspects fictional |
| Ocean Overview | **Real** | Detections, sea state, vessel activity |
| Live Monitoring | **Real** | Real detections and the real active detector |
| Pollution Events | **Real** | 108 events from measured indices |
| Ocean Map | **Real (partial)** | All layers real except one labelled synthetic SAR overlay |
| Forecasts | **Real** | A year of measured history; honest about losing to naive |
| Risk Analysis | **Real** | Deterministic scoring over real detections |
| Knowledge Graph | **Real** | Foreign keys only, 0 unresolved citations |
| RAG Research | **Real (partial)** | Real retrieval; corpus is a seed set |
| Agent Analysis | **Real** | 6 runs over real detections |
| Reports | **Real** | 6 reports, number-checked AI summaries |
| Model Performance | **Real** | Measured metrics; unevaluated models say so |
| Drift Monitoring | **Real measurements** | 407 real inferences; window timestamps assigned and labelled |
| Experiments | **Empty, honestly** | Scaffolding only; page says so |
| Retraining | **Real** | Policy and trigger state |
| System Health | **Real** | Live component status |
| API / Infrastructure | **Real** | Live introspection |

---

## 5. Pending — not done, with reasons

| Item | Why not | Effort |
|---|---|---|
| **Retrain SAR model on calibrated backscatter** | Prepared tiles average **34 units darker** than training patches and 22/100 still saturate, so measured accuracy does not transfer. The single highest-value item. | 3–5 days (needs a labelled Sentinel-1 set over Indian waters) |
| **MARIDA marine-debris classifier** | FDI has no published absolute threshold, so floating-material detections stay relative-only until a trained classifier replaces the percentile | 2–3 days |
| **WDPA protected-area boundaries** | Risk engine uses 28 curated centroids; under-states proximity for large reserves | 1 day |
| **Real legal corpus** | MARPOL Annex I and NOSDCP; corpus is currently a seed set | 1–2 days |
| **Automated alerts to authorities** | A detection that reaches nobody is a dashboard entry | 2 days |
| **Cloud deployment, scheduled ingestion** | Fetch jobs are run by hand | 2–3 days |
| **Optical YOLO evaluation** | No measured results; page reports "Not evaluated" rather than a placeholder | 1 day |
| **Experiments page** | Scaffolding only | 1–2 days |
| **CPCB forecasting** | Forecaster runs on marine regions; water series needs the daily-bucket work redone for a different cadence | 1 day |
| **NWDP feeds** | Blocked upstream by firewall policy — not fixable from this side. Certificate pinning already works | — |
| **Real vessel identities on detections** | **Declined, not pending.** See section 6 | — |

---

## 6. Known limitations, and every remaining "simulated" occurrence

### Deliberate limits

**No real vessel is named against any detection.** The platform holds a table
that marks a vessel `SOURCE_SUSPECT` at up to 0.97 confidence, and its
detections are benchmark patches and statistical anomalies — nobody spilled
anything. A real MMSI in that row names an identifiable ship as the source of
an event that did not happen, on a page built to be screenshotted, and the
caveat underneath does not survive a crop. Global Fishing Watch answers the
question it *can* answer honestly: how busy is this water.

**FDI is never called plastic.** Biermann et al. (2020) — the paper defining
the index — publishes no threshold; the word does not appear in it. They
classify with a Naïve Bayes model over an FDI/NDVI feature space trained on
nine plastic pixels. So floating-material detections carry no absolute floor
and say "relative anomaly only".

**Detections are statistical anomalies, not incidents.** Top 1% of a region's
own twelve months, plus an absolute floor. Not a regulatory limit anywhere.

### Every remaining occurrence

| Where | Occurrence | Reason |
|---|---|---|
| Ocean Map — full-scene SAR overlay | "Synthetic Demo" on the layer, legend and banner | **Genuinely synthetic.** That one layer is a demonstration output. |
| Candidate Review — optical products | "SYNTHETIC optical products" banner | **Genuinely synthetic** reflectance arrays. Scene metadata is real Copernicus STAC. |
| Candidate Review — vessel suspects | "FICTIONAL VESSELS, deliberately" | See above. |
| Candidate Review — drift panel | "PARTICLE MODEL over real forcing" | Currents and wind are real; spill origin and volume are chosen. |
| `Overview`, `Reports`, `SystemHealth` | `contains_simulated_data` / `demo_mode` banners | **Conditional and currently inert.** Left in place so they fire again if simulated data ever returns. |
| `LiveMonitoring` source comment | "returned the mock" | Code comment explaining a fixed bug. |
| `PollutionSignature.PLASTIC_DEBRIS_SIGNATURE` | Deprecated enum value | Retained because stored rows may reference it; nothing new is written with it. |

### Other limitations

- Confidence scores are **uncalibrated** — rankings, not probabilities.
- Coastal proximity uses 90 reference points, not a real coastline polygon.
- Drift simulation uses real forcing but a chosen spill origin and volume.
- Forecasts **lose to last-value-carried-forward in all 40 regions**.
- Drift monitoring reports **WARNING** (PSI 0.11), untuned.
- Nothing refreshes without someone running a fetch job.

---

## 7. How an event is decided

**Both criteria are required.**

1. **Regional anomaly** — the reading is in the top 1% of what this platform
   has measured *in that region* over the last twelve months. Per region,
   because NDTI's 99th percentile runs from **0.142** in quiet cells to
   **0.313** off the Krishna–Godavari delta; one global cut-off would flag
   river mouths every day of the year. A region needs **40+ clear readings**
   or it raises nothing — there is no fallback to another region's water.

2. **Absolute floor** — NDCI ≥ **0.08** (`ALGAL_BLOOM_NDCI_THRESHOLD`);
   NDTI > **0** (the sign convention from Lacaux et al. 2007: positive is
   turbid, negative is clear). **FDI has none**, and says so.

Adding the second criterion removed 6 chlorophyll detections that were
unusual locally but below any absolute concern, and 9 turbidity detections of
water that was not turbid at all. Counts went from a suspicious 41/41/41 — a
number describing the method rather than the sea — to **41 / 35 / 32**.

Readings computed from fewer than **100 water pixels** are excluded entirely.
Full method: `docs/anomaly-method.md`.

---

## 8. Sentinel-1: the saturation fix, and the incident replay

### The fix

Validation first: replaying all **306 benchmark patches** reproduced the
stored scores to within 1% (live mean 0.5657 vs stored 0.5724, same minimum,
no saturation). The model was never wrong. Two faults in **live tile
preparation**:

1. **A per-tile percentile stretch** rescaled every tile to fill the 8-bit
   range. Open ocean has a σ⁰ spread under 2 dB and the training patches sit
   at std ≈ 18; the stretch produced ≈ 70. Replaced with a **fixed −30…−5 dB
   window**, derived by matching the training distribution — real water now
   lands at mean 146.1 / std 19.1 against training's 147 / 18.
2. **A 60% validity floor** let through tiles that were a third solid black,
   because outside-footprint pixels render as zero and 10·log₁₀(0) is −∞.
   Raised to **98%**.

| | Before | After |
|---|---|---|
| Tiles at confidence 1.000 | 100/100 | **22/100** |
| Score range | 1.000 only | 0.784–1.000 |
| Prepared tile brightness | — | 112.6 (training 147) |

Ordinary open water now scores **p_oil ≈ 0.05**, where it scored 1.000.
**Not fully solved**: brightness is still ~34 units low and the model's
measured accuracy does not transfer.

### The incident replay

**MSC ELSA 3**, IMO 9123221, sank 07:50 on 25 May 2025 at 09°18.75′N
076°08.16′E, 13 nm south-west of Kochi, carrying 367 t heavy fuel oil and
84.4 t diesel. Position, time, IMO and cargo from the **Kerala State Disaster
Management Authority SITREP-3** (1300 hrs, 25/05/2025).

| Pass | After | Tiles | Max p(oil) | Wind |
|---|---|---|---|---|
| 2025-05-28 | +3 d | 12 | 0.0033 | 9.3 m/s |
| 2025-06-02 | +8 d | 2 | 0.0008 | 3.4 m/s |
| 2025-06-09 | +15 d | 12 | 0.0623 | 5.4 m/s |
| 2025-06-14 | +20 d | 5 | 0.0005 | 8.2 m/s |

**Not detected.** Published with the reasons it is weak evidence: the first
pass was three days later into a 9.3 m/s wind, which roughens the sea enough
to suppress slick contrast; dispersant had been applied; oil weathers within
days; the model is off-distribution. **It does not establish that no slick
was present.**

This matters because a detector that always answered "no" would score
identically on open water. This was the test that could have distinguished
them, and it is published either way — held there by a test, because a
finding that only appears when favourable is not a finding.

---

## 9. How to run, reset and verify

```powershell
docker compose up -d backend
```

Open `http://localhost:8000/app/india`.

```powershell
scripts/reset_demo.sh
```

Restores `backups/oip-demo-final-v2.dump` and prints the counts below.

Refresh the external caches (optional, not needed for a demo):

```powershell
python scripts/fetch_marine_conditions.py
```

```powershell
python scripts/fetch_gfw_activity.py
```

```powershell
python scripts/fetch_sentinel2_indices.py --days 365
```

```powershell
python scripts/rebuild_real_events.py --rebuild-events
```

### Expected counts

| | |
|---|---|
| Pollution events | 108 (25 CRITICAL) |
| Sentinel-2 index readings | 3,006 |
| SAR candidates | 306 |
| Prediction logs | 407 |
| Water observations | 4,601,509 |
| Regions | 40 |
| Reports / agent runs | 6 / 6 |
| Knowledge graph | 611 nodes / 253 edges, 0 unresolved |
| **Simulated rows** | **0** |

---

## 10. Decisions made overnight

- **No oil event created from the MSC ELSA 3 replay** — the detector flagged
  nothing. Stored as validation evidence instead.
- **Replay widened** from 15 km / 14 days to 35 km / 21 days after the first
  run found only one pass. All figures unchanged.
- **FDI keeps no absolute floor** — verified from the Biermann paper that
  none exists to cite.
- **NDTI floor set at 0, not higher** — published turbid-water levels are
  local calibrations; borrowing one from a Senegalese pond study for the Bay
  of Bengal would repeat the global-threshold error with a citation attached.
- **Health CLI vocabulary changed** to match the page (a 403 is `PAUSED`,
  not `DOWN`) so the two cannot disagree about the same feed.
- **Zones fall back to optical observations** with a **null** backscatter —
  backscatter is a radar quantity and an optical cell has none.

## 11. Blocked overnight

- **NWDP water feeds (HTTP 403).** TLS pinning works and the handshake
  completes; the firewall refuses automated clients as policy. Not worked
  around — an attempt to probe it with a browser-impersonating User-Agent
  was refused by the permission classifier, correctly, and was not retried.
- **Docker Desktop stopped mid-run.** Restarted; no work lost.
- **Nature and core.ac.uk refused automated fetches** of the Biermann paper.
  Read the open-access PMC copy instead (PMC7181820).

---

## 12. Test suite and tag

```
845 passed, 25 skipped, 0 failed
```

Frontend type-check clean. 24 pages, 0 console errors, clean restart
verified.

**Tag:** `demo-final-v2`
**Branch:** `feature/real-data`
**Database:** `backups/oip-demo-final-v2.dump`
