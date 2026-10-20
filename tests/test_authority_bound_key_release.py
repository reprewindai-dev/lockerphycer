from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.execution_cells.authority import Ed25519AuthorityVerifier, canonical_json_bytes
from core.execution_cells.key_release import (
    AESGCMKeyUnwrapper,
    AuthorityBoundDEKReleaser,
    EncryptedWorkloadBinding,
    KeyReleaseError,
    WrappedDEK,
    dek_wrap_aad,
    workload_binding_digest,
)
from core.execution_cells.models import (
    AuthorityProof,
    AuthorizedExecutionEnvelope,
    CellResourceLimits,
    SignedAuthority,
)


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _binding() -> EncryptedWorkloadBinding:
    return EncryptedWorkloadBinding(
        package_id="pkg-sai-p1",
        state_root="sha256:" + "1" * 64,
        ciphertext_root="sha256:" + "2" * 64,
        capability_id="virtualdb.ai.infer",
        kek_id="lab-kek-1",
    )


def _signed_authority(
    private_key: Ed25519PrivateKey,
    binding: EncryptedWorkloadBinding,
    *,
    runtime_instance: str,
    epoch: int,
    assignment_id: str,
) -> SignedAuthority:
    now = datetime.now(timezone.utc)
    envelope = AuthorizedExecutionEnvelope(
        execution_id=f"exec-{runtime_instance}-{epoch}",
        path_id="path-sai-p1",
        request_id="req-sai-p1",
        idempotency_key=f"idem-{runtime_instance}-{epoch}",
        grant_id=f"grant-{runtime_instance}-{epoch}",
        subject_id="subject-sai-p1",
        tenant_id="tenant-sai-p1",
        workspace_id="workspace-sai-p1",
        capability_id=binding.capability_id,
        semantic_intent_digest=workload_binding_digest(binding),
        resource_constraints=CellResourceLimits(memory_mb=64),
        authority_epoch=epoch,
        assignment_id=assignment_id,
        runtime_kind="lockerphycer-cell",
        runtime_instance=runtime_instance,
        policy_digest="sha256:" + "3" * 64,
        allowed_provider_set=["local-ai"],
        budget_ceiling=1,
        evidence_profile="sai-p1",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=5),
        nonce=f"nonce-{runtime_instance}-{epoch}-123456",
    )
    payload = canonical_json_bytes(envelope.model_dump(mode="json"))
    signature = private_key.sign(payload)
    return SignedAuthority(
        envelope=envelope,
        proof=AuthorityProof(
            key_id="cappo-test-key",
            signature_b64url=_b64url(signature),
        ),
    )


def _verifier(private_key: Ed25519PrivateKey) -> Ed25519AuthorityVerifier:
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return Ed25519AuthorityVerifier({"cappo-test-key": _b64url(public_bytes)})


def _wrapped_dek(binding: EncryptedWorkloadBinding, kek: bytes, dek: bytes) -> WrappedDEK:
    nonce = os.urandom(12)
    ciphertext = AESGCM(kek).encrypt(nonce, dek, dek_wrap_aad(binding))
    return WrappedDEK(
        kek_id=binding.kek_id,
        nonce_b64url=_b64url(nonce),
        ciphertext_b64url=_b64url(ciphertext),
    )


class SpyUnwrapper:
    def __init__(self, result: bytes) -> None:
        self.result = result
        self.called = False

    def unwrap(self, wrapped: WrappedDEK, *, aad: bytes) -> bytes:
        self.called = True
        return self.result


def test_wrong_runtime_denies_before_unwrap() -> None:
    signing_key = Ed25519PrivateKey.generate()
    binding = _binding()
    authority_a = _signed_authority(
        signing_key,
        binding,
        runtime_instance="host-a",
        epoch=1,
        assignment_id="assignment-a",
    )
    spy = SpyUnwrapper(b"d" * 32)
    releaser_b = AuthorityBoundDEKReleaser(
        _verifier(signing_key),
        spy,
        expected_runtime_instance="host-b",
    )
    wrapped = WrappedDEK(
        kek_id=binding.kek_id,
        nonce_b64url=_b64url(b"n" * 12),
        ciphertext_b64url=_b64url(b"c" * 32),
    )

    with pytest.raises(KeyReleaseError, match="different Lockerphycer cell host"):
        releaser_b.release(
            authority_a,
            binding,
            wrapped,
            current_epoch=1,
            current_assignment_id="assignment-a",
        )

    assert spy.called is False


