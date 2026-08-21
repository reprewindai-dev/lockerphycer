"""Lockerphycer cell-host service.

Run this process on the execution host and bind it to a Unix-domain socket.
It owns the narrow OCI-runtime capability so CAPPO/Lockerphycer application
containers never need the host Docker/Podman socket.
"""

from __future__ import annotations

import hmac
import json
import os

from fastapi import FastAPI, Header, HTTPException

from core.execution_cells.authority import AuthorityVerificationError, Ed25519AuthorityVerifier
from core.execution_cells.effects import (
    EffectBoundaryError,
    GitHubAppConfig,
    GitHubAppCredentialBroker,
    GitHubEffectBroker,
    GitHubFileUpdateIntent,
)
from core.execution_cells.models import CellRequest, CellResult, SignedAuthority
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
    if not isinstance(value, dict) or not value or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise CellHostConfigurationError("CAPPO authority key map must be a non-empty string map")
    return value


def _build_runtime() -> OCICellRuntime:
    verifier = Ed25519AuthorityVerifier(_load_authority_keys())
    configured = os.environ.get("LOCKERPHYCER_OCI_RUNTIME", "").strip() or None
    return OCICellRuntime(verifier, runtime_binary=configured)


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
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Fail boot rather than exposing a cell-host process with incomplete authority.
_CELL_HOST_KEY = _required("LOCKERPHYCER_CELL_HOST_API_KEY")
if len(_CELL_HOST_KEY) < 32:
    raise CellHostConfigurationError("LOCKERPHYCER_CELL_HOST_API_KEY must be at least 32 characters")
_RUNTIME = _build_runtime()


def _authorize_host_call(value: str | None) -> None:
    if not value or not hmac.compare_digest(value, _CELL_HOST_KEY):
        raise HTTPException(status_code=401, detail="cell-host authentication failed")


@app.get("/health")
def health() -> dict[str, str]:
    # Local process health only; does not claim a working cell or provider.
    return {"status": "healthy", "scope": "process_only", "runtime": _RUNTIME.runtime_name}


@app.post("/v1/cells/run", response_model=CellResult)
def run_cell(
    request: CellRequest,
    x_cell_host_key: str | None = Header(default=None),
) -> CellResult:
    _authorize_host_call(x_cell_host_key)
    try:
        return _RUNTIME.run(request)
    except AuthorityVerificationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CellRuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class GitHubEffectRequest(GitHubFileUpdateIntent):
    """GitHub effect plus its independently signed CAPPO authority."""

    authority: SignedAuthority


@app.post("/v1/effects/github/file-update")
def github_file_update(
    request: GitHubEffectRequest,
    x_cell_host_key: str | None = Header(default=None),
) -> dict:
    _authorize_host_call(x_cell_host_key)

    # Verify CAPPO signature and expiry independently from the caller.
    _RUNTIME.verifier.verify(request.authority)
    intent = GitHubFileUpdateIntent(**request.model_dump(exclude={"authority"}))
    broker = _build_github_broker()
    try:
        return broker.execute(request.authority.envelope, intent)
    except (AuthorityVerificationError, EffectBoundaryError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        broker.credentials.close()
