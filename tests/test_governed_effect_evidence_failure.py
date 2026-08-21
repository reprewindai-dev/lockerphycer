from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from core.execution_cells.effects import (
    GitHubAppConfig,
    GitHubAppCredentialBroker,
    GitHubEffectBroker,
    GitHubFileUpdateIntent,
    effect_digest,
)
from core.execution_cells.models import AuthorizedExecutionEnvelope, CellResourceLimits


def _private_key_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")


def _intent() -> GitHubFileUpdateIntent:
    return GitHubFileUpdateIntent(
        owner="reprewindai-dev",
        repo="sandbox",
        branch="main",
        path="README.md",
        expected_blob_sha="a" * 40,
        content_b64=base64.b64encode(b"governed\n").decode("ascii"),
        commit_message="test: accepted effect evidence",
    )


def _envelope(intent: GitHubFileUpdateIntent) -> AuthorizedExecutionEnvelope:
    now = datetime.now(timezone.utc)
    return AuthorizedExecutionEnvelope(
        execution_id="exec-evidence",
        path_id="path-evidence",
        request_id="request-evidence",
        idempotency_key="idem-evidence",
        grant_id="grant-evidence",
        subject_id="agent-evidence",
        tenant_id="tenant",
        workspace_id="workspace",
        capability_id="github.file.update",
        semantic_intent_digest=effect_digest(intent),
        resource_constraints=CellResourceLimits(),
        authority_epoch=1,
        assignment_id="assignment",
        runtime_kind="lockerphycer-cell",
        runtime_instance="host",
        required_isolation="os-enforced",
        runtime_image_digest="sha256:" + "b" * 64,
        network_policy_digest="network:none",
        policy_digest="sha256:policy",
        allowed_provider_set=["github"],
        budget_ceiling=100,
        evidence_profile="pgl-required",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=1),
        nonce="0123456789abcdef0123456789abcdef",
    )


def test_accepted_mutation_with_malformed_response_is_not_recast_as_failed() -> None:
    intent = _intent()
    envelope = _envelope(intent)
    get_count = 0
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_count
        methods.append(request.method)
        if request.method == "POST":
            return httpx.Response(201, json={"token": "jit-token"})
        if request.method == "GET":
            get_count += 1
            if get_count == 1:
                return httpx.Response(200, json={"sha": "a" * 40})
            return httpx.Response(200, json={"sha": "b" * 40})
        if request.method == "PUT":
            # Target accepted the consequence, but its response is unusable as JSON.
            return httpx.Response(200, content=b"not-json")
        if request.method == "DELETE":
            return httpx.Response(204)
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.test")
    credentials = GitHubAppCredentialBroker(
        GitHubAppConfig(
            app_id="123",
            installation_id="456",
            private_key_pem=_private_key_pem(),
            api_base="https://api.github.test",
            revocation_attempts=1,
        ),
        client=client,
    )

    result = GitHubEffectBroker(credentials).execute(envelope, intent)

    assert result["mutation_succeeded"] is True
    assert result["mutation_http_status"] == 200
    assert result["mutation_response_body_verified"] is False
    assert result["after_blob_sha"] == "b" * 40
    assert result["target_result_confirmed"] is True
    assert result["credential_revoked"] is True
    assert result["security_status"] == "COMPLETE"
    assert methods == ["POST", "GET", "PUT", "GET", "DELETE"]


def test_accepted_mutation_without_recoverable_after_state_is_evidence_incomplete() -> None:
    intent = _intent()
    envelope = _envelope(intent)
    get_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_count
        if request.method == "POST":
            return httpx.Response(201, json={"token": "jit-token"})
        if request.method == "GET":
            get_count += 1
            if get_count == 1:
                return httpx.Response(200, json={"sha": "a" * 40})
            return httpx.Response(503)
        if request.method == "PUT":
            return httpx.Response(201, content=b"{broken")
        if request.method == "DELETE":
            return httpx.Response(204)
        raise AssertionError(request.url)

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.github.test")
    credentials = GitHubAppCredentialBroker(
        GitHubAppConfig(
            app_id="123",
            installation_id="456",
            private_key_pem=_private_key_pem(),
            api_base="https://api.github.test",
            revocation_attempts=1,
        ),
        client=client,
    )

    result = GitHubEffectBroker(credentials).execute(envelope, intent)

    assert result["mutation_succeeded"] is True
    assert result["target_result_confirmed"] is False
    assert result["credential_revoked"] is True
    assert result["security_status"] == "ACCEPTED_EVIDENCE_INCOMPLETE"
    assert result["mutation_evidence_status"] == "ACCEPTED_EVIDENCE_INCOMPLETE"
