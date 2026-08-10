# ArgMax Mini database validation

This bundle validates `schema-v2.sql` and the Alembic revision chain against a real PostgreSQL 16 container.

## 1. WSL prerequisites

Run from Ubuntu WSL2:

```bash
./scripts/install-docker-wsl.sh
```

Close and reopen WSL after installation, then confirm:

```bash
docker version
docker compose version
```

If Docker Desktop with WSL integration is already installed, skip the installation script.

## 2. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-db.txt
```

## 3. Run all database tests

```bash
cp .env.example .env
set -a
source .env
set +a
./scripts/verify-all.sh
```

## Tests

- Direct application of `schema-v2.sql` to `argmax_schema_test`
- Expected table/index counts
- Key PostgreSQL unique, partial unique, CHECK, and FK behavior
- Absence of evaluator seed in the schema-only DB
- Alembic `upgrade head`
- Fixed evaluator seed existence exactly once
- Alembic `downgrade base`
- Removal of all application tables
- Re-upgrade and seed idempotent outcome

The SQL schema and Alembic migration must be tested in separate databases. Do not apply both to the same database.
