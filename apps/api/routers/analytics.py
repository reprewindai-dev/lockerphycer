"""First-party funnel analytics.

Public:  GET  /api/v1/analytics/config   collection mode for this visitor
         POST /api/v1/analytics/events   anonymous event batch (rate-limited)
Session: POST /api/v1/analytics/link     link this tab's session id to the
                                         signed-in workspace (activation_events)
Admin:   GET  /api/v1/analytics/funnel   step counts, conversion and bounce

No cookies are read or set, and no IP address or user agent is stored.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.analytics import events as E
from core.analytics import funnel as F
from core.analytics.models import AnalyticsEvent
from core.database.database import get_db
from core.entitlements.activation import add_event_in_txn, build_event
from core.security.auth import get_current_user, require_admin
from db.models import ActivationEvent, User, UserSession, Workspace

logger = logging.getLogger(__name__)
router = APIRouter()

LINK_EVENT = "analytics_session_linked"
_SALT = os.urandom(16)  # per process; rate-limit keys are never persisted

batch_limiter = E.SlidingWindowLimiter(E.batch_limit())
event_limiter = E.SlidingWindowLimiter(E.event_limit())
link_limiter = E.SlidingWindowLimiter(20)

ANALYTICS_ORIGINS = {
    "https://veklom.com",
    "https://www.veklom.com",
    "https://os.veklom.com",
    "https://vlink.veklom.com",
}

_BOT_UA = re.compile(r"bot|crawl|spider|slurp|headless|lighthouse|preview|monitor|curl|wget|python-requests|httpclient", re.I)


def _headers(request: Request) -> dict[str, str]:
    return {k.lower(): v for k, v in request.headers.items()}


def _rate_key(request: Request) -> str:
    h = request.headers
    ip = (
        h.get("cf-connecting-ip")
        or (h.get("x-forwarded-for") or "").split(",")[0].strip()
        or h.get("x-real-ip")
        or (request.client.host if request.client else "unknown")
    )
    return hashlib.sha256(_SALT + ip.encode()).hexdigest()


def _origin_allowed(origin: str | None) -> bool:
    if not origin:
        return True  # server-to-server (VLink proxy) or same-origin beacon without Origin
    from core.security.middleware import allowed_request_origins

    o = origin.rstrip("/")
    return o in ANALYTICS_ORIGINS or o in allowed_request_origins()


def _too_many(retry: int = 60) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": {"code": 429, "message": "Rate limit exceeded"}},
        headers={"Retry-After": str(retry)},
    )


@router.get("/config")
async def analytics_config(request: Request, consent: Optional[str] = Query(None, max_length=16)):
    """Tells the tracker whether it may create a per-tab session id."""
    if consent not in (None, "granted", "denied", "unset"):
        consent = None
    mode = E.decide_mode(_headers(request), consent)
    return JSONResponse(
        {"mode": mode.mode, "reasons": mode.reasons},
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/events")
async def ingest_events(request: Request, db: AsyncSession = Depends(get_db)):
    if not _origin_allowed(request.headers.get("origin")):
        raise HTTPException(status_code=403, detail="origin not allowed")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > E.MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="payload_too_large")

    key = _rate_key(request)
    if not batch_limiter.allow(key):
        return _too_many()

    raw = await request.body()
    try:
        batch = E.parse_batch(raw)
    except E.ValidationError as exc:
        code = 413 if str(exc) == "payload_too_large" else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc

    if not event_limiter.allow(key, cost=len(batch.events)):
        return _too_many()

    if _BOT_UA.search(request.headers.get("user-agent", "")):
        return {"accepted": 0, "dropped": len(batch.events), "mode": "ignored"}

    mode = E.decide_mode(_headers(request), batch.consent)
    batch = E.apply_mode(batch, mode)
    now = datetime.utcnow()
    for ev in batch.events:
        db.add(
            AnalyticsEvent(
                event_name=ev.event_name,
                session_id=batch.session_id,
                host=batch.host,
                path=ev.path,
                referrer_domain=ev.referrer_domain,
                props=ev.props,
                country=mode.country,
                aggregate_only=batch.session_id is None,
                client_ts=ev.client_ts,
                received_at=now,
                **ev.utm,
            )
        )
    if batch.events:
        await db.commit()
    return {"accepted": len(batch.events), "dropped": batch.dropped, "mode": mode.mode}


class LinkRequest(BaseModel):
    sid: str = Field(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    consent: Optional[str] = Field(default=None, pattern=r"^(granted|denied|unset)$")


@router.post("/link")
async def link_session(
    body: LinkRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record, once, that this anonymous session belongs to the signed-in workspace."""
    if not link_limiter.allow(_rate_key(request)):
        return _too_many()
    mode = E.decide_mode(_headers(request), body.consent)
    if mode.aggregate:
        return {"linked": False, "reasons": mode.reasons}
    ws = (
        await db.execute(
            select(Workspace)
            .where(Workspace.owner_id == current_user.email, Workspace.is_active == True)  # noqa: E712
            .order_by(Workspace.created_at.asc())
        )
    ).scalars().first()
    event = build_event(
        LINK_EVENT,
        workspace_id=ws.id if ws else None,
        user_id=current_user.id,
        source="analytics",
        ref=body.sid,
    )
    event.dedupe_key = f"{LINK_EVENT}:{body.sid}"
    try:
        added = await add_event_in_txn(db, event)
        if added:
            await db.commit()
    except IntegrityError:
        await db.rollback()
        added = False
    return {"linked": True, "new": bool(added)}


