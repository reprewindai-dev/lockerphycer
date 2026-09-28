"""Add only the outbox table; explicitly run before deploying the new API.

python -m scripts.create_identity_email_outbox
No user alterations, resets, credentials or transport calls.
"""
import asyncio
from apps.email.outbox import IdentityEmailOutbox
from core.database.database import engine


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: IdentityEmailOutbox.__table__.create(sync, checkfirst=True))
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
