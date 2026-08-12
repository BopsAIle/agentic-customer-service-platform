"""add stable action correlation to agent-run projections

Revision ID: 20260812_0007
Revises: 20260812_0006
"""

from alembic import op
import sqlalchemy as sa


revision = "20260812_0007"
down_revision = "20260812_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_run_projections",
        sa.Column("action_id", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_run_projections", "action_id")
