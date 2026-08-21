"""Host-enforced OCI runtime for disposable governed execution cells.

The untrusted workload gets no network namespace connectivity and receives no
upstream credential.  External consequences are brokered by the trusted host
plane after the cell produces a structured result/effect intent.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
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
    """Run one cell using Podman or Docker with fail-closed isolation flags.

    This is intentionally a host-side primitive.  Do not expose a Docker/Podman
    socket inside the untrusted cell and do not mount host credentials into it.
    """

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

        # Only explicitly supplied non-credential environment is forwarded.
        for key, value in sorted(request.safe_environment.items()):
            cmd.extend(["--env", f"{key}={value}"])

        cmd.append(request.image)
        cmd.extend(request.command)
        return cmd

    def _force_remove(self, cell_id: str) -> None:
        subprocess.run(
            [self.runtime_binary, "rm", "-f", cell_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )

    def _teardown_confirmed(self, cell_id: str) -> bool:
        probe = subprocess.run(
            [self.runtime_binary, "inspect", cell_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        return probe.returncode != 0

    def run(self, request: CellRequest) -> CellResult:
        authority_hash = self._validate_request(request)
        envelope = request.authority.envelope
        cell_id = _safe_cell_name(envelope.execution_id)
        command = self.build_command(request, cell_id)
        started_at = datetime.now(timezone.utc)
        timed_out = False
        exit_code: int | None = None
        stdout = b""
        stderr = b""

        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
        )

        payload = json.dumps(request.input_payload, separators=(",", ":")).encode("utf-8")
        try:
            stdout, stderr = process.communicate(
                input=payload,
                timeout=envelope.resource_constraints.timeout_seconds,
            )
            exit_code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            self._force_remove(cell_id)
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            exit_code = process.returncode
        finally:
            # ``--rm`` should remove the cell, but cleanup is explicit and
            # idempotent so a runtime failure cannot silently leave authority alive.
            self._force_remove(cell_id)

        teardown_confirmed = self._teardown_confirmed(cell_id)
        if not teardown_confirmed:
            raise CellRuntimeError("cell teardown could not be confirmed")

        completed_at = datetime.now(timezone.utc)
        stdout = stdout[: self.max_output_bytes]
        stderr = stderr[: self.max_output_bytes]

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
            teardown_confirmed=True,
            authority_digest=authority_hash,
        )
