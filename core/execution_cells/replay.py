"""Durable replay fencing and cell-success binding for governed authority."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import SignedAuthority


class ReplayDetected(RuntimeError):
    """A one-time authority has already been consumed for this stage."""


class CellSuccessRequired(RuntimeError):
    """A brokered effect has no matching successful disposable-cell result."""


class SQLiteReplayStore:
    """Small host-local durable replay and stage-binding store.

    Each authority may be consumed once per explicit stage. A brokered effect is
    additionally bound to the digest emitted by a *successful* disposable cell,
    preventing callers from skipping the cell and invoking the trusted broker
    directly with an otherwise valid CAPPO authority.
    """

    VALID_STAGES = frozenset({"cell_run", "effect"})

    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS consumed_authority (
                    key_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    grant_id TEXT NOT NULL,
                    execution_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    expires_at TEXT,
                    consumed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (key_id, nonce, stage),
                    UNIQUE (grant_id, stage)
                )
                """
            )
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(consumed_authority)").fetchall()
            }
            if "expires_at" not in columns:
                connection.execute("ALTER TABLE consumed_authority ADD COLUMN expires_at TEXT")

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS successful_cell_output (
                    key_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    grant_id TEXT NOT NULL UNIQUE,
                    execution_id TEXT NOT NULL,
                    effect_digest TEXT NOT NULL,
                    cell_id TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (key_id, nonce)
                )
                """
            )

    @staticmethod
    def _expiry(authority: SignedAuthority) -> str:
        return authority.envelope.expires_at.astimezone(timezone.utc).isoformat()

    def prune_expired(self, now: datetime | None = None) -> None:
        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM successful_cell_output WHERE expires_at <= ?",
                (current,),
            )
            # Legacy rows created before expires_at was introduced are retained;
            # their authority lifetime is unknown and deleting them could reopen replay.
            connection.execute(
                "DELETE FROM consumed_authority WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (current,),
            )
            connection.execute("COMMIT")

    def consume(self, authority: SignedAuthority, stage: str) -> None:
        if stage not in self.VALID_STAGES:
            raise ValueError(f"unsupported replay stage: {stage}")
        self.prune_expired()
        proof = authority.proof
        envelope = authority.envelope

        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO consumed_authority
                        (key_id, nonce, grant_id, execution_id, stage, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proof.key_id,
                        envelope.nonce,
                        envelope.grant_id,
                        envelope.execution_id,
                        stage,
                        self._expiry(authority),
                    ),
                )
                connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise ReplayDetected(f"authority already consumed for stage {stage}") from exc

    def record_cell_success(
        self,
        authority: SignedAuthority,
        *,
        effect_digest: str,
        cell_id: str,
    ) -> None:
        """Persist the exact effect digest emitted by a successful torn-down cell."""
        self.prune_expired()
        proof = authority.proof
        envelope = authority.envelope
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                cell_run = connection.execute(
                    """
                    SELECT 1 FROM consumed_authority
                    WHERE key_id = ? AND nonce = ? AND grant_id = ? AND stage = 'cell_run'
                    """,
                    (proof.key_id, envelope.nonce, envelope.grant_id),
                ).fetchone()
                if cell_run is None:
                    connection.execute("ROLLBACK")
                    raise CellSuccessRequired("cell_run stage was not consumed")
                connection.execute(
                    """
                    INSERT INTO successful_cell_output
                        (key_id, nonce, grant_id, execution_id, effect_digest, cell_id, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proof.key_id,
                        envelope.nonce,
                        envelope.grant_id,
                        envelope.execution_id,
                        effect_digest,
                        cell_id,
                        self._expiry(authority),
                    ),
                )
                connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise ReplayDetected("successful cell output already recorded for this authority") from exc

    def require_cell_success(self, authority: SignedAuthority, *, effect_digest: str) -> str:
        """Return the originating cell id only for an exact successful output digest."""
        self.prune_expired()
        proof = authority.proof
        envelope = authority.envelope
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT effect_digest, cell_id, expires_at
                FROM successful_cell_output
                WHERE key_id = ? AND nonce = ? AND grant_id = ? AND execution_id = ?
                """,
                (
                    proof.key_id,
                    envelope.nonce,
                    envelope.grant_id,
                    envelope.execution_id,
                ),
            ).fetchone()
        if row is None:
            raise CellSuccessRequired("brokered effect requires a prior successful cell run")
        stored_digest, cell_id, expires_at = row
        if stored_digest != effect_digest:
            raise CellSuccessRequired("brokered effect does not match successful cell output")
        if expires_at <= datetime.now(timezone.utc).isoformat():
            raise CellSuccessRequired("successful cell binding has expired")
        return str(cell_id)
