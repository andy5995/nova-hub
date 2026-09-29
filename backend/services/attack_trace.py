"""Follow each BRE attack through the hub, from launch to result.

A Missing In Transit is the attacker's game giving up: no result came back
within the league's "Days for Lost Attacks". From inside the game that is all
anyone can see. The hub carried every hop, though, and each attack carries an ID
its result echoes, so the hub can say exactly how far an attack got:

    launched            the attacker's session (game clock of the attacker's board)
    attack at hub       first packet the hub received it in
    attack delivered    the packet addressed to the target's board was taken
    result at hub       first packet the hub received the result in
    result delivered    the packet addressed back to the attacker was taken

The last stage reached is where it stopped. That is descriptive on purpose -- a
board that has not polled today is not a fault -- but where a result was handed
over after the MIT window, the game will have thrown it away, and saying so is
not a judgement call.

"Taken" means downloaded by the board's client, or, when the board is the hub's
own, processed by the hub's game.

Everything here is best-effort with respect to ingest: decoding a packet must
never be the reason a packet fails to be stored.
"""
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.logging_config import get_logger
from backend.models.database import AttackSighting, League, LeagueGameSettings, Packet
from backend.services import bre_packet

logger = get_logger(context="attack_trace")

DEFAULT_LOST_ATTACK_DAYS = 7    # BRE's default, used until a Configupdate is seen


def _now() -> datetime:
    return datetime.utcnow()


# ── recording ─────────────────────────────────────────────────────────────
def record(db: Session, packet: Packet, content: bytes) -> int:
    """Record the attacks and league settings in one packet. Returns sightings added.

    Idempotent per packet: a filename is reused when its sequence number wraps,
    and the outbound collector then rewrites the same row, so whatever was
    recorded against the row before belongs to a different packet and goes.
    """
    league = packet.league or db.get(League, packet.league_id)
    if league is None or league.game_type != "B":
        return 0

    records = bre_packet.parse(content)
    db.query(AttackSighting).filter(AttackSighting.packet_id == packet.id).delete()

    added = 0
    for rec in records:
        if not rec.crc_ok:
            # A damaged record decodes to garbage; recording a garbage ID would
            # invent an attack that never happened.
            continue
        if rec.type in (bre_packet.INDIV_ATTACK, bre_packet.ATTACK_RESULT):
            a = bre_packet.attack(rec)
            db.add(AttackSighting(
                attack_id=a.attack_id, is_result=a.is_result,
                packet_id=packet.id, league_id=league.id,
                from_planet=a.from_planet, to_planet=a.to_planet,
                attacker=a.attacker, target=a.target,
                attack_type=a.attack_type, stamp=a.stamp,
            ))
            added += 1
        elif rec.type == bre_packet.CONFIG_UPDATE:
            _remember_settings(db, league, packet, bre_packet.league_settings(rec))
    db.commit()
    return added


def record_safely(db: Session, packet: Packet, content: bytes) -> int:
    """`record()` for ingest paths: logs and swallows anything it raises."""
    try:
        return record(db, packet, content)
    except Exception as exc:
        db.rollback()
        logger.warning(f"Could not trace attacks in {packet.filename}: {exc}")
        return 0


def _remember_settings(db, league, packet, s: bre_packet.LeagueSettings):
    seen = packet.uploaded_at or datetime.utcnow()
    row = db.get(LeagueGameSettings, league.id)
    if row is not None and row.seen_at and row.seen_at > seen:
        return      # an older packet being backfilled; keep the newer settings
    if row is None:
        row = LeagueGameSettings(league_id=league.id)
        db.add(row)
    row.game_started_at = s.game_started_at
    row.protection_turns = s.protection_turns
    row.indiv_attacks_per_day = s.indiv_attacks_per_day
    row.lost_attack_days = s.lost_attack_days
    row.packet_id = packet.id
    row.seen_at = seen


# ── backfill ──────────────────────────────────────────────────────────────
PACKET_DIRS = ("processed", "outbound", "inbound")


def backfill(db: Session, data_dir: Path, redo: bool = False) -> Dict[str, int]:
    """Trace packets stored before this existed, from the files still on disk.

    A file is only used if its SHA-256 matches the row's checksum: filenames are
    reused every thousand packets, so a same-named file may be a later packet.
    """
    counts = {"packets": 0, "traced": 0, "sightings": 0, "missing": 0, "mismatched": 0}
    done = set() if redo else {
        pid for (pid,) in db.query(AttackSighting.packet_id).distinct()
    }
    packets = (
        db.query(Packet).join(League, Packet.league_id == League.id)
        .filter(League.game_type == "B")
        .order_by(Packet.uploaded_at.asc())
        .all()
    )
    index = _file_index(Path(data_dir))
    for packet in packets:
        if packet.id in done:
            continue
        counts["packets"] += 1
        content = packet.file_data or _read(index.get(packet.filename.upper()))
        if content is None:
            counts["missing"] += 1
            continue
        if packet.checksum and hashlib.sha256(content).hexdigest() != packet.checksum:
            counts["mismatched"] += 1
            continue
        counts["sightings"] += record_safely(db, packet, content)
        counts["traced"] += 1
    return counts


def _file_index(data_dir: Path) -> Dict[str, List[Path]]:
    index: Dict[str, List[Path]] = {}
    for sub in PACKET_DIRS:
        folder = data_dir / "packets" / sub
        if folder.is_dir():
            for f in folder.iterdir():
                if f.is_file():
                    index.setdefault(f.name.upper(), []).append(f)
    return index


