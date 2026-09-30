"""Add workspace entitlements, credit ledger, activation events, Stripe webhook events

Revision ID: c4e8f1a2b3d5
Revises: a1b2c3d4e5f6
Create Date: 2026-09-30 18:00:00.000000

Backfill: every existing workspace gets a workspace_entitlements row.
  * The owner's earliest workspace gets Welcome anchored at workspaces.created_at
    (so a workspace older than WELCOME_DAYS is already past Welcome; the app's
    lazy roll moves it to Developer, writes the grant and emits welcome_ended
    on first access).
  * Any other workspace of the same owner gets no Welcome (never recurs) and
    starts a Developer period now.
Tables are only created if absent (dev boots may have run create_all first).
"""

import os
import uuid
from datetime import datetime, timedelta

import sqlalchemy as sa
from alembic import op

revision = "c4e8f1a2b3d5"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    if "workspace_entitlements" not in existing:
        op.create_table(
            "workspace_entitlements",
            sa.Column("workspace_id", sa.String(36), primary_key=True),
            sa.Column("owner_key", sa.String(255), nullable=False),
            sa.Column("plan", sa.String(40), nullable=False),
            sa.Column("welcome_started_at", sa.DateTime(), nullable=True),
            sa.Column("welcome_ends_at", sa.DateTime(), nullable=True),
            sa.Column("welcome_owner_key", sa.String(255), nullable=True, unique=True),
            sa.Column("welcome_ended_at", sa.DateTime(), nullable=True),
            sa.Column("converted_at", sa.DateTime(), nullable=True),
            sa.Column("period_start", sa.DateTime(), nullable=False),
            sa.Column("period_end", sa.DateTime(), nullable=False),
            sa.Column("period_allowance", sa.Integer(), nullable=False),
            sa.Column("period_used", sa.Integer(), nullable=False),
            sa.Column("topup_balance", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_workspace_entitlements_owner_key", "workspace_entitlements", ["owner_key"])

    if "credit_ledger" not in existing:
        op.create_table(
            "credit_ledger",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("workspace_id", sa.String(36), nullable=False),
            sa.Column("entry_type", sa.String(20), nullable=False),
            sa.Column("direction", sa.String(6), nullable=False),
            sa.Column("action_type", sa.String(60), nullable=True),
            sa.Column("credits", sa.Integer(), nullable=False),
            sa.Column("allowance_debit", sa.Integer(), nullable=False),
            sa.Column("topup_debit", sa.Integer(), nullable=False),
            sa.Column("balance_after", sa.Integer(), nullable=False),
            sa.Column("idempotency_key", sa.String(255), nullable=True, unique=True),
            sa.Column("reverses_entry_id", sa.String(36), nullable=True),
            sa.Column("mount_id", sa.String(160), nullable=True),
            sa.Column("execution_ref", sa.String(160), nullable=True),
            sa.Column("operation_ref", sa.String(160), nullable=True),
            sa.Column("principal", sa.String(255), nullable=True),
            sa.Column("settlement_rail", sa.String(40), nullable=False),
            sa.Column("settlement_ref", sa.String(255), nullable=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        for col in ("workspace_id", "entry_type", "action_type", "reverses_entry_id",
                    "mount_id", "execution_ref", "principal", "created_at"):
            op.create_index(f"ix_credit_ledger_{col}", "credit_ledger", [col])

    if "activation_events" not in existing:
        op.create_table(
            "activation_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("event_name", sa.String(60), nullable=False),
            sa.Column("workspace_id", sa.String(36), nullable=True),
            sa.Column("user_id", sa.String(255), nullable=True),
            sa.Column("source", sa.String(40), nullable=False),
            sa.Column("ref", sa.String(255), nullable=True),
            sa.Column("dedupe_key", sa.String(255), nullable=True, unique=True),
            sa.Column("details", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        for col in ("event_name", "workspace_id", "user_id", "created_at"):
            op.create_index(f"ix_activation_events_{col}", "activation_events", [col])

    if "stripe_webhook_events" not in existing:
        op.create_table(
            "stripe_webhook_events",
            sa.Column("event_id", sa.String(255), primary_key=True),
            sa.Column("event_type", sa.String(120), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("workspace_id", sa.String(36), nullable=True),
            sa.Column("result", sa.String(255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("processed_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_stripe_webhook_events_event_type", "stripe_webhook_events", ["event_type"])
        op.create_index("ix_stripe_webhook_events_workspace_id", "stripe_webhook_events", ["workspace_id"])

    _backfill(bind)


def _backfill(bind) -> None:
    welcome_days = _int_env("WELCOME_DAYS", 14)
    ceiling = _int_env("WELCOME_CREDIT_CEILING", 100_000)
    period_days = _int_env("ENTITLEMENT_PERIOD_DAYS", 30)
    now = datetime.utcnow()

    workspaces = bind.execute(
        sa.text("SELECT id, owner_id, created_at FROM workspaces ORDER BY created_at ASC, id ASC")
    ).fetchall()
    have = {r[0] for r in bind.execute(sa.text("SELECT workspace_id FROM workspace_entitlements"))}
    welcomed = {
        r[0] for r in bind.execute(
            sa.text("SELECT welcome_owner_key FROM workspace_entitlements WHERE welcome_owner_key IS NOT NULL")
        )
    }
    ent_t = sa.table(
        "workspace_entitlements", *(sa.column(c) for c in (
            "workspace_id", "owner_key", "plan", "welcome_started_at", "welcome_ends_at",
            "welcome_owner_key", "period_start", "period_end", "period_allowance",
            "period_used", "topup_balance", "created_at")),
    )
    ledger_t = sa.table(
        "credit_ledger", *(sa.column(c) for c in (
            "id", "workspace_id", "entry_type", "direction", "credits", "allowance_debit",
            "topup_debit", "balance_after", "idempotency_key", "settlement_rail",
            "description", "created_at")),
    )
    for ws_id, owner_id, created_at in workspaces:
        if ws_id in have:
            continue
        owner_key = (owner_id or "").strip().lower() or f"workspace:{ws_id}"
        anchor = created_at or now
        if owner_key not in welcomed:
            welcomed.add(owner_key)
            row = dict(welcome_started_at=anchor, welcome_ends_at=anchor + timedelta(days=welcome_days),
                       welcome_owner_key=owner_key, period_start=anchor,
                       period_end=anchor + timedelta(days=welcome_days), period_allowance=ceiling)
            label = "Welcome safe-use ceiling (backfill)"
        else:
            row = dict(welcome_started_at=None, welcome_ends_at=None, welcome_owner_key=None,
                       period_start=now, period_end=now + timedelta(days=period_days), period_allowance=250)
            label = "developer allowance (backfill; Welcome already used by owner)"
        op.bulk_insert(ent_t, [dict(workspace_id=ws_id, owner_key=owner_key, plan="developer",
                                    period_used=0, topup_balance=0, created_at=now, **row)])
        if now < row["period_end"]:
            op.bulk_insert(ledger_t, [dict(
                id=str(uuid.uuid4()), workspace_id=ws_id, entry_type="grant", direction="credit",
                credits=row["period_allowance"], allowance_debit=0, topup_debit=0,
                balance_after=row["period_allowance"],
                idempotency_key=f"grant:{ws_id}:{row['period_start'].isoformat()}",
                settlement_rail="off_chain_ledger", description=label, created_at=now)])


def downgrade() -> None:
    op.drop_table("stripe_webhook_events")
    op.drop_table("activation_events")
    op.drop_table("credit_ledger")
    op.drop_table("workspace_entitlements")
