"""Add conversation memories table

Revision ID: 003
Revises: 002
Create Date: 2026-06-26
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_memories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False, index=True),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("learnings", sa.JSON, nullable=True),
        sa.Column("corrections", sa.JSON, nullable=True),
        sa.Column("topics", sa.JSON, nullable=True),
        sa.Column("message_count", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("conversation_memories")
