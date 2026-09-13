import asyncio
from core.database.database import get_db_status, engine, Base
from db.models import User

async def main():
    print(await get_db_status())
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created")

asyncio.run(main())
