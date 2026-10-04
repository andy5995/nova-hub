"""InterBBS traffic other than attacks: ops, trade deals, spy reports, messages.

See backend/services/traffic_trace.py. The listing carries no contents; an
admin can reveal one event's, which is logged. Messages are never revealed.
"""
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, Query
from sqlalchemy.orm import Session

from backend.core.config import get_config
from backend.core.database import get_db
from backend.core.security import get_current_user, require_admin
from backend.logging_config import get_logger
from backend.models.database import League, Packet, SysopUser, TrafficSighting
from backend.schemas.attacks import AttackHop
from backend.schemas.traffic import TrafficDetails, TrafficEvent
from backend.services import attack_trace, bre_packet, traffic_trace

router = APIRouter()
logger = get_logger(context="management_traffic")

# What a reveal can say something about. Not a Message, and not the types whose
# contents are not mapped yet.
REVEALABLE = frozenset({
    bre_packet.TERRORIST_OP, bre_packet.TERRORIST_RESULT, bre_packet.TRADE_DEAL,
    bre_packet.SPY_REPORT, bre_packet.REPORT, bre_packet.SPY_GUY,
})


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat() if t else None


@router.get("/", response_model=List[TrafficEvent], summary="List InterBBS Traffic")
async def list_traffic(
    days: int = Query(14, ge=1, le=365),
    league_id: Optional[int] = Query(None),
    planet: Optional[int] = Query(None, description="Either end"),
    record_type: Optional[int] = Query(None, ge=0, le=255),
    limit: int = Query(500, ge=1, le=2000),
    current_user: SysopUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Traffic reaching the hub within `days`, newest first, each with its hops."""
    hub_index = get_config().get("hub", {}).get("bbs_index", "01")
    found = traffic_trace.events(db, hub_index, league_id=league_id,
                                 since=datetime.utcnow() - timedelta(days=days),
                                 planet=planet, record_type=record_type, limit=limit)
    names = {lg.id: lg.name for lg in db.query(League).all()}
    return [
        TrafficEvent(
            key=e.key, league_id=e.league_id, league_name=names.get(e.league_id),
            kind=e.name, record_type=e.record_type,
            from_planet=e.from_planet, to_planet=e.to_planet,
            from_letter=e.from_letter, to_letter=e.to_letter,
            recipients=e.recipients, stamp=_iso(e.stamp),
            at_hub=_iso(e.at_hub), delivered=_iso(e.delivered), stage=e.stage,
            paired_with=e.paired_with, revealable=e.record_type in REVEALABLE,
            hops=[AttackHop(is_result=False, packet_id=h.packet_id, filename=h.filename,
                            source_bbs=h.source_bbs, dest_bbs=h.dest_bbs,
                            at_hub=_iso(h.at_hub), taken=_iso(h.taken)) for h in e.hops],
        )
        for e in found
    ]


@router.get("/{key}/details", response_model=TrafficDetails,
            summary="Reveal an Event's Contents (admin)")
async def reveal_details(
    key: str = PathParam(..., pattern="^[0-9a-f]{16}$"),
    current_user: SysopUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Hidden game state: admin only, one event per request, logged.

    A Message's content is refused to everyone.
    """
    sightings = db.query(TrafficSighting).filter(TrafficSighting.event_key == key).all()
    if not sightings:
        raise HTTPException(status_code=404, detail="No such event")
    rtype = sightings[0].record_type
    if rtype == bre_packet.MESSAGE:
        raise HTTPException(status_code=403, detail="Message content is never revealed")
    if rtype not in REVEALABLE:
        raise HTTPException(status_code=404, detail="This kind of record is not decoded yet")
    data_dir = Path(get_config().get("server", {}).get("data_dir", "./data"))
    packets = db.query(Packet).filter(Packet.id.in_([s.packet_id for s in sightings])).all()
    for r in attack_trace.stored_records(packets, data_dir):
        if r.type == rtype and bre_packet.event_key(r) == key:
            logger.info(f"Traffic {key} ({r.name}) revealed to {current_user.username}")
            return TrafficDetails(key=key, kind=r.name, details=bre_packet.traffic_details(r))
    raise HTTPException(status_code=404, detail="No stored packet holds this event")
