"""Durable identity-email intents; no tokens, passwords, or rendered links at rest.

Run the worker separately: python -m apps.email.outbox_worker.
An attempt is fenced as INDETERMINATE before transport I/O. A crash never
causes automatic duplicate delivery. SMTP acceptance is NOT inbox delivery.
"""
import hashlib
from datetime import datetime, timedelta

from sqlalchemy import DateTime, ForeignKey, Integer, String, select
from sqlalchemy.orm import Mapped, mapped_column

from core.database.database import Base
from db.models import User, new_id


class IdentityEmailOutbox(Base):
    __tablename__ = "identity_email_outbox"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    credential_version: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default="QUEUED", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    correlation_id: Mapped[str | None] = mapped_column(String(255))
    outcome_code: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def enqueue_identity_email(db, user, kind):
    if kind not in ("verification", "password_reset"):
        raise ValueError("Unsupported identity email kind")
    # Serialize enqueue for this identity on PostgreSQL, including concurrent resend.
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = datetime.utcnow()
    existing = (await db.execute(select(IdentityEmailOutbox).where(
        IdentityEmailOutbox.user_id == user.id,
        IdentityEmailOutbox.kind == kind,
        IdentityEmailOutbox.expires_at > now,
        IdentityEmailOutbox.status.in_(("QUEUED", "INDETERMINATE")),
    ))).scalars().first()
    if existing:
        return existing
    # A cooldown also covers already accepted messages. No delivery claim is made.
    recent = (await db.execute(select(IdentityEmailOutbox).where(
        IdentityEmailOutbox.user_id == user.id,
        IdentityEmailOutbox.kind == kind,
        IdentityEmailOutbox.created_at > now - timedelta(minutes=1),
    ))).scalars().first()
    if recent:
        return recent
    row = IdentityEmailOutbox(
        user_id=user.id, kind=kind, expires_at=now + timedelta(hours=24),
        credential_version=(hashlib.sha256(user.hashed_password.encode()).hexdigest()
                            if kind == "password_reset" else None),
    )
    db.add(row)
    return row
