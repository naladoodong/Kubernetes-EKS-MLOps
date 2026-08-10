"""Create the ArgMax Mini initial PostgreSQL schema.

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-08-06

The DDL is intentionally SQL-first and mirrors schema-v2.sql. Alembic owns
transaction boundaries, so the source file's outer BEGIN/COMMIT statements are
not included here.
"""

from collections.abc import Sequence

from alembic import op


# Revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMA_STATEMENTS: tuple[str, ...] = (
    '-- ArgMax Mini PostgreSQL schema\n-- Source of truth: data-model-v5.md and state-transitions-v4.md\n-- Revision: schema-v2.sql\n-- PostgreSQL 14+\n\nCREATE EXTENSION IF NOT EXISTS pgcrypto',

    '-- -----------------------------------------------------------------------------\n-- 1. users\n-- -----------------------------------------------------------------------------\nCREATE TABLE users (\n    id          UUID         NOT NULL DEFAULT gen_random_uuid(),\n    email       VARCHAR(320) NOT NULL,\n    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),\n\n    CONSTRAINT pk_users PRIMARY KEY (id),\n    CONSTRAINT ck_users_email_not_blank\n        CHECK (length(btrim(email)) > 0)\n)',

    'CREATE UNIQUE INDEX uq_users_email_ci\n    ON users (lower(btrim(email)))',

    "COMMENT ON TABLE users IS\n    'Resource ownership root. Authentication implementation is outside the current scope.'",

    '-- -----------------------------------------------------------------------------\n-- 2. datasets\n-- -----------------------------------------------------------------------------\nCREATE TABLE datasets (\n    id          UUID         NOT NULL DEFAULT gen_random_uuid(),\n    user_id     UUID         NOT NULL,\n    name        VARCHAR(255) NOT NULL,\n    description TEXT,\n    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),\n    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),\n    deleted_at  TIMESTAMPTZ,\n\n    CONSTRAINT pk_datasets PRIMARY KEY (id),\n    CONSTRAINT fk_datasets_user\n        FOREIGN KEY (user_id)\n        REFERENCES users (id)\n        ON DELETE RESTRICT,\n    CONSTRAINT ck_datasets_name_not_blank\n        CHECK (length(btrim(name)) > 0)\n)',

    'CREATE UNIQUE INDEX uq_datasets_active_user_name\n    ON datasets (user_id, lower(btrim(name)))\n    WHERE deleted_at IS NULL',

    "COMMENT ON TABLE datasets IS\n    'Logical dataset container. File metadata and processing status belong to dataset_versions.'",

    "-- -----------------------------------------------------------------------------\n-- 3. dataset_versions\n-- -----------------------------------------------------------------------------\nCREATE TABLE dataset_versions (\n    id                      UUID         NOT NULL DEFAULT gen_random_uuid(),\n    dataset_id              UUID         NOT NULL,\n    version_number          INTEGER      NOT NULL,\n    original_filename       VARCHAR(512) NOT NULL,\n    file_format             VARCHAR(16)  NOT NULL,\n    mime_type               VARCHAR(255),\n    size_bytes              BIGINT,\n    original_storage_uri    TEXT,\n    processed_storage_uri   TEXT,\n    checksum_algorithm      VARCHAR(16)  NOT NULL DEFAULT 'SHA256',\n    checksum                VARCHAR(128),\n    row_count               BIGINT,\n    column_count            INTEGER,\n    status                  VARCHAR(32)  NOT NULL DEFAULT 'PENDING',\n    error_code              VARCHAR(100),\n    error_message           TEXT,\n    processing_started_at   TIMESTAMPTZ,\n    processing_finished_at  TIMESTAMPTZ,\n    created_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),\n    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),\n\n    CONSTRAINT pk_dataset_versions PRIMARY KEY (id),\n    CONSTRAINT fk_dataset_versions_dataset\n        FOREIGN KEY (dataset_id)\n        REFERENCES datasets (id)\n        ON DELETE CASCADE,\n    CONSTRAINT uq_dataset_versions_dataset_version\n        UNIQUE (dataset_id, version_number),\n    CONSTRAINT ck_dataset_versions_filename_not_blank\n        CHECK (length(btrim(original_filename)) > 0),\n    CONSTRAINT ck_dataset_versions_version_number_positive\n        CHECK (version_number > 0),\n    CONSTRAINT ck_dataset_versions_file_format\n        CHECK (file_format IN ('CSV', 'XLSX')),\n    CONSTRAINT ck_dataset_versions_checksum_algorithm\n        CHECK (checksum_algorithm = 'SHA256'),\n    CONSTRAINT ck_dataset_versions_size_non_negative\n        CHECK (size_bytes IS NULL OR size_bytes >= 0),\n    CONSTRAINT ck_dataset_versions_row_count_non_negative\n        CHECK (row_count IS NULL OR row_count >= 0),\n    CONSTRAINT ck_dataset_versions_column_count_non_negative\n        CHECK (column_count IS NULL OR column_count >= 0),\n    CONSTRAINT ck_dataset_versions_status\n        CHECK (status IN (\n            'PENDING', 'UPLOADING', 'UPLOADED',\n            'PROCESSING', 'READY', 'FAILED'\n        )),\n    CONSTRAINT ck_dataset_versions_finished_requires_started\n        CHECK (\n            processing_finished_at IS NULL\n            OR processing_started_at IS NOT NULL\n        ),\n    CONSTRAINT ck_dataset_versions_processing_time_order\n        CHECK (\n            processing_finished_at IS NULL\n            OR processing_finished_at >= processing_started_at\n        )\n)",

    'CREATE INDEX idx_dataset_versions_dataset_status_version\n    ON dataset_versions (dataset_id, status, version_number DESC)',

    'CREATE INDEX idx_dataset_versions_status_created\n    ON dataset_versions (status, created_at)',

    "COMMENT ON COLUMN dataset_versions.file_format IS\n    'Original user-uploaded file format. Processed internal format is represented by processed_storage_uri.'",

    "COMMENT ON TABLE dataset_versions IS\n    'Immutable uploaded file version and its processing metadata.'",

    "-- -----------------------------------------------------------------------------\n-- 4. dataset_columns\n-- -----------------------------------------------------------------------------\nCREATE TABLE dataset_columns (\n    id                  UUID         NOT NULL DEFAULT gen_random_uuid(),\n    dataset_version_id  UUID         NOT NULL,\n    name                VARCHAR(255) NOT NULL,\n    ordinal_position    INTEGER      NOT NULL,\n    data_type           VARCHAR(32)  NOT NULL,\n    physical_type       VARCHAR(64),\n    is_nullable         BOOLEAN      NOT NULL DEFAULT false,\n    null_count          BIGINT       NOT NULL DEFAULT 0,\n    distinct_count      BIGINT,\n    statistics_json     JSONB        NOT NULL DEFAULT '{}'::jsonb,\n    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),\n\n    CONSTRAINT pk_dataset_columns PRIMARY KEY (id),\n    CONSTRAINT fk_dataset_columns_dataset_version\n        FOREIGN KEY (dataset_version_id)\n        REFERENCES dataset_versions (id)\n        ON DELETE CASCADE,\n    CONSTRAINT uq_dataset_columns_version_ordinal\n        UNIQUE (dataset_version_id, ordinal_position),\n    CONSTRAINT ck_dataset_columns_name_not_blank\n        CHECK (length(btrim(name)) > 0),\n    CONSTRAINT ck_dataset_columns_ordinal_positive\n        CHECK (ordinal_position > 0),\n    CONSTRAINT ck_dataset_columns_null_count_non_negative\n        CHECK (null_count >= 0),\n    CONSTRAINT ck_dataset_columns_distinct_count_non_negative\n        CHECK (distinct_count IS NULL OR distinct_count >= 0),\n    CONSTRAINT ck_dataset_columns_data_type\n        CHECK (data_type IN (\n            'STRING', 'INTEGER', 'FLOAT', 'BOOLEAN',\n            'DATE', 'DATETIME', 'CATEGORY', 'UNKNOWN'\n        ))\n)",

    'CREATE UNIQUE INDEX uq_dataset_columns_version_name_ci\n    ON dataset_columns (dataset_version_id, lower(btrim(name)))',

    "-- -----------------------------------------------------------------------------\n-- 5. upload_sessions\n-- -----------------------------------------------------------------------------\nCREATE TABLE upload_sessions (\n    id                           UUID         NOT NULL DEFAULT gen_random_uuid(),\n    dataset_version_id           UUID         NOT NULL,\n    status                       VARCHAR(32)  NOT NULL DEFAULT 'INITIATED',\n    storage_key                  TEXT         NOT NULL,\n    upload_method                VARCHAR(16)  NOT NULL,\n    upload_id                    TEXT,\n    expected_size_bytes          BIGINT,\n    expected_checksum_algorithm  VARCHAR(16)  NOT NULL DEFAULT 'SHA256',\n    expected_checksum            VARCHAR(128),\n    part_size_bytes              INTEGER,\n    expires_at                   TIMESTAMPTZ  NOT NULL,\n    completed_at                 TIMESTAMPTZ,\n    aborted_at                   TIMESTAMPTZ,\n    error_code                   VARCHAR(100),\n    error_message                TEXT,\n    created_at                   TIMESTAMPTZ  NOT NULL DEFAULT now(),\n    updated_at                   TIMESTAMPTZ  NOT NULL DEFAULT now(),\n\n    CONSTRAINT pk_upload_sessions PRIMARY KEY (id),\n    CONSTRAINT fk_upload_sessions_dataset_version\n        FOREIGN KEY (dataset_version_id)\n        REFERENCES dataset_versions (id)\n        ON DELETE CASCADE,\n    CONSTRAINT ck_upload_sessions_storage_key_not_blank\n        CHECK (length(btrim(storage_key)) > 0),\n    CONSTRAINT ck_upload_sessions_status\n        CHECK (status IN (\n            'INITIATED', 'UPLOADING', 'COMPLETED',\n            'ABORTED', 'EXPIRED', 'FAILED'\n        )),\n    CONSTRAINT ck_upload_sessions_upload_method\n        CHECK (upload_method IN ('SINGLE_PUT', 'MULTIPART')),\n    CONSTRAINT ck_upload_sessions_method_storage\n        CHECK (\n            (upload_method = 'SINGLE_PUT'\n                AND upload_id IS NULL\n                AND part_size_bytes IS NULL)\n            OR\n            (upload_method = 'MULTIPART'\n                AND upload_id IS NOT NULL\n                AND part_size_bytes IS NOT NULL)\n        ),\n    CONSTRAINT ck_upload_sessions_checksum_algorithm\n        CHECK (expected_checksum_algorithm = 'SHA256'),\n    CONSTRAINT ck_upload_sessions_expected_size_non_negative\n        CHECK (expected_size_bytes IS NULL OR expected_size_bytes >= 0),\n    CONSTRAINT ck_upload_sessions_part_size_positive\n        CHECK (part_size_bytes IS NULL OR part_size_bytes > 0),\n    CONSTRAINT ck_upload_sessions_expiry_after_creation\n        CHECK (expires_at > created_at),\n    CONSTRAINT ck_upload_sessions_completed_after_creation\n        CHECK (completed_at IS NULL OR completed_at >= created_at),\n    CONSTRAINT ck_upload_sessions_aborted_after_creation\n        CHECK (aborted_at IS NULL OR aborted_at >= created_at)\n)",

    'CREATE INDEX idx_upload_sessions_dataset_version\n    ON upload_sessions (dataset_version_id)',

    'CREATE UNIQUE INDEX uq_upload_sessions_upload_id\n    ON upload_sessions (upload_id)\n    WHERE upload_id IS NOT NULL',

    "CREATE UNIQUE INDEX uq_upload_sessions_active_version\n    ON upload_sessions (dataset_version_id)\n    WHERE status IN ('INITIATED', 'UPLOADING')",

    "CREATE UNIQUE INDEX uq_upload_sessions_completed_version\n    ON upload_sessions (dataset_version_id)\n    WHERE status = 'COMPLETED'",

    "COMMENT ON TABLE upload_sessions IS\n    'Individual S3 direct-upload attempt, using either a single PUT or multipart upload. A dataset version may have multiple sequential attempts, at most one active and one completed. After S3 completion is verified, the UploadSession COMPLETED transition, DatasetVersion metadata update, DatasetVersion UPLOADED transition, and OutboxEvent creation must be committed in one database transaction.'",

    '-- -----------------------------------------------------------------------------\n-- 6. models\n-- -----------------------------------------------------------------------------\nCREATE TABLE models (\n    id          UUID         NOT NULL DEFAULT gen_random_uuid(),\n    user_id     UUID         NOT NULL,\n    name        VARCHAR(255) NOT NULL,\n    description TEXT,\n    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),\n    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),\n    deleted_at  TIMESTAMPTZ,\n\n    CONSTRAINT pk_models PRIMARY KEY (id),\n    CONSTRAINT fk_models_user\n        FOREIGN KEY (user_id)\n        REFERENCES users (id)\n        ON DELETE RESTRICT,\n    CONSTRAINT ck_models_name_not_blank\n        CHECK (length(btrim(name)) > 0)\n)',

    'CREATE INDEX idx_models_user\n    ON models (user_id)',

    'CREATE UNIQUE INDEX uq_models_active_user_name\n    ON models (user_id, lower(btrim(name)))\n    WHERE deleted_at IS NULL',

    "-- -----------------------------------------------------------------------------\n-- 7. training_jobs\n-- -----------------------------------------------------------------------------\nCREATE TABLE training_jobs (\n    id                    UUID         NOT NULL DEFAULT gen_random_uuid(),\n    user_id               UUID         NOT NULL,\n    model_id              UUID         NOT NULL,\n    dataset_version_id    UUID         NOT NULL,\n    status                VARCHAR(32)  NOT NULL DEFAULT 'QUEUED',\n    algorithm             VARCHAR(100) NOT NULL,\n    hyperparameters       JSONB        NOT NULL DEFAULT '{}'::jsonb,\n    requested_gpu_count   INTEGER      NOT NULL DEFAULT 1,\n    idempotency_key       VARCHAR(255) NOT NULL,\n    mlflow_run_id         VARCHAR(255),\n    started_at            TIMESTAMPTZ,\n    finished_at           TIMESTAMPTZ,\n    cancel_requested_at   TIMESTAMPTZ,\n    error_code            VARCHAR(100),\n    error_message         TEXT,\n    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),\n    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),\n\n    CONSTRAINT pk_training_jobs PRIMARY KEY (id),\n    CONSTRAINT fk_training_jobs_user\n        FOREIGN KEY (user_id)\n        REFERENCES users (id)\n        ON DELETE RESTRICT,\n    CONSTRAINT fk_training_jobs_model\n        FOREIGN KEY (model_id)\n        REFERENCES models (id)\n        ON DELETE RESTRICT,\n    CONSTRAINT fk_training_jobs_dataset_version\n        FOREIGN KEY (dataset_version_id)\n        REFERENCES dataset_versions (id)\n        ON DELETE RESTRICT,\n    CONSTRAINT uq_training_jobs_user_idempotency\n        UNIQUE (user_id, idempotency_key),\n    CONSTRAINT ck_training_jobs_status\n        CHECK (status IN (\n            'QUEUED', 'SCHEDULING', 'RUNNING', 'SUCCEEDED',\n            'FAILED', 'CANCEL_REQUESTED', 'CANCELLED'\n        )),\n    CONSTRAINT ck_training_jobs_gpu_count_positive\n        CHECK (requested_gpu_count > 0),\n    CONSTRAINT ck_training_jobs_algorithm_not_blank\n        CHECK (length(btrim(algorithm)) > 0),\n    CONSTRAINT ck_training_jobs_idempotency_key_not_blank\n        CHECK (length(btrim(idempotency_key)) > 0),\n    CONSTRAINT ck_training_jobs_finished_requires_started\n        CHECK (finished_at IS NULL OR started_at IS NOT NULL),\n    CONSTRAINT ck_training_jobs_time_order\n        CHECK (finished_at IS NULL OR finished_at >= started_at),\n    CONSTRAINT ck_training_jobs_cancel_after_creation\n        CHECK (\n            cancel_requested_at IS NULL\n            OR cancel_requested_at >= created_at\n        )\n)",

    'CREATE INDEX idx_training_jobs_user_created\n    ON training_jobs (user_id, created_at DESC)',

    'CREATE INDEX idx_training_jobs_status_created\n    ON training_jobs (status, created_at)',

    'CREATE INDEX idx_training_jobs_model_created\n    ON training_jobs (model_id, created_at DESC)',

    'CREATE INDEX idx_training_jobs_dataset_version\n    ON training_jobs (dataset_version_id)',

    "COMMENT ON TABLE training_jobs IS\n    'Training execution. Creation requires service-layer validation that the dataset version is READY and ownership is consistent. Transition to SUCCEEDED requires at least one READY ModelVersion, one ModelInterface for each READY ModelVersion, and ModelVersion.model_id values matching TrainingJob.model_id; these cross-table invariants and the TrainingJobEvent record are enforced atomically by the service layer.'",

    "-- -----------------------------------------------------------------------------\n-- 8. training_job_events\n-- -----------------------------------------------------------------------------\nCREATE TABLE training_job_events (\n    id               UUID         NOT NULL DEFAULT gen_random_uuid(),\n    training_job_id  UUID         NOT NULL,\n    event_type       VARCHAR(100) NOT NULL,\n    from_status      VARCHAR(32),\n    to_status        VARCHAR(32),\n    message          TEXT,\n    metadata_json    JSONB        NOT NULL DEFAULT '{}'::jsonb,\n    occurred_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),\n\n    CONSTRAINT pk_training_job_events PRIMARY KEY (id),\n    CONSTRAINT fk_training_job_events_training_job\n        FOREIGN KEY (training_job_id)\n        REFERENCES training_jobs (id)\n        ON DELETE CASCADE,\n    CONSTRAINT ck_training_job_events_type_not_blank\n        CHECK (length(btrim(event_type)) > 0),\n    CONSTRAINT ck_training_job_events_from_status\n        CHECK (\n            from_status IS NULL\n            OR from_status IN (\n                'QUEUED', 'SCHEDULING', 'RUNNING', 'SUCCEEDED',\n                'FAILED', 'CANCEL_REQUESTED', 'CANCELLED'\n            )\n        ),\n    CONSTRAINT ck_training_job_events_to_status\n        CHECK (\n            to_status IS NULL\n            OR to_status IN (\n                'QUEUED', 'SCHEDULING', 'RUNNING', 'SUCCEEDED',\n                'FAILED', 'CANCEL_REQUESTED', 'CANCELLED'\n            )\n        )\n)",

    'CREATE INDEX idx_training_job_events_job_occurred\n    ON training_job_events (training_job_id, occurred_at, id)',

    "-- -----------------------------------------------------------------------------\n-- 9. training_checkpoints\n-- -----------------------------------------------------------------------------\nCREATE TABLE training_checkpoints (\n    id                  UUID         NOT NULL DEFAULT gen_random_uuid(),\n    training_job_id     UUID         NOT NULL,\n    sequence_number     INTEGER      NOT NULL,\n    epoch               BIGINT,\n    step                BIGINT,\n    storage_uri         TEXT         NOT NULL,\n    size_bytes          BIGINT,\n    checksum_algorithm  VARCHAR(16)  NOT NULL DEFAULT 'SHA256',\n    checksum            VARCHAR(128),\n    is_resumable        BOOLEAN      NOT NULL DEFAULT true,\n    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),\n\n    CONSTRAINT pk_training_checkpoints PRIMARY KEY (id),\n    CONSTRAINT fk_training_checkpoints_training_job\n        FOREIGN KEY (training_job_id)\n        REFERENCES training_jobs (id)\n        ON DELETE CASCADE,\n    CONSTRAINT uq_training_checkpoints_job_sequence\n        UNIQUE (training_job_id, sequence_number),\n    CONSTRAINT ck_training_checkpoints_sequence_positive\n        CHECK (sequence_number > 0),\n    CONSTRAINT ck_training_checkpoints_epoch_non_negative\n        CHECK (epoch IS NULL OR epoch >= 0),\n    CONSTRAINT ck_training_checkpoints_step_non_negative\n        CHECK (step IS NULL OR step >= 0),\n    CONSTRAINT ck_training_checkpoints_size_non_negative\n        CHECK (size_bytes IS NULL OR size_bytes >= 0),\n    CONSTRAINT ck_training_checkpoints_checksum_algorithm\n        CHECK (checksum_algorithm = 'SHA256'),\n    CONSTRAINT ck_training_checkpoints_storage_uri_not_blank\n        CHECK (length(btrim(storage_uri)) > 0)\n)",

    "-- -----------------------------------------------------------------------------\n-- 10. model_versions\n-- -----------------------------------------------------------------------------\nCREATE TABLE model_versions (\n    id                UUID         NOT NULL DEFAULT gen_random_uuid(),\n    model_id          UUID         NOT NULL,\n    training_job_id   UUID         NOT NULL,\n    version_number    INTEGER      NOT NULL,\n    candidate_number  INTEGER      NOT NULL DEFAULT 1,\n    status            VARCHAR(32)  NOT NULL DEFAULT 'CREATING',\n    artifact_uri      TEXT,\n    artifact_format   VARCHAR(64),\n    metrics_json      JSONB        NOT NULL DEFAULT '{}'::jsonb,\n    mlflow_run_id     VARCHAR(255),\n    error_code        VARCHAR(100),\n    error_message     TEXT,\n    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),\n    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),\n\n    CONSTRAINT pk_model_versions PRIMARY KEY (id),\n    CONSTRAINT fk_model_versions_model\n        FOREIGN KEY (model_id)\n        REFERENCES models (id)\n        ON DELETE RESTRICT,\n    CONSTRAINT fk_model_versions_training_job\n        FOREIGN KEY (training_job_id)\n        REFERENCES training_jobs (id)\n        ON DELETE RESTRICT,\n    CONSTRAINT uq_model_versions_model_version\n        UNIQUE (model_id, version_number),\n    CONSTRAINT uq_model_versions_job_candidate\n        UNIQUE (training_job_id, candidate_number),\n    CONSTRAINT ck_model_versions_version_positive\n        CHECK (version_number > 0),\n    CONSTRAINT ck_model_versions_candidate_positive\n        CHECK (candidate_number > 0),\n    CONSTRAINT ck_model_versions_status\n        CHECK (status IN ('CREATING', 'READY', 'FAILED', 'ARCHIVED')),\n    CONSTRAINT ck_model_versions_ready_artifact\n        CHECK (\n            status <> 'READY'\n            OR (\n                artifact_uri IS NOT NULL\n                AND length(btrim(artifact_uri)) > 0\n                AND artifact_format IS NOT NULL\n                AND length(btrim(artifact_format)) > 0\n            )\n        )\n)",

    "COMMENT ON TABLE model_versions IS\n    'Model artifact candidate produced by a training job. model_id must equal the referenced training job model_id; enforced by the service layer.'",

    "-- -----------------------------------------------------------------------------\n-- 11. model_interfaces\n-- -----------------------------------------------------------------------------\nCREATE TABLE model_interfaces (\n    id                  UUID        NOT NULL DEFAULT gen_random_uuid(),\n    model_version_id    UUID        NOT NULL,\n    input_schema_json   JSONB       NOT NULL,\n    output_schema_json  JSONB       NOT NULL,\n    schema_version      VARCHAR(32) NOT NULL DEFAULT '1.0',\n    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),\n\n    CONSTRAINT pk_model_interfaces PRIMARY KEY (id),\n    CONSTRAINT fk_model_interfaces_model_version\n        FOREIGN KEY (model_version_id)\n        REFERENCES model_versions (id)\n        ON DELETE CASCADE,\n    CONSTRAINT uq_model_interfaces_model_version\n        UNIQUE (model_version_id),\n    CONSTRAINT ck_model_interfaces_schema_version_not_blank\n        CHECK (length(btrim(schema_version)) > 0)\n)",

    "-- -----------------------------------------------------------------------------\n-- 12. inference_deployments\n-- -----------------------------------------------------------------------------\nCREATE TABLE inference_deployments (\n    id                    UUID         NOT NULL DEFAULT gen_random_uuid(),\n    user_id               UUID         NOT NULL,\n    model_version_id      UUID         NOT NULL,\n    name                  VARCHAR(255) NOT NULL,\n    environment           VARCHAR(16)  NOT NULL,\n    status                VARCHAR(32)  NOT NULL DEFAULT 'PENDING',\n    kserve_namespace      VARCHAR(253),\n    kserve_service_name   VARCHAR(253),\n    endpoint              TEXT,\n    min_replicas          INTEGER      NOT NULL DEFAULT 1,\n    max_replicas          INTEGER      NOT NULL DEFAULT 1,\n    traffic_config_json   JSONB        NOT NULL DEFAULT '{}'::jsonb,\n    error_code            VARCHAR(100),\n    error_message         TEXT,\n    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),\n    updated_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),\n\n    CONSTRAINT pk_inference_deployments PRIMARY KEY (id),\n    CONSTRAINT fk_inference_deployments_user\n        FOREIGN KEY (user_id)\n        REFERENCES users (id)\n        ON DELETE RESTRICT,\n    CONSTRAINT fk_inference_deployments_model_version\n        FOREIGN KEY (model_version_id)\n        REFERENCES model_versions (id)\n        ON DELETE RESTRICT,\n    CONSTRAINT ck_inference_deployments_name_not_blank\n        CHECK (length(btrim(name)) > 0),\n    CONSTRAINT ck_inference_deployments_environment\n        CHECK (environment IN ('DEVELOPMENT', 'STAGING', 'PRODUCTION')),\n    CONSTRAINT ck_inference_deployments_status\n        CHECK (status IN (\n            'PENDING', 'DEPLOYING', 'READY', 'UPDATING',\n            'FAILED', 'DELETING', 'DELETED'\n        )),\n    CONSTRAINT ck_inference_deployments_min_replicas\n        CHECK (min_replicas >= 1),\n    CONSTRAINT ck_inference_deployments_replica_range\n        CHECK (max_replicas >= min_replicas)\n)",

    "CREATE UNIQUE INDEX uq_inference_deployments_active_user_env_name\n    ON inference_deployments (\n        user_id,\n        environment,\n        lower(btrim(name))\n    )\n    WHERE status <> 'DELETED'",

    "CREATE UNIQUE INDEX uq_inference_deployments_kserve_resource\n    ON inference_deployments (kserve_namespace, kserve_service_name)\n    WHERE kserve_namespace IS NOT NULL\n      AND kserve_service_name IS NOT NULL\n      AND status <> 'DELETED'",

    'CREATE INDEX idx_inference_deployments_model_version\n    ON inference_deployments (model_version_id)',

    'CREATE INDEX idx_inference_deployments_user_status\n    ON inference_deployments (user_id, status, created_at DESC)',

    "COMMENT ON TABLE inference_deployments IS\n    'User-owned KServe deployment. user_id must match the owner of the referenced model version; enforced by the service layer.'",

    "-- -----------------------------------------------------------------------------\n-- 13. audit_logs\n-- -----------------------------------------------------------------------------\nCREATE TABLE audit_logs (\n    id              UUID         NOT NULL DEFAULT gen_random_uuid(),\n    actor_type      VARCHAR(32)  NOT NULL DEFAULT 'USER',\n    actor_user_id   UUID,\n    action          VARCHAR(100) NOT NULL,\n    resource_type   VARCHAR(64)  NOT NULL,\n    resource_id     UUID,\n    request_id      VARCHAR(100),\n    result          VARCHAR(32)  NOT NULL,\n    error_code      VARCHAR(100),\n    metadata_json   JSONB        NOT NULL DEFAULT '{}'::jsonb,\n    occurred_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),\n\n    CONSTRAINT pk_audit_logs PRIMARY KEY (id),\n    CONSTRAINT fk_audit_logs_actor_user\n        FOREIGN KEY (actor_user_id)\n        REFERENCES users (id)\n        ON DELETE SET NULL,\n    CONSTRAINT ck_audit_logs_actor_type\n        CHECK (actor_type IN ('USER', 'SYSTEM')),\n    CONSTRAINT ck_audit_logs_result\n        CHECK (result IN ('SUCCESS', 'FAILURE')),\n    CONSTRAINT ck_audit_logs_action_not_blank\n        CHECK (length(btrim(action)) > 0),\n    CONSTRAINT ck_audit_logs_resource_type_not_blank\n        CHECK (length(btrim(resource_type)) > 0)\n)",

    'CREATE INDEX idx_audit_logs_resource\n    ON audit_logs (resource_type, resource_id, occurred_at DESC)',

    'CREATE INDEX idx_audit_logs_actor\n    ON audit_logs (actor_user_id, occurred_at DESC)',

    'CREATE INDEX idx_audit_logs_request\n    ON audit_logs (request_id)\n    WHERE request_id IS NOT NULL',

    "COMMENT ON COLUMN audit_logs.actor_user_id IS\n    'May be NULL with actor_type USER after the referenced user is physically deleted via ON DELETE SET NULL.'",

    "COMMENT ON COLUMN audit_logs.resource_id IS\n    'Polymorphic resource reference; intentionally has no foreign key.'",

    "-- -----------------------------------------------------------------------------\n-- 14. outbox_events\n-- -----------------------------------------------------------------------------\nCREATE TABLE outbox_events (\n    id               UUID         NOT NULL DEFAULT gen_random_uuid(),\n    aggregate_type   VARCHAR(64)  NOT NULL,\n    aggregate_id     UUID         NOT NULL,\n    event_type       VARCHAR(100) NOT NULL,\n    payload_json     JSONB        NOT NULL DEFAULT '{}'::jsonb,\n    idempotency_key  VARCHAR(255),\n    occurred_at      TIMESTAMPTZ  NOT NULL DEFAULT now(),\n    published_at     TIMESTAMPTZ,\n    retry_count      INTEGER      NOT NULL DEFAULT 0,\n    last_error       TEXT,\n    next_attempt_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),\n\n    CONSTRAINT pk_outbox_events PRIMARY KEY (id),\n    CONSTRAINT ck_outbox_events_retry_count_non_negative\n        CHECK (retry_count >= 0),\n    CONSTRAINT ck_outbox_events_aggregate_type_not_blank\n        CHECK (length(btrim(aggregate_type)) > 0),\n    CONSTRAINT ck_outbox_events_event_type_not_blank\n        CHECK (length(btrim(event_type)) > 0),\n    CONSTRAINT ck_outbox_events_publish_time_order\n        CHECK (published_at IS NULL OR published_at >= occurred_at)\n)",

    'CREATE INDEX idx_outbox_events_pending\n    ON outbox_events (next_attempt_at, occurred_at)\n    WHERE published_at IS NULL',

    "COMMENT ON COLUMN outbox_events.aggregate_id IS\n    'Polymorphic aggregate reference; intentionally has no foreign key.'",

    "COMMENT ON TABLE outbox_events IS\n    'Transactional outbox. Published rows are retained for 30 days; unpublished rows are not automatically deleted.'",
)


