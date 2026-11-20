#!/usr/bin/env bash
#
# Restore the demo database and print the counts that prove it worked.
#
# For the case where something has been clicked mid-demo that should not have
# been -- stage-2 refine, an ingestion run -- and the previous state is needed
# back in under a minute.
#
# Usage:
#   scripts/reset_demo.sh                     # newest backups/oip-after-*.dump
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
if [ $# -ge 1 ]; then
  DUMP="$1"
else
  # Newest after-window dump. Deliberately not the newest file in backups/:
  # a before-window dump is a rollback point, not a known-good demo state.
  DUMP="$(ls -1t backups/oip-after-*.dump 2>/dev/null | head -1 || true)"
fi

if [ -z "${DUMP:-}" ] || [ ! -f "$DUMP" ]; then
  echo "No dump found. Looked for backups/oip-after-*.dump" >&2
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
SELECT 'Water quality observations', count(*)::text FROM water_quality_observations;
SQL
  awk -F'|' '{ printf "  %-28s %s\n", $1, $2 }'

echo
echo "Expected after window 3/4a: 686 events, 10 CRITICAL, 306 candidates,"
echo "307 prediction logs, 5 model versions (3 evaluated), 4.6M water obs."
echo
echo "Restart the API so it reconnects cleanly:"
echo "  (stop the uvicorn process, then)"
echo "  cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001"
