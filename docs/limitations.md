# Limitations

An honest account of what this system cannot do. Written for a reader deciding
how much weight to put on its output — and because a project that lists its
limits is more credible than one that does not.

## 1. Detection

### Confidence is not calibrated

Every confidence the platform produces is an **uncalibrated score**, and every
response says so via `confidence_is_calibrated: false`.

The SAR detector's score is a normalised combination of backscatter depth and
contrast. It orders detections sensibly — a darker, more structured patch
scores higher — but 0.74 does **not** mean "74% likely to be oil". No labelled
validation set has been run against it.

The YOLO checkpoint's score is a real model output, but it has not been
calibrated against a held-out set either, so the same caveat applies.

Fixing this requires a labelled dataset (see [ai-pipeline.md](ai-pipeline.md#7-what-would-improve-this)),
then reliability-diagram analysis and Platt scaling or isotonic regression.

### Look-alikes are not resolved, only flagged

The detector separates *uniformly dark* cells (likely low wind) from
*structured dark* cells (possible film). That is a genuine discrimination, but
it does not resolve the look-alike problem — it narrows it. Biogenic slicks in
particular produce structured dark formations essentially identical to oil in
C-band VV.

Without wind data the platform **cannot** distinguish a slick from a calm
patch with any reliability, and it says so on every detection.

### Area estimates are order-of-magnitude

Extent is interpolated between the p10 and p90 percentile anchors of a
regional reducer. It is not measured from a segmentation mask. Treat
`estimated_area_km2` as an order-of-magnitude figure; `area_method` records
how it was derived.

### Screening resolution cannot delineate

Stage 1 localises *which cell* deserves attention. It does not delineate a
feature. Even after stage-2 refinement, sub-cells are thousands of km² — far
above slick scale. Delineation requires full-resolution scene analysis, which
the platform does not currently perform.

### No sub-surface or dissolved pollution

C-band SAR sees the surface only. Dissolved chemicals, suspended
microplastics, and anything below the immediate surface are invisible to it.

This is why `chemical_pollution` exists as a *trained label* but not as a
*signature*. The YOLO checkpoint was trained to emit it, and the label is
preserved verbatim on `Detection.class_name` — nothing is discarded. But
neither SAR backscatter nor optical reflectance can identify a chemical
species: what an optical sensor records is surface discolouration, which has
many causes. The detection is therefore reported with
`signature: surface_anomaly` plus an explicit caveat naming the downgrade.

The same reasoning applies to `plastic_debris_signature`, which is retained
only for optical detectors and carries high uncertainty even there.

## 2. Geographic context

Both proximity measures are **coarse approximations** and each carries a
`precision_note` in the API:

- **Coastline distance** is the distance to the nearest of ~62 major coastal
  reference points (ports and headlands), not to the true coastline. It
  over-states distance wherever reference coverage is sparse; typical error is
  tens to low hundreds of km. Production replacement: GSHHG or OSM coastline
  polygons with a spatial index.
- **Protected-area distance** is the distance to the approximate *centroid* of
  one of 20 curated marine protected areas. Centroid distance under-states
  proximity badly for large reserves (Papahānaumokuākea spans ~1.5 million
  km²). This is **not** a WDPA mirror: absence from the list does not mean
  absence of protection. Production replacement: the full WDPA marine subset.

Both feed the risk score, so risk carries this imprecision.

## 3. Risk scoring

### The weights are a judgement, not a constant

`FACTOR_WEIGHTS` encodes a product decision about what matters and how much.
It is not derived from environmental-impact literature, and it has not been
validated against expert assessments of real incidents. It is versioned
(`risk-engine-1.0.0`) so any stored assessment traces to the weighting that
produced it, and it is transparent so a domain expert can disagree
specifically.

### Renormalisation is a deliberate trade

When a factor cannot be evaluated the score renormalises over the remainder.
This avoids the dangerous failure — an unmeasured event reading as safe — but
it means a score computed from two factors is less reliable than one computed
from six, while both are reported on the same 0–100 scale. `missing_factors`
tells a consumer which they are looking at.

### Severity thresholds are conventions

LOW/MEDIUM/HIGH/CRITICAL cut at 25/50/75. Round numbers, not empirical
boundaries.

## 4. Forecasting

### It forecasts activity, not pollution

The platform forecasts **its own detection activity** for a region. This is a
real time-series problem over data it owns, but it is not a forecast of
pollution. If satellite coverage changes, or a threshold is tuned, the
forecast moves without anything changing in the water.

### It does not forecast dispersion

Predicting where a slick will drift requires surface currents, wind fields,
wave spectra, oil type and weathering state, integrated in a Lagrangian
transport model (GNOME, OpenDrift, MEDSLIK). **None** of those inputs exist
here. `forecast_kind` is `detection_activity` on every response so this can
never be misread.

The predecessor's `/predict-spread` returned hardcoded constants labelled
`"LSTM-mock"` with `spread_km2` values. That endpoint is gone.

### Short history, weak models

Holt's linear smoothing is appropriate for short, noisy, non-seasonal series —
which is what exists. It frequently **does not beat** the naive baseline, and
`beats_naive` reports that honestly. LSTM/PatchTST are deferred until enough
real history accumulates to justify them; fitting a deep model to 30 points
would produce a confident-looking curve with no information in it.

### Prediction intervals are approximate

Intervals assume normally distributed, homoscedastic one-step residuals and
widen as √h. Neither assumption strictly holds. Exact intervals need the
state-space form of the model.

### Forward-filling hides gaps

Building a regular daily grid forward-fills days with no coverage. A flat
stretch may be a satellite revisit gap rather than stable conditions. The
`coverage_ratio` on `/trends` exposes this; the forecast notes it as a caveat.

## 5. Data and infrastructure

### Demo mode is synthetic

With `DEMO_MODE=true` all observations come from `DemoSatelliteProvider`. They
are statistically plausible and deterministic, but **entirely invented**.
Every such record is tagged `SIMULATED` and propagates that tag through
detector, risk engine and API envelope.

Do not use demo-mode output to characterise any real region.

### Model metrics are null until measured

Registry entries report `null` for mAP, precision and recall until an
evaluation run records them. This is intentional: a null is honest, a
plausible-looking 0.87 is not. The original README advertised metrics that no
evaluation had produced.

### Drift detection needs volume

PSI checks require ≥30 samples per window and report `insufficient_data`
otherwise. On a low-traffic deployment they will report that most of the time.

### Ingestion is synchronous

Fine for ~38 cells. A larger grid or finer refinement needs a task queue;
stage-2 refinement in particular can issue up to 64 Earth Engine calls per
cell and will exceed request timeouts if pushed.

### Not validated at scale

Tested against SQLite and the demo provider. The Postgres path is configured
and the driver is a dependency, but has not been exercised under load. There
is no migration tooling — `init_db()` creates tables and nothing handles
schema evolution. Add Alembic before any deployment that must preserve data.

### Docker build unverified

The Dockerfile and compose stack are written but **have not been built or run**
in this environment — the Docker daemon was unavailable. Treat them as
untested. CI includes a `docker-build` job that will exercise them on first
push.

## 5b. Model licence

The YOLOv8 checkpoint carries **AGPL-3.0** via Ultralytics, recorded in the
file's own metadata. Serving it over a network obliges release of the serving
application's source under AGPL, unless a commercial licence is held from
Ultralytics.

This does not affect local use, evaluation or a public GitHub portfolio repo.
It does matter if the platform is ever deployed as a hosted service. The
detector abstraction makes the alternative cheap: a permissively-licensed
detector implements `BaseDetector` and registers in `app.vision.registry`
without touching any caller.

## 6. Security incident

The predecessor notebook contained a **live ngrok authentication token in
plaintext** and was shared as a file. It also uploaded a **Google Cloud
service-account JSON key** into a Colab session, where it persisted in session
storage and notebook state.

Required remediation, both of which must be done regardless of this rewrite:

1. **Revoke the ngrok token** at
   <https://dashboard.ngrok.com/get-started/your-authtoken> and regenerate.
   A leaked token lets a third party open tunnels on the account.
2. **Delete the GCP service-account key** in Google Cloud Console → IAM →
   Service Accounts → Keys, and issue a replacement that never enters a
   notebook. The service-account email and project ID are not themselves
   secret; the key is.

Preventive measures now in the repository:

- All configuration flows through `Settings`; no credential may be hardcoded.
- `.gitignore` covers `.env`, `*-key.json`, `*service-account*.json`, `*.pem`.
- The structured logger redacts credential-shaped keys from every record.
- CI runs gitleaks over full history, plus an explicit pattern check for the
  exact shapes that leaked (ngrok tokens, PEM private keys, `AIza`/`sk-` keys).
- `.env.example` documents `NGROK_AUTH_TOKEN` under a "not used, do not
  re-add" heading.

## 7. Scientific-claim boundary

Summarising what may and may not be said from this system's output:

| The platform may say | It may **not** say |
|---|---|
| "Mean VV backscatter was −24.8 dB" | "The water is polluted" |
| "A dark formation was detected, score 0.49" | "An oil spill was detected" |
| "Structure is consistent with a surface film" | "This is oil" |
| "Risk 68/100 given these six factors" | "This will cause 68 units of harm" |
| "Detection activity is trending upward" | "Pollution is increasing" |
| "Forecast risk 70 [64–75] at +7d" | "The slick will reach the coast" |

The distinction between the columns is enforced in code — by the signature
vocabulary, the `EvidenceLevel` propagation, the plausibility gate and the
`forecast_kind` field — and asserted by the scientific-integrity CI job. It is
the point of the project.

## 8. India water intelligence

**Data age, and the one exception.** CPCB's published extracts mostly end in
2020–2021 and the Central Water Commission's run to April–June 2025. Since
Phase 4 there is also **CPCB's real-time network**: automatic analysers
reporting hourly, which the platform reads and which can describe a water body
*now*.

That exception is small and must not be read as more than it is:

| | Covered |
|---|---|
| Stations | **40 of 4,951** |
| Water bodies | **26 of 2,740** |
| States | **6 of 35** (UK, UP, HR, BR, JH, WB) |
| Rivers | the Ganga and its tributaries, not the whole country |
| Parameters | 9 of the 12 series published; depth and stage are hydrology, and total organic carbon has no entry in the registry |

For every other water body the platform still says "current condition cannot
be established from this dataset", names the newest source and gives its date.
**There is no nationwide real-time water-quality coverage in India that this
platform can reach**, and it does not pretend otherwise.

**Sensors are not laboratories.** The real-time values come from field
analysers: they drift, they are cleaned on a schedule, and they go offline.
The feed publishes each station's maintenance diary. A station that stops
reporting keeps its last value in the feed, so **the feed being live does not
mean every station in it is** — on the day it was integrated, 39 of 40 had
reported within the hour and one had not reported for 24 days. Freshness is
judged per observation from its own timestamp, never assumed from the source
being live.

**Two sources, not one truth.** CPCB and CWC sample different stations by
different programmes. Their observations are stored separately, shown as
separate series, and never averaged. Where both measure a parameter the
status uses the most recent value and says which agency produced it. The
platform does not rank agencies: `source_type`, `observation_method` and a
reliability note are recorded as facts.

**Coverage.** CPCB: 35 state/UT codes. CWC: 29. See
[DATASET_COVERAGE.md](DATASET_COVERAGE.md) for the counts, which are computed
from the database.

**Identity is parsed for CPCB and read from drainage columns for CWC.**
CPCB's `River` column is empty, so its water bodies come from station names.
CWC fills `River`, `Basin` and `Tributary`, but the `River` column repeats the
`Basin` name in most rows, where it is a basin label rather than the water
body: read literally it put all 36 Sikkim stations on the Brahmaputra
mainstem, up to 264 km from the Teesta they sample. The rule that replaced it
is in [water-geospatial.md](water-geospatial.md#2-canonical-identity).

**A sub-basin is not always the stream sampled.** Where the source gives only
a basin and a sub-basin, the sub-basin is used and recorded at confidence
0.55. It can still be too coarse: a station at Ujjain is in the Yamuna
sub-basin but stands on the Shipra, which the source never names, so it is
attached to the Yamuna. `cli geometry-qa` reports every station further than
25 km from its water body's geometry — that report is the measure of this
limitation, not a list of bugs, and it is not silently repaired. Untyped
same-named bodies are not linked across states, so generic names can still
appear more than once.

**Geometry** comes from an OpenStreetMap regional extract, matched offline by
name, water-type affinity and station proximity, with connectivity for rivers.
Coverage is partial: many small ponds and unclassified bodies have no named
OSM feature near their stations, and some matches are refused as ambiguous
rather than guessed. Shapes are OSM's, not a survey; boundaries are
geoBoundaries (2011 states, 2021 districts), not the official boundaries of
India.

**Standards.** Rivers are compared against the EP Rules 1986 bathing-water
criteria, which is what CPCB uses to identify polluted stretches; everything
else says "reference comparison unavailable" unless a designated use is
recorded or chosen. IS 10500 (drinking/groundwater) is not loaded. No
official polluted-stretch classification is loaded: CPCB publishes it as PDF
and the import path is there, waiting for a machine-readable table.

**Units.** Conversions are applied only where they are exact. Both agencies
label conductivity mS/cm while publishing µS/cm magnitudes; the platform
resolves that by magnitude and flags the observation `unit_assumed_us_cm`
rather than multiplying every reading by a thousand. A unit it cannot convert
is stored unconverted and flagged `unit_not_convertible`, never compared.

**Satellite.** One path: Sentinel-2 L2A for lakes with a matched polygon,
with strict per-lake cloud and water checks. The stored value is an
uncalibrated index (NDTI) with no unit — not turbidity, never compared with a
standard or with CPCB's NTU. Scene pictures are rendered on demand by the
imagery service; if that service is unreachable the stored evidence (scene,
date, cover fractions, index) still displays.

**Database.** PostgreSQL 16 + PostGIS 3.4 is the production target and is
what the spatial queries run on; SQLite remains for development and tests,
where the Python geometry helpers are used instead. The two paths are
exercised by the same test suite, but only PostGIS is exercised against the
full national dataset.

**Deployment.** Nothing is deployed. The staging stack runs locally under
`docker compose`; AWS outbound access to the portals, OSM mirrors and the
imagery service has not been verified from inside a VPC.

**Not implemented:** status-history population, user-reported issues,
pollution-source attribution, basin boundaries, vector tiles, scheduled
ingestion (the jobs exist and are idempotent; nothing schedules them yet).

**Q&A.** Rule-based routing and entity resolution; no language model is used
on the water path. Unusual phrasings fail towards "no evidence".
