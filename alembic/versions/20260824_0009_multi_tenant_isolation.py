"""add explicit tenant ownership and isolation columns

Revision ID: 20260824_0009
Revises: 20260824_0008
"""

from datetime import UTC, datetime

from alembic import op
import sqlalchemy as sa


revision = "20260824_0009"
down_revision = "20260824_0008"
branch_labels = None
depends_on = None

_TABLES = (
    "customers",
    "orders",
    "support_tickets",
    "refund_requests",
    "escalations",
    "business_action_receipts",
    "policy_audit_events",
    "agent_run_projections",
    "memory_records",
)


def upgrade() -> None:
    # Existing rows are backfilled into this compatibility tenant before the
    # non-null foreign keys are applied. Production mappings must be explicit.
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=200), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.bulk_insert(
        sa.table(
            "tenants",
            sa.column("id", sa.String()),
            sa.column("name", sa.String()),
            sa.column("status", sa.String()),
            sa.column("created_at", sa.DateTime()),
        ),
        [
            {
                "id": "default",
                "name": "Default tenant",
                "status": "active",
                "created_at": datetime.now(UTC),
            }
        ],
    )

    # Use PostgreSQL ALTER TABLE operations instead of batch recreation. Batch
    # recreation attempts to drop each table's primary key, which is unsafe
    # while existing child foreign keys still reference it.
    for table_name in _TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "tenant_id",
                sa.String(length=200),
                nullable=False,
                server_default="default",
            ),
        )

    for table_name in _TABLES:
        op.create_foreign_key(
            f"fk_{table_name}_tenant_id",
            table_name,
            "tenants",
            ["tenant_id"],
            ["id"],
        )
        op.create_index(f"ix_{table_name}_tenant_id", table_name, ["tenant_id"])
        op.alter_column(
            table_name,
            "tenant_id",
            existing_type=sa.String(length=200),
            existing_nullable=False,
            server_default=None,
        )

    op.drop_index("ix_customers_email", table_name="customers")
    op.create_unique_constraint(
        "uq_customer_tenant_email", "customers", ["tenant_id", "email"]
    )
    op.create_index("ix_customers_email", "customers", ["email"], unique=False)

    op.drop_constraint(
        "uq_business_action_receipt_scope", "business_action_receipts", type_="unique"
    )
    op.create_unique_constraint(
        "uq_business_action_receipt_scope",
        "business_action_receipts",
        ["tenant_id", "actor_id", "operation", "idempotency_key"],
    )

    op.drop_index("uq_refund_requests_active_order", table_name="refund_requests")
    op.create_index(
        "uq_refund_requests_active_order",
        "refund_requests",
        ["tenant_id", "order_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('requested', 'approved', 'processing')"),
        sqlite_where=sa.text("status IN ('requested', 'approved', 'processing')"),
    )

    op.drop_constraint(
        "uq_agent_run_projection_run_id", "agent_run_projections", type_="unique"
    )
    op.create_unique_constraint(
        "uq_agent_run_projection_tenant_run",
        "agent_run_projections",
        ["tenant_id", "run_id"],
    )


def downgrade() -> None:
    op.drop_index("uq_refund_requests_active_order", table_name="refund_requests")
    op.create_index(
        "uq_refund_requests_active_order",
        "refund_requests",
        ["order_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('requested', 'approved', 'processing')"),
        sqlite_where=sa.text("status IN ('requested', 'approved', 'processing')"),
    )

    op.drop_constraint(
        "uq_agent_run_projection_tenant_run", "agent_run_projections", type_="unique"
    )
    op.create_unique_constraint(
        "uq_agent_run_projection_run_id", "agent_run_projections", ["run_id"]
    )

    op.drop_constraint(
        "uq_business_action_receipt_scope", "business_action_receipts", type_="unique"
    )
    op.create_unique_constraint(
        "uq_business_action_receipt_scope",
        "business_action_receipts",
        ["actor_id", "operation", "idempotency_key"],
    )

    op.drop_constraint("uq_customer_tenant_email", "customers", type_="unique")
    op.drop_index("ix_customers_email", table_name="customers")
    op.create_index("ix_customers_email", "customers", ["email"], unique=True)

    for table_name in reversed(_TABLES):
        op.drop_index(f"ix_{table_name}_tenant_id", table_name=table_name)
        op.drop_constraint(
            f"fk_{table_name}_tenant_id", table_name=table_name, type_="foreignkey"
        )
        op.drop_column(table_name, "tenant_id")
    op.drop_table("tenants")
