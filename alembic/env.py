import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from sqlalchemy import inspect

from core.database.database import Base
# Import every module that defines tables so they are registered with Base.metadata
from db import models
from apps.email import outbox  # noqa: F401
from core.analytics import models as analytics_models  # noqa: F401
from core.security import mfa  # noqa: F401
import os
from core.config.settings import settings

target_metadata = Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def _normalize_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    return url

# Set the sqlalchemy.url dynamically
config.set_main_option("sqlalchemy.url", _normalize_url(settings.DATABASE_URL))

def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _create_base_schema_if_pristine(connection: Connection) -> None:
    """The migration chain starts after the original tables (users, workspaces, ...),
    which were only ever created by the app at startup. On a completely empty
    database the chain therefore failed ("relation workspaces does not exist"), so a
    fresh install could not run the schema step that compose runs before the app.
    Create the model tables first, exactly as the app would, then let every
    migration run as usual. A database that has any table is left untouched."""
    existing = inspect(connection).get_table_names()
    if existing:
        return
    target_metadata.create_all(connection)
    connection.commit()


def do_run_migrations(connection: Connection) -> None:
    _create_base_schema_if_pristine(connection)
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
