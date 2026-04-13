"""phase 6 presentation 3d tables

Revision ID: 20260413_0002
Revises: 20260411_0001
Create Date: 2026-04-13 21:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260413_0002"
down_revision = "20260411_0001"
branch_labels = None
depends_on = None


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    try:
        columns = inspector.get_columns(table_name)
    except sa.exc.NoSuchTableError:
        return False
    return any(column["name"] == column_name for column in columns)


def _index_exists(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    try:
        indexes = inspector.get_indexes(table_name)
    except sa.exc.NoSuchTableError:
        return False
    return any(index["name"] == index_name for index in indexes)


def _foreign_key_exists(inspector: sa.Inspector, table_name: str, constraint_name: str) -> bool:
    try:
        foreign_keys = inspector.get_foreign_keys(table_name)
    except sa.exc.NoSuchTableError:
        return False
    return any((item.get("name") or "") == constraint_name for item in foreign_keys)


def _create_bundle_table() -> None:
    op.create_table(
        "presentation_3d_bundles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_id", sa.String(length=36), sa.ForeignKey("design_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scene_spec_revision", sa.String(length=50), nullable=False, server_default="v1"),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="queued"),
        sa.Column("qa_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("approval_status", sa.String(length=30), nullable=False, server_default="not_requested"),
        sa.Column("delivery_status", sa.String(length=30), nullable=False, server_default="preview_only"),
        sa.Column("is_degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("degraded_reasons_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("scene_spec_url", sa.String(length=500), nullable=True),
        sa.Column("manifest_url", sa.String(length=500), nullable=True),
        sa.Column("qa_report_url", sa.String(length=500), nullable=True),
        sa.Column("runtime_metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def _create_jobs_table() -> None:
    op.create_table(
        "presentation_3d_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("bundle_id", sa.String(length=36), sa.ForeignKey("presentation_3d_bundles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_type", sa.String(length=50), nullable=False, server_default="generate_bundle"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(length=50), nullable=False, server_default="scene_spec"),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("runtime_metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def _create_assets_table() -> None:
    op.create_table(
        "presentation_3d_assets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("bundle_id", sa.String(length=36), sa.ForeignKey("presentation_3d_bundles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_type", sa.String(length=50), nullable=False),
        sa.Column("asset_role", sa.String(length=100), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("public_url", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(length=120), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def _create_approvals_table() -> None:
    op.create_table(
        "presentation_3d_approvals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("bundle_id", sa.String(length=36), sa.ForeignKey("presentation_3d_bundles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "presentation_3d_bundles"):
        _create_bundle_table()
        inspector = sa.inspect(bind)

    for index_name, columns in (
        ("ix_presentation_3d_bundles_project_id", ["project_id"]),
        ("ix_presentation_3d_bundles_version_id", ["version_id"]),
        ("ix_presentation_3d_bundles_status", ["status"]),
        ("ix_presentation_3d_bundles_qa_status", ["qa_status"]),
        ("ix_presentation_3d_bundles_approval_status", ["approval_status"]),
        ("ix_presentation_3d_bundles_delivery_status", ["delivery_status"]),
    ):
        if not _index_exists(inspector, "presentation_3d_bundles", index_name):
            op.create_index(index_name, "presentation_3d_bundles", columns)
            inspector = sa.inspect(bind)

    if not _column_exists(inspector, "design_versions", "current_presentation_3d_bundle_id"):
        op.add_column("design_versions", sa.Column("current_presentation_3d_bundle_id", sa.String(length=36), nullable=True))
        inspector = sa.inspect(bind)

    if bind.dialect.name != "sqlite" and not _foreign_key_exists(
        inspector,
        "design_versions",
        "fk_design_versions_current_presentation_3d_bundle_id",
    ):
        op.create_foreign_key(
            "fk_design_versions_current_presentation_3d_bundle_id",
            "design_versions",
            "presentation_3d_bundles",
            ["current_presentation_3d_bundle_id"],
            ["id"],
        )
        inspector = sa.inspect(bind)

    if not _index_exists(inspector, "design_versions", "ix_design_versions_current_presentation_3d_bundle_id"):
        op.create_index(
            "ix_design_versions_current_presentation_3d_bundle_id",
            "design_versions",
            ["current_presentation_3d_bundle_id"],
        )
        inspector = sa.inspect(bind)

    if not _table_exists(inspector, "presentation_3d_jobs"):
        _create_jobs_table()
        inspector = sa.inspect(bind)

    for index_name, columns in (
        ("ix_presentation_3d_jobs_bundle_id", ["bundle_id"]),
        ("ix_presentation_3d_jobs_status", ["status"]),
        ("ix_presentation_3d_jobs_stage", ["stage"]),
    ):
        if not _index_exists(inspector, "presentation_3d_jobs", index_name):
            op.create_index(index_name, "presentation_3d_jobs", columns)
            inspector = sa.inspect(bind)

    if not _table_exists(inspector, "presentation_3d_assets"):
        _create_assets_table()
        inspector = sa.inspect(bind)

    for index_name, columns in (
        ("ix_presentation_3d_assets_bundle_id", ["bundle_id"]),
        ("ix_presentation_3d_assets_asset_type", ["asset_type"]),
        ("ix_presentation_3d_assets_asset_role", ["asset_role"]),
    ):
        if not _index_exists(inspector, "presentation_3d_assets", index_name):
            op.create_index(index_name, "presentation_3d_assets", columns)
            inspector = sa.inspect(bind)

    if not _table_exists(inspector, "presentation_3d_approvals"):
        _create_approvals_table()
        inspector = sa.inspect(bind)

    if not _index_exists(inspector, "presentation_3d_approvals", "ix_presentation_3d_approvals_bundle_id"):
        op.create_index("ix_presentation_3d_approvals_bundle_id", "presentation_3d_approvals", ["bundle_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _table_exists(inspector, "presentation_3d_approvals"):
        if _index_exists(inspector, "presentation_3d_approvals", "ix_presentation_3d_approvals_bundle_id"):
            op.drop_index("ix_presentation_3d_approvals_bundle_id", table_name="presentation_3d_approvals")
        op.drop_table("presentation_3d_approvals")
        inspector = sa.inspect(bind)

    if _table_exists(inspector, "presentation_3d_assets"):
        for index_name in (
            "ix_presentation_3d_assets_asset_role",
            "ix_presentation_3d_assets_asset_type",
            "ix_presentation_3d_assets_bundle_id",
        ):
            if _index_exists(inspector, "presentation_3d_assets", index_name):
                op.drop_index(index_name, table_name="presentation_3d_assets")
                inspector = sa.inspect(bind)
        op.drop_table("presentation_3d_assets")
        inspector = sa.inspect(bind)

    if _table_exists(inspector, "presentation_3d_jobs"):
        for index_name in (
            "ix_presentation_3d_jobs_stage",
            "ix_presentation_3d_jobs_status",
            "ix_presentation_3d_jobs_bundle_id",
        ):
            if _index_exists(inspector, "presentation_3d_jobs", index_name):
                op.drop_index(index_name, table_name="presentation_3d_jobs")
                inspector = sa.inspect(bind)
        op.drop_table("presentation_3d_jobs")
        inspector = sa.inspect(bind)

    if _column_exists(inspector, "design_versions", "current_presentation_3d_bundle_id"):
        if _index_exists(inspector, "design_versions", "ix_design_versions_current_presentation_3d_bundle_id"):
            op.drop_index(
                "ix_design_versions_current_presentation_3d_bundle_id",
                table_name="design_versions",
            )
            inspector = sa.inspect(bind)
        if bind.dialect.name != "sqlite" and _foreign_key_exists(
            inspector,
            "design_versions",
            "fk_design_versions_current_presentation_3d_bundle_id",
        ):
            op.drop_constraint(
                "fk_design_versions_current_presentation_3d_bundle_id",
                "design_versions",
                type_="foreignkey",
            )
            inspector = sa.inspect(bind)
        # SQLite may have the FK embedded in table creation because the base
        # revision uses metadata.create_all(). Rebuilding that table inside this
        # revision is unnecessary because downgrade to base will drop all tables
        # in the previous revision immediately afterwards.
        if bind.dialect.name != "sqlite":
            op.drop_column("design_versions", "current_presentation_3d_bundle_id")
            inspector = sa.inspect(bind)

    if _table_exists(inspector, "presentation_3d_bundles"):
        for index_name in (
            "ix_presentation_3d_bundles_delivery_status",
            "ix_presentation_3d_bundles_approval_status",
            "ix_presentation_3d_bundles_qa_status",
            "ix_presentation_3d_bundles_status",
            "ix_presentation_3d_bundles_version_id",
            "ix_presentation_3d_bundles_project_id",
        ):
            if _index_exists(inspector, "presentation_3d_bundles", index_name):
                op.drop_index(index_name, table_name="presentation_3d_bundles")
                inspector = sa.inspect(bind)
        op.drop_table("presentation_3d_bundles")
