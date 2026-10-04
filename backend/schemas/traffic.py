"""Schemas for the InterBBS traffic view.

As for attacks: the listing says who sent what kind of thing to whom and how
far it got. What was in it is TrafficDetails, admin only, one event at a time,
on request -- and a Message's text is never decoded at all.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from backend.schemas.attacks import AttackHop


class TrafficEvent(BaseModel):
    key: str
    league_id: int
    league_name: Optional[str] = None
    kind: str                         # the game's own name, e.g. "Terrorist Op"
    record_type: int
    from_planet: int
    to_planet: int
    from_letter: Optional[str] = None
    to_letter: Optional[str] = None
    recipients: Optional[str] = None  # Message: "all planets", or realm letters
    stamp: Optional[str] = None       # far side's game clock, where it says
    at_hub: Optional[str] = None
    delivered: Optional[str] = None
    stage: str
    paired_with: Optional[str] = None
    revealable: bool                  # whether there is anything an admin may reveal
    hops: List[AttackHop] = []


class TrafficDetails(BaseModel):
    key: str
    kind: str
    details: Dict[str, Any]
