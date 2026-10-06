"""GitHub OAuth Routes"""

import os
import json
import base64
import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Request, Response, HTTPException, status
from fastapi.responses import RedirectResponse
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config.settings import settings
from core.database.database import get_db
from core.security.auth import create_access_token, create_refresh_token, hash_token, session_claims
from core.security.middleware import allowed_request_origins, trusted_client_ip
from db.models import User, UserSession, UserRole, UserStatus
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
router = APIRouter()

CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")
# The callback URL we tell GitHub to return to. Must match GitHub OAuth App config.
CALLBACK_URL = os.environ.get("GITHUB_CALLBACK_URL", "https://veklom.com/api/v1/auth/github/callback")
SESSION_COOKIE = os.environ.get("VEKLOM_SESSION_COOKIE_NAME", "veklom_session")
# Binds the signed OAuth state to the browser that started the login.
NONCE_COOKIE = "veklom_oauth_nonce"
STATE_TTL_SECONDS = 15 * 60


def _public_base_url() -> str:
    return os.environ.get("PUBLIC_FRONTEND_URL", "https://veklom.com").rstrip("/")


def _allowed_redirect_origins() -> set[str]:
    """Origins a post-login redirect may land on: the configured frontend and
    the CORS allowlist (LOCKERPHYCER_CORS_ORIGINS plus the known Veklom hosts)."""
    return allowed_request_origins() | {_public_base_url()}


def _cookie_secure() -> bool:
    return settings.ENVIRONMENT == "production"


def _nonce_cookie_path(request: Request) -> str:
    # The router prefix (…/auth/github) covers both /login and /callback.
    return request.url.path.rsplit("/", 1)[0] or "/"


@router.get("/config-status")
async def github_config_status():
    present = {
        "client_id": bool(CLIENT_ID),
        "client_secret": bool(CLIENT_SECRET),
        "callback_url": bool(CALLBACK_URL),
    }
    return {
        "configured": all(present.values()),
        "present": present,
        "missing": [name for name, configured in present.items() if not configured],
    }


def safe_return_to(value: str | None) -> str:
    """A relative path on the frontend, or an absolute URL on an allowed origin;
    anything else falls back to /os."""
    if not value or "\\" in value:
        return "/os"
    if value.startswith("/"):
        return "/os" if value.startswith("//") else value
    parts = urlsplit(value)
    if parts.scheme in ("http", "https") and parts.netloc:
        if f"{parts.scheme}://{parts.netloc}" in _allowed_redirect_origins():
            return value
    return "/os"

def sign_state(next_url: str, nonce: str) -> str:
    if not CLIENT_SECRET:
        raise ValueError("GITHUB_CLIENT_SECRET is missing")
    payload = json.dumps({"next": next_url, "nonce": nonce, "ts": int(time.time() * 1000)}, separators=(',', ':'))
    sig = hmac.new(CLIENT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    state_obj = {"payload": payload, "sig": sig}
    return base64.urlsafe_b64encode(json.dumps(state_obj, separators=(',', ':')).encode()).decode()

def verify_state(state: str) -> dict | None:
    """The signed state's ``next`` and ``nonce``; None when the signature,
    shape or age is wrong. The caller still has to match the nonce against
    the browser's cookie."""
    try:
        if not CLIENT_SECRET:
            return None
        parsed = json.loads(base64.urlsafe_b64decode(state).decode())
        payload = parsed.get("payload")
        sig = parsed.get("sig")
        if not isinstance(payload, str) or not isinstance(sig, str):
            return None
        expected = hmac.new(CLIENT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(payload)
        nonce = data.get("nonce")
        if not isinstance(nonce, str) or not nonce:
            return None
        if int(time.time() * 1000) - int(data.get("ts", 0)) > STATE_TTL_SECONDS * 1000:
            return None
        return {"next": data.get("next", "/os"), "nonce": nonce}
    except Exception:
        return None

def derive_password(github_id: int) -> str:
    if not CLIENT_SECRET:
        raise ValueError("GITHUB_CLIENT_SECRET is missing")
    return hmac.new(CLIENT_SECRET.encode(), f"veklom-github-{github_id}".encode(), hashlib.sha256).hexdigest()


def login_redirect(destination: str, request: Request, error: str = None) -> RedirectResponse:
    # OAuth callbacks arrive from GitHub, so Origin/Referer are not trusted as
    # the Veklom return host. Relative destinations land on the configured
    # public frontend; absolute ones must be on an allowed origin.
    destination = safe_return_to(destination)
    url = f"{_public_base_url()}{destination}" if destination.startswith("/") else destination
    if error:
        url += f"?github_error_description={error[:240]}"
    return RedirectResponse(url=url, status_code=302)


@router.get("/login")
async def github_login(request: Request, next: str = "/os"):
    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="GitHub OAuth is not configured")

    safe_next = safe_return_to(next)
    nonce = os.urandom(16).hex()
    state = sign_state(safe_next, nonce)

    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": CALLBACK_URL,
        "scope": "user:email read:user",
        "state": state
    }
    github_url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    response = RedirectResponse(url=github_url, status_code=302)
    response.set_cookie(
        key=NONCE_COOKIE,
        value=nonce,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path=_nonce_cookie_path(request),
        max_age=STATE_TTL_SECONDS,
    )
    return response


