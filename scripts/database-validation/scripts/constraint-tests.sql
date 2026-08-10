\set ON_ERROR_STOP on

-- Test data is isolated inside a transaction and rolled back.
BEGIN;

INSERT INTO users (id, email)
VALUES ('10000000-0000-4000-8000-000000000001', 'owner@example.com');

DO $$
BEGIN
  BEGIN
    INSERT INTO users (email) VALUES ('  OWNER@example.com  ');
    RAISE EXCEPTION 'case-insensitive email unique constraint did not reject duplicate';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

INSERT INTO datasets (id, user_id, name)
VALUES (
  '20000000-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000001',
  'dataset-a'
);

INSERT INTO dataset_versions (
  id, dataset_id, version_number, original_filename, file_format, status
) VALUES (
  '30000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001',
  1, 'input.csv', 'CSV', 'UPLOADING'
);

DO $$
BEGIN
  BEGIN
    INSERT INTO dataset_versions (
      dataset_id, version_number, original_filename, file_format
    ) VALUES (
      '20000000-0000-4000-8000-000000000001', 1, 'dup.csv', 'CSV'
    );
    RAISE EXCEPTION 'dataset version unique constraint did not reject duplicate';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

INSERT INTO upload_sessions (
  dataset_version_id, storage_key, expires_at, status, upload_method
) VALUES (
  '30000000-0000-4000-8000-000000000001',
  'uploads/one', now() + interval '1 hour', 'INITIATED', 'SINGLE_PUT'
);

DO $$
BEGIN
  BEGIN
    INSERT INTO upload_sessions (
      dataset_version_id, storage_key, expires_at, status, upload_method, upload_id
    ) VALUES (
      '30000000-0000-4000-8000-000000000001',
      'uploads/invalid-single', now() + interval '1 hour', 'FAILED', 'SINGLE_PUT', 'unexpected-id'
    );
    RAISE EXCEPTION 'SINGLE_PUT storage constraint did not reject upload_id';
  EXCEPTION WHEN check_violation THEN NULL;
  END;

  BEGIN
    INSERT INTO upload_sessions (
      dataset_version_id, storage_key, expires_at, status, upload_method
    ) VALUES (
      '30000000-0000-4000-8000-000000000001',
      'uploads/invalid-multipart', now() + interval '1 hour', 'FAILED', 'MULTIPART'
    );
    RAISE EXCEPTION 'MULTIPART storage constraint did not require upload_id and part_size_bytes';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

DO $$
BEGIN
  BEGIN
    INSERT INTO upload_sessions (
      dataset_version_id, storage_key, expires_at, status, upload_method
    ) VALUES (
      '30000000-0000-4000-8000-000000000001',
      'uploads/two', now() + interval '1 hour', 'UPLOADING', 'SINGLE_PUT'
    );
    RAISE EXCEPTION 'active upload-session partial unique index did not reject duplicate';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

DO $$
BEGIN
  BEGIN
    INSERT INTO dataset_versions (
      dataset_id, version_number, original_filename, file_format, status
    ) VALUES (
      '20000000-0000-4000-8000-000000000001', 2, 'bad.csv', 'CSV', 'INVALID'
    );
    RAISE EXCEPTION 'dataset version status CHECK did not reject invalid value';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

INSERT INTO models (id, user_id, name)
VALUES (
  '40000000-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000001',
  'model-a'
);

INSERT INTO training_jobs (
  id, user_id, model_id, dataset_version_id, algorithm, idempotency_key
) VALUES (
  '50000000-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000001',
  '40000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001',
  'xgboost', 'test-key'
);

DO $$
BEGIN
  BEGIN
    INSERT INTO model_versions (
      model_id, training_job_id, version_number, status, artifact_uri, artifact_format
    ) VALUES (
      '40000000-0000-4000-8000-000000000001',
      '50000000-0000-4000-8000-000000000001',
      1, 'READY', '   ', 'ONNX'
    );
    RAISE EXCEPTION 'READY model version blank artifact CHECK did not reject value';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

ROLLBACK;
