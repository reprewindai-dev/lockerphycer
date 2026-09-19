from core.config.settings import settings
from core.security.middleware import is_allowed_origin


def test_known_local_and_public_origins_are_allowed(monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://veklom.dev")
    monkeypatch.delenv("LOCKERPHYCER_CORS_ORIGINS", raising=False)

    assert is_allowed_origin("http://localhost:3002") is True
    assert is_allowed_origin("http://127.0.0.1:3002") is True
    assert is_allowed_origin("https://veklom.dev") is True


def test_origin_matching_is_exact_not_substring(monkeypatch):
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://veklom.dev")
    monkeypatch.delenv("LOCKERPHYCER_CORS_ORIGINS", raising=False)

    assert is_allowed_origin("https://veklom.dev.attacker.example") is False
    assert is_allowed_origin("https://attacker.example/?next=https://veklom.dev") is False


def test_explicit_origin_extension_is_supported(monkeypatch):
    monkeypatch.setenv("LOCKERPHYCER_CORS_ORIGINS", "https://preview.veklom.com")

    assert is_allowed_origin("https://preview.veklom.com/") is True
