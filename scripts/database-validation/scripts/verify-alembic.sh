#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
POSTGRES_USER="${POSTGRES_USER:-argmax}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-argmax}"
POSTGRES_PORT="${POSTGRES_PORT:-5433}"
ALEMBIC_DB="${ALEMBIC_DB:-argmax_alembic_test}"
DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT}/${ALEMBIC_DB}"

cd "$ROOT_DIR"
docker compose up -d db
until docker compose exec -T db pg_isready -U "$POSTGRES_USER" -d postgres >/dev/null 2>&1; do sleep 1; done

docker compose exec -T db psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 <<SQL
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$ALEMBIC_DB' AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS $ALEMBIC_DB;
CREATE DATABASE $ALEMBIC_DB;
SQL

export DATABASE_URL
python -m alembic upgrade head
python -m alembic current
python -m alembic heads

docker compose exec -T db psql -U "$POSTGRES_USER" -d "$ALEMBIC_DB" -v ON_ERROR_STOP=1 < scripts/assertions.sql
seed_count="$(docker compose exec -T db psql -U "$POSTGRES_USER" -d "$ALEMBIC_DB" -Atc "SELECT count(*) FROM users WHERE id='00000000-0000-4000-8000-000000000001' AND lower(btrim(email))='evaluator@argmax-mini.local';" | tr -d '\r')"
[[ "$seed_count" == "1" ]] || { echo "evaluator seed count after upgrade is $seed_count" >&2; exit 1; }

python -m alembic downgrade base
remaining="$(docker compose exec -T db psql -U "$POSTGRES_USER" -d "$ALEMBIC_DB" -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' AND table_name <> 'alembic_version';" | tr -d '\r')"
[[ "$remaining" == "0" ]] || { echo "application tables remain after downgrade: $remaining" >&2; exit 1; }

python -m alembic upgrade head
seed_count="$(docker compose exec -T db psql -U "$POSTGRES_USER" -d "$ALEMBIC_DB" -Atc "SELECT count(*) FROM users WHERE id='00000000-0000-4000-8000-000000000001';" | tr -d '\r')"
[[ "$seed_count" == "1" ]] || { echo "evaluator seed count after re-upgrade is $seed_count" >&2; exit 1; }

echo "PASS: Alembic upgrade/downgrade/re-upgrade and evaluator seed verified."
