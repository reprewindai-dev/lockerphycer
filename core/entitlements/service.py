"""Workspace entitlement engine (persistent port of the reference orchestrator).

Invariants (locked commercial model):
  * Welcome: WELCOME_DAYS from workspace creation, automatic, never recurs for
    the same owner or workspace. High ceiling + abuse limit, never "unlimited".
  * After Welcome the workspace is on Developer: 250 credits per period.
  * Consumption order: period allowance first, then non-expiring top-ups.
  * Credits are consumed off-chain. No currency peg lives here.
  * The ledger is append-only; an idempotency key never charges twice.
  * Reads are fail-safe: they are never blocked for lack of credits.

All datetimes are naive UTC, matching the rest of db/models.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.entitlements import plans as P
from core.entitlements.activation import add_event_in_txn, build_event
from core.entitlements.config import EntitlementSettings, get_entitlement_settings
from db.models import ActivationEvent, CreditLedgerEntry, Workspace, WorkspaceEntitlement


def _now() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Errors (structured, rendered by the router as-is)
# ---------------------------------------------------------------------------


class EntitlementError(Exception):
    status_code = 400
    code = "ENTITLEMENT_ERROR"

    def __init__(self, body: dict[str, Any]):
        self.body = {"code": self.code, **body}
        super().__init__(self.code)


class CreditsExhausted(EntitlementError):
    status_code = 402
    code = "CREDITS_EXHAUSTED"


class SafeUseLimitReached(EntitlementError):
    status_code = 429
    code = "SAFE_USE_LIMIT_REACHED"


class PlanLimitReached(EntitlementError):
    status_code = 403
    code = "PLAN_LIMIT_REACHED"


class IdempotencyConflict(EntitlementError):
    status_code = 409
    code = "IDEMPOTENCY_CONFLICT"


class UnknownWorkspace(EntitlementError):
    status_code = 404
    code = "WORKSPACE_NOT_FOUND"


@dataclass
class MeterResult:
    allowed: bool
    charged: bool
    replay: bool
    credits: int
    entry_id: str | None
    action_type: str
    balance: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "charged": self.charged,
            "replay": self.replay,
            "credits": self.credits,
            "entry_id": self.entry_id,
            "action_type": self.action_type,
            "balance": self.balance,
        }


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------


def _cfg() -> EntitlementSettings:
    return get_entitlement_settings()


def in_welcome(ent: WorkspaceEntitlement, now: datetime) -> bool:
    return bool(
        ent.welcome_ends_at is not None
        and ent.welcome_ended_at is None
        and now < ent.welcome_ends_at
    )


def _allowance_remaining(ent: WorkspaceEntitlement) -> int:
    return max(0, int(ent.period_allowance or 0) - int(ent.period_used or 0))


def balances(ent: WorkspaceEntitlement) -> dict[str, int]:
    remaining = _allowance_remaining(ent)
    return {
        "allowance_total": int(ent.period_allowance or 0),
        "allowance_used": int(ent.period_used or 0),
        "allowance_remaining": remaining,
        "topup_balance": int(ent.topup_balance or 0),
        "total_available": remaining + int(ent.topup_balance or 0),
    }


def _plan_allowance(plan: str, cfg: EntitlementSettings, current: int) -> int:
    credits = P.plan_catalog(cfg)[plan]["monthly_credits"]
    return current if credits is None else int(credits)


def _entry(ent: WorkspaceEntitlement, now: datetime, **kw: Any) -> CreditLedgerEntry:
    return CreditLedgerEntry(
        workspace_id=ent.workspace_id,
        balance_after=balances(ent)["total_available"],
        created_at=now,
        **kw,
    )


def _grant(ent: WorkspaceEntitlement, now: datetime, description: str, key: str) -> CreditLedgerEntry:
    return _entry(
        ent,
        now,
        entry_type="grant",
        direction="credit",
        credits=int(ent.period_allowance or 0),
        idempotency_key=key,
        description=description,
    )


async def _key_exists(db: AsyncSession, key: str) -> CreditLedgerEntry | None:
    return (
        await db.execute(select(CreditLedgerEntry).where(CreditLedgerEntry.idempotency_key == key))
    ).scalar_one_or_none()


async def _roll(db: AsyncSession, ent: WorkspaceEntitlement, now: datetime) -> None:
    """Lazily apply Welcome expiry and monthly resets up to ``now``."""
    cfg = _cfg()
    period = timedelta(days=cfg.ENTITLEMENT_PERIOD_DAYS)

    if (
        ent.welcome_ends_at is not None
        and ent.welcome_ended_at is None
        and now >= ent.welcome_ends_at
    ):
        # Welcome over: drop to the base plan, first period starts at Welcome end.
        ent.welcome_ended_at = ent.welcome_ends_at
        ent.period_start = ent.welcome_ends_at
        ent.period_end = ent.welcome_ends_at + period
        ent.period_allowance = _plan_allowance(ent.plan, cfg, 0)
        ent.period_used = 0
        await add_event_in_txn(
            db,
            build_event(
                "welcome_ended",
                workspace_id=ent.workspace_id,
                details={"welcome_ends_at": ent.welcome_ends_at.isoformat(), "plan": ent.plan},
                now=now,
            ),
        )
        if now < ent.period_end:
            key = f"grant:{ent.workspace_id}:{ent.period_start.isoformat()}"
            if await _key_exists(db, key) is None:
                db.add(_grant(ent, now, f"{ent.plan} allowance after Welcome", key))

    if now >= ent.period_end:
        elapsed = math.floor((now - ent.period_end) / period) + 1
        ent.period_start = ent.period_end + (elapsed - 1) * period
        ent.period_end = ent.period_start + period
        ent.period_allowance = _plan_allowance(ent.plan, cfg, int(ent.period_allowance or 0))
        ent.period_used = 0
        key = f"grant:{ent.workspace_id}:{ent.period_start.isoformat()}"
        if await _key_exists(db, key) is None:
            db.add(_grant(ent, now, f"{ent.plan} monthly allowance reset", key))


async def _load(db: AsyncSession, workspace_id: str, *, lock: bool) -> WorkspaceEntitlement | None:
    stmt = select(WorkspaceEntitlement).where(WorkspaceEntitlement.workspace_id == workspace_id)
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def ensure_entitlement(
    db: AsyncSession,
    workspace: Workspace,
    *,
    now: datetime | None = None,
    lock: bool = False,
) -> WorkspaceEntitlement:
    """Return the workspace's entitlement, creating it (Welcome clock) if absent.

    Creation anchors Welcome at ``workspace.created_at``. This is also the
    backfill path for pre-existing workspaces: a workspace older than
    WELCOME_DAYS lands directly on Developer. Does not commit.
    """
    now = now or _now()
    ent = await _load(db, workspace.id, lock=lock)
    if ent is not None:
        await _roll(db, ent, now)
        return ent

    cfg = _cfg()
    owner_key = (workspace.owner_id or "").strip().lower() or f"workspace:{workspace.id}"
    anchor = workspace.created_at or now
    prior_welcome = (
        await db.execute(
            select(WorkspaceEntitlement.workspace_id).where(
                WorkspaceEntitlement.welcome_owner_key == owner_key
            )
        )
    ).scalar_one_or_none()

    if prior_welcome is None:
        ends = anchor + timedelta(days=cfg.WELCOME_DAYS)
        ent = WorkspaceEntitlement(
            workspace_id=workspace.id,
            owner_key=owner_key,
            plan=P.DEVELOPER,
            welcome_started_at=anchor,
            welcome_ends_at=ends,
            welcome_owner_key=owner_key,
            period_start=anchor,
            period_end=ends,
            period_allowance=cfg.WELCOME_CREDIT_CEILING,
            period_used=0,
            topup_balance=0,
            created_at=now,
        )
    else:
        # Welcome never recurs for the same owner.
        ent = WorkspaceEntitlement(
            workspace_id=workspace.id,
            owner_key=owner_key,
            plan=P.DEVELOPER,
            period_start=now,
            period_end=now + timedelta(days=cfg.ENTITLEMENT_PERIOD_DAYS),
            period_allowance=_plan_allowance(P.DEVELOPER, cfg, 0),
            period_used=0,
            topup_balance=0,
            created_at=now,
        )
    db.add(ent)
    if now < ent.period_end:
        label = "Welcome safe-use ceiling" if prior_welcome is None else "developer allowance (Welcome already used by owner)"
        db.add(_grant(ent, now, label, f"grant:{ent.workspace_id}:{ent.period_start.isoformat()}"))
    await db.flush()
    await _roll(db, ent, now)
    return ent


async def _workspace(db: AsyncSession, workspace_id: str) -> Workspace:
    ws = await db.get(Workspace, workspace_id)
    if ws is None:
        raise UnknownWorkspace({"workspace_id": workspace_id})
    return ws


async def _locked_entitlement(db: AsyncSession, workspace_id: str, now: datetime) -> WorkspaceEntitlement:
    ent = await _load(db, workspace_id, lock=True)
    if ent is None:
        await ensure_entitlement(db, await _workspace(db, workspace_id), now=now)
        await db.flush()
        ent = await _load(db, workspace_id, lock=True)
    assert ent is not None
    await _roll(db, ent, now)
    return ent


def _denial_body(ent: WorkspaceEntitlement, now: datetime, action: str, cost: int) -> dict[str, Any]:
    cfg = _cfg()
    return {
        "message": "Credits exhausted; funding required to continue governed actions.",
        "workspace_id": ent.workspace_id,
        "plan": ent.plan,
        "in_welcome": in_welcome(ent, now),
        "action_type": action,
        "required_credits": cost,
        "balance": balances(ent),
        "period_end": ent.period_end.isoformat(),
        "topups_allowed": True,
        "upgrade_path": cfg.ENTITLEMENTS_UPGRADE_PATH,
        "topup_path": cfg.ENTITLEMENTS_TOPUP_PATH,
    }


async def _used_last_24h(db: AsyncSession, workspace_id: str, now: datetime) -> int:
    since = now - timedelta(hours=24)
    rows = (
        await db.execute(
            select(CreditLedgerEntry.entry_type, func.coalesce(func.sum(CreditLedgerEntry.credits), 0))
            .where(
                CreditLedgerEntry.workspace_id == workspace_id,
                CreditLedgerEntry.created_at >= since,
                CreditLedgerEntry.entry_type.in_(("debit", "reversal")),
            )
            .group_by(CreditLedgerEntry.entry_type)
        )
    ).all()
    totals = {etype: int(total) for etype, total in rows}
    return totals.get("debit", 0) - totals.get("reversal", 0)


def _replay_result(entry: CreditLedgerEntry, workspace_id: str, action: str, ent_bal: dict) -> MeterResult:
    if entry.workspace_id != workspace_id or (entry.action_type and entry.action_type != action):
        raise IdempotencyConflict({"idempotency_key": entry.idempotency_key})
    return MeterResult(
        allowed=True,
        charged=entry.entry_type == "debit",
        replay=True,
        credits=int(entry.credits or 0),
        entry_id=entry.id,
        action_type=action,
        balance=ent_bal,
    )


# ---------------------------------------------------------------------------
# Public operations
# ---------------------------------------------------------------------------


async def debit(
    db: AsyncSession,
    workspace_id: str,
    action_type: str,
    *,
    idempotency_key: str,
    mount_id: str | None = None,
    execution_ref: str | None = None,
    operation_ref: str | None = None,
    principal: str | None = None,
    now: datetime | None = None,
) -> MeterResult:
    """Charge one metered action. Commits. Raises CreditsExhausted (402) etc."""
    now = now or _now()
    action = P.normalize_action(action_type)
    if not idempotency_key:
        raise ValueError("idempotency_key is required")

    ent = await _locked_entitlement(db, workspace_id, now)
    existing = await _key_exists(db, idempotency_key)
    if existing is not None:
        result = _replay_result(existing, workspace_id, action, balances(ent))
        await db.commit()
        return result

    cost = P.CREDIT_SCHEDULE[action]
    is_read = action in P.READ_ACTIONS
    refs = dict(mount_id=mount_id, execution_ref=execution_ref, operation_ref=operation_ref, principal=principal)

    if in_welcome(ent, now) and not is_read:
        cap = _cfg().WELCOME_DAILY_CREDIT_CAP
        if await _used_last_24h(db, workspace_id, now) + cost > cap:
            db.add(_entry(ent, now, entry_type="denied", direction="none", action_type=action,
                          credits=0, description="welcome daily safe-use limit", **refs))
            await db.commit()
            raise SafeUseLimitReached({
                "message": "Welcome safe-use limit reached for the last 24 hours.",
                "workspace_id": workspace_id,
                "daily_credit_cap": cap,
                "retry_after_seconds": 3600,
                "upgrade_path": _cfg().ENTITLEMENTS_UPGRADE_PATH,
            })

    available = balances(ent)["total_available"]
    if available < cost:
        if is_read:
            # Fail safe: reads continue at zero charge (reference orchestrator behaviour).
            entry = _entry(ent, now, entry_type="read_unbilled", direction="none", action_type=action,
                           credits=0, idempotency_key=idempotency_key,
                           description="verification read beyond balance (not charged)", **refs)
            db.add(entry)
            await db.commit()
            return MeterResult(True, False, False, 0, entry.id, action, balances(ent))
        body = _denial_body(ent, now, action, cost)
        db.add(_entry(ent, now, entry_type="denied", direction="none", action_type=action,
                      credits=0, description="credits exhausted", **refs))
        await db.commit()
        raise CreditsExhausted(body)

    allowance_debit = min(cost, _allowance_remaining(ent))
    topup_debit = cost - allowance_debit
    ent.period_used = int(ent.period_used or 0) + allowance_debit
    ent.topup_balance = int(ent.topup_balance or 0) - topup_debit
    ent.updated_at = now
    entry = _entry(ent, now, entry_type="debit", direction="debit", action_type=action, credits=cost,
                   allowance_debit=allowance_debit, topup_debit=topup_debit,
                   idempotency_key=idempotency_key, description=f"metered {action}", **refs)
    db.add(entry)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent replay of the same key won the race: report it as a replay.
        await db.rollback()
        existing = await _key_exists(db, idempotency_key)
        if existing is None:
            raise
        return _replay_result(existing, workspace_id, action, {})
    return MeterResult(True, True, False, cost, entry.id, action, balances(ent))


async def reverse(
    db: AsyncSession,
    idempotency_key: str,
    *,
    reason: str = "authority_denied",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Refund a debit (e.g. CAPPO denied after the commercial preflight). Idempotent."""
    now = now or _now()
    original = await _key_exists(db, idempotency_key)
    if original is None or original.entry_type != "debit":
        return {"reversed": False, "reason": "no_debit_for_key"}
    ent = await _locked_entitlement(db, original.workspace_id, now)
    rkey = f"reversal:{idempotency_key}"
    if await _key_exists(db, rkey) is not None:
        await db.commit()
        return {"reversed": True, "replay": True, "balance": balances(ent)}
    # Allowance is restored only if the debit belongs to the current period;
    # an expired period's allowance is not resurrected. Top-ups always return.
    allowance_back = original.allowance_debit if original.created_at >= ent.period_start else 0
    ent.period_used = max(0, int(ent.period_used or 0) - int(allowance_back or 0))
    ent.topup_balance = int(ent.topup_balance or 0) + int(original.topup_debit or 0)
    ent.updated_at = now
    db.add(_entry(ent, now, entry_type="reversal", direction="credit", action_type=original.action_type,
                  credits=int(original.credits or 0), allowance_debit=-int(allowance_back or 0),
                  topup_debit=-int(original.topup_debit or 0), idempotency_key=rkey,
                  reverses_entry_id=original.id, mount_id=original.mount_id,
                  execution_ref=original.execution_ref, operation_ref=original.operation_ref,
                  principal=original.principal, description=f"reversal: {reason}"))
    await db.commit()
    return {"reversed": True, "replay": False, "balance": balances(ent)}


