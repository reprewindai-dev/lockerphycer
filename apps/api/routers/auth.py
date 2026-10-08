"""Authentication routes."""

import asyncio
import hashlib
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.schemas.auth import (
    EmailVerificationConfirm,
    EmailVerificationRequest,
    LoginRequest,
    AgreementAcceptRequest,
    LoginResponse,
    PasswordReset,
    PasswordResetConfirm,
    RegisterRequest,
    UserResponse,
)
from apps.email.sender import send_password_reset, send_verify_email, send_welcome
from apps.email.outbox import enqueue_identity_email
from core.config.settings import settings
from core.database.database import get_db
from core.entitlements.activation import emit_activation_event
from core.security.mfa import verify_mfa_code
from core.security.middleware import trusted_client_ip
from core.security.auth import (
    session_claims,
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    create_refresh_token,
    get_current_user,
    get_password_hash,
    hash_token,
    verify_password,
    verify_token,
)
from core.agreements import CURRENT_AGREEMENTS
from db.models import AgreementAcceptance, User, UserSession, UserRole, UserStatus

router = APIRouter()
security = HTTPBearer()


def _email_verified(user: User) -> bool:
    # There is no separate verified flag: registration creates the account
    # INACTIVE, login refuses INACTIVE ("Email verification required"), and
    # /email-verification/confirm is what moves it to ACTIVE.
    return user.status == UserStatus.ACTIVE


def _user_response(user: User) -> UserResponse:
    payload = UserResponse.model_validate(user).model_dump(mode="json")
    payload["email_verified"] = _email_verified(user)
    payload["_links"] = {
        "self": {"href": "/api/v1/auth/me", "method": "GET"},
        "workspace": {"href": "/api/v1/workspace", "method": "GET"},
    }
    return UserResponse(**payload)


def _first_name(user: User) -> str:
    name = (user.full_name or user.username or "there").strip()
    return name.split()[0] if name else "there"


def _credential_version(user: User) -> str:
    return hashlib.sha256(user.hashed_password.encode("utf-8")).hexdigest()


def _request_metadata(request: Request) -> tuple[str | None, str | None]:
    ip_address = trusted_client_ip(request)
    user_agent = request.headers.get("user-agent")
    return ip_address, user_agent[:512] if user_agent else None


def _verification_url(token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/verify-email?token={quote(token)}"


def _password_reset_url(token: str) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/reset-password?token={quote(token)}"


async def _send_verification(user: User) -> bool:
    token = create_email_verification_token(user.email)
    message_id = await asyncio.to_thread(
        send_verify_email,
        user.email,
        _first_name(user),
        _verification_url(token),
    )
    return bool(message_id)


async def _send_reset(user: User) -> bool:
    token = create_password_reset_token(user.email, _credential_version(user))
    message_id = await asyncio.to_thread(
        send_password_reset,
        user.email,
        _first_name(user),
        _password_reset_url(token),
    )
    return bool(message_id)


def _require_all_current(document_types: list[str]) -> set[str]:
    """The ticked document types, or 422 unless they are exactly the current agreements."""
    accepted = set(document_types)
    missing = sorted(set(CURRENT_AGREEMENTS) - accepted)
    unknown = sorted(accepted - set(CURRENT_AGREEMENTS))
    if missing or unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "AGREEMENTS_INCOMPLETE: every current agreement must be accepted"
                + (f"; missing: {', '.join(missing)}" if missing else "")
                + (f"; unknown: {', '.join(unknown)}" if unknown else "")
            ),
        )
    return accepted


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    accepted = None
    if user_data.accepted_agreements is not None:
        accepted = _require_all_current(user_data.accepted_agreements)
    normalized_email = user_data.email.strip().lower()
    existing_user = (await db.execute(select(User).where(User.email == normalized_email))).scalars().first()
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(
        email=normalized_email,
        username=user_data.username,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        role=UserRole.USER,
        # INACTIVE is the pre-verification state. SUSPENDED remains reserved for
        # administrative/security suspension and is never reactivated by email.
        status=UserStatus.INACTIVE,
    )
    db.add(user)
    await db.flush()

    # What the person accepted commits with the account, or neither does.
    if accepted is not None:
        ip_address, user_agent = _request_metadata(request)
        for document_type in sorted(accepted):
            db.add(AgreementAcceptance(
                user_id=user.id,
                document_type=document_type,
                document_version=CURRENT_AGREEMENTS[document_type],
                source="signup_form",
                ip_address=ip_address,
                user_agent=user_agent,
            ))

    # Identity and delivery intent commit atomically. No network I/O here.
    await enqueue_identity_email(db, user, "verification")

    await db.commit()
    await db.refresh(user)
    response = _user_response(user)
    await emit_activation_event(db, "signup_completed", user_id=user.id)
    return response


