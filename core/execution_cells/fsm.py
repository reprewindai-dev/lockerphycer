"""Finite-state lifecycle contract for a verified governed execution cell.

The FSM is host-owned evidence. It does not grant authority; CAPPO does that.
Transitions are hash chained so a later receipt can detect omission/reordering.
A cryptographic host signature is applied separately to the final attestation.

For the first GitHub consequence the untrusted cell is destroyed before the
trusted broker mints a target credential. This intentionally eliminates overlap
between hostile compute lifetime and upstream target-credential lifetime.
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
    EXECUTING = "EXECUTING"
    CELL_OUTPUT_VALIDATED = "CELL_OUTPUT_VALIDATED"
    CELL_DESTROYED = "CELL_DESTROYED"
    BROKER_PATH_READY = "BROKER_PATH_READY"
    MUTATION_REVALIDATED = "MUTATION_REVALIDATED"
    MUTATION_ATTEMPTED = "MUTATION_ATTEMPTED"
    MUTATION_ACCEPTED = "MUTATION_ACCEPTED"
    MUTATION_DENIED = "MUTATION_DENIED"
    MUTATION_FAILED = "MUTATION_FAILED"
    CREDENTIALS_REVOKED = "CREDENTIALS_REVOKED"
    EVIDENCE_SEALED = "EVIDENCE_SEALED"
    TEARDOWN_ATTESTED = "TEARDOWN_ATTESTED"
    COMPLETED = "COMPLETED"
    FAILED_UNVERIFIED = "FAILED_UNVERIFIED"


_ALLOWED: dict[CellPhase, frozenset[CellPhase]] = {
    CellPhase.REQUESTED: frozenset({CellPhase.IDENTITY_VERIFIED}),
    CellPhase.IDENTITY_VERIFIED: frozenset({CellPhase.LEASE_VALIDATED}),
    CellPhase.LEASE_VALIDATED: frozenset({CellPhase.CELL_ALLOCATED}),
    CellPhase.CELL_ALLOCATED: frozenset({CellPhase.RUNTIME_MEASURED}),
    CellPhase.RUNTIME_MEASURED: frozenset({CellPhase.NETWORK_LOCKED}),
    CellPhase.NETWORK_LOCKED: frozenset({CellPhase.EXECUTING}),
    CellPhase.EXECUTING: frozenset({CellPhase.CELL_OUTPUT_VALIDATED}),
    CellPhase.CELL_OUTPUT_VALIDATED: frozenset({CellPhase.CELL_DESTROYED}),
    CellPhase.CELL_DESTROYED: frozenset({CellPhase.BROKER_PATH_READY}),
    CellPhase.BROKER_PATH_READY: frozenset({CellPhase.MUTATION_REVALIDATED}),
    CellPhase.MUTATION_REVALIDATED: frozenset({CellPhase.MUTATION_ATTEMPTED}),
    CellPhase.MUTATION_ATTEMPTED: frozenset(
        {CellPhase.MUTATION_ACCEPTED, CellPhase.MUTATION_DENIED, CellPhase.MUTATION_FAILED}
    ),
    CellPhase.MUTATION_ACCEPTED: frozenset({CellPhase.CREDENTIALS_REVOKED}),
    CellPhase.MUTATION_DENIED: frozenset({CellPhase.CREDENTIALS_REVOKED}),
    CellPhase.MUTATION_FAILED: frozenset({CellPhase.CREDENTIALS_REVOKED}),
    CellPhase.CREDENTIALS_REVOKED: frozenset({CellPhase.EVIDENCE_SEALED}),
    CellPhase.EVIDENCE_SEALED: frozenset({CellPhase.TEARDOWN_ATTESTED}),
    CellPhase.TEARDOWN_ATTESTED: frozenset({CellPhase.COMPLETED, CellPhase.FAILED_UNVERIFIED}),
    CellPhase.COMPLETED: frozenset(),
    CellPhase.FAILED_UNVERIFIED: frozenset(),
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
    """Strict forward-only lifecycle recorder with explicit outcome branches."""

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
        if not self.transitions:
            if phase != CellPhase.REQUESTED:
                raise LifecycleError(
                    f"invalid lifecycle transition: expected {CellPhase.REQUESTED.value}, got {phase.value}"
                )
        else:
            allowed = _ALLOWED[self.transitions[-1].phase]
            if phase not in allowed:
                expected = ", ".join(sorted(item.value for item in allowed)) or "terminal"
                raise LifecycleError(
                    f"invalid lifecycle transition: expected one of [{expected}], got {phase.value}"
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
        if self.current_phase != CellPhase.COMPLETED:
            raise LifecycleError("verified governed-cell lifecycle is incomplete")
        phases = {transition.phase for transition in self.transitions}
        mandatory = {
            CellPhase.LEASE_VALIDATED,
            CellPhase.RUNTIME_MEASURED,
            CellPhase.NETWORK_LOCKED,
            CellPhase.CELL_DESTROYED,
            CellPhase.MUTATION_REVALIDATED,
            CellPhase.MUTATION_ACCEPTED,
            CellPhase.CREDENTIALS_REVOKED,
            CellPhase.EVIDENCE_SEALED,
            CellPhase.TEARDOWN_ATTESTED,
        }
        missing = mandatory - phases
        if missing:
            raise LifecycleError(
                "verified governed-cell lifecycle is missing mandatory phases: "
                + ",".join(sorted(phase.value for phase in missing))
            )

    def export(self) -> list[dict[str, Any]]:
        return [transition.model_dump(mode="json") for transition in self.transitions]
