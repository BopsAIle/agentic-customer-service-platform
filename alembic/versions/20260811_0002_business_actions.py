"""add refund requests and human escalations

Revision ID: 20260811_0002
Revises: 20260811_0001
"""
from alembic import op
import sqlalchemy as sa

revision = "20260811_0002"
down_revision = "20260811_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refund_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_refund_requests_customer_id", "refund_requests", ["customer_id"])
    op.create_index("ix_refund_requests_order_id", "refund_requests", ["order_id"])
    op.create_table(
        "escalations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("customers.id"), nullable=False),
        sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("support_tickets.id"), nullable=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_escalations_customer_id", "escalations", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_escalations_customer_id", table_name="escalations")
    op.drop_table("escalations")
    op.drop_index("ix_refund_requests_order_id", table_name="refund_requests")
    op.drop_index("ix_refund_requests_customer_id", table_name="refund_requests")
    op.drop_table("refund_requests")

