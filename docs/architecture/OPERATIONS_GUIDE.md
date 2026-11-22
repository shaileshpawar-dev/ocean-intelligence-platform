# OceanAI Operations, Ingestion & Incident Review Guide
**Project:** OceanAI — India Water Intelligence & Marine Intelligence Platform  
**Document:** `docs/architecture/OPERATIONS_GUIDE.md`  
**Status:** Living Engineering Guide  
**Last Updated:** November 12, 2026  

---

## 1. System Operating Environment

- **Operating System:** Windows 11 / Linux compatible
- **Database Engine:** PostgreSQL 16 with PostGIS 3.4 in Docker container `ocean-intelligence-platform-db-1` (port 5433).
- **Backend Runtime:** Python 3.12 virtual environment (`.venv\Scripts\python.exe`).
- **Frontend Runtime:** Node.js 18+ with Vite dev server or statically built bundle served via FastAPI.

---

## 2. Standard Service Commands

### 2.1 Starting Database Container
```powershell
docker start ocean-intelligence-platform-db-1
```

> [!CAUTION]
> Never execute `docker compose down -v`. Volume deletion will destroy the PostGIS database and historical candidate review records.

### 2.2 Running Backend Server
```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
- Interactive Swagger UI documentation: `http://127.0.0.1:8000/docs`
- Application Entrypoints:
  - `/app` (Intelligence Overview)
  - `/app/ocean-map` (Geospatial Ocean Map)
  - `/app/candidate-review` (Marine Incident Review Dashboard)
  - `/app/ai` (Model Diagnostics Console)

### 2.3 Running Frontend Development Server
```powershell
cd frontend
npm run dev
```

---

## 3. Copernicus Data Space Integration Configuration

To query and extract Sentinel-2 Level-2A imagery, configure the following environment keys in `.env`:

```env
# Copernicus Data Space Ecosystem (CDSE)
CDSE_STAC_URL=https://stac.dataspace.copernicus.eu/v1
CDSE_TOKEN_URL=https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token
CDSE_USERNAME=your_copernicus_username_here
CDSE_PASSWORD=your_copernicus_password_here
```

When credentials are not yet configured in local development, the platform gracefully switches to discoverable metadata exploration and cached local raster chips, clearly reporting `Authentication Unavailable` without application failure.

---

## 4. Analyst Review Workflow

1. Navigate to `/app/candidate-review`.
2. Inspect KPI summary metrics:
   - Evaluated Samples (306)
   - Mutually exclusive queues: Standard Wind (136), Low-Wind Ambiguity (70), High-Wind Ambiguity (0), Wind Unavailable (1), Non-Detections (99).
3. Select a candidate to open the **Candidate Detail Drawer**.
4. Examine the SAR dark patch, ERA5 wind context, and the newly added **Optical Evidence (Sentinel-2)** tab.
5. Record one of four formal review decisions:
   - `potential_oil_slick`
   - `rejected_lookalike`
   - `inconclusive`
   - `requires_additional_evidence`
6. Every review is recorded in table `sar_candidate_reviews` with an immutable append-only timestamp and notes.
