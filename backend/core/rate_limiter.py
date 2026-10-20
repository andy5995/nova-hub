"""
In-memory auth rate limiter for Nova Hub

Tracks failed authentication attempts per IP address and enforces
a temporary lockout after exceeding the configured threshold.
"""

import time
from collections import defaultdict
from threading import Lock
from typing import Dict, List

from fastapi import HTTPException, Request, status

from backend.core.config import get_config
from backend.logging_config import get_logger

logger = get_logger(context="rate_limiter")

# Per-IP tracking: IP -> list of attempt timestamps
_attempts: Dict[str, List[float]] = defaultdict(list)
# Per-IP lockout expiry: IP -> lockout_until timestamp
_lockouts: Dict[str, float] = {}
_lock = Lock()


def from_trusted_proxy(request: Request) -> bool:
    """Whether the request came through the reverse proxy, whose X-Forwarded-* headers count."""
    peer = request.client.host if request.client else None
    return peer is not None and peer in get_config().security.trusted_proxies


def _get_client_ip(request: Request) -> str:
    """The client's IP: the peer's, or what the trusted proxy says it saw.

    The proxy appends the address it received from, so the last entry is the
    one it vouches for; anything left of it came from the client. Caddy, as
    deployed, replaces the header outright for untrusted clients, so there is
    usually only one.
    """
    peer = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for and from_trusted_proxy(request):
        return forwarded_for.split(",")[-1].strip() or peer
    return peer


def _prune(now: float, window: float) -> None:
    """Drop IPs with no recent attempts and expired lockouts, so the tables stay small."""
    for ip in [ip for ip, times in _attempts.items() if not times or now - times[-1] >= window]:
        del _attempts[ip]
    for ip in [ip for ip, until in _lockouts.items() if now >= until]:
        del _lockouts[ip]


def record_failed_attempt(request: Request) -> None:
    """Record a failed auth attempt for the requesting IP."""
    config = get_config()
    if not config.rate_limiting.enabled:
        return

    ip = _get_client_ip(request)
    now = time.monotonic()
    window = 60.0  # 1 minute sliding window
    max_attempts = config.rate_limiting.auth_attempts_per_minute
    lockout_duration = config.rate_limiting.auth_lockout_seconds

    with _lock:
        _prune(now, window)
        # Prune old attempts outside the window
        _attempts[ip] = [t for t in _attempts[ip] if now - t < window]
        _attempts[ip].append(now)

        if len(_attempts[ip]) >= max_attempts:
            _lockouts[ip] = now + lockout_duration
            _attempts[ip] = []
            logger.warning(
                f"Auth lockout applied for IP {ip} "
                f"({max_attempts} attempts in {window}s, locked for {lockout_duration}s)"
            )


def check_rate_limit(request: Request) -> None:
    """
    Raise HTTP 429 if the requesting IP is currently locked out.

    Call this at the start of auth endpoints before processing credentials.
    """
    config = get_config()
    if not config.rate_limiting.enabled:
        return

    ip = _get_client_ip(request)
    now = time.monotonic()

    with _lock:
        lockout_until = _lockouts.get(ip)
        if lockout_until and now < lockout_until:
            retry_after = int(lockout_until - now)
            logger.info(f"Blocked auth attempt from locked-out IP {ip} (retry after {retry_after}s)")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many failed authentication attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        elif lockout_until and now >= lockout_until:
            # Lockout expired
            del _lockouts[ip]
