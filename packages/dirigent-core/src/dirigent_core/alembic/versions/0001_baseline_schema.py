"""The whole schema, as one revision.

There were eight: a baseline, and then a migration for each thing that changed after it --
a sealed webhook secret, an idempotency key, a waiting status, a step order, one name for a
row's age. Nothing had shipped, so none of them had a database to move forward, and each was
a place where an ALTER behaves differently from the CREATE that would have said the same
thing. One of them proved it: SQLite accepts a CURRENT_TIMESTAMP default on an empty table
and refuses it on one with rows, so a column added by ALTER broke a development instance
that a test on a fresh database could never have caught.

This is what those eight amounted to. What proves it faithful is not this file but
``test_the_migrations_leave_no_drift_against_the_models_on_sqlite`` and its PostgreSQL twin,
which compare a migrated database against the models.

Revision ID: 0001_baseline
Revises: nothing
Create Date: 2026-08-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

import dirigent_core.types

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create every table, index and constraint the models declare."""
    op.create_table(
        "connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("kind", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=False),
        sa.Column("secret_envelope", sa.LargeBinary(), nullable=True),
        sa.Column("secret_key_id", sa.String(length=100), nullable=True),
        sa.Column("last_check_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("last_check_healthy", sa.Boolean(), nullable=True),
        sa.Column("last_check_detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_connections")),
        sa.UniqueConstraint("code", name=op.f("uq_connections_code")),
    )
    with op.batch_alter_table("connections", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_connections_kind"), ["kind"], unique=False)

    op.create_table(
        "schemas",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("body", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=False),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schemas")),
        sa.UniqueConstraint("code", name=op.f("uq_schemas_code")),
    )

    op.create_table(
        "pipelines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipelines")),
        sa.UniqueConstraint("code", name=op.f("uq_pipelines_code")),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("admin", "operator", "viewer", name="user_role", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("last_login_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "workers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("hostname", sa.String(length=255), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column(
            "plugins", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=False
        ),
        sa.Column("tags", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=False),
        sa.Column("concurrency", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("starting", "running", "draining", "stopped", name="worker_status", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("catalog_digest", sa.String(length=71), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workers")),
        sa.UniqueConstraint("name", name=op.f("uq_workers_name")),
    )
    with op.batch_alter_table("workers", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_workers_last_seen_at"), ["last_seen_at"], unique=False)

    op.create_table(
        "alert_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "event",
            sa.Enum(
                "run_failed",
                "run_completed_with_errors",
                "run_succeeded",
                "run_stuck",
                name="alert_event",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "scope", sa.Enum("global", "pipeline", name="alert_scope", native_enum=False, length=32), nullable=False
        ),
        sa.Column("pipeline_id", sa.Uuid(), nullable=True),
        sa.Column("notifier", sa.String(length=100), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=True),
        sa.Column("template", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("throttle_seconds", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("paused", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("last_sent_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connections.id"],
            name=op.f("fk_alert_rules_connection_id_connections"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_id"], ["pipelines.id"], name=op.f("fk_alert_rules_pipeline_id_pipelines"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alert_rules")),
        sa.UniqueConstraint("code", name=op.f("uq_alert_rules_code")),
    )
    with op.batch_alter_table("alert_rules", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_alert_rules_event"), ["event"], unique=False)
        batch_op.create_index(batch_op.f("ix_alert_rules_pipeline_id"), ["pipeline_id"], unique=False)

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.Enum("api", "session", name="token_kind", native_enum=False, length=32), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("prefix", sa.String(length=16), nullable=False),
        sa.Column("expires_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_api_tokens_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_tokens_token_hash")),
    )
    with op.batch_alter_table("api_tokens", schema=None) as batch_op:
        batch_op.create_index("ix_api_tokens_user_id_kind", ["user_id", "kind"], unique=False)

    op.create_table(
        "pipeline_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "document", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=False
        ),
        sa.Column(
            "step_order", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=False
        ),
        sa.Column("digest", sa.String(length=71), nullable=False),
        sa.Column(
            "provenance_source",
            sa.Enum("ui", "file", "url", "api", name="provenance_source", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("provenance_ref", sa.Text(), nullable=True),
        sa.Column("applied_by", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_id"],
            ["pipelines.id"],
            name=op.f("fk_pipeline_versions_pipeline_id_pipelines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_versions")),
        sa.UniqueConstraint("pipeline_id", "version", name=op.f("uq_pipeline_versions_pipeline_id_version")),
    )
    with op.batch_alter_table("pipeline_versions", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_pipeline_versions_digest"), ["digest"], unique=False)
        batch_op.create_index(batch_op.f("ix_pipeline_versions_pipeline_id"), ["pipeline_id"], unique=False)

    op.create_table(
        "trigger_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column(
            "document", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=False
        ),
        sa.Column("digest", sa.String(length=71), nullable=False),
        sa.Column(
            "provenance_source",
            sa.Enum("ui", "file", "url", "api", "directory", name="provenance_source", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("provenance_ref", sa.Text(), nullable=True),
        sa.Column("applied_by", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_id"],
            ["pipelines.id"],
            name=op.f("fk_trigger_documents_pipeline_id_pipelines"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trigger_documents")),
        sa.UniqueConstraint("code", name=op.f("uq_trigger_documents_code")),
    )
    with op.batch_alter_table("trigger_documents", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_trigger_documents_digest"), ["digest"], unique=False)
        batch_op.create_index(batch_op.f("ix_trigger_documents_pipeline_id"), ["pipeline_id"], unique=False)

    op.create_table(
        "schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum("cron", "interval", "one_time", name="schedule_kind", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("cron", sa.String(length=200), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=True),
        sa.Column("run_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), server_default="UTC", nullable=False),
        sa.Column("params", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=False),
        sa.Column(
            "connection_pins",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "log_levels", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=True
        ),
        sa.Column(
            "priority",
            sa.Enum("low", "normal", "high", name="run_priority", native_enum=False, length=32),
            nullable=True,
        ),
        sa.Column("managed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("trigger_document_id", sa.Uuid(), nullable=True),
        sa.Column("paused", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("next_fire_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("last_fired_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_id"], ["pipelines.id"], name=op.f("fk_schedules_pipeline_id_pipelines"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["trigger_document_id"],
            ["trigger_documents.id"],
            name=op.f("fk_schedules_trigger_document_id_trigger_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedules")),
        sa.UniqueConstraint("pipeline_id", "code", name=op.f("uq_schedules_pipeline_id_code")),
    )
    with op.batch_alter_table("schedules", schema=None) as batch_op:
        batch_op.create_index("ix_schedules_paused_next_fire_at", ["paused", "next_fire_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_schedules_pipeline_id"), ["pipeline_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_schedules_trigger_document_id"), ["trigger_document_id"], unique=False)

    op.create_table(
        "webhook_triggers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=200), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), server_default="", nullable=False),
        sa.Column("hmac_secret", sa.LargeBinary(), nullable=True),
        sa.Column("hmac_secret_key_id", sa.String(length=100), nullable=True),
        sa.Column(
            "params_from_payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum("low", "normal", "high", name="run_priority", native_enum=False, length=32),
            nullable=True,
        ),
        sa.Column("managed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("trigger_document_id", sa.Uuid(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("rate_limit_per_minute", sa.Integer(), server_default=sa.text("60"), nullable=False),
        sa.Column("last_delivery_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_id"],
            ["pipelines.id"],
            name=op.f("fk_webhook_triggers_pipeline_id_pipelines"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_document_id"],
            ["trigger_documents.id"],
            name=op.f("fk_webhook_triggers_trigger_document_id_trigger_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_triggers")),
        sa.UniqueConstraint("pipeline_id", "code", name=op.f("uq_webhook_triggers_pipeline_id_code")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_webhook_triggers_token_hash")),
    )
    with op.batch_alter_table("webhook_triggers", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_webhook_triggers_pipeline_id"), ["pipeline_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_webhook_triggers_trigger_document_id"), ["trigger_document_id"], unique=False
        )

    op.create_table(
        "runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_id", sa.Uuid(), nullable=False),
        sa.Column("pipeline_version_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "completed_with_errors",
                "failed",
                "cancelled",
                name="run_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "priority",
            sa.Enum("low", "normal", "high", name="run_priority", native_enum=False, length=32),
            server_default="normal",
            nullable=False,
        ),
        sa.Column("params", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=False),
        sa.Column(
            "triggered_by_kind",
            sa.Enum(
                "adhoc",
                "schedule",
                "webhook",
                "api_token",
                "user",
                "pipeline",
                "backfill",
                name="trigger_kind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("triggered_by_id", sa.Uuid(), nullable=True),
        sa.Column("triggered_by_label", sa.String(length=200), nullable=True),
        sa.Column("traceparent", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("finished_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("window_start", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("window_end", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column(
            "log_levels", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=True
        ),
        sa.Column(
            "worker_tags", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=False
        ),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_id"], ["pipelines.id"], name=op.f("fk_runs_pipeline_id_pipelines"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["pipeline_version_id"],
            ["pipeline_versions.id"],
            name=op.f("fk_runs_pipeline_version_id_pipeline_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
    )
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.create_index("ix_runs_finished_at", ["finished_at"], unique=False)
        batch_op.create_index(
            "ix_runs_pipeline_id_status_created_at", ["pipeline_id", "status", "created_at"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_runs_status"), ["status"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("alert_rule_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "event",
            sa.Enum(
                "run_failed",
                "run_completed_with_errors",
                "run_succeeded",
                "run_stuck",
                name="alert_event",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("notifier", sa.String(length=100), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "context", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum("pending", "sending", "sent", "failed", name="notification_status", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("available_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=200), nullable=True),
        sa.Column("lease_expires_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("sent_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["alert_rule_id"],
            ["alert_rules.id"],
            name=op.f("fk_notifications_alert_rule_id_alert_rules"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["connections.id"],
            name=op.f("fk_notifications_connection_id_connections"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_notifications_run_id_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint(
            "alert_rule_id", "run_id", "event", name=op.f("uq_notifications_alert_rule_id_run_id_event")
        ),
    )
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_notifications_alert_rule_id"), ["alert_rule_id"], unique=False)
        batch_op.create_index("ix_notifications_created_at", ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_notifications_run_id"), ["run_id"], unique=False)
        batch_op.create_index("ix_notifications_status_available_at", ["status", "available_at"], unique=False)

    op.create_table(
        "run_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_name", sa.String(length=200), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("item_key", sa.String(length=500), nullable=False),
        sa.Column(
            "item_value", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=True
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "succeeded",
                "failed",
                "skipped",
                name="run_item_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("failing_step", sa.String(length=200), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("finished_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_run_items_run_id_runs"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_items")),
        sa.UniqueConstraint("run_id", "step_name", "item_index", name=op.f("uq_run_items_run_id_step_name_item_index")),
    )
    with op.batch_alter_table("run_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_run_items_run_id"), ["run_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_run_items_status"), ["status"], unique=False)

    op.create_table(
        "schedule_firings",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("scheduled_for", dirigent_core.types.UtcDateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.Enum(
                "fired", "queued", "replaced", "skipped", "failed", name="firing_outcome", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("misfired", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_schedule_firings_run_id_runs"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["schedules.id"],
            name=op.f("fk_schedule_firings_schedule_id_schedules"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedule_firings")),
    )
    with op.batch_alter_table("schedule_firings", schema=None) as batch_op:
        batch_op.create_index("ix_schedule_firings_created_at", ["created_at"], unique=False)
        batch_op.create_index("ix_schedule_firings_schedule_id_id", ["schedule_id", "id"], unique=False)

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("webhook_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.Enum("accepted", "skipped", "rejected", name="webhook_outcome", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=True),
        sa.Column(
            "mapped_params", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=True
        ),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name=op.f("fk_webhook_deliveries_run_id_runs"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["webhook_id"],
            ["webhook_triggers.id"],
            name=op.f("fk_webhook_deliveries_webhook_id_webhook_triggers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
    )
    with op.batch_alter_table("webhook_deliveries", schema=None) as batch_op:
        batch_op.create_index("ix_webhook_deliveries_created_at", ["created_at"], unique=False)
        batch_op.create_index("ix_webhook_deliveries_webhook_id_id", ["webhook_id", "id"], unique=False)

    op.create_table(
        "step_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("run_item_id", sa.Uuid(), nullable=True),
        sa.Column("step_name", sa.String(length=200), nullable=False),
        sa.Column("block_id", sa.String(length=200), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column(
            "kind", sa.Enum("automatic", "manual", name="attempt_kind", native_enum=False, length=32), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "queued",
                "running",
                "waiting",
                "succeeded",
                "failed",
                "skipped",
                "cancelled",
                name="attempt_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("available_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("next_poll_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=200), nullable=True),
        sa.Column("lease_expires_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column(
            "remote_handle", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=True
        ),
        sa.Column(
            "poke_cursor", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=True
        ),
        sa.Column("gone_probes", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("poke_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("waiting_message", sa.String(length=500), nullable=True),
        sa.Column("waiting_progress", sa.Float(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=400), nullable=True),
        sa.Column("input", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=True),
        sa.Column("output", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=True),
        sa.Column("output_artifact_id", sa.Uuid(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_class", sa.String(length=32), nullable=True),
        sa.Column("started_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column("finished_at", dirigent_core.types.UtcDateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_step_attempts_run_id_runs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["run_item_id"], ["run_items.id"], name=op.f("fk_step_attempts_run_item_id_run_items"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_step_attempts")),
        sa.UniqueConstraint("run_id", "idempotency_key", name=op.f("uq_step_attempts_run_id_idempotency_key")),
        sa.UniqueConstraint(
            "run_id",
            "step_name",
            "run_item_id",
            "attempt",
            name=op.f("uq_step_attempts_run_id_step_name_run_item_id_attempt"),
        ),
    )
    with op.batch_alter_table("step_attempts", schema=None) as batch_op:
        batch_op.create_index("ix_step_attempts_lease_expires_at", ["lease_expires_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_step_attempts_run_id"), ["run_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_step_attempts_run_item_id"), ["run_item_id"], unique=False)
        batch_op.create_index("ix_step_attempts_status_available_at", ["status", "available_at"], unique=False)
        batch_op.create_index("ix_step_attempts_status_next_poll_at", ["status", "next_poll_at"], unique=False)

    op.create_table(
        "artifact_refs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("step_name", sa.String(length=200), nullable=True),
        sa.Column("uri", sa.Text(), nullable=True),
        sa.Column("scheme", sa.String(length=32), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=True),
        sa.Column("digest", sa.String(length=71), nullable=True),
        sa.Column(
            "inline_value", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=True
        ),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_artifact_refs_run_id_runs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["step_attempt_id"],
            ["step_attempts.id"],
            name=op.f("fk_artifact_refs_step_attempt_id_step_attempts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact_refs")),
    )
    with op.batch_alter_table("artifact_refs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_artifact_refs_run_id"), ["run_id"], unique=False)

    op.create_table(
        "log_entries",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("run_item_id", sa.Uuid(), nullable=True),
        sa.Column("step_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("step_name", sa.String(length=200), nullable=True),
        sa.Column(
            "level",
            sa.Enum("debug", "info", "warning", "error", name="log_level", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("fields", sa.JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql"), nullable=True),
        sa.Column(
            "created_at",
            dirigent_core.types.UtcDateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], name=op.f("fk_log_entries_run_id_runs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["run_item_id"], ["run_items.id"], name=op.f("fk_log_entries_run_item_id_run_items"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["step_attempt_id"],
            ["step_attempts.id"],
            name=op.f("fk_log_entries_step_attempt_id_step_attempts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_log_entries")),
    )
    with op.batch_alter_table("log_entries", schema=None) as batch_op:
        batch_op.create_index("ix_log_entries_created_at", ["created_at"], unique=False)
        batch_op.create_index("ix_log_entries_run_id_id", ["run_id", "id"], unique=False)


def downgrade() -> None:
    """Drop all of it."""
    with op.batch_alter_table("log_entries", schema=None) as batch_op:
        batch_op.drop_index("ix_log_entries_run_id_id")
        batch_op.drop_index("ix_log_entries_created_at")

    op.drop_table("log_entries")
    with op.batch_alter_table("artifact_refs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_artifact_refs_run_id"))

    op.drop_table("artifact_refs")
    with op.batch_alter_table("step_attempts", schema=None) as batch_op:
        batch_op.drop_index("ix_step_attempts_status_next_poll_at")
        batch_op.drop_index("ix_step_attempts_status_available_at")
        batch_op.drop_index(batch_op.f("ix_step_attempts_run_item_id"))
        batch_op.drop_index(batch_op.f("ix_step_attempts_run_id"))
        batch_op.drop_index("ix_step_attempts_lease_expires_at")

    op.drop_table("step_attempts")
    with op.batch_alter_table("webhook_deliveries", schema=None) as batch_op:
        batch_op.drop_index("ix_webhook_deliveries_webhook_id_id")
        batch_op.drop_index("ix_webhook_deliveries_created_at")

    op.drop_table("webhook_deliveries")
    with op.batch_alter_table("schedule_firings", schema=None) as batch_op:
        batch_op.drop_index("ix_schedule_firings_schedule_id_id")
        batch_op.drop_index("ix_schedule_firings_created_at")

    op.drop_table("schedule_firings")
    with op.batch_alter_table("run_items", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_run_items_status"))
        batch_op.drop_index(batch_op.f("ix_run_items_run_id"))

    op.drop_table("run_items")
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_index("ix_notifications_status_available_at")
        batch_op.drop_index(batch_op.f("ix_notifications_run_id"))
        batch_op.drop_index("ix_notifications_created_at")
        batch_op.drop_index(batch_op.f("ix_notifications_alert_rule_id"))

    op.drop_table("notifications")
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_runs_status"))
        batch_op.drop_index("ix_runs_pipeline_id_status_created_at")
        batch_op.drop_index("ix_runs_finished_at")

    op.drop_table("runs")
    with op.batch_alter_table("webhook_triggers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_webhook_triggers_trigger_document_id"))
        batch_op.drop_index(batch_op.f("ix_webhook_triggers_pipeline_id"))

    op.drop_table("webhook_triggers")
    with op.batch_alter_table("schedules", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_schedules_trigger_document_id"))
        batch_op.drop_index(batch_op.f("ix_schedules_pipeline_id"))
        batch_op.drop_index("ix_schedules_paused_next_fire_at")

    op.drop_table("schedules")
    with op.batch_alter_table("trigger_documents", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_trigger_documents_pipeline_id"))
        batch_op.drop_index(batch_op.f("ix_trigger_documents_digest"))

    op.drop_table("trigger_documents")
    with op.batch_alter_table("pipeline_versions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pipeline_versions_pipeline_id"))
        batch_op.drop_index(batch_op.f("ix_pipeline_versions_digest"))

    op.drop_table("pipeline_versions")
    with op.batch_alter_table("api_tokens", schema=None) as batch_op:
        batch_op.drop_index("ix_api_tokens_user_id_kind")

    op.drop_table("api_tokens")
    with op.batch_alter_table("alert_rules", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_alert_rules_pipeline_id"))
        batch_op.drop_index(batch_op.f("ix_alert_rules_event"))

    op.drop_table("alert_rules")
    with op.batch_alter_table("workers", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workers_last_seen_at"))

    op.drop_table("workers")
    op.drop_table("users")
    op.drop_table("pipelines")
    op.drop_table("schemas")
    with op.batch_alter_table("connections", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_connections_kind"))

    op.drop_table("connections")
