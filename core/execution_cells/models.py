"""Typed contracts for Lockerphycer governed execution cells.

These models deliberately separate CAPPO authority from Lockerphycer enforcement.
A cell may only start from a cryptographically verified, unexpired authority
lease.  The cell itself never creates or widens authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CellResourceLimits(BaseModel):
    """Hard limits that the host runtime must enforce for one cell."""

    model_config = ConfigDict(extra="forbid")

    cpus: float = Field(default=1.0, gt=0, le=64)
    memory_mb: int = Field(default=512, ge=32, le=262_144)
    pids: int = Field(default=64, ge=8, le=32_768)
    timeout_seconds: int = Field(default=120, ge=1, le=3_600)
    tmpfs_mb: int = Field(default=128, ge=16, le=16_384)


class AuthorizedExecutionEnvelope(BaseModel):
    """Immutable CAPPO-authorized semantic transaction.

    Field names follow CAPPO's approved runtime-authority design.  Unknown
    authority-bearing fields are rejected instead of being silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(min_length=1)
    path_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    grant_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    delegation_id: str | None = None
    tenant_id: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    capability_id: str = Field(min_length=1)
    semantic_intent_digest: str = Field(min_length=1)
    resource_constraints: CellResourceLimits
    authority_epoch: int = Field(ge=0)
    assignment_id: str = Field(min_length=1)
    runtime_kind: str = Field(min_length=1)
    runtime_instance: str = Field(min_length=1)
    policy_digest: str = Field(min_length=1)
    allowed_provider_set: list[str] = Field(min_length=1)
    budget_ceiling: int = Field(ge=0)
    evidence_profile: str = Field(min_length=1)
    issued_at: datetime
    expires_at: datetime
    nonce: str = Field(min_length=16)

    @field_validator("issued_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("authority timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> "AuthorizedExecutionEnvelope":
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        return self

    def assert_current(self, now: datetime | None = None) -> None:
        current = now or datetime.now(timezone.utc)
        if current < self.issued_at:
            raise ValueError("authority is not active yet")
        if current >= self.expires_at:
            raise ValueError("authority has expired")


class AuthorityProof(BaseModel):
    """Detached CAPPO signature over canonical envelope JSON."""

    model_config = ConfigDict(extra="forbid")

    algorithm: Literal["Ed25519"] = "Ed25519"
    key_id: str = Field(min_length=1)
    signature_b64url: str = Field(min_length=32)


class SignedAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envelope: AuthorizedExecutionEnvelope
    proof: AuthorityProof


class CellRequest(BaseModel):
    """A single disposable workload invocation.

    Credentials are intentionally absent.  External effects are brokered by the
    host/control plane; static or JIT upstream credentials are never passed to
    the untrusted workload environment.
    """

    model_config = ConfigDict(extra="forbid")

    authority: SignedAuthority
    image: str = Field(min_length=1)
    command: list[str] = Field(min_length=1)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    safe_environment: dict[str, str] = Field(default_factory=dict)
    expected_effect_digest: str | None = None


class CellResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cell_id: str
    execution_id: str
    grant_id: str
    started_at: datetime
    completed_at: datetime
    exit_code: int | None
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    runtime: str
    network_mode: Literal["none"] = "none"
    credential_mode: Literal["brokered_only"] = "brokered_only"
    teardown_confirmed: bool
    authority_digest: str
