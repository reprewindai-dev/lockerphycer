"""Migration of BYOS accounts into Lockerphycer: real SQLAlchemy models, real bcrypt.

Source is a SQLite file shaped like the BYOS `users`/`workspaces` tables; target is a
SQLite file created from the Lockerphycer models. Asserts passwords survive verbatim
(verify_password succeeds), usernames are derived + unique, and re-running is a no-op.
"""

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-migration-tests")

import bcrypt
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.database.database import Base
from core.security.auth import verify_password
from db.models import User, UserRole, UserStatus, Workspace
from scripts.migrate_byos_users import derive_username, map_status, migrate

SOURCE_SCHEMA = """
CREATE TABLE workspaces (id TEXT PRIMARY KEY, name TEXT, slug TEXT, is_active INTEGER, created_at TEXT, updated_at TEXT);
CREATE TABLE users (
  id TEXT PRIMARY KEY, email TEXT, hashed_password TEXT, full_name TEXT, role TEXT, status TEXT,
  is_active INTEGER, workspace_id TEXT, mfa_enabled INTEGER, mfa_secret TEXT, failed_login_attempts INTEGER,
  account_locked_until TEXT, last_login TEXT, last_activity TEXT, created_at TEXT, updated_at TEXT
);
"""


def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode()


async def _seed_source(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        for stmt in SOURCE_SCHEMA.strip().split(";"):
            if stmt.strip():
                await conn.execute(text(stmt))
        await conn.execute(
            text(
                "INSERT INTO workspaces VALUES ('ws-1','Acme','acme',1,'2026-01-01T00:00:00','2026-01-02T00:00:00')"
            )
        )
        rows = [
            (
                "u-1",
                "Owner@Example.com",
                _hash("owner-pass-123"),
                "Owner One",
                "OWNER",
                "ACTIVE",
                1,
                "ws-1",
                0,
                None,
                0,
                None,
                "2026-02-01T00:00:00",
                None,
                "2026-01-01T00:00:00",
                None,
            ),
            (
                "u-2",
                "owner@other.io",
                _hash("second-pass-123"),
                "",
                "USER",
                "ACTIVE",
                1,
                "ws-1",
                0,
                None,
                2,
                None,
                None,
                None,
                "2026-01-03T00:00:00",
                None,
            ),
            (
                "u-3",
                "ab@short.io",
                "plaintext-legacy",
                None,
                "READONLY",
                "SUSPENDED",
                0,
                "ws-1",
                0,
                None,
                0,
                None,
                None,
                None,
                "2026-01-04T00:00:00",
                None,
            ),
        ]
        for r in rows:
            await conn.execute(
                text(
                    "INSERT INTO users VALUES ("
                    + ",".join(f":p{i}" for i in range(len(r)))
                    + ")"
                ),
                {f"p{i}": v for i, v in enumerate(r)},
            )
    await engine.dispose()


async def _init_target(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


def test_derive_username_sanitises_and_deduplicates():
    taken: set[str] = set()
    assert derive_username("John.Doe+x@example.com", taken) == "john.doe-x"
    assert derive_username("john.doe+x@other.com", taken) == "john.doe-x-2"
    assert derive_username("ab@x.io", taken) == "ab-user"
    assert derive_username("!!@x.io", taken) == "user"


def test_map_status_prefers_explicit_status():
    assert map_status("SUSPENDED", False) is UserStatus.SUSPENDED
    assert map_status(None, False) is UserStatus.INACTIVE
    assert map_status("bogus", True) is UserStatus.ACTIVE


@pytest.fixture
def db_urls(tmp_path):
    return (
        f"sqlite+aiosqlite:///{tmp_path}/byos.db",
        f"sqlite+aiosqlite:///{tmp_path}/lp.db",
    )


def test_dry_run_writes_nothing(db_urls):
    src, dst = db_urls
    asyncio.run(_seed_source(src))
    asyncio.run(_init_target(dst))

    report = asyncio.run(migrate(src, dst, apply=False))
    assert report.source_users == 3
    assert len(report.users_migrated) == 3

    async def count():
        engine = create_async_engine(dst)
        async with engine.connect() as conn:
            n = (await conn.execute(select(User))).scalars().all()
        await engine.dispose()
        return len(n)

    assert asyncio.run(count()) == 0


def test_apply_preserves_passwords_and_is_idempotent(db_urls):
    src, dst = db_urls
    asyncio.run(_seed_source(src))
    asyncio.run(_init_target(dst))

    report = asyncio.run(migrate(src, dst, apply=True))
    assert report.users_migrated == [
        "owner@example.com",
        "owner@other.io",
        "ab@short.io",
    ]
    assert report.users_non_bcrypt_hash == ["ab@short.io"]
    assert report.workspaces_migrated == ["ws-1"]
    assert report.username_assignments == {
        "owner@example.com": "owner",
        "owner@other.io": "owner-2",
        "ab@short.io": "ab-user",
    }

    async def load():
        engine = create_async_engine(dst)
        async with async_sessionmaker(
            engine, expire_on_commit=False, class_=AsyncSession
        )() as db:
            users = {
                u.email: u for u in (await db.execute(select(User))).scalars().all()
            }
            ws = (await db.execute(select(Workspace))).scalars().one()
        await engine.dispose()
        return users, ws

    users, ws = asyncio.run(load())
    owner = users["owner@example.com"]
    assert owner.id == "u-1"
    assert owner.role is UserRole.ADMIN
    assert owner.status is UserStatus.ACTIVE
    assert owner.full_name == "Owner One"
    assert verify_password("owner-pass-123", owner.hashed_password)
    assert not verify_password("wrong", owner.hashed_password)
    assert owner.last_login is not None

    second = users["owner@other.io"]
    assert second.role is UserRole.USER
    assert second.failed_login_attempts == 2
    assert second.full_name is None
    assert verify_password("second-pass-123", second.hashed_password)

    third = users["ab@short.io"]
    assert third.status is UserStatus.SUSPENDED

    assert ws.id == "ws-1" and ws.slug == "acme" and ws.owner_id == "owner@example.com"
    assert ws.settings["migrated_from"] == "byos"

    again = asyncio.run(migrate(src, dst, apply=True))
    assert again.users_migrated == []
    assert len(again.users_skipped_existing) == 3
    assert again.workspaces_skipped_existing == ["ws-1"]
