-- ArgMax Mini PostgreSQL schema
-- Source of truth: docs/architecture/data-model-v5.md and docs/architecture/state-transitions-v4.md
-- Revision: database/schema-v2.sql
-- PostgreSQL 14+

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- -----------------------------------------------------------------------------
-- 1. users
-- -----------------------------------------------------------------------------
CREATE TABLE users (
    id          UUID         NOT NULL DEFAULT gen_random_uuid(),
    email       VARCHAR(320) NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT pk_users PRIMARY KEY (id),
    CONSTRAINT ck_users_email_not_blank
        CHECK (length(btrim(email)) > 0)
);

CREATE UNIQUE INDEX uq_users_email_ci
    ON users (lower(btrim(email)));

COMMENT ON TABLE users IS
    'Resource ownership root. Authentication implementation is outside the current scope.';

-- -----------------------------------------------------------------------------
-- 2. datasets
-- -----------------------------------------------------------------------------
CREATE TABLE datasets (
    id          UUID         NOT NULL DEFAULT gen_random_uuid(),
    user_id     UUID         NOT NULL,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ,

    CONSTRAINT pk_datasets PRIMARY KEY (id),
    CONSTRAINT fk_datasets_user
        FOREIGN KEY (user_id)
        REFERENCES users (id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_datasets_name_not_blank
        CHECK (length(btrim(name)) > 0)
);

CREATE UNIQUE INDEX uq_datasets_active_user_name
    ON datasets (user_id, lower(btrim(name)))
    WHERE deleted_at IS NULL;

COMMENT ON TABLE datasets IS
    'Logical dataset container. File metadata and processing status belong to dataset_versions.';

-- -----------------------------------------------------------------------------
-- 3. dataset_versions
-- -----------------------------------------------------------------------------
CREATE TABLE dataset_versions (
    id                      UUID         NOT NULL DEFAULT gen_random_uuid(),
    dataset_id              UUID         NOT NULL,
    version_number          INTEGER      NOT NULL,
    original_filename       VARCHAR(512) NOT NULL,
    file_format             VARCHAR(16)  NOT NULL,
    mime_type               VARCHAR(255),
    size_bytes              BIGINT,
    original_storage_uri    TEXT,
    processed_storage_uri   TEXT,
    checksum_algorithm      VARCHAR(16)  NOT NULL DEFAULT 'SHA256',
    checksum                VARCHAR(128),
    row_count               BIGINT,
    column_count            INTEGER,
    status                  VARCHAR(32)  NOT NULL DEFAULT 'PENDING',
    error_code              VARCHAR(100),
    error_message           TEXT,
    processing_started_at   TIMESTAMPTZ,
    processing_finished_at  TIMESTAMPTZ,
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT pk_dataset_versions PRIMARY KEY (id),
    CONSTRAINT fk_dataset_versions_dataset
        FOREIGN KEY (dataset_id)
        REFERENCES datasets (id)
        ON DELETE CASCADE,
    CONSTRAINT uq_dataset_versions_dataset_version
        UNIQUE (dataset_id, version_number),
    CONSTRAINT ck_dataset_versions_filename_not_blank
        CHECK (length(btrim(original_filename)) > 0),
    CONSTRAINT ck_dataset_versions_version_number_positive
        CHECK (version_number > 0),
    CONSTRAINT ck_dataset_versions_file_format
        CHECK (file_format IN ('CSV', 'XLSX')),
    CONSTRAINT ck_dataset_versions_checksum_algorithm
        CHECK (checksum_algorithm = 'SHA256'),
    CONSTRAINT ck_dataset_versions_size_non_negative
        CHECK (size_bytes IS NULL OR size_bytes >= 0),
    CONSTRAINT ck_dataset_versions_row_count_non_negative
        CHECK (row_count IS NULL OR row_count >= 0),
    CONSTRAINT ck_dataset_versions_column_count_non_negative
        CHECK (column_count IS NULL OR column_count >= 0),
    CONSTRAINT ck_dataset_versions_status
        CHECK (status IN (
            'PENDING', 'UPLOADING', 'UPLOADED',
            'PROCESSING', 'READY', 'FAILED'
        )),
    CONSTRAINT ck_dataset_versions_finished_requires_started
        CHECK (
            processing_finished_at IS NULL
            OR processing_started_at IS NOT NULL
        ),
    CONSTRAINT ck_dataset_versions_processing_time_order
        CHECK (
            processing_finished_at IS NULL
            OR processing_finished_at >= processing_started_at
        )
);

CREATE INDEX idx_dataset_versions_dataset_status_version
    ON dataset_versions (dataset_id, status, version_number DESC);

CREATE INDEX idx_dataset_versions_status_created
    ON dataset_versions (status, created_at);

COMMENT ON COLUMN dataset_versions.file_format IS
    'Original user-uploaded file format. Processed internal format is represented by processed_storage_uri.';
COMMENT ON TABLE dataset_versions IS
    'Immutable uploaded file version and its processing metadata.';

-- -----------------------------------------------------------------------------
-- 4. dataset_columns
-- -----------------------------------------------------------------------------
CREATE TABLE dataset_columns (
    id                  UUID         NOT NULL DEFAULT gen_random_uuid(),
    dataset_version_id  UUID         NOT NULL,
    name                VARCHAR(255) NOT NULL,
    ordinal_position    INTEGER      NOT NULL,
    data_type           VARCHAR(32)  NOT NULL,
    physical_type       VARCHAR(64),
    is_nullable         BOOLEAN      NOT NULL DEFAULT false,
    null_count          BIGINT       NOT NULL DEFAULT 0,
    distinct_count      BIGINT,
    statistics_json     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT pk_dataset_columns PRIMARY KEY (id),
    CONSTRAINT fk_dataset_columns_dataset_version
        FOREIGN KEY (dataset_version_id)
        REFERENCES dataset_versions (id)
        ON DELETE CASCADE,
    CONSTRAINT uq_dataset_columns_version_ordinal
        UNIQUE (dataset_version_id, ordinal_position),
    CONSTRAINT ck_dataset_columns_name_not_blank
        CHECK (length(btrim(name)) > 0),
    CONSTRAINT ck_dataset_columns_ordinal_positive
        CHECK (ordinal_position > 0),
    CONSTRAINT ck_dataset_columns_null_count_non_negative
        CHECK (null_count >= 0),
    CONSTRAINT ck_dataset_columns_distinct_count_non_negative
        CHECK (distinct_count IS NULL OR distinct_count >= 0),
    CONSTRAINT ck_dataset_columns_data_type
        CHECK (data_type IN (
            'STRING', 'INTEGER', 'FLOAT', 'BOOLEAN',
            'DATE', 'DATETIME', 'CATEGORY', 'UNKNOWN'
        ))
);

CREATE UNIQUE INDEX uq_dataset_columns_version_name_ci
    ON dataset_columns (dataset_version_id, lower(btrim(name)));

-- -----------------------------------------------------------------------------
-- 5. upload_sessions
-- -----------------------------------------------------------------------------
CREATE TABLE upload_sessions (
    id                           UUID         NOT NULL DEFAULT gen_random_uuid(),
    dataset_version_id           UUID         NOT NULL,
    status                       VARCHAR(32)  NOT NULL DEFAULT 'INITIATED',
    storage_key                  TEXT         NOT NULL,
    upload_method                VARCHAR(16)  NOT NULL,
    upload_id                    TEXT,
    expected_size_bytes          BIGINT,
    expected_checksum_algorithm  VARCHAR(16)  NOT NULL DEFAULT 'SHA256',
    expected_checksum            VARCHAR(128),
    part_size_bytes              INTEGER,
    expires_at                   TIMESTAMPTZ  NOT NULL,
    completed_at                 TIMESTAMPTZ,
    aborted_at                   TIMESTAMPTZ,
    error_code                   VARCHAR(100),
    error_message                TEXT,
    created_at                   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at                   TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT pk_upload_sessions PRIMARY KEY (id),
    CONSTRAINT fk_upload_sessions_dataset_version
        FOREIGN KEY (dataset_version_id)
        REFERENCES dataset_versions (id)
        ON DELETE CASCADE,
    CONSTRAINT ck_upload_sessions_storage_key_not_blank
        CHECK (length(btrim(storage_key)) > 0),
    CONSTRAINT ck_upload_sessions_status
        CHECK (status IN (
            'INITIATED', 'UPLOADING', 'COMPLETED',
            'ABORTED', 'EXPIRED', 'FAILED'
        )),
    CONSTRAINT ck_upload_sessions_upload_method
        CHECK (upload_method IN ('SINGLE_PUT', 'MULTIPART')),
    CONSTRAINT ck_upload_sessions_method_storage
        CHECK (
            (upload_method = 'SINGLE_PUT'
                AND upload_id IS NULL
                AND part_size_bytes IS NULL)
            OR
            (upload_method = 'MULTIPART'
                AND upload_id IS NOT NULL
                AND part_size_bytes IS NOT NULL)
        ),
    CONSTRAINT ck_upload_sessions_checksum_algorithm
        CHECK (expected_checksum_algorithm = 'SHA256'),
    CONSTRAINT ck_upload_sessions_expected_size_non_negative
        CHECK (expected_size_bytes IS NULL OR expected_size_bytes >= 0),
    CONSTRAINT ck_upload_sessions_part_size_positive
        CHECK (part_size_bytes IS NULL OR part_size_bytes > 0),
    CONSTRAINT ck_upload_sessions_expiry_after_creation
        CHECK (expires_at > created_at),
    CONSTRAINT ck_upload_sessions_completed_after_creation
        CHECK (completed_at IS NULL OR completed_at >= created_at),
    CONSTRAINT ck_upload_sessions_aborted_after_creation
        CHECK (aborted_at IS NULL OR aborted_at >= created_at)
);

CREATE INDEX idx_upload_sessions_dataset_version
    ON upload_sessions (dataset_version_id);

CREATE UNIQUE INDEX uq_upload_sessions_upload_id
    ON upload_sessions (upload_id)
    WHERE upload_id IS NOT NULL;

CREATE UNIQUE INDEX uq_upload_sessions_active_version
    ON upload_sessions (dataset_version_id)
    WHERE status IN ('INITIATED', 'UPLOADING');

CREATE UNIQUE INDEX uq_upload_sessions_completed_version
    ON upload_sessions (dataset_version_id)
    WHERE status = 'COMPLETED';

COMMENT ON TABLE upload_sessions IS
    'Individual S3 direct-upload attempt, using either a single PUT or multipart upload. A dataset version may have multiple sequential attempts, at most one active and one completed. After S3 completion is verified, the UploadSession COMPLETED transition, DatasetVersion metadata update, DatasetVersion UPLOADED transition, and OutboxEvent creation must be committed in one database transaction.';

-- -----------------------------------------------------------------------------
-- 6. models
-- -----------------------------------------------------------------------------
CREATE TABLE models (
    id          UUID         NOT NULL DEFAULT gen_random_uuid(),
    user_id     UUID         NOT NULL,
    name        VARCHAR(255) NOT NULL,
    description TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    deleted_at  TIMESTAMPTZ,

    CONSTRAINT pk_models PRIMARY KEY (id),
    CONSTRAINT fk_models_user
        FOREIGN KEY (user_id)
        REFERENCES users (id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_models_name_not_blank
        CHECK (length(btrim(name)) > 0)
);

CREATE INDEX idx_models_user
    ON models (user_id);

CREATE UNIQUE INDEX uq_models_active_user_name
    ON models (user_id, lower(btrim(name)))
    WHERE deleted_at IS NULL;

-- -----------------------------------------------------------------------------
-- 7. training_jobs
-- -----------------------------------------------------------------------------
CREATE TABLE training_jobs (
    id                    UUID         NOT NULL DEFAULT gen_random_uuid(),
    user_id               UUID         NOT NULL,
    model_id              UUID         NOT NULL,
    dataset_version_id    UUID         NOT NULL,
    target_column_id      UUID         NOT NULL,
    status                VARCHAR(32)  NOT NULL DEFAULT 'QUEUED',
    algorithm             VARCHAR(100) NOT NULL,
    hyperparameters       JSONB        NOT NULL DEFAULT '{}'::jsonb,
    requested_gpu_count   INTEGER      NOT NULL DEFAULT 1,
    idempotency_key       VARCHAR(255) NOT NULL,
    mlflow_run_id         VARCHAR(255),
    started_at            TIMESTAMPTZ,
    finished_at           TIMESTAMPTZ,
    cancel_requested_at   TIMESTAMPTZ,
    error_code            VARCHAR(100),
    error_message         TEXT,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT pk_training_jobs PRIMARY KEY (id),
    CONSTRAINT fk_training_jobs_user
        FOREIGN KEY (user_id)
        REFERENCES users (id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_training_jobs_model
        FOREIGN KEY (model_id)
        REFERENCES models (id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_training_jobs_dataset_version
        FOREIGN KEY (dataset_version_id)
        REFERENCES dataset_versions (id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_training_jobs_target_column
        FOREIGN KEY (target_column_id)
        REFERENCES dataset_columns (id)
        ON DELETE RESTRICT,
    CONSTRAINT uq_training_jobs_user_idempotency
        UNIQUE (user_id, idempotency_key),
    CONSTRAINT ck_training_jobs_status
        CHECK (status IN (
            'QUEUED', 'SCHEDULING', 'RUNNING', 'SUCCEEDED',
            'FAILED', 'CANCEL_REQUESTED', 'CANCELLED'
        )),
    CONSTRAINT ck_training_jobs_gpu_count_positive
        CHECK (requested_gpu_count > 0),
    CONSTRAINT ck_training_jobs_algorithm_not_blank
        CHECK (length(btrim(algorithm)) > 0),
    CONSTRAINT ck_training_jobs_idempotency_key_not_blank
        CHECK (length(btrim(idempotency_key)) > 0),
    CONSTRAINT ck_training_jobs_finished_requires_started
        CHECK (finished_at IS NULL OR started_at IS NOT NULL),
    CONSTRAINT ck_training_jobs_time_order
        CHECK (finished_at IS NULL OR finished_at >= started_at),
    CONSTRAINT ck_training_jobs_cancel_after_creation
        CHECK (
            cancel_requested_at IS NULL
            OR cancel_requested_at >= created_at
        )
);

CREATE INDEX idx_training_jobs_user_created
    ON training_jobs (user_id, created_at DESC);

CREATE INDEX idx_training_jobs_status_created
    ON training_jobs (status, created_at);

CREATE INDEX idx_training_jobs_model_created
    ON training_jobs (model_id, created_at DESC);

CREATE INDEX idx_training_jobs_dataset_version
    ON training_jobs (dataset_version_id);

CREATE INDEX idx_training_jobs_target_column
    ON training_jobs (target_column_id);

COMMENT ON TABLE training_jobs IS
    'Training execution. Creation requires service-layer validation that the dataset version is READY and ownership is consistent. Transition to SUCCEEDED requires at least one READY ModelVersion, one ModelInterface for each READY ModelVersion, and ModelVersion.model_id values matching TrainingJob.model_id; these cross-table invariants and the TrainingJobEvent record are enforced atomically by the service layer.';

-- -----------------------------------------------------------------------------
-- 8. training_job_events
-- -----------------------------------------------------------------------------
CREATE TABLE training_job_events (
    id               UUID         NOT NULL DEFAULT gen_random_uuid(),
    training_job_id  UUID         NOT NULL,
    event_type       VARCHAR(100) NOT NULL,
    from_status      VARCHAR(32),
    to_status        VARCHAR(32),
    message          TEXT,
    metadata_json    JSONB        NOT NULL DEFAULT '{}'::jsonb,
    occurred_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT pk_training_job_events PRIMARY KEY (id),
    CONSTRAINT fk_training_job_events_training_job
        FOREIGN KEY (training_job_id)
        REFERENCES training_jobs (id)
        ON DELETE CASCADE,
    CONSTRAINT ck_training_job_events_type_not_blank
        CHECK (length(btrim(event_type)) > 0),
    CONSTRAINT ck_training_job_events_from_status
        CHECK (
            from_status IS NULL
            OR from_status IN (
                'QUEUED', 'SCHEDULING', 'RUNNING', 'SUCCEEDED',
                'FAILED', 'CANCEL_REQUESTED', 'CANCELLED'
            )
        ),
    CONSTRAINT ck_training_job_events_to_status
        CHECK (
            to_status IS NULL
            OR to_status IN (
                'QUEUED', 'SCHEDULING', 'RUNNING', 'SUCCEEDED',
                'FAILED', 'CANCEL_REQUESTED', 'CANCELLED'
            )
        )
);

CREATE INDEX idx_training_job_events_job_occurred
    ON training_job_events (training_job_id, occurred_at, id);

-- -----------------------------------------------------------------------------
-- 9. training_checkpoints
-- -----------------------------------------------------------------------------
CREATE TABLE training_checkpoints (
    id                  UUID         NOT NULL DEFAULT gen_random_uuid(),
    training_job_id     UUID         NOT NULL,
    sequence_number     INTEGER      NOT NULL,
    epoch               BIGINT,
    step                BIGINT,
    storage_uri         TEXT         NOT NULL,
    size_bytes          BIGINT,
    checksum_algorithm  VARCHAR(16)  NOT NULL DEFAULT 'SHA256',
    checksum            VARCHAR(128),
    is_resumable        BOOLEAN      NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT pk_training_checkpoints PRIMARY KEY (id),
    CONSTRAINT fk_training_checkpoints_training_job
        FOREIGN KEY (training_job_id)
        REFERENCES training_jobs (id)
        ON DELETE CASCADE,
    CONSTRAINT uq_training_checkpoints_job_sequence
        UNIQUE (training_job_id, sequence_number),
    CONSTRAINT ck_training_checkpoints_sequence_positive
        CHECK (sequence_number > 0),
    CONSTRAINT ck_training_checkpoints_epoch_non_negative
        CHECK (epoch IS NULL OR epoch >= 0),
    CONSTRAINT ck_training_checkpoints_step_non_negative
        CHECK (step IS NULL OR step >= 0),
    CONSTRAINT ck_training_checkpoints_size_non_negative
        CHECK (size_bytes IS NULL OR size_bytes >= 0),
    CONSTRAINT ck_training_checkpoints_checksum_algorithm
        CHECK (checksum_algorithm = 'SHA256'),
    CONSTRAINT ck_training_checkpoints_storage_uri_not_blank
        CHECK (length(btrim(storage_uri)) > 0)
);

-- -----------------------------------------------------------------------------
-- 10. model_versions
-- -----------------------------------------------------------------------------
CREATE TABLE model_versions (
    id                UUID         NOT NULL DEFAULT gen_random_uuid(),
    model_id          UUID         NOT NULL,
    training_job_id   UUID         NOT NULL,
    version_number    INTEGER      NOT NULL,
    candidate_number  INTEGER      NOT NULL DEFAULT 1,
    status            VARCHAR(32)  NOT NULL DEFAULT 'CREATING',
    artifact_uri      TEXT,
    artifact_format   VARCHAR(64),
    metrics_json      JSONB        NOT NULL DEFAULT '{}'::jsonb,
    mlflow_run_id     VARCHAR(255),
    error_code        VARCHAR(100),
    error_message     TEXT,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT pk_model_versions PRIMARY KEY (id),
    CONSTRAINT fk_model_versions_model
        FOREIGN KEY (model_id)
        REFERENCES models (id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_model_versions_training_job
        FOREIGN KEY (training_job_id)
        REFERENCES training_jobs (id)
        ON DELETE RESTRICT,
    CONSTRAINT uq_model_versions_model_version
        UNIQUE (model_id, version_number),
    CONSTRAINT uq_model_versions_job_candidate
        UNIQUE (training_job_id, candidate_number),
    CONSTRAINT ck_model_versions_version_positive
        CHECK (version_number > 0),
    CONSTRAINT ck_model_versions_candidate_positive
        CHECK (candidate_number > 0),
    CONSTRAINT ck_model_versions_status
        CHECK (status IN ('CREATING', 'READY', 'FAILED', 'ARCHIVED')),
    CONSTRAINT ck_model_versions_ready_artifact
        CHECK (
            status <> 'READY'
            OR (
                artifact_uri IS NOT NULL
                AND length(btrim(artifact_uri)) > 0
                AND artifact_format IS NOT NULL
                AND length(btrim(artifact_format)) > 0
            )
        )
);

COMMENT ON TABLE model_versions IS
    'Model artifact candidate produced by a training job. model_id must equal the referenced training job model_id; enforced by the service layer.';

-- -----------------------------------------------------------------------------
-- 11. model_interfaces
-- -----------------------------------------------------------------------------
CREATE TABLE model_interfaces (
    id                  UUID        NOT NULL DEFAULT gen_random_uuid(),
    model_version_id    UUID        NOT NULL,
    input_schema_json   JSONB       NOT NULL,
    output_schema_json  JSONB       NOT NULL,
    schema_version      VARCHAR(32) NOT NULL DEFAULT '1.0',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_model_interfaces PRIMARY KEY (id),
    CONSTRAINT fk_model_interfaces_model_version
        FOREIGN KEY (model_version_id)
        REFERENCES model_versions (id)
        ON DELETE CASCADE,
    CONSTRAINT uq_model_interfaces_model_version
        UNIQUE (model_version_id),
    CONSTRAINT ck_model_interfaces_schema_version_not_blank
        CHECK (length(btrim(schema_version)) > 0)
);

-- -----------------------------------------------------------------------------
-- 12. inference_deployments
-- -----------------------------------------------------------------------------
CREATE TABLE inference_deployments (
    id                    UUID         NOT NULL DEFAULT gen_random_uuid(),
    user_id               UUID         NOT NULL,
    model_version_id      UUID         NOT NULL,
    name                  VARCHAR(255) NOT NULL,
    environment           VARCHAR(16)  NOT NULL,
    status                VARCHAR(32)  NOT NULL DEFAULT 'PENDING',
    kserve_namespace      VARCHAR(253),
    kserve_service_name   VARCHAR(253),
    endpoint              TEXT,
    min_replicas          INTEGER      NOT NULL DEFAULT 1,
    max_replicas          INTEGER      NOT NULL DEFAULT 1,
    traffic_config_json   JSONB        NOT NULL DEFAULT '{}'::jsonb,
    operation_started_at  TIMESTAMPTZ,
    applied_min_replicas  INTEGER,
    applied_max_replicas  INTEGER,
    error_code            VARCHAR(100),
    error_message         TEXT,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT pk_inference_deployments PRIMARY KEY (id),
    CONSTRAINT fk_inference_deployments_user
        FOREIGN KEY (user_id)
        REFERENCES users (id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_inference_deployments_model_version
        FOREIGN KEY (model_version_id)
        REFERENCES model_versions (id)
        ON DELETE RESTRICT,
    CONSTRAINT ck_inference_deployments_name_not_blank
        CHECK (length(btrim(name)) > 0),
    CONSTRAINT ck_inference_deployments_environment
        CHECK (environment IN ('DEVELOPMENT', 'STAGING', 'PRODUCTION')),
    CONSTRAINT ck_inference_deployments_status
        CHECK (status IN (
            'PENDING', 'DEPLOYING', 'READY', 'UPDATING',
            'FAILED', 'DELETING', 'DELETED'
        )),
    CONSTRAINT ck_inference_deployments_min_replicas
        CHECK (min_replicas >= 1),
    CONSTRAINT ck_inference_deployments_replica_range
        CHECK (max_replicas >= min_replicas),
    CONSTRAINT ck_inference_deployments_operation_started_after_creation
        CHECK (operation_started_at IS NULL OR operation_started_at >= created_at),
    CONSTRAINT ck_inference_deployments_applied_replica_range
        CHECK (
            (applied_min_replicas IS NULL AND applied_max_replicas IS NULL)
            OR (
                applied_min_replicas >= 1
                AND applied_max_replicas >= applied_min_replicas
            )
        )
);

CREATE UNIQUE INDEX uq_inference_deployments_active_user_env_name
    ON inference_deployments (
        user_id,
        environment,
        lower(btrim(name))
    )
    WHERE status <> 'DELETED';

CREATE UNIQUE INDEX uq_inference_deployments_kserve_resource
    ON inference_deployments (kserve_namespace, kserve_service_name)
    WHERE kserve_namespace IS NOT NULL
      AND kserve_service_name IS NOT NULL
      AND status <> 'DELETED';

CREATE INDEX idx_inference_deployments_model_version
    ON inference_deployments (model_version_id);

CREATE INDEX idx_inference_deployments_user_status
    ON inference_deployments (user_id, status, created_at DESC);

COMMENT ON TABLE inference_deployments IS
    'User-owned KServe deployment. user_id must match the owner of the referenced model version; enforced by the service layer.';

-- -----------------------------------------------------------------------------
-- 13. audit_logs
-- -----------------------------------------------------------------------------
CREATE TABLE audit_logs (
    id              UUID         NOT NULL DEFAULT gen_random_uuid(),
    actor_type      VARCHAR(32)  NOT NULL DEFAULT 'USER',
    actor_user_id   UUID,
    action          VARCHAR(100) NOT NULL,
    resource_type   VARCHAR(64)  NOT NULL,
    resource_id     UUID,
    request_id      VARCHAR(100),
    result          VARCHAR(32)  NOT NULL,
    error_code      VARCHAR(100),
    metadata_json   JSONB        NOT NULL DEFAULT '{}'::jsonb,
    occurred_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT pk_audit_logs PRIMARY KEY (id),
    CONSTRAINT fk_audit_logs_actor_user
        FOREIGN KEY (actor_user_id)
        REFERENCES users (id)
        ON DELETE SET NULL,
    CONSTRAINT ck_audit_logs_actor_type
        CHECK (actor_type IN ('USER', 'SYSTEM')),
    CONSTRAINT ck_audit_logs_result
        CHECK (result IN ('SUCCESS', 'FAILURE')),
    CONSTRAINT ck_audit_logs_action_not_blank
        CHECK (length(btrim(action)) > 0),
    CONSTRAINT ck_audit_logs_resource_type_not_blank
        CHECK (length(btrim(resource_type)) > 0)
);

CREATE INDEX idx_audit_logs_resource
    ON audit_logs (resource_type, resource_id, occurred_at DESC);

CREATE INDEX idx_audit_logs_actor
    ON audit_logs (actor_user_id, occurred_at DESC);

CREATE INDEX idx_audit_logs_request
    ON audit_logs (request_id)
    WHERE request_id IS NOT NULL;

COMMENT ON COLUMN audit_logs.actor_user_id IS
    'May be NULL with actor_type USER after the referenced user is physically deleted via ON DELETE SET NULL.';
COMMENT ON COLUMN audit_logs.resource_id IS
    'Polymorphic resource reference; intentionally has no foreign key.';

-- -----------------------------------------------------------------------------
-- 14. outbox_events
-- -----------------------------------------------------------------------------
CREATE TABLE outbox_events (
    id               UUID         NOT NULL DEFAULT gen_random_uuid(),
    aggregate_type   VARCHAR(64)  NOT NULL,
    aggregate_id     UUID         NOT NULL,
    event_type       VARCHAR(100) NOT NULL,
    payload_json     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key  VARCHAR(255),
    occurred_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),
    published_at     TIMESTAMPTZ,
    retry_count      INTEGER      NOT NULL DEFAULT 0,
    last_error       TEXT,
    next_attempt_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT pk_outbox_events PRIMARY KEY (id),
    CONSTRAINT ck_outbox_events_retry_count_non_negative
        CHECK (retry_count >= 0),
    CONSTRAINT ck_outbox_events_aggregate_type_not_blank
        CHECK (length(btrim(aggregate_type)) > 0),
    CONSTRAINT ck_outbox_events_event_type_not_blank
        CHECK (length(btrim(event_type)) > 0),
    CONSTRAINT ck_outbox_events_publish_time_order
        CHECK (published_at IS NULL OR published_at >= occurred_at)
);

CREATE INDEX idx_outbox_events_pending
    ON outbox_events (next_attempt_at, occurred_at)
    WHERE published_at IS NULL;

COMMENT ON COLUMN outbox_events.aggregate_id IS
    'Polymorphic aggregate reference; intentionally has no foreign key.';
COMMENT ON TABLE outbox_events IS
    'Transactional outbox. Published rows are retained for 30 days; unpublished rows are not automatically deleted.';

COMMIT;
