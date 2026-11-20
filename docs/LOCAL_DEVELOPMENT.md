# Local Development & Operation Guide — OceanAI India Water Intelligence

This guide documents the exact setup, persistence architecture, startup, shutdown, restart, and troubleshooting workflows for running the OceanAI India Water Intelligence platform entirely locally without cloud dependencies.

---

## 1. Local Architecture & URLs

The local stack runs via Docker Desktop (or natively with Python + Node) backed by PostgreSQL 16 + PostGIS 3.4.

| Service | Host URL / Port | Details |
|---|---|---|
| **OceanAI Console** | [`http://localhost:8000/app`](http://localhost:8000/app) | React SPA dashboard served by FastAPI |
| **India Water Map** | [`http://localhost:8000/app/map`](http://localhost:8000/app/map) | Interactive Leaflet PostGIS water map |
| **API Endpoints** | [`http://localhost:8000/api/v1`](http://localhost:8000/api/v1) | FastAPI endpoints |
| **OpenAPI Documentation** | [`http://localhost:8000/docs`](http://localhost:8000/docs) | Interactive Swagger UI |
| **Health Check** | [`http://localhost:8000/api/v1/health`](http://localhost:8000/api/v1/health) | System health & component status |
| **PostgreSQL / PostGIS** | `localhost:5433` (container `:5432`) | Spatial database storing all 4.6M records |

---

## 2. Persistent Data Architecture

The platform operates on **authentic historical and real-time open datasets**:
- **4,601,153 water-quality observations** (CPCB Manual to 2021/2025, CWC Manual to June 2025, and CPCB Real-Time automatic sensors).
- **4,951 monitoring stations** across 35 states and union territories.
- **2,740 resolved water bodies** across India.
- **405 matched PostGIS geometries** (river lines and lake polygons derived from OpenStreetMap bulk extracts).
- **771 administrative boundaries** (geoBoundaries ADM1 states and ADM2 districts).
- **35 curated cities** with polygon bounding extents.
- **17 Sentinel-2 L2A satellite scenes** with cloud-mask filtering and uncalibrated NDTI turbidity proxies.

### Docker Volume Mapping
The database and evidence files persist across container restarts and builds using named Docker volumes:

```yaml
volumes:
  pgdata:
    name: oip_pgdata
    external: true
  oipdata:
    name: ocean-intelligence-platform_oipdata
    external: true
```

> [!CAUTION]
> **Never run `docker compose down -v` or delete Docker volumes.** Doing so would erase the 4.6M observation PostGIS database. Standard restarts (`docker compose restart` or `docker compose down` without `-v`) safely preserve all data.

---

## 3. Quick Start (Docker Compose)

### Prerequisites
- Docker Desktop with Compose V2.
- Ensure ports `8000` and `5433` are available.

### Step 1: Verify Environment Configuration
Ensure `.env` exists in the repository root:
```bash
cp .env.example .env
```
Ensure `.env` contains:
```env
POSTGRES_USER=oip
POSTGRES_DB=oip
POSTGRES_PASSWORD=<your_secure_password>
POSTGRES_PORT=5433
DATABASE_URL=postgresql+psycopg://oip:<your_secure_password>@localhost:5433/oip
```

### Step 2: Start the PostGIS Database
```bash
docker compose up -d db
```
Verify database health:
```bash
docker compose ps db
```

### Step 3: Run Database Migrations (One-shot)
```bash
docker compose run --rm migrate
```
This confirms the Alembic schema is at `head`.

### Step 4: Start the Backend & Web Console
```bash
docker compose up -d backend
```
The FastAPI backend serves both the API and the pre-built React console. Open:
- **Dashboard**: [http://localhost:8000/app](http://localhost:8000/app)
- **Water Map**: [http://localhost:8000/app/map](http://localhost:8000/app/map)

---

## 4. Operational Commands

### Check Health & Service Status
```bash
# Container status
docker compose ps

# Application health endpoint
curl http://localhost:8000/api/v1/health

# Water domain overview (counts, recency, source breakdown)
curl http://localhost:8000/api/v1/water-overview
```

### Stopping the Services
```bash
# Stop containers without touching volumes
docker compose stop

# Or stop and remove containers (preserves persistent volumes)
docker compose down
```

### Restarting the Services
```bash
docker compose restart
```

### Rebuilding After Frontend or Backend Edits
```bash
# Rebuild frontend bundle locally if needed
cd frontend && npm run build && cd ..

# Rebuild and restart the container
docker compose up -d --build backend
```

---

## 5. Running Ingestion & Data Jobs

Data ingestion and processing commands are run as one-shot jobs via the `jobs` profile:

```bash
# Check status of previous ingestion jobs
docker compose run --rm jobs python -m app.water.cli jobs

# Ingest new readings from CPCB real-time analysers
docker compose run --rm jobs python -m app.water.cli sync-water-data --provider cpcb_rtwqms

# Match OpenStreetMap geometry from extracted features
docker compose run --rm jobs python -m app.water.cli import-geometry --file data/processed/india-water.ndjson

# Re-index Water RAG corpus and reference standards
docker compose run --rm jobs python -m app.water.cli reindex-water-rag
```

---

## 6. Running Tests

```bash
# Run PostGIS integration tests against local Docker DB (port 5433)
$env:TEST_POSTGIS_URL="postgresql+psycopg://oip:<password>@localhost:5433/oip"
python -m pytest backend/tests/test_postgis.py

# Run backend unit, domain, pipeline, and vision test suite (576 passing tests)
python -m pytest backend/tests --ignore=backend/tests/test_postgis.py

# Combined test suite: 597 passing tests, 0 failures

# Run frontend typecheck and production build
cd frontend
npm run typecheck
npm run build
```

### Running with Real YOLO Optical Water Pollution Detector
```bash
# Checkpoint is located at data/models/optical/best.pt (52 MB, YOLOv8m)
$env:DETECTOR_BACKEND="yolo"
$env:DATABASE_URL="postgresql+psycopg://oip:<password>@localhost:5433/oip"
python -m uvicorn app.main:app --app-dir backend --port 8000
```

---

## 7. Troubleshooting

### Port 8000 Already in Use
If port 8000 is occupied by another process or container:
```bash
# Identify listening processes
netstat -ano | findstr :8000
# Or in Docker
docker ps --filter "publish=8000"
```
Stop the conflicting process or container before launching OceanAI.

### Database Connection Refused (`localhost:5433`)
The `docker-compose.yml` maps port `5433:5432` to allow host tools to access the database without conflicting with host PostgreSQL instances.
Verify:
1. `docker compose ps db` shows `healthy`.
2. Port binding `0.0.0.0:5433->5432/tcp` is active.

### Missing Data or Empty Map
If the map appears empty:
1. Check that `docker-compose.yml` specifies `name: oip_pgdata` under `volumes.pgdata`.
2. Verify table counts:
   ```bash
   docker exec -it ocean-intelligence-platform-db-1 psql -U oip -d oip -c "SELECT count(*) FROM water_quality_observations;"
   ```
   Should output `4601153`.

### "No Recent Data" Status
This is **intended epistemic honesty**, not a bug:
- CPCB Manual records end in 2021.
- CWC Manual records end in June 2025.
- CPCB Real-Time automatic analysers report hourly on 40 stations in the Ganga basin.
Water bodies without observations within their reporting cadence correctly show **No Recent Data** and display historical observations with explicit sampling dates.
