"""Security helpers: password hashing, signed tokens, rate limiting, client IP."""
import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque

SECRET = os.getenv("SECRET_KEY") or secrets.token_hex(32)  # random per boot if unset
TOKEN_HOURS = 12
PBKDF2_ROUNDS = 200_000


# ---------- passwords ----------
def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), PBKDF2_ROUNDS).hex()
    return f"pbkdf2${PBKDF2_ROUNDS}${salt}${h}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, rounds, salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), int(rounds)).hex()
        return hmac.compare_digest(calc, h)
    except (ValueError, AttributeError):
        return False


# ---------- tokens ----------
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def make_token(username: str, role: str, mission_id=None) -> str:
    payload = _b64(json.dumps({"u": username, "r": role, "m": mission_id,
                               "exp": int(time.time()) + TOKEN_HOURS * 3600}).encode())
    sig = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def read_token(token: str):
    try:
        payload, sig = token.split(".", 1)
        good = hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(good, sig):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if data["exp"] < time.time():
            return None
        return {"username": data["u"], "role": data["r"], "mission_id": data.get("m")}
    except Exception:
        return None


# ---------- rate limiting (in-memory, per process) ----------
class RateLimiter:
    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: float) -> bool:
        """Record a hit; return True if allowed, False if over the limit."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self._hits) > 50_000:  # crude memory guard
                self._hits.clear()
            return True

    def count(self, key: str, window: float) -> int:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and q[0] <= now - window:
                q.popleft()
            return len(q)

    def reset(self, key: str):
        with self._lock:
            self._hits.pop(key, None)


limiter = RateLimiter()


def client_ip(request) -> str:
    # On Render, traffic passes through Cloudflare, which overwrites CF-Connecting-IP with the
    # real client address (clients cannot forge it). X-Forwarded-For's first entry CAN be forged,
    # so it is not trusted.
    for h in ("cf-connecting-ip", "true-client-ip"):
        v = request.headers.get(h)
        if v:
            return v.strip()[:64]
    return request.client.host if request.client else "unknown"
