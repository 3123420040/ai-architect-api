"""professional deliverable product job tables

Revision ID: 20260427_0003
Revises: 20260413_0002
Create Date: 2026-04-27 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260427_0003"
down_revision = "20260413_0002"
branch_labels = None
depends_on = None


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_exists(inspector: sa.Inspector, table_name: str, column_name: str) -> bool:
    try:
        return any(column["name"] == column_name for column in inspector.get_columns(table_name))
    except sa.exc.NoSuchTableError:
        return False


def _index_exists(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    try:
        return any(index["name"] == index_name for index in inspector.get_indexes(table_name))
    except sa.exc.NoSuchTableError:
        return False


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _table_exists(inspector, "professional_deliverable_bundles"):
        if not _column_exists(inspector, "design_versions", "current_professional_deliverable_bundle_id"):
            op.add_column("design_versions", sa.Column("current_professional_deliverable_bundle_id", sa.String(length=36), nullable=True))
        return

    op.create_table(
        "professional_deliverable_bundles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("version_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("quality_status", sa.String(length=20), nullable=False),
        sa.Column("is_degraded", sa.Boolean(), nullable=False),
        sa.Column("degraded_reasons_json", sa.JSON(), nullable=False),
        sa.Column("gate_summary_url", sa.String(length=500), nullable=True),
        sa.Column("runtime_metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["design_versions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_professional_deliverable_bundles_project_id"), "professional_deliverable_bundles", ["project_id"], unique=False)
    op.create_index(op.f("ix_professional_deliverable_bundles_quality_status"), "professional_deliverable_bundles", ["quality_status"], unique=False)
    op.create_index(op.f("ix_professional_deliverable_bundles_status"), "professional_deliverable_bundles", ["status"], unique=False)
    op.create_index(op.f("ix_professional_deliverable_bundles_version_id"), "professional_deliverable_bundles", ["version_id"], unique=False)

    op.create_table(
        "professional_deliverable_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("bundle_id", sa.String(length=36), nullable=False),
        sa.Column("job_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("stage", sa.String(length=50), nullable=False),
        sa.Column("progress_percent", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("runtime_metadata_json", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bundle_id"], ["professional_deliverable_bundles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_professional_deliverable_jobs_bundle_id"), "professional_deliverable_jobs", ["bundle_id"], unique=False)
    op.create_index(op.f("ix_professional_deliverable_jobs_stage"), "professional_deliverable_jobs", ["stage"], unique=False)
    op.create_index(op.f("ix_professional_deliverable_jobs_status"), "professional_deliverable_jobs", ["status"], unique=False)

    op.create_table(
        "professional_deliverable_assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("bundle_id", sa.String(length=36), nullable=False),
        sa.Column("asset_type", sa.String(length=50), nullable=False),
        sa.Column("asset_role", sa.String(length=100), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("public_url", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("checksum", sa.String(length=120), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bundle_id"], ["professional_deliverable_bundles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_professional_deliverable_assets_asset_role"), "professional_deliverable_assets", ["asset_role"], unique=False)
    op.create_index(op.f("ix_professional_deliverable_assets_asset_type"), "professional_deliverable_assets", ["asset_type"], unique=False)
    op.create_index(op.f("ix_professional_deliverable_assets_bundle_id"), "professional_deliverable_assets", ["bundle_id"], unique=False)

    op.add_column("design_versions", sa.Column("current_professional_deliverable_bundle_id", sa.String(length=36), nullable=True))
    op.create_index(op.f("ix_design_versions_current_professional_deliverable_bundle_id"), "design_versions", ["current_professional_deliverable_bundle_id"], unique=False)
    op.create_foreign_key(
        "fk_design_versions_current_professional_deliverable_bundle_id",
        "design_versions",
        "professional_deliverable_bundles",
        ["current_professional_deliverable_bundle_id"],
        ["id"],
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _index_exists(inspector, "design_versions", "ix_design_versions_current_professional_deliverable_bundle_id"):
        op.drop_index(op.f("ix_design_versions_current_professional_deliverable_bundle_id"), table_name="design_versions")
    if _column_exists(inspector, "design_versions", "current_professional_deliverable_bundle_id"):
        with op.batch_alter_table("design_versions", schema=None) as batch_op:
            batch_op.drop_column("current_professional_deliverable_bundle_id")
    if _table_exists(inspector, "professional_deliverable_assets"):
        op.drop_index(op.f("ix_professional_deliverable_assets_bundle_id"), table_name="professional_deliverable_assets")
        op.drop_index(op.f("ix_professional_deliverable_assets_asset_type"), table_name="professional_deliverable_assets")
        op.drop_index(op.f("ix_professional_deliverable_assets_asset_role"), table_name="professional_deliverable_assets")
        op.drop_table("professional_deliverable_assets")
    if _table_exists(inspector, "professional_deliverable_jobs"):
        op.drop_index(op.f("ix_professional_deliverable_jobs_status"), table_name="professional_deliverable_jobs")
        op.drop_index(op.f("ix_professional_deliverable_jobs_stage"), table_name="professional_deliverable_jobs")
        op.drop_index(op.f("ix_professional_deliverable_jobs_bundle_id"), table_name="professional_deliverable_jobs")
        op.drop_table("professional_deliverable_jobs")
    if _table_exists(inspector, "professional_deliverable_bundles"):
        op.drop_index(op.f("ix_professional_deliverable_bundles_version_id"), table_name="professional_deliverable_bundles")
        op.drop_index(op.f("ix_professional_deliverable_bundles_status"), table_name="professional_deliverable_bundles")
        op.drop_index(op.f("ix_professional_deliverable_bundles_quality_status"), table_name="professional_deliverable_bundles")
        op.drop_index(op.f("ix_professional_deliverable_bundles_project_id"), table_name="professional_deliverable_bundles")
        op.drop_table("professional_deliverable_bundles")
