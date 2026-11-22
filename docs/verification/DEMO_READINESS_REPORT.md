# OceanAI Demo Readiness Report

**Report date:** 2026-11-16  
**Planned presentation:** 2026-11-17  
**Repository:** `C:\Users\Shailesh\New folder (2)\ocean-intelligence-platform`  
**Branch / HEAD:** `feature/india-water-intelligence` / `91eb7fa`  
**Prepared for:** local faculty presentation  
**Assessment:** **READY FOR A CONTROLLED LOCAL DEMONSTRATION, WITH EXPLICIT SYNTHETIC LABELS AND DOCUMENTED LIMITATIONS**

> This report covers demonstration readiness only. It is not a scientific validation report and does not certify any model, dataset, or marine-pollution output for operational, regulatory, or response use.

---

## 1. Readiness verdict

### 1.1 Demo-blocking status

No demo-blocking runtime issue remains.

- The database container is running and healthy.
- The FastAPI backend is running with exactly one process tree.
- The React console is built, current, and served by FastAPI at `/app`.
- All 17 readiness checks pass.
- All 14 application pages load with zero HTTP errors, zero JavaScript errors, and zero broken images.
- Candidate images, optical products, AI citations, India map tiles, and Ocean Map footprints were exercised successfully.
- The database and file-state comparison found no deletions and no data loss.
- The full backend suite is **643 passed, 2 failed, 21 skipped**. Both failures are pre-existing and unrelated to this readiness pass; they were left unchanged and are documented in Section 9.
- The earlier 300-second startup timeout is explained and reproduced as a harness process-wait artifact, not a startup-script hang. The startup script itself exits normally, including a cold start in **12.5 seconds**. See Section 5.

### 1.2 What this demo can honestly show

1. A working, coherent environmental-intelligence application with 14 loadable modules.
2. A real India water-quality archive: **4,601,153 observations**, **2,740 water bodies**, and **4,951 monitoring stations**.
3. Real deterministic retrieval over a real 22-document / 31-passage marine-pollution corpus.
4. A research-replay SAR candidate review workflow with real historical patches and metadata, explicit uncalibrated scores, and append-only review history.
5. Clear provenance and synthetic-data labels on optical, AIS, full-scene SAR, fusion, drift, and impact panels.
6. Honest empty, insufficient-data, and not-evaluated states where the platform has no data.

### 1.3 What must not be claimed

Do **not** describe any of the following as validated, measured, operational, or confirmed:

- SAR oil-slick scores or the 76.2% value as a probability.
- Full-scene SAR detections as real satellite detections.
- Optical RGB/SWIR/SCL/NDCI products as measured reflectance or chlorophyll.
- Multi-sensor fusion as a calibrated probability or Bayesian result.
- AIS vessel identification as identity confirmation.
- Drift trajectories or beaching risk as validated predictions.
- Environmental impact as a validated vulnerability assessment.
- India water status as present-day water quality.
- Model performance as evaluated; the registry has zero evaluated models.
- Any output as suitable for regulatory or spill-response decisions.

The recommended framing is: **“This is a working demonstration of the software, provenance, and review workflow. The India water layer is real; the marine layers are explicitly labeled research replays or synthetic demonstrations. Scientific validation is future work.”**

---

## 2. Verified URLs

All URLs were served locally by FastAPI on `127.0.0.1:8000`. The browser audit loaded all 14 application pages successfully.

| # | Module | URL |
|---|---|---|
| 1 | Landing | `http://127.0.0.1:8000/app` |
| 2 | Command Center / Dashboard | `http://127.0.0.1:8000/app/overview` |
| 3 | India Water Overview | `http://127.0.0.1:8000/app/india` |
| 4 | India Water Map | `http://127.0.0.1:8000/app/map` |
| 5 | Ocean Map | `http://127.0.0.1:8000/app/ocean-map` |
| 6 | Candidate Review | `http://127.0.0.1:8000/app/candidate-review` |
| 7 | Candidate Detail (`cand_s1_0036`) | `http://127.0.0.1:8000/app/candidate-review/cand_s1_0036` |
| 8 | AI Assistant | `http://127.0.0.1:8000/app/ai` |
| 9 | System Health | `http://127.0.0.1:8000/app/health` |
| 10 | Model Performance | `http://127.0.0.1:8000/app/models` |
| 11 | Pollution Events | `http://127.0.0.1:8000/app/events` |
| 12 | Drift Monitoring | `http://127.0.0.1:8000/app/drift` |
| 13 | Live Monitoring | `http://127.0.0.1:8000/app/live` |
| 14 | AI Research | `http://127.0.0.1:8000/app/research` |

Supporting endpoints:

