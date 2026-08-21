from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from core.execution_cells.effects import (
    CredentialRevocationError,
    EffectBoundaryError,
    GitHubAppConfig,
    GitHubAppCredentialBroker,
    GitHubEffectBroker,
    GitHubFileUpdateIntent,
    effect_digest,
)
from core.execution_cells.models import AuthorizedExecutionEnvelope, CellResourceLimits


def _intent(expected_sha: str = "a" * 40, path: str = "README.md") -> GitHubFileUpdateIntent:
    return GitHubFileUpdateIntent(
        owner="reprewindai-dev",
        repo="sandbox",
        branch="main",
        path=path,
        expected_blob_sha=expected_sha,
        content_b64=base64.b64encode(b"governed\n").decode("ascii"),
        commit_message="test: governed mutation",
    )


def _envelope(intent: GitHubFileUpdateIntent) -> AuthorizedExecutionEnvelope:
    now = datetime.now(timezone.utc)
    return AuthorizedExecutionEnvelope(
        execution_id="exec-github-1",
        path_id="path-github-1",
        request_id="request-github-1",
        idempotency_key="idem-github-1",
        grant_id="grant-github-1",
        subject_id="agent-test",
        delegation_id=None,
        tenant_id="tenant-test",
        workspace_id="workspace-test",
        capability_id="github.file.update",
        semantic_intent_digest=effect_digest(intent),
        resource_constraints=CellResourceLimits(),
        authority_epoch=1,
        assignment_id="assignment-1",
        runtime_kind="lockerphycer-cell",
        runtime_instance="cell-host-test",
        policy_digest="sha256:policy",
        allowed_provider_set=["github"],
        budget_ceiling=100,
        evidence_profile="pgl-required",
        issued_at=now - timedelta(seconds=5),
        expires_at=now + timedelta(minutes=5),
        nonce="0123456789abcdef0123456789abcdef",
    )


def _private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


def _credentials(client: httpx.Client, *, revocation_attempts: int = 1) -> GitHubAppCredentialBroker:
    return GitHubAppCredentialBroker(
        GitHubAppConfig(
            app_id="123",
            installation_id="456",
            private_key_pem=_private_key_pem(),
            api_base="https://api.github.test",
            revocation_attempts=revocation_attempts,
        ),
        client=client,
    )


def test_github_effect_is_state_bound_repo_scoped_and_revoked():
    intent = _intent()
    envelope = _envelope(intent)
    calls: list[tuple[str, str]] = []
    minted_body = {}

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal minted_body
        calls.append((request.method, str(request.url)))
        if request.method == "POST" and "/access_tokens" in request.url.path:
            import json
            minted_body = json.loads(request.content.decode())
            return httpx.Response(201, json={"token": "jit-installation-token"})
        if request.method == "GET" and "/contents/README.md" in request.url.path:
            assert request.headers["Authorization"] == "Bearer jit-installation-token"
            assert request.url.params["ref"] == "main"
            return httpx.Response(200, json={"sha": "a" * 40})
        if request.method == "PUT" and "/contents/README.md" in request.url.path:
            assert request.headers["Authorization"] == "Bearer jit-installation-token"
            return httpx.Response(200, json={"content": {"sha": "b" * 40}, "commit": {"sha": "c" * 40}})
        if request.method == "DELETE" and request.url.path == "/installation/token":
            assert request.headers["Authorization"] == "Bearer jit-installation-token"
            return httpx.Response(204)
        raise AssertionError(f"unexpected request {request.method} {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.test")
    result = GitHubEffectBroker(_credentials(client)).execute(envelope, intent)

    assert result["mutation_succeeded"] is True
    assert result["before_sha"] == "a" * 40
    assert result["after_blob_sha"] == "b" * 40
    assert result["commit_sha"] == "c" * 40
    assert result["credential_revoked"] is True
    assert result["security_status"] == "COMPLETE"
    assert minted_body == {"repositories": ["sandbox"], "permissions": {"contents": "write"}}
    assert [method for method, _ in calls] == ["POST", "GET", "PUT", "DELETE"]
    assert "jit-installation-token" not in repr(result)


def test_stale_target_state_denies_mutation_and_still_revokes_token():
    intent = _intent()
    envelope = _envelope(intent)
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(201, json={"token": "jit-installation-token"})
        if request.method == "GET":
            return httpx.Response(200, json={"sha": "d" * 40})
        if request.method == "DELETE":
            return httpx.Response(204)
        raise AssertionError("PUT must not occur after stale-state detection")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(EffectBoundaryError, match="target state changed"):
        GitHubEffectBroker(_credentials(client)).execute(envelope, intent)

    assert methods == ["POST", "GET", "DELETE"]


def test_authority_is_rechecked_immediately_before_mutation():
    intent = _intent()
    envelope = _envelope(intent)
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(201, json={"token": "jit-installation-token"})
        if request.method == "GET":
            envelope.expires_at = datetime.now(timezone.utc) - timedelta(milliseconds=1)
            return httpx.Response(200, json={"sha": "a" * 40})
        if request.method == "DELETE":
            return httpx.Response(204)
        raise AssertionError("expired authority must not reach PUT")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(EffectBoundaryError, match="expired"):
        GitHubEffectBroker(_credentials(client)).execute(envelope, intent)
    assert methods == ["POST", "GET", "DELETE"]


def test_authorized_filename_delimiters_are_percent_encoded():
    intent = _intent(path="docs/a?b#c.md")
    envelope = _envelope(intent)
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.raw_path.decode())
        if request.method == "POST":
            return httpx.Response(201, json={"token": "jit-installation-token"})
        if request.method == "GET":
            assert request.url.path.endswith("/contents/docs/a?b#c.md")
            return httpx.Response(200, json={"sha": "a" * 40})
        if request.method == "PUT":
            return httpx.Response(200, json={"content": {"sha": "b" * 40}, "commit": {"sha": "c" * 40}})
        if request.method == "DELETE":
            return httpx.Response(204)
        raise AssertionError

    client = httpx.Client(transport=httpx.MockTransport(handler))
    GitHubEffectBroker(_credentials(client)).execute(envelope, intent)
    content_paths = [p for p in seen_paths if "/contents/" in p]
    assert content_paths
    assert all("%3F" in p and "%23" in p for p in content_paths)


def test_failed_effect_with_unconfirmed_revocation_surfaces_security_incident():
    intent = _intent()
    envelope = _envelope(intent)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"token": "jit-installation-token"})
        if request.method == "GET":
            return httpx.Response(500)
        if request.method == "DELETE":
            return httpx.Response(503)
        raise AssertionError

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(CredentialRevocationError, match="revocation was not confirmed"):
        GitHubEffectBroker(_credentials(client)).execute(envelope, intent)


def test_effect_digest_mismatch_denies_before_any_provider_call():
    intent = _intent()
    envelope = _envelope(intent).model_copy(update={"semantic_intent_digest": "sha256:" + "0" * 64})

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("provider must not be contacted")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(EffectBoundaryError, match="digest does not match"):
        GitHubEffectBroker(_credentials(client)).execute(envelope, intent)
