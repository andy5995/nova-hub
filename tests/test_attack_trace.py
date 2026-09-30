"""Following attacks through the hub, using the real packets from the rig.

The fixtures are one rig session in league 901B, replayed into the database with
the timings the hub would have recorded: node 2's three attacks on node 1 (the
hub's own board) and their results, then two more attacks whose results were
held back until node 2 had declared them Missing In Transit. That league's
coordinator had set "Days for Lost Attacks" to 1, and the Configupdate in the
result packets says so -- which is what the MIT judgement must use.
"""
import hashlib
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.models.database import (
    AttackSighting, Base, League, LeagueGameSettings, Packet,
)
from backend.services import attack_trace

FIXTURES = Path(__file__).parent / "fixtures" / "bre_packets"
HUB = "01"


def raw(name):
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def league(db):
    lg = League(league_id="901", game_type="B", name="Rig 901B")
    db.add(lg)
    db.commit()
    return lg


def t(hhmm, day=29, month=9):
    h, m = hhmm.split(":")
    return datetime(2026, month, day, int(h), int(m))


def store(db, league, fixture, filename, *, at, taken=None, trace=True):
    src, dst = filename[4:6].upper(), filename[6:8].upper()
    content = raw(fixture)
    p = Packet(filename=filename.upper(), league_id=league.id,
               source_bbs_index=src, dest_bbs_index=dst,
               sequence_number=int(filename[-3:]), file_size=len(content),
               checksum=hashlib.sha256(content).hexdigest(), uploaded_at=at)
    if src == HUB:
        p.processed_at = at          # the collector's time for what the hub wrote
    if taken:
        if dst == HUB:
            p.processed_at = taken
        else:
            p.downloaded_at = taken
            p.is_downloaded = True
    db.add(p)
    db.commit()
    if trace:
        attack_trace.record(db, p, content)
    return p


def upload(db, league, seq, at, source="02"):
    """A packet a board uploaded, for its sequence number and time alone."""
    db.add(Packet(filename=f"901B{source}01.{seq:03d}", league_id=league.id,
                  source_bbs_index=source, dest_bbs_index=HUB, sequence_number=seq,
                  file_size=0, uploaded_at=at))
    db.commit()


def rig_session(db, league):
    """The two rounds, with the times the hub would have seen."""
    store(db, league, "attacks_901b0201.001", "901b0201.001", at=t("02:53"), taken=t("02:55"))
    store(db, league, "results_901b0102.002", "901b0102.002", at=t("02:55"), taken=t("02:57"))
    store(db, league, "attacks_mit_901b0201.002", "901b0201.002", at=t("03:02"), taken=t("03:04"))
    # Node 2 rolls into the 30th, burning .003 -- and gives up on the two.
    upload(db, league, 4, t("00:12", day=30))
    # Collected by node 2 three days later -- after it had given up.
    store(db, league, "results_late_901b0102.004", "901b0102.004", at=t("03:04"),
          taken=t("03:05", day=2, month=10))


def by_id(db, **kw):
    return {j.attack_id: j for j in attack_trace.journeys(db, HUB, **kw)}


def test_a_packet_records_its_attacks_and_nothing_about_their_strength(db, league):
    store(db, league, "attacks_901b0201.001", "901b0201.001", at=t("02:53"))
    rows = db.query(AttackSighting).all()
    assert len(rows) == 3 and not any(r.is_result for r in rows)
    assert {(r.from_planet, r.attacker, r.to_planet, r.target) for r in rows} == {(2, "A", 1, "A")}
    assert "troopers" not in AttackSighting.__table__.columns


def test_recording_the_same_packet_twice_does_not_duplicate(db, league):
    p = store(db, league, "attacks_901b0201.001", "901b0201.001", at=t("02:53"))
    attack_trace.record(db, p, raw("attacks_901b0201.001"))
    assert db.query(AttackSighting).count() == 3


def test_a_reused_filename_replaces_what_the_row_carried(db, league):
    """The outbound collector rewrites the row when a sequence number wraps."""
    p = store(db, league, "attacks_901b0201.001", "901b0201.001", at=t("02:53"))
    attack_trace.record(db, p, raw("attacks_mit_901b0201.002"))
    assert db.query(AttackSighting).count() == 2


def test_falcons_eye_packets_are_left_alone(db):
    fe = League(league_id="900", game_type="F", name="FE")
    db.add(fe)
    db.commit()
    store(db, fe, "attacks_901b0201.001", "900f0201.001", at=t("02:53"))
    assert db.query(AttackSighting).count() == 0


