#!/usr/bin/env bash
#
# Restore the demo database and print the counts that prove it worked.
#
# For the case where something has been clicked mid-demo that should not have
# been -- stage-2 refine, an ingestion run -- and the previous state is needed
# back in under a minute.
#
# Usage:
#   scripts/reset_demo.sh                     # backups/oip-demo-final.dump
#   scripts/reset_demo.sh path/to/file.dump   # a specific dump
#   FORCE=1 scripts/reset_demo.sh             # skip the confirmation prompt
#
# This DROPS AND RECREATES the public schema. Anything written since the dump
# is gone. It asks first unless FORCE=1.

set -euo pipefail

CONTAINER="${CONTAINER:-ocean-intelligence-platform-db-1}"
DB_USER="${DB_USER:-oip}"
DB_NAME="${DB_NAME:-oip}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# Pick the dump
# ---------------------------------------------------------------------------
# The frozen demo state, by name rather than by timestamp. "Newest
# after-window dump" was fine while windows were the unit of work, but it
# silently follows whatever ran last -- and the dump that should come back
# mid-demo is a specific known-good state, not the most recent one.
FINAL_DUMP="backups/oip-demo-final.dump"

if [ $# -ge 1 ]; then
  DUMP="$1"
elif [ -f "$FINAL_DUMP" ]; then
  DUMP="$FINAL_DUMP"
else
  # Fallback for a checkout without the frozen dump. A before-window dump is
  # a rollback point, not a known-good demo state, so those stay excluded.
  DUMP="$(ls -1t backups/oip-after-*.dump 2>/dev/null | head -1 || true)"
fi

if [ -z "${DUMP:-}" ] || [ ! -f "$DUMP" ]; then
  echo "No dump found. Looked for $FINAL_DUMP, then backups/oip-after-*.dump" >&2
  echo "Pass one explicitly: scripts/reset_demo.sh backups/<file>.dump" >&2
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "Container '$CONTAINER' is not running." >&2
  echo "Start it with: docker compose up -d db" >&2
  exit 1
fi

echo "Restoring : $DUMP"
echo "Into      : $DB_NAME on container $CONTAINER"
echo "Dump size : $(du -h "$DUMP" | cut -f1)"
echo

if [ "${FORCE:-0}" != "1" ]; then
  printf 'This DROPS the current database. Continue? [y/N] '
  read -r reply
  case "$reply" in
    [yY] | [yY][eE][sS]) ;;
    *)
      echo "Aborted. Nothing was changed."
      exit 1
      ;;
  esac
fi

# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------
echo "Dropping schema..."
docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -q \
  -c 'DROP SCHEMA public CASCADE;' \
  -c 'CREATE SCHEMA public;' \
  -c "GRANT ALL ON SCHEMA public TO $DB_USER;" \
  -c 'CREATE EXTENSION IF NOT EXISTS postgis;' >/dev/null

echo "Restoring data (a minute or so)..."
# pg_restore reports benign ownership and extension notices on a fresh schema;
# a non-zero exit is only fatal if the verification below comes back wrong.
if ! docker exec -i "$CONTAINER" pg_restore -U "$DB_USER" -d "$DB_NAME" \
  --no-owner --no-privileges < "$DUMP" 2>/tmp/oip_restore_err; then
  echo "pg_restore reported warnings; verifying the result anyway." >&2
fi

# ---------------------------------------------------------------------------
# Prove it
# ---------------------------------------------------------------------------
echo
echo "=== Restored state ==="

docker exec -i "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -At -F'|' <<'SQL' |
SELECT 'Pollution events',        count(*)::text FROM pollution_events
UNION ALL
SELECT '  of which CRITICAL',     count(*)::text FROM pollution_events WHERE severity = 'CRITICAL'
UNION ALL
SELECT 'SAR candidates',          count(*)::text FROM sar_candidates
UNION ALL
SELECT 'Prediction logs',         count(*)::text FROM prediction_logs
UNION ALL
SELECT 'Model versions',          count(*)::text FROM model_versions
UNION ALL
SELECT '  of which evaluated',    count(*)::text FROM model_versions WHERE metrics_source IS NOT NULL
UNION ALL
SELECT 'Regions',                 count(*)::text FROM regions
UNION ALL
SELECT 'Zone history buckets',    count(*)::text FROM zone_history
UNION ALL
SELECT 'Water quality observations', count(*)::text FROM water_quality_observations
UNION ALL
SELECT 'Sentinel-2 index readings', count(*)::text FROM optical_index_observations
UNION ALL
SELECT 'Reports',                  count(*)::text FROM reports
UNION ALL
SELECT 'Agent runs',               count(*)::text FROM agent_runs;
SQL
  awk -F'|' '{ printf "  %-28s %s\n", $1, $2 }'

echo
echo "Expected (oip-demo-final, frozen 21 Nov 2026):"
echo "  666 events, 81 CRITICAL, 306 candidates, 337 prediction logs,"
echo "  5 model versions (3 evaluated), 4,601,509 water obs, 40 regions,"
echo "  253 Sentinel-2 index readings, 8 reports, 8 agent runs."
echo
echo "The cached external data (Sentinel-2, Copernicus Marine, Open-Meteo,"
echo "GFW) lives in the oipdata volume, not in this dump, and is untouched."
echo
echo "Restart the API so it reconnects cleanly:"
echo "  docker compose restart backend"
