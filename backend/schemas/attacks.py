"""Schemas for the attack-tracing view.

No unit counts anywhere: an admin who also plays must not learn an attack's
strength from the hub. What is here identifies an attack and times its journey.
"""
from typing import List, Optional

from pydantic import BaseModel


class AttackHop(BaseModel):
    """One packet that carried the attack, or its result, through the hub."""
    is_result: bool
    packet_id: int
    filename: str
    source_bbs: Optional[int] = None
    dest_bbs: Optional[int] = None
    at_hub: Optional[str] = None
    taken: Optional[str] = None


class AttackJourney(BaseModel):
    attack_id: str
    league_id: int
    league_name: Optional[str] = None
    from_planet: int
    to_planet: int
    attacker: str
    target: str
    attack_type: Optional[str] = None
    # Game clocks: the attacker's board for launched, the defender's for resolved.
    launched: Optional[str] = None
    resolved: Optional[str] = None
    # Hub clock.
    attack_at_hub: Optional[str] = None
    attack_delivered: Optional[str] = None
    result_at_hub: Optional[str] = None
    result_delivered: Optional[str] = None
    stage: str
    lost_attack_days: int
    # When the attacker's board writes it off: midnight on its own clock, and
    # that moment on the hub's. The board's offset from the hub is measured.
    mit_due_local: Optional[str] = None
    mit_due: Optional[str] = None
    attacker_clock_minutes: Optional[int] = None
    # Hub clock: the attacker's uploads either side of its rollover into the due date.
    rollover_after: Optional[str] = None
    rollover_before: Optional[str] = None
    mit: Optional[str] = None       # "late" | "possible" | "overdue" | None
    # Set when the stage is "relay not held": the board the hub's missing relay was for.
    unheld_relay_to: Optional[int] = None
    hops: List[AttackHop] = []
