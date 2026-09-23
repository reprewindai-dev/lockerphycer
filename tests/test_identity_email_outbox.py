"""Isolated database tests. No real mail transport, recipient or production DB."""
import asyncio
from datetime import datetime, timedelta
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from apps.email.outbox import IdentityEmailOutbox as Outbox, enqueue_identity_email
from apps.email.outbox_worker import process_one, validate_public_origin
from apps.email import sender
from core.database.database import Base
from core.config.settings import settings
from db.models import User, UserStatus


def test_durable_outbox_retry_and_ambiguity(tmp_path, monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'queue.db'))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as db:
            user = User(email='offline@example.invalid', username='offline',
                        hashed_password='not-a-password', status=UserStatus.INACTIVE)
            db.add(user)
            await db.flush()
            await enqueue_identity_email(db, user, 'verification')
            await db.commit()
            await enqueue_identity_email(db, user, 'verification')
            await db.commit()
            assert len((await db.execute(select(Outbox))).scalars().all()) == 1
        monkeypatch.setattr(sender, 'send_verify_email', lambda *args: None)
        monkeypatch.setattr(settings, 'EMAIL_TRANSPORT', 'disabled')
        assert await process_one(factory) is False
        async with factory() as db:
            held = (await db.execute(select(Outbox))).scalars().one()
            assert held.status == 'QUEUED' and held.attempts == 0
        monkeypatch.setattr(settings, 'EMAIL_TRANSPORT', 'smtp')
        await process_one(factory)
        async with factory() as db:
            row = (await db.execute(select(Outbox))).scalars().one()
            assert row.status == 'QUEUED' and row.attempts == 1
            row.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
            row.attempts = 4
            await db.commit()
        await process_one(factory)
        async with factory() as db:
            row = (await db.execute(select(Outbox))).scalars().one()
            assert row.status == 'FAILED' and row.attempts == 5
            row.status = 'QUEUED'
            row.next_attempt_at = datetime.utcnow() - timedelta(seconds=1)
            await db.commit()
        def ambiguous(*args):
            raise sender.DeliveryIndeterminate()
        monkeypatch.setattr(sender, 'send_verify_email', ambiguous)
        await process_one(factory)
        assert await process_one(factory) is False
        async with factory() as db:
            row = (await db.execute(select(Outbox))).scalars().one()
            assert row.status == 'INDETERMINATE'
            assert (await db.get(User, row.user_id)).status == UserStatus.INACTIVE
        await engine.dispose()
    asyncio.run(run())


def test_atomic_rollback_and_relay_acceptance(tmp_path, monkeypatch):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'atomic.db'))
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as db:
            user = User(email='offline@example.invalid', username='offline',
                        hashed_password='not-a-password', status=UserStatus.INACTIVE)
            db.add(user)
            await db.flush()
            await enqueue_identity_email(db, user, 'verification')
            await db.rollback()
            assert not (await db.execute(select(User))).scalars().all()
            assert not (await db.execute(select(Outbox))).scalars().all()
            db.add(user)
            await db.flush()
            await enqueue_identity_email(db, user, 'verification')
            await db.commit()
        monkeypatch.setattr(sender, 'send_verify_email', lambda *args: 'local-test-acceptance')
        await process_one(factory)
        async with factory() as db:
            row = (await db.execute(select(Outbox))).scalars().one()
            assert row.status == 'ACCEPTED'  # NOT DELIVERED or ACTIVE
            assert (await db.get(User, row.user_id)).status == UserStatus.INACTIVE
        await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize('origin', ['http://localhost:3000', 'https://localhost', 'https://127.0.0.1', 'https://0.0.0.0'])
def test_production_localhost_rejected(monkeypatch, origin):
    monkeypatch.setattr(settings, 'ENVIRONMENT', 'production')
    monkeypatch.setattr(settings, 'FRONTEND_URL', origin)
    with pytest.raises(ValueError):
        validate_public_origin()
