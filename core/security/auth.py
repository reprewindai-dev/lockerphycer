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
bearer = HTTPBearer(auto_error=True)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    expires = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = data.copy()
    payload.update({"exp": expires, "iat": datetime.utcnow(), "jti": str(uuid4()), "token_type": "access"})
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def create_refresh_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    expires = datetime.utcnow() + (expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))
    payload = data.copy()
    payload.update({"exp": expires, "iat": datetime.utcnow(), "jti": str(uuid4()), "token_type": "refresh"})
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def verify_token(token: str, expected_type: str | None = None) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        if expected_type and payload.get("token_type") != expected_type:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return payload
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    from db.models import User, UserSession, UserStatus

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
