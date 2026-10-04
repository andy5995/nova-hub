"""The rest of the InterBBS traffic, followed through the hub like attacks are.

A Terrorist Op, trade deal, spy report or message is one record that the hub
may carry twice -- in from its board, and out again in the packet its own game
writes for the target -- and the bytes do not change, so their hash is the
event. What the listing says is who sent what kind of thing to whom, and how far
it got; what was in it stays in the packet (see bre_packet.traffic_details).

Terrorist Ops carry no ID. A result echoes its op's first ten bytes -- the two
realm letters and player IDs -- so it is paired with the latest op between
the same two players that it followed.

Player IDs are not letters, and a Message names its recipients only by ID. The
letters are learned from records that carry both (an op, a trade deal, a
message's sender); a recipient never seen that way shows as "?".
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from backend.models.database import Packet, TrafficSighting
from backend.services import bre_packet
from backend.services.attack_trace import Hop, _bbs, _earliest


@dataclass
class Event:
    key: str
    league_id: int
    record_type: int
    from_planet: int
    to_planet: int
    from_letter: Optional[str] = None
    to_letter: Optional[str] = None
    recipients: Optional[str] = None     # Message: "all planets", or letters
    stamp: Optional[datetime] = None
    at_hub: Optional[datetime] = None
    delivered: Optional[datetime] = None
    pair_key: Optional[str] = None
    paired_with: Optional[str] = None    # an op's result, or a result's op
    hops: List[Hop] = field(default_factory=list)
    _players: Tuple[Optional[int], Optional[int]] = (None, None)
    _recipient_ids: Optional[List[int]] = None

    @property
    def name(self) -> str:
        return bre_packet.RECORD_TYPES.get(self.record_type, f"type {self.record_type:#04x}")

    @property
    def stage(self) -> str:
        if self.delivered:
            return "delivered"
        return "awaiting pickup" if self.at_hub else "not seen"


def events(db: Session, hub_index: str, league_id: Optional[int] = None,
           since: Optional[datetime] = None, planet: Optional[int] = None,
           record_type: Optional[int] = None, limit: int = 500) -> List[Event]:
    q = db.query(TrafficSighting, Packet).join(Packet, TrafficSighting.packet_id == Packet.id)
    if league_id is not None:
        q = q.filter(TrafficSighting.league_id == league_id)
    if planet is not None:
        q = q.filter((TrafficSighting.from_planet == planet)
                     | (TrafficSighting.to_planet == planet))
    if record_type is not None:
        q = q.filter(TrafficSighting.record_type == record_type)
    if since is not None:
        q = q.filter(Packet.uploaded_at >= since)
    hub = _bbs(hub_index)

    by_key: Dict[str, Event] = {}
    for s, p in q.all():
        e = by_key.get(s.event_key)
        if e is None:
            e = by_key[s.event_key] = Event(
                key=s.event_key, league_id=s.league_id, record_type=s.record_type,
                from_planet=s.from_planet, to_planet=s.to_planet,
                from_letter=s.from_letter, to_letter=s.to_letter,
                stamp=s.stamp, pair_key=s.pair_key,
                _players=(s.from_player, s.to_player),
                _recipient_ids=None if s.recipients is None
                else [int(r) for r in s.recipients.split(",") if r],
            )
        source, dest = _bbs(p.source_bbs_index), _bbs(p.dest_bbs_index)
        # As for attacks: the hub's own board takes a packet when the hub's game
        # runs it, and a packet the hub's game wrote reached the hub when it was
        # collected.
        taken = p.processed_at if dest == hub else p.downloaded_at
        at_hub = (p.processed_at or p.uploaded_at) if source == hub else p.uploaded_at
        e.hops.append(Hop(False, p.id, p.filename, source, dest, at_hub, taken))
        e.at_hub = _earliest(e.at_hub, at_hub)
        if dest == s.to_planet and taken:
            e.delivered = _earliest(e.delivered, taken)

    out = list(by_key.values())
    for e in out:
        e.hops.sort(key=lambda h: h.at_hub or datetime.min)
    _pair_operations(out)
    _name_recipients(db, out)
    out.sort(key=lambda e: e.at_hub or datetime.min, reverse=True)
    return out[:limit]


def _pair_operations(out: List[Event]) -> None:
    ops: Dict[Tuple[int, str], List[Event]] = {}
    for e in out:
        if e.record_type == bre_packet.TERRORIST_OP and e.pair_key:
            ops.setdefault((e.league_id, e.pair_key), []).append(e)
    for group in ops.values():
        group.sort(key=lambda e: e.at_hub or datetime.min)
    results = sorted((e for e in out if e.record_type == bre_packet.TERRORIST_RESULT
                      and e.pair_key), key=lambda e: e.at_hub or datetime.min)
    for r in results:
        candidates = [o for o in ops.get((r.league_id, r.pair_key), [])
                      if o.paired_with is None
                      and (o.at_hub or datetime.min) <= (r.at_hub or datetime.max)]
        if candidates:
            op = candidates[-1]
            op.paired_with, r.paired_with = r.key, op.key


def _name_recipients(db: Session, out: List[Event]) -> None:
    messages = [e for e in out if e._recipient_ids is not None]
    if not messages:
        return
    letters: Dict[Tuple[int, int, int], str] = {}
    leagues = {e.league_id for e in messages}
    for s in db.query(TrafficSighting).filter(TrafficSighting.league_id.in_(leagues)):
        if s.from_player is not None and s.from_letter:
            letters[(s.league_id, s.from_planet, s.from_player)] = s.from_letter
        if s.to_player is not None and s.to_letter:
            letters[(s.league_id, s.to_planet, s.to_player)] = s.to_letter
    for e in messages:
        ids = e._recipient_ids
        if ids == [bre_packet.ALL_PLANETS]:
            e.recipients = "all planets"
        else:
            e.recipients = "".join(letters.get((e.league_id, e.to_planet, i), "?")
                                   for i in ids)
