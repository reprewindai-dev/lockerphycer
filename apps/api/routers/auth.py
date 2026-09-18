"""Authentication routes."""

import asyncio
import hashlib
from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.schemas.auth import (
    EmailVerificationConfirm,
    EmailVerificationRequest,
    LoginRequest,
    LoginResponse,
    PasswordReset,
    PasswordResetConfirm,
    RegisterRequest,
    UserResponse,
)
from apps.email.sender import send_password_reset, send_verify_email, send_welcome
from core.config.settings import settings
from core.database.database import get_db
from core.security.auth import (
    create_access_token,
    create_email_verification_token,
    create_password_reset_token,
    create_refresh_token,
    get_current_user,
    get_password_hash,
    verify_password,
    verify_token,
)
from db.models import User, UserSession, UserRole, UserStatus

router = APIRouter()
security = HTTPBearer()


def _user_response(user: User) -> UserResponse:
    payload = UserResponse.model_validate(user).model_dump(mode="json")
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
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip_address = forwarded_for or (request.client.host if request.client else None)
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


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: RegisterRequest, db: AsyncSession = Depends(get_db)):
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

    delivered = await _send_verification(user)
    if not delivered:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification delivery unavailable; registration was not created",
        )

    await db.commit()
    await db.refresh(user)
    return _user_response(user)


@router.post("/email-verification/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_verification(
    payload: EmailVerificationRequest,
    db: AsyncSession = Depends(get_db),
):
    normalized_email = payload.email.strip().lower()
    user = (await db.execute(select(User).where(User.email == normalized_email))).scalars().first()
    if user and user.status == UserStatus.INACTIVE:
        await _send_verification(user)
    # Deliberately generic to avoid account enumeration.
    return {"message": "If verification is required, a new email has been sent."}


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

    user.failed_login_attempts = 0
    user.account_locked_until = None
    user.last_login = now
    user.last_activity = now

    access_token = create_access_token({"sub": user.email})
    refresh_token = create_refresh_token({"sub": user.email})
    ip_address, user_agent = _request_metadata(request)

    session = UserSession(
        user_id=user.id,
        session_token=access_token,
        refresh_token=refresh_token,
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )
    db.add(session)
    await db.commit()
    await db.refresh(user)

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


@router.post("/password-reset", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    payload: PasswordReset,
    db: AsyncSession = Depends(get_db),
):
    normalized_email = payload.email.strip().lower()
    user = (await db.execute(select(User).where(User.email == normalized_email))).scalars().first()
    if user and user.status != UserStatus.SUSPENDED:
        await _send_reset(user)
    return {"message": "If an account exists for that email, a reset link has been sent."}


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
            UserSession.refresh_token == credentials.credentials,
            UserSession.user_id == user.id,
            UserSession.is_active == True,
            UserSession.expires_at > now,
        )
    )
    session = session_result.scalars().first()
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked or expired")

    access_token = create_access_token({"sub": user.email})
    refresh_token = create_refresh_token({"sub": user.email})
    session.session_token = access_token
    session.refresh_token = refresh_token
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
    session = await db.execute(select(UserSession).where(UserSession.session_token == credentials.credentials))
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
    payload["_links"] = {
        "self": {"href": "/api/v1/auth/me", "method": "GET"},
        "workspace": {"href": "/api/v1/workspace", "method": "GET"},
        "logout": {"href": "/api/v1/auth/logout", "method": "POST"},
    }
    return UserResponse(**payload)

from pydantic import BaseModel
class GitHubExchangeRequest(BaseModel):
    github_username: str

@router.post("/github/exchange")
async def github_exchange(
    payload: GitHubExchangeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    normalized_email = f"{payload.github_username}@machine.veklom.com"
    user = (await db.execute(select(User).where(User.email == normalized_email))).scalars().first()
    if not user:
        user = User(
            email=normalized_email,
            username=payload.github_username,
            full_name=payload.github_username,
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
        data={"sub": user.email, "session_id": session_id},
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    refresh_token = create_refresh_token(
        data={"sub": user.email, "session_id": session_id},
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    
    session = UserSession(
        id=session_id,
        user_id=user.id,
        session_token=access_token,
        refresh_token=refresh_token,
        ip_address=ip_address,
        user_agent=user_agent,
        expires_at=now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    db.add(session)
    await db.commit()
    
    return {"access_token": access_token, "token_type": "bearer", "user": _user_response(user)}
