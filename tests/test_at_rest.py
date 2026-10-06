"""mfa_secret encryption at rest: round trip, no double wrapping, legacy
plaintext rows still readable, and a wrong key fails closed (None)."""
import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-test-1234")

from core.security.at_rest import EncryptedSecret, decrypt_secret, encrypt_secret, is_encrypted  # noqa: E402

SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def test_round_trip_and_fits_the_column():
    stored = encrypt_secret(SECRET)
    assert is_encrypted(stored) and SECRET not in stored
    assert len(stored) <= 255
    assert decrypt_secret(stored) == SECRET
    assert encrypt_secret(SECRET) != stored  # fresh IV every time


def test_column_type_does_not_double_wrap_and_reads_legacy_plaintext():
    column = EncryptedSecret(255)
    stored = column.process_bind_param(SECRET, None)
    assert column.process_bind_param(stored, None) == stored
    assert column.process_result_value(stored, None) == SECRET
    assert column.process_result_value(SECRET, None) == SECRET  # legacy, not yet migrated
    assert column.process_bind_param(None, None) is None


def test_wrong_key_fails_closed():
    stored = encrypt_secret(SECRET, secret_key="key-one-key-one-key-one-key-one-0000")
    assert decrypt_secret(stored, secret_key="key-two-key-two-key-two-key-two-0000") is None
