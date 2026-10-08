"""Add agreement_acceptances (what each person accepted at signup)

Revision ID: b8c2e4f6a1d3
Revises: a9d4e6c2b7f3
Create Date: 2026-10-08 17:00:00.000000

New table only; no existing table is altered. Before this, signup acceptance was posted
to a route no service implemented, so no acceptance was ever recorded.
"""

import sqlalchemy as sa
from alembic import op

revision = "b8c2e4f6a1d3"
down_revision = "a9d4e6c2b7f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "agreement_acceptances" in set(sa.inspect(bind).get_table_names()):
        return  # dev boots may have run create_all first
    op.create_table(
        "agreement_acceptances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_type", sa.String(40), nullable=False),
        sa.Column("document_version", sa.String(20), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_id", "document_type", "document_version", name="uq_agreement_acceptance"),
    )
    op.create_index("ix_agreement_acceptances_user_id", "agreement_acceptances", ["user_id"])


def downgrade() -> None:
    op.drop_table("agreement_acceptances")
