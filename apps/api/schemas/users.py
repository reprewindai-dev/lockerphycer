"""
User Schemas
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum

from db.models import UserRole, UserStatus


class UserBase(BaseModel):
    """Base user schema"""
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)
    full_name: Optional[str] = None
    role: Optional[UserRole] = UserRole.USER


class UserCreate(UserBase):
    """User creation schema"""
    password: str = Field(..., min_length=8, max_length=128)


class UserUpdate(BaseModel):
    """User update schema"""
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[UserRole] = None
    status: Optional[UserStatus] = None


class UserResponse(UserBase):
    """User response schema"""
    id: str
    status: UserStatus
    mfa_enabled: bool
    failed_login_attempts: int
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_activity: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """User list response schema"""
    users: List[UserResponse]
    total: int
    skip: int
    limit: int


class UserStats(BaseModel):
    """User statistics schema"""
    total_users: int
    active_users: int
    inactive_users: int
    suspended_users: int
    locked_users: int
    new_users_today: int
    new_users_this_week: int
    new_users_this_month: int


class UserActivity(BaseModel):
    """User activity schema"""
    user_id: str
    username: str
    email: str
    last_login: Optional[datetime]
    last_activity: Optional[datetime]
    session_count: int
    failed_login_attempts: int
    is_online: bool
