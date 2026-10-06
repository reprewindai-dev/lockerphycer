"""Add workspace_wallets and wallet_nonces (Veklom Wallet on Base)

Revision ID: d7a1c9e4f2b6
Revises: c4e8f1a2b3d5
Create Date: 2026-09-30 21:00:00.000000

Tables are only created if absent (dev boots may have run create_all first).
No backfill: a wallet is bound only by a fresh SIWE signature from its owner.
"""

import sqlalchemy as sa
from alembic import op

revision = "d7a1c9e4f2b6"
down_revision = "c4e8f1a2b3d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "workspace_wallets" not in existing:
        op.create_table(
            "workspace_wallets",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("workspace_id", sa.String(36), nullable=False),
            sa.Column("chain_id", sa.Integer(), nullable=False),
            sa.Column("address", sa.String(42), nullable=False),
            sa.Column("source", sa.String(20), nullable=False),
            sa.Column("wallet_provider", sa.String(60), nullable=True),
            sa.Column("signature_kind", sa.String(20), nullable=False),
            sa.Column("siwe_message", sa.Text(), nullable=False),
            sa.Column("siwe_signature", sa.Text(), nullable=False),
            sa.Column("siwe_nonce", sa.String(64), nullable=False, unique=True),
            sa.Column("verified_by", sa.String(255), nullable=False),
            sa.Column("verified_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("workspace_id", "chain_id", "address", name="uq_workspace_wallet_address"),
        )
        op.create_index("ix_workspace_wallets_workspace_id", "workspace_wallets", ["workspace_id"])
        op.create_index("ix_workspace_wallets_chain_id", "workspace_wallets", ["chain_id"])
        op.create_index("ix_workspace_wallets_address", "workspace_wallets", ["address"])

    if "wallet_nonces" not in existing:
        op.create_table(
            "wallet_nonces",
            sa.Column("nonce", sa.String(64), primary_key=True),
            sa.Column("workspace_id", sa.String(36), nullable=False),
            sa.Column("issued_to", sa.String(255), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("used_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_wallet_nonces_workspace_id", "wallet_nonces", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("wallet_nonces")
    op.drop_table("workspace_wallets")
