"""Where each BRE attack got to: the journey behind a Missing In Transit.

See backend/services/attack_trace.py for how a journey is assembled, and
backend/services/bre_packet.py for how an attack is read out of a packet.
"""
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.core.config import get_config
from backend.core.database import get_db
from backend.core.security import get_current_user
from backend.models.database import League, SysopUser
from backend.schemas.attacks import AttackHop, AttackJourney
from backend.services import attack_trace

router = APIRouter()

DEFAULT_WINDOW_DAYS = 14
MAX_WINDOW_DAYS = 365
STAGES = ("result delivered", "result awaiting pickup", "awaiting result",
          "attack awaiting pickup")


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat() if t else None


@router.get("/", response_model=List[AttackJourney], summary="List Attack Journeys")
async def list_attacks(
    days: int = Query(DEFAULT_WINDOW_DAYS, ge=1, le=MAX_WINDOW_DAYS),
    league_id: Optional[int] = Query(None),
    planet: Optional[int] = Query(None, description="Attacker's or target's planet"),
    attack_id: Optional[str] = Query(None, pattern="^[0-9a-fA-F]{1,16}$",
                                     description="ID or a prefix of it; ignores `days`"),
    stage: Optional[str] = Query(None),
    mit: Optional[str] = Query(None, pattern="^(late|overdue|any)$"),
    limit: int = Query(500, ge=1, le=2000),
    current_user: SysopUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Individual attacks, most recently launched first, each with its hops.

    **Query Parameters:**
    - `days`: launched within this many days (default 14)
    - `league_id`, `planet`: filters; `planet` matches either side
    - `attack_id`: find one attack by ID, whatever its age
    - `stage`: only attacks whose journey stopped at this stage
    - `mit`: `late` (result handed over after the MIT window), `overdue` (past the
      window, no result delivered), or `any`
    """
    hub_index = get_config().get("hub", {}).get("bbs_index", "01")
    since = None if attack_id else datetime.utcnow() - timedelta(days=days)
    found = attack_trace.journeys(db, hub_index, league_id=league_id, since=since,
                                  planet=planet, attack_id=attack_id, limit=2000)
    if stage:
        found = [j for j in found if j.stage == stage]
    if mit:
        found = [j for j in found if j.mit and (mit == "any" or j.mit == mit)]

    names = {lg.id: lg.name for lg in db.query(League).all()}
    return [
        AttackJourney(
            attack_id=j.attack_id,
            league_id=j.league_id,
            league_name=names.get(j.league_id),
            from_planet=j.from_planet,
            to_planet=j.to_planet,
            attacker=j.attacker,
            target=j.target,
            attack_type=j.attack_type,
            launched=_iso(j.launched),
            resolved=_iso(j.resolved),
            attack_at_hub=_iso(j.attack_at_hub),
            attack_delivered=_iso(j.attack_delivered),
            result_at_hub=_iso(j.result_at_hub),
            result_delivered=_iso(j.result_delivered),
            stage=j.stage,
            lost_attack_days=j.lost_attack_days,
            mit_due=_iso(j.mit_due),
            mit=j.mit,
            hops=[AttackHop(is_result=h.is_result, packet_id=h.packet_id,
                            filename=h.filename, source_bbs=h.source_bbs,
                            dest_bbs=h.dest_bbs, at_hub=_iso(h.at_hub),
                            taken=_iso(h.taken)) for h in j.hops],
        )
        for j in found[:limit]
    ]