| Purpose | URL |
|---|---|
| Swagger API documentation | `http://127.0.0.1:8000/docs` |
| Health API | `http://127.0.0.1:8000/api/v1/health` |
| Candidate summary | `http://127.0.0.1:8000/api/v1/sar-candidates/summary` |
| Candidate detail | `http://127.0.0.1:8000/api/v1/sar-candidates/cand_s1_0036` |
| Candidate patch image | `http://127.0.0.1:8000/api/v1/sar-candidates/cand_s1_0036/image` |
| Optical evidence image (RGB) | `http://127.0.0.1:8000/api/v1/sar-candidates/cand_s1_0036/optical-evidence/1/image/rgb` |

---

## 3. Exact startup, check, and shutdown commands

Run these from the repository root in PowerShell.

### 3.1 Start

```powershell
cd "C:\Users\Shailesh\New folder (2)\ocean-intelligence-platform"
powershell -ExecutionPolicy Bypass -File scripts\start_oceanai_demo.ps1
```

What the script does:

1. Verifies Docker Desktop and the Docker daemon.
2. Finds the existing `ocean-intelligence-platform-db-1` container. It never creates or recreates the container.
3. Starts the existing container only if it is stopped.
4. Waits up to 120 seconds for PostgreSQL health.
5. Verifies SQLAlchemy connectivity using the backend's own settings.
6. Reuses a healthy OceanAI backend on port 8000, or starts one from `.venv` if the port is free.
7. Refuses to kill an unrelated process if port 8000 is occupied but the OceanAI health check fails.
8. Verifies the SPA, API docs, candidate detail, and candidate patch image.
9. Prints the demo URLs and data-label reminder.

Optional frontend rebuild after changing `frontend/src`:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_oceanai_demo.ps1 -RebuildFrontend
```

### 3.2 Read-only readiness check

```powershell
cd "C:\Users\Shailesh\New folder (2)\ocean-intelligence-platform"
powershell -ExecutionPolicy Bypass -File scripts\check_oceanai_demo.ps1
```

The current script performs 17 checks and exits `0` only when all pass. It is read-only except for the known drift-audit side effect described in Section 10.

### 3.3 Stop the backend

```powershell
cd "C:\Users\Shailesh\New folder (2)\ocean-intelligence-platform"
powershell -ExecutionPolicy Bypass -File scripts\stop_oceanai_demo.ps1
```

What the script does:

1. Reads `logs\demo\backend.pid`.
2. Verifies the PID's command line contains `uvicorn`, `app.main:app`, and this repository path.
3. Stops only that verified backend tree.
4. Leaves the PostGIS container and the `oip_pgdata` volume running and untouched.
5. Never runs `docker compose down`, never removes volumes, and never stops unrelated services.

If the PID file is missing or the process does not match, the script stops nothing.

### 3.4 Manual health check

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health | ConvertTo-Json
```

Expected key values:

```text
status      : ok
app_name    : Ocean Intelligence Platform
version     : 0.1.0
demo_mode   : True
```

---

## 4. Docker, database, and backend status at report time

### 4.1 Docker

| Item | Value |
|---|---|
| Docker server | `29.7.2` |
| Container | `ocean-intelligence-platform-db-1` |
| Image | `postgis/postgis:16-3.4` |
| Container ID | `402f9c5c4b8bbec29833ea4095d5e0ab3b0bc610b2cf85eb930f5c4ac66932cd` |
| Container status | `running` / `healthy` |
| Published port | host `5433` → container `5432` |
| Volume | `oip_pgdata` mounted at `/var/lib/postgresql/data` |
| Restart count | `0` |

### 4.2 Database

| Item | Value |
|---|---|
| PostgreSQL | `16.4 (Debian 16.4-1.pgdg110+2)` |
| PostGIS | `3.4.3` |
| Database / user | `oip` / `oip` |
| Alembic head | `b2c3d4e5f6a7` |
| Base tables | 41 in `public`, plus 2 PostGIS views (`geography_columns`, `geometry_columns`) |
| Integrity | No removed tables; file-state comparison found no data loss |

Final row counts:

| Table | Rows |
|---|---:|
| `water_quality_observations` | 4,601,153 (the readiness script labels this `water_observations`) |
| `water_bodies` | 2,740 |
| `monitoring_stations` | 4,951 |
| `sar_candidates` | 306 |
| `sar_candidate_reviews` | 8 |
| `sar_candidate_optical_evidence` | 1 |
| `drift_reports` | 56 |
| `drift_simulations` | 2 |
| `vessels` | 6 |
| `vessel_positions` | 28 |
| `research_documents` | 22 |
| `research_chunks` | 31 |
| `model_versions` | 2 |

Candidate summary at report time:

```text
total=306   awaiting=202   reviewed=5   eligible=207
UI caption: 202 awaiting + 5 reviewed = 207 eligible
```

**Provenance caveat:** the 306 candidates comprise **300 historical research-replay rows** (`cand_s1_*`) and **6 acceptance-test fixture rows** (`cand_test_*`). The 8 review events comprise **7 fixture reviews** and **1 review on the research candidate `cand_s1_0036`**. These QA rows are intentionally preserved. The UI labels the module as a research replay; do not present 306 as a production benchmark.

