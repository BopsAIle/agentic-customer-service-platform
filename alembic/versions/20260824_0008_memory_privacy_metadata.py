"""add structured memory privacy metadata

Revision ID: 20260824_0008
Revises: 20260812_0007
"""

import sqlalchemy as sa

from alembic import op

revision = "20260824_0008"
down_revision = "20260812_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_records",
        sa.Column(
            "sensitivity_level", sa.String(length=20), nullable=False, server_default="internal"
        ),
    )
    op.add_column(
        "memory_records",
        sa.Column(
            "retention_policy", sa.String(length=20), nullable=False, server_default="standard"
        ),
    )
    op.add_column(
        "memory_records",
        sa.Column(
            "redaction_state", sa.String(length=20), nullable=False, server_default="not_required"
        ),
    )


def downgrade() -> None:
    op.drop_column("memory_records", "redaction_state")
    op.drop_column("memory_records", "retention_policy")
    op.drop_column("memory_records", "sensitivity_level")
