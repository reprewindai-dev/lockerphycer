from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone

import pytest

from core.execution_cells.firecracker import (
    FirecrackerConfig,
    FirecrackerMicroVMRuntime,
    FirecrackerRuntimeError,
)
from core.execution_cells.models import (
    AuthorityProof,
    AuthorizedExecutionEnvelope,
    CellRequest,
    CellResourceLimits,
    SignedAuthority,
)


class _Verifier:
    def verify(self, authority: SignedAuthority) -> str:
        authority.envelope.assert_current()
        return "sha256:" + "1" * 64


def _digest(path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _authority(*, rootfs_digest: str, kernel_digest: str, isolation: str = "microvm") -> SignedAuthority:
    now = datetime.now(timezone.utc)
    envelope = AuthorizedExecutionEnvelope(
        execution_id="exec-firecracker",
        path_id="path-firecracker",
        request_id="req-firecracker",
        idempotency_key="idem-firecracker",
        grant_id="grant-firecracker",
        subject_id="agent-firecracker",
        tenant_id="tenant",
        workspace_id="workspace",
        capability_id="github.file.update",
        semantic_intent_digest="sha256:" + "2" * 64,
        resource_constraints=CellResourceLimits(
            cpus=1,
            memory_mb=128,
            pids=32,
            timeout_seconds=30,
            tmpfs_mb=64,
        ),
        authority_epoch=1,
        assignment_id="assignment",
        runtime_kind="lockerphycer-cell",
        runtime_instance="host-a",
        required_isolation=isolation,
        runtime_image_digest=rootfs_digest,
        runtime_kernel_digest=kernel_digest,
        network_policy_digest="network:none",
        policy_digest="sha256:policy",
        allowed_provider_set=["github"],
        budget_ceiling=100,
        evidence_profile="pgl-required",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=1),
        nonce="0123456789abcdef0123456789abcdef",
    )
    return SignedAuthority(
        envelope=envelope,
        proof=AuthorityProof(
            key_id="test",
            signature_b64url="A" * 43,
        ),
    )


def _runtime(tmp_path, monkeypatch):
    binary = tmp_path / "firecracker"
    kernel = tmp_path / "vmlinux"
    rootfs = tmp_path / "rootfs.ext4"
    binary.write_bytes(b"firecracker-test-binary")
    kernel.write_bytes(b"kernel-test")
    rootfs.write_bytes(b"rootfs-test")
    binary.chmod(0o755)

    real_exists = os.path.exists
    monkeypatch.setattr(
        os.path,
        "exists",
        lambda path: True if path == "/dev/kvm" else real_exists(path),
    )
    config = FirecrackerConfig(
        binary=str(binary),
        kernel_path=str(kernel),
        rootfs_path=str(rootfs),
        kernel_digest=_digest(kernel),
        rootfs_digest=_digest(rootfs),
        state_dir=str(tmp_path / "state"),
    )
    runtime = FirecrackerMicroVMRuntime(
        _Verifier(),
        config,
        expected_runtime_instance="host-a",
    )
    return runtime, kernel, rootfs


def test_microvm_artifacts_are_bound_to_signed_authority(tmp_path, monkeypatch) -> None:
    runtime, kernel, rootfs = _runtime(tmp_path, monkeypatch)
    authority = _authority(rootfs_digest=_digest(rootfs), kernel_digest=_digest(kernel))
    request = CellRequest(
        authority=authority,
        image=f"lockerphycer-rootfs@{_digest(rootfs)}",
        command=["/usr/local/bin/lockerphycer-cell-agent"],
        input_payload={"provider": "github"},
    )

    observed_kernel, observed_rootfs, measurement = runtime._verify_artifacts(request)

    assert observed_kernel == _digest(kernel)
    assert observed_rootfs == _digest(rootfs)
    assert measurement.startswith("sha256:")


def test_microvm_does_not_accept_os_enforced_authority(tmp_path, monkeypatch) -> None:
    runtime, kernel, rootfs = _runtime(tmp_path, monkeypatch)
    authority = _authority(
        rootfs_digest=_digest(rootfs),
        kernel_digest=_digest(kernel),
        isolation="os-enforced",
    )
    request = CellRequest(
        authority=authority,
        image=f"lockerphycer-rootfs@{_digest(rootfs)}",
        command=["/usr/local/bin/lockerphycer-cell-agent"],
    )

    with pytest.raises(FirecrackerRuntimeError, match="does not require microVM"):
        runtime._verify_artifacts(request)


def test_microvm_rejects_runtime_artifact_substitution(tmp_path, monkeypatch) -> None:
    runtime, kernel, rootfs = _runtime(tmp_path, monkeypatch)
    wrong = "sha256:" + "f" * 64
    authority = _authority(rootfs_digest=wrong, kernel_digest=_digest(kernel))
    request = CellRequest(
        authority=authority,
        image=f"lockerphycer-rootfs@{wrong}",
        command=["/usr/local/bin/lockerphycer-cell-agent"],
    )

    with pytest.raises(FirecrackerRuntimeError, match="rootfs digest does not match"):
        runtime._verify_artifacts(request)


def test_firecracker_source_configures_vsock_but_no_guest_nic() -> None:
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "core"
        / "execution_cells"
        / "firecracker.py"
    ).read_text(encoding="utf-8")
    assert '"/vsock"' in source
    assert '"/network-interfaces' not in source
    assert '"/drives/rootfs"' in source
    assert '"is_read_only": True' in source
