"""Lockerphycer governed-cell host service.

Run this process on the execution host and bind it to a Unix-domain socket. It
owns the narrow local runtime capability so CAPPO/application containers never
receive a Docker/Podman socket or direct Firecracker/KVM control.
"""

from __future__ import annotations

import hmac
import json
import os
from functools import lru_cache
from typing import Any

from fastapi import FastAPI, Header, HTTPException

from core.execution_cells.authority import AuthorityVerificationError, Ed25519AuthorityVerifier
from core.execution_cells.effects import (
    EffectBoundaryError,
    GitHubAppConfig,
    GitHubAppCredentialBroker,
    GitHubEffectBroker,
    GitHubFileUpdateIntent,
    effect_digest,
    validate_effect_authority,
)
from core.execution_cells.firecracker import (
    FirecrackerConfig,
    FirecrackerMicroVMRuntime,
    FirecrackerRuntimeError,
)
from core.execution_cells.models import CellRequest, CellResult, SignedAuthority
from core.execution_cells.replay import CellSuccessRequired, ReplayDetected, SQLiteReplayStore
from core.execution_cells.runtime import CellRuntimeError, OCICellRuntime


class CellHostConfigurationError(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise CellHostConfigurationError(f"{name} is required")
    return value


def _load_authority_keys() -> dict[str, str]:
    raw = _required("LOCKERPHYCER_CAPPO_AUTHORITY_KEYS_JSON")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CellHostConfigurationError("LOCKERPHYCER_CAPPO_AUTHORITY_KEYS_JSON must be JSON") from exc
    if not isinstance(value, dict) or not value or not all(
        isinstance(key, str) and isinstance(public_key, str) for key, public_key in value.items()
    ):
        raise CellHostConfigurationError("CAPPO authority key map must be a non-empty string map")
    return value


def _build_github_broker() -> GitHubEffectBroker:
    config = GitHubAppConfig(
        app_id=_required("LOCKERPHYCER_GITHUB_APP_ID"),
        installation_id=_required("LOCKERPHYCER_GITHUB_INSTALLATION_ID"),
        private_key_pem=_required("LOCKERPHYCER_GITHUB_APP_PRIVATE_KEY_PEM"),
        api_base=os.environ.get("LOCKERPHYCER_GITHUB_API_BASE", "https://api.github.com").rstrip("/"),
    )
    return GitHubEffectBroker(GitHubAppCredentialBroker(config))


app = FastAPI(
    title="Lockerphycer Governed Cell Host",
    version="0.2.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Authority, replay fencing and host audience are production invariants: fail boot
# rather than start an execution controller with an incomplete trust boundary.
_CELL_HOST_KEY = _required("LOCKERPHYCER_CELL_HOST_API_KEY")
if len(_CELL_HOST_KEY) < 32:
    raise CellHostConfigurationError("LOCKERPHYCER_CELL_HOST_API_KEY must be at least 32 characters")
_HOST_INSTANCE = _required("LOCKERPHYCER_CELL_HOST_INSTANCE")
_AUTHORITY_VERIFIER = Ed25519AuthorityVerifier(_load_authority_keys())
_REPLAY = SQLiteReplayStore(_required("LOCKERPHYCER_REPLAY_DB"))


@lru_cache(maxsize=1)
def _oci_runtime() -> OCICellRuntime:
    configured = os.environ.get("LOCKERPHYCER_OCI_RUNTIME", "").strip() or None
    return OCICellRuntime(
        _AUTHORITY_VERIFIER,
        runtime_binary=configured,
        expected_runtime_instance=_HOST_INSTANCE,
    )


@lru_cache(maxsize=1)
def _firecracker_runtime() -> FirecrackerMicroVMRuntime:
    return FirecrackerMicroVMRuntime(
        _AUTHORITY_VERIFIER,
        FirecrackerConfig.from_environment(),
        expected_runtime_instance=_HOST_INSTANCE,
    )


def _runtime_for(authority: SignedAuthority) -> Any:
    required = authority.envelope.required_isolation
    if required == "microvm":
        # No fallback: if KVM/Firecracker/artifacts are unavailable, the signed
        # hard-isolation requirement cannot be weakened to a shared-kernel cell.
        return _firecracker_runtime()
    if required == "os-enforced":
        return _oci_runtime()
    raise CellHostConfigurationError("unsupported required_isolation value")


def _require_runtime_artifact_binding(request: CellRequest) -> None:
    """Require the exact runtime artifact selected by CAPPO's signed authority."""
    envelope = request.authority.envelope
    if envelope.runtime_image_digest is None:
        raise CellRuntimeError("signed authority is missing runtime_image_digest")
    if "@sha256:" not in request.image:
        raise CellRuntimeError("cell image must be pinned by immutable sha256 digest")
    requested_digest = request.image.rsplit("@", 1)[1].lower()
    if requested_digest != envelope.runtime_image_digest:
        raise CellRuntimeError("requested runtime image does not match CAPPO-signed authority")
    if envelope.required_isolation == "microvm" and envelope.runtime_kernel_digest is None:
        raise CellRuntimeError("microVM authority is missing runtime_kernel_digest")


def _authorize_host_call(value: str | None) -> None:
    if not value or not hmac.compare_digest(value, _CELL_HOST_KEY):
        raise HTTPException(status_code=401, detail="cell-host authentication failed")


def _record_successful_effect_output(request: CellRequest, result: CellResult) -> None:
    """Bind a brokerable effect to the exact output of a successful torn-down cell."""
    envelope = request.authority.envelope
    if envelope.capability_id != "github.file.update":
        return
    if result.timed_out or result.exit_code != 0 or not result.teardown_confirmed:
        return
    if result.isolation_class != envelope.required_isolation:
        raise CellRuntimeError("cell result isolation class does not match signed authority")
    try:
        raw = json.loads(result.stdout)
        intent = GitHubFileUpdateIntent.model_validate(raw)
        validate_effect_authority(envelope, intent)
    except Exception as exc:
        raise CellRuntimeError("successful cell did not emit the exact authorized effect") from exc
    _REPLAY.record_cell_success(
        request.authority,
        effect_digest=effect_digest(intent),
        cell_id=result.cell_id,
    )


@app.get("/health")
def health() -> dict[str, Any]:
    # Process/configuration health only. This does not claim that a cell can boot,
    # KVM exists, a provider is reachable, or a consequence is VERIFIED_LIVE.
    return {
        "status": "healthy",
        "scope": "process_only",
        "cell_host_instance": _HOST_INSTANCE,
        "microvm_configured": FirecrackerMicroVMRuntime.configured(),
    }


@app.post("/v1/cells/run", response_model=CellResult)
def run_cell(
    request: CellRequest,
    x_cell_host_key: str | None = Header(default=None),
) -> CellResult:
    _authorize_host_call(x_cell_host_key)
    try:
        _AUTHORITY_VERIFIER.verify(request.authority)
        _require_runtime_artifact_binding(request)
        runtime = _runtime_for(request.authority)
        _REPLAY.consume(request.authority, "cell_run")
        result = runtime.run(request)
        _record_successful_effect_output(request, result)
        return result
    except AuthorityVerificationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ReplayDetected, CellSuccessRequired) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (CellRuntimeError, FirecrackerRuntimeError, CellHostConfigurationError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class GitHubEffectRequest(GitHubFileUpdateIntent):
    """GitHub effect plus its independently signed CAPPO authority."""

    authority: SignedAuthority


@app.post("/v1/effects/github/file-update")
def github_file_update(
    request: GitHubEffectRequest,
    x_cell_host_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _authorize_host_call(x_cell_host_key)
    try:
        # The provider side has no runtime fallback either: a brokered effect is
        # accepted only if the exact digest was first emitted by the successfully
        # completed cell stage under this same signed authority.
        _AUTHORITY_VERIFIER.verify(request.authority)
        intent = GitHubFileUpdateIntent(**request.model_dump(exclude={"authority"}))
        digest = effect_digest(intent)
        originating_cell_id = _REPLAY.require_cell_success(
            request.authority,
            effect_digest=digest,
        )
        _REPLAY.consume(request.authority, "effect")
        broker = _build_github_broker()
        try:
            result = broker.execute(request.authority.envelope, intent)
            result["originating_cell_id"] = originating_cell_id
            result["required_isolation"] = request.authority.envelope.required_isolation
            return result
        finally:
            broker.credentials.close()
    except AuthorityVerificationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ReplayDetected, CellSuccessRequired, EffectBoundaryError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
