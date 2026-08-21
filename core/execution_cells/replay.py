"""Durable replay fencing for governed cell authority."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import SignedAuthority


class ReplayDetected(RuntimeError):
    """A one-time authority has already been consumed for this stage."""


class SQLiteReplayStore:
    """Small host-local durable replay store.

    Each authority may be consumed once per explicit stage.  The two P0 stages
    are intentionally separate: one offline cell invocation may be followed by
    one brokered effect using the same CAPPO authority, but neither stage may be
    replayed.
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
                    consumed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (key_id, nonce, stage),
                    UNIQUE (grant_id, stage)
                )
                """
            )

    def consume(self, authority: SignedAuthority, stage: str) -> None:
        if stage not in self.VALID_STAGES:
            raise ValueError(f"unsupported replay stage: {stage}")
        proof = authority.proof
        envelope = authority.envelope

        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO consumed_authority
                        (key_id, nonce, grant_id, execution_id, stage)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        proof.key_id,
                        envelope.nonce,
                        envelope.grant_id,
                        envelope.execution_id,
                        stage,
                    ),
                )
                connection.execute("COMMIT")
        except sqlite3.IntegrityError as exc:
            raise ReplayDetected(f"authority already consumed for stage {stage}") from exc
