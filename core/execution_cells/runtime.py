"""Host-enforced OCI runtime for disposable governed execution cells.

The untrusted workload gets no network namespace connectivity and receives no
upstream credential. External consequences are brokered by the trusted host
plane after the cell produces a structured result/effect intent.
"""

from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timezone
from typing import Protocol

from .models import CellRequest, CellResult


class CellRuntimeError(RuntimeError):
    """The host runtime could not enforce or complete a cell invocation."""


_SECRET_NAME = re.compile(
    r"(^|_)(SECRET|TOKEN|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|ACCESS_KEY|AUTHORIZATION)(_|$)",
    re.IGNORECASE,
)


class AuthorityVerifier(Protocol):
    def verify(self, authority) -> str: ...


def _safe_cell_name(execution_id: str) -> str:
    compact = re.sub(r"[^a-zA-Z0-9_.-]", "-", execution_id)[:40].strip("-.")
    return f"veklom-cell-{compact or 'exec'}-{uuid.uuid4().hex[:10]}"


class OCICellRuntime:
    """Run one Level-2 cell using Podman or Docker with fail-closed isolation.

    This is intentionally a host-side primitive. Do not expose a Docker/Podman
    socket inside the untrusted cell and do not mount host credentials into it.
    Conventional OCI cells share the host kernel and therefore do not satisfy
    the hard-isolation claim reserved for the Firecracker backend.
    """

    isolation_class = "os-enforced"

    def __init__(
        self,
        verifier: AuthorityVerifier,
        runtime_binary: str | None = None,
        max_output_bytes: int = 1_048_576,
        expected_runtime_instance: str | None = None,
    ) -> None:
        self.verifier = verifier
        self.runtime_binary = runtime_binary or self._detect_runtime()
        self.max_output_bytes = max_output_bytes
        self.expected_runtime_instance = (expected_runtime_instance or "").strip() or None
        if self.max_output_bytes < 4096:
            raise ValueError("max_output_bytes is too small")

    @staticmethod
    def _detect_runtime() -> str:
        for candidate in ("podman", "docker"):
            path = shutil.which(candidate)
            if path:
                return path
        raise CellRuntimeError("no supported OCI runtime found; install rootless Podman or Docker")

    @property
    def runtime_name(self) -> str:
        return self.runtime_binary.rsplit("/", 1)[-1]

    def _validate_request(self, request: CellRequest) -> str:
        authority_hash = self.verifier.verify(request.authority)
        envelope = request.authority.envelope

        if "@sha256:" not in request.image:
            raise CellRuntimeError("cell image must be pinned by immutable sha256 digest")
        if envelope.runtime_kind != "lockerphycer-cell":
            raise CellRuntimeError("authority runtime_kind does not authorize a Lockerphycer cell")
        if self.expected_runtime_instance and envelope.runtime_instance != self.expected_runtime_instance:
            raise CellRuntimeError("authority is bound to a different Lockerphycer cell host")
        if not envelope.allowed_provider_set:
            raise CellRuntimeError("authority has no allowed provider set")

        for key in request.safe_environment:
            if not key or "=" in key or "\x00" in key:
                raise CellRuntimeError("invalid cell environment key")
            if _SECRET_NAME.search(key) or key.upper().startswith(("AWS_", "GITHUB_", "AZURE_", "GOOGLE_")):
                raise CellRuntimeError(f"credential-like environment variable forbidden in cell: {key}")

        return authority_hash

    def build_command(self, request: CellRequest, cell_id: str) -> list[str]:
        limits = request.authority.envelope.resource_constraints
        cmd = [
            self.runtime_binary,
            "run",
            "--rm",
            "--name",
            cell_id,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(limits.pids),
            "--memory",
            f"{limits.memory_mb}m",
            "--cpus",
            str(limits.cpus),
            "--user",
            "65532:65532",
            "--workdir",
            "/workspace",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size={limits.tmpfs_mb}m",
            "--tmpfs",
            f"/workspace:rw,nosuid,nodev,size={limits.tmpfs_mb}m",
            "--env",
            "VEKLOM_CELL_NETWORK=none",
            "--env",
            "VEKLOM_CREDENTIAL_MODE=brokered_only",
            "--env",
            f"VEKLOM_EXECUTION_ID={request.authority.envelope.execution_id}",
            "--env",
            f"VEKLOM_GRANT_ID={request.authority.envelope.grant_id}",
        ]
        for key, value in sorted(request.safe_environment.items()):
            cmd.extend(["--env", f"{key}={value}"])
        cmd.append(request.image)
        cmd.extend(request.command)
        return cmd

    def _force_remove(self, cell_id: str) -> None:
        try:
            subprocess.run(
                [self.runtime_binary, "rm", "-f", cell_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CellRuntimeError("cell runtime cleanup timed out") from exc

    def _teardown_confirmed(self, cell_id: str) -> bool:
        """Confirm absence without treating arbitrary runtime failure as proof."""
        try:
            if self.runtime_name == "podman":
                probe = subprocess.run(
                    [self.runtime_binary, "container", "exists", cell_id],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=10,
                    check=False,
                )
                if probe.returncode == 0:
                    return False
                if probe.returncode == 1:
                    return True
                raise CellRuntimeError("Podman could not verify cell teardown")

            probe = subprocess.run(
                [self.runtime_binary, "inspect", "--type", "container", cell_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=10,
                check=False,
            )
            if probe.returncode == 0:
                return False
            diagnostic = (probe.stderr or b"")[:4096].decode("utf-8", errors="replace").lower()
            if "no such object" in diagnostic or "no such container" in diagnostic:
                return True
            raise CellRuntimeError("OCI runtime could not verify cell teardown")
        except subprocess.TimeoutExpired as exc:
            raise CellRuntimeError("cell teardown inspection timed out") from exc

    def _collect_bounded(
        self,
        process: subprocess.Popen,
        *,
        payload: bytes,
        timeout_seconds: float,
        cell_id: str,
    ) -> tuple[bytes, bytes, bool, bool]:
        """Move stdin/stdout/stderr under one bounded, nonblocking deadline."""
        if process.stdin is None or process.stdout is None or process.stderr is None:
            raise CellRuntimeError("cell runtime pipes were not created")

        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        os.set_blocking(process.stderr.fileno(), False)

        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        if payload:
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
        else:
            process.stdin.close()

        payload_view = memoryview(payload)
        payload_offset = 0
        stdout = bytearray()
        stderr = bytearray()
        output_total = 0
        timed_out = False
        output_exceeded = False
        deadline = time.monotonic() + max(0.001, float(timeout_seconds))

        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    break

                events = selector.select(timeout=min(0.1, remaining))
                if not events:
                    if process.poll() is not None:
                        # EOF notifications may arrive on the next selector pass.
                        continue
                    continue

                for key, mask in events:
                    if key.data == "stdin" and mask & selectors.EVENT_WRITE:
                        try:
                            written = os.write(process.stdin.fileno(), payload_view[payload_offset:])
                            payload_offset += written
                        except (BlockingIOError, InterruptedError):
                            continue
                        except (BrokenPipeError, OSError):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                            continue
                        if payload_offset >= len(payload):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                        continue

                    if mask & selectors.EVENT_READ:
                        try:
                            chunk = os.read(key.fileobj.fileno(), 65536)
                        except (BlockingIOError, InterruptedError):
                            continue
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        output_total += len(chunk)
                        if output_total > self.max_output_bytes:
                            output_exceeded = True
                            break
                        if key.data == "stdout":
                            stdout.extend(chunk)
                        else:
                            stderr.extend(chunk)

                if output_exceeded:
                    break
        finally:
            selector.close()
            if process.stdin and not process.stdin.closed:
                process.stdin.close()

        if timed_out or output_exceeded:
            self._force_remove(cell_id)

        remaining = deadline - time.monotonic()
        if process.poll() is None:
            if remaining <= 0:
                timed_out = True
                self._force_remove(cell_id)
            else:
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    self._force_remove(cell_id)

        if process.poll() is None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)

        return bytes(stdout), bytes(stderr), timed_out, output_exceeded

    def run(self, request: CellRequest) -> CellResult:
        authority_hash = self._validate_request(request)
        envelope = request.authority.envelope
        cell_id = _safe_cell_name(envelope.execution_id)
        command = self.build_command(request, cell_id)
        started_at = datetime.now(timezone.utc)

        remaining_authority = (envelope.expires_at - started_at).total_seconds()
        if remaining_authority <= 0:
            raise CellRuntimeError("authority expired before cell spawn")
        effective_timeout = min(
            float(envelope.resource_constraints.timeout_seconds),
            remaining_authority,
        )

        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
        )

        payload = json.dumps(request.input_payload, separators=(",", ":")).encode("utf-8")
        output_error: CellRuntimeError | None = None
        try:
            stdout, stderr, timed_out, output_exceeded = self._collect_bounded(
                process,
                payload=payload,
                timeout_seconds=effective_timeout,
                cell_id=cell_id,
            )
            exit_code = process.returncode
            if output_exceeded:
                output_error = CellRuntimeError("cell output exceeded host-enforced byte limit")
        finally:
            self._force_remove(cell_id)

        teardown_confirmed = self._teardown_confirmed(cell_id)
        if not teardown_confirmed:
            raise CellRuntimeError("cell teardown could not be confirmed")
        if output_error is not None:
            raise output_error

        completed_at = datetime.now(timezone.utc)
        return CellResult(
            cell_id=cell_id,
            execution_id=envelope.execution_id,
            grant_id=envelope.grant_id,
            started_at=started_at,
            completed_at=completed_at,
            exit_code=exit_code,
            timed_out=timed_out,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            runtime=self.runtime_name,
            isolation_class=self.isolation_class,
            teardown_confirmed=True,
            authority_digest=authority_hash,
        )