@router.post("/email-verification/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    payload: EmailVerificationRequest,
    db: AsyncSession = Depends(get_db),
):
    normalized_email = payload.email.strip().lower()
    user = (await db.execute(select(User).where(User.email == normalized_email))).scalars().first()
    if user and user.status == UserStatus.INACTIVE:
        await enqueue_identity_email(db, user, "verification")
        await db.commit()
    # Deliberately generic to avoid account enumeration.
    return {"message": "If verification is required, an email request has been queued."}


@router.post("/email-verification/confirm")
async def confirm_email_verification(
    payload: EmailVerificationConfirm,
    db: AsyncSession = Depends(get_db),
):
    token = verify_token(payload.token, expected_type="email_verification")
    email = str(token.get("sub") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = (await db.execute(select(User).where(User.email == email))).scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if user.status == UserStatus.SUSPENDED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account unavailable")
    if user.status == UserStatus.LOCKED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account temporarily locked")

    activated = user.status == UserStatus.INACTIVE
    if activated:
        user.status = UserStatus.ACTIVE
        user.failed_login_attempts = 0
        user.account_locked_until = None
        await db.commit()
        await db.refresh(user)
        await asyncio.to_thread(send_welcome, user.email, _first_name(user))
        await emit_activation_event(db, "email_verified", user_id=user.id)

    return {"verified": True, "activated": activated}


@router.post("/login", response_model=LoginResponse)
async def login(
    login_data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    normalized_email = login_data.email.strip().lower()
    user = (await db.execute(select(User).where(User.email == normalized_email))).scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    now = datetime.utcnow()
    if user.status == UserStatus.SUSPENDED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account unavailable")
    if user.status == UserStatus.INACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Email verification required")
    if user.status == UserStatus.LOCKED:
        if user.account_locked_until and user.account_locked_until > now:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account temporarily locked")
        user.status = UserStatus.ACTIVE
        user.account_locked_until = None
        user.failed_login_attempts = 0

    if not verify_password(login_data.password, user.hashed_password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
            user.account_locked_until = now + timedelta(minutes=settings.ACCOUNT_LOCKOUT_DURATION_MINUTES)
            user.status = UserStatus.LOCKED
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Second factor. An account with MFA enabled gets no session from a password
    # alone; a wrong code counts as a failed attempt exactly like a wrong password.
    if user.mfa_enabled:
        if not login_data.mfa_code:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA code required")
        if not await verify_mfa_code(db, user, login_data.mfa_code.strip()):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
                user.account_locked_until = now + timedelta(minutes=settings.ACCOUNT_LOCKOUT_DURATION_MINUTES)
                user.status = UserStatus.LOCKED
            await db.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user.failed_login_attempts = 0
    user.account_locked_until = None
    user.last_login = now
    user.last_activity = now

    claims = await session_claims(db, user)
    access_token = create_access_token(claims)
    refresh_token = create_refresh_token(claims)
    ip_address, user_agent = _request_metadata(request)

    session = UserSession(
        user_id=user.id,
        session_token_hash=hash_token(access_token),
        refresh_token_hash=hash_token(refresh_token),
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(session)
    await db.commit()
    await db.refresh(user)
    response_user = _user_response(user)
    await _maybe_emit_second_session(db, user.id)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=response_user,
        _links={
            "refresh": {"href": "/api/v1/auth/refresh", "method": "POST"},
            "logout": {"href": "/api/v1/auth/logout", "method": "POST"},
            "workspace": {"href": "/api/v1/workspace", "method": "GET"},
        },
    )


async def _maybe_emit_second_session(db: AsyncSession, user_id: str) -> None:
    """second_session: the user's second password login (once-only)."""
    try:
        count = (
            await db.execute(select(func.count()).select_from(UserSession).where(UserSession.user_id == user_id))
        ).scalar_one()
    except Exception:
        return
    if count >= 2:
        await emit_activation_event(db, "second_session", user_id=user_id)


@router.post("/password-reset", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    payload: PasswordReset,
    db: AsyncSession = Depends(get_db),
):
    normalized_email = payload.email.strip().lower()
    user = (await db.execute(select(User).where(User.email == normalized_email))).scalars().first()
    if user and user.status != UserStatus.SUSPENDED:
        await enqueue_identity_email(db, user, "password_reset")
        await db.commit()
    return {"message": "If an eligible account exists, a reset email request has been queued."}


@router.post("/password-reset/confirm")
async def confirm_password_reset(
    payload: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db),
):
    token = verify_token(payload.token, expected_type="password_reset")
    email = str(token.get("sub") or "").strip().lower()
    credential_version = str(token.get("credential_version") or "")
    if not email or not credential_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = (await db.execute(select(User).where(User.email == email))).scalars().first()
    if not user or credential_version != _credential_version(user):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    if user.status == UserStatus.SUSPENDED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account unavailable")

    user.hashed_password = get_password_hash(payload.new_password)
    user.failed_login_attempts = 0
    user.account_locked_until = None
    if user.status == UserStatus.LOCKED:
        user.status = UserStatus.ACTIVE

    # Credential recovery is a security boundary: revoke every existing session.
    await db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id, UserSession.is_active == True)
        .values(is_active=False, last_accessed=datetime.utcnow())
    )
    await db.commit()
    return {"message": "Password reset complete. Please sign in again."}


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    payload = verify_token(credentials.credentials, expected_type="refresh")
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = (await db.execute(select(User).where(User.email == email))).scalars().first()
    if not user or user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is not active")

    now = datetime.utcnow()
    session_result = await db.execute(
        select(UserSession).where(
            UserSession.refresh_token_hash == hash_token(credentials.credentials),
            UserSession.user_id == user.id,
            UserSession.is_active == True,
            UserSession.expires_at > now,
        )
    )
    session = session_result.scalars().first()
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked or expired")

    claims = await session_claims(db, user)
    access_token = create_access_token(claims)
    refresh_token = create_refresh_token(claims)
    session.session_token_hash = hash_token(access_token)
    session.refresh_token_hash = hash_token(refresh_token)
    session.last_accessed = now
    session.expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    user.last_activity = now
    await db.commit()

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=_user_response(user),
        _links={
            "refresh": {"href": "/api/v1/auth/refresh", "method": "POST"},
            "logout": {"href": "/api/v1/auth/logout", "method": "POST"},
            "workspace": {"href": "/api/v1/workspace", "method": "GET"},
        },
    )


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
):
    session = await db.execute(
        select(UserSession).where(UserSession.session_token_hash == hash_token(credentials.credentials))
    )
    session_obj = session.scalar_one_or_none()
    if session_obj:
        session_obj.is_active = False
        session_obj.last_accessed = datetime.utcnow()
        await db.commit()
    return {"message": "Successfully logged out"}