def test_stale_epoch_and_mutated_binding_deny_before_unwrap() -> None:
    signing_key = Ed25519PrivateKey.generate()
    binding = _binding()
    authority = _signed_authority(
        signing_key,
        binding,
        runtime_instance="host-a",
        epoch=1,
        assignment_id="assignment-a",
    )
    spy = SpyUnwrapper(b"d" * 32)
    releaser = AuthorityBoundDEKReleaser(
        _verifier(signing_key),
        spy,
        expected_runtime_instance="host-a",
    )
    wrapped = WrappedDEK(
        kek_id=binding.kek_id,
        nonce_b64url=_b64url(b"n" * 12),
        ciphertext_b64url=_b64url(b"c" * 32),
    )

    with pytest.raises(KeyReleaseError, match="authority epoch is stale"):
        releaser.release(
            authority,
            binding,
            wrapped,
            current_epoch=2,
            current_assignment_id="assignment-a",
        )
    assert spy.called is False

    mutated = binding.model_copy(update={"ciphertext_root": "sha256:" + "9" * 64})
    with pytest.raises(KeyReleaseError, match="not bound to this encrypted workload"):
        releaser.release(
            authority,
            mutated,
            wrapped,
            current_epoch=1,
            current_assignment_id="assignment-a",
        )
    assert spy.called is False


def test_epoch_rebind_releases_same_dek_on_new_host() -> None:
    signing_key = Ed25519PrivateKey.generate()
    binding = _binding()
    kek = os.urandom(32)
    dek = os.urandom(32)
    wrapped = _wrapped_dek(binding, kek, dek)
    verifier = _verifier(signing_key)

    authority_a = _signed_authority(
        signing_key,
        binding,
        runtime_instance="host-a",
        epoch=1,
        assignment_id="assignment-a",
    )
    releaser_a = AuthorityBoundDEKReleaser(
        verifier,
        AESGCMKeyUnwrapper({binding.kek_id: kek}),
        expected_runtime_instance="host-a",
    )
    assert releaser_a.release(
        authority_a,
        binding,
        wrapped,
        current_epoch=1,
        current_assignment_id="assignment-a",
    ) == dek

    authority_b = _signed_authority(
        signing_key,
        binding,
        runtime_instance="host-b",
        epoch=2,
        assignment_id="assignment-b",
    )
    releaser_b = AuthorityBoundDEKReleaser(
        verifier,
        AESGCMKeyUnwrapper({binding.kek_id: kek}),
        expected_runtime_instance="host-b",
    )
    assert releaser_b.release(
        authority_b,
        binding,
        wrapped,
        current_epoch=2,
        current_assignment_id="assignment-b",
    ) == dek


def test_wrapped_dek_tamper_fails_authentication() -> None:
    signing_key = Ed25519PrivateKey.generate()
    binding = _binding()
    kek = os.urandom(32)
    dek = os.urandom(32)
    wrapped = _wrapped_dek(binding, kek, dek)
    raw = bytearray(base64.urlsafe_b64decode(wrapped.ciphertext_b64url + "=" * (-len(wrapped.ciphertext_b64url) % 4)))
    raw[0] ^= 1
    tampered = wrapped.model_copy(update={"ciphertext_b64url": _b64url(bytes(raw))})

    authority = _signed_authority(
        signing_key,
        binding,
        runtime_instance="host-a",
        epoch=1,
        assignment_id="assignment-a",
    )
    releaser = AuthorityBoundDEKReleaser(
        _verifier(signing_key),
        AESGCMKeyUnwrapper({binding.kek_id: kek}),
        expected_runtime_instance="host-a",
    )

    with pytest.raises(KeyReleaseError, match="authentication failed"):
        releaser.release(
            authority,
            binding,
            tampered,
            current_epoch=1,
            current_assignment_id="assignment-a",
        )
