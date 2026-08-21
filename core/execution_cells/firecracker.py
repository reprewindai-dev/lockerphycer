"""Firecracker/KVM hard-isolation backend for Lockerphycer governed cells.

This backend is deliberately different from the OCI Level-2 runtime:
- the executor gets a separate guest kernel behind KVM;
- the P0 microVM has no network interface at all;
- the only host/guest data path is Firecracker virtio-vsock;
- kernel and rootfs measurements are verified against CAPPO-signed authority;
- the host enforces the shorter of resource timeout and authority lifetime;
- the Firecracker process is terminated and absence is positively confirmed
  before a brokered external consequence may proceed.

Source implementation is not a VERIFIED_LIVE claim. A host must actually provide
/dev/kvm, Firecracker, the measured kernel/rootfs, and the adversarial evidence
required by the governed-compute acceptance contract.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import httpx

from .authority import canonical_json_bytes
from .models import CellRequest, CellResult


class FirecrackerRuntimeError(RuntimeError):
    """The host could not establish or prove the requested microVM boundary."""


class AuthorityVerifier(Protocol):
    def verify(self, authority) -> str: ...


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _safe_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in value)[:40].strip("-.")
    return safe or uuid.uuid4().hex[:16]


@dataclass(frozen=True)
class FirecrackerConfig:
    binary: str
    kernel_path: str
    rootfs_path: str
    kernel_digest: str
    rootfs_digest: str
    state_dir: str
    guest_vsock_port: int = 5000
    boot_args: str = "console=ttyS0 reboot=k panic=1 pci=off root=/dev/vda ro init=/init"
    api_timeout_seconds: float = 5.0

    @classmethod
    def from_environment(cls) -> "FirecrackerConfig":
        binary = os.environ.get("LOCKERPHYCER_FIRECRACKER_BINARY", "").strip() or shutil.which("firecracker") or ""
        kernel_path = os.environ.get("LOCKERPHYCER_FIRECRACKER_KERNEL", "").strip()
        rootfs_path = os.environ.get("LOCKERPHYCER_FIRECRACKER_ROOTFS", "").strip()
        kernel_digest = os.environ.get("LOCKERPHYCER_FIRECRACKER_KERNEL_SHA256", "").strip()
        rootfs_digest = os.environ.get("LOCKERPHYCER_FIRECRACKER_ROOTFS_SHA256", "").strip()
        state_dir = os.environ.get("LOCKERPHYCER_FIRECRACKER_STATE_DIR", "").strip()
        port_raw = os.environ.get("LOCKERPHYCER_FIRECRACKER_GUEST_PORT", "5000").strip()
        boot_args = os.environ.get("LOCKERPHYCER_FIRECRACKER_BOOT_ARGS", "").strip()

        missing = [
            name
            for name, value in (
                ("LOCKERPHYCER_FIRECRACKER_BINARY", binary),
                ("LOCKERPHYCER_FIRECRACKER_KERNEL", kernel_path),
                ("LOCKERPHYCER_FIRECRACKER_ROOTFS", rootfs_path),
                ("LOCKERPHYCER_FIRECRACKER_KERNEL_SHA256", kernel_digest),
                ("LOCKERPHYCER_FIRECRACKER_ROOTFS_SHA256", rootfs_digest),
                ("LOCKERPHYCER_FIRECRACKER_STATE_DIR", state_dir),
            )
            if not value
        ]
        if missing:
            raise FirecrackerRuntimeError("Firecracker runtime is not configured: " + ", ".join(missing))
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise FirecrackerRuntimeError("LOCKERPHYCER_FIRECRACKER_GUEST_PORT must be an integer") from exc
        if not 1024 <= port <= 65535:
            raise FirecrackerRuntimeError("Firecracker guest vsock port must be between 1024 and 65535")
        for name, digest in (
            ("kernel", kernel_digest),
            ("rootfs", rootfs_digest),
        ):
            if not digest.startswith("sha256:") or len(digest) != 71:
                raise FirecrackerRuntimeError(f"configured {name} digest must be sha256:<64 hex>")
        return cls(
            binary=binary,
            kernel_path=kernel_path,
            rootfs_path=rootfs_path,
            kernel_digest=kernel_digest,
            rootfs_digest=rootfs_digest,
            state_dir=state_dir,
            guest_vsock_port=port,
            boot_args=boot_args or cls.boot_args,
        )


class FirecrackerMicroVMRuntime:
    """Run one P0 executor in a no-NIC Firecracker microVM."""

    isolation_class = "microvm"
    runtime_name = "firecracker"

    def __init__(
        self,
        verifier: AuthorityVerifier,
        config: FirecrackerConfig,
        *,
        expected_runtime_instance: str,
        max_message_bytes: int = 1_048_576,
    ) -> None:
        self.verifier = verifier
        self.config = config
        self.expected_runtime_instance = expected_runtime_instance.strip()
        self.max_message_bytes = max_message_bytes
        if not self.expected_runtime_instance:
            raise FirecrackerRuntimeError("expected Lockerphycer runtime instance is required")
        if self.max_message_bytes < 4096:
            raise FirecrackerRuntimeError("Firecracker message limit is too small")
        if not os.path.exists("/dev/kvm"):
            raise FirecrackerRuntimeError("/dev/kvm is unavailable; hard-isolated microVM execution is unavailable")
        if not os.path.isfile(self.config.binary) or not os.access(self.config.binary, os.X_OK):
            raise FirecrackerRuntimeError("configured Firecracker binary is missing or not executable")
        if not os.path.isfile(self.config.kernel_path) or not os.path.isfile(self.config.rootfs_path):
            raise FirecrackerRuntimeError("configured Firecracker kernel/rootfs is missing")
        Path(self.config.state_dir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def configured() -> bool:
        required = (
            "LOCKERPHYCER_FIRECRACKER_KERNEL",
            "LOCKERPHYCER_FIRECRACKER_ROOTFS",
            "LOCKERPHYCER_FIRECRACKER_KERNEL_SHA256",
            "LOCKERPHYCER_FIRECRACKER_ROOTFS_SHA256",
            "LOCKERPHYCER_FIRECRACKER_STATE_DIR",
        )
        return all(os.environ.get(name, "").strip() for name in required)

    def _verify_artifacts(self, request: CellRequest) -> tuple[str, str, str]:
        envelope = request.authority.envelope
        if envelope.required_isolation != "microvm":
            raise FirecrackerRuntimeError("CAPPO authority does not require microVM isolation")
        if envelope.runtime_instance != self.expected_runtime_instance:
            raise FirecrackerRuntimeError("authority is bound to a different Lockerphycer cell host")
        if envelope.runtime_kind != "lockerphycer-cell":
            raise FirecrackerRuntimeError("authority runtime_kind does not authorize a Lockerphycer cell")
        if envelope.runtime_image_digest is None or envelope.runtime_kernel_digest is None:
            raise FirecrackerRuntimeError("microVM authority is missing signed rootfs/kernel measurements")
        if envelope.runtime_image_digest != self.config.rootfs_digest:
            raise FirecrackerRuntimeError("signed rootfs digest does not match configured Firecracker rootfs")
        if envelope.runtime_kernel_digest != self.config.kernel_digest:
            raise FirecrackerRuntimeError("signed kernel digest does not match configured Firecracker kernel")

        observed_rootfs = _sha256_file(self.config.rootfs_path)
        observed_kernel = _sha256_file(self.config.kernel_path)
        if observed_rootfs != self.config.rootfs_digest:
            raise FirecrackerRuntimeError("observed Firecracker rootfs measurement mismatch")
        if observed_kernel != self.config.kernel_digest:
            raise FirecrackerRuntimeError("observed Firecracker kernel measurement mismatch")

        requested_digest = request.image.rsplit("@", 1)[-1] if "@" in request.image else ""
        if requested_digest != envelope.runtime_image_digest:
            raise FirecrackerRuntimeError("requested executor image does not match CAPPO-signed rootfs digest")

        binary_digest = _sha256_file(self.config.binary)
        measurement = "sha256:" + hashlib.sha256(
            canonical_json_bytes(
                {
                    "isolation": "microvm",
                    "vmm": binary_digest,
                    "kernel": observed_kernel,
                    "rootfs": observed_rootfs,
                    "network": "none",
                    "transport": "vsock-only",
                    "boot_args": self.config.boot_args,
                }
            )
        ).hexdigest()
        return observed_kernel, observed_rootfs, measurement

    @staticmethod
    def _api_put(client: httpx.Client, path: str, payload: dict[str, Any]) -> None:
        try:
            response = client.put(path, json=payload)
        except httpx.HTTPError as exc:
            raise FirecrackerRuntimeError(f"Firecracker API unavailable at {path}") from exc
        if response.status_code != 204:
            raise FirecrackerRuntimeError(f"Firecracker rejected {path} configuration")

    @staticmethod
    def _wait_for_path(path: str, process: subprocess.Popen[bytes], deadline: float) -> None:
        while time.monotonic() < deadline:
            if os.path.exists(path):
                return
            if process.poll() is not None:
                raise FirecrackerRuntimeError("Firecracker exited before its API/vsock socket became ready")
            time.sleep(0.01)
        raise FirecrackerRuntimeError("Firecracker socket readiness timed out")

    def _configure_and_start(
        self,
        *,
        process: subprocess.Popen[bytes],
        api_socket: str,
        vsock_socket: str,
        guest_cid: int,
        request: CellRequest,
        deadline: float,
    ) -> None:
        self._wait_for_path(api_socket, process, deadline)
        remaining = max(0.1, min(self.config.api_timeout_seconds, deadline - time.monotonic()))
        transport = httpx.HTTPTransport(uds=api_socket, retries=0)
        with httpx.Client(transport=transport, base_url="http://firecracker", timeout=remaining) as client:
            limits = request.authority.envelope.resource_constraints
            vcpus = max(1, min(32, int(limits.cpus) if float(limits.cpus).is_integer() else int(limits.cpus) + 1))
            self._api_put(
                client,
                "/machine-config",
                {"vcpu_count": vcpus, "mem_size_mib": limits.memory_mb, "smt": False},
            )
            self._api_put(
                client,
                "/boot-source",
                {"kernel_image_path": self.config.kernel_path, "boot_args": self.config.boot_args},
            )
            self._api_put(
                client,
                "/drives/rootfs",
                {
                    "drive_id": "rootfs",
                    "path_on_host": self.config.rootfs_path,
                    "is_root_device": True,
                    "is_read_only": True,
                },
            )
            # Deliberately configure no /network-interfaces device for this P0.
            self._api_put(
                client,
                "/vsock",
                {"guest_cid": guest_cid, "uds_path": vsock_socket},
            )
            self._api_put(client, "/actions", {"action_type": "InstanceStart"})

    def _exchange_vsock(self, *, vsock_socket: str, payload: bytes, deadline: float) -> bytes:
        if len(payload) > self.max_message_bytes:
            raise FirecrackerRuntimeError("microVM input exceeds host message limit")
        self._wait_for_path(vsock_socket, _NeverExitedProcess(), deadline)

        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.settimeout(max(0.1, deadline - time.monotonic()))
            connection.connect(vsock_socket)
            connection.sendall(f"CONNECT {self.config.guest_vsock_port}\n".encode("ascii"))
            acknowledgement = self._recv_line(connection, 128)
            if not acknowledgement.startswith(b"OK "):
                raise FirecrackerRuntimeError("Firecracker vsock guest agent did not accept the channel")
            connection.sendall(struct.pack("!I", len(payload)) + payload)
            raw_length = self._recv_exact(connection, 4)
            length = struct.unpack("!I", raw_length)[0]
            if length > self.max_message_bytes:
                raise FirecrackerRuntimeError("microVM output exceeds host message limit")
            return self._recv_exact(connection, length)
        except (OSError, socket.timeout) as exc:
            raise FirecrackerRuntimeError("Firecracker vsock exchange failed") from exc
        finally:
            connection.close()

    @staticmethod
    def _recv_line(connection: socket.socket, limit: int) -> bytes:
        data = bytearray()
        while len(data) < limit:
            chunk = connection.recv(1)
            if not chunk:
                break
            data.extend(chunk)
            if chunk == b"\n":
                return bytes(data)
        raise FirecrackerRuntimeError("invalid Firecracker vsock acknowledgement")

    @staticmethod
    def _recv_exact(connection: socket.socket, length: int) -> bytes:
        data = bytearray()
        while len(data) < length:
            chunk = connection.recv(length - len(data))
            if not chunk:
                raise FirecrackerRuntimeError("microVM vsock channel closed early")
            data.extend(chunk)
        return bytes(data)

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes], deadline_seconds: float = 5.0) -> bool:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=deadline_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    return False
        return process.poll() is not None

    def run(self, request: CellRequest) -> CellResult:
        authority_digest = self.verifier.verify(request.authority)
        envelope = request.authority.envelope
        observed_kernel, observed_rootfs, runtime_measurement = self._verify_artifacts(request)

        started_at = datetime.now(timezone.utc)
        remaining_authority = (envelope.expires_at - started_at).total_seconds()
        if remaining_authority <= 0:
            raise FirecrackerRuntimeError("authority expired before microVM allocation")
        timeout = min(float(envelope.resource_constraints.timeout_seconds), remaining_authority)
        deadline = time.monotonic() + timeout

        cell_id = f"veklom-microvm-{_safe_id(envelope.execution_id)}-{uuid.uuid4().hex[:8]}"
        # Firecracker guest CIDs 0, 1 and 2 are reserved; choose a unique positive
        # value from the execution nonce and stay below signed 32-bit range.
        guest_cid = 3 + (int(hashlib.sha256((envelope.nonce + cell_id).encode()).hexdigest()[:8], 16) % 2_000_000_000)

        with tempfile.TemporaryDirectory(prefix=f"{cell_id}-", dir=self.config.state_dir) as cell_dir:
            api_socket = os.path.join(cell_dir, "firecracker-api.sock")
            vsock_socket = os.path.join(cell_dir, "executor.vsock")
            process = subprocess.Popen(
                [self.config.binary, "--api-sock", api_socket, "--id", cell_id],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                shell=False,
            )
            output = b""
            timed_out = False
            try:
                self._configure_and_start(
                    process=process,
                    api_socket=api_socket,
                    vsock_socket=vsock_socket,
                    guest_cid=guest_cid,
                    request=request,
                    deadline=deadline,
                )
                payload = canonical_json_bytes(request.input_payload)
                output = self._exchange_vsock(vsock_socket=vsock_socket, payload=payload, deadline=deadline)
                if time.monotonic() >= deadline:
                    timed_out = True
            finally:
                teardown_confirmed = self._terminate(process)

            if not teardown_confirmed:
                raise FirecrackerRuntimeError("microVM teardown could not be confirmed")
            if timed_out:
                raise FirecrackerRuntimeError("microVM exceeded authority/resource wall-time limit")

        completed_at = datetime.now(timezone.utc)
        network_policy_digest = envelope.network_policy_digest or "network:none"
        return CellResult(
            cell_id=cell_id,
            execution_id=envelope.execution_id,
            grant_id=envelope.grant_id,
            started_at=started_at,
            completed_at=completed_at,
            exit_code=0,
            timed_out=False,
            stdout=output.decode("utf-8", errors="strict"),
            stderr="",
            runtime=self.runtime_name,
            isolation_class="microvm",
            network_mode="none",
            credential_mode="brokered_only",
            runtime_measurement=runtime_measurement,
            network_policy_digest=network_policy_digest,
            teardown_confirmed=True,
            authority_digest=authority_digest,
        )


class _NeverExitedProcess:
    """Adapter used while waiting for the Firecracker-created vsock UDS."""

    @staticmethod
    def poll() -> None:
        return None