async def grant_topup(
    db: AsyncSession,
    workspace_id: str,
    credits: int,
    *,
    idempotency_key: str,
    settlement_rail: str,
    settlement_ref: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Add non-expiring top-up credits (after settlement is verified elsewhere)."""
    now = now or _now()
    if credits <= 0:
        raise ValueError("credits must be positive")
    ent = await _locked_entitlement(db, workspace_id, now)
    existing = await _key_exists(db, idempotency_key)
    if existing is not None:
        if existing.workspace_id != workspace_id or existing.entry_type != "topup" or existing.credits != credits:
            raise IdempotencyConflict({"idempotency_key": idempotency_key})
        await db.commit()
        return {"replay": True, "entry_id": existing.id, "balance": balances(ent)}
    ent.topup_balance = int(ent.topup_balance or 0) + credits
    ent.updated_at = now
    entry = _entry(ent, now, entry_type="topup", direction="credit", credits=credits,
                   idempotency_key=idempotency_key, settlement_rail=settlement_rail,
                   settlement_ref=settlement_ref, description="top-up (non-expiring)")
    db.add(entry)
    await db.commit()
    return {"replay": False, "entry_id": entry.id, "balance": balances(ent)}


async def set_plan(
    db: AsyncSession,
    workspace_id: str,
    plan: str,
    *,
    monthly_credits: int | None = None,
    now: datetime | None = None,
) -> WorkspaceEntitlement:
    """Change the base plan; starts a fresh allowance period now. Commits."""
    now = now or _now()
    if plan not in P.PLAN_IDS:
        raise ValueError(f"unknown plan {plan}")
    if plan == P.ENTERPRISE and monthly_credits is None:
        raise ValueError("enterprise requires monthly_credits (custom contract)")
    cfg = _cfg()
    ent = await _locked_entitlement(db, workspace_id, now)
    if plan in P.PAID_PLANS:
        if in_welcome(ent, now):
            ent.welcome_ended_at = now
        if ent.converted_at is None and ent.welcome_started_at is not None:
            ent.converted_at = now
            await add_event_in_txn(db, build_event(
                "trial_converted", workspace_id=workspace_id, details={"plan": plan}, now=now))
    ent.plan = plan
    ent.period_start = now
    ent.period_end = now + timedelta(days=cfg.ENTITLEMENT_PERIOD_DAYS)
    ent.period_allowance = int(monthly_credits) if monthly_credits is not None else _plan_allowance(plan, cfg, 0)
    ent.period_used = 0
    ent.updated_at = now
    db.add(_grant(ent, now, f"plan set to {plan}", f"grant:{workspace_id}:{plan}:{now.isoformat()}"))
    await db.commit()
    return ent


async def renew_period(
    db: AsyncSession,
    workspace_id: str,
    *,
    ref: str,
    now: datetime | None = None,
) -> WorkspaceEntitlement:
    """Start a fresh allowance period (paid renewal). Idempotent per ``ref``. Commits."""
    now = now or _now()
    cfg = _cfg()
    ent = await _locked_entitlement(db, workspace_id, now)
    key = f"grant:{ref}"
    if await _key_exists(db, key) is None:
        ent.period_start = now
        ent.period_end = now + timedelta(days=cfg.ENTITLEMENT_PERIOD_DAYS)
        ent.period_allowance = _plan_allowance(ent.plan, cfg, int(ent.period_allowance or 0))
        ent.period_used = 0
        ent.updated_at = now
        db.add(_grant(ent, now, f"{ent.plan} renewal", key))
    await db.commit()
    return ent


def effective_limits(ent: WorkspaceEntitlement, now: datetime) -> dict[str, Any]:
    cfg = _cfg()
    limits = P.welcome_limits(cfg) if in_welcome(ent, now) else dict(P.plan_catalog(cfg)[ent.plan])
    if ent.plan == P.ENTERPRISE:
        limits["monthly_credits"] = int(ent.period_allowance or 0)
    return limits


def snapshot(ent: WorkspaceEntitlement, now: datetime | None = None) -> dict[str, Any]:
    now = now or _now()
    cfg = _cfg()
    welcome_active = in_welcome(ent, now)
    days_left = 0
    if welcome_active:
        days_left = max(0, math.ceil((ent.welcome_ends_at - now).total_seconds() / 86400))
    catalog = P.plan_catalog(cfg)
    return {
        "workspace_id": ent.workspace_id,
        "plan": ent.plan,
        "plan_name": catalog[ent.plan]["name"],
        "effective_tier": P.WELCOME if welcome_active else ent.plan,
        "welcome": {
            "active": welcome_active,
            "eligible": ent.welcome_started_at is not None,
            "started_at": ent.welcome_started_at.isoformat() if ent.welcome_started_at else None,
            "ends_at": ent.welcome_ends_at.isoformat() if ent.welcome_ends_at else None,
            "ended_at": ent.welcome_ended_at.isoformat() if ent.welcome_ended_at else None,
            "days_left": days_left,
            "message": P.WELCOME_MESSAGE.format(days=cfg.WELCOME_DAYS) if welcome_active else None,
        },
        "period": {"start": ent.period_start.isoformat(), "end": ent.period_end.isoformat()},
        "balances": balances(ent),
        "limits": effective_limits(ent, now),
        "credit_schedule": dict(P.CREDIT_SCHEDULE),
        "consumption_order": ["allowance", "topup"],
        "upgrade_path": cfg.ENTITLEMENTS_UPGRADE_PATH,
        "topup_path": cfg.ENTITLEMENTS_TOPUP_PATH,
    }


async def check_agent_limit(db: AsyncSession, workspace: Workspace, active_agents: int) -> None:
    """Raise PlanLimitReached if adding one more agent would exceed the plan."""
    now = _now()
    ent = await ensure_entitlement(db, workspace, now=now)
    limit = effective_limits(ent, now).get("agents")
    if limit is not None and active_agents >= limit:
        raise PlanLimitReached({
            "limit": "agents",
            "max": limit,
            "current": active_agents,
            "plan": ent.plan,
            "in_welcome": in_welcome(ent, now),
            "upgrade_path": _cfg().ENTITLEMENTS_UPGRADE_PATH,
        })


GOVERNED_ACTIONS = tuple(a for a in P.CREDIT_SCHEDULE if a not in P.READ_ACTIONS)


async def usage_summary(
    db: AsyncSession,
    workspace_id: str,
    *,
    since: datetime,
    until: datetime,
) -> dict[str, Any]:
    """Aggregate the metering ledger + activation milestones for one window."""
    window = (
        CreditLedgerEntry.workspace_id == workspace_id,
        CreditLedgerEntry.created_at >= since,
        CreditLedgerEntry.created_at < until,
    )
    rows = (
        await db.execute(
            select(
                CreditLedgerEntry.entry_type,
                CreditLedgerEntry.action_type,
                func.count(),
                func.coalesce(func.sum(CreditLedgerEntry.credits), 0),
            )
            .where(*window)
            .group_by(CreditLedgerEntry.entry_type, CreditLedgerEntry.action_type)
        )
    ).all()
    count: dict[tuple[str, str | None], int] = {}
    credits: dict[str, int] = {}
    for etype, action, n, total in rows:
        count[(etype, action)] = int(n)
        credits[etype] = credits.get(etype, 0) + int(total)

    def n(etype: str, actions: tuple[str, ...]) -> int:
        return sum(count.get((etype, a), 0) for a in actions)

    reversed_governed = n("reversal", GOVERNED_ACTIONS)
    allowed_governed = n("debit", GOVERNED_ACTIONS) - reversed_governed
    agents = (
        await db.execute(
            select(func.count(func.distinct(CreditLedgerEntry.principal))).where(
                *window,
                CreditLedgerEntry.entry_type == "debit",
                CreditLedgerEntry.principal.isnot(None),
            )
        )
    ).scalar_one()
    milestones = (
        await db.execute(
            select(ActivationEvent.event_name, func.min(ActivationEvent.created_at))
            .where(ActivationEvent.workspace_id == workspace_id)
            .group_by(ActivationEvent.event_name)
        )
    ).all()
    return {
        "workspace_id": workspace_id,
        "window": {"since": since.isoformat(), "until": until.isoformat()},
        "governed_actions": allowed_governed,
        "governed_executions": n("debit", ("governed_execution",)) - n("reversal", ("governed_execution",)),
        "denied_actions": reversed_governed + n("denied", GOVERNED_ACTIONS),
        "denied_for_credits": n("denied", GOVERNED_ACTIONS),
        "verification_reads": n("debit", P.READ_ACTIONS) + n("read_unbilled", P.READ_ACTIONS),
        "active_agents": int(agents or 0),
        "receipts": allowed_governed,
        "credits_used": credits.get("debit", 0) - credits.get("reversal", 0),
        "milestones": {name: ts.isoformat() for name, ts in milestones},
        "source": "lockerphycer credit_ledger (metered traffic only)",
    }