### 4.3 Backend

| Item | Value |
|---|---|
| Process | FastAPI / Uvicorn |
| Address | `127.0.0.1:8000` |
| PID file | `logs\demo\backend.pid` = `8932` |
| Actual listener | PID `28268` (child of 8932) |
| Backend trees | Exactly one (`8932` → `28268`) |
| Health | `status=ok`, `app_name=Ocean Intelligence Platform`, `version=0.1.0`, `demo_mode=True` |
| SPA source | `backend/app/static/app` |
| Error log | `logs\demo\backend.err.log`; **0** `ERROR` / `Traceback` / `CRITICAL` lines |
| Output log | `logs\demo\backend.out.log` |

The PID file records the process created by `Start-Process`; Uvicorn's serving child is the actual listener. This is expected and the shutdown script stops the verified tree. The two Python processes are the parent and serving child, not duplicate backends.

---

## 5. Startup and shutdown verification

### 5.1 Scenarios exercised

| Scenario | Starting state | Observed result |
|---|---|---|
| A | Database running, backend healthy | Startup reused the existing backend; printed “no duplicate process”; script returned in **2.5 s** |
| B | Database running, backend stopped | Startup started the backend; script returned in **12.5 s**; backend healthy afterward; exactly one tree |
| C | Database stopped, container and volume intact | Startup started the **existing** container (no recreation); same container ID `402f...`; same `oip_pgdata` mount; database healthy; backend started |
| D | Backend running, shutdown invoked | Shutdown stopped only the verified backend tree; port 8000 became free; database remained `running healthy` |

Scenario C is important: the script does **not** run `docker compose up` in a way that would recreate the container. It uses `docker start` on the existing container ID. The volume and data were preserved.

### 5.2 Earlier 300-second timeout / SIGTERM: root cause and resolution

**Observed earlier:** an invocation through the agent shell appeared to hang for about 300 seconds and was terminated, even though the startup script had already printed “OceanAI demo is ready” and the backend was healthy.

**Investigation:**

- The startup output completed normally.
- The outer PowerShell wrapper (PID 19928 in that run) remained alive while the backend (PID 7548) continued serving.
- The wrapper exited immediately after `stop_oceanai_demo.ps1` stopped the backend.
- The backend itself was never unhealthy and was not duplicated.
- Direct detached tests confirmed the script process exits on its own:
  - Reuse path: script process exited in **2.5 s**; backend remained healthy.
  - Cold path: script process exited in **12.5 s**; the new backend (`8932` → `28268`) remained healthy after the script process was gone.

**Root cause:** the agent harness waits for the command's descendant process tree / inherited Windows job or console handles. The detached Uvicorn process keeps that tree open, so the harness does not return even though `start_oceanai_demo.ps1` has finished. The earlier SIGTERM/timeout applied to the wrapper, not to the backend. This is a harness interaction, not a startup-script hang.

**Resolution:**

- The startup script is correct and exits normally.
- For normal use, run it from a regular PowerShell terminal, or launch it detached/backgrounded when using an agent shell.
- Do not interpret the harness waiting on the detached backend as a failed startup.
- The script's own internal waits are bounded: 120 seconds for PostgreSQL and 90 seconds for backend health.

---

## 6. Functional status of all 14 modules

“Pass” below means the module loaded and behaved as designed in the browser audit. It is not a scientific validation statement.

