"""Standalone worker. No automatic startup in API processes or production tests."""
import asyncio
import hashlib
from datetime import datetime, timedelta
from urllib.parse import quote, urlparse
import ipaddress

from sqlalchemy import select, update

from apps.email.outbox import IdentityEmailOutbox as Outbox
from apps.email import sender
from core.config.settings import settings
from core.database.database import SessionLocal
from core.security.auth import create_email_verification_token, create_password_reset_token
from db.models import User, UserStatus


def validate_public_origin():
    if settings.ENVIRONMENT != "production":
        return
    origin = urlparse(settings.FRONTEND_URL)
    host = (origin.hostname or "").lower().rstrip(".")
    invalid = origin.scheme != "https" or not host or origin.username or origin.password
    invalid = invalid or host == "localhost" or host.endswith((".localhost", ".local"))
    try:
        invalid = invalid or not ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    if invalid:
        raise ValueError("Production email requires a public HTTPS frontend origin")


async def process_one(session_factory=SessionLocal):
    now = datetime.utcnow()
    async with session_factory() as db:
        row = (await db.execute(select(Outbox).where(
            Outbox.status == "QUEUED", Outbox.next_attempt_at <= now,
        ).order_by(Outbox.created_at).limit(1))).scalars().first()
        if row is None:
            return False
        row_id = row.id
        # Compare-and-swap claim works even when multiple workers select the same row.
        claimed = await db.execute(update(Outbox).where(
            Outbox.id == row_id, Outbox.status == "QUEUED",
        ).values(status="INDETERMINATE", attempts=Outbox.attempts + 1,
                 outcome_code="ATTEMPT_STARTED", updated_at=now))
        await db.commit()
        if claimed.rowcount != 1:
            return True
        await db.refresh(row)
        user = await db.get(User, row.user_id)
        eligible = user and user.status not in (UserStatus.SUSPENDED, UserStatus.LOCKED)
        if row.kind == "verification":
            eligible = eligible and user.status == UserStatus.INACTIVE
        elif row.kind == "password_reset":
            eligible = eligible and row.credential_version == hashlib.sha256(
                user.hashed_password.encode()).hexdigest()
        else:
            eligible = False
        if not eligible or row.expires_at <= now:
            row.status, row.outcome_code = "FAILED", "EXPIRED_OR_INELIGIBLE"
        else:
            name = (user.full_name or user.username or "there").split()[0]
            # Tokens are minted at dispatch, not before a potentially long outage.
            if row.kind == "verification":
                token = create_email_verification_token(user.email)
                path, send = "verify-email", sender.send_verify_email
            else:
                token = create_password_reset_token(user.email, row.credential_version)
                path, send = "reset-password", sender.send_password_reset
            url = f"{settings.FRONTEND_URL.rstrip('/')}/{path}?token={quote(token)}"
            try:
                validate_public_origin()
                correlation = await asyncio.to_thread(send, user.email, name, url)
                if correlation:
                    row.status, row.outcome_code = "ACCEPTED", "RELAY_ACCEPTED"
                    row.correlation_id = correlation[:255]
                elif row.attempts >= 5:
                    row.status, row.outcome_code = "FAILED", "RETRY_LIMIT"
                else:
                    row.status, row.outcome_code = "QUEUED", "TRANSPORT_UNAVAILABLE"
                    row.next_attempt_at = now + timedelta(seconds=min(3600, 60 * 2 ** row.attempts))
            except Exception:
                # No exception details: SMTP errors can contain recipient/token data.
                row.status, row.outcome_code = "INDETERMINATE", "OUTCOME_UNKNOWN"
        row.updated_at = datetime.utcnow()
        await db.commit()
    return True


async def main():
    while True:
        try:
            worked = await process_one()
        except Exception:
            # DB outages must not terminate the supervisor's worker loop or leak secrets.
            worked = False
        await asyncio.sleep(1 if worked else 10)


if __name__ == "__main__":
    asyncio.run(main())
