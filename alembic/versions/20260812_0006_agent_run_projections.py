"""add durable operator agent-run projections

Revision ID: 20260812_0006
Revises: 20260812_0005
"""

from alembic import op
import sqlalchemy as sa


revision = "20260812_0006"
down_revision = "20260812_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_run_projections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=200), nullable=False),
        sa.Column("request_id", sa.String(length=200), nullable=False),
        sa.Column("conversation_id", sa.String(length=200), nullable=False),
        sa.Column("effective_customer_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.String(length=200), nullable=False),
        sa.Column("actor_type", sa.String(length=40), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("intent", sa.String(length=80), nullable=False),
        sa.Column("request_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("duration_ms", sa.Numeric(14, 3), nullable=False),
        sa.Column("trace_id", sa.String(length=80), nullable=True),
        sa.Column("path", sa.JSON(), nullable=False),
        sa.Column("failure_category", sa.String(length=80), nullable=True),
        sa.Column("degraded_components", sa.JSON(), nullable=False),
        sa.Column("recovery_action", sa.String(length=80), nullable=True),
        sa.Column("memory_item_count", sa.Integer(), nullable=False),
        sa.Column("memory_keys", sa.JSON(), nullable=False),
        sa.Column("memory_types", sa.JSON(), nullable=False),
        sa.Column("tools", sa.JSON(), nullable=False),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("rag_documents", sa.JSON(), nullable=False),
        sa.Column("retrieval_metadata", sa.JSON(), nullable=False),
        sa.Column("trace", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("run_id", name="uq_agent_run_projection_run_id"),
    )
    op.create_index(
        "ix_agent_run_projection_conversation_created",
        "agent_run_projections",
        ["conversation_id", "created_at", "id"],
    )
    op.create_index(
        "ix_agent_run_projection_customer_created",
        "agent_run_projections",
        ["effective_customer_id", "created_at", "id"],
    )
    op.create_index(
        "ix_agent_run_projection_created",
        "agent_run_projections",
        ["created_at", "id"],
    )


def downgrade() -> None:
    for name in (
        "ix_agent_run_projection_created",
        "ix_agent_run_projection_customer_created",
        "ix_agent_run_projection_conversation_created",
    ):
        op.drop_index(name, table_name="agent_run_projections")
    op.drop_table("agent_run_projections")
