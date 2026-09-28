"""Isolated real-HTTP/PostgreSQL test; requires an externally network-isolated API.

No worker is started and no mail is sent. Never run against production.
Run seed, restart the dedicated API and PostgreSQL containers, then verify.
"""
import asyncio
import json
import sys
import urllib.error
import urllib.request

from sqlalchemy import select
from core.database.database import engine, SessionLocal
from apps.email.outbox import IdentityEmailOutbox
from db.models import User, UserStatus

EMAIL = "reprewindai@gmail.com"
PASSWORD = "Isolated-HTTP-Test-Only-Not-Production!"


def post(path, payload):
    request = urllib.request.Request(
        "http://127.0.0.1:18092/api/v1/auth/" + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Origin": "https://veklom.com"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


async def inspect():
    async with SessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == EMAIL))).scalars().one()
        assert user.status == UserStatus.INACTIVE
        row = (await db.execute(select(IdentityEmailOutbox).where(
            IdentityEmailOutbox.user_id == user.id))).scalars().one()
        assert row.status == "QUEUED" and row.attempts == 0
        result = {"user_id": user.id, "outbox_id": row.id,
                  "identity": "INACTIVE", "delivery": "QUEUED", "attempts": row.attempts}
    await engine.dispose()
    return result


if __name__ == "__main__":
    assert engine.url.database == "outbox_test", "Dedicated database required"
    assert engine.url.host in ("127.0.0.1", "localhost"), "Isolated loopback DB required"
    if sys.argv[1] == "seed":
        assert post("register", {"email": EMAIL, "username": "http-outbox-controlled",
                                 "full_name": "Isolated Acceptance", "password": PASSWORD}) == 201
    else:
        assert sys.argv[1] == "verify"
    assert post("login", {"email": EMAIL, "password": PASSWORD}) == 403
    result = asyncio.run(inspect())
    if sys.argv[1] == "verify":
        assert result["user_id"] == sys.argv[2]
        assert result["outbox_id"] == sys.argv[3]
    print(json.dumps({"phase": sys.argv[1], "result": "PASS", **result}))