| # | Module | Status | Verified behaviour | Data provenance |
|---|---|---|---|---|
| 1 | Landing `/app` | Pass | Loaded; provenance legend (Observed, Detected, Inferred, Forecast, Retrieved); navigation and calls to action work | UI / static content |
| 2 | Command Center `/app/overview` | Pass — honest zero-state | Loaded; legacy marine KPI tiles show 0 events, 0 observations, 0 km² because those tables are empty; no fabricated values; update timestamp shown | Mixed: platform status is live; legacy marine KPIs are empty |
| 3 | India Water `/app/india` | Pass | 2,740 water bodies, 4,951 stations, 4,601,153 observations; freshness explanation; 0 current, 2,714 historical-only; latest observation Sep 26, 2026 | **Real archive** |
| 4 | India Water Map `/app/map` | Pass | Leaflet map; 30/30 OSM tiles loaded; 1,536 paths; 1,500 most-sampled shown; “status when last measured” legend and date caveat | **Real geometries and observations** |
| 5 | Ocean Map `/app/ocean-map` | Pass | 148 SAR scenes plus placeholder; 454 footprint paths; 0 monitored cells / 0 active detections; synthetic full-scene banner; candidate points identified as historical research detections | Mixed: real scene metadata and historical candidate points; **synthetic full-scene overlays** |
| 6 | Candidate Review `/app/candidate-review` | Pass | 306 total; 202 awaiting, 5 reviewed, 207 eligible; exhaustive disposition `136 + 70 + 0 + 1 + 99 = 306`; search placeholder now “Search candidate ID or patch name...”; no split/safe_scene in API or UI | Research replay: 300 historical rows + 6 QA fixtures; scores **uncalibrated** |
| 7 | Candidate Detail `/app/candidate-review/cand_s1_0036` | Pass | Patch image and optical image load; review history; ERA5 context; four optical products; fusion, drift, and impact panels; all synthetic/demo banners present | Mixed: real historical patch and metadata; **synthetic optical / AIS / drift / impact**; rule-based fusion |
| 8 | AI Assistant `/app/ai` | Pass | “Mithi River” answer returned; 5 citations; grounded; warning that latest data is 02 Dec 2021 (1,809 days old); map action present | **Real deterministic retrieval**, LLM disabled |
| 9 | System Health `/app/health` | Pass | 6 of 8 subsystems operational; database PostgreSQL 16.4 + PostGIS 3.4.3; LLM unavailable by configuration; prediction monitoring unavailable because no traffic | **Live service status** |
| 10 | Model Performance `/app/models` | Pass — not evaluated | 2 registered models, 1 deployed, 0 evaluated; metrics show “Not evaluated”; inference p95 unavailable (0 requests logged) | **Real registry inventory**; no metrics |
| 11 | Pollution Events `/app/events` | Pass — honest empty state | 0 of 0 detections; explicit “No matching detections” message | Empty legacy marine table |
| 12 | Drift Monitoring `/app/drift` | Pass — insufficient data | Overall status “Insufficient data”; minimum 30 samples per window; UI explicitly says this is not the same as “no drift” | Monitoring data; no verdict |
| 13 | Live Monitoring `/app/live` | Pass — honest empty state | Service operational; 0 observations; 0 requests logged; mock detector `mock-detector` / `sim-1.0.0`; no recent detections | Empty legacy marine tables; mock detector |
| 14 | AI Research `/app/research` | Pass | 22 documents / 31 passages; suggested questions; grounded retrieval; no-answer behaviour when corpus lacks evidence | **Real RAG corpus** |

---

## 7. Real-data-backed versus synthetic modules

### 7.1 Real or measured data

| Area | What is real | Notes |
|---|---|---|
| India water observations | 4,601,153 individual parameter measurements | Historical archive, not present-day water quality |
| Water bodies and stations | 2,740 water bodies; 4,951 monitoring stations | Resolved from station records |
| Water-body geometries | Real shapes used by the India map | 1,536 paths rendered from the most-sampled set |
| India map tiles | OpenStreetMap tiles; geoBoundaries attribution | 30/30 tiles loaded |
| Historical SAR candidate set | 300 research-replay candidates with historical patch images, scene metadata, and ERA5 collocation | Scores are uncalibrated |
| RAG corpus | 22 marine-pollution documents / 31 passages | Deterministic retrieval; no LLM |
| Service health | Live API-derived subsystem status | 6/8 available |
| Model registry | 2 registered models, 1 deployed | 0 evaluated; metrics null |

### 7.2 Synthetic, simulated, or seeded demonstrations

| Area | What is synthetic | Label in UI / API |
|---|---|---|
| Optical products | RGB, SWIR, SCL, NDCI arrays; not measured reflectance or chlorophyll | “Simulated … not measured reflectance” / “SYNTHETIC” |
| Full-scene SAR | Footprint detections and probabilities generated for demonstration; no live raster ingestion | “SYNTHETIC demonstration outputs” |
| AIS vessels | 6 seeded vessels / 28 positions; associations are proximity heuristics, not identity | “DEMONSTRATION DATA” |
| Multi-sensor fusion | Rule-based concordance over SAR plus simulated optical inputs; 0.92 is a rule score, not a probability | “rule score” / “not a calibrated probability” |
| Lagrangian drift | Constant forcing and stochastic beaching; not validated | “SIMULATION” |
| Environmental impact | Static distance lookup against 9 reference receptor points; `cand_s1_0036` returns 0 proximate receptors / LOW | “SIMULATION” |
| QA fixture candidates/reviews | 6 candidate fixtures and seeded review events | Preserved for test/demo continuity; not production data |

### 7.3 Empty or not evaluated

| Area | State |
|---|---|
| Command Center legacy marine KPIs | 0 events / 0 observations / 0 km² |
| Pollution Events | 0 detections |
| Live Monitoring | 0 observations / 0 requests |
| Model Performance | 2 registered, 0 evaluated |
| Drift Monitoring | Insufficient data; no verdict |
| AI Assistant LLM | `llm:none`; deterministic retrieval only |

---

## 8. Browser test results

### 8.1 Full 14-page audit

The audit loaded every route in a real browser and captured console, network, image, and DOM state.

