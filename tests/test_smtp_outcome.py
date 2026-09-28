import smtplib
import pytest
from apps.email import sender


def test_ambiguous_data_does_not_fall_back(monkeypatch):
    calls = []
    class SMTP:
        def __init__(self, host, *args, **kwargs):
            calls.append(host)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def ehlo(self): pass
        def starttls(self, **kwargs): pass
        def login(self, *args): pass
        def send_message(self, msg): raise TimeoutError()
    monkeypatch.setattr(sender.smtplib, 'SMTP', SMTP)
    monkeypatch.setattr(sender.settings, 'SMTP_HOST', 'primary.invalid')
    monkeypatch.setattr(sender.settings, 'SMTP_SSL', False)
    monkeypatch.setattr(sender.settings, 'EMAIL_TRANSPORT', 'smtp')
    monkeypatch.setattr(sender.settings, 'SMTP_FALLBACK_HOST', 'fallback.invalid')
    with pytest.raises(sender.DeliveryIndeterminate):
        sender._send('controlled@example.invalid', 'test', 'test')
    assert calls == ['primary.invalid']


def test_explicit_rejection_uses_fallback(monkeypatch):
    calls = []
    class SMTP:
        def __init__(self, host, *args, **kwargs):
            calls.append(host)
            self.host = host
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def ehlo(self): pass
        def starttls(self, **kwargs): pass
        def login(self, *args): pass
        def send_message(self, msg):
            if self.host == 'primary.invalid':
                raise smtplib.SMTPDataError(451, b'try later')
            return {}
    monkeypatch.setattr(sender.smtplib, 'SMTP', SMTP)
    for key, value in {'SMTP_HOST': 'primary.invalid', 'SMTP_SSL': False,
                       'SMTP_FALLBACK_HOST': 'fallback.invalid',
                       'SMTP_FALLBACK_SSL': False, 'EMAIL_TRANSPORT': 'smtp'}.items():
        monkeypatch.setattr(sender.settings, key, value)
    assert sender._send('controlled@example.invalid', 'test', 'test')
    assert calls == ['primary.invalid', 'fallback.invalid']
