#!/usr/bin/env bash
#
# Prove the test suite cannot touch a real database.
#
# The suite drops every table at session teardown. It once did that to the
# local PostgreSQL server, because `.env` exports DATABASE_URL and conftest
# used os.environ.setdefault: a dataset that took hours to ingest was emptied.
# conftest now overwrites DATABASE_URL and refuses to run against anything but
# its own temporary SQLite file.
#
# This script is the end-to-end check of that: it puts a marker table in the
# PostgreSQL database, runs the whole suite with DATABASE_URL deliberately
# pointed at it, and fails if the marker is gone afterwards.
#
# Usage (from the repository root, with .env present):
#   bash scripts/check_test_isolation.sh
set -euo pipefail

cd "$(dirname "$0")/.."
set -a
# shellcheck disable=SC1091
. ./.env
set +a

PSQL=(docker exec -i oip-postgis psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t -A)

echo "1. place a marker in ${POSTGRES_DB}"
"${PSQL[@]}" -c "CREATE TABLE IF NOT EXISTS isolation_marker (note text);"
"${PSQL[@]}" -c "DELETE FROM isolation_marker;"
"${PSQL[@]}" -c "INSERT INTO isolation_marker VALUES ('must survive the test suite');"

echo "2. run the suite with DATABASE_URL pointed at that database"
cd backend
DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT:-5433}/${POSTGRES_DB}" \
  ../.venv/Scripts/python.exe -m pytest -q 2>&1 | tail -3
cd ..

echo "3. the marker must still be there"
survived=$("${PSQL[@]}" -c "SELECT count(*) FROM isolation_marker;" || echo "0")
if [ "${survived}" = "1" ]; then
  echo "PASS: the suite ran on its own SQLite file and left the database alone."
  "${PSQL[@]}" -c "DROP TABLE isolation_marker;"
  exit 0
fi
echo "FAIL: the marker is gone (count=${survived}). The suite reached a real database."
exit 1
