"""A packet is whatever a member uploads (#88).

The parser must stay small on input that decompresses to gigabytes, fail as a
PacketFormatError rather than anything else on damaged values, and the hub
must believe only what a packet's sender could have written: a member writes
its own records, never the coordinator's settings or Game Start.
"""
import struct
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.models.database import AttackSighting, GameReset, LeagueGameSettings
from backend.services import bre_packet
from backend.services.bre_packet import (
    MAX_PACKET_BODY,
    MAX_RECORD_BODY,
    PacketFormatError,
    Record,
    parse,
    real48,
    record_crc,
    timestamp,
)
from tests.test_attack_trace import db, league, store, t  # noqa: F401


def packet(*records):
    """A packet of (type, src, dst, payload) records, CRCs computed."""
    out = bytearray(bre_packet.HEADER_SIZE)
    for rtype, src, dst, payload in records:
        out += struct.pack("<BHBB", rtype, len(payload), src, dst) + record_crc(payload) + payload
    return bytes(out)


BOMB = b"\xfd\xff" * 30000     # 60 KB that would decompress to 7.6 MB


@pytest.mark.parametrize("good_crc", [True, False])
def test_a_record_that_decompresses_past_the_cap_is_refused_before_it_is_built(good_crc):
    data = packet((bre_packet.INDIV_ATTACK, 2, 1, BOMB))
    if not good_crc:
        data = data[:bre_packet.HEADER_SIZE + 5] + b"\0\0\0\0" + data[bre_packet.HEADER_SIZE + 9:]

    started = time.monotonic()
    with pytest.raises(PacketFormatError, match="decompresses past"):
        parse(data)
    assert time.monotonic() - started < 1


def test_a_packet_of_many_records_under_the_cap_still_has_a_budget():
    near_cap = b"\xfd\xff" * (MAX_RECORD_BODY // 255 - 1)
    count = MAX_PACKET_BODY // len(bre_packet.unrle(near_cap)) + 2
    with pytest.raises(PacketFormatError):
        parse(packet(*[(bre_packet.REPORT, 2, 1, near_cap)] * count))


def test_real_records_fit_well_inside_the_caps():
    from tests.test_attack_trace import raw
    for name in ("attacks_901b0201.001", "results_901b0102.002"):
        assert all(len(r.data) < MAX_RECORD_BODY // 4 for r in parse(raw(name)))


@pytest.mark.parametrize("raw", [b"", b"\x81", b"\xff" * 7])
def test_a_real_of_the_wrong_size_is_a_format_error(raw):
    with pytest.raises(PacketFormatError):
        real48(raw)


def test_a_date_no_calendar_holds_is_no_date():
    assert abs(real48(b"\xff" * 6)) > 1e37
    assert timestamp(b"\xff" * 6) is None


def test_a_damaged_record_is_a_format_error_on_reveal():
    for rtype in (bre_packet.SPY_REPORT, bre_packet.REPORT, bre_packet.NEWS, bre_packet.TRADE_DEAL):
        with pytest.raises(PacketFormatError):
            bre_packet.traffic_details(Record(rtype, 2, 1, True, b""))


def test_a_loss_that_is_not_a_fraction_is_unknown():
    from tests.test_attack_trace import raw
    result = next(r for r in parse(raw("results_901b0102.002"))
                  if r.type == bre_packet.ATTACK_RESULT)
    tail = bytearray(result.data)
    tail[bre_packet.ATTACK_SIZE + 21:bre_packet.ATTACK_SIZE + 27] = b"\x90" + b"\0" * 5  # 32768
    forces = bre_packet.forces(Record(result.type, 1, 2, True, bytes(tail)))
    assert forces.loss_fraction is None and forces.lost() is None


# -- who may say what -----------------------------------------------------------

def test_a_member_cannot_send_the_coordinators_settings(db, league):  # noqa: F811
    # The hub's real result packet, with its Configupdate, uploaded as node 2's.
    store(db, league, "results_901b0102.002", "901b0201.009", at=t("03:00"))
    assert db.query(LeagueGameSettings).count() == 0
    assert db.query(GameReset).count() == 0

    store(db, league, "results_901b0102.002", "901b0102.009", at=t("03:01"))
    assert db.query(LeagueGameSettings).one().lost_attack_days == 1


def test_a_member_cannot_send_records_in_another_boards_name(db, league):  # noqa: F811
    # Node 2's attacks, uploaded by node 3.
    store(db, league, "attacks_901b0201.001", "901b0301.001", at=t("02:53"))
    assert db.query(AttackSighting).count() == 0

    store(db, league, "attacks_901b0201.001", "901b0201.001", at=t("02:54"))
    assert db.query(AttackSighting).count() == 3
