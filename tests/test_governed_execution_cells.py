from __future__ import annotations

import base64
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.execution_cells.authority import (
    AuthorityVerificationError,
    Ed25519AuthorityVerifier,
    canonical_json_bytes,
)
from core.execution_cells.models import (
    AuthorityProof,
    AuthorizedExecutionEnvelope,
    CellRequest,
    CellResourceLimits,
    SignedAuthority,
)
from core.execution_cells.runtime import CellRuntimeError, OCICellRuntime


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _signed_authority(*, expired: bool = False):
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    now = datetime.now(timezone.utc)
    if expired:
        issued_at = now - timedelta(minutes=5)
        expires_at = now - timedelta(minutes=1)
    else:
        issued_at = now - timedelta(seconds=5)
        expires_at = now + timedelta(minutes=5)

    envelope = AuthorizedExecutionEnvelope(
        execution_id="exec-123",
        path_id="path-1",
        request_id="req-1",
        idempotency_key="idem-1",
        grant_id="grant-1",
        subject_id="agent-1",
        delegation_id=None,
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        capability_id="github.file.update",
        semantic_intent_digest="sha256:intent",
        resource_constraints=CellResourceLimits(
            cpus=0.5,
            memory_mb=128,
            pids=32,
            timeout_seconds=30,
            tmpfs_mb=64,
        ),
        authority_epoch=7,
        assignment_id="assignment-7",
        runtime_kind="lockerphycer-cell",
        runtime_instance="cell-host-1",
        policy_digest="sha256:policy",
        allowed_provider_set=["github"],
        budget_ceiling=500,
        evidence_profile="pgl-required",
        issued_at=issued_at,
        expires_at=expires_at,
        nonce="0123456789abcdef0123456789abcdef",
    )
    payload = canonical_json_bytes(envelope.model_dump(mode="json"))
    proof = AuthorityProof(
        key_id="cappo-test-key",
        signature_b64url=_b64url(private_key.sign(payload)),
    )
    signed = SignedAuthority(envelope=envelope, proof=proof)
    verifier = Ed25519AuthorityVerifier({"cappo-test-key": _b64url(public_key)})
    return signed, verifier


def _request(authority: SignedAuthority, **updates) -> CellRequest:
    data = {
        "authority": authority,
        "image": "ghcr.io/example/executor@sha256:" + "a" * 64,
        "command": ["/executor", "plan-effect"],
        "input_payload": {"path": "README.md"},
        "safe_environment": {"LANG": "C.UTF-8"},
    }
    data.update(updates)
    return CellRequest(**data)


def test_valid_authority_builds_hard_bounded_cell_command():
    authority, verifier = _signed_authority()
    runtime = OCICellRuntime(verifier, runtime_binary="/usr/bin/podman")
    request = _request(authority)

    digest = runtime._validate_request(request)
    command = runtime.build_command(request, "veklom-cell-test")

    assert digest.startswith("sha256:")
    assert command[:2] == ["/usr/bin/podman", "run"]
    assert ["--network", "none"] == command[command.index("--network") : command.index("--network") + 2]
    assert "--read-only" in command
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert command[command.index("--security-opt") + 1] == "no-new-privileges"
    assert command[command.index("--pids-limit") + 1] == "32"
    assert command[command.index("--memory") + 1] == "128m"
    assert command[command.index("--cpus") + 1] == "0.5"
    assert command[command.index("--user") + 1] == "65532:65532"
    assert "VEKLOM_CREDENTIAL_MODE=brokered_only" in command
    assert request.image in command


def test_tampered_authority_is_rejected_before_cell_spawn():
    authority, verifier = _signed_authority()
    tampered = SignedAuthority(
        envelope=authority.envelope.model_copy(update={"capability_id": "github.repo.delete"}),
        proof=authority.proof,
    )

    with pytest.raises(AuthorityVerificationError, match="signature is invalid"):
        verifier.verify(tampered)


def test_expired_authority_is_rejected_before_cell_spawn():
    authority, verifier = _signed_authority(expired=True)

    with pytest.raises(AuthorityVerificationError, match="expired"):
        verifier.verify(authority)


def test_credential_like_environment_is_forbidden():
    authority, verifier = _signed_authority()
    runtime = OCICellRuntime(verifier, runtime_binary="/usr/bin/podman")
    request = _request(authority, safe_environment={"GITHUB_TOKEN": "must-not-enter-cell"})

    with pytest.raises(CellRuntimeError, match="credential-like environment variable forbidden"):
        runtime._validate_request(request)


def test_mutable_image_tag_is_rejected():
    authority, verifier = _signed_authority()
    runtime = OCICellRuntime(verifier, runtime_binary="/usr/bin/podman")
    request = _request(authority, image="ghcr.io/example/executor:latest")

    with pytest.raises(CellRuntimeError, match="pinned by immutable sha256 digest"):
        runtime._validate_request(request)


def test_host_output_is_bounded_while_untrusted_process_runs():
    authority, verifier = _signed_authority()
    # /bin/true safely absorbs the cleanup command used after the short-lived
    # local test process has already exited.
    runtime = OCICellRuntime(verifier, runtime_binary="/bin/true", max_output_bytes=4096)
    process = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdout.write('x' * 8192)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr, timed_out, exceeded = runtime._collect_bounded(
        process,
        payload=b"{}",
        timeout_seconds=5,
        cell_id="test-cell",
    )
    assert exceeded is True
    assert timed_out is False
    assert len(stdout) + len(stderr) <= 4096


def test_podman_teardown_requires_documented_absence_status(monkeypatch):
    authority, verifier = _signed_authority()
    runtime = OCICellRuntime(verifier, runtime_binary="/usr/bin/podman")

    def absent(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 1, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", absent)
    assert runtime._teardown_confirmed("cell") is True


def test_teardown_runtime_error_is_not_misreported_as_absence(monkeypatch):
    authority, verifier = _signed_authority()
    runtime = OCICellRuntime(verifier, runtime_binary="/usr/bin/podman")

    def broken(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 125, stdout=b"", stderr=b"permission denied")

    monkeypatch.setattr(subprocess, "run", broken)
    with pytest.raises(CellRuntimeError, match="could not verify"):
        runtime._teardown_confirmed("cell")
