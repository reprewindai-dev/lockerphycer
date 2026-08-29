"""Real PGL network client for compositional consequence evidence.

This module intentionally has no mock fallback.  A foundational composition
probe must cross the actual PGL HTTP boundary, persist one exact event, read it
back, and verify the agent ledger chain.  If any of those operations fail, the
probe remains unverified rather than manufacturing a success assertion.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx


class PGLEvidenceError(RuntimeError):
    """PGL could not persist or independently verify composition evidence."""


def canonical_digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class PGLCompositionWitness:
    event_id: str
    event_hash: str
    previous_event_hash: str | None
    chain_head: str
    details_digest: str
    persisted: bool
    event_readback_verified: bool
    ledger_verification: bool
    checked_events: int


class RealPGLClient:
    """Minimal fail-closed client for GnomLedger/PGL's authenticated ledger API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_seconds: float = 10.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("PGL base_url is required")
        if not api_key.strip():
            raise ValueError("PGL API key is required")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=False)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @property
    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key, "content-type": "application/json"}

    @staticmethod
    def _json_object(response: httpx.Response, context: str) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise PGLEvidenceError(f"{context} returned non-JSON evidence") from exc
        if not isinstance(body, dict):
            raise PGLEvidenceError(f"{context} returned a non-object payload")
        return body

    def persist_and_verify(
        self,
        *,
        agent_id: str,
        actor: str,
        execution_id: str,
        idempotency_key: str,
        details: dict[str, Any],
    ) -> PGLCompositionWitness:
        """Persist exact composition evidence, read it back, then verify the chain."""
        if details.get("execution_id") != execution_id:
            raise PGLEvidenceError("composition details execution_id is not exact")

        expected_details_digest = canonical_digest(details)
        create = self._client.post(
            f"{self.base_url}/api/v1/ledger/events",
            headers=self._headers,
            json={
                "agent_id": agent_id,
                "event_type": "custom",
                "actor": actor,
                "summary": f"Lockerphycer composition consequence {execution_id}"[:255],
                "details": details,
                "idempotency_key": idempotency_key,
            },
        )
        if create.status_code != 201:
            raise PGLEvidenceError(f"PGL event persistence failed with HTTP {create.status_code}")
        created = self._json_object(create, "PGL event persistence")
        event_id = created.get("event_id")
        event_hash = created.get("event_hash")
        if not isinstance(event_id, str) or not event_id:
            raise PGLEvidenceError("PGL did not return an event_id")
        if not isinstance(event_hash, str) or not event_hash:
            raise PGLEvidenceError("PGL did not return an event_hash")
        if created.get("persisted") is not True:
            raise PGLEvidenceError("PGL did not confirm persistence")

        readback = self._client.get(
            f"{self.base_url}/api/v1/ledger/events/{event_id}",
            headers=self._headers,
        )
        if readback.status_code != 200:
            raise PGLEvidenceError(f"PGL event readback failed with HTTP {readback.status_code}")
        observed = self._json_object(readback, "PGL event readback")
        observed_details = observed.get("details")
        if not isinstance(observed_details, dict):
            raise PGLEvidenceError("PGL readback omitted event details")
        if canonical_digest(observed_details) != expected_details_digest:
            raise PGLEvidenceError("PGL readback details do not match persisted consequence evidence")
        if observed.get("event_hash") != event_hash:
            raise PGLEvidenceError("PGL event hash changed between persistence and readback")

        verify = self._client.get(
            f"{self.base_url}/api/v1/ledger/agents/{agent_id}/verify",
            headers=self._headers,
        )
        if verify.status_code != 200:
            raise PGLEvidenceError(f"PGL chain verification failed with HTTP {verify.status_code}")
        chain = self._json_object(verify, "PGL chain verification")
        if chain.get("status") != "verified" or chain.get("valid") is not True:
            raise PGLEvidenceError("PGL ledger chain is not verified")
        latest = chain.get("latest_event_hash")
        if not isinstance(latest, str) or not latest:
            raise PGLEvidenceError("PGL chain verification omitted latest_event_hash")
        checked = chain.get("checked_events")
        if not isinstance(checked, int) or checked < 1:
            raise PGLEvidenceError("PGL chain verification did not check any events")

        return PGLCompositionWitness(
            event_id=event_id,
            event_hash=event_hash,
            previous_event_hash=created.get("prev_event_hash") if isinstance(created.get("prev_event_hash"), str) else None,
            chain_head=latest,
            details_digest=expected_details_digest,
            persisted=True,
            event_readback_verified=True,
            ledger_verification=True,
            checked_events=checked,
        )
