"""First-party funnel analytics: validation, rate limit, privacy (GPC/DNT/consent),
session link through activation_events, funnel math and the admin endpoint."""

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DEBUG", "true")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_lockerphycer.db"

from core.analytics import events as E  # noqa: E402
from core.analytics import funnel as F  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def _sid() -> str:
    return uuid.uuid4().hex + uuid.uuid4().hex[:8]


def _ip() -> str:
    return f"10.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"


def _batch(events, sid=None, host="veklom.com", **extra):
    body = {"v": 1, "host": host, "events": events, **extra}
    if sid is not None:
        body["sid"] = sid
    return body


def _pv(path="/", **props):
    return {"name": "page_view", "path": path, "ts": int(datetime.utcnow().timestamp() * 1000), "props": props}


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from apps.api.main import app
    from apps.api.routers import analytics as A

    A.batch_limiter.reset()
    A.event_limiter.reset()
    A.link_limiter.reset()
    with TestClient(app) as c:
        yield c


async def _rows_for(sid=None, path=None):
    from sqlalchemy import select

    from core.analytics.models import AnalyticsEvent
    from core.database.database import SessionLocal

    async with SessionLocal() as db:
        q = select(AnalyticsEvent)
        if sid is not None:
            q = q.where(AnalyticsEvent.session_id == sid)
        if path is not None:
            q = q.where(AnalyticsEvent.path == path)
        return list((await db.execute(q)).scalars())


def _post(client, body, **headers):
    h = {"content-type": "text/plain;charset=UTF-8", "x-forwarded-for": _ip(), "origin": "https://veklom.com"}
    h.update({k.replace("_", "-"): v for k, v in headers.items()})
    return client.post("/api/v1/analytics/events", content=json.dumps(body), headers=h)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_accepts_valid_batch_and_stores_no_ip_or_user_agent(client):
    sid = _sid()
    r = _post(client, _batch([
        _pv("/pricing?email=a@b.com#x", referrer_domain="www.Google.com", utm_source="newsletter"),
        {"name": "cta_click", "path": "/", "props": {"cta": "start-free-vlink", "href": "/signup?returnTo=%2Fvlink"}},
        {"name": "scroll_depth", "path": "/", "props": {"depth": 50}},
    ], sid=sid), user_agent="Mozilla/5.0 test")
    assert r.status_code == 200, r.text
    assert r.json() == {"accepted": 3, "dropped": 0, "mode": "session"}
    rows = run(_rows_for(sid=sid))
    assert len(rows) == 3
    pv = next(x for x in rows if x.event_name == "page_view")
    assert pv.path == "/pricing"  # query and fragment never stored
    assert pv.referrer_domain == "google.com" and pv.utm_source == "newsletter"
    cta = next(x for x in rows if x.event_name == "cta_click")
    assert cta.props == {"cta": "start-free-vlink", "href": "/signup"}
    from core.analytics.models import AnalyticsEvent

    columns = {c.name for c in AnalyticsEvent.__table__.columns}
    assert not columns & {"ip", "ip_address", "user_agent", "email", "user_id", "cookie"}


@pytest.mark.parametrize(
    "body,status,detail",
    [
        (_batch([{"name": "purchase", "path": "/"}], sid="a" * 22), 400, "unknown_event"),
        (_batch([{"name": "page_view", "path": "https://evil.example/"}], sid="a" * 22), 400, "invalid_path"),
        (_batch([_pv()] * 26, sid="a" * 22), 400, "too_many_events"),
        (_batch([], sid="a" * 22), 400, "no_events"),
        (_batch([_pv()], sid="short"), 400, "invalid_sid"),
        (_batch([_pv()], sid="a" * 22, host="evil.com"), 400, "invalid_host"),
        (_batch([_pv()], sid="a" * 22, email="x@y.z"), 400, "unknown_fields"),
        (_batch([{"name": "cta_click", "path": "/", "props": {}}], sid="a" * 22), 400, "missing_cta"),
        (_batch([{"name": "scroll_depth", "path": "/", "props": {"depth": 37}}], sid="a" * 22), 400, "missing_depth"),
    ],
)
def test_rejects_invalid_batches(client, body, status, detail):
    r = _post(client, body)
    assert r.status_code == status, r.text
    assert r.json()["error"]["message"] == detail


