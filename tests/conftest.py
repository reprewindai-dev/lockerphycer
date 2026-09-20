import os
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")
os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("DEBUG", "true")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_lockerphycer.db"

@pytest.fixture(autouse=True)
def mock_email_sender(monkeypatch):
    monkeypatch.setattr("apps.email.sender.send_verify_email", lambda *a, **kw: "mocked_msg_id")
    monkeypatch.setattr("apps.email.sender.send_password_reset", lambda *a, **kw: "mocked_msg_id")
    monkeypatch.setattr("apps.email.sender.send_welcome", lambda *a, **kw: "mocked_msg_id")
