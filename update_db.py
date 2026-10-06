import asyncio
import sys
import os

# Append project root to sys.path
sys.path.append(r'C:\Users\antho\Documents\Codex\2026-09-16\w\work\veklom-m1p2\lockerphycer')

from core.database.database import engine
from db.models import Base

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Database updated!")

if __name__ == '__main__':
    asyncio.run(init_db())
