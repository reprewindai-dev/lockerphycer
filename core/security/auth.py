"""Authentication, authorization, and password utilities."""

from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config.settings import settings
from core.database.database import get_db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer = HTTPBearer(auto_error=False)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _create_token(data: dict, token_type: str, expires_delta: timedelta) -> str:
    now = datetime.utcnow()
    payload = data.copy()
    # Workspace identity is a security boundary consumed by CAPPO. Preserve an
    # explicitly resolved workspace claim supplied by LockerPhycer callers;
    # only fall back to the legacy "default" claim when no workspace identity
    # has been resolved yet (for example before first-time onboarding).
    if not any(payload.get(key) for key in ("workspace_id", "workspace", "tenant_id")):
        payload["workspace"] = "default"
    payload.update(
        {
            "exp": now + expires_delta,
            "iat": now,
            "jti": str(uuid4()),
            "token_type": token_type,
            "iss": "veklom-lockerphycer",
            "aud": "veklom-cappo",
        }
    )
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return _create_token(
        data,
        "access",
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    return _create_token(
        data,
        "refresh",
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def create_email_verification_token(email: str) -> str:
    return _create_token(
        {"sub": email},
        "email_verification",
        timedelta(minutes=settings.EMAIL_VERIFICATION_EXPIRE_MINUTES),
    )


def create_password_reset_token(email: str, credential_version: str) -> str:
    """Create a reset token bound to the current password hash version.

    The credential-version binding makes a successful reset invalidate every
    outstanding reset token for the previous password without storing reset
    tokens in plaintext.
    """
    return _create_token(
        {"sub": email, "credential_version": credential_version},
        "password_reset",
        timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
    )


def verify_token(token: str, expected_type: str | None = None) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"], audience="veklom-cappo")
        if expected_type and payload.get("token_type") != expected_type:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return payload
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    from db.models import User, UserSession, UserStatus

    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = verify_token(credentials.credentials, expected_type="access")
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is not active")
    session_result = await db.execute(
        select(UserSession).where(
            UserSession.session_token == credentials.credentials,
            UserSession.user_id == user.id,
            UserSession.is_active == True,
            UserSession.expires_at > datetime.utcnow(),
        )
    )
    session = session_result.scalars().first()
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked or expired")
    user.last_activity = datetime.utcnow()
    session.last_accessed = datetime.utcnow()
    await db.commit()
    return user


async def require_admin(current_user=Depends(get_current_user)) -> str:
    role = current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role)
    if role != "admin" and current_user.email != settings.ADMIN_EMAIL:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user.email


def sanitize_input(input_string: str) -> str:
    """Sanitize user input to prevent XSS/Injection patterns."""
    dangerous_chars = "<>\"'&"
    for char in dangerous_chars:
        input_string = input_string.replace(char, "")
    return input_string.strip()


def is_safe_url(url: str) -> bool:
    """Check if URL is safe (prevents protocols like javascript: / data: / vbscript: / file:)."""
    dangerous_schemes = ["javascript:", "data:", "vbscript:", "file:"]
    lower = url.lower().strip()
    return not any(lower.startswith(s) for s in dangerous_schemes)


def generate_csrf_token() -> str:
    """Generate a secure CSRF token."""
    import secrets
    return secrets.token_urlsafe(32)


def verify_csrf_token(token: str, expected_token: str) -> bool:
    """Verify a CSRF token using secure hmac comparison."""
    import hmac
    return hmac.compare_digest(token, expected_token)