def _read(paths: Optional[List[Path]]) -> Optional[bytes]:
    # Several dirs may hold the name (a direct-routed packet is both archived
    # and copied to outbound); the checksum test picks the right one, so any
    # candidate that matches will do -- return the first readable.
    for p in paths or ():
        try:
            return p.read_bytes()
        except OSError:
            continue
    return None


# ── the journey ───────────────────────────────────────────────────────────
@dataclass
class Hop:
    is_result: bool
    packet_id: int
    filename: str
    source_bbs: int
    dest_bbs: int
    at_hub: Optional[datetime]
    taken: Optional[datetime]


@dataclass
class Journey:
    attack_id: str
    league_id: int
    from_planet: int
    to_planet: int
    attacker: str
    target: str
    attack_type: Optional[str]
    launched: Optional[datetime]
    resolved: Optional[datetime]           # defender's game clock
    attack_at_hub: Optional[datetime] = None
    attack_delivered: Optional[datetime] = None
    result_at_hub: Optional[datetime] = None
    result_delivered: Optional[datetime] = None
    lost_attack_days: int = DEFAULT_LOST_ATTACK_DAYS
    hops: List[Hop] = field(default_factory=list)

    @property
    def stage(self) -> str:
        if self.result_delivered:
            return "result delivered"
        if self.result_at_hub:
            return "result awaiting pickup"
        if self.attack_delivered:
            return "awaiting result"
        if self.attack_at_hub:
            return "attack awaiting pickup"
        return "not seen"

    @property
    def mit_due(self) -> Optional[datetime]:
        """The game day the attacker's board gives up on it.

        The game counts in days from the attack's date, so this is a date, not a
        24-hour multiple of the launch time -- and it is on the attacker's clock,
        which the hub's clock only approximates.
        """
        if not self.launched:
            return None
        day = datetime.combine(self.launched.date(), datetime.min.time())
        return day + timedelta(days=self.lost_attack_days)

    @property
    def mit(self) -> Optional[str]:
        """"late" if the result was handed over after the window (the game discards
        it), "overdue" if it is past the window with no result delivered, else None."""
        due = self.mit_due
        if due is None:
            return None
        if self.result_delivered:
            return "late" if self.result_delivered >= due else None
        return "overdue" if _now() >= due else None


def _bbs(hexstr: str) -> Optional[int]:
    try:
        return int(hexstr, 16)
    except (TypeError, ValueError):
        return None


def journeys(db: Session, hub_index: str, league_id: Optional[int] = None,
             since: Optional[datetime] = None, planet: Optional[int] = None,
             attack_id: Optional[str] = None, limit: int = 500) -> List[Journey]:
    q = db.query(AttackSighting, Packet).join(Packet, AttackSighting.packet_id == Packet.id)
    if league_id is not None:
        q = q.filter(AttackSighting.league_id == league_id)
    if attack_id:
        q = q.filter(AttackSighting.attack_id.startswith(attack_id.lower()))
    if planet is not None:
        q = q.filter((AttackSighting.from_planet == planet)
                     | (AttackSighting.to_planet == planet))
    if since is not None:
        # Window on when the attack was launched, taken from its attack
        # sightings -- a result's stamp is the defender's, and later.
        ids = (db.query(AttackSighting.attack_id)
               .filter(AttackSighting.is_result.is_(False),
                       AttackSighting.stamp >= since))
        q = q.filter(AttackSighting.attack_id.in_(ids))

    lost_days = {s.league_id: s.lost_attack_days
                 for s in db.query(LeagueGameSettings).all() if s.lost_attack_days}
    hub = _bbs(hub_index)

    by_id: Dict[str, Journey] = {}
    for s, p in q.all():
        j = by_id.get(s.attack_id)
        if j is None:
            j = by_id[s.attack_id] = Journey(
                attack_id=s.attack_id, league_id=s.league_id,
                from_planet=s.from_planet, to_planet=s.to_planet,
                attacker=s.attacker, target=s.target, attack_type=s.attack_type,
                launched=None, resolved=None,
                lost_attack_days=lost_days.get(s.league_id, DEFAULT_LOST_ATTACK_DAYS),
            )
        dest = _bbs(p.dest_bbs_index)
        # A packet for the hub's own board is taken when the hub's game runs it;
        # any other is taken when that board's client downloads it.
        taken = p.processed_at if dest == hub else p.downloaded_at
        j.hops.append(Hop(s.is_result, p.id, p.filename, _bbs(p.source_bbs_index),
                          dest, p.uploaded_at, taken))
        if s.is_result:
            j.resolved = _earliest(j.resolved, s.stamp)
            j.result_at_hub = _earliest(j.result_at_hub, p.uploaded_at)
            if dest == s.from_planet and taken:
                j.result_delivered = _earliest(j.result_delivered, taken)
        else:
            j.launched = j.launched or s.stamp
            j.attack_type = j.attack_type or s.attack_type
            j.attack_at_hub = _earliest(j.attack_at_hub, p.uploaded_at)
            if dest == s.to_planet and taken:
                j.attack_delivered = _earliest(j.attack_delivered, taken)

    out = list(by_id.values())
    for j in out:
        j.hops.sort(key=lambda h: (h.at_hub or datetime.min, h.is_result))
    out.sort(key=lambda j: j.launched or j.attack_at_hub or datetime.min, reverse=True)
    return out[:limit]


def _earliest(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)
