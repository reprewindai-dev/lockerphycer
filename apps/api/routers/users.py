"""
User Management Routes
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from typing import List, Optional
from datetime import datetime, timedelta

from core.database.database import get_db
from db.models import User, UserSession, UserRole, UserStatus
from core.security.auth import get_current_user
from apps.api.schemas.users import UserResponse, UserCreate, UserUpdate, UserListResponse

router = APIRouter()


@router.get("/", response_model=UserListResponse)
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    role: Optional[UserRole] = None,
    status: Optional[UserStatus] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List users with filtering and pagination"""
    
    # Build query
    query = select(User)
    
    # Apply filters
    conditions = []
    
    if role:
        conditions.append(User.role == role)
    
    if status:
        conditions.append(User.status == status)
    
    if search:
        search_pattern = f"%{search}%"
        conditions.append(
            or_(
                User.email.ilike(search_pattern),
                User.username.ilike(search_pattern),
                User.full_name.ilike(search_pattern)
            )
        )
    
    if conditions:
        query = query.where(and_(*conditions))
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # Apply pagination
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    users = result.scalars().all()
    
    return UserListResponse(
        users=[UserResponse.from_orm(user) for user in users],
        total=total,
        skip=skip,
        limit=limit
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user by ID"""
    
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserResponse.from_orm(user)


@router.post("/", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create new user"""
    
    # Check if user already exists
    existing_user = await db.execute(
        select(User).where(
            or_(User.email == user_data.email, User.username == user_data.username)
        )
    )
    if existing_user.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email or username already exists"
        )
    
    # Create new user
    from core.security.auth import get_password_hash
    
    user = User(
        email=user_data.email,
        username=user_data.username,
        hashed_password=get_password_hash(user_data.password),
        full_name=user_data.full_name,
        role=user_data.role or UserRole.USER,
        status=UserStatus.ACTIVE
    )
    
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    return UserResponse.from_orm(user)


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update user"""
    
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Check permissions (users can only update themselves, admins can update anyone)
    if current_user.role != UserRole.ADMIN and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    # Update fields
    update_data = user_data.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)
    
    user.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(user)
    
    return UserResponse.from_orm(user)


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete user (soft delete)"""
    
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Check permissions
    if current_user.role != UserRole.ADMIN and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    # Soft delete
    user.status = UserStatus.INACTIVE
    user.updated_at = datetime.utcnow()
    await db.commit()
    
    return {"message": "User deleted successfully"}


@router.post("/{user_id}/activate")
async def activate_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Activate user account"""
    
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Check permissions
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    user.status = UserStatus.ACTIVE
    user.updated_at = datetime.utcnow()
    await db.commit()
    
    return {"message": "User activated successfully"}


@router.post("/{user_id}/deactivate")
async def deactivate_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Deactivate user account"""
    
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Check permissions
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    user.status = UserStatus.INACTIVE
    user.updated_at = datetime.utcnow()
    await db.commit()
    
    return {"message": "User deactivated successfully"}


@router.get("/{user_id}/sessions")
async def get_user_sessions(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user sessions"""
    
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Check permissions
    if current_user.role != UserRole.ADMIN and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    # Get active sessions
    result = await db.execute(
        select(UserSession).where(
            and_(
                UserSession.user_id == user_id,
                UserSession.is_active == True,
                UserSession.expires_at > datetime.utcnow()
            )
        )
    )
    sessions = result.scalars().all()
    
    return {
        "sessions": [
            {
                "id": session.id,
                "ip_address": session.ip_address,
                "user_agent": session.user_agent,
                "created_at": session.created_at,
                "expires_at": session.expires_at,
                "last_accessed": session.last_accessed
            }
            for session in sessions
        ]
    }


@router.delete("/{user_id}/sessions/{session_id}")
async def revoke_session(
    user_id: str,
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Revoke user session"""
    
    session = await db.get(UserSession, session_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    
    # Check permissions
    if current_user.role != UserRole.ADMIN and current_user.id != session.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    
    session.is_active = False
    await db.commit()
    
    return {"message": "Session revoked successfully"}
