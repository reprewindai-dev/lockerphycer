"""Store only SHA-256 digests of session tokens

Revision ID: e5a7c3b9d1f2
Revises: f3b9d2e7a4c1
Create Date: 2026-10-06 12:00:00.000000

user_sessions.session_token / refresh_token held the bearer tokens verbatim,
so a read of the table was a replayable login. This adds session_token_hash
and refresh_token_hash, fills them from the existing rows and drops the
plaintext columns. Live sessions keep working: the API still receives the raw
token and looks it up by digest (core.security.auth.hash_token).

Downgrade is lossy by design: it restores the plaintext columns (nullable, no
unique constraint) but cannot recover the tokens from their digests, so it
deactivates every session and every user signs in again. Upgrading again
retires those token-less rows under unique "revoked:<id>" markers.
"""

import hashlib

import sqlalchemy as sa
from alembic import op

revision = "e5a7c3b9d1f2"
down_revision = "f3b9d2e7a4c1"
branch_labels = None
depends_on = None

TABLE = "user_sessions"
SESSION_INDEX = "ix_user_sessions_session_token_hash"
REFRESH_INDEX = "ix_user_sessions_refresh_token_hash"


def _digest(token: str) -> str:
    # Same function as core.security.auth.hash_token, inlined so the migration
    # does not depend on application code that may change later.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _columns(bind) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(TABLE)}


def _indexes(bind) -> set[str]:
    return {i["name"] for i in sa.inspect(bind).get_indexes(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _columns(bind)

    if "session_token_hash" not in columns:  # dev boots may have run create_all first
        with op.batch_alter_table(TABLE) as batch:
            batch.add_column(sa.Column("session_token_hash", sa.String(64), nullable=True))
            batch.add_column(sa.Column("refresh_token_hash", sa.String(64), nullable=True))

    if "session_token" in columns:
        rows = bind.execute(sa.text(f"SELECT id, session_token, refresh_token FROM {TABLE}")).fetchall()
        for row_id, session_token, refresh_token in rows:
            if session_token and refresh_token:
                params = {"s": _digest(session_token), "r": _digest(refresh_token), "i": row_id, "active": None}
            else:
                # A row with no token was never usable; give it a unique marker and retire it.
                params = {"s": f"revoked:{row_id}", "r": f"revoked:{row_id}", "i": row_id, "active": False}
            bind.execute(
                sa.text(
                    f"UPDATE {TABLE} SET session_token_hash = :s, refresh_token_hash = :r, "
                    f"is_active = COALESCE(:active, is_active) WHERE id = :i"
                ),
                params,
            )
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_column("session_token")
            batch.drop_column("refresh_token")

    with op.batch_alter_table(TABLE) as batch:
        batch.alter_column("session_token_hash", existing_type=sa.String(64), nullable=False)
        batch.alter_column("refresh_token_hash", existing_type=sa.String(64), nullable=False)

    indexes = _indexes(bind)
    if SESSION_INDEX not in indexes:
        op.create_index(SESSION_INDEX, TABLE, ["session_token_hash"], unique=True)
    if REFRESH_INDEX not in indexes:
        op.create_index(REFRESH_INDEX, TABLE, ["refresh_token_hash"])


def downgrade() -> None:
    bind = op.get_bind()

    if "session_token" not in _columns(bind):
        with op.batch_alter_table(TABLE) as batch:
            batch.add_column(sa.Column("session_token", sa.Text(), nullable=True))
            batch.add_column(sa.Column("refresh_token", sa.Text(), nullable=True))

    # Digests cannot be turned back into tokens: every session is revoked.
    bind.execute(sa.text(f"UPDATE {TABLE} SET is_active = :inactive"), {"inactive": False})

    indexes = _indexes(bind)
    for name in (SESSION_INDEX, REFRESH_INDEX):
        if name in indexes:
            op.drop_index(name, table_name=TABLE)

    with op.batch_alter_table(TABLE) as batch:
        batch.drop_column("session_token_hash")
        batch.drop_column("refresh_token_hash")
