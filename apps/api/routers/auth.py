"""Authentication Routes"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext

from apps.api.schemas.auth import LoginRequest, LoginResponse, RegisterRequest, UserResponse
from core.database.database import get_db
from core.security.auth import create_access_token, create_refresh_token, get_current_user, get_password_hash, verify_password, verify_token
from db.models import User, UserSession, UserRole, UserStatus

router = APIRouter()
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _user_response(user: User) -> UserResponse:
    payload = UserResponse.model_validate(user).model_dump(mode="json")
    payload["_links"] = {
        "self": {"href": "/api/v1/auth/me", "method": "GET"},
        "workspace": {"href": "/api/v1/workspace", "method": "GET"},
    }
    return UserResponse(**payload)


@router.post("/register", response_model=UserResponse)
async def register(user_data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    existing_user = (await db.execute(select(User).where(User.email == user_data.email))).scalars().first()
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(
        email=user_data.email,
        username=user_data.username,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        role=UserRole.USER,
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return _user_response(user)


@router.post("/login", response_model=LoginResponse)
async def login(login_data: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.email == login_data.email))).scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if user.status == UserStatus.LOCKED and user.account_locked_until and user.account_locked_until > datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account temporarily locked")

    if not verify_password(login_data.password, user.hashed_password):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= 10:
            user.account_locked_until = datetime.utcnow() + timedelta(minutes=30)
            user.status = UserStatus.LOCKED
        await db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user.failed_login_attempts = 0
    user.account_locked_until = None
    user.status = UserStatus.ACTIVE
    user.last_login = datetime.utcnow()
    user.last_activity = datetime.utcnow()

    access_token = create_access_token({"sub": user.email})
    refresh_token = create_refresh_token({"sub": user.email})

    session = UserSession(
        user_id=user.id,
        session_token=access_token,
        refresh_token=refresh_token,
        ip_address="127.0.0.1",
        user_agent="Locker Phycer Client",
        expires_at=datetime.utcnow() + timedelta(minutes=60),
    )
    db.add(session)
    await db.commit()
    await db.refresh(user)

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=3600,
        user=_user_response(user),
        _links={
            "refresh": {"href": "/api/v1/auth/refresh", "method": "POST"},
            "logout": {"href": "/api/v1/auth/logout", "method": "POST"},
            "workspace": {"href": "/api/v1/workspace", "method": "GET"},
        },
    )


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
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    session_result = await db.execute(
        select(UserSession).where(
            UserSession.refresh_token == credentials.credentials,
            UserSession.user_id == user.id,
            UserSession.is_active == True,
            UserSession.expires_at > datetime.utcnow(),
        )
    )
    session = session_result.scalars().first()
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked or expired")

    access_token = create_access_token({"sub": user.email})
    refresh_token = create_refresh_token({"sub": user.email})
    session.session_token = access_token
    session.refresh_token = refresh_token
    session.last_accessed = datetime.utcnow()
    user.last_activity = datetime.utcnow()
    await db.commit()

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=3600,
        user=_user_response(user),
        _links={
            "refresh": {"href": "/api/v1/auth/refresh", "method": "POST"},
            "logout": {"href": "/api/v1/auth/logout", "method": "POST"},
            "workspace": {"href": "/api/v1/workspace", "method": "GET"},
        },
    )


@router.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(security), db: AsyncSession = Depends(get_db)):
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
async def get_current_user_info(current_user: User = Depends(resolve_current_user)):
    payload = UserResponse.model_validate(current_user).model_dump(mode="json")
    payload["_links"] = {
        "self": {"href": "/api/v1/auth/me", "method": "GET"},
        "workspace": {"href": "/api/v1/workspace", "method": "GET"},
        "logout": {"href": "/api/v1/auth/logout", "method": "POST"},
    }
    return UserResponse(**payload)
