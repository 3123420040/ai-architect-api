"""professional deliverable partial asset state

Revision ID: 20260427_0004
Revises: 20260427_0003
Create Date: 2026-04-27 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260427_0004"
down_revision = "20260427_0003"
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
        for column in (
            sa.Column("failed_gates_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("warnings_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("missing_artifacts_json", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("user_message", sa.String(length=500), nullable=True),
            sa.Column("technical_details_json", sa.JSON(), nullable=False, server_default="{}"),
        ):
            if not _column_exists(inspector, "professional_deliverable_bundles", column.name):
                op.add_column("professional_deliverable_bundles", column)
    if _table_exists(inspector, "professional_deliverable_assets"):
        if not _column_exists(inspector, "professional_deliverable_assets", "status"):
            op.add_column("professional_deliverable_assets", sa.Column("status", sa.String(length=20), nullable=False, server_default="ready"))
            op.create_index(op.f("ix_professional_deliverable_assets_status"), "professional_deliverable_assets", ["status"], unique=False)
        if not _column_exists(inspector, "professional_deliverable_assets", "skip_reason"):
            op.add_column("professional_deliverable_assets", sa.Column("skip_reason", sa.Text(), nullable=True))
        if not _column_exists(inspector, "professional_deliverable_assets", "validation_error"):
            op.add_column("professional_deliverable_assets", sa.Column("validation_error", sa.Text(), nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _table_exists(inspector, "professional_deliverable_assets"):
        if _index_exists(inspector, "professional_deliverable_assets", "ix_professional_deliverable_assets_status"):
            op.drop_index(op.f("ix_professional_deliverable_assets_status"), table_name="professional_deliverable_assets")
        for column_name in ("validation_error", "skip_reason", "status"):
            if _column_exists(inspector, "professional_deliverable_assets", column_name):
                with op.batch_alter_table("professional_deliverable_assets", schema=None) as batch_op:
                    batch_op.drop_column(column_name)
    if _table_exists(inspector, "professional_deliverable_bundles"):
        for column_name in (
            "technical_details_json",
            "user_message",
            "missing_artifacts_json",
            "warnings_json",
            "failed_gates_json",
        ):
            if _column_exists(inspector, "professional_deliverable_bundles", column_name):
                with op.batch_alter_table("professional_deliverable_bundles", schema=None) as batch_op:
                    batch_op.drop_column(column_name)
