"""Cryptographic verification for CAPPO-issued cell authority."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .models import SignedAuthority


class AuthorityVerificationError(ValueError):
    """Raised when a cell authority cannot be trusted."""


def canonical_json_bytes(value: object) -> bytes:
    """Return deterministic UTF-8 JSON for detached signature verification."""

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def authority_payload(authority: SignedAuthority) -> bytes:
    return canonical_json_bytes(authority.envelope.model_dump(mode="json"))


def authority_digest(authority: SignedAuthority) -> str:
    return "sha256:" + hashlib.sha256(authority_payload(authority)).hexdigest()


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception as exc:  # pragma: no cover - implementation-dependent message
        raise AuthorityVerificationError("invalid base64url authority material") from exc


class Ed25519AuthorityVerifier:
    """Verify a detached CAPPO signature using pinned public keys.

    Public keys are raw 32-byte Ed25519 keys encoded as base64url.  Key lookup
    is by explicit ``key_id`` so rotation does not silently broaden trust.
    """

    def __init__(self, public_keys: Mapping[str, str]) -> None:
        self._keys = dict(public_keys)
        if not self._keys:
            raise AuthorityVerificationError("at least one CAPPO authority key is required")

    def verify(self, authority: SignedAuthority) -> str:
        proof = authority.proof
        encoded_key = self._keys.get(proof.key_id)
        if encoded_key is None:
            raise AuthorityVerificationError("unknown CAPPO authority key id")

        key_bytes = _b64url_decode(encoded_key)
        if len(key_bytes) != 32:
            raise AuthorityVerificationError("CAPPO Ed25519 public key must be 32 bytes")

        signature = _b64url_decode(proof.signature_b64url)
        if len(signature) != 64:
            raise AuthorityVerificationError("CAPPO Ed25519 signature must be 64 bytes")

        try:
            Ed25519PublicKey.from_public_bytes(key_bytes).verify(
                signature,
                authority_payload(authority),
            )
        except InvalidSignature as exc:
            raise AuthorityVerificationError("CAPPO authority signature is invalid") from exc

        try:
            authority.envelope.assert_current()
        except ValueError as exc:
            raise AuthorityVerificationError(str(exc)) from exc

        return authority_digest(authority)
