"""Offline integration test ONLY on dedicated database named outbox_test.

Run seed, restart dedicated Postgres, then run verify. No SMTP calls permitted.
"""
import asyncio
import sys
from datetime import datetime, timedelta
from sqlalchemy import select
from core.database.database import Base, engine, SessionLocal
from apps.email.outbox import IdentityEmailOutbox as Outbox, enqueue_identity_email
from apps.email.outbox_worker import process_one
from apps.email import sender
from db.models import User, UserStatus


async def main(phase):
    assert engine.url.database == 'outbox_test', 'Dedicated test DB required'
    if phase == 'seed':
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as db:
            assert not (await db.execute(select(User))).scalars().all()
            user = User(id='pg-outbox-user', email='offline@example.invalid',
                        username='offline', hashed_password='test-only', status=UserStatus.INACTIVE)
            db.add(user)
            await db.flush()
            await enqueue_identity_email(db, user, 'verification')
            await db.commit()
        print('PASS: inactive identity and intent persisted, no transport called')
    else:
        async with SessionLocal() as db:
            user = await db.get(User, 'pg-outbox-user')
            assert user.status == UserStatus.INACTIVE
            rows = (await db.execute(select(Outbox))).scalars().all()
            assert len(rows) == 1 and rows[0].status == 'QUEUED'
            original_id = rows[0].id
        async def resend():
            async with SessionLocal() as db:
                user = await db.get(User, 'pg-outbox-user')
                await enqueue_identity_email(db, user, 'verification')
                await db.commit()
        await asyncio.gather(*(resend() for _ in range(12)))
        async with SessionLocal() as db:
            rows = (await db.execute(select(Outbox))).scalars().all()
            assert len(rows) == 1 and rows[0].id == original_id
        calls = []
        def accept(*args):
            calls.append(True)
            return 'isolated-relay-acceptance'
        sender.send_verify_email = accept
        await asyncio.gather(*(process_one() for _ in range(12)))
        assert len(calls) == 1
        async with SessionLocal() as db:
            row = await db.get(Outbox, original_id)
            assert row.status == 'ACCEPTED' and row.attempts == 1
            # Durable pre-send claim simulates the crash window after claim commit.
            row.status = 'INDETERMINATE'
            row.outcome_code = 'ATTEMPT_STARTED'
            await db.commit()
        assert await process_one() is False
        assert len(calls) == 1
        print('PASS: restart persistence; 12 enqueuers/12 workers; one relay call; unknown claim not replayed')
    await engine.dispose()


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1]))
