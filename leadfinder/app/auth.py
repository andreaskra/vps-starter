"""Password check (PBKDF2), signed session cookie, login rate limiting."""
import hashlib
import hmac
import threading
import time

from itsdangerous import BadSignature, URLSafeTimedSerializer

from . import config

SESSION_MAX_AGE = 7 * 24 * 3600  # one week
COOKIE_NAME = "leadfinder_session"

_serializer = URLSafeTimedSerializer(config.SECRET_KEY, salt="leadfinder-auth")

# login rate limit: max 5 failed attempts per IP per 15 minutes
_attempts: dict[str, list[float]] = {}
_attempts_lock = threading.Lock()
MAX_ATTEMPTS = 5
WINDOW = 15 * 60


def verify_password(password: str) -> bool:
    """Hash format written by setup.sh: pbkdf2_sha256:<iterations>:<salt_hex>:<hash_hex>.
    Colon-delimited on purpose — docker compose interpolates `$` in env_file values."""
    try:
        algo, iterations, salt, expected = config.DASHBOARD_PASSWORD_HASH.split(":")
        if algo != "pbkdf2_sha256":
            return False
        computed = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        ).hex()
        return hmac.compare_digest(computed, expected)
    except (ValueError, AttributeError):
        return False


def rate_limited(ip: str) -> bool:
    with _attempts_lock:
        stamps = [t for t in _attempts.get(ip, []) if time.time() - t < WINDOW]
        _attempts[ip] = stamps
        return len(stamps) >= MAX_ATTEMPTS


def record_failure(ip: str) -> None:
    with _attempts_lock:
        _attempts.setdefault(ip, []).append(time.time())


def make_session_token() -> str:
    return _serializer.dumps({"auth": True})


def check_session_token(token: str) -> bool:
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE)
        return bool(data.get("auth"))
    except BadSignature:
        return False
