"""Brokered consequence adapters for governed execution cells.

The cell never receives provider credentials or general network access.  It may
propose a structured effect intent, but the trusted host broker performs the
real external mutation only when the intent is exactly bound to CAPPO's signed
semantic-intent digest and current target state.
"""

from __future__ import annotations

import base64
import hashlib
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from pydantic import BaseModel, ConfigDict, Field

from .authority import canonical_json_bytes
from .models import AuthorizedExecutionEnvelope


class EffectBoundaryError(RuntimeError):
    """A requested external effect does not satisfy its authority boundary."""


class GitHubFileUpdateIntent(BaseModel):
    """One exact GitHub Contents API mutation."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(default="github", pattern="^github$")
    operation: str = Field(default="github.file.update", pattern=r"^github\.file\.update$")
    owner: str = Field(min_length=1, max_length=100)
    repo: str = Field(min_length=1, max_length=100)
    branch: str = Field(min_length=1, max_length=255)
    path: str = Field(min_length=1, max_length=4096)
    expected_blob_sha: str = Field(min_length=40, max_length=64)
    content_b64: str = Field(min_length=1)
    commit_message: str = Field(min_length=1, max_length=500)


def effect_digest(intent: GitHubFileUpdateIntent) -> str:
    payload = canonical_json_bytes(intent.model_dump(mode="json"))
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def validate_effect_authority(
    envelope: AuthorizedExecutionEnvelope,
    intent: GitHubFileUpdateIntent,
) -> None:
    """Fail closed unless the exact effect is what CAPPO authorized."""

    envelope.assert_current()
    if envelope.capability_id != intent.operation:
        raise EffectBoundaryError("effect operation is outside CAPPO capability authority")
    if intent.provider not in envelope.allowed_provider_set:
        raise EffectBoundaryError("effect provider is outside CAPPO allowed provider set")
    if effect_digest(intent) != envelope.semantic_intent_digest:
        raise EffectBoundaryError("effect intent digest does not match CAPPO authority")


@dataclass(frozen=True)
class GitHubAppConfig:
    app_id: str
    installation_id: str
    private_key_pem: str
    api_base: str = "https://api.github.com"
    timeout_seconds: float = 15.0


class GitHubAppCredentialBroker:
    """Mint one repository-scoped installation token just in time."""

    def __init__(self, config: GitHubAppConfig, client: httpx.Client | None = None) -> None:
        self.config = config
        self.client = client or httpx.Client(
            timeout=config.timeout_seconds,
            follow_redirects=False,
            headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _app_jwt(self) -> str:
        now = int(time.time())
        return jwt.encode(
            {"iat": now - 30, "exp": now + 540, "iss": self.config.app_id},
            self.config.private_key_pem,
            algorithm="RS256",
        )

    def mint_repository_token(self, owner: str, repo: str) -> str:
        # GitHub installation-token creation accepts an explicit repository
        # restriction plus a narrow permission map.  This token never enters the cell.
        response = self.client.post(
            f"{self.config.api_base}/app/installations/{self.config.installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {self._app_jwt()}"},
            json={"repositories": [repo], "permissions": {"contents": "write"}},
        )
        if response.status_code not in {200, 201}:
            raise EffectBoundaryError("GitHub JIT credential mint failed")
        token = response.json().get("token")
        if not isinstance(token, str) or not token:
            raise EffectBoundaryError("GitHub JIT credential response was invalid")
        return token

    def revoke_token(self, token: str) -> None:
        response = self.client.delete(
            f"{self.config.api_base}/installation/token",
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code not in {204, 401, 404}:
            # A failed explicit revocation is surfaced; callers must not claim
            # immediate credential teardown if GitHub did not confirm it.
            raise EffectBoundaryError("GitHub JIT credential revocation failed")


class GitHubEffectBroker:
    """Perform one state-bound GitHub mutation outside the untrusted cell."""

    def __init__(self, credentials: GitHubAppCredentialBroker) -> None:
        self.credentials = credentials

    def execute(
        self,
        envelope: AuthorizedExecutionEnvelope,
        intent: GitHubFileUpdateIntent,
    ) -> dict[str, Any]:
        validate_effect_authority(envelope, intent)
        token = self.credentials.mint_repository_token(intent.owner, intent.repo)
        mutation_succeeded = False
        revoke_error: Exception | None = None
        try:
            headers = {"Authorization": f"Bearer {token}"}
            content_url = (
                f"{self.credentials.config.api_base}/repos/{intent.owner}/{intent.repo}"
                f"/contents/{intent.path}"
            )
            current = self.credentials.client.get(
                content_url,
                headers=headers,
                params={"ref": intent.branch},
            )
            if current.status_code != 200:
                raise EffectBoundaryError("GitHub target-state lookup failed")
            current_sha = current.json().get("sha")
            if current_sha != intent.expected_blob_sha:
                raise EffectBoundaryError("GitHub target state changed; mutation denied")

            # Decode locally before the provider call so malformed content cannot
            # consume an authorized mutation attempt.
            try:
                base64.b64decode(intent.content_b64, validate=True)
            except Exception as exc:
                raise EffectBoundaryError("effect content_b64 is invalid") from exc

            response = self.credentials.client.put(
                content_url,
                headers=headers,
                json={
                    "message": intent.commit_message,
                    "content": intent.content_b64,
                    "sha": intent.expected_blob_sha,
                    "branch": intent.branch,
                },
            )
            if response.status_code not in {200, 201}:
                raise EffectBoundaryError("GitHub mutation failed")

            body = response.json()
            mutation_succeeded = True
            return {
                "provider": "github",
                "operation": intent.operation,
                "repository": f"{intent.owner}/{intent.repo}",
                "branch": intent.branch,
                "path": intent.path,
                "before_sha": intent.expected_blob_sha,
                "after_blob_sha": (body.get("content") or {}).get("sha"),
                "commit_sha": (body.get("commit") or {}).get("sha"),
                "effect_digest": effect_digest(intent),
                "mutation_succeeded": True,
            }
        finally:
            try:
                self.credentials.revoke_token(token)
            except Exception as exc:  # preserve the primary mutation exception
                revoke_error = exc
            if revoke_error is not None and mutation_succeeded:
                raise revoke_error
