"""add selective persistent customer memory

Revision ID: 20260811_0003
Revises: 20260811_0002
"""

from alembic import op
import sqlalchemy as sa

revision = "20260811_0003"
down_revision = "20260811_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("memory_type", sa.String(40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("normalized_key", sa.String(64), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
    )
    op.create_index(
        "ix_memory_records_customer_status", "memory_records", ["customer_id", "status"]
    )
    op.create_index(
        "ix_memory_records_customer_key", "memory_records", ["customer_id", "normalized_key"]
    )


def downgrade() -> None:
    op.drop_index("ix_memory_records_customer_key", table_name="memory_records")
    op.drop_index("ix_memory_records_customer_status", table_name="memory_records")
    op.drop_table("memory_records")
