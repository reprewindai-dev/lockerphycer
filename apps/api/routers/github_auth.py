"""GitHub OAuth Routes"""

import os
import json
import base64
import hashlib
import hmac
import time
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, Request, Response, HTTPException, status
from fastapi.responses import RedirectResponse
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database.database import get_db
from core.security.auth import create_access_token, create_refresh_token
from db.models import User, UserSession, UserRole, UserStatus
from datetime import datetime, timedelta

router = APIRouter()

CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")
# The callback URL we tell GitHub to return to. Must match GitHub OAuth App config.
CALLBACK_URL = os.environ.get("GITHUB_CALLBACK_URL", "https://veklom.com/api/v1/auth/github/callback")
SESSION_COOKIE = os.environ.get("VEKLOM_SESSION_COOKIE_NAME", "veklom_session")


def safe_return_to(value: str | None) -> str:
    if not value:
        return "/os"
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/os"
    return value

def sign_state(next_url: str, nonce: str) -> str:
    if not CLIENT_SECRET:
        raise ValueError("GITHUB_CLIENT_SECRET is missing")
    payload = json.dumps({"next": next_url, "nonce": nonce, "ts": int(time.time() * 1000)}, separators=(',', ':'))
    sig = hmac.new(CLIENT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    state_obj = {"payload": payload, "sig": sig}
    return base64.urlsafe_b64encode(json.dumps(state_obj, separators=(',', ':')).encode()).decode()

def verify_state(state: str) -> dict | None:
    try:
        if not CLIENT_SECRET:
            return None
        parsed = json.loads(base64.urlsafe_b64decode(state).decode())
        payload = parsed.get("payload")
        sig = parsed.get("sig")
        expected = hmac.new(CLIENT_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if sig != expected:
            return None
        data = json.loads(payload)
        # Reject state older than 15 minutes
        if int(time.time() * 1000) - data.get("ts", 0) > 15 * 60 * 1000:
            return None
        return {"next": data.get("next", "/os")}
    except Exception:
        return None

def derive_password(github_id: int) -> str:
    if not CLIENT_SECRET:
        raise ValueError("GITHUB_CLIENT_SECRET is missing")
    return hmac.new(CLIENT_SECRET.encode(), f"veklom-github-{github_id}".encode(), hashlib.sha256).hexdigest()


def login_redirect(destination: str, request: Request, error: str = None) -> RedirectResponse:
    # Assuming the frontend is where we redirect for login errors
    base_url = "https://veklom.com"
    # Try to extract the origin from headers if possible
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin:
        parsed_origin = urlparse(origin)
        base_url = f"{parsed_origin.scheme}://{parsed_origin.netloc}"
        
    url = f"{base_url}{destination}" if destination.startswith("/") else destination
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
    return RedirectResponse(url=github_url, status_code=302)


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
            
            github_user = user_res.json()
            emails = emails_res.json()
            
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
    
    access_token = create_access_token({"sub": user.email})
    refresh_token = create_refresh_token({"sub": user.email})

    session = UserSession(
        user_id=user.id,
        session_token=access_token,
        refresh_token=refresh_token,
        ip_address="127.0.0.1",
        user_agent="GitHub OAuth",
        expires_at=datetime.utcnow() + timedelta(minutes=60),
    )
    db.add(session)
    await db.commit()

    # Step 4: Redirect to frontend with cookies
    destination = state_data["next"]
    if not destination.startswith("/"):
        destination = "/os"
        
    response = login_redirect(destination, request)
    
    # Set HttpOnly Session Cookie
    response.set_cookie(
        key=SESSION_COOKIE,
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        max_age=7 * 24 * 60 * 60
    )
    
    # Set readable bearer token for frontend
    response.set_cookie(
        key="veklom_github_token",
        value=access_token,
        httponly=False,
        secure=True,
        samesite="lax",
        path="/",
        max_age=60
    )
    
    return response

