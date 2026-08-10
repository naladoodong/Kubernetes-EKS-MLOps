#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POSTGRES_USER="${POSTGRES_USER:-argmax}"
SCHEMA_DB="${SCHEMA_DB:-argmax_schema_test}"

cd "$ROOT_DIR"
docker compose up -d db
until docker compose exec -T db pg_isready -U "$POSTGRES_USER" -d postgres >/dev/null 2>&1; do sleep 1; done

docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$SCHEMA_DB' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS $SCHEMA_DB;
CREATE DATABASE $SCHEMA_DB;
SQL

docker compose exec -T db psql -U "$POSTGRES_USER" -d "$SCHEMA_DB" -v ON_ERROR_STOP=1 < schema-v2.sql
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$SCHEMA_DB" -v ON_ERROR_STOP=1 < scripts/assertions.sql
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$SCHEMA_DB" -v ON_ERROR_STOP=1 < scripts/constraint-tests.sql

seed_count="$(docker compose exec -T db psql -U "$POSTGRES_USER" -d "$SCHEMA_DB" -Atc "SELECT count(*) FROM users WHERE id='00000000-0000-4000-8000-000000000001';" | tr -d '\r')"
[[ "$seed_count" == "0" ]] || { echo "schema-only DB unexpectedly contains evaluator seed" >&2; exit 1; }

echo "PASS: schema-v2.sql applied and database constraints verified."
