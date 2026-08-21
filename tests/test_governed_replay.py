from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.execution_cells.authority import canonical_json_bytes
from core.execution_cells.models import (
    AuthorityProof,
    AuthorizedExecutionEnvelope,
    CellResourceLimits,
    SignedAuthority,
)
from core.execution_cells.replay import ReplayDetected, SQLiteReplayStore


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _authority() -> SignedAuthority:
    private_key = Ed25519PrivateKey.generate()
    now = datetime.now(timezone.utc)
    envelope = AuthorizedExecutionEnvelope(
        execution_id="exec-replay",
        path_id="path-replay",
        request_id="req-replay",
        idempotency_key="idem-replay",
        grant_id="grant-replay",
        subject_id="agent-replay",
        delegation_id=None,
        tenant_id="tenant",
        workspace_id="workspace",
        capability_id="github.file.update",
        semantic_intent_digest="sha256:" + "a" * 64,
        resource_constraints=CellResourceLimits(),
        authority_epoch=1,
        assignment_id="assignment",
        runtime_kind="lockerphycer-cell",
        runtime_instance="host",
        policy_digest="sha256:policy",
        allowed_provider_set=["github"],
        budget_ceiling=100,
        evidence_profile="pgl-required",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=5),
        nonce="0123456789abcdef0123456789abcdef",
    )
    signature = private_key.sign(canonical_json_bytes(envelope.model_dump(mode="json")))
    return SignedAuthority(
        envelope=envelope,
        proof=AuthorityProof(key_id="kid", signature_b64url=_b64url(signature)),
    )


def test_each_stage_is_one_time_and_persists_across_store_instances(tmp_path):
    path = str(tmp_path / "replay.sqlite3")
    authority = _authority()
    store = SQLiteReplayStore(path)

    store.consume(authority, "cell_run")
    store.consume(authority, "effect")

    reopened = SQLiteReplayStore(path)
    with pytest.raises(ReplayDetected, match="cell_run"):
        reopened.consume(authority, "cell_run")
    with pytest.raises(ReplayDetected, match="effect"):
        reopened.consume(authority, "effect")


def test_unknown_replay_stage_is_rejected(tmp_path):
    store = SQLiteReplayStore(str(tmp_path / "replay.sqlite3"))
    with pytest.raises(ValueError, match="unsupported replay stage"):
        store.consume(_authority(), "unknown")
