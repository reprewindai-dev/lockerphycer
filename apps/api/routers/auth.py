"""
Authentication Routes
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
from typing import Optional
import jwt
from passlib.context import CryptContext

from core.database.database import get_db
from db.models import User, UserSession, UserRole, UserStatus
from core.security.auth import create_access_token, verify_token, get_password_hash
from apps.api.schemas.auth import LoginRequest, LoginResponse, RegisterRequest, UserResponse

router = APIRouter()
security = HTTPBearer()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.post("/register", response_model=UserResponse)
async def register(
    user_data: RegisterRequest,
    db: AsyncSession = Depends(get_db)
):
    """Register a new user"""
    
    # Check if user already exists
    existing_user = (await db.execute(select(User).where(User.email == user_data.email))).scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Create new user
    user = User(
        email=user_data.email,
        username=user_data.username,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        role=UserRole.USER,
        status=UserStatus.ACTIVE
    )
    
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    response_data = UserResponse.from_orm(user).dict()
    response_data["_links"] = {
        "self": {"href": "/api/v1/auth/me", "method": "GET"},
        "login": {"href": "/api/v1/auth/login", "method": "POST"}
    }
    
    return UserResponse(**response_data)


@router.post("/login", response_model=LoginResponse)
async def login(
    login_data: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    """Authenticate user and return tokens"""
    
    # Find user by email
    user = (await db.execute(select(User).where(User.email == login_data.email))).scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    # Check password
    if not pwd_context.verify(login_data.password, user.hashed_password):
        # Increment failed login attempts
        user.failed_login_attempts += 1
        
        # Lock account if too many failed attempts
        if user.failed_login_attempts >= 10:
            user.account_locked_until = datetime.utcnow() + timedelta(minutes=30)
            user.status = UserStatus.LOCKED
        
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    # Check if account is locked
    if user.status == UserStatus.LOCKED and user.account_locked_until > datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account temporarily locked"
        )
    
    # Reset failed login attempts
    user.failed_login_attempts = 0
    user.last_login = datetime.utcnow()
    user.last_activity = datetime.utcnow()
    
    # Create session
    access_token = create_access_token(data={"sub": user.email})
    refresh_token = create_access_token(
        data={"sub": user.email}, 
        expires_delta=timedelta(days=7)
    )
    
    # Create session record
    session = UserSession(
        user_id=user.id,
        session_token=access_token,
        refresh_token=refresh_token,
        ip_address="127.0.0.1",  # Would get from request
        user_agent="Locker Phycer Client",  # Would get from request
        expires_at=datetime.utcnow() + timedelta(hours=1)
    )
    
    db.add(session)
    await db.commit()
    
    user_resp = UserResponse.from_orm(user).dict()
    user_resp["_links"] = {
        "self": {"href": "/api/v1/auth/me", "method": "GET"},
        "workspace": {"href": "/api/v1/workspace", "method": "GET"}
    }
    
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=3600,
        user=UserResponse(**user_resp),
        _links={
            "refresh": {"href": "/api/v1/auth/refresh", "method": "POST"},
            "logout": {"href": "/api/v1/auth/logout", "method": "POST"},
            "workspace": {"href": "/api/v1/workspace", "method": "GET"}
        }
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Refresh access token"""
    
    # Verify refresh token
    payload = verify_token(credentials.credentials)
    email = payload.get("sub")
    
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
    # Find user
    user = (await db.execute(select(User).where(User.email == email))).scalars().first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    # Create new tokens
    access_token = create_access_token(data={"sub": user.email})
    refresh_token = create_access_token(
        data={"sub": user.email}, 
        expires_delta=timedelta(days=7)
    )
    
    # Update session
    user.last_activity = datetime.utcnow()
    
    await db.commit()
    
    user_resp = UserResponse.from_orm(user).dict()
    user_resp["_links"] = {
        "self": {"href": "/api/v1/auth/me", "method": "GET"},
        "workspace": {"href": "/api/v1/workspace", "method": "GET"}
    }
    
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=3600,
        user=UserResponse(**user_resp),
        _links={
            "refresh": {"href": "/api/v1/auth/refresh", "method": "POST"},
            "logout": {"href": "/api/v1/auth/logout", "method": "POST"},
            "workspace": {"href": "/api/v1/workspace", "method": "GET"}
        }
    )


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
):
    """Logout user and invalidate session"""
    
    # Find and invalidate session
    session = await db.execute(
        select(UserSession).where(UserSession.session_token == credentials.credentials)
    )
    session_obj = session.scalar_one_or_none()
    
    if session_obj:
        session_obj.is_active = False
        await db.commit()
    
    return {"message": "Successfully logged out"}


async def resolve_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Get current authenticated user"""
    payload = verify_token(credentials.credentials)
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = (await db.execute(select(User).where(User.email == email))).scalars().first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.status != UserStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is not active")
    user.last_activity = datetime.utcnow()
    await db.commit()
    return user


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    current_user: User = Depends(resolve_current_user)
):
    """Get current user information"""
    user_resp = UserResponse.from_orm(current_user).dict()
    user_resp["_links"] = {
        "self": {"href": "/api/v1/auth/me", "method": "GET"},
        "workspace": {"href": "/api/v1/workspace", "method": "GET"},
        "logout": {"href": "/api/v1/auth/logout", "method": "POST"}
    }
    return UserResponse(**user_resp)