def test_an_undecodable_packet_never_fails_ingest(db, league):
    p = store(db, league, "attacks_901b0201.001", "901b0201.001", at=t("02:53"), trace=False)
    assert attack_trace.record_safely(db, p, b"not a packet at all") == 0
    assert db.query(Packet).count() == 1


def test_the_coordinators_mit_window_is_remembered(db, league):
    rig_session(db, league)
    assert db.get(LeagueGameSettings, league.id).lost_attack_days == 1


def test_a_completed_round_trip(db, league):
    rig_session(db, league)
    j = by_id(db)
    first = [x for x in j.values() if x.attack_at_hub == t("02:53")]
    assert len(first) == 3
    for x in first:
        assert x.stage == "result delivered"
        assert (x.attack_delivered, x.result_at_hub, x.result_delivered) == \
            (t("02:55"), t("02:55"), t("02:57"))
        assert x.mit is None
        assert [h.is_result for h in x.hops] == [False, True]


def test_a_result_handed_over_after_the_window_is_late(db, league):
    """The game discards it; the hub can say so."""
    rig_session(db, league)
    late = [x for x in by_id(db).values() if x.mit]
    assert len(late) == 2
    assert all(x.mit == "late" and x.stage == "result delivered" for x in late)
    assert all(x.mit_due == datetime(2026, 9, 30) for x in late)
    assert {x.target for x in late} == {"A", "B"}


def test_the_window_closes_at_midnight_on_the_attackers_clock(db, league):
    """Boards keep local time, the hub UTC; production's run 10 to 13 hours
    ahead. Here node 2 is 10 hours ahead, and its result is handed over at 15:00
    on the 29th by the hub -- already 01:00 on the 30th for node 2, past midnight,
    so its game has thrown the attack away. Judged on the hub's clock it would
    look nine hours early."""
    ahead = timedelta(hours=10)
    store(db, league, "attacks_mit_901b0201.002", "901b0201.002",
          at=t("03:02") - ahead, taken=t("03:04") - ahead)
    store(db, league, "results_late_901b0102.004", "901b0102.004",
          at=t("03:04") - ahead, taken=t("15:00"))
    upload(db, league, 4, t("14:20"))      # its rollover into the 30th, its clock
    got = list(by_id(db).values())
    assert {x.attacker_clock for x in got} == {ahead}
    assert {x.mit_due_local for x in got} == {datetime(2026, 9, 30)}
    assert {x.mit_due for x in got} == {datetime(2026, 9, 29, 14, 0)}
    assert {x.mit for x in got} == {"late"}


def _second_round(db, league, result_taken):
    store(db, league, "attacks_mit_901b0201.002", "901b0201.002", at=t("03:02"), taken=t("03:04"))
    store(db, league, "results_late_901b0102.004", "901b0102.004", at=t("03:04"),
          taken=result_taken)
    return {x.mit for x in by_id(db).values()}


def test_a_result_taken_after_midnight_but_before_the_rollover_counts(db, league):
    """Production, 3 Sep: The Eclipse took a result at 00:06, its next run wrote
    .415, and only after that did it burn .416 rolling over. The rig confirms a
    result already in the inbound at the rollover run is imported first."""
    upload(db, league, 3, t("00:08", day=30))
    upload(db, league, 5, t("00:32", day=30))
    assert _second_round(db, league, t("00:06", day=30)) == {None}


def test_a_result_taken_while_the_board_rolled_over_is_possible(db, league):
    """Production, 6 Sep: the burn fell between 23:56 and 00:25 and the result was
    taken at 00:23. Packets cannot say which came first; the board's log can."""
    upload(db, league, 3, t("23:56"))
    upload(db, league, 5, t("00:25", day=30))
    assert _second_round(db, league, t("00:23", day=30)) == {"possible"}
    assert by_id(db)["ca9564ee5fb676f8"].rollover == (t("23:56"), t("00:25", day=30))


def test_without_a_rollover_seen_a_result_after_midnight_is_only_possible(db, league):
    assert _second_round(db, league, t("05:00", day=30)) == {"possible"}


def test_no_result_past_the_window_is_overdue(db, league, monkeypatch):
    rig_session(db, league)
    # Drop the first round's results, leaving those attacks waiting.
    first_ids = {x.attack_id for x in by_id(db).values() if x.attack_at_hub == t("02:53")}
    db.query(AttackSighting).filter(AttackSighting.is_result.is_(True),
                                    AttackSighting.attack_id.in_(first_ids)).delete()
    db.commit()
    monkeypatch.setattr(attack_trace, "_now", lambda: datetime(2026, 9, 29, 23, 0))
    assert {by_id(db)[i].mit for i in first_ids} == {None}
    monkeypatch.setattr(attack_trace, "_now", lambda: datetime(2026, 9, 30, 0, 1))
    stalled = [by_id(db)[i] for i in first_ids]
    assert {(x.stage, x.mit) for x in stalled} == {("awaiting result", "overdue")}