def test_rejects_oversized_payload(client):
    big = _batch([_pv("/" + "a" * 400, utm_content="x" * 90)] * 25, sid="b" * 22)
    raw = json.dumps(big) + " " * E.MAX_BODY_BYTES
    r = client.post("/api/v1/analytics/events", content=raw,
                    headers={"x-forwarded-for": _ip(), "origin": "https://veklom.com"})
    assert r.status_code == 413


def test_rejects_invalid_json_and_foreign_origin(client):
    r = client.post("/api/v1/analytics/events", content="{not json",
                    headers={"x-forwarded-for": _ip(), "origin": "https://veklom.com"})
    assert r.status_code == 400
    r = _post(client, _batch([_pv()], sid=_sid()), origin="https://evil.example")
    assert r.status_code == 403
    for origin in ("https://os.veklom.com", "https://vlink.veklom.com"):
        assert _post(client, _batch([_pv()], sid=_sid(), host="vlink"), origin=origin).status_code == 200


def test_unknown_props_dropped_and_paths_scrubbed():
    batch = E.parse_batch(json.dumps(_batch([
        {"name": "page_view", "path": "/reset-password/eyJhbGciOiJIUzI1NiJ9abc123/", "props": {"email": "a@b.c"}},
        {"name": "page_view", "path": "/pair/3f2a9c1e-1111-4222-8333-444455556666/ada@example.com"},
        {"name": "page_view", "path": "/acceptable-use/"},
        {"name": "login_succeeded", "path": "/login", "props": {"method": "password", "email": "a@b.c"}},
    ], sid="c" * 22)).encode())
    paths = [e.path for e in batch.events]
    assert paths == ["/reset-password/:id/", "/pair/:id/:id", "/acceptable-use/", "/login"]
    assert batch.events[0].props == {} and batch.events[3].props == {"method": "password"}


def test_without_session_id_only_page_views_are_kept():
    batch = E.parse_batch(json.dumps(_batch([_pv(), {"name": "signup_started", "path": "/signup"}])).encode())
    assert [e.event_name for e in batch.events] == ["page_view"] and batch.dropped == 1


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