| Result | Value |
|---|---|
| Pages loaded | **14 / 14** |
| HTTP errors | **0** |
| JavaScript errors | **0** |
| Broken images | **0** |
| Landing text length | 1,508 characters |
| Dashboard text length | 1,807 characters |
| India Water text length | 4,367 characters |
| Candidate detail | Loaded; full drawer and both images verified |
| Ocean Map | 148 scenes, synthetic banner, 454 footprint paths |
| India Map | 30/30 tiles, 1,536 paths |
| Raw results | `%TEMP%\oip-final\oip-browser-audit\results.json` |

### 8.2 Interaction audit

| Interaction | Result |
|---|---|
| Candidate search control | Present; placeholder **“Search candidate ID or patch name...”** |
| Candidate row click | Opened drawer for `cand_s1_0036` |
| Candidate images | **2 / 2** loaded: SAR patch and optical RGB; 0 broken |
| Research-replay banner | Present |
| Synthetic optical banner | Present |
| AIS demonstration banner | Present |
| Drift simulation banner | Present |
| Impact simulation banner | Present |
| Uncalibrated wording | “uncalibrated model score” present; “rule score” present; “not a calibrated probability” present |
| Ground-truth leakage | No `split`, `safe_scene`, or `ground_truth` in public API/UI |
| Overclaiming copy | No “Primary Suspect” or “High probability” leaks in the audited drawer |
| Candidate KPI captions | `202 awaiting + 5 reviewed = 207 eligible`; `136 + 70 + 0 + 1 + 99 = 306 total` |
| Optical tabs | True Colour default; SWIR, SCL Mask, and NDCI Algal Map each switched successfully; all four captions identify synthetic output |
| AI Assistant | Grounded answer; **5 citations**; map action present |
| India Map | Leaflet active; **30/30** tiles; **1,536** paths |
| Ocean Map | Leaflet active; **148** scenes plus placeholder; **454** footprint paths; synthetic banner present; no benchmark leak |
| Interaction HTTP errors | **0** (candidate, AI, India map, Ocean map) |
| Interaction JavaScript errors | **0** (candidate, AI, India map, Ocean map) |
| Raw interaction results | `%TEMP%\oip_final_interact.txt` |

Screenshots and intermediate interaction artifacts are under `%TEMP%\oip-interaction-audit\`.

---

## 9. Backend and frontend verification

### 9.1 Backend test suite

Command:

```powershell
cd "C:\Users\Shailesh\New folder (2)\ocean-intelligence-platform\backend"
..\.venv\Scripts\python.exe -m pytest -q --tb=short
```

Result:

```text
2 failed, 643 passed, 21 skipped in 51.17s
```

The suite runs against an isolated temporary SQLite database. `backend/tests/conftest.py` overwrites `DATABASE_URL` before importing the application and refuses to run the suite against PostgreSQL. The demo PostgreSQL database was not touched by these tests.

**Passed:** 643  
**Failed:** 2  
**Skipped:** 21

The 21 skips are expected environment gates, primarily:

- PostGIS tests that require `TEST_POSTGIS_URL`;
- model-weight tests whose local checkpoints are not present;
- agent tests that skip when no events are available.

#### The two failures

Both are in `backend/tests/test_wind_screener.py`, class `TestMultiSensorIntegrator`:

1. `test_multi_sensor_conflicting_algae`
2. `test_multi_sensor_supporting_sunglint`

Both fail with the same cause:

```text
TypeError: MultiSensorIntegrator.integrate() missing 2 required positional arguments:
'model_version' and 'sar_time'
```

The tests call:

```python
integrator.integrate("target_01", 33.0, 33.0, sar_result, optical_data)
```

The current method signature requires:

```python
integrate(candidate_id, latitude, longitude, sar_confidence, screening_status,
          model_version, sar_time, ...)
```

These tests are stale relative to the method signature. They are **pre-existing**, unrelated to this readiness pass, and were **not modified** to force a green result. The demo does not exercise these test paths.

### 9.2 Frontend typecheck and build

Commands:

```powershell
cd frontend
npm run typecheck
npm run build
```

Result:

| Step | Exit code | Details |
|---|---:|---|
| `npm run typecheck` (`tsc --noEmit`) | **0** | No type errors |
| `npm run build` (`tsc -b && vite build`) | **0** | Vite 6.4.3; 2,324 modules transformed |

Built SPA entry points:

```text
backend/app/static/app/index.html
backend/app/static/app/assets/index-DX-PNTCP.js
backend/app/static/app/assets/index-uuEnHRF0.css
```

The built candidate bundle contains the new placeholder and uncalibrated-score wording; the old `"Search candidate ID, scene"` string is absent.

### 9.3 Readiness script

Command:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_oceanai_demo.ps1
```

Result at 09:03 on 2026-11-16:

```text
ALL CHECKS PASSED (17/17)
```

Checks cover Docker, PostGIS container, database contents, health API, database version, SPA, API docs, console build freshness, India water overview, candidate summary, candidate calibration flag, held-out identifier absence, candidate patch image, optical product image, SAR scene inventory, model registry, and the drift endpoint.