# ---------------------------------------------------------------------------
# Funnel (admin)
# ---------------------------------------------------------------------------


def _parse_bound(value: Optional[str], *, end: bool) -> Optional[datetime]:
    if not value:
        return None
    try:
        if len(value) == 10:
            d = date.fromisoformat(value)
            return datetime.combine(d + timedelta(days=1) if end else d, time.min)
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None) if dt.tzinfo is None else (dt - dt.utcoffset()).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid date: {value}") from exc


def _chunks(items: list, n: int = 500):
    for i in range(0, len(items), n):
        yield items[i : i + n]


@router.get("/funnel")
async def funnel(
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None),
    host: Optional[str] = Query(None),
    admin_email: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.utcnow()
    end = _parse_bound(to, end=True) or now
    start = _parse_bound(from_, end=False) or (end - timedelta(days=30))
    if start >= end:
        raise HTTPException(status_code=400, detail="from must be before to")
    if end - start > timedelta(days=366):
        raise HTTPException(status_code=400, detail="window longer than 366 days")
    if host is not None and host not in E.HOSTS:
        raise HTTPException(status_code=400, detail="invalid host")

    # --- anonymous sessions -------------------------------------------------
    q = select(
        AnalyticsEvent.session_id, AnalyticsEvent.event_name, AnalyticsEvent.path,
        AnalyticsEvent.received_at, AnalyticsEvent.referrer_domain, AnalyticsEvent.props,
    ).where(
        AnalyticsEvent.session_id.is_not(None),
        AnalyticsEvent.received_at >= start,
        AnalyticsEvent.received_at < end,
    )
    if host:
        q = q.where(AnalyticsEvent.host == host)
    rows = (await db.execute(q)).all()
    summaries = F.summarize_sessions(F.SessionEvent(*r) for r in rows)
    counts = F.session_counts(summaries)

    agg_q = select(AnalyticsEvent.host, func.count()).where(
        AnalyticsEvent.session_id.is_(None),
        AnalyticsEvent.event_name == "page_view",
        AnalyticsEvent.received_at >= start,
        AnalyticsEvent.received_at < end,
    ).group_by(AnalyticsEvent.host)
    if host:
        agg_q = agg_q.where(AnalyticsEvent.host == host)
    agg_by_host = {h: int(n) for h, n in (await db.execute(agg_q)).all()}

    # --- account cohort -----------------------------------------------------
    cohort_rows = (
        await db.execute(
            select(User.id, User.email, User.created_at, User.last_activity).where(
                User.created_at >= start, User.created_at < end
            )
        )
    ).all()
    cohort = [F.CohortUser(r.id, (r.email or "").lower(), r.created_at) for r in cohort_rows]
    user_ids = [u.id for u in cohort]
    emails = [u.email for u in cohort]

    workspaces_by_email: dict[str, list[str]] = defaultdict(list)
    for chunk in _chunks(emails):
        for ws_id, owner in (
            await db.execute(select(Workspace.id, Workspace.owner_id).where(Workspace.owner_id.in_(chunk)))
        ).all():
            workspaces_by_email[(owner or "").lower()].append(ws_id)
    ws_ids = [w for ids in workspaces_by_email.values() for w in ids]

    activations: list[F.Activation] = []
    seen: set[str] = set()
    for column, values in ((ActivationEvent.user_id, user_ids), (ActivationEvent.workspace_id, ws_ids)):
        for chunk in _chunks(values):
            for r in (
                await db.execute(
                    select(ActivationEvent.id, ActivationEvent.event_name, ActivationEvent.user_id,
                           ActivationEvent.workspace_id, ActivationEvent.created_at, ActivationEvent.ref)
                    .where(column.in_(chunk))
                )
            ).all():
                if r.id in seen:
                    continue
                seen.add(r.id)
                activations.append(F.Activation(r.event_name, r.user_id, r.workspace_id, r.created_at, r.ref))

    activity: dict[str, list[datetime]] = defaultdict(list)
    for chunk in _chunks(user_ids):
        for uid, created, last in (
            await db.execute(
                select(UserSession.user_id, UserSession.created_at, UserSession.last_accessed)
                .where(UserSession.user_id.in_(chunk))
            )
        ).all():
            activity[uid].extend(t for t in (created, last) if t is not None)
    for r in cohort_rows:
        if r.last_activity is not None and r.id in activity:
            activity[r.id].append(r.last_activity)

    sid_owner = {a.ref: a.user_id for a in activations if a.event_name == LINK_EVENT and a.ref and a.user_id}
    linked: dict[str, list[F.SessionEvent]] = defaultdict(list)
    for chunk in _chunks(list(sid_owner)):
        for r in (
            await db.execute(
                select(AnalyticsEvent.session_id, AnalyticsEvent.event_name, AnalyticsEvent.path,
                       AnalyticsEvent.received_at, AnalyticsEvent.referrer_domain, AnalyticsEvent.props)
                .where(AnalyticsEvent.session_id.in_(chunk))
            )
        ).all():
            linked[sid_owner[r.session_id]].append(F.SessionEvent(*r))

    counts.update(F.account_steps(cohort, workspaces_by_email, activations, activity, linked))
    visitor_sessions = [s for s in summaries.values() if s.visitor]
    bounced = sum(1 for s in visitor_sessions if not s.engaged)

    return {
        "window": {"from": start.isoformat(), "to": end.isoformat(), "host": host},
        "generated_at": now.isoformat(),
        "steps": F.build_steps(counts),
        "bounce": {
            "sessions": len(visitor_sessions),
            "bounced": bounced,
            "bounce_rate": round(bounced / len(visitor_sessions), 4) if visitor_sessions else None,
            "by_landing_page": F.bounce_table(visitor_sessions, "landing_path"),
            "by_referrer": F.bounce_table(visitor_sessions, "referrer"),
        },
        "session_events": F.session_event_breakdown(summaries),
        "aggregate_page_views": {"total": sum(agg_by_host.values()), "by_host": agg_by_host},
        "linked_sessions": len(sid_owner),
        "notes": [
            "Steps 1-3 count anonymous sessions whose events fall in the window; steps 4+ count accounts created in the window, followed forward to now.",
            "Session-to-account conversion compares different units: email verification usually opens a new tab, which is a new anonymous session.",
            "Aggregate page views (Global Privacy Control, Do Not Track, declined or not-yet-given consent where prior consent is required) carry no session id and are not in the funnel.",
            "Accounts created in the last 7 days cannot have reached Day-7 yet.",
        ],
    }
