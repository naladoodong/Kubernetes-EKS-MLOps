\set ON_ERROR_STOP on

DO $$
DECLARE
  table_count integer;
  index_count integer;
BEGIN
  SELECT count(*) INTO table_count
  FROM information_schema.tables
  WHERE table_schema = 'public'
    AND table_type = 'BASE TABLE'
    AND table_name <> 'alembic_version';

  IF table_count <> 14 THEN
    RAISE EXCEPTION 'Expected 14 application tables, found %', table_count;
  END IF;

  SELECT count(*) INTO index_count
  FROM pg_indexes
  WHERE schemaname = 'public'
    AND indexname NOT LIKE '%_pkey';

  IF index_count < 24 THEN
    RAISE EXCEPTION 'Expected at least 24 non-PK indexes, found %', index_count;
  END IF;
END $$;
