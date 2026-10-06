"""The unverified GitHub username exchange is retired.

A bare username is not proof of GitHub ownership. The exchange only accepts a
GitHub access token, and it never touches the identity store before GitHub has
attested that token against this deployment's own OAuth application.
"""
import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from apps.api.routers.auth import GitHubExchangeRequest, github_exchange


class NoDatabaseAccess:
    def __getattr__(self, name):
        raise AssertionError('Unverified exchange must not access identity store')


def test_username_is_not_an_accepted_credential():
    with pytest.raises(ValidationError):
        GitHubExchangeRequest(github_username='claimed-owner')


def test_token_without_app_attestation_cannot_create_identity_or_session(monkeypatch):
    monkeypatch.delenv("GITHUB_CLIENT_ID", raising=False)
    monkeypatch.delenv("GITHUB_CLIENT_SECRET", raising=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(github_exchange(GitHubExchangeRequest(github_access_token='gho_' + 'x' * 36),
                                    request=None, db=NoDatabaseAccess()))
    assert exc.value.status_code == 503
