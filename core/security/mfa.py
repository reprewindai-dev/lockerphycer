"""
core/security/mfa.py

TOTP-based MFA, built to slot directly into lockerphycer's existing schema —
User.mfa_enabled and User.mfa_secret already exist in db/models, unused
until now. This closes one real gap between the README's claims and the
actual code, without inventing a new schema.

Flow:
  1. setup_mfa(user)      -> generates a secret + provisioning URI + QR
                             code, stores the secret but does NOT flip
                             mfa_enabled yet (matches standard practice:
                             don't enable until the user proves they can
                             generate a valid code)
  2. confirm_mfa_setup()  -> verifies the user's first real TOTP code,
                             flips mfa_enabled=True, issues backup codes
  3. verify_mfa_code()    -> used at login step 2; accepts either a live
                             TOTP code or a single-use backup code
  4. disable_mfa()        -> requires a valid code to turn off, not just
                             a button click

Backup codes are hashed with the same bcrypt context already used for
passwords in core/security/auth.py — no new crypto primitive introduced.
"""

import io
import secrets
from typing import Optional

import pyotp
import qrcode
from sqlalchemy import Column, String, Boolean, DateTime, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from core.security.auth import pwd_context  # reuse the existing bcrypt context, don't fork a second one
from db.models import Base, User


class MFABackupCode(Base):
    """One row per backup code. Hashed, single-use, tied to a user."""
    __tablename__ = "mfa_backup_codes"

    id = Column(String, primary_key=True, default=lambda: secrets.token_hex(16))
    user_id = Column(String, nullable=False, index=True)
    code_hash = Column(String, nullable=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    used_at = Column(DateTime(timezone=True), nullable=True)


ISSUER_NAME = "Locker Phycer"
BACKUP_CODE_COUNT = 10


def _generate_backup_codes() -> list[str]:
    """Human-typeable codes: 8 hex chars, grouped for readability (e.g. a1b2-c3d4)."""
    codes = []
    for _ in range(BACKUP_CODE_COUNT):
        raw = secrets.token_hex(4)
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes


def setup_mfa(user_email: str) -> dict:
    """
    Step 1: generate a new secret + QR code. Does NOT persist or enable
    anything by itself — caller stores the secret against the user record
    but leaves mfa_enabled False until confirm_mfa_setup succeeds.
    """
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user_email, issuer_name=ISSUER_NAME)

    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    return {
        "secret": secret,  # show once, at setup time only — never re-display after this
        "provisioning_uri": provisioning_uri,
        "qr_code_png_bytes": buf.getvalue(),
    }


def verify_totp_code(secret: str, code: str) -> bool:
    """Real TOTP verification with a 1-step (30s) window either side for clock drift."""
    if not secret or not code:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


async def confirm_mfa_setup(
    db: AsyncSession, user: User, secret: str, code: str
) -> Optional[list[str]]:
    """
    Step 2: verify the user actually has a working authenticator app before
    turning MFA on. Returns the plaintext backup codes ONCE (caller must
    show them to the user immediately — only the hashes are stored) or
    None if the code didn't verify.
    """
    if not verify_totp_code(secret, code):
        return None

    user.mfa_secret = secret
    user.mfa_enabled = True

    plaintext_codes = _generate_backup_codes()
    for code_str in plaintext_codes:
        db.add(MFABackupCode(user_id=user.id, code_hash=pwd_context.hash(code_str)))

    await db.commit()
    return plaintext_codes


async def verify_mfa_code(db: AsyncSession, user: User, code: str) -> bool:
    """
    Step 2 of login: accepts a live TOTP code OR a single-use backup code.
    Backup codes are consumed on success — never valid twice.
    """
    if not user.mfa_enabled or not user.mfa_secret:
        return False

    if verify_totp_code(user.mfa_secret, code):
        return True

    # Not a valid TOTP code — check unused backup codes
    result = await db.execute(
        select(MFABackupCode).where(
            MFABackupCode.user_id == user.id, MFABackupCode.used == False  # noqa: E712
        )
    )
    for backup in result.scalars().all():
        if pwd_context.verify(code, backup.code_hash):
            backup.used = True
            backup.used_at = func.now()
            await db.commit()
            return True

    return False


async def disable_mfa(db: AsyncSession, user: User, code: str) -> bool:
    """Requires a valid current code to disable — prevents a hijacked session from silently turning MFA off."""
    if not await verify_mfa_code(db, user, code):
        return False
    user.mfa_enabled = False
    user.mfa_secret = None
    result = await db.execute(select(MFABackupCode).where(MFABackupCode.user_id == user.id))
    for backup in result.scalars().all():
        await db.delete(backup)
    await db.commit()
    return True
