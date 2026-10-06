"""Add analytics_events (first-party, cookieless funnel analytics)

Revision ID: f3b9d2e7a4c1
Revises: d7a1c9e4f2b6 (chained after the wallet tables so the history has one head)
Create Date: 2026-09-30 21:00:00.000000

New table only; no shared table is altered. The session-to-account link is an
``analytics_session_linked`` row in the existing activation_events table.
No IP address, user agent or cookie value is stored.
"""

import sqlalchemy as sa
from alembic import op

revision = "f3b9d2e7a4c1"
down_revision = "d7a1c9e4f2b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "analytics_events" in set(sa.inspect(bind).get_table_names()):
        return  # dev boots may have run create_all first
    op.create_table(
        "analytics_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_name", sa.String(40), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("host", sa.String(16), nullable=False),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("referrer_domain", sa.String(253), nullable=True),
        sa.Column("utm_source", sa.String(100), nullable=True),
        sa.Column("utm_medium", sa.String(100), nullable=True),
        sa.Column("utm_campaign", sa.String(100), nullable=True),
        sa.Column("utm_term", sa.String(100), nullable=True),
        sa.Column("utm_content", sa.String(100), nullable=True),
        sa.Column("props", sa.JSON(), nullable=False),
        sa.Column("country", sa.String(2), nullable=True),
        sa.Column("aggregate_only", sa.Boolean(), nullable=False),
        sa.Column("client_ts", sa.DateTime(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
    )
    for col in ("event_name", "session_id", "host", "received_at"):
        op.create_index(f"ix_analytics_events_{col}", "analytics_events", [col])


def downgrade() -> None:
    op.drop_table("analytics_events")