def test_a_result_the_attacker_has_not_collected(db, league):
    store(db, league, "attacks_901b0201.001", "901b0201.001", at=t("02:53"), taken=t("02:55"))
    store(db, league, "results_901b0102.002", "901b0102.002", at=t("02:55"))
    assert {x.stage for x in by_id(db).values()} == {"result awaiting pickup"}


def test_an_attack_the_hubs_game_has_not_run(db, league):
    store(db, league, "attacks_901b0201.001", "901b0201.001", at=t("02:53"))
    assert {x.stage for x in by_id(db).values()} == {"attack awaiting pickup"}


def test_find_one_attack_by_the_start_of_its_id(db, league):
    rig_session(db, league)
    assert list(by_id(db, attack_id="CA95")) == ["ca9564ee5fb676f8"]


def test_backfill_reads_files_whose_checksum_matches(db, league, tmp_path):
    processed = tmp_path / "packets" / "processed"
    outbound = tmp_path / "packets" / "outbound"
    processed.mkdir(parents=True)
    outbound.mkdir(parents=True)
    store(db, league, "attacks_901b0201.001", "901b0201.001", at=t("02:53"), trace=False)
    store(db, league, "results_901b0102.002", "901b0102.002", at=t("02:55"), trace=False)
    (processed / "901B0201.001").write_bytes(raw("attacks_901b0201.001"))
    # Same name, different packet: a later one after the sequence wrapped.
    (outbound / "901B0102.002").write_bytes(raw("results_late_901b0102.004"))

    counts = attack_trace.backfill(db, tmp_path)
    assert (counts["traced"], counts["mismatched"], counts["sightings"]) == (1, 1, 3)
    assert attack_trace.backfill(db, tmp_path)["packets"] == 1   # only the untraceable one


def test_backfill_carries_on_past_a_packet_it_cannot_decode(db, league, tmp_path):
    """Batched with a savepoint per packet: one bad packet must not lose the rest."""
    processed = tmp_path / "packets" / "processed"
    processed.mkdir(parents=True)
    junk = b"\x00" * 12 + b"\x07\xff\xff"            # a record header that runs off the end
    bad = Packet(filename="901B0201.007", league_id=league.id, source_bbs_index="02",
                 dest_bbs_index="01", sequence_number=7, file_size=len(junk),
                 checksum=hashlib.sha256(junk).hexdigest(), uploaded_at=t("02:50"))
    db.add(bad)
    db.commit()
    (processed / "901B0201.007").write_bytes(junk)
    store(db, league, "attacks_901b0201.001", "901b0201.001", at=t("02:53"), trace=False)
    (processed / "901B0201.001").write_bytes(raw("attacks_901b0201.001"))

    counts = attack_trace.backfill(db, tmp_path)
    assert (counts["failed"], counts["traced"], counts["sightings"]) == (1, 1, 3)
    db.rollback()                      # nothing pending may depend on the bad packet
    assert db.query(AttackSighting).count() == 3


def test_backfill_prefers_the_file_whose_checksum_matches_over_stale_file_data(
        db, league, tmp_path):
    """Production: a wrapped outbound row kept the old packet's bytes in file_data."""
    outbound = tmp_path / "packets" / "outbound"
    outbound.mkdir(parents=True)
    p = store(db, league, "results_901b0102.002", "901b0102.002", at=t("02:55"), trace=False)
    p.file_data = raw("results_late_901b0102.004")      # the row's previous occupant
    db.commit()
    (outbound / "901B0102.002").write_bytes(raw("results_901b0102.002"))
    counts = attack_trace.backfill(db, tmp_path)
    assert (counts["traced"], counts["mismatched"], counts["sightings"]) == (1, 0, 3)


def test_nodelists_are_not_counted_as_packets(db, league, tmp_path):
    text = b"HOST 01 ...\r\n"
    db.add(Packet(filename="BRNODES.901", league_id=league.id, source_bbs_index="01",
                  dest_bbs_index="00", sequence_number=0, file_size=len(text),
                  checksum=hashlib.sha256(text).hexdigest(), file_data=text))
    db.commit()
    assert attack_trace.backfill(db, tmp_path)["packets"] == 0


