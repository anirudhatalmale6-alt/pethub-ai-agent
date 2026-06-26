"""Add performance feedback tables

Revision ID: 004
Revises: 003
Create Date: 2026-06-26
"""
from alembic import op
import sqlalchemy as sa

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "performance_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=True),
        sa.Column("action_type", sa.String(50), nullable=False, index=True),
        sa.Column("action_detail", sa.String(255), nullable=False),
        sa.Column("scores", sa.JSON, server_default="{}"),
        sa.Column("overall_score", sa.Float, server_default="0"),
        sa.Column("what_worked", sa.JSON, server_default="[]"),
        sa.Column("what_failed", sa.JSON, server_default="[]"),
        sa.Column("improvements", sa.JSON, server_default="[]"),
        sa.Column("context", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "improvement_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("action_type", sa.String(50), nullable=False, index=True),
        sa.Column("rule", sa.Text, nullable=False),
        sa.Column("source_record_id", sa.String(36), nullable=True),
        sa.Column("times_applied", sa.Integer, server_default="0"),
        sa.Column("effectiveness", sa.Float, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("improvement_rules")
    op.drop_table("performance_records")