def test_batch_rate_limit_per_client(client, monkeypatch):
    from apps.api.routers import analytics as A

    monkeypatch.setattr(A, "batch_limiter", E.SlidingWindowLimiter(3))
    ip = _ip()
    codes = [_post(client, _batch([_pv()], sid=_sid()), x_forwarded_for=ip).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    # Another client is unaffected.
    assert _post(client, _batch([_pv()], sid=_sid()), x_forwarded_for=_ip()).status_code == 200


def test_event_rate_limit_counts_events(client, monkeypatch):
    from apps.api.routers import analytics as A

    monkeypatch.setattr(A, "event_limiter", E.SlidingWindowLimiter(30))
    ip = _ip()
    assert _post(client, _batch([_pv()] * 25, sid=_sid()), x_forwarded_for=ip).status_code == 200
    r = _post(client, _batch([_pv()] * 10, sid=_sid()), x_forwarded_for=ip)
    assert r.status_code == 429 and r.headers["retry-after"] == "60"


def test_limiter_window_slides():
    lim = E.SlidingWindowLimiter(2, window_s=60)
    t0 = datetime(2026, 9, 30, 12)
    assert lim.allow("k", t0) and lim.allow("k", t0)
    assert not lim.allow("k", t0 + timedelta(seconds=59))
    assert lim.allow("k", t0 + timedelta(seconds=61))


# ---------------------------------------------------------------------------
# Global Privacy Control, DNT and consent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("header", [{"sec_gpc": "1"}, {"dnt": "1"}])
def test_gpc_and_dnt_store_aggregate_page_views_only(client, header):
    sid = _sid()
    path = f"/gpc-{uuid.uuid4().hex[:8]}"
    r = _post(client, _batch([
        _pv(path, referrer_domain="news.ycombinator.com", utm_campaign="launch"),
        {"name": "cta_click", "path": path, "props": {"cta": "nav:pricing"}},
        {"name": "page_exit", "path": path, "props": {"engaged_s": 40}},
    ], sid=sid), **header)
    assert r.status_code == 200
    assert r.json()["mode"] == "aggregate" and r.json()["accepted"] == 1 and r.json()["dropped"] == 2
    assert run(_rows_for(sid=sid)) == []
    rows = run(_rows_for(path=path))
    assert len(rows) == 1
    row = rows[0]
    assert row.event_name == "page_view" and row.session_id is None and row.aggregate_only is True
    assert row.referrer_domain is None and row.utm_campaign is None and row.props == {}


def test_config_endpoint_reports_mode(client):
    ok = client.get("/api/v1/analytics/config")
    assert ok.status_code == 200 and ok.json() == {"mode": "session", "reasons": []}
    assert "set-cookie" not in ok.headers
    gpc = client.get("/api/v1/analytics/config", headers={"sec-gpc": "1"}).json()
    assert gpc["mode"] == "aggregate" and "global_privacy_control" in gpc["reasons"]
    eu = client.get("/api/v1/analytics/config", headers={"cf-ipcountry": "DE"}).json()
    assert eu == {"mode": "aggregate", "reasons": ["prior_consent_required"]}
    eu_ok = client.get("/api/v1/analytics/config?consent=granted", headers={"cf-ipcountry": "DE"}).json()
    assert eu_ok["mode"] == "session"
    declined = client.get("/api/v1/analytics/config?consent=denied").json()
    assert declined["mode"] == "aggregate"


def test_prior_consent_country_without_opt_in_is_aggregate(client):
    sid = _sid()
    r = _post(client, _batch([_pv("/eu"), {"name": "signup_started", "path": "/signup"}], sid=sid), cf_ipcountry="FR")
    assert r.json()["mode"] == "aggregate" and run(_rows_for(sid=sid)) == []
    sid2 = _sid()
    r = _post(client, _batch([_pv("/eu")], sid=sid2, consent="granted"), cf_ipcountry="FR")
    assert r.json()["mode"] == "session"
    rows = run(_rows_for(sid=sid2))
    assert rows and rows[0].country == "FR"


def test_decide_mode_rules():
    assert E.decide_mode({}, None).mode == "session"
    assert E.decide_mode({"cf-ipcountry": "US"}, "unset").mode == "session"
    assert E.decide_mode({"cf-ipcountry": "GB"}, None).reasons == ["prior_consent_required"]
    assert E.decide_mode({"sec-gpc": "1", "cf-ipcountry": "US"}, "granted").mode == "aggregate"


def test_bot_user_agents_are_ignored(client):
    sid = _sid()
    r = _post(client, _batch([_pv()], sid=sid), user_agent="Googlebot/2.1")
    assert r.json()["mode"] == "ignored" and run(_rows_for(sid=sid)) == []


# ---------------------------------------------------------------------------
# Session link (activation_events only)
# ---------------------------------------------------------------------------


def _seed_user(role="user", created_at=None, workspace=True):
    from core.database.database import Base, SessionLocal, engine
    from core.security.auth import create_access_token, create_refresh_token, get_password_hash
    from db.models import SubscriptionTier, User, UserRole, UserSession, UserStatus, Workspace

    email = f"an-{uuid.uuid4().hex}@example.com"
    ws_id = str(uuid.uuid4())

    async def seed():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with SessionLocal() as db:
            user = User(email=email, username=f"an-{uuid.uuid4().hex[:10]}",
                        hashed_password=get_password_hash("CorrectHorseBatteryStaple1"),
                        role=UserRole.ADMIN if role == "admin" else UserRole.USER, status=UserStatus.ACTIVE,
                        created_at=created_at or datetime.utcnow())
            db.add(user)
            await db.flush()
            token = create_access_token({"sub": email})
            db.add(UserSession(user_id=user.id, session_token=token,
                               refresh_token=create_refresh_token({"sub": email}),
                               expires_at=datetime.utcnow() + timedelta(hours=1)))
            if workspace:
                db.add(Workspace(id=ws_id, owner_id=email, name="w", slug=f"w-{uuid.uuid4().hex[:10]}",
                                 tier=SubscriptionTier.FREE))
            await db.commit()
            return token, user.id

    token, uid = run(seed())
    return token, uid, ws_id


async def _link_rows(sid):
    from sqlalchemy import select

    from core.database.database import SessionLocal
    from db.models import ActivationEvent

    async with SessionLocal() as db:
        return list((await db.execute(select(ActivationEvent).where(ActivationEvent.ref == sid))).scalars())


def test_link_writes_one_activation_event(client):
    token, uid, ws_id = _seed_user()
    sid = _sid()
    h = {"Authorization": f"Bearer {token}", "x-forwarded-for": _ip()}
    assert client.post("/api/v1/analytics/link", json={"sid": sid}).status_code == 401
    r = client.post("/api/v1/analytics/link", json={"sid": sid}, headers=h)
    assert r.status_code == 200 and r.json() == {"linked": True, "new": True}
    again = client.post("/api/v1/analytics/link", json={"sid": sid}, headers=h)
    assert again.json() == {"linked": True, "new": False}
    rows = run(_link_rows(sid))
    assert len(rows) == 1
    ev = rows[0]
    assert ev.event_name == "analytics_session_linked" and ev.workspace_id == ws_id
    assert ev.user_id == uid and ev.source == "analytics"


def test_link_refused_under_gpc(client):
    token, _uid, _ws = _seed_user()
    sid = _sid()
    r = client.post("/api/v1/analytics/link", json={"sid": sid},
                    headers={"Authorization": f"Bearer {token}", "sec-gpc": "1", "x-forwarded-for": _ip()})
    assert r.json() == {"linked": False, "reasons": ["global_privacy_control"]}
    assert run(_link_rows(sid)) == []


# ---------------------------------------------------------------------------
# Funnel math
# ---------------------------------------------------------------------------

T0 = datetime(2026, 3, 2, 9, 0, 0)


def _ev(sid, name, sec, path="/", ref=None, **props):
    return F.SessionEvent(sid, name, path, T0 + timedelta(seconds=sec), ref, props)


def test_engagement_and_bounce():
    events = [
        _ev("a", "page_view", 0, "/", "google.com"),              # bounce: 1 page, 5 s
        _ev("a", "page_exit", 5, "/", engaged_s=5),
        _ev("b", "page_view", 0, "/"), _ev("b", "page_view", 9, "/pricing"),   # engaged: 2 pages
        _ev("c", "page_view", 0, "/vlink", "news.ycombinator.com"),
        _ev("c", "page_exit", 45, "/vlink", engaged_s=31),                      # engaged: 31 s visible
        _ev("d", "page_view", 0, "/vlink", "news.ycombinator.com"),
        _ev("d", "cta_click", 3, "/vlink", cta="start-free-vlink"),            # engaged: CTA
        _ev("e", "page_view", 0, "/"), _ev("e", "scroll_depth", 2, "/", depth=90),  # bounce: scroll only
        _ev("f", "signup_started", 0, "/signup"),                               # no page view: not a visitor
    ]
    s = F.summarize_sessions(events)
    assert F.session_counts(s) == {"visitor": 5, "engaged": 3, "signup_started": 0}
    by_landing = {r["landing_path"]: r for r in F.bounce_table(s.values(), "landing_path")}
    assert by_landing["/"] == {"landing_path": "/", "sessions": 3, "bounced": 2, "bounce_rate": 0.6667}
    assert by_landing["/vlink"]["bounce_rate"] == 0.0
    by_ref = {r["referrer"]: r for r in F.bounce_table(s.values(), "referrer")}
    assert by_ref["google.com"]["bounced"] == 1 and by_ref["(direct)"]["sessions"] == 2


def test_build_steps_conversion_and_drop():
    counts = {k: 0 for k, *_ in F.STEPS}
    counts.update(visitor=200, engaged=80, signup_started=20, account_created=10, email_verified=5)
    steps = F.build_steps(counts)
    assert [s["key"] for s in steps][:3] == ["visitor", "engaged", "signup_started"]
    assert len(steps) == 14
    eng = steps[1]
    assert eng["conversion_from_previous"] == 0.4 and eng["drop_from_previous"] == 0.6
    assert steps[4]["conversion_from_first"] == 0.025
    assert steps[0]["conversion_from_previous"] is None
    # After a zero step, conversion is undefined rather than a division error.
    assert steps[6]["conversion_from_previous"] is None


def test_account_steps():
    u1 = F.CohortUser("u1", "one@example.com", T0)
    u2 = F.CohortUser("u2", "two@example.com", T0)
    u3 = F.CohortUser("u3", "three@example.com", T0)
    ws = {"one@example.com": ["w1"], "two@example.com": ["w2"]}
    A = F.Activation
    acts = [
        A("signup_completed", "u1", None, T0), A("email_verified", "u1", None, T0 + timedelta(minutes=5)),
        A("system_connected", None, "w1", T0 + timedelta(hours=1)),
        A("first_governed_execution", None, "w1", T0 + timedelta(hours=2)),
        A("first_receipt_verified", None, "w1", T0 + timedelta(hours=2)),
        A("welcome_ended", None, "w1", T0 + timedelta(days=14)),
        A("trial_converted", None, "w1", T0 + timedelta(days=15)),
        A("welcome_ended", None, "w2", T0 + timedelta(days=14)),               # no live dependency
        A("system_connected", None, "w2", T0 + timedelta(days=20)),            # connected only after Welcome
        A("signup_completed", "u3", None, T0),                                 # never verified
    ]
    activity = {
        "u1": [T0 + timedelta(minutes=10), T0 + timedelta(days=6, hours=1)],   # day 1 and day 7
        "u2": [T0 + timedelta(hours=30)],                                      # day 2 (GitHub: no email event)
    }
    linked = {"u1": [_ev("s1", "vlink_connect_viewed", 700, "/vlink/connect/")]}
    c = F.account_steps([u1, u2, u3], ws, acts, activity, linked)
    assert c == {
        "account_created": 3, "email_verified": 2, "logged_in": 2, "vlink_connect_viewed": 1,
        "system_connected": 2, "first_governed_execution": 1, "first_receipt": 1,
        "day2_return": 2, "day7_active": 1, "welcome_ended_live": 1, "converted": 1,
    }


def test_funnel_endpoint_admin_only_and_counts(client):
    from core.analytics.models import AnalyticsEvent
    from core.database.database import SessionLocal
    from db.models import ActivationEvent

    token_user, _u, _w = _seed_user()
    token_admin, _a, _aw = _seed_user(role="admin")
    window_start = datetime(2025, 4, 1)
    token_new, uid_new, ws_new = _seed_user(created_at=window_start + timedelta(days=2))
    sid_a, sid_b, sid_c = _sid(), _sid(), _sid()

    async def seed():
        async with SessionLocal() as db:
            t = window_start + timedelta(days=1)
            rows = [
                (sid_a, "page_view", "/", t, "google.com", {}),
                (sid_b, "page_view", "/", t, None, {}), (sid_b, "page_view", "/pricing", t, None, {}),
                (sid_b, "signup_started", "/signup", t, None, {}),
                (sid_c, "page_view", "/vlink/connect/", t + timedelta(days=2), None, {}),
                (sid_c, "vlink_connect_viewed", "/vlink/connect/", t + timedelta(days=2), None, {}),
            ]
            for sid, name, path, at, ref, props in rows:
                db.add(AnalyticsEvent(event_name=name, session_id=sid, host="veklom.com", path=path,
                                      referrer_domain=ref, props=props, aggregate_only=False, received_at=at))
            db.add(AnalyticsEvent(event_name="page_view", session_id=None, host="os", path="/os", props={},
                                  aggregate_only=True, received_at=t))
            db.add(ActivationEvent(event_name="analytics_session_linked", user_id=uid_new, workspace_id=ws_new,
                                   source="analytics", ref=sid_c, dedupe_key=f"analytics_session_linked:{sid_c}",
                                   details={}, created_at=t + timedelta(days=2)))
            db.add(ActivationEvent(event_name="system_connected", workspace_id=ws_new, source="lockerphycer",
                                   dedupe_key=f"system_connected:ws:{ws_new}", details={},
                                   created_at=t + timedelta(days=2)))
            await db.commit()

    run(seed())
    q = "/api/v1/analytics/funnel?from=2025-04-01&to=2025-04-30"
    assert client.get(q).status_code == 401
    assert client.get(q, headers={"Authorization": f"Bearer {token_user}"}).status_code == 403
    r = client.get(q, headers={"Authorization": f"Bearer {token_admin}"})
    assert r.status_code == 200, r.text
    body = r.json()
    steps = {s["key"]: s for s in body["steps"]}
    assert steps["visitor"]["count"] == 3 and steps["visitor"]["unit"] == "sessions"
    assert steps["engaged"]["count"] == 1 and steps["signup_started"]["count"] == 1
    assert steps["account_created"]["count"] == 1 and steps["account_created"]["unit"] == "accounts"
    assert steps["logged_in"]["count"] == 1 and steps["vlink_connect_viewed"]["count"] == 1
    assert steps["system_connected"]["count"] == 1 and steps["converted"]["count"] == 0
    assert steps["engaged"]["conversion_from_previous"] == round(1 / 3, 4)
    assert body["aggregate_page_views"] == {"total": 1, "by_host": {"os": 1}}
    assert body["bounce"]["sessions"] == 3 and body["bounce"]["bounced"] == 2
    assert body["linked_sessions"] == 1
    assert client.get("/api/v1/analytics/funnel?from=2025-05-01&to=2025-04-01",
                      headers={"Authorization": f"Bearer {token_admin}"}).status_code == 400
