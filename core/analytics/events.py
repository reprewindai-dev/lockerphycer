"""Validation and privacy mode for incoming analytics batches.

Everything here is pure (no I/O) so the rules are unit-testable.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Allowlists
# ---------------------------------------------------------------------------

EVENT_NAMES = frozenset(
    {
        "page_view",
        "cta_click",
        "scroll_depth",
        "signup_started",
        "signup_submitted",
        "github_signup_clicked",
        "login_viewed",
        "login_succeeded",
        "vlink_connect_viewed",
        "page_exit",
    }
)

HOSTS = frozenset({"veklom.com", "os", "vlink"})

# Countries where Veklom's own jurisdiction profile (frontend
# lib/privacy/jurisdiction.ts) sets requiresPriorOptionalConsent: the EEA,
# the UK and China. Without an explicit opt-in, visitors there are counted in
# aggregate only (no session id).
EEA = frozenset(
    "AT BE BG HR CY CZ DK EE FI FR DE GR HU IS IE IT LV LI LT LU MT NL NO PL PT RO SK SI ES SE".split()
)
PRIOR_CONSENT_COUNTRIES = EEA | {"GB", "CN"}

MAX_BODY_BYTES = 16 * 1024
MAX_EVENTS_PER_BATCH = 25
MAX_PATH_LEN = 512

_SID_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_CTA_RE = re.compile(r"^[a-z0-9][a-z0-9:_./ -]{0,63}$")
_UTM_RE = re.compile(r"^[\w .:/+-]{1,100}$", re.UNICODE)
_TOKENISH_SEGMENT = re.compile(
    r"^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|(?=[^/]*\d)[A-Za-z0-9_.~-]{16,}|\d{4,})$",
    re.IGNORECASE,
)
_EMAILISH = re.compile(r"[^/@\s]+@[^/@\s]+")

UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")

# Per-event allowed props: name -> validator returning a clean value or None.


def _int_in(lo: int, hi: int):
    def check(v: Any):
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        iv = int(v)
        return iv if lo <= iv <= hi else None

    return check


def _one_of(*allowed):
    def check(v: Any):
        return v if v in allowed else None

    return check


def _cta(v: Any):
    if not isinstance(v, str):
        return None
    v = v.strip().lower()
    return v if _CTA_RE.match(v) else None


def _bool(v: Any):
    return v if isinstance(v, bool) else None


def _path_prop(v: Any):
    return normalize_path(v) if isinstance(v, str) else None


PROP_RULES: dict[str, dict[str, Any]] = {
    "page_view": {},
    "cta_click": {"cta": _cta, "href": _path_prop},
    "scroll_depth": {"depth": _one_of(50, 90)},
    "signup_started": {},
    "signup_submitted": {},
    "github_signup_clicked": {"accepted": _bool},
    "login_viewed": {},
    "login_succeeded": {"method": _one_of("password", "github")},
    "vlink_connect_viewed": {"state": _one_of("signed_in", "signed_out", "unknown")},
    "page_exit": {"engaged_s": _int_in(0, 86_400), "depth": _int_in(0, 100), "pages": _int_in(0, 10_000)},
}

REQUIRED_PROPS = {"cta_click": ("cta",), "scroll_depth": ("depth",)}


class ValidationError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Normalisers
# ---------------------------------------------------------------------------


def normalize_path(raw: str) -> str | None:
    """Path only: no query or fragment; token-like segments become ':id'."""
    if not isinstance(raw, str) or not raw.startswith("/") or raw.startswith("//"):
        return None
    path = raw.split("?", 1)[0].split("#", 1)[0]
    if len(path) > MAX_PATH_LEN * 2:
        return None
    segments = []
    for seg in path.split("/"):
        if seg and (_TOKENISH_SEGMENT.match(seg) or _EMAILISH.search(seg)):
            segments.append(":id")
        else:
            segments.append(seg)
    clean = "/".join(segments)[:MAX_PATH_LEN]
    return clean or "/"


def normalize_domain(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    d = raw.strip().lower().rstrip(".")
    if d.startswith("www."):
        d = d[4:]
    return d if _DOMAIN_RE.match(d) else None


def normalize_utm(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    v = raw.strip()[:100]
    if not v or _EMAILISH.search(v):
        return None
    return v if _UTM_RE.match(v) else None


def normalize_country(raw: str | None) -> str | None:
    c = (raw or "").strip().upper()
    if c in ("XX", "T1", "") or not re.fullmatch(r"[A-Z]{2}", c):
        return None
    return c


# ---------------------------------------------------------------------------
# Privacy mode
# ---------------------------------------------------------------------------


@dataclass
class PrivacyMode:
    mode: str  # "session" | "aggregate"
    reasons: list[str] = field(default_factory=list)
    country: str | None = None

    @property
    def aggregate(self) -> bool:
        return self.mode == "aggregate"


def decide_mode(headers: dict[str, str], consent: str | None) -> PrivacyMode:
    """Session-level measurement only when nothing asks us not to.

    headers: lower-cased request headers.
    consent: "granted" | "denied" | "unset" | None, from the site's own privacy
             choice (veklom_privacy_choices in localStorage).
    """
    reasons: list[str] = []
    if headers.get("sec-gpc", "").strip() == "1":
        reasons.append("global_privacy_control")
    if headers.get("dnt", "").strip() == "1":
        reasons.append("do_not_track")
    if consent == "denied":
        reasons.append("analytics_declined")
    country = normalize_country(headers.get("cf-ipcountry"))
    if country in PRIOR_CONSENT_COUNTRIES and consent != "granted":
        reasons.append("prior_consent_required")
    return PrivacyMode("aggregate" if reasons else "session", reasons, country)


# ---------------------------------------------------------------------------
# Batch parsing
# ---------------------------------------------------------------------------


@dataclass
class CleanEvent:
    event_name: str
    path: str
    props: dict
    client_ts: datetime | None
    referrer_domain: str | None = None
    utm: dict = field(default_factory=dict)


@dataclass
class CleanBatch:
    session_id: str | None
    host: str
    consent: str | None
    events: list[CleanEvent]
    dropped: int = 0


def _client_ts(v: Any, now: datetime) -> datetime | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        ts = datetime.fromtimestamp(v / 1000.0, tz=timezone.utc).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError):
        return None
    # Clock skew guard: keep only plausible client times.
    if abs((ts - now).total_seconds()) > 86_400:
        return None
    return ts


def parse_batch(raw: bytes, now: datetime | None = None) -> CleanBatch:
    """Validate a raw request body. Raises ValidationError on anything malformed."""
    now = now or datetime.utcnow()
    if len(raw) > MAX_BODY_BYTES:
        raise ValidationError("payload_too_large")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("invalid_json") from exc
    if not isinstance(body, dict):
        raise ValidationError("invalid_body")
    unknown_top = set(body) - {"v", "sid", "host", "consent", "events"}
    if unknown_top:
        raise ValidationError("unknown_fields")
    if body.get("v", 1) != 1:
        raise ValidationError("unsupported_version")

    sid = body.get("sid")
    if sid is not None and (not isinstance(sid, str) or not _SID_RE.match(sid)):
        raise ValidationError("invalid_sid")
    host = body.get("host")
    if host not in HOSTS:
        raise ValidationError("invalid_host")
    consent = body.get("consent")
    if consent is not None and consent not in ("granted", "denied", "unset"):
        raise ValidationError("invalid_consent")

    events = body.get("events")
    if not isinstance(events, list) or not events:
        raise ValidationError("no_events")
    if len(events) > MAX_EVENTS_PER_BATCH:
        raise ValidationError("too_many_events")

    clean: list[CleanEvent] = []
    for ev in events:
        if not isinstance(ev, dict):
            raise ValidationError("invalid_event")
        name = ev.get("name")
        if name not in EVENT_NAMES:
            raise ValidationError("unknown_event")
        path = normalize_path(ev.get("path"))
        if path is None:
            raise ValidationError("invalid_path")
        props_in = ev.get("props") or {}
        if not isinstance(props_in, dict):
            raise ValidationError("invalid_props")
        rules = PROP_RULES[name]
        props = {}
        for key, check in rules.items():
            if key in props_in:
                val = check(props_in[key])
                if val is not None:
                    props[key] = val
        for key in REQUIRED_PROPS.get(name, ()):
            if key not in props:
                raise ValidationError(f"missing_{key}")
        ref = normalize_domain(props_in.get("referrer_domain")) if name == "page_view" else None
        utm = {}
        if name == "page_view":
            for key in UTM_KEYS:
                val = normalize_utm(props_in.get(key))
                if val:
                    utm[key] = val
        clean.append(CleanEvent(name, path, props, _client_ts(ev.get("ts"), now), ref, utm))

    if sid is None and any(e.event_name != "page_view" for e in clean):
        # Without a session id only aggregate page views are meaningful.
        kept = [e for e in clean if e.event_name == "page_view"]
        return CleanBatch(None, host, consent, kept, dropped=len(clean) - len(kept))
    return CleanBatch(sid, host, consent, clean)


def apply_mode(batch: CleanBatch, mode: PrivacyMode) -> CleanBatch:
    """Aggregate mode: no session id, page_view only, no referrer or campaign."""
    if not mode.aggregate:
        return batch
    kept = [
        CleanEvent(e.event_name, e.path, {}, None, None, {})
        for e in batch.events
        if e.event_name == "page_view"
    ]
    return CleanBatch(None, batch.host, batch.consent, kept, batch.dropped + len(batch.events) - len(kept))


# ---------------------------------------------------------------------------
# Rate limiting (in memory; the key is a salted hash that is never persisted)
# ---------------------------------------------------------------------------


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: int = 60, max_keys: int = 50_000):
        self.limit = limit
        self.window = timedelta(seconds=window_s)
        self.max_keys = max_keys
        self._hits: dict[str, list[datetime]] = {}

    def allow(self, key: str, now: datetime | None = None, cost: int = 1) -> bool:
        now = now or datetime.utcnow()
        cutoff = now - self.window
        hits = [t for t in self._hits.get(key, ()) if t > cutoff]
        if len(hits) + cost > self.limit:
            self._hits[key] = hits
            return False
        hits.extend([now] * cost)
        self._hits[key] = hits
        if len(self._hits) > self.max_keys:
            for k in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
                self._hits.pop(k, None)
        return True

    def reset(self) -> None:
        self._hits.clear()


def batch_limit() -> int:
    return _int_env("ANALYTICS_BATCHES_PER_MINUTE", 60)


def event_limit() -> int:
    return _int_env("ANALYTICS_EVENTS_PER_MINUTE", 600)