def upgrade() -> None:
    """Create all ArgMax Mini tables, constraints, indexes, and comments."""
    # Execute statements individually for DBAPI compatibility and Alembic's
    # online and offline SQL-generation modes.
    for statement in SCHEMA_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    """Drop all application tables in reverse dependency order."""
    # pgcrypto is intentionally retained because extensions may be shared by
    # other schemas or applications in the same database.
    op.execute("DROP TABLE IF EXISTS outbox_events")
    op.execute("DROP TABLE IF EXISTS audit_logs")
    op.execute("DROP TABLE IF EXISTS inference_deployments")
    op.execute("DROP TABLE IF EXISTS model_interfaces")
    op.execute("DROP TABLE IF EXISTS model_versions")
    op.execute("DROP TABLE IF EXISTS training_checkpoints")
    op.execute("DROP TABLE IF EXISTS training_job_events")
    op.execute("DROP TABLE IF EXISTS training_jobs")
    op.execute("DROP TABLE IF EXISTS models")
    op.execute("DROP TABLE IF EXISTS upload_sessions")
    op.execute("DROP TABLE IF EXISTS dataset_columns")
    op.execute("DROP TABLE IF EXISTS dataset_versions")
    op.execute("DROP TABLE IF EXISTS datasets")
    op.execute("DROP TABLE IF EXISTS users")
