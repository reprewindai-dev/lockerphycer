import asyncio
import pytest
from fastapi import HTTPException
from apps.api.routers.auth import GitHubExchangeRequest, github_exchange


def test_username_cannot_create_identity_or_session():
    class NoDatabaseAccess:
        def __getattr__(self, name):
            raise AssertionError('Username exchange must not access identity store')
    with pytest.raises(HTTPException) as exc:
        asyncio.run(github_exchange(GitHubExchangeRequest(github_username='claimed-owner'),
                                    request=None, db=NoDatabaseAccess()))
    assert exc.value.status_code == 410
