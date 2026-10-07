import os
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DEBUG", "true")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_lockerphycer.db"

# Tests assume a fresh database (e.g. idempotency keys must not already exist).
# A file left by an earlier run made a second run on the same checkout fail with
# IDEMPOTENCY_CONFLICT, so start every session from a clean file.
for _stale in ("test_lockerphycer.db", "test_lockerphycer.db-journal", "test_lockerphycer.db-wal", "test_lockerphycer.db-shm"):
    if os.path.exists(_stale):
        os.remove(_stale)

@pytest.fixture(autouse=True)
def mock_email_sender(monkeypatch):
    monkeypatch.setattr("apps.email.sender.send_verify_email", lambda *a, **kw: "mocked_msg_id")
    monkeypatch.setattr("apps.email.sender.send_password_reset", lambda *a, **kw: "mocked_msg_id")
    monkeypatch.setattr("apps.email.sender.send_welcome", lambda *a, **kw: "mocked_msg_id")
    # The auth router binds these names when it is first imported, which happens
    # at collection time for some test modules; patch its bindings as well.
    import apps.api.routers.auth as auth_router

    for name in ("send_verify_email", "send_password_reset", "send_welcome"):
        monkeypatch.setattr(auth_router, name, lambda *a, **kw: "mocked_msg_id")


@pytest.fixture(autouse=True)
def fresh_rate_limit_budget():
    """Every test starts with an empty rate-limit window.

    All tests share one client address, so without this the suite as a whole
    spends the 100-requests-per-minute budget and later tests fail with 429
    for reasons unrelated to what they check.
    """
    import gc

    from core.security.middleware import RateLimiter

    for candidate in gc.get_objects():
        if isinstance(candidate, RateLimiter):
            candidate.requests.clear()
    yield