async def resolve_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    return await get_current_user(credentials, db)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(resolve_current_user),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    payload = UserResponse.model_validate(current_user).model_dump(mode="json")
    token_payload = verify_token(credentials.credentials, expected_type="access")
    workspace_id = token_payload.get("workspace_id") or token_payload.get("tenant_id")
    if not workspace_id:
        legacy_workspace = token_payload.get("workspace")
        workspace_id = legacy_workspace if legacy_workspace and legacy_workspace != "default" else None
    payload["workspace_id"] = workspace_id
    payload["email_verified"] = _email_verified(current_user)
    payload["_links"] = {
        "self": {"href": "/api/v1/auth/me", "method": "GET"},
        "workspace": {"href": "/api/v1/workspace", "method": "GET"},
        "logout": {"href": "/api/v1/auth/logout", "method": "POST"},
    }
    return UserResponse(**payload)


@router.get("/me/agreements")
async def get_my_agreements(
    current_user: User = Depends(resolve_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The agreements this account accepted, and whether it has accepted every current one."""
    return await _agreements_view(db, current_user)


@router.post("/me/agreements")
async def accept_my_agreements(
    payload: AgreementAcceptRequest,
    request: Request,
    current_user: User = Depends(resolve_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record that this signed-in account accepts the current agreements, now.

    For GitHub signups (the boxes are ticked before leaving for GitHub) and for accounts with
    no record of accepting the current versions. Each row is stamped with this moment and its
    context; an account's missing history is never back-filled. Already-recorded versions are
    left as they are.
    """
    accepted = _require_all_current(payload.accepted_agreements)
    existing = {
        (r.document_type, r.document_version)
        for r in (
            await db.execute(select(AgreementAcceptance).where(AgreementAcceptance.user_id == current_user.id))
        ).scalars().all()
    }
    ip_address, user_agent = _request_metadata(request)
    for document_type in sorted(accepted):
        version = CURRENT_AGREEMENTS[document_type]
        if (document_type, version) in existing:
            continue
        db.add(AgreementAcceptance(
            user_id=current_user.id,
            document_type=document_type,
            document_version=version,
            source=payload.context,
            ip_address=ip_address,
            user_agent=user_agent,
        ))
    await db.commit()
    return await _agreements_view(db, current_user)


async def _agreements_view(db: AsyncSession, current_user: User) -> dict:
    rows = (
        await db.execute(
            select(AgreementAcceptance)
            .where(AgreementAcceptance.user_id == current_user.id)
            .order_by(AgreementAcceptance.accepted_at.asc(), AgreementAcceptance.document_type.asc())
        )
    ).scalars().all()
    accepted = {(r.document_type, r.document_version) for r in rows}
    return {
        "accepted": [
            {
                "document_type": r.document_type,
                "document_version": r.document_version,
                "source": r.source,
                "accepted_at": r.accepted_at.isoformat() + "Z",
            }
            for r in rows
        ],
        "current": [{"document_type": t, "document_version": v} for t, v in CURRENT_AGREEMENTS.items()],
        "all_current_accepted": all((t, v) in accepted for t, v in CURRENT_AGREEMENTS.items()),
    }

import os
import re

import httpx
from pydantic import BaseModel, Field


class GitHubExchangeRequest(BaseModel):
    github_access_token: str = Field(..., min_length=20, max_length=512)


_GITHUB_LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def _github_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10)


async def _github_login_for_app_token(access_token: str) -> str:
    """Return the GitHub login a token belongs to, as attested by GitHub itself.

    The token is checked against this deployment's own OAuth app (client id and
    secret), so a caller-supplied username, or a token issued to some other app,
    never yields a Veklom session.
    """
    client_id = os.environ.get("GITHUB_CLIENT_ID")
    client_secret = os.environ.get("GITHUB_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="GitHub sign-in is not configured")
    try:
        async with _github_http_client() as client:
            response = await client.post(
                f"https://api.github.com/applications/{client_id}/token",
                auth=(client_id, client_secret),
                headers={"Accept": "application/vnd.github+json"},
                json={"access_token": access_token},
            )
    except httpx.HTTPError:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="GitHub verification unavailable")
    if response.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="GitHub token was not issued to this application")
    login = ((response.json() or {}).get("user") or {}).get("login")
    if not isinstance(login, str) or not _GITHUB_LOGIN_RE.match(login):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="GitHub identity could not be verified")
    return login


@router.post("/github/exchange")
async def github_exchange(
    payload: GitHubExchangeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    github_username = await _github_login_for_app_token(payload.github_access_token)
    normalized_email = f"{github_username.lower()}@machine.veklom.com"
    user = (await db.execute(select(User).where(User.email == normalized_email))).scalars().first()
    if not user:
        user = User(
            email=normalized_email,
            username=github_username,
            full_name=github_username,
            hashed_password="github_oauth_no_password",
            role="user"
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)

    ip_address, user_agent = _request_metadata(request)
    now = datetime.utcnow()
    
    import uuid
    session_id = str(uuid.uuid4())
    
    access_token = create_access_token(
        data={**(await session_claims(db, user)), "session_id": session_id},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    refresh_token = create_refresh_token(
        data={**(await session_claims(db, user)), "session_id": session_id},
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    
    session = UserSession(
        id=session_id,
        user_id=user.id,
        session_token_hash=hash_token(access_token),
        refresh_token_hash=hash_token(refresh_token),
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    db.add(session)
    await db.commit()
    
    return {"access_token": access_token, "token_type": "bearer", "user": _user_response(user)}
