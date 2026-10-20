"""Authority-gated DEK release for encrypted governed workloads.

This module deliberately keeps cryptographic key release on the trusted host side.
A workload package may carry ciphertext and a wrapped DEK, but possession of those
artifacts is insufficient to recover plaintext. Lockerphycer verifies CAPPO
execution authority, runtime ownership, epoch/assignment freshness, and the
package binding before invoking any key-unwrapping primitive.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping, Set
from typing import Literal, Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, Field

from .authority import canonical_json_bytes
from .models import SignedAuthority


_SHA256 = r"^sha256:[0-9a-f]{64}$"


class KeyReleaseError(ValueError):
    """Raised when a governed workload DEK must not be released."""


class EncryptedWorkloadBinding(BaseModel):
    """Portable package facts that CAPPO binds through semantic_intent_digest.

    The binding contains no plaintext secret. ``ciphertext_root`` commits to the
    encrypted payload set, while ``state_root`` identifies the logical workload
    state whose confidentiality and execution are being governed.
    """

    model_config = ConfigDict(extra="forbid")

    package_id: str = Field(min_length=1)
    state_root: str = Field(pattern=_SHA256)
    ciphertext_root: str = Field(pattern=_SHA256)
    capability_id: str = Field(min_length=1)
    kek_id: str = Field(min_length=1)


class WrappedDEK(BaseModel):
    """A 256-bit DEK wrapped under an external Lockerphycer-controlled KEK."""

    model_config = ConfigDict(extra="forbid")

    algorithm: Literal["AES-256-GCM"] = "AES-256-GCM"
    kek_id: str = Field(min_length=1)
    nonce_b64url: str = Field(min_length=16)
    ciphertext_b64url: str = Field(min_length=24)


class AuthorityVerifier(Protocol):
    def verify(self, authority: SignedAuthority) -> str: ...


class DEKUnwrapper(Protocol):
    def unwrap(self, wrapped: WrappedDEK, *, aad: bytes) -> bytes: ...


def _b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception as exc:  # pragma: no cover - decoder message is platform-specific
        raise KeyReleaseError("invalid base64url wrapped-key material") from exc


def workload_binding_payload(binding: EncryptedWorkloadBinding) -> bytes:
    """Return the domain-separated canonical package binding."""

    return canonical_json_bytes(
        {
            "domain": "VEKLOM-WORKLOAD-BINDING-v1",
            "binding": binding.model_dump(mode="json"),
        }
    )


def workload_binding_digest(binding: EncryptedWorkloadBinding) -> str:
    return "sha256:" + hashlib.sha256(workload_binding_payload(binding)).hexdigest()


def dek_wrap_aad(binding: EncryptedWorkloadBinding) -> bytes:
    """Bind wrapped-key authentication to the exact encrypted workload package."""

    return canonical_json_bytes(
        {
            "domain": "VEKLOM-DEK-WRAP-v1",
            "binding_digest": workload_binding_digest(binding),
        }
    )


class AESGCMKeyUnwrapper:
    """Lab-grade KEK provider for AES-256-GCM wrapped DEKs.

    KEKs are injected from trusted host configuration and must never be stored in
    the portable workload package. Production deployments can replace this
    provider with TPM/KMS/enclave-backed unwrapping without changing the release
    gate.
    """

    def __init__(self, keys: Mapping[str, bytes]) -> None:
        self._keys = dict(keys)
        if not self._keys:
            raise KeyReleaseError("at least one KEK is required")
        for key_id, key in self._keys.items():
            if not key_id:
                raise KeyReleaseError("KEK id must not be empty")
            if len(key) != 32:
                raise KeyReleaseError("AES-256-GCM KEKs must be exactly 32 bytes")

    def unwrap(self, wrapped: WrappedDEK, *, aad: bytes) -> bytes:
        key = self._keys.get(wrapped.kek_id)
        if key is None:
            raise KeyReleaseError("unknown KEK id")

        nonce = _b64url_decode(wrapped.nonce_b64url)
        ciphertext = _b64url_decode(wrapped.ciphertext_b64url)
        if len(nonce) != 12:
            raise KeyReleaseError("AES-GCM wrapped-key nonce must be 12 bytes")
        if len(ciphertext) < 16:
            raise KeyReleaseError("wrapped DEK ciphertext is too short")

        try:
            dek = AESGCM(key).decrypt(nonce, ciphertext, aad)
        except InvalidTag as exc:
            raise KeyReleaseError("wrapped DEK authentication failed") from exc
        if len(dek) != 32:
            raise KeyReleaseError("released DEK must be exactly 32 bytes")
        return dek


class AuthorityBoundDEKReleaser:
    """Fail closed before secret material is unwrapped or exposed."""

    def __init__(
        self,
        verifier: AuthorityVerifier,
        unwrapper: DEKUnwrapper,
        *,
        expected_runtime_instance: str,
        allowed_capabilities: Set[str] | None = None,
    ) -> None:
        runtime_instance = expected_runtime_instance.strip()
        if not runtime_instance:
            raise KeyReleaseError("expected runtime instance is required")
        self._verifier = verifier
        self._unwrapper = unwrapper
        self._expected_runtime_instance = runtime_instance
        self._allowed_capabilities = frozenset(
            allowed_capabilities or {"virtualdb.ai.infer"}
        )
        if not self._allowed_capabilities:
            raise KeyReleaseError("at least one key-release capability is required")

    def release(
        self,
        authority: SignedAuthority,
        binding: EncryptedWorkloadBinding,
        wrapped_dek: WrappedDEK,
        *,
        current_epoch: int,
        current_assignment_id: str,
    ) -> bytes:
        """Release the DEK only after every execution/key predicate is satisfied."""

        # Signature and lifetime are checked before any secret operation.
        self._verifier.verify(authority)
        envelope = authority.envelope

        if envelope.runtime_instance != self._expected_runtime_instance:
            raise KeyReleaseError("authority is bound to a different Lockerphycer cell host")
        if envelope.authority_epoch != current_epoch:
            raise KeyReleaseError("authority epoch is stale for key release")
        if envelope.assignment_id != current_assignment_id:
            raise KeyReleaseError("runtime assignment is stale for key release")
        if envelope.capability_id not in self._allowed_capabilities:
            raise KeyReleaseError("capability does not authorize key release")
        if binding.capability_id != envelope.capability_id:
            raise KeyReleaseError("workload capability binding mismatch")
        if wrapped_dek.kek_id != binding.kek_id:
            raise KeyReleaseError("wrapped DEK KEK binding mismatch")

        expected_intent = workload_binding_digest(binding)
        if envelope.semantic_intent_digest != expected_intent:
            raise KeyReleaseError("authority is not bound to this encrypted workload")

        # No unwrapping occurs above this line. This ordering is the SAI-P1 gate.
        return self._unwrapper.unwrap(wrapped_dek, aad=dek_wrap_aad(binding))
