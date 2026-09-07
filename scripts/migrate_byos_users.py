"""One-time migration of accounts from the retired BYOS identity database into Lockerphycer.

Copies `users` (and the `workspaces` they belong to) from the BYOS Postgres into the
Lockerphycer database. Both systems store bcrypt hashes in `users.hashed_password`, so
passwords carry over unchanged and no reset is required.

Dry-run by default; nothing is written unless `--apply` is passed. Idempotent: rows whose
email / workspace id already exist in the target are skipped, so it is safe to re-run.

Usage (inside the lockerphycer-api container, which has DATABASE_URL and the models):

    python scripts/migrate_byos_users.py \
        --source postgresql://veklom:PASSWORD@veklom-postgres:5432/veklom \
        [--apply] [--report /app/logs/byos_user_migration.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.database.database import _normalize_url
from db.models import SubscriptionTier, User, UserRole, UserStatus, Workspace

USERNAME_MIN = 3
USERNAME_MAX = 80
_USERNAME_STRIP = re.compile(r"[^a-z0-9._-]+")
_USERNAME_TRIM = re.compile(r"^[-._]+|[-._]+$")

ROLE_MAP = {
    "OWNER": UserRole.ADMIN,
    "ADMIN": UserRole.ADMIN,
    "ANALYST": UserRole.SECURITY_ANALYST,
    "USER": UserRole.USER,
    "READONLY": UserRole.USER,
}


@dataclass
class Report:
    started_at: str
    apply: bool
    source_users: int = 0
    source_workspaces: int = 0
    users_migrated: list[str] = field(default_factory=list)
    users_skipped_existing: list[str] = field(default_factory=list)
    users_non_bcrypt_hash: list[str] = field(default_factory=list)
    workspaces_migrated: list[str] = field(default_factory=list)
    workspaces_skipped_existing: list[str] = field(default_factory=list)
    username_assignments: dict[str, str] = field(default_factory=dict)
    finished_at: str | None = None


def derive_username(email: str, taken: set[str]) -> str:
    local = email.split("@", 1)[0].lower()
    base = _USERNAME_TRIM.sub("", _USERNAME_STRIP.sub("-", local)) or "user"
    if len(base) < USERNAME_MIN:
        base = f"{base}-user"
    base = base[:USERNAME_MAX]
    candidate = base
    n = 2
    while candidate in taken:
        suffix = f"-{n}"
        candidate = f"{base[: USERNAME_MAX - len(suffix)]}{suffix}"
        n += 1
    taken.add(candidate)
    return candidate


def map_role(role: str | None) -> UserRole:
    return ROLE_MAP.get((role or "").upper(), UserRole.USER)


def map_status(status: str | None, is_active: bool | None) -> UserStatus:
    """Explicit BYOS status wins; the `is_active` flag only decides when status is unknown."""
    try:
        return UserStatus[(status or "").upper()]
    except KeyError:
        return UserStatus.INACTIVE if is_active is False else UserStatus.ACTIVE


def _utcnow() -> datetime:
    # Models store naive UTC timestamps.
    return datetime.now(UTC).replace(tzinfo=None)


def _dt(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return None


async def fetch_source(engine: AsyncEngine) -> tuple[list[dict], list[dict]]:
    async with engine.connect() as conn:
        users = (
            (
                await conn.execute(
                    text(
                        "SELECT id, email, hashed_password, full_name, role, status, is_active, "
                        "workspace_id, mfa_enabled, mfa_secret, failed_login_attempts, "
                        "account_locked_until, last_login, last_activity, created_at, updated_at "
                        "FROM users ORDER BY created_at NULLS LAST, email"
                    )
                )
            )
            .mappings()
            .all()
        )
        workspaces = (
            (
                await conn.execute(
                    text(
                        "SELECT id, name, slug, is_active, created_at, updated_at FROM workspaces ORDER BY created_at NULLS LAST"
                    )
                )
            )
            .mappings()
            .all()
        )
    return [dict(u) for u in users], [dict(w) for w in workspaces]


async def migrate(source_url: str, target_url: str, apply: bool) -> Report:
    report = Report(started_at=_utcnow().isoformat(), apply=apply)
    source_engine = create_async_engine(_normalize_url(source_url))
    target_engine = create_async_engine(_normalize_url(target_url))
    Session = async_sessionmaker(
        target_engine, expire_on_commit=False, class_=AsyncSession
    )

    try:
        src_users, src_workspaces = await fetch_source(source_engine)
        report.source_users = len(src_users)
        report.source_workspaces = len(src_workspaces)

        async with Session() as db:
            existing_emails = {
                e.lower() for e in (await db.execute(select(User.email))).scalars()
            }
            taken_usernames = set((await db.execute(select(User.username))).scalars())
            existing_ws_ids = set((await db.execute(select(Workspace.id))).scalars())
            existing_ws_slugs = set(
                (await db.execute(select(Workspace.slug))).scalars()
            )

            # Workspace owner: first OWNER/ADMIN member by creation order, else first member.
            owner_priority = {"OWNER": 0, "ADMIN": 1}
            owner_rank: dict[str, tuple[int, str]] = {}
            for u in src_users:
                ws_id = u["workspace_id"]
                if not ws_id:
                    continue
                rank = owner_priority.get((u["role"] or "").upper(), 2)
                if ws_id not in owner_rank or rank < owner_rank[ws_id][0]:
                    owner_rank[ws_id] = (rank, u["email"].strip().lower())
            owner_by_ws = {ws: email for ws, (_, email) in owner_rank.items()}

            for w in src_workspaces:
                if w["id"] in existing_ws_ids or w["slug"] in existing_ws_slugs:
                    report.workspaces_skipped_existing.append(w["id"])
                    continue
                db.add(
                    Workspace(
                        id=w["id"],
                        owner_id=owner_by_ws.get(w["id"], ""),
                        name=w["name"],
                        slug=w["slug"],
                        tier=SubscriptionTier.FREE,
                        is_active=bool(w["is_active"])
                        if w["is_active"] is not None
                        else True,
                        settings={
                            "migrated_from": "byos",
                            "byos_workspace_id": w["id"],
                        },
                        created_at=_dt(w["created_at"]) or _utcnow(),
                        updated_at=_dt(w["updated_at"]),
                    )
                )
                report.workspaces_migrated.append(w["id"])

            for u in src_users:
                email = (u["email"] or "").strip().lower()
                if not email or email in existing_emails:
                    report.users_skipped_existing.append(email)
                    continue
                hashed = u["hashed_password"] or ""
                if not hashed.startswith("$2"):
                    report.users_non_bcrypt_hash.append(email)
                username = derive_username(email, taken_usernames)
                report.username_assignments[email] = username
                db.add(
                    User(
                        id=u["id"],
                        email=email,
                        username=username,
                        hashed_password=hashed,
                        full_name=u["full_name"] or None,
                        role=map_role(u["role"]),
                        status=map_status(u["status"], u["is_active"]),
                        mfa_enabled=bool(u["mfa_enabled"]),
                        mfa_secret=u["mfa_secret"],
                        failed_login_attempts=int(u["failed_login_attempts"] or 0),
                        account_locked_until=_dt(u["account_locked_until"]),
                        last_login=_dt(u["last_login"]),
                        last_activity=_dt(u["last_activity"]),
                        created_at=_dt(u["created_at"]) or _utcnow(),
                        updated_at=_dt(u["updated_at"]),
                    )
                )
                existing_emails.add(email)
                report.users_migrated.append(email)

            if apply:
                await db.commit()
            else:
                await db.rollback()
    finally:
        await source_engine.dispose()
        await target_engine.dispose()

    report.finished_at = _utcnow().isoformat()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source",
        default=os.environ.get("SOURCE_DATABASE_URL"),
        help="BYOS Postgres URL",
    )
    parser.add_argument(
        "--target",
        default=os.environ.get("DATABASE_URL"),
        help="Lockerphycer DATABASE_URL",
    )
    parser.add_argument(
        "--apply", action="store_true", help="commit changes (default: dry-run)"
    )
    parser.add_argument("--report", help="write JSON evidence to this path")
    args = parser.parse_args()
    if not args.source or not args.target:
        parser.error(
            "--source and --target (or SOURCE_DATABASE_URL / DATABASE_URL) are required"
        )

    report = asyncio.run(migrate(args.source, args.target, args.apply))
    summary = {
        "mode": "APPLIED" if report.apply else "DRY-RUN",
        "source_users": report.source_users,
        "source_workspaces": report.source_workspaces,
        "users_migrated": len(report.users_migrated),
        "users_skipped_existing": len(report.users_skipped_existing),
        "users_non_bcrypt_hash": len(report.users_non_bcrypt_hash),
        "workspaces_migrated": len(report.workspaces_migrated),
        "workspaces_skipped_existing": len(report.workspaces_skipped_existing),
    }
    print(json.dumps(summary, indent=2))
    if args.report:
        Path(args.report).write_text(json.dumps(asdict(report), indent=2, default=str))
        print(f"report written to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
