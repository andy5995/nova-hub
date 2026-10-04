#!/usr/bin/env python3
"""Put the 2026-09-29 rig attack session into a served hub, so the Attacks page
has something real to show.

The packets are the genuine ones from tests/fixtures/bre_packets. The hub-side
times are the ones the rig actually saw, with one exception that makes this a
replay rather than a record: node 2 only declared MIT because its DOS clock was
moved three days forward with REDATE, so its late pickup happened on its own
2 October. To keep every time in the past, the whole session -- hub times and
the games' own stamps alike -- is shifted back SHIFT days, and the league's name
says so. Relative timings are exact.

    python tests/live/replay_attacks.py <path/to/config.toml>
"""
import hashlib
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.core.config import init_config                          # noqa: E402
from backend.core.database import get_session, init_database         # noqa: E402
from backend.models.database import (                                 # noqa: E402
    AttackSighting, Base, League, LeagueGameSettings, Packet, TrafficSighting,
)
from backend.services import attack_trace                             # noqa: E402

FIXTURES = REPO / "tests" / "fixtures" / "bre_packets"
SHIFT = timedelta(days=4)
NAME = "BRE League 901 (rig replay, dates -4d)"


def at(month, day, hh, mm):
    return datetime(2026, month, day, hh, mm) - SHIFT


# fixture, filename, reached hub, taken (downloaded, or run by the hub's game)
SESSION = [
    ("attacks_901b0201.001", "901B0201.001", at(9, 29, 2, 53), at(9, 29, 2, 55)),
    ("results_901b0102.002", "901B0102.002", at(9, 29, 2, 55), at(9, 29, 2, 57)),
    ("attacks_mit_901b0201.002", "901B0201.002", at(9, 29, 3, 2), at(9, 29, 3, 4)),
    # Node 2's first upload after rolling into the due date: its rollovers of
    # 30 Sep - 2 Oct burned .003-.005, so the hub sees the gap and knows the late
    # result below arrived after the attacks were written off.
    ("rollover_901b0201.006", "901B0201.006", at(10, 2, 3, 3), at(10, 2, 3, 4)),
    ("results_late_901b0102.004", "901B0102.004", at(9, 29, 3, 4), at(10, 2, 3, 5)),
    # A later round with tanks and bombers, for the admin's forces reveal. Node 2
    # was REDATEd to 7 Oct for it; its stamps are moved to the hub's day below.
    ("forces_901b0201.013", "901B0201.013", at(9, 30, 11, 10), at(9, 30, 11, 12)),
    ("forces_results_901b0102.010", "901B0102.010", at(9, 30, 11, 14), at(9, 30, 11, 19)),
    # The next day's round: jets on carriers, and a win that captured regions.
    ("jets_901b0201.015", "901B0201.015", at(10, 1, 11, 18), at(10, 1, 11, 19)),
    ("jets_results_901b0102.012", "901B0102.012", at(10, 1, 11, 20), at(10, 1, 11, 21)),
    # Then a trade deal and Terrorist Ops, the last batch partly caught.
    ("trade_901b0201.017", "901B0201.017", at(10, 1, 11, 40), at(10, 1, 11, 41)),
    ("trade_report_901b0102.014", "901B0102.014", at(10, 1, 11, 42), at(10, 1, 11, 43)),
    ("tops_901b0201.019", "901B0201.019", at(10, 1, 11, 50), at(10, 1, 11, 51)),
    ("tops_partial_901b0102.016", "901B0102.016", at(10, 1, 11, 52), at(10, 1, 11, 53)),
]
# Node 2 was REDATEd a day further for each of those rounds; its game's dates
# map back to the hub's day like this (days to subtract, by October date).
REDATED = {7: 7, 8: 7, 9: 8, 10: 9}


def main():
    config = init_config(sys.argv[1] if len(sys.argv) > 1 else "config.toml")
    init_database(f"sqlite:///{config.database.path}")
    db = get_session()
    Base.metadata.create_all(bind=db.get_bind())      # the two new tables, if absent

    league = db.query(League).filter_by(league_id="901", game_type="B").first()
    if league is None:
        league = League(league_id="901", game_type="B", name=NAME, is_active=True)
        db.add(league)
        db.commit()
    league.name = NAME
    db.commit()

    hub = config._raw.get("hub", {}).get("bbs_index", "01").upper()
    processed = Path(config._raw["server"]["data_dir"]) / "packets" / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    for fixture, filename, reached, taken in SESSION:
        content = (FIXTURES / fixture).read_bytes()
        (processed / filename).write_bytes(content)
        p = db.query(Packet).filter_by(filename=filename, league_id=league.id).first()
        if p is None:
            p = Packet(filename=filename, league_id=league.id)
            db.add(p)
        p.source_bbs_index, p.dest_bbs_index = filename[4:6], filename[6:8]
        p.sequence_number = int(filename[-3:])
        p.file_size = len(content)
        p.checksum = hashlib.sha256(content).hexdigest()
        p.uploaded_at = reached
        if p.dest_bbs_index == hub:
            p.processed_at, p.is_processed = taken, True
        else:
            p.downloaded_at, p.is_downloaded = taken, True
        db.commit()
        attack_trace.record(db, p, content)
        print(f"  {filename}: {db.query(AttackSighting).filter_by(packet_id=p.id).count()} attack(s), "
              f"{db.query(TrafficSighting).filter_by(packet_id=p.id).count()} other")

    sightings = (db.query(AttackSighting).filter_by(league_id=league.id).all()
                 + db.query(TrafficSighting).filter_by(league_id=league.id).all())
    for s in sightings:
        if s.stamp and s.stamp.year == 2026 and s.stamp.month == 9 and s.stamp.day == 29:
            s.stamp -= SHIFT
        elif s.stamp and s.stamp.year == 2026 and s.stamp.month == 10 and s.stamp.day in REDATED:
            s.stamp -= timedelta(days=REDATED[s.stamp.day]) + SHIFT
    settings = db.get(LeagueGameSettings, league.id)
    if settings and settings.game_started_at and settings.game_started_at.day == 29:
        settings.game_started_at -= SHIFT
    db.commit()
    print(f"replayed into league {league.id} ({NAME})")


if __name__ == "__main__":
    main()