---

## 10. Database and file-state comparison

### 10.1 Snapshot method

- Pre-demo snapshot: `%TEMP%\oip_before_snapshot.json`
- Post-audit snapshot: `%TEMP%\oip_after_snapshot.json`
- Comparator: `%TEMP%\oip_compare_snapshot.py`

The snapshot records every public table's row count and counts files in the important data directories.

### 10.2 Result

| Check | Result |
|---|---|
| Tables before | 41 |
| Tables after | 41 |
| Removed tables | None |
| Added tables | None |
| File-count changes | None |
| Data loss detected | **No** |
| Candidate rows | 306 before and after |
| Candidate review rows | 8 before and after |
| Water observations | 4,601,153 before and after |
| Optical evidence rows | 1 before and after |
| Vessels / positions | 6 / 28 before and after |
| Research documents / chunks | 22 / 31 before and after |
| Model versions | 2 before and after |

### 10.3 The one row-count change: `drift_reports`

At the time of the first snapshot comparison, `drift_reports` changed from **36 to 52 (+16)**. A final re-comparison after the last readiness and verification calls shows **36 to 56 (+20)**. In both comparisons, no rows were deleted, no tables were added or removed, and file counts were unchanged.

Cause: `GET /api/v1/drift` runs the drift checks and persists audit-report rows. Each call appends **two** rows (data drift and prediction drift). The 14-page browser audit and readiness checks invoked the endpoint several times.

After the first comparison, the final readiness check and one manual verification call added two more pairs. The final count at report time is **56**. This is an additive side effect, not data loss.

This is a known limitation: the Drift Monitoring endpoint is a GET that mutates state. It was deliberately **not** fixed in this readiness pass to avoid changing application behaviour immediately before the demo. Do not describe the drift endpoint as side-effect-free.

### 10.4 Backups

Two non-destructive backup sets are preserved:

