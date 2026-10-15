"""A league's resets: the ones performed from the console, and the ones the hub
only saw happen.

A BRE game's first PLANETARY after a league-wide reset sends every member a
Game Start record (0x10). It has the Configupdate's layout, so it carries the
start time and the three settings bre_packet decodes so far. Every Game Start
the hub passes is recorded here:

- right after a console reset, it confirms that reset: the start time and what
  was sent are filled in, and any setting that disagrees with the draft is
  listed in `sent_config["mismatches"]`;
- otherwise it is a reset done some other way (by hand, or before the console
  could), kept as an `observed` row so the history goes back further than the
  console does.

FE's packets aren't decoded yet, so an FE league's history is its console
resets only.
"""
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

from sqlalchemy.orm import Session

from backend.logging_config import get_logger
from backend.models.database import GameReset, League, Packet
from backend.services import bre_packet

logger = get_logger(context="game_reset")

# A console reset's Game Start goes out on the run straight after it. Allow for
# that run failing and the next good one being a day or so later.
CONFIRM_WINDOW = timedelta(days=3)

# The settings a Game Start carries, as catalogue field ids.
_SENT = (("protection_turns", "protection_turns"),
         ("indiv_attacks", "indiv_attacks_per_day"),
         ("lost_attack_days", "lost_attack_days"))


def sent(s: bre_packet.LeagueSettings) -> dict:
    out = {fid: getattr(s, attr) for fid, attr in _SENT}
    out["game_start"] = s.game_started_at.isoformat() if s.game_started_at else None
    return out


def mismatches(settings: dict, got: dict) -> list:
    """The settings in `got` (from sent()) that disagree with a reset's draft."""
    wrong = [fid for fid, _ in _SENT
             if fid in settings and got.get(fid) is not None and got[fid] != settings[fid]]
    start = settings.get("start_date")
    if start and got.get("game_start") and got["game_start"][:10] != start:
        wrong.append("start_date")
    return wrong


def record_game_start(db: Session, league: League, packet: Packet,
                      s: bre_packet.LeagueSettings) -> Optional[GameReset]:
    """Note a Game Start the hub has passed. Idempotent: every member's packet
    carries the same one."""
    if s.game_started_at is None:
        return None
    known = (db.query(GameReset)
             .filter(GameReset.league_id == league.id,
                     GameReset.game_start == s.game_started_at)
             .first())
    if known is not None:
        return known
    got = sent(s)
    seen = packet.uploaded_at or datetime.utcnow()
    pending = (db.query(GameReset)
               .filter(GameReset.league_id == league.id,
                       GameReset.source == "console",
                       GameReset.status == "applied",
                       GameReset.game_start.is_(None),
                       GameReset.applied_at >= seen - CONFIRM_WINDOW,
                       GameReset.applied_at <= seen + timedelta(minutes=5))
               .order_by(GameReset.applied_at.desc())
               .first())
    if pending is not None:
        pending.game_start = s.game_started_at
        pending.sent_config = {**got, "mismatches": mismatches(pending.settings, got)}
        logger.info(f"Reset {pending.id} of {league.full_id} confirmed by "
                    f"{packet.filename}: game start {s.game_started_at}")
        return pending
    row = GameReset(
        league_id=league.id, status="applied", source="observed",
        settings={fid: got[fid] for fid, _ in _SENT}, version=1,
        created_at=seen, updated_at=seen, applied_at=seen,
        game_start=s.game_started_at, sent_config=got)
    db.add(row)
    logger.info(f"Observed a reset of {league.full_id} in {packet.filename}: "
                f"game start {s.game_started_at}")
    return row


def history(db: Session, league: League) -> list:
    """Every reset but the draft, newest first, each with when its game ended
    (the next reset's start), or None for the game being played now."""
    rows = (db.query(GameReset)
            .filter(GameReset.league_id == league.id, GameReset.status != "draft")
            .all())

    def began(r):
        return r.game_start or r.applied_at or r.created_at or datetime.min
    rows.sort(key=began, reverse=True)
    out, after = [], None
    for r in rows:
        ended = None
        if r.status == "applied":
            ended = began(after) if after is not None else None
            after = r
        out.append((r, ended))
    return out


def backfill(db: Session, data_dir: Path) -> Dict[str, int]:
    """Record the Game Starts in BRE packets already on disk. Idempotent."""
    from backend.services.attack_trace import NODELIST_PREFIXES, _candidates, _file_index

    counts = {"packets": 0, "game_starts": 0, "missing": 0, "failed": 0}
    index = _file_index(Path(data_dir))
    packets = (db.query(Packet).join(League, Packet.league_id == League.id)
               .filter(League.game_type == "B")
               .order_by(Packet.uploaded_at.asc()).all())
    for packet in packets:
        if packet.filename.upper().startswith(NODELIST_PREFIXES):
            continue
        counts["packets"] += 1
        candidates = _candidates(packet, index.get(packet.filename.upper()))
        content = next((c for c in candidates if not packet.checksum
                        or hashlib.sha256(c).hexdigest() == packet.checksum), None)
        if content is None:
            counts["missing"] += 1
            continue
        try:
            for rec in bre_packet.parse(content):
                if rec.type == bre_packet.GAME_START and rec.crc_ok:
                    record_game_start(db, packet.league or db.get(League, packet.league_id),
                                      packet, bre_packet.league_settings(rec))
                    counts["game_starts"] += 1
            db.flush()
        except Exception as exc:
            counts["failed"] += 1
            logger.warning(f"Could not read {packet.filename} for Game Starts: {exc}")
    db.commit()
    return counts
