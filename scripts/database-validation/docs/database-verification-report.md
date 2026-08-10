# Database verification report

**Conclusion: PASS**

## Environment

| Item | Value |
| --- | --- |
| WSL distribution | Ubuntu-24.04 (WSL 2) |
| Ubuntu release | 24.04.4 LTS (Noble Numbat) |
| WSL version | 2.6.3.0 |
| Docker | 29.7.2 (build `a7dcaa6`) |
| Docker Compose | v5.4.0 |
| PostgreSQL image | `postgres:16-alpine` |
| PostgreSQL server | 16.14 (Alpine 15.2.0) |
| Python | 3.12.3 |
| Alembic | 1.16.5 |
| SQLAlchemy | 2.0.43 |
| psycopg | 3.2.9 |

## Commands executed

```bash
# Read README.md and every file in scripts/
cat README.md
for file in scripts/*; do cat "$file"; done

# Confirm the container tooling
docker --version
docker compose version

# Create/activate the environment and install requirements
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-db.txt

# Reset the configured local test environment
cp -f .env.example .env
set -a
source .env
set +a

# Complete validation
./scripts/verify-all.sh
```

Docker and Docker Compose were already available, so `scripts/install-docker-wsl.sh` was not run.

## Results

| Validation | Result | Evidence |
| --- | --- | --- |
| `schema-v2.sql` validation | PASS | Applied cleanly to a newly created `argmax_schema_test` database. |
| Schema assertions | PASS | Expected 14 application tables and at least 24 non-primary-key indexes were verified. |
| Constraint tests | PASS | Case-insensitive email uniqueness, dataset-version uniqueness, active upload-session partial uniqueness, status CHECK, and READY artifact CHECK all rejected invalid input as expected. |
| Schema-only seed check | PASS | Evaluator user count was `0`. |
| Alembic upgrade | PASS | Revisions `0001_initial_schema` and `0002_seed_evaluator_user` upgraded to head. |
| Evaluator seed verification | PASS | Fixed evaluator user existed exactly once after upgrade. |
| Alembic downgrade | PASS | `downgrade base` removed all application tables. |
| Alembic re-upgrade | PASS | Upgrade to head succeeded again; evaluator user count was exactly `1`. |

`./scripts/verify-all.sh` completed with exit code `0` and emitted:

```text
PASS: schema-v2.sql applied and database constraints verified.
PASS: Alembic upgrade/downgrade/re-upgrade and evaluator seed verified.
```

## Fixes made

None. The complete validation passed on the first test run; no schema, Alembic, seed migration, or verification-script changes were necessary.