@router.get("/callback")
async def github_callback(request: Request, db: AsyncSession = Depends(get_db)):
    error_param = request.query_params.get("error")
    code = request.query_params.get("code")
    state_param = request.query_params.get("state")

    if error_param:
        desc = request.query_params.get("error_description") or error_param
        return login_redirect("/login", request, desc)

    if not code or not state_param:
        return login_redirect("/login", request, "Missing OAuth code or state")

    state_data = verify_state(state_param)
    if not state_data:
        return login_redirect("/login", request, "Invalid or expired OAuth state. Please try again.")
    nonce_cookie = request.cookies.get(NONCE_COOKIE) or ""
    if not hmac.compare_digest(nonce_cookie, state_data["nonce"]):
        return login_redirect("/login", request, "OAuth state did not match this browser. Please try again.")

    # Step 1: Exchange code
    async with httpx.AsyncClient() as client:
        try:
            token_res = await client.post(
                "https://github.com/login/oauth/access_token",
                json={"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "code": code, "redirect_uri": CALLBACK_URL},
                headers={"Accept": "application/json"}
            )
            token_data = token_res.json()
            if "error" in token_data or "access_token" not in token_data:
                return login_redirect("/login", request, token_data.get("error_description", "GitHub token exchange failed"))
            github_token = token_data["access_token"]
        except Exception:
            return login_redirect("/login", request, "Could not reach GitHub. Please try again.")

        # Step 2: Get User Info
        try:
            user_res = await client.get("https://api.github.com/user", headers={"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"})
            emails_res = await client.get("https://api.github.com/user/emails", headers={"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"})
            
            if user_res.status_code != 200:
                logger.warning("GitHub /user returned %s", user_res.status_code)
                return login_redirect("/login", request, "Could not retrieve GitHub user info.")
            github_user = user_res.json()
            # /user/emails needs the GitHub App "Email addresses: read" account permission.
            # Without it GitHub returns 403 with an error object; fall back to the profile email.
            emails = emails_res.json() if emails_res.status_code == 200 else []
            if emails_res.status_code != 200:
                logger.warning("GitHub /user/emails returned %s; using profile email", emails_res.status_code)

            primary_email = next((e["email"] for e in emails if e.get("primary") and e.get("verified")), None)
            if not primary_email:
                primary_email = next((e["email"] for e in emails if e.get("verified")), None)
            if not primary_email:
                primary_email = github_user.get("email")
                
            if not primary_email:
                return login_redirect("/login", request, "No verified email on your GitHub account. Please add one and try again.")
                
        except Exception:
            return login_redirect("/login", request, "Could not retrieve GitHub user info.")

    # Step 3: Find or Create User
    password = derive_password(github_user["id"])
    display_name = github_user.get("name") or github_user.get("login")
    username_base = "".join(c if c.isalnum() else "_" for c in github_user.get("login", "")).strip("_")[:80]

    # Try login first
    from core.security.auth import get_password_hash, verify_password
    
    user = (await db.execute(select(User).where(User.email == primary_email))).scalars().first()
    
    if user:
        if not verify_password(password, user.hashed_password):
            return login_redirect("/login", request, "An account with this email already exists. Sign in with your password first, then link GitHub in settings.")
    else:
        # Register new user
        user = User(
            email=primary_email,
            username=username_base,
            hashed_password=get_password_hash(password),
            full_name=display_name,
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # Issue Session
    user.last_login = datetime.utcnow()
    user.last_activity = datetime.utcnow()
    
    claims = await session_claims(db, user)
    access_token = create_access_token(claims)
    refresh_token = create_refresh_token(claims)

    session = UserSession(
        user_id=user.id,
        session_token_hash=hash_token(access_token),
        refresh_token_hash=hash_token(refresh_token),
        ip_address=trusted_client_ip(request),
        user_agent="GitHub OAuth",
        expires_at=datetime.utcnow() + timedelta(minutes=60),
    )
    db.add(session)
    await db.commit()

    # Step 4: Redirect to frontend with cookies (login_redirect re-validates
    # the destination against the allowed origins).
    response = login_redirect(state_data["next"], request)
    response.delete_cookie(key=NONCE_COOKIE, path=_nonce_cookie_path(request))

    # Set HttpOnly Session Cookie
    response.set_cookie(
        key=SESSION_COOKIE,
        value=access_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
        max_age=7 * 24 * 60 * 60
    )

    # Short-lived bearer handoff. HttpOnly: scripts on the page must not be
    # able to read the session token.
    response.set_cookie(
        key="veklom_github_token",
        value=access_token,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
        max_age=60
    )

    return response