| Backup directory | Contents |
|---|---|
| `backups\demo_readiness_20261115_160151\` | Original pre-edit copies of files changed during the readiness pass |
| `backups\demo_readiness_20261116_085025\` | Later wording and script backups, with SHA-256 manifest |

No backup, fixture, review, evidence row, dataset, or log was deleted.

---

## 11. Changes made during this readiness pass

These are the changes that took the repository from the Phase 18 audit state to the current demo state.

| Area | Change |
|---|---|
| Data paths | Candidate and optical image resolution fixed to use repository-root absolute paths; fixes images when the backend is launched from a different working directory |
| Public candidate API | Removed `split`, `safe_scene`, and `ground_truth` from public candidate responses |
| Candidate UI | Removed `split` and `safe_scene` display; corrected search placeholder to “Search candidate ID or patch name...” in `frontend/src/pages/CandidateReview.tsx` |
| Optical panels | Added synthetic-product labels to all four optical views |
| AIS panel | Added “DEMONSTRATION DATA” label and clarified proximity heuristic |
| Full-scene SAR | Added “SYNTHETIC demonstration outputs” label on Ocean Map |
| Fusion | Replaced “confidence” wording with “uncalibrated model score” and “rule score” in `backend/app/vision/multi_sensor.py` and `backend/app/services/candidate_service.py`; clarified not a calibrated probability |
| Drift / impact | Added simulation labels and clarified that outputs are not validated predictions |
| Candidate KPIs | Captions now derive from live counts rather than hardcoded numbers |
| Ocean Map | Scene limit increased to 200; 148 scenes currently returned |
| Startup script | Health check now verifies the OceanAI application name, not just `status=ok`; no duplicate backend; safe container reuse |
| Check script | Health check also verifies the application name |
| Frontend | Typecheck and production build rerun; SPA rebuilt into `backend/app/static/app` |

No scientific model was replaced. No schema migration was added. No test was modified to hide a failure. No destructive Git, Docker, or database command was run. All changes remain uncommitted; the branch has 97 dirty entries at report time.

---

## 12. Known limitations

### 12.1 Scientific and data limitations

1. **SAR scores are uncalibrated.** The 76.2% value is a model ranking score, not a probability and not a validated confidence. No calibration curve, precision/recall, or held-out evaluation exists for the deployed model.
2. **Candidate review is a research replay, not a blind operational review.** The 306-row table includes 300 historical research rows and 6 QA fixtures. The underlying table still stores `split` and `safe_scene`, even though the public API/UI no longer expose them. Do not claim blinding or benchmark isolation.
3. **The live database contains seeded QA reviews.** 8 review events exist: 7 on acceptance-test fixtures and 1 on the research candidate `cand_s1_0036`. The UI's “5 reviewed” count is distinct candidates, not review events.
4. **Full-scene SAR is synthetic.** There is no live raster ingestion; footprint probabilities are demonstration outputs.
5. **Optical products are synthetic.** RGB, SWIR, SCL, and NDCI arrays are generated. The scene metadata (granule, platform, tile, time, cloud cover) is real, but the pixels and indices are not measured reflectance or chlorophyll.
6. **Fusion is rule-based.** The 0.92 value is a concordance score over inputs that include simulated optical data. It is not a probability and not a Bayesian posterior.
7. **AIS is a seeded demonstration.** 6 vessels and 28 positions; association is a proximity heuristic, not identity confirmation.
8. **Drift is simulated.** Constant forcing and stochastic beaching; trajectories and beaching flags are illustrative. Legacy stored mass balance may not conserve mass.
9. **Impact is a static distance lookup.** It uses 9 reference receptor points and is not a validated vulnerability index. `cand_s1_0036` returns 0 proximate receptors / LOW.
10. **India water data is historical.** 0 of 2,740 water bodies have data recent enough to describe present-day condition. The latest observation anywhere is 26 Sep 2026; manual sampling records largely stop in 2021. The Mithi River answer is based on 02 Dec 2021 data.
11. **AI is deterministic retrieval, not an LLM.** `llm:none`; answers are assembled from stored records or the 22-document / 31-passage corpus, with citations. It declines when evidence is missing.
12. **Models are not evaluated.** 2 registered, 1 deployed, 0 evaluated. No mAP, latency, or calibration claims can be made.
13. **Legacy marine modules are empty.** Command Center marine KPIs, Pollution Events, and Live Monitoring show zero. This is honest, not a bug.
14. **Drift has insufficient data.** The status is “insufficient data”, not “no drift”. Minimum 30 samples per window.
15. **State-changing GET.** `GET /api/v1/drift` appends audit rows. Every readiness check adds two `drift_reports` rows.

### 12.2 Operational and security limitations

1. The application is a local demonstration, not a hardened deployment.
2. No authentication or authorization is enforced.
3. No external monitoring, backup schedule, or high-availability configuration is in place.
4. The frontend has no separate unit-test suite in this pass; typecheck and production build are the verification gate.
5. The two stale `MultiSensorIntegrator` tests remain red and are not part of the demo path.
6. The working tree is uncommitted (97 entries); the demo relies on the current working tree, not a tagged release.

---

## 13. Recommended faculty presentation sequence

Target length: **18–20 minutes**, plus questions. The sequence leads with the strongest real asset, then demonstrates the review workflow and provenance discipline.

| Time | Module | URL | Suggested talk track |
|---:|---|---|---|
| 0:00 | Landing | `/app` | “OceanAI separates observed, detected, inferred, forecast, and retrieved information. Every value carries its provenance.” |
| 0:01 | India Water | `/app/india` | “This is the real archive: 4.6 million observations, 2,740 water bodies, 4,951 stations. It is historical, and the platform says so: zero bodies have data recent enough for a present-tense claim.” |
| 0:05 | India Water Map | `/app/map` | “1,536 water-body shapes, 30 map tiles. Colour shows what the last measurement found and when, not today's condition.” |
| 0:08 | AI Assistant | `/app/ai` | Ask: “What is the latest available status of Mithi River?” Show the answer, the 02 Dec 2021 date, the 1,809-day staleness warning, and the 5 citations. “This is deterministic retrieval, not an LLM.” |
| 0:12 | Candidate Review | `/app/candidate-review` | “A research replay of a frozen Sentinel-1 audit set. 306 rows, 202 awaiting + 5 reviewed = 207 eligible. The scores are uncalibrated rankings.” |
| 0:15 | Candidate Detail | `/app/candidate-review/cand_s1_0036` | Centerpiece: SAR patch, ERA5 wind context, four optical tabs, fusion, review history, drift, impact. Point out every synthetic label and the “uncalibrated model score 76.2%” wording. |
| 0:21 | Ocean Map | `/app/ocean-map` | “148 historical SAR scenes; the full-scene overlays are explicitly SYNTHETIC. Candidate points are historical research detections, not a live feed.” |
| 0:24 | System Health | `/app/health` | “6 of 8 subsystems operational; database and PostGIS live; LLM disabled by configuration; prediction monitoring has no traffic yet. The platform reports null rather than inventing a number.” |
| 0:26 | Model Performance | `/app/models` | “2 registered, 1 deployed, 0 evaluated. Null means not evaluated — no performance claim.” |
| 0:27 | Drift Monitoring | `/app/drift` | “Insufficient data. That is not the same as no drift.” |
| 0:28 | AI Research | `/app/research` | Ask a regulatory question; show the cited answer and the corpus size (22 documents / 31 passages). |
| 0:30 | Close | — | “The India water layer is real and dated. The marine layers are labeled research replays and synthetic demonstrations. Scientific validation is the next phase.” |

### 13.1 Short version (8–10 minutes)

If time is tight:

1. Landing (`/app`) — 1 minute.
2. India Water (`/app/india`) — 3 minutes.
3. AI Assistant (`/app/ai`) — 2 minutes.
4. Candidate Detail (`/app/candidate-review/cand_s1_0036`) — 3 minutes.
5. System Health (`/app/health`) — 1 minute.

### 13.2 Pages to show only if asked

- **Command Center** — zero legacy marine KPIs; honest empty state.
- **Pollution Events** — 0 of 0; honest no-detections state.
- **Live Monitoring** — 0 observations / 0 requests; mock detector.
- **Drift Monitoring** — insufficient data; useful to explain “not the same as no drift”.

### 13.3 Do not click during the presentation

These controls mutate state or trigger pipeline work:

- “Adopt Recommendation”
- “Attach Track to Review”
- “Re-attach Drift Risk to Review”
- “Run ingestion”
- “Stage-2 refine”
- Review submission controls (unless explicitly demonstrating an append-only review)
- Any retraining or experiment control

Showing the Drift Monitoring page is safe for the demo but appends audit rows. Do not call it “read-only”.

### 13.4 Verbal guardrails

Use these phrases:

- “Uncalibrated model score”, not “confidence” or “probability”.
- “Rule-based concordance”, not “Bayesian” or “fusion probability”.
- “Research replay”, not “benchmark” or “validated evaluation”.
- “Synthetic demonstration”, not “detected slick” or “satellite detection”.
- “Historical observation”, not “current water quality”.
- “Not evaluated”, not “zero performance”.
- “Insufficient data”, not “no drift”.

---

## 14. Pre-presentation checklist

- [ ] Docker Desktop is running.
- [ ] From the repository root: `powershell -ExecutionPolicy Bypass -File scripts\start_oceanai_demo.ps1`.
- [ ] From the repository root: `powershell -ExecutionPolicy Bypass -File scripts\check_oceanai_demo.ps1` → **ALL CHECKS PASSED (17/17)**.
- [ ] Open `http://127.0.0.1:8000/app` and confirm the landing page.
- [ ] Open `http://127.0.0.1:8000/app/candidate-review/cand_s1_0036` and confirm both images load.
- [ ] Open `http://127.0.0.1:8000/app/ai` and run the Mithi River question once; confirm citations.
- [ ] Open `http://127.0.0.1:8000/app/map` and wait for 30/30 tiles.
- [ ] Open `http://127.0.0.1:8000/app/ocean-map` and confirm the synthetic banner.
- [ ] Keep `powershell -ExecutionPolicy Bypass -File scripts\stop_oceanai_demo.ps1` ready for shutdown.
- [ ] Do **not** run `docker compose down -v` or remove the `oip_pgdata` volume.
- [ ] If port 8000 is occupied, check `/api/v1/health` first; the startup script will not kill an unrelated process.
- [ ] If `frontend/src` changed since the build, rerun with `-RebuildFrontend`.
- [ ] Have the limitations section available for questions.

