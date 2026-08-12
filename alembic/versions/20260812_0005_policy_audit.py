"""add durable policy audit events

Revision ID: 20260812_0005
Revises: 20260811_0004
"""

from alembic import op
import sqlalchemy as sa


revision = "20260812_0005"
down_revision = "20260811_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "policy_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(length=80), nullable=False),
        sa.Column("agent_run_id", sa.String(length=200), nullable=False),
        sa.Column("request_id", sa.String(length=200), nullable=False),
        sa.Column("conversation_id", sa.String(length=200), nullable=False),
        sa.Column("actor_id", sa.String(length=200), nullable=False),
        sa.Column("actor_type", sa.String(length=40), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("effective_customer_id", sa.Integer(), nullable=False),
        sa.Column("action_id", sa.String(length=200), nullable=True),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("risk_level", sa.Integer(), nullable=False),
        sa.Column("policy_outcome", sa.String(length=40), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("stage", sa.String(length=60), nullable=False),
        sa.Column("confirmation_status", sa.String(length=40), nullable=True),
        sa.Column("revalidation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("execution_status", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("event_id", name="uq_policy_audit_event_id"),
    )
    op.create_index(
        "ix_policy_audit_events_agent_run_id",
        "policy_audit_events",
        ["agent_run_id"],
    )
    op.create_index(
        "ix_policy_audit_conversation_created",
        "policy_audit_events",
        ["conversation_id", "created_at", "id"],
    )
    op.create_index(
        "ix_policy_audit_customer_created",
        "policy_audit_events",
        ["effective_customer_id", "created_at", "id"],
    )
    op.create_index(
        "ix_policy_audit_request_created",
        "policy_audit_events",
        ["request_id", "created_at", "id"],
    )
    op.create_index(
        "ix_policy_audit_action_created",
        "policy_audit_events",
        ["action_id", "created_at", "id"],
    )


def downgrade() -> None:
    for name in (
        "ix_policy_audit_action_created",
        "ix_policy_audit_request_created",
        "ix_policy_audit_customer_created",
        "ix_policy_audit_conversation_created",
        "ix_policy_audit_events_agent_run_id",
    ):
        op.drop_index(name, table_name="policy_audit_events")
    op.drop_table("policy_audit_events")
