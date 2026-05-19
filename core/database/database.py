"""
Database Configuration and Connection Management
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import create_engine, MetaData
from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator

from core.config.settings import settings


class Base(DeclarativeBase):
    """Base class for all database models"""
    pass


# Build engine kwargs based on database type
_is_sqlite = settings.DATABASE_URL.startswith("sqlite")
_engine_kwargs: dict = {"echo": settings.DEBUG, "future": True}
if not _is_sqlite:
    _engine_kwargs.update(pool_size=20, max_overflow=30, pool_timeout=30, pool_recycle=3600)

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

_sync_url = settings.DATABASE_URL
if "asyncpg" in _sync_url:
    _sync_url = _sync_url.replace("postgresql+asyncpg://", "postgresql://")
elif "aiosqlite" in _sync_url:
    _sync_url = _sync_url.replace("sqlite+aiosqlite://", "sqlite://")

sync_engine = create_engine(_sync_url, echo=settings.DEBUG)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_db_status() -> dict:
    """Check database connection status"""
    try:
        from sqlalchemy import text
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "message": "Database connection successful"
        }
    except Exception as e:
        logging.error(f"Database health check failed: {e}")
        return {
            "status": "unhealthy",
            "message": str(e)
        }


@asynccontextmanager
async def get_transaction() -> AsyncGenerator[AsyncSession, None]:
    """Get database session with transaction"""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


# Metadata for migrations
metadata = MetaData()


def init_db():
    """Initialize database tables"""
    Base.metadata.create_all(bind=sync_engine)


def drop_db():
    """Drop all database tables"""
    Base.metadata.drop_all(bind=sync_engine)
