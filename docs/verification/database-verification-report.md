# Database Verification Report

## Environment

- PostgreSQL: 16.14 (`postgres:16-alpine`)
- Alembic: 1.16.5
- SQLAlchemy: 2.0.43
- psycopg: 3.2.9
- Docker: 29.7.2 (Docker Compose v5.4.0)
- WSL: Ubuntu 24.04.4 LTS on WSL 2 (WSL 2.6.3.0)

## Schema SQL Verification

- `schema-v2.sql` applied successfully
- 14 application tables created
- expected indexes and constraints verified
- negative constraint tests passed

## Alembic Verification

- upgrade head: PASS
- evaluator seed: PASS
- downgrade base: PASS
- re-upgrade head: PASS
- duplicate seed check: PASS

## Final Result

PASS
