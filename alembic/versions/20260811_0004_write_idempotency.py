"""add database-enforced business write idempotency

Revision ID: 20260811_0004
Revises: 20260811_0003
"""

from alembic import op
import sqlalchemy as sa

revision = "20260811_0004"
down_revision = "20260811_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_action_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.String(200), nullable=False),
        sa.Column("operation", sa.String(80), nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("result_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "actor_id",
            "operation",
            "idempotency_key",
            name="uq_business_action_receipt_scope",
        ),
    )
    op.create_index(
        "ix_business_action_receipts_customer_id",
        "business_action_receipts",
        ["customer_id"],
    )
    op.create_index(
        "uq_refund_requests_active_order",
        "refund_requests",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('requested', 'approved', 'processing')"),
        sqlite_where=sa.text("status IN ('requested', 'approved', 'processing')"),
    )


def downgrade() -> None:
    op.drop_index("uq_refund_requests_active_order", table_name="refund_requests")
    op.drop_index(
        "ix_business_action_receipts_customer_id",
        table_name="business_action_receipts",
    )
    op.drop_table("business_action_receipts")
