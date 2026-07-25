"""
Real end-to-end test: actual SQLAlchemy models copied from the real repo
(db/models, core/database, core/security/auth.py), an in-memory SQLite DB,
and genuine TOTP codes generated the same way an authenticator app would.
No mocks on the code paths that matter — pyotp really validates against
real time-based codes, bcrypt really hashes and verifies backup codes.
"""
import asyncio
import pyotp

import os
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from core.database.database import Base
from db.models import User, UserRole, UserStatus
from core.security.mfa import (
    setup_mfa,
    confirm_mfa_setup,
    verify_mfa_code,
    disable_mfa,
    verify_totp_code,
    MFABackupCode,
)

failures = 0
def check(label, cond):
    global failures
    print(("PASS" if cond else "FAIL") + " — " + label)
    if not cond:
        failures += 1


async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as db:
        user = User(
            id="test-user-1",
            email="anthony@veklom.com",
            username="anthony",
            hashed_password="irrelevant-for-this-test",
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        db.add(user)
        await db.commit()

        # --- Step 1: setup generates a real secret + scannable QR ---
        setup = setup_mfa(user.email)
        check("setup_mfa returns a base32 secret", len(setup["secret"]) >= 16)
        check("setup_mfa returns a real otpauth:// provisioning URI", setup["provisioning_uri"].startswith("otpauth://totp/"))
        check("setup_mfa returns real PNG bytes for the QR code", setup["qr_code_png_bytes"][:8] == b"\x89PNG\r\n\x1a\n")
        check("mfa_enabled is still False until confirmed", user.mfa_enabled is False)

        # --- Step 2: confirming with a WRONG code must not enable MFA ---
        wrong_result = await confirm_mfa_setup(db, user, setup["secret"], "000000")
        check("confirm_mfa_setup rejects a wrong code", wrong_result is None)
        check("mfa_enabled still False after a failed confirm", user.mfa_enabled is False)

        # --- Step 3: confirming with the REAL current TOTP code enables MFA ---
        real_code = pyotp.TOTP(setup["secret"]).now()
        backup_codes = await confirm_mfa_setup(db, user, setup["secret"], real_code)
        check("confirm_mfa_setup accepts a real current code", backup_codes is not None)
        check("mfa_enabled is True after a successful confirm", user.mfa_enabled is True)
        check("exactly 10 backup codes were issued", backup_codes is not None and len(backup_codes) == 10)

        # --- Step 4: login-time verification with a live TOTP code ---
        login_code = pyotp.TOTP(user.mfa_secret).now()
        check("verify_mfa_code accepts a live TOTP code at login", await verify_mfa_code(db, user, login_code))
        check("verify_mfa_code rejects a garbage code", not await verify_mfa_code(db, user, "111111"))

        # --- Step 5: backup codes work once, then are burned ---
        one_backup = backup_codes[0]
        check("a real backup code works the first time", await verify_mfa_code(db, user, one_backup))
        check("the SAME backup code fails the second time (single-use)", not await verify_mfa_code(db, user, one_backup))
        # a different, still-unused backup code should still work
        check("a different unused backup code still works", await verify_mfa_code(db, user, backup_codes[1]))

        # --- Step 6: disabling requires a valid code, not just a flag flip ---
        disable_fail = await disable_mfa(db, user, "999999")
        check("disable_mfa refuses without a valid code", disable_fail is False)
        check("mfa_enabled still True after a failed disable attempt", user.mfa_enabled is True)

        final_code = pyotp.TOTP(user.mfa_secret).now()
        disable_ok = await disable_mfa(db, user, final_code)
        check("disable_mfa succeeds with a valid code", disable_ok is True)
        check("mfa_enabled is False after disabling", user.mfa_enabled is False)
        check("mfa_secret is cleared after disabling", user.mfa_secret is None)

    print(f"\n{failures} FAILURE(S)" if failures else "\nALL PASS")
    return failures


if __name__ == "__main__":
    result = asyncio.run(main())
    exit(1 if result else 0)
