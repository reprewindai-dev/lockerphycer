"""Activation events: append-only product milestones per workspace/user.

Once-only events carry a dedupe_key (unique), so repeated emits are no-ops.
Emission is best-effort from request paths: it must never break signup,
login or execution.
"""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import ActivationEvent

logger = logging.getLogger(__name__)

ACTIVATION_EVENTS = frozenset(
    {
        "signup_completed",
        "email_verified",
        "wallet_created",
        "wallet_connected",
        "funding_method_added",
        "capability_issued",
        "system_connected",
        "first_authority_decision",
        "first_governed_execution",
        "first_denied_action",
        "first_receipt_verified",
        "second_session",
        "production_workflow_connected",
        "welcome_ending_notified",
        "welcome_ended",
        "trial_converted",
    }
)

# Events CAPPO may report over the internal endpoint.
CAPPO_EVENTS = frozenset(
    {
        "capability_issued",
        "first_authority_decision",
        "first_governed_execution",
        "first_denied_action",
        "first_receipt_verified",
        "system_connected",
        "production_workflow_connected",
    }
)

# Every listed milestone is once-only per subject; capability_issued is the
# exception (every issuance is recorded; the first one is derivable).
REPEATABLE_EVENTS = frozenset({"capability_issued"})


def dedupe_key_for(event_name: str, workspace_id: str | None, user_id: str | None) -> str | None:
    if event_name in REPEATABLE_EVENTS:
        return None
    subject = f"ws:{workspace_id}" if workspace_id else f"user:{user_id}"
    return f"{event_name}:{subject}"


def build_event(
    event_name: str,
    *,
    workspace_id: str | None = None,
    user_id: str | None = None,
    source: str = "lockerphycer",
    ref: str | None = None,
    details: dict | None = None,
    now: datetime | None = None,
) -> ActivationEvent:
    if event_name not in ACTIVATION_EVENTS:
        raise ValueError(f"unknown activation event: {event_name}")
    if not workspace_id and not user_id:
        raise ValueError("activation event needs a workspace_id or user_id")
    return ActivationEvent(
        event_name=event_name,
        workspace_id=workspace_id,
        user_id=user_id,
        source=source,
        ref=ref,
        dedupe_key=dedupe_key_for(event_name, workspace_id, user_id),
        details=details or {},
        created_at=now or datetime.utcnow(),
    )


async def add_event_in_txn(db: AsyncSession, event: ActivationEvent) -> bool:
    """Add inside the caller's transaction (caller holds the relevant row lock)."""
    if event.dedupe_key:
        exists = await db.execute(
            select(ActivationEvent.id).where(ActivationEvent.dedupe_key == event.dedupe_key)
        )
        if exists.scalar_one_or_none() is not None:
            return False
    db.add(event)
    return True


async def emit_activation_event(db: AsyncSession, event_name: str, **kwargs) -> bool:
    """Best-effort standalone emit. Call only after the caller has committed.

    Commits its own row; on duplicate or any failure it rolls back and returns
    False without raising.
    """
    try:
        event = build_event(event_name, **kwargs)
        added = await add_event_in_txn(db, event)
        if not added:
            return False
        await db.commit()
        return True
    except IntegrityError:
        await db.rollback()
        return False
    except Exception:  # never break the calling flow
        logger.warning("activation event %s not recorded", event_name, exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
        return False
