"""Finite-state lifecycle contract for a verified governed execution cell.

The FSM is host-owned evidence. It does not grant authority; CAPPO does that.
Transitions are hash chained so a later receipt can detect omission/reordering.
A cryptographic host signature is applied separately to the final attestation.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict

from .authority import canonical_json_bytes


class CellPhase(str, Enum):
    REQUESTED = "REQUESTED"
    IDENTITY_VERIFIED = "IDENTITY_VERIFIED"
    LEASE_VALIDATED = "LEASE_VALIDATED"
    CELL_ALLOCATED = "CELL_ALLOCATED"
    RUNTIME_MEASURED = "RUNTIME_MEASURED"
    NETWORK_LOCKED = "NETWORK_LOCKED"
    CREDENTIAL_PATH_READY = "CREDENTIAL_PATH_READY"
    EXECUTING = "EXECUTING"
    MUTATION_REVALIDATED = "MUTATION_REVALIDATED"
    EVIDENCE_SEALED = "EVIDENCE_SEALED"
    CREDENTIALS_REVOKED = "CREDENTIALS_REVOKED"
    CELL_DESTROYED = "CELL_DESTROYED"


_ORDER = list(CellPhase)
_ALLOWED: dict[CellPhase, CellPhase | None] = {
    phase: (_ORDER[index + 1] if index + 1 < len(_ORDER) else None)
    for index, phase in enumerate(_ORDER)
}


class LifecycleTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: CellPhase
    occurred_at: datetime
    evidence: dict[str, Any]
    previous_hash: str | None
    transition_hash: str


class LifecycleError(RuntimeError):
    pass


def _hash_transition(
    *,
    phase: CellPhase,
    occurred_at: datetime,
    evidence: dict[str, Any],
    previous_hash: str | None,
) -> str:
    payload = {
        "phase": phase.value,
        "occurred_at": occurred_at.astimezone(timezone.utc).isoformat(),
        "evidence": evidence,
        "previous_hash": previous_hash,
    }
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class LifecycleRecorder:
    """Strict forward-only Level-4 lifecycle recorder."""

    def __init__(self) -> None:
        self.transitions: list[LifecycleTransition] = []

    @property
    def current_phase(self) -> CellPhase | None:
        return self.transitions[-1].phase if self.transitions else None

    @property
    def final_hash(self) -> str | None:
        return self.transitions[-1].transition_hash if self.transitions else None

    def advance(
        self,
        phase: CellPhase,
        evidence: dict[str, Any] | None = None,
        *,
        occurred_at: datetime | None = None,
    ) -> LifecycleTransition:
        expected = CellPhase.REQUESTED if not self.transitions else _ALLOWED[self.transitions[-1].phase]
        if expected != phase:
            raise LifecycleError(
                f"invalid lifecycle transition: expected {expected.value if expected else 'terminal'}, got {phase.value}"
            )
        instant = occurred_at or datetime.now(timezone.utc)
        if instant.tzinfo is None or instant.utcoffset() is None:
            raise LifecycleError("lifecycle timestamps must be timezone-aware")
        previous_hash = self.final_hash
        facts = evidence or {}
        transition_hash = _hash_transition(
            phase=phase,
            occurred_at=instant,
            evidence=facts,
            previous_hash=previous_hash,
        )
        transition = LifecycleTransition(
            phase=phase,
            occurred_at=instant,
            evidence=facts,
            previous_hash=previous_hash,
            transition_hash=transition_hash,
        )
        self.transitions.append(transition)
        return transition

    def require_complete(self) -> None:
        if self.current_phase != CellPhase.CELL_DESTROYED:
            raise LifecycleError("Level-4 lifecycle is incomplete")

    def export(self) -> list[dict[str, Any]]:
        return [transition.model_dump(mode="json") for transition in self.transitions]
