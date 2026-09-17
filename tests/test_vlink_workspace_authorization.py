import asyncio
from types import SimpleNamespace

from fastapi import HTTPException, Response

from apps.api.routers.workspace import authorize_vlink_workspace


class WorkspaceLookup:
    def __init__(self, workspace):
        self.workspace = workspace

    async def get(self, _model, workspace_id):
        if self.workspace and self.workspace.id == workspace_id:
            return self.workspace
        return None


def run_authorization(workspace, email="owner@example.com", workspace_id="ws-owned"):
    response = Response()
    result = asyncio.run(
        authorize_vlink_workspace(
            workspace_id,
            response=response,
            current_user=SimpleNamespace(email=email),
            db=WorkspaceLookup(workspace),
        )
    )
    return result, response


def test_owner_session_authorizes_exact_active_workspace():
    workspace = SimpleNamespace(id="ws-owned", owner_id="owner@example.com", is_active=True)

    result, response = run_authorization(workspace)

    assert result == {
        "authorized": True,
        "workspace_id": "ws-owned",
    }
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["vary"] == "Authorization"


def test_non_owner_is_denied_even_when_user_is_authenticated():
    workspace = SimpleNamespace(id="ws-owned", owner_id="owner@example.com", is_active=True)

    try:
        run_authorization(workspace, email="other@example.com")
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "Workspace ownership required"
    else:
        raise AssertionError("non-owner session unexpectedly authorized")


def test_inactive_workspace_cannot_authorize_vlink_creation():
    workspace = SimpleNamespace(id="ws-owned", owner_id="owner@example.com", is_active=False)

    try:
        run_authorization(workspace)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("inactive workspace unexpectedly authorized")


def test_unknown_workspace_fails_closed():
    try:
        run_authorization(None)
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("unknown workspace unexpectedly authorized")
