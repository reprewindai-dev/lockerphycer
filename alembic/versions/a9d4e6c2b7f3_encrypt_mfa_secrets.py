"""Encrypt users.mfa_secret at rest

Revision ID: a9d4e6c2b7f3
Revises: e5a7c3b9d1f2
Create Date: 2026-10-06 12:30:00.000000

Data-only migration, no schema change. Every plaintext TOTP secret is rewritten
as ``enc1:<fernet token>`` under the key derived from SECRET_KEY
(core.security.at_rest). Rows already in that format are left alone, so the
migration can be re-run. The column stays String(255): a 32-character secret
encrypts to about 145 characters.

Downgrade decrypts the rows back to plaintext; it needs the same SECRET_KEY.
"""

import sqlalchemy as sa
from alembic import op

from core.security.at_rest import decrypt_secret, encrypt_secret, is_encrypted

revision = "a9d4e6c2b7f3"
down_revision = "e5a7c3b9d1f2"
branch_labels = None
depends_on = None


def _rows(bind):
    return bind.execute(sa.text("SELECT id, mfa_secret FROM users WHERE mfa_secret IS NOT NULL")).fetchall()


def upgrade() -> None:
    bind = op.get_bind()
    for user_id, secret in _rows(bind):
        if is_encrypted(secret):
            continue
        bind.execute(
            sa.text("UPDATE users SET mfa_secret = :value WHERE id = :id"),
            {"value": encrypt_secret(secret), "id": user_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    for user_id, secret in _rows(bind):
        if not is_encrypted(secret):
            continue
        plaintext = decrypt_secret(secret)
        if plaintext is None:
            raise RuntimeError(f"mfa_secret for user {user_id} cannot be decrypted with the current SECRET_KEY")
        bind.execute(
            sa.text("UPDATE users SET mfa_secret = :value WHERE id = :id"),
            {"value": plaintext, "id": user_id},
        )
