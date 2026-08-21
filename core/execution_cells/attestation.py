"""Host-signed DSSE attestations for governed-cell enforcement evidence.

These attestations are evidence, not authority. CAPPO remains the issuer of
consequence authority. GnomLedger/PGL is expected to durably seal the DSSE
object alongside the CAPPO authority and resulting effect evidence.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .authority import canonical_json_bytes


DSSE_PAYLOAD_TYPE = "application/vnd.veklom.governed-cell-attestation.v1+json"


class AttestationError(RuntimeError):
    pass


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except Exception as exc:  # pragma: no cover - defensive guard
        raise AttestationError("invalid base64url host attestation key") from exc


def dsse_pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE Pre-Authentication Encoding (PAE)."""
    return (
        b"DSSEv1 "
        + str(len(payload_type.encode("utf-8"))).encode("ascii")
        + b" "
        + payload_type.encode("utf-8")
        + b" "
        + str(len(payload)).encode("ascii")
        + b" "
        + payload
    )


@dataclass(frozen=True)
class HostAttestationSigner:
    key_id: str
    private_key: Ed25519PrivateKey

    @classmethod
    def from_b64url_seed(cls, *, key_id: str, seed_b64url: str) -> "HostAttestationSigner":
        raw = _b64url_decode(seed_b64url)
        if len(raw) != 32:
            raise AttestationError("host attestation Ed25519 seed must be exactly 32 bytes")
        return cls(key_id=key_id, private_key=Ed25519PrivateKey.from_private_bytes(raw))

    def public_key_b64url(self) -> str:
        raw = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    def sign_statement(self, statement: dict[str, Any]) -> dict[str, Any]:
        payload = canonical_json_bytes(statement)
        signature = self.private_key.sign(dsse_pae(DSSE_PAYLOAD_TYPE, payload))
        return {
            "payloadType": DSSE_PAYLOAD_TYPE,
            "payload": _b64(payload),
            "signatures": [{"keyid": self.key_id, "sig": _b64(signature)}],
        }


def build_enforcement_statement(
    *,
    execution_id: str,
    grant_id: str,
    authority_digest: str,
    cell_id: str,
    runtime: str,
    runtime_measurements: dict[str, Any],
    network_evidence: dict[str, Any],
    lifecycle: list[dict[str, Any]],
    lifecycle_final_hash: str,
    teardown_confirmed: bool,
    credential_revocation_confirmed: bool,
    effect: dict[str, Any] | None,
    security_status: str,
) -> dict[str, Any]:
    if not teardown_confirmed:
        raise AttestationError("cannot issue completion attestation without confirmed teardown")
    return {
        "_type": "https://veklom.dev/attestations/governed-cell/v1",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "execution_id": execution_id,
        "grant_id": grant_id,
        "authority_digest": authority_digest,
        "cell_id": cell_id,
        "runtime": runtime,
        "runtime_measurements": runtime_measurements,
        "network_evidence": network_evidence,
        "lifecycle": lifecycle,
        "lifecycle_final_hash": lifecycle_final_hash,
        "teardown_confirmed": teardown_confirmed,
        "credential_revocation_confirmed": credential_revocation_confirmed,
        "effect": effect,
        "security_status": security_status,
    }
