"""analytics_events: anonymous first-party page and funnel events.

Privacy contract (mirrored on veklom.com/privacy and /cookies):
  * no IP address, user agent, cookie, email, name or account id is stored;
  * ``session_id`` is a random per-tab value the browser keeps in
    sessionStorage; it is NULL for aggregate-only events (Global Privacy
    Control, Do Not Track, no consent where prior consent is required);
  * ``country`` is the two-letter country supplied by the edge (CF-IPCountry),
    never derived from a stored IP;
  * the only link between a session and an account is an
    ``analytics_session_linked`` row in activation_events, written after sign-in.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from core.database.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    event_name: Mapped[str] = mapped_column(String(40), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), index=True)
    host: Mapped[str] = mapped_column(String(16), index=True)
    path: Mapped[str] = mapped_column(String(512))
    referrer_domain: Mapped[str | None] = mapped_column(String(253))
    utm_source: Mapped[str | None] = mapped_column(String(100))
    utm_medium: Mapped[str | None] = mapped_column(String(100))
    utm_campaign: Mapped[str | None] = mapped_column(String(100))
    utm_term: Mapped[str | None] = mapped_column(String(100))
    utm_content: Mapped[str | None] = mapped_column(String(100))
    props: Mapped[dict] = mapped_column(JSON, default=dict)
    country: Mapped[str | None] = mapped_column(String(2))
    aggregate_only: Mapped[bool] = mapped_column(Boolean, default=False)
    client_ts: Mapped[datetime | None] = mapped_column(DateTime)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
