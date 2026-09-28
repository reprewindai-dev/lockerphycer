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
