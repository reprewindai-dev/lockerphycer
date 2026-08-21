"""Brokered consequence adapters for governed execution cells.

The cell never receives provider credentials or general network access. It may
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
from urllib.parse import quote

import httpx
import jwt
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .authority import canonical_json_bytes
from .models import AuthorizedExecutionEnvelope


class EffectBoundaryError(RuntimeError):
    """A requested external effect does not satisfy its authority boundary."""


class CredentialRevocationError(EffectBoundaryError):
    """A temporary provider credential could not be positively revoked."""


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

    @field_validator("path")
    @classmethod
    def reject_parent_traversal(cls, value: str) -> str:
        if value.startswith("/") or ".." in value.split("/"):
            raise ValueError("GitHub path must be repository-relative without parent traversal")
        return value


def effect_digest(intent: GitHubFileUpdateIntent) -> str:
    payload = canonical_json_bytes(intent.model_dump(mode="json"))
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def validate_effect_authority(
    envelope: AuthorizedExecutionEnvelope,
    intent: GitHubFileUpdateIntent,
) -> None:
    """Fail closed unless the exact effect is what CAPPO authorized."""

    try:
        envelope.assert_current()
    except ValueError as exc:
        raise EffectBoundaryError(str(exc)) from exc
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
    revocation_attempts: int = 3


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
        # restriction plus a narrow permission map. This token never enters the cell.
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

    def revoke_token(self, token: str) -> bool:
        """Require GitHub's documented 204; retry transient failures briefly."""
        attempts = max(1, min(int(self.config.revocation_attempts), 5))
        for attempt in range(attempts):
            try:
                response = self.client.delete(
                    f"{self.config.api_base}/installation/token",
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError:
                response = None
            if response is not None and response.status_code == 204:
                return True
            if attempt + 1 < attempts:
                time.sleep(0.1 * (attempt + 1))
        return False


class GitHubEffectBroker:
    """Perform one state-bound GitHub mutation outside the untrusted cell."""

    def __init__(self, credentials: GitHubAppCredentialBroker) -> None:
        self.credentials = credentials

    @staticmethod
    def _content_path(intent: GitHubFileUpdateIntent) -> str:
        owner = quote(intent.owner, safe="")
        repo = quote(intent.repo, safe="")
        # Preserve repository path separators while encoding query/fragment and
        # other URL delimiters that are valid Git filename characters.
        path = quote(intent.path, safe="/")
        return f"/repos/{owner}/{repo}/contents/{path}"

    def execute(
        self,
        envelope: AuthorizedExecutionEnvelope,
        intent: GitHubFileUpdateIntent,
    ) -> dict[str, Any]:
        validate_effect_authority(envelope, intent)

        # Reject malformed content before creating any upstream credential.
        try:
            base64.b64decode(intent.content_b64, validate=True)
        except Exception as exc:
            raise EffectBoundaryError("effect content_b64 is invalid") from exc

        token = self.credentials.mint_repository_token(intent.owner, intent.repo)
        result: dict[str, Any] | None = None
        content_url = f"{self.credentials.config.api_base}{self._content_path(intent)}"
        try:
            headers = {"Authorization": f"Bearer {token}"}
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

            # Authority and current state are revalidated at the final mutation
            # boundary, after provider/network delay and immediately before PUT.
            try:
                envelope.assert_current()
            except ValueError as exc:
                raise EffectBoundaryError(str(exc)) from exc

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
            result = {
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
        except Exception as primary:
            # A failed consequence attempt still has a live temporary credential.
            # If revocation cannot be positively confirmed, surface that security
            # incident instead of silently discarding the failed revocation.
            if not self.credentials.revoke_token(token):
                raise CredentialRevocationError(
                    "GitHub effect failed and JIT credential revocation was not confirmed"
                ) from primary
            raise

        # Once a real consequence has occurred, preserve its evidence even when
        # revocation is not positively confirmed; CAPPO/PGL must record both facts.
        result["credential_revoked"] = self.credentials.revoke_token(token)
        result["security_status"] = (
            "COMPLETE" if result["credential_revoked"] else "REVOCATION_NOT_CONFIRMED"
        )
        return result
