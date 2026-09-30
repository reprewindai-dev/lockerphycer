"""Funnel math. Pure functions over plain rows so the arithmetic is testable.

Two units are joined in one funnel, and every step says which one it counts:
  * sessions  - anonymous per-tab sessions whose first event falls in the
                window (analytics_events with a session id);
  * accounts  - users whose account was created in the window (users.created_at),
                followed through activation_events, user_sessions and linked
                analytics sessions.
The session-to-account step is therefore a ratio of different units, not a
tracked per-person conversion: a visitor usually verifies their email in a new
tab, which is a new anonymous session by design.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable

ENGAGED_SECONDS = 30
INTERACTION_EVENTS = frozenset(
    {"cta_click", "signup_started", "signup_submitted", "github_signup_clicked", "login_succeeded"}
)
SIGNUP_START_EVENTS = frozenset({"signup_started", "signup_submitted", "github_signup_clicked"})
LIVE_DEPENDENCY_EVENTS = frozenset({"system_connected", "production_workflow_connected"})

STEPS: list[tuple[str, str, str, str]] = [
    ("visitor", "Visitor", "sessions", "Anonymous sessions with at least one page view."),
    ("engaged", "Engaged", "sessions",
     "Sessions with 2+ page views, a CTA click or signup/login interaction, or 30+ s of visible time on a page."),
    ("signup_started", "Signup started", "sessions",
     "Sessions that focused the signup form, submitted it, or clicked 'Sign up with GitHub'."),
    ("account_created", "Account created", "accounts", "Users whose account was created in the window (users.created_at)."),
    ("email_verified", "Email verified", "accounts",
     "Cohort users with an email_verified activation event, or who have signed in (password sign-in requires a verified address; GitHub supplies a verified address)."),
    ("logged_in", "Logged in", "accounts", "Cohort users with at least one sign-in session (user_sessions)."),
    ("vlink_connect_viewed", "VLink connect viewed", "accounts",
     "Cohort users with a linked analytics session that viewed VLink connect."),
    ("system_connected", "System connected", "accounts", "Cohort users whose workspace has a system_connected activation event."),
    ("first_governed_execution", "First governed execution", "accounts", "first_governed_execution activation event."),
    ("first_receipt", "First receipt", "accounts", "first_receipt_verified activation event."),
    ("day2_return", "Day-2 return", "accounts",
     "Any sign-in, authenticated request or linked page view on day 2 or later (24 h or more after account creation)."),
    ("day7_active", "Day-7 active", "accounts", "The same activity on day 7 or later (6 x 24 h or more after account creation)."),
    ("welcome_ended_live", "Welcome ended with a live dependency", "accounts",
     "welcome_ended, with system_connected or production_workflow_connected recorded before it."),
    ("converted", "Converted", "accounts", "trial_converted activation event."),
]


@dataclass
class SessionEvent:
    session_id: str
    event_name: str
    path: str
    received_at: datetime
    referrer_domain: str | None = None
    props: dict = field(default_factory=dict)


@dataclass
class SessionSummary:
    session_id: str
    first_at: datetime
    landing_path: str | None = None
    referrer: str = "(direct)"
    pages: int = 0
    max_engaged_s: int = 0
    names: set = field(default_factory=set)

    @property
    def engaged(self) -> bool:
        return (
            self.pages >= 2
            or bool(self.names & INTERACTION_EVENTS)
            or self.max_engaged_s >= ENGAGED_SECONDS
        )

    @property
    def visitor(self) -> bool:
        return "page_view" in self.names


def summarize_sessions(events: Iterable[SessionEvent]) -> dict[str, SessionSummary]:
    out: dict[str, SessionSummary] = {}
    for ev in sorted(events, key=lambda e: e.received_at):
        s = out.get(ev.session_id)
        if s is None:
            s = out[ev.session_id] = SessionSummary(ev.session_id, ev.received_at)
        s.names.add(ev.event_name)
        if ev.event_name == "page_view":
            if s.pages == 0:
                s.landing_path = ev.path
                s.referrer = ev.referrer_domain or "(direct)"
            s.pages += 1
        elif ev.event_name == "page_exit":
            try:
                s.max_engaged_s = max(s.max_engaged_s, int((ev.props or {}).get("engaged_s") or 0))
            except (TypeError, ValueError):
                pass
    return out


def bounce_table(sessions: Iterable[SessionSummary], key: str, limit: int = 50) -> list[dict]:
    """Bounce = a visitor session that never became engaged."""
    groups: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for s in sessions:
        if not s.visitor:
            continue
        k = (s.landing_path or "(unknown)") if key == "landing_path" else s.referrer
        groups[k][0] += 1
        if not s.engaged:
            groups[k][1] += 1
    rows = [
        {key: k, "sessions": n, "bounced": b, "bounce_rate": round(b / n, 4) if n else None}
        for k, (n, b) in groups.items()
    ]
    rows.sort(key=lambda r: (-r["sessions"], r[key]))
    return rows[:limit]


@dataclass
class CohortUser:
    id: str
    email: str
    created_at: datetime


@dataclass
class Activation:
    event_name: str
    user_id: str | None
    workspace_id: str | None
    created_at: datetime
    ref: str | None = None


def _day_index(created: datetime, t: datetime) -> int:
    return int((t - created) // timedelta(days=1)) + 1


def account_steps(
    cohort: list[CohortUser],
    workspaces_by_email: dict[str, list[str]],
    activations: list[Activation],
    activity: dict[str, list[datetime]],
    linked_session_events: dict[str, list[SessionEvent]],
) -> dict[str, int]:
    """Count cohort users reaching each account-level step.

    activity: user_id -> timestamps of sign-ins / authenticated requests.
    linked_session_events: user_id -> events of analytics sessions linked to them.
    """
    by_user: dict[str, list[Activation]] = defaultdict(list)
    by_ws: dict[str, list[Activation]] = defaultdict(list)
    for a in activations:
        if a.user_id:
            by_user[a.user_id].append(a)
        if a.workspace_id:
            by_ws[a.workspace_id].append(a)

    counts = {k: 0 for k, *_ in STEPS[3:]}
    for u in cohort:
        events = list(by_user.get(u.id, ()))
        seen_ids = {id(a) for a in events}
        for ws in workspaces_by_email.get((u.email or "").lower(), ()):
            for a in by_ws.get(ws, ()):
                if id(a) not in seen_ids:
                    events.append(a)
                    seen_ids.add(id(a))
        names = {a.event_name for a in events}
        first = {}
        for a in sorted(events, key=lambda a: a.created_at):
            first.setdefault(a.event_name, a.created_at)

        user_activity = list(activity.get(u.id, ()))
        linked = linked_session_events.get(u.id, [])
        user_activity.extend(e.received_at for e in linked)
        signed_in = bool(activity.get(u.id))

        counts["account_created"] += 1
        if "email_verified" in names or signed_in:
            counts["email_verified"] += 1
        if signed_in:
            counts["logged_in"] += 1
        if any(e.event_name == "vlink_connect_viewed" for e in linked):
            counts["vlink_connect_viewed"] += 1
        if "system_connected" in names:
            counts["system_connected"] += 1
        if "first_governed_execution" in names:
            counts["first_governed_execution"] += 1
        if "first_receipt_verified" in names:
            counts["first_receipt"] += 1
        days = [_day_index(u.created_at, t) for t in user_activity if t >= u.created_at]
        if any(d >= 2 for d in days):
            counts["day2_return"] += 1
        if any(d >= 7 for d in days):
            counts["day7_active"] += 1
        ended = first.get("welcome_ended")
        if ended is not None and any(
            first.get(n) is not None and first[n] <= ended for n in LIVE_DEPENDENCY_EVENTS
        ):
            counts["welcome_ended_live"] += 1
        if "trial_converted" in names:
            counts["converted"] += 1
    return counts


def build_steps(counts: dict[str, int]) -> list[dict]:
    out = []
    prev = None
    first = None
    for key, label, unit, definition in STEPS:
        n = int(counts.get(key, 0))
        if first is None:
            first = n
        conv = round(n / prev, 4) if prev else None
        out.append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "count": n,
                "conversion_from_previous": conv,
                "drop_from_previous": round(1 - conv, 4) if conv is not None else None,
                "conversion_from_first": round(n / first, 4) if first else None,
                "definition": definition,
            }
        )
        prev = n
    return out


def session_counts(summaries: dict[str, SessionSummary]) -> dict[str, int]:
    visitors = [s for s in summaries.values() if s.visitor]
    return {
        "visitor": len(visitors),
        "engaged": sum(1 for s in visitors if s.engaged),
        "signup_started": sum(1 for s in visitors if s.names & SIGNUP_START_EVENTS),
    }


def session_event_breakdown(summaries: dict[str, SessionSummary]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for s in summaries.values():
        for n in s.names:
            out[n] += 1
    return dict(sorted(out.items()))
