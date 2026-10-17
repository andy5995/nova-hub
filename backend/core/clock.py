"""
The hub's one source of "now".

Every DateTime column holds naive UTC, and every comparison in the code is
between naive datetimes, so "now" has to be naive UTC too. That is what
datetime.utcnow() returned, but Python 3.12 deprecates it. This gives the same
value from the timezone-aware clock, so nothing stored or compared changes.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """The current time in UTC, without a tzinfo, as the database stores it."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
