import asyncio

import apps.api.routers.github_auth as github_auth


def test_github_config_status_reports_missing_secret(monkeypatch):
    monkeypatch.setattr(github_auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(github_auth, "CLIENT_SECRET", None)
    monkeypatch.setattr(github_auth, "CALLBACK_URL", "https://veklom.dev/api/v1/auth/github/callback")

    result = asyncio.run(github_auth.github_config_status())

    assert result["configured"] is False
    assert result["missing"] == ["client_secret"]
    assert result["present"]["client_secret"] is False


def test_github_config_status_reports_configured_without_exposing_secret(monkeypatch):
    monkeypatch.setattr(github_auth, "CLIENT_ID", "client-id")
    monkeypatch.setattr(github_auth, "CLIENT_SECRET", "do-not-return")
    monkeypatch.setattr(github_auth, "CALLBACK_URL", "https://veklom.dev/api/v1/auth/github/callback")

    result = asyncio.run(github_auth.github_config_status())

    assert result["configured"] is True
    assert result["missing"] == []
    assert "do-not-return" not in repr(result)
