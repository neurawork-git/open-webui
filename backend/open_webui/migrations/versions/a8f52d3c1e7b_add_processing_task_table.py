"""Add processing_task table for document processing dashboard

Revision ID: a8f52d3c1e7b
Revises: c440947495f3
Create Date: 2026-01-29 14:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a8f52d3c1e7b"
down_revision: Union[str, None] = "c440947495f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "processing_task",
        # Primary key
        sa.Column("id", sa.Text(), primary_key=True),
        # Document reference
        sa.Column("document_id", sa.Text(), nullable=True),
        sa.Column("document_name", sa.Text(), nullable=True),
        sa.Column("document_type", sa.Text(), default="file_upload"),
        # User/context reference
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("chat_id", sa.Text(), nullable=True),
        sa.Column("knowledge_id", sa.Text(), nullable=True),
        # State tracking
        sa.Column("status", sa.Text(), default="queued", nullable=False),
        sa.Column("stage", sa.Text(), default="queued", nullable=False),
        sa.Column("progress", sa.Float(), default=0.0, nullable=False),
        # Timing (BigInteger for epoch timestamps)
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.BigInteger(), nullable=True),
        sa.Column("completed_at", sa.BigInteger(), nullable=True),
        # Progress details
        sa.Column("total_chunks", sa.Integer(), nullable=True),
        sa.Column("processed_chunks", sa.Integer(), default=0),
        sa.Column("current_batch", sa.Integer(), default=0),
        sa.Column("retry_count", sa.Integer(), default=0),
        # Error tracking
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_details", sa.JSON(), nullable=True),
        # Cancellation
        sa.Column("cancel_requested", sa.Boolean(), default=False),
        sa.Column("cancelled_by", sa.Text(), nullable=True),
        sa.Column("cancelled_at", sa.BigInteger(), nullable=True),
        # Additional metadata
        sa.Column("metadata", sa.JSON(), nullable=True),
        # Indexes for common queries
        sa.Index("ix_processing_task_status", "status"),
        sa.Index("ix_processing_task_user_id", "user_id"),
        sa.Index("ix_processing_task_created_at", "created_at"),
        sa.Index("ix_processing_task_document_id", "document_id"),
    )


def downgrade() -> None:
    op.drop_table("processing_task")
