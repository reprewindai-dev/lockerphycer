"""Async SQLAlchemy database bootstrap."""

from collections.abc import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from core.config.settings import settings


class Base(DeclarativeBase):
    pass


def _normalize_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return url


engine = create_async_engine(_normalize_url(settings.DATABASE_URL), pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def get_db_status() -> dict:
    try:
        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "healthy"}
    except Exception:
        return {"status": "unhealthy"}
