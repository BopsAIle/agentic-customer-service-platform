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

    for table_name in _TABLES:
        with op.batch_alter_table(table_name, recreate="always") as batch:
            batch.add_column(
                sa.Column(
                    "tenant_id",
                    sa.String(length=200),
                    nullable=False,
                    server_default="default",
                )
            )
            batch.create_foreign_key(
                f"fk_{table_name}_tenant_id",
                "tenants",
                ["tenant_id"],
                ["id"],
            )
            batch.create_index(f"ix_{table_name}_tenant_id", ["tenant_id"])

    with op.batch_alter_table("customers", recreate="always") as batch:
        batch.create_unique_constraint("uq_customer_tenant_email", ["tenant_id", "email"])

    with op.batch_alter_table("business_action_receipts", recreate="always") as batch:
        batch.drop_constraint("uq_business_action_receipt_scope", type_="unique")
        batch.create_unique_constraint(
            "uq_business_action_receipt_scope",
            ["tenant_id", "actor_id", "operation", "idempotency_key"],
        )

    with op.batch_alter_table("refund_requests", recreate="always") as batch:
        batch.drop_index("uq_refund_requests_active_order")
        batch.create_index(
            "uq_refund_requests_active_order",
            ["tenant_id", "order_id"],
            unique=True,
            postgresql_where=sa.text("status IN ('requested', 'approved', 'processing')"),
            sqlite_where=sa.text("status IN ('requested', 'approved', 'processing')"),
        )

    with op.batch_alter_table("agent_run_projections", recreate="always") as batch:
        batch.drop_constraint("uq_agent_run_projection_run_id", type_="unique")
        batch.create_unique_constraint(
            "uq_agent_run_projection_tenant_run", ["tenant_id", "run_id"]
        )

    op.drop_index("ix_customers_email", table_name="customers")
    op.create_index("ix_customers_email", "customers", ["email"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("refund_requests", recreate="always") as batch:
        batch.drop_index("uq_refund_requests_active_order")
        batch.create_index(
            "uq_refund_requests_active_order",
            ["order_id"],
            unique=True,
            postgresql_where=sa.text("status IN ('requested', 'approved', 'processing')"),
            sqlite_where=sa.text("status IN ('requested', 'approved', 'processing')"),
        )

    op.drop_index("ix_customers_email", table_name="customers")
    op.create_index("ix_customers_email", "customers", ["email"], unique=True)

    with op.batch_alter_table("agent_run_projections", recreate="always") as batch:
        batch.drop_constraint("uq_agent_run_projection_tenant_run", type_="unique")
        batch.create_unique_constraint("uq_agent_run_projection_run_id", ["run_id"])

    with op.batch_alter_table("business_action_receipts", recreate="always") as batch:
        batch.drop_constraint("uq_business_action_receipt_scope", type_="unique")
        batch.create_unique_constraint(
            "uq_business_action_receipt_scope", ["actor_id", "operation", "idempotency_key"]
        )

    for table_name in reversed(_TABLES):
        with op.batch_alter_table(table_name, recreate="always") as batch:
            batch.drop_index(f"ix_{table_name}_tenant_id")
            batch.drop_constraint(f"fk_{table_name}_tenant_id", type_="foreignkey")
            batch.drop_column("tenant_id")
    op.drop_table("tenants")
