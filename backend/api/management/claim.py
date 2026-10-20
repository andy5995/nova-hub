"""Claim links, the sysop's side: public, no session needed to look.

For an unbound link, possession is the credential (see
backend/services/claim_links.py), so these endpoints take no login. A bound
link also needs its account signed in to claim: the session is read if there
is one, never required to look. An unknown token counts as a failed attempt
toward the per-IP lockout the login endpoints use, which is what stops anyone
guessing at them.

GET reports the link's state and changes nothing -- a chat app fetching a
preview of a pasted link must not use it up. POST claims it.
"""

import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.rate_limiter import (
    _get_client_ip,
    check_rate_limit,
    from_trusted_proxy,
    record_failed_attempt,
)
from backend.core.security import get_current_user_optional
from backend.logging_config import get_logger
from backend.models.database import ClaimLink, Client, SysopUser
from backend.schemas.claim import ClaimedLeague, ClaimPageStatus, ClaimResult
from backend.services import audit, claim_links

logger = get_logger(context="claim_links")

router = APIRouter()

# secrets.token_urlsafe(32) is 43 characters of URL-safe base64.
TOKEN = Path(..., pattern=r"^[A-Za-z0-9_-]{20,64}$")


# A hostname or IPv4 address, or a bracketed IPv6 one, with an optional port.
_HOST = re.compile(r"(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])(?::\d{1,5})?")

def utc(dt: Optional[datetime]) -> Optional[datetime]:
    """The database holds naive UTC; say so on the way out."""
    return dt.replace(tzinfo=timezone.utc) if dt else None


def public_url(request: Request) -> str:
    """The hub's address as sysops reach it: [server] public_url, else the request's."""
    from backend.core.config import get_config

    configured = get_config().get("server", {}).get("public_url")
    if configured:
        return str(configured).rstrip("/")
    proto, host = request.url.scheme, request.url.netloc
    if from_trusted_proxy(request):
        proto = request.headers.get("x-forwarded-proto", proto)
        host = request.headers.get("x-forwarded-host", host)
    # Links built here go into claim pages and config files: a Host header
    # carrying anything but a hostname and port is not one to repeat.
    if proto not in ("http", "https") or not _HOST.fullmatch(host):
        raise HTTPException(status_code=400, detail="Bad Host header")
    return f"{proto}://{host}"


def _link_or_404(request: Request, db: Session, token: str) -> ClaimLink:
    check_rate_limit(request)
    link = claim_links.find(db, token)
    if link is None:
        record_failed_attempt(request)
        raise HTTPException(status_code=404, detail="This claim link is not valid.")
    return link


@router.get("/{token}", response_model=ClaimPageStatus, summary="Claim Link Status")
async def claim_status(
    request: Request,
    token: str = TOKEN,
    db: Session = Depends(get_db),
    viewer: Optional[SysopUser] = Depends(get_current_user_optional),
):
    """
    What a claim link is for and whether it can still be used. Changes nothing.

    **Returns:** the BBS's name, the link's state (`ready`, `used`, `superseded`
    or `expired`), whether claiming needs a sign-in and whether the viewer is
    the right account, its expiry, and when and from where it was used if it was.
    """
    link = _link_or_404(request, db, token)
    return ClaimPageStatus(
        bbs_name=link.client.bbs_name,
        state=claim_links.state(link),
        requires_sign_in=link.user_id is not None,
        signed_in_as_owner=link.user_id is not None and viewer is not None
        and viewer.id == link.user_id,
        expires_at=utc(link.expires_at),
        used_at=utc(link.used_at),
        used_ip=link.used_ip,
    )


@router.post("/{token}", response_model=ClaimResult, summary="Claim Credentials")
async def claim(
    request: Request,
    token: str = TOKEN,
    db: Session = Depends(get_db),
    viewer: Optional[SysopUser] = Depends(get_current_user_optional),
):
    """
    Use a claim link: generate the BBS's client secret and return it, once.

    The new secret replaces the BBS's previous one immediately. Returns the
    credentials together with ready-made client config files (Linux
    `config.toml`, Windows `config.psd1`) listing the BBS's leagues. 409 if
    the link has been used, superseded or has expired. A bound link needs its
    account signed in: 401 when no one is, 403 when someone else is.
    """
    link = _link_or_404(request, db, token)
    if link.user_id is not None:
        if viewer is None:
            raise HTTPException(status_code=401,
                                detail="Sign in to claim these credentials.")
        if viewer.id != link.user_id:
            record_failed_attempt(request)
            raise HTTPException(
                status_code=403,
                detail="This link was issued to a different hub account. Sign in as that "
                       "account, or ask the hub admin.",
            )
    ip = _get_client_ip(request)
    try:
        secret = claim_links.claim(db, link, ip)
    except claim_links.NotClaimable:
        db.refresh(link)
        raise HTTPException(
            status_code=409,
            detail=f"This claim link cannot be used: it is {claim_links.state(link)}.",
        )

    client: Client = link.client
    audit.record(db, "claim_link.used", target=client,
                 detail=f"link {link.id}; the BBS's secret was replaced", request=request)
    db.commit()
    logger.info(f"Claim link {link.id} used for client {client.client_id} from {ip}")

    hub_url = public_url(request)
    leagues = claim_links.league_entries(db, client)
    return ClaimResult(
        bbs_name=client.bbs_name,
        hub_url=hub_url,
        client_id=client.client_id,
        client_secret=secret,
        leagues=[ClaimedLeague(game=e.code, number=e.number, bbs_index=e.bbs_index) for e in leagues],
        config_toml=claim_links.render_config_toml(client, secret, hub_url, leagues),
        config_psd1=claim_links.render_config_psd1(client, secret, hub_url, leagues),
    )
