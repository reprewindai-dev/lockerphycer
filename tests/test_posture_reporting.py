"""Posture endpoints must not invent evidence: with no vault and no control
registry connected, they report not_implemented / unwired, not healthy."""
import os


def _set_test_env():
    os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("DEBUG", "true")
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_lockerphycer.db"


def _session(client, *, admin: bool = False):
    from test_workspace_onboarding import _seed_user

    _, token, _ = _seed_user(admin=admin)
    return {"Authorization": f"Bearer {token}"}


def test_vault_posture_is_reported_as_not_implemented():
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as client:
        assert client.get("/api/v1/command-center/governance/vault").status_code in (401, 403)
        assert client.get("/api/v1/command-center/governance/vault", headers=_session(client)).status_code == 403

        body = client.get("/api/v1/command-center/governance/vault", headers=_session(client, admin=True)).json()
        assert body["status"] == "not_implemented"
        assert body["wired"] is False
        assert body["secrets_stored"] == 0
        assert body["encryption"] is None and body["key_rotation_days"] is None and body["last_rotation"] is None


def test_security_controls_are_not_reported_as_enabled():
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as client:
        controls = client.get("/api/v1/security/controls", headers=_session(client)).json()
        assert controls, "the catalogue of planned controls is still listed"
        for control in controls:
            assert control["enabled"] is False, control
            assert control["status"] == "not_implemented" and control["wired"] is False, control


def test_compliance_does_not_claim_database_encryption():
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as client:
        body = client.get("/api/v1/command-center/governance/compliance", headers=_session(client, admin=True)).json()
        policies = {p["name"]: p for p in body["policies"]}
        assert policies["Data Encryption at Rest"]["evidence"] == "not_wired"
        assert policies["MFA Requirement"]["evidence"] == "configured"