def test_a_relayed_hop_is_timed_by_when_the_hub_wrote_it(db, league):
    """Node 2 attacks node 3 through the hub: 02->01 is run by the hub's game,
    which writes the attack into 01->03. That row may be months old if its
    filename has wrapped; processed_at is when this packet was collected."""
    store(db, league, "attacks_901b0201.001", "901b0201.001", at=t("02:53"), taken=t("02:54"))
    relay = store(db, league, "attacks_901b0201.001", "901b0103.500",
                  at=datetime(2026, 1, 23), trace=False)
    relay.processed_at, relay.downloaded_at = t("02:54"), t("03:10")
    db.commit()
    attack_trace.record(db, relay, raw("attacks_901b0201.001"))
    j = next(iter(by_id(db).values()))
    assert [(h.source_bbs, h.dest_bbs, h.at_hub) for h in j.hops] == \
        [(2, 1, t("02:53")), (1, 3, t("02:54"))]
    assert j.attack_at_hub == t("02:53")


# ── the endpoint ──────────────────────────────────────────────────────────
@pytest.fixture
def api(db):
    from main import app, service_app, management_app
    from backend.core.database import get_db
    from backend.core.security import get_current_user
    from backend.models.database import SysopUser

    apps = (app, service_app, management_app)
    saved = {a: dict(a.dependency_overrides) for a in apps}
    for a in apps:
        a.dependency_overrides[get_db] = lambda: db
        a.dependency_overrides[get_current_user] = lambda: SysopUser(
            id=1, username="admin", hashed_password="x", is_superuser=True)
    yield TestClient(app)
    for a in apps:
        a.dependency_overrides.clear()
        a.dependency_overrides.update(saved[a])


BASE = "/management/api/v1/attacks/"


def test_endpoint_lists_journeys_without_unit_counts(api, db, league):
    rig_session(db, league)
    got = api.get(BASE, params={"days": 365}).json()
    assert len(got) == 5
    assert got[0]["league_name"] == "Rig 901B"
    assert all("troop" not in key for j in got for key in j)
    assert all(j["hops"] for j in got)


def test_endpoint_filters_to_mit(api, db, league):
    rig_session(db, league)
    got = api.get(BASE, params={"days": 365, "mit": "late"}).json()
    assert sorted(j["attack_id"] for j in got) == ["06bbbec123bcac00", "ca9564ee5fb676f8"]


def test_endpoint_rejects_an_id_that_is_not_hex(api):
    assert api.get(BASE, params={"attack_id": "nope"}).status_code == 422


# ── history the hub no longer holds ───────────────────────────────────────
def test_a_missing_relay_on_a_route_with_no_packets_then_is_not_called_mit(db, league, monkeypatch):
    """Production: 45 of 015B's attacks stop at the hub because the packet that
    relayed them was overwritten by an older collector. Nothing survives on that
    route from those hours, so the hub says so instead of crying MIT."""
    store(db, league, "attacks_mit_901b0201.002", "901b0201.002", at=t("03:02"), taken=t("03:04"))
    monkeypatch.setattr(attack_trace, "_now", lambda: datetime(2026, 10, 10))  # past the default 7 days
    # The hub's game resolved them for its own board; its reply to node 2 is gone.
    got = list(by_id(db).values())
    assert {(x.stage, x.mit, x.unheld_relay_to) for x in got} == {("relay not held", None, 2)}


def test_a_missing_relay_on_a_route_that_kept_its_packets_is_mit(db, league, monkeypatch):
    store(db, league, "attacks_mit_901b0201.002", "901b0201.002", at=t("03:02"), taken=t("03:04"))
    db.add(Packet(filename="901B0102.009", league_id=league.id, source_bbs_index=HUB,
                  dest_bbs_index="02", sequence_number=9, file_size=0,
                  uploaded_at=t("03:05"), processed_at=t("03:05")))   # carried something else
    db.commit()
    monkeypatch.setattr(attack_trace, "_now", lambda: datetime(2026, 10, 10))  # past the default 7 days
    got = list(by_id(db).values())
    assert {(x.stage, x.mit) for x in got} == {("awaiting result", "overdue")}


def test_a_reused_slot_from_months_before_does_not_count_as_held(db, league, monkeypatch):
    store(db, league, "attacks_mit_901b0201.002", "901b0201.002", at=t("03:02"), taken=t("03:04"))
    db.add(Packet(filename="901B0102.009", league_id=league.id, source_bbs_index=HUB,
                  dest_bbs_index="02", sequence_number=9, file_size=0,
                  uploaded_at=datetime(2026, 6, 7), processed_at=t("03:05")))
    db.commit()
    monkeypatch.setattr(attack_trace, "_now", lambda: datetime(2026, 10, 10))
    assert {x.stage for x in by_id(db).values()} == {"relay not held"}