---

## 15. Evidence and artifacts

| Artifact | Location |
|---|---|
| Phase 18 system audit | `docs\verification\PHASE_18_SYSTEM_AUDIT.md` |
| This report | `docs\verification\DEMO_READINESS_REPORT.md` |
| Startup script | `scripts\start_oceanai_demo.ps1` |
| Readiness check script | `scripts\check_oceanai_demo.ps1` |
| Shutdown script | `scripts\stop_oceanai_demo.ps1` |
| Full backend test output | `%TEMP%\oip_pytest_full.txt` |
| Browser audit results | `%TEMP%\oip-final\oip-browser-audit\results.json` |
| Interaction audit results | `%TEMP%\oip_final_interact.txt` |
| Interaction screenshots | `%TEMP%\oip-interaction-audit\` |
| Pre-demo snapshot | `%TEMP%\oip_before_snapshot.json` |
| Post-audit snapshot | `%TEMP%\oip_after_snapshot.json` |
| Final post-check snapshot | `%TEMP%\oip_after_final_snapshot.json` |
| Snapshot comparator | `%TEMP%\oip_compare_snapshot.py` |
| Original backups | `backups\demo_readiness_20261115_160151\` |
| Later backups + manifest | `backups\demo_readiness_20261116_085025\` |
| Backend logs | `logs\demo\backend.out.log`, `logs\demo\backend.err.log` |
| Backend PID file | `logs\demo\backend.pid` |

---

## 16. Scope confirmation

- Phase 19 was **not** started.
- The application was **not** redesigned.
- Scientific models were **not** replaced.
- No feature unrelated to the presentation was added.
- No test fixture, review, evidence, dataset, database row, or file was deleted.
- No destructive Git, Docker, or database command was run.
- No scientific validation is claimed for synthetic or uncalibrated outputs.

**Final state:** the OceanAI demo is running locally at `http://127.0.0.1:8000/app` with the database healthy, the backend healthy, the SPA current, all 17 readiness checks passing, all 14 pages verified, and all known limitations documented above.
