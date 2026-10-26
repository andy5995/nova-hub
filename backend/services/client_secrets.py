"""
A BBS's client secret: checking it, and rotating it.

Only the secret's hash is kept. A rotation either stops the old secret at once
or keeps it working for a few hours, so a node isn't cut off between the
rotation and the sysop's config edit. Only the secret just replaced is kept:
rotating again during a window drops the one before it.

Stopping the old secret at once also ends every access token already issued
(they otherwise live 24 hours), because the usual reason to rotate in a hurry
is a secret that got out. A window leaves them alone: that rotation is planned,
and the tokens expire on their own.
"""

from datetime import datetime, timedelta
from typing import Optional

from backend.core.clock import utcnow
from backend.core.security import get_password_hash, verify_password
from backend.models.database import Client

# Long enough to edit a config over a weekend; short enough that a forgotten
# old secret doesn't linger.
MAX_OVERLAP_HOURS = 72


def rotate(client: Client, overlap_hours: int = 0) -> str:
    """Give the client a new secret and return it. The caller commits."""
    if not 0 <= overlap_hours <= MAX_OVERLAP_HOURS:
        raise ValueError(f"overlap_hours must be 0 to {MAX_OVERLAP_HOURS}")
    secret = Client.generate_client_secret()
    now = utcnow()
    if overlap_hours:
        client.previous_client_secret = client.client_secret
        client.previous_secret_expires_at = now + timedelta(hours=overlap_hours)
    else:
        client.previous_client_secret = None
        client.previous_secret_expires_at = None
        client.tokens_valid_after = now
    client.client_secret = get_password_hash(secret)
    return secret


def old_secret_until(client: Client, now: Optional[datetime] = None) -> Optional[datetime]:
    """When the replaced secret stops working, or None if it already has."""
    until = client.previous_secret_expires_at
    if client.previous_client_secret and until and until > (now or utcnow()):
        return until
    return None


def matches(client: Client, secret: str) -> bool:
    """The current secret, or the replaced one while its window is open."""
    if verify_password(secret, client.client_secret):
        return True
    return old_secret_until(client) is not None and verify_password(
        secret, client.previous_client_secret)


def token_revoked(client: Client, issued_at: Optional[float]) -> bool:
    """Whether a service token issued at this Unix time predates a rotation that ended it.

    Issue times carry fractions of a second, so a token taken in the same
    second as the rotation still falls on the right side of it. A token from
    before tokens were stamped has no issue time; a rotation ends it too.
    """
    if client.tokens_valid_after is None:
        return False
    cutoff = (client.tokens_valid_after - datetime(1970, 1, 1)).total_seconds()
    return issued_at is None or issued_at < cutoff
