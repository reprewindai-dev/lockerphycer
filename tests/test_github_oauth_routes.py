from apps.api.main import app
from apps.api.routers.github_auth import login_redirect


def test_github_oauth_router_is_registered():
    paths = {route.path for route in app.routes}
    assert "/api/v1/auth/github/login" in paths
    assert "/api/v1/auth/github/callback" in paths


def test_callback_redirect_does_not_trust_github_referer(monkeypatch):
    from starlette.requests import Request

    monkeypatch.setenv("PUBLIC_FRONTEND_URL", "https://veklom.com")
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/github/callback",
            "headers": [(b"referer", b"https://github.com/login/oauth/authorize")],
        }
    )
    response = login_redirect("/os", request)
    assert response.headers["location"] == "https://veklom.com/os"


def _oauth_app(monkeypatch):
    import apps.api.routers.github_auth as github_auth

    monkeypatch.setattr(github_auth, "CLIENT_ID", "Iv1.test-client-id")
    monkeypatch.setattr(github_auth, "CLIENT_SECRET", "test-client-secret-" + "x" * 32)
    monkeypatch.setenv("PUBLIC_FRONTEND_URL", "https://veklom.com")
    return github_auth


def test_state_signature_is_compared_in_constant_time_and_tampering_is_rejected(monkeypatch):
    import base64
    import hmac
    import json

    github_auth = _oauth_app(monkeypatch)
    calls = []
    real_compare = hmac.compare_digest
    monkeypatch.setattr(hmac, "compare_digest", lambda a, b: calls.append((a, b)) or real_compare(a, b))

    state = github_auth.sign_state("/os", "nonce-123")
    assert github_auth.verify_state(state) == {"next": "/os", "nonce": "nonce-123"}
    assert calls, "signature must go through hmac.compare_digest"

    parsed = json.loads(base64.urlsafe_b64decode(state))
    parsed["sig"] = ("0" if parsed["sig"][0] != "0" else "1") + parsed["sig"][1:]
    forged = base64.urlsafe_b64encode(json.dumps(parsed).encode()).decode()
    assert github_auth.verify_state(forged) is None
    assert github_auth.verify_state("not-a-state") is None


def test_return_target_is_limited_to_configured_origins(monkeypatch):
    from starlette.requests import Request

    github_auth = _oauth_app(monkeypatch)
    monkeypatch.setenv("LOCKERPHYCER_CORS_ORIGINS", "https://preview.veklom.com")
    request = Request({"type": "http", "method": "GET", "path": "/api/v1/auth/github/callback", "headers": []})

    assert github_auth.safe_return_to("/os/settings") == "/os/settings"
    assert github_auth.safe_return_to("https://preview.veklom.com/os") == "https://preview.veklom.com/os"
    assert github_auth.safe_return_to("https://veklom.com/os") == "https://veklom.com/os"
    for bad in ("https://evil.example/os", "//evil.example/os", "https://veklom.com@evil.example/", "javascript:alert(1)", "/os\\evil"):
        assert github_auth.safe_return_to(bad) == "/os", bad
        assert github_auth.login_redirect(bad, request).headers["location"] == "https://veklom.com/os", bad


def test_callback_refuses_a_state_that_this_browser_did_not_start(monkeypatch):
    from fastapi.testclient import TestClient
    from apps.api.main import app

    github_auth = _oauth_app(monkeypatch)
    with TestClient(app) as client:
        started = client.get("/api/v1/auth/github/login", params={"next": "/os"}, follow_redirects=False)
        assert started.status_code == 302
        nonce_cookie = started.headers["set-cookie"]
        assert nonce_cookie.startswith(f"{github_auth.NONCE_COOKIE}=") and "HttpOnly" in nonce_cookie
        state = started.headers["location"].split("state=")[1].split("&")[0]

        # Same signed state, no nonce cookie (another browser, or a replay): refused before any GitHub call.
        client.cookies.clear()
        replayed = client.get("/api/v1/auth/github/callback", params={"code": "abc", "state": state}, follow_redirects=False)
        assert replayed.status_code == 302
        assert replayed.headers["location"].startswith("https://veklom.com/login?github_error_description=OAuth%20state%20did%20not%20match")

        # A different browser's nonce does not match either.
        client.cookies.set(github_auth.NONCE_COOKIE, "0" * 32)
        wrong = client.get("/api/v1/auth/github/callback", params={"code": "abc", "state": state}, follow_redirects=False)
        assert wrong.headers["location"].startswith("https://veklom.com/login?github_error_description=OAuth%20state%20did%20not%20match")


class _FakeGitHubResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeGitHub:
    """Stands in for httpx.AsyncClient: GitHub attests one user."""

    login = "octo-test"
    email = "octo-test@example.com"

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        return _FakeGitHubResponse(200, {"access_token": "gho_test_token"})

    async def get(self, url, **kwargs):
        if url.endswith("/user"):
            return _FakeGitHubResponse(200, {"id": 424242, "login": self.login, "name": "Octo Test", "email": None})
        return _FakeGitHubResponse(200, [{"email": self.email, "primary": True, "verified": True}])


def test_callback_sets_httponly_cookies_and_records_the_trusted_client_ip(monkeypatch):
    import asyncio
    import uuid

    from fastapi.testclient import TestClient
    from sqlalchemy import select

    from apps.api.main import app
    from core.config.settings import settings
    from core.database.database import SessionLocal
    from db.models import User, UserSession

    github_auth = _oauth_app(monkeypatch)
    suffix = uuid.uuid4().hex[:10]
    monkeypatch.setattr(_FakeGitHub, "login", f"octo-{suffix}")
    monkeypatch.setattr(_FakeGitHub, "email", f"octo-{suffix}@example.com")
    monkeypatch.setattr(github_auth.httpx, "AsyncClient", _FakeGitHub)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    with TestClient(app, base_url="https://testserver") as client:  # Secure cookies need https
        started = client.get("/api/v1/auth/github/login", params={"next": "/os/settings"}, follow_redirects=False)
        assert "Secure" in started.headers["set-cookie"]
        state = started.headers["location"].split("state=")[1].split("&")[0]
        done = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "abc", "state": state},
            headers={"CF-Connecting-IP": "203.0.113.9", "X-Forwarded-For": "1.2.3.4"},
            follow_redirects=False,
        )
        assert done.status_code == 302, done.text
        assert done.headers["location"] == "https://veklom.com/os/settings"

        cookies = {c.split("=", 1)[0]: c for c in done.headers.get_list("set-cookie")}
        for name in (github_auth.SESSION_COOKIE, "veklom_github_token"):
            assert "HttpOnly" in cookies[name], cookies[name]
            assert "Secure" in cookies[name], cookies[name]
            assert "samesite=lax" in cookies[name].lower(), cookies[name]
        assert 'Max-Age=0' in cookies[github_auth.NONCE_COOKIE] or 'expires=' in cookies[github_auth.NONCE_COOKIE].lower()

    async def recorded_ip():
        async with SessionLocal() as db:
            user = (await db.execute(select(User).where(User.email == _FakeGitHub.email))).scalars().one()
            session = (await db.execute(select(UserSession).where(UserSession.user_id == user.id))).scalars().one()
            return session.ip_address

    assert asyncio.run(recorded_ip()) == "203.0.113.9"
