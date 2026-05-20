"""
Security Utilities and Authentication
"""

from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
import secrets
import hashlib
import hmac
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

from core.config.settings import settings

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Separator used when storing salted API key hashes: "<hex-salt>$<hex-hash>"
_HASH_SEP = "$"


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Dict[str, Any]:
    """Verify JWT token and return payload"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise ValueError("Invalid token")


def get_password_hash(password: str) -> str:
    """Hash password using bcrypt"""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash"""
    return pwd_context.verify(plain_password, hashed_password)


def generate_secure_token(length: int = 32) -> str:
    """Generate secure random token"""
    return secrets.token_urlsafe(length)


def generate_api_key() -> str:
    """Generate API key"""
    timestamp = str(int(datetime.utcnow().timestamp()))
    random_part = secrets.token_urlsafe(32)
    return f"lp_{timestamp}_{random_part}"


def hash_api_key(api_key: str) -> str:
    """Hash API key for storage using PBKDF2-HMAC-SHA256 with a random salt.

    Returns a string of the form ``<hex-salt>$<hex-hash>`` so the salt is
    stored alongside the derived key.  This replaces the previous bare
    hashlib.sha256 call (CodeQL alerts #6 and #7 — weak/broken hashing on
    sensitive data).
    """
    salt: bytes = secrets.token_bytes(32)
    derived: bytes = hashlib.pbkdf2_hmac(
        "sha256",
        api_key.encode("utf-8"),
        salt,
        iterations=260_000,
    )
    return salt.hex() + _HASH_SEP + derived.hex()


def verify_api_key(api_key: str, hashed_key: str) -> bool:
    """Verify API key against a salted PBKDF2 hash.

    Supports both the legacy bare-sha256 format (64 hex chars, no separator)
    and the new salted format so existing keys keep working until rotated.
    """
    if _HASH_SEP not in hashed_key:
        # Legacy path: bare sha256 — compare and schedule re-hash on next write
        candidate = hashlib.sha256(api_key.encode()).hexdigest()
        return hmac.compare_digest(candidate, hashed_key)

    try:
        salt_hex, stored_hex = hashed_key.split(_HASH_SEP, 1)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False

    derived: bytes = hashlib.pbkdf2_hmac(
        "sha256",
        api_key.encode("utf-8"),
        salt,
        iterations=260_000,
    )
    return hmac.compare_digest(derived.hex(), stored_hex)


class EncryptionManager:
    """Encryption manager for sensitive data"""
    
    def __init__(self, key: Optional[str] = None):
        if key:
            self.fernet = Fernet(key.encode())
        else:
            # Derive key from settings
            self.fernet = Fernet(self._derive_key(settings.ENCRYPTION_KEY))
    
    def _derive_key(self, password: str) -> bytes:
        """Derive encryption key from password"""
        password_bytes = password.encode()
        salt = b"lockerphycer_salt"  # In production, use a proper salt
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password_bytes))
        return key
    
    def encrypt(self, data: str) -> str:
        """Encrypt data"""
        encrypted_data = self.fernet.encrypt(data.encode())
        return base64.urlsafe_b64encode(encrypted_data).decode()
    
    def decrypt(self, encrypted_data: str) -> str:
        """Decrypt data"""
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
        decrypted_data = self.fernet.decrypt(encrypted_bytes)
        return decrypted_data.decode()


# Global encryption manager
encryption_manager = EncryptionManager()


def encrypt_field(data: str) -> str:
    """Encrypt a field"""
    return encryption_manager.encrypt(data)


def decrypt_field(encrypted_data: str) -> str:
    """Decrypt a field"""
    return encryption_manager.decrypt(encrypted_data)


def generate_session_id() -> str:
    """Generate secure session ID"""
    return secrets.token_urlsafe(32)


def validate_password_strength(password: str) -> Dict[str, Any]:
    """Validate password strength"""
    errors = []
    
    if len(password) < 8:
        errors.append("Password must be at least 8 characters long")
    
    if not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter")
    
    if not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter")
    
    if not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one digit")
    
    special_chars = "!@#$%^&*()_+-=[]{}|;:,.<>?"
    if not any(c in special_chars for c in password):
        errors.append("Password must contain at least one special character")
    
    # Check for common patterns
    common_patterns = ["password", "123456", "qwerty", "admin"]
    if any(pattern in password.lower() for pattern in common_patterns):
        errors.append("Password contains common patterns")
    
    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "strength": calculate_password_strength(password)
    }


def calculate_password_strength(password: str) -> str:
    """Calculate password strength"""
    score = 0
    
    # Length
    if len(password) >= 8:
        score += 1
    if len(password) >= 12:
        score += 1
    if len(password) >= 16:
        score += 1
    
    # Character types
    if any(c.isupper() for c in password):
        score += 1
    if any(c.islower() for c in password):
        score += 1
    if any(c.isdigit() for c in password):
        score += 1
    if any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        score += 1
    
    # Complexity
    unique_chars = len(set(password))
    if unique_chars >= len(password) * 0.7:
        score += 1
    
    if score <= 3:
        return "weak"
    elif score <= 6:
        return "medium"
    elif score <= 8:
        return "strong"
    else:
        return "very_strong"


def generate_csrf_token() -> str:
    """Generate CSRF token"""
    return secrets.token_urlsafe(32)


def verify_csrf_token(token: str, expected_token: str) -> bool:
    """Verify CSRF token"""
    return hmac.compare_digest(token, expected_token)


def sanitize_input(input_string: str) -> str:
    """Sanitize user input"""
    # Remove potentially dangerous characters
    dangerous_chars = "<>\"'&"
    for char in dangerous_chars:
        input_string = input_string.replace(char, "")
    return input_string.strip()


def is_safe_url(url: str) -> bool:
    """Check if URL is safe (no javascript: / data: scheme injection)"""
    dangerous_schemes = ["javascript:", "data:", "vbscript:", "file:"]
    lower = url.lower().strip()
    return not any(lower.startswith(s) for s in dangerous_schemes)


# ---------------------------------------------------------------------------
# Admin auth dependency — JWT-first, query-param fallback in dev mode only
# ---------------------------------------------------------------------------
from fastapi import Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional as _Opt

_bearer_scheme = HTTPBearer(auto_error=False)


async def require_admin(
    credentials: _Opt[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    caller_email: _Opt[str] = Query(None),
) -> str:
    """Resolve admin identity.

    Production path: Bearer JWT containing ``sub`` == ADMIN_EMAIL and
    ``role`` == ``admin``.

    Dev-mode fallback: ``?caller_email=<ADMIN_EMAIL>`` still accepted
    when ``settings.DEBUG`` is True so local testing is not blocked.
    """
    admin = settings.ADMIN_EMAIL

    # 1) Try Bearer token
    if credentials and credentials.credentials:
        try:
            payload = verify_token(credentials.credentials)
        except (ValueError, Exception):
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        token_email = payload.get("sub", "")
        token_role = payload.get("role", "")
        if token_email != admin or token_role != "admin":
            raise HTTPException(status_code=403, detail="Command Center: admin only")
        return token_email

    # 2) Dev-mode query-param fallback
    if settings.DEBUG and caller_email:
        if caller_email != admin:
            raise HTTPException(status_code=403, detail="Command Center: admin only")
        return caller_email

    # 3) No auth provided
    if settings.DEBUG:
        return admin  # allow unauthenticated access in dev for convenience

    raise HTTPException(status_code=401, detail="Authentication required")
