"""An account must not be able to raise its own privileges, and the GitHub
device-flow exchange must only trust an identity GitHub itself attests."""
import os
import uuid


def _set_test_env():
    os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
    os.environ.setdefault("ENVIRONMENT", "development")
    os.environ.setdefault("DEBUG", "true")
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_lockerphycer.db"


def _signed_in_user(client, *, admin: bool = False):
    """Seed a user and a live session directly, so these tests do not depend on
    email delivery or spend the shared login rate-limit budget."""

    from test_workspace_onboarding import _seed_user

    _, token, _ = _seed_user(admin=admin)
    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    return me.json(), headers


def test_user_cannot_change_own_role_status_or_email():
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as client:
        me, headers = _signed_in_user(client)
        for body in ({"role": "admin"}, {"status": "active"}, {"email": f"other-{uuid.uuid4()}@example.com"}):
            denied = client.put(f"/api/v1/users/{me['id']}", headers=headers, json=body)
            assert denied.status_code == 403, body

        after = client.get("/api/v1/auth/me", headers=headers).json()
        assert after["role"] == "user"
        assert after["email"] == me["email"]

        renamed = client.put(f"/api/v1/users/{me['id']}", headers=headers, json={"full_name": "Renamed User"})
        assert renamed.status_code == 200
        assert renamed.json()["full_name"] == "Renamed User"


def test_user_cannot_create_list_or_read_other_users():
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as client:
        me, headers = _signed_in_user(client)
        other, _ = _signed_in_user(client)

        created = client.post(
            "/api/v1/users/",
            headers=headers,
            json={"email": f"minted-{uuid.uuid4()}@example.com", "username": f"minted-{uuid.uuid4().hex[:8]}", "password": "CorrectHorseBatteryStaple1", "role": "admin"},
        )
        assert created.status_code == 403
        assert client.get("/api/v1/users/", headers=headers).status_code == 403
        assert client.get(f"/api/v1/users/{other['id']}", headers=headers).status_code == 403
        assert client.get(f"/api/v1/users/{me['id']}", headers=headers).status_code == 200


def test_user_cannot_touch_another_account_or_its_sessions():
    """Every mutating or session-revealing users route must refuse a non-admin
    acting on someone else's account, while the account's own sessions stay
    reachable to it and to an admin."""
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as client:
        me, headers = _signed_in_user(client)
        other, other_headers = _signed_in_user(client)
        other_sessions = client.get(f"/api/v1/users/{other['id']}/sessions", headers=other_headers).json()["sessions"]
        assert len(other_sessions) == 1
        other_session_id = other_sessions[0]["id"]

        for method, path in [
            ("put", f"/api/v1/users/{other['id']}"),
            ("delete", f"/api/v1/users/{other['id']}"),
            ("post", f"/api/v1/users/{other['id']}/activate"),
            ("post", f"/api/v1/users/{other['id']}/deactivate"),
            ("post", f"/api/v1/users/{me['id']}/activate"),
            ("post", f"/api/v1/users/{me['id']}/deactivate"),
            ("get", f"/api/v1/users/{other['id']}/sessions"),
            ("delete", f"/api/v1/users/{other['id']}/sessions/{other_session_id}"),
            # The path's user_id is not what authorises a revoke; the session's owner is.
            ("delete", f"/api/v1/users/{me['id']}/sessions/{other_session_id}"),
        ]:
            kwargs = {"json": {"full_name": "Hijacked"}} if method == "put" else {}
            response = getattr(client, method)(path, headers=headers, **kwargs)
            assert response.status_code == 403, (method, path, response.status_code)

        # The other account is untouched and still signed in.
        assert client.get("/api/v1/auth/me", headers=other_headers).status_code == 200
        assert client.get("/api/v1/auth/me", headers=other_headers).json()["full_name"] != "Hijacked"

        _, admin_headers = _signed_in_user(client, admin=True)
        assert client.get(f"/api/v1/users/{other['id']}/sessions", headers=admin_headers).status_code == 200
        revoked = client.delete(f"/api/v1/users/{other['id']}/sessions/{other_session_id}", headers=admin_headers)
        assert revoked.status_code == 200
        assert client.get("/api/v1/auth/me", headers=other_headers).status_code == 401


def test_admin_can_still_manage_users():
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as client:
        _, admin_headers = _signed_in_user(client, admin=True)
        other, _ = _signed_in_user(client)

        assert client.get("/api/v1/users/", headers=admin_headers).status_code == 200
        promoted = client.put(f"/api/v1/users/{other['id']}", headers=admin_headers, json={"role": "security_analyst"})
        assert promoted.status_code == 200
        assert promoted.json()["role"] == "security_analyst"


def test_github_exchange_rejects_a_bare_username():
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    with TestClient(app) as client:
        response = client.post("/api/v1/auth/github/exchange", json={"github_username": "octocat"})
        assert response.status_code == 422
        assert "access_token" not in response.text.replace("github_access_token", "")


def test_github_exchange_requires_a_token_github_attests(monkeypatch):
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app
    from apps.api.routers import auth as auth_router

    monkeypatch.setenv("GITHUB_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "test-client-secret")
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, auth=None, headers=None, json=None):
            calls.append((url, auth, json))
            if json["access_token"] == "gho_" + "a" * 36:
                return FakeResponse(200, {"user": {"login": "Octo-Cat"}})
            return FakeResponse(404, {"message": "Not Found"})

    monkeypatch.setattr(auth_router, "_github_http_client", FakeClient)

    with TestClient(app) as client:
        rejected = client.post("/api/v1/auth/github/exchange", json={"github_access_token": "gho_" + "b" * 36})
        assert rejected.status_code == 401
        assert "access_token" not in rejected.json()

        accepted = client.post("/api/v1/auth/github/exchange", json={"github_access_token": "gho_" + "a" * 36})
        assert accepted.status_code == 200
        body = accepted.json()
        assert body["user"]["email"] == "octo-cat@machine.veklom.com"
        assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}).status_code == 200

    assert calls[0][0] == "https://api.github.com/applications/test-client-id/token"
    assert calls[0][1] == ("test-client-id", "test-client-secret")


def test_github_exchange_is_unavailable_without_app_credentials(monkeypatch):
    _set_test_env()
    from fastapi.testclient import TestClient
    from apps.api.main import app

    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/github/exchange", json={"github_access_token": "gho_" + "a" * 36})
        assert response.status_code == 503
