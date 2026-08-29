from __future__ import annotations

import httpx
import pytest

from core.execution_cells.pgl_client import PGLEvidenceError, RealPGLClient, canonical_digest


def _client(handler):
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, base_url="http://pgl.test")


def test_persist_readback_and_chain_verification() -> None:
    details = {"execution_id": "exec-1", "cell_id": "cell-1", "target": {"before": "a", "after": "b"}}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-api-key") == "test-key"
        if request.method == "POST" and request.url.path == "/api/v1/ledger/events":
            return httpx.Response(
                201,
                json={
                    "event_id": "evt-1",
                    "event_type": "custom",
                    "actor": "predator",
                    "summary": "ok",
                    "details": details,
                    "prev_event_hash": "prev",
                    "event_hash": "hash-1",
                    "created_at": "2026-08-29T10:00:00Z",
                    "persisted": True,
                    "idempotent_replay": False,
                    "chain_head": "hash-1",
                },
            )
        if request.method == "GET" and request.url.path == "/api/v1/ledger/events/evt-1":
            return httpx.Response(
                200,
                json={
                    "event_id": "evt-1",
                    "event_type": "custom",
                    "actor": "predator",
                    "summary": "ok",
                    "details": details,
                    "prev_event_hash": "prev",
                    "event_hash": "hash-1",
                    "created_at": "2026-08-29T10:00:00Z",
                    "persisted": True,
                    "idempotent_replay": False,
                    "chain_head": "hash-1",
                },
            )
        if request.method == "GET" and request.url.path == "/api/v1/ledger/agents/agent-1/verify":
            return httpx.Response(
                200,
                json={
                    "status": "verified",
                    "valid": True,
                    "latest_event_hash": "hash-1",
                    "checked_events": 2,
                    "first_event_at": "2026-08-29T09:00:00Z",
                    "last_event_at": "2026-08-29T10:00:00Z",
                    "errors": [],
                    "reason": "Ledger chain verified.",
                },
            )
        return httpx.Response(404)

    raw_client = _client(handler)
    pgl = RealPGLClient("http://pgl.test", "test-key", client=raw_client)
    witness = pgl.persist_and_verify(
        agent_id="agent-1",
        actor="predator",
        execution_id="exec-1",
        idempotency_key="composition:exec-1",
        details=details,
    )
    assert witness.persisted is True
    assert witness.event_readback_verified is True
    assert witness.ledger_verification is True
    assert witness.details_digest == canonical_digest(details)
    assert witness.event_id == "evt-1"


def test_rejects_readback_that_does_not_match_persisted_consequence() -> None:
    details = {"execution_id": "exec-1", "target": {"after": "good"}}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"event_id": "evt-1", "event_hash": "hash-1", "persisted": True})
        if request.url.path.endswith("/events/evt-1"):
            return httpx.Response(200, json={"event_hash": "hash-1", "details": {"execution_id": "exec-1", "target": {"after": "tampered"}}})
        return httpx.Response(500)

    pgl = RealPGLClient("http://pgl.test", "test-key", client=_client(handler))
    with pytest.raises(PGLEvidenceError, match="readback details"):
        pgl.persist_and_verify(
            agent_id="agent-1",
            actor="predator",
            execution_id="exec-1",
            idempotency_key="composition:exec-1",
            details=details,
        )


def test_rejects_unverified_chain() -> None:
    details = {"execution_id": "exec-1"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"event_id": "evt-1", "event_hash": "hash-1", "persisted": True})
        if request.url.path.endswith("/events/evt-1"):
            return httpx.Response(200, json={"event_hash": "hash-1", "details": details})
        if request.url.path.endswith("/verify"):
            return httpx.Response(200, json={"status": "blocked", "valid": False, "latest_event_hash": "hash-1", "checked_events": 1})
        return httpx.Response(404)

    pgl = RealPGLClient("http://pgl.test", "test-key", client=_client(handler))
    with pytest.raises(PGLEvidenceError, match="not verified"):
        pgl.persist_and_verify(
            agent_id="agent-1",
            actor="predator",
            execution_id="exec-1",
            idempotency_key="composition:exec-1",
            details=details,
        )
