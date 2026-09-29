"""Decoding real BRE packets, captured on the test rig in league 901B.

Node 2's realm "Raider Two" (A) attacked node 1's "Hub Target" (A) three times --
37 and 38 troopers Normal, 25 Quick Strike -- and later attacked "Second Target"
(B) with 5 and "Hub Target" with 6. The second pair's results were withheld until
node 2 had declared them Missing In Transit, then delivered late; the game
discarded them. The fixtures are those packets, byte for byte.
"""
from datetime import datetime
from pathlib import Path

import pytest

from backend.services import bre_packet as bp

FIXTURES = Path(__file__).parent / "fixtures" / "bre_packets"


def load(name):
    return (FIXTURES / name).read_bytes()


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.iterdir()
                                         if not p.name.startswith(".")))
def test_every_record_passes_its_checksum(name):
    records = bp.parse(load(name))
    assert records and all(r.crc_ok for r in records)


def test_decompressed_sizes_match_the_games_own_transcript():
    # /DETAILED printed "Old: 1448 ... Recon Update", "Old: 240 ... Configupdate",
    # "Old: 783 ... Player List" for this packet.
    sizes = {r.name: len(r.data) for r in bp.parse(load("relay_900B0103.002"))}
    assert sizes["Recon Update"] == 1448
    assert sizes["Configupdate"] == 240
    assert sizes["Player List"] == 783


def test_a_relayed_packet_keeps_each_records_own_source():
    pairs = {(r.src, r.dst) for r in bp.parse(load("relay_900B0103.002"))}
    assert pairs == {(1, 3), (2, 3)}


def test_attacks_decode():
    got = bp.attacks(load("attacks_901b0201.001"))
    assert [(a.from_planet, a.attacker, a.to_planet, a.target, a.attack_type)
            for a in got] == [(2, "A", 1, "A", "Normal"),
                              (2, "A", 1, "A", "Normal"),
                              (2, "A", 1, "A", "Quick Strike")]
    assert len({a.attack_id for a in got}) == 3
    assert not any(a.is_result for a in got)


def test_target_letter_is_distinct_from_attacker_letter():
    got = bp.attacks(load("attacks_mit_901b0201.002"))
    assert [(a.attacker, a.target) for a in got] == [("A", "B"), ("A", "A")]


def test_troop_counts_are_where_the_differential_put_them():
    recs = [r for r in bp.parse(load("attacks_901b0201.001"))
            if r.type == bp.INDIV_ATTACK]
    assert [bp.troopers(r) for r in recs] == [37, 38, 25]


def test_every_result_carries_its_attacks_id():
    sent = bp.attacks(load("attacks_901b0201.001"))
    back = bp.attacks(load("results_901b0102.002"))
    assert all(a.is_result for a in back)
    assert [a.attack_id for a in back] == [a.attack_id for a in sent]


def test_late_results_still_carry_the_id_of_the_attack_declared_mit():
    sent = bp.attacks(load("attacks_mit_901b0201.002"))
    late = bp.attacks(load("results_late_901b0102.004"))
    assert {a.attack_id for a in late} == {a.attack_id for a in sent}


def test_the_stamp_is_the_date_the_mit_report_prints():
    # report.bra on node 2: "Date: 09/29/2026  02:59:14  Result: Missing In Transit"
    stamp = bp.attacks(load("attacks_mit_901b0201.002"))[0].stamp
    assert stamp.replace(microsecond=0) == datetime(2026, 9, 29, 2, 59, 14)


def test_a_result_is_stamped_when_it_was_resolved():
    sent = bp.attacks(load("attacks_901b0201.001"))[0].stamp
    back = bp.attacks(load("results_901b0102.002"))[0].stamp
    assert back.replace(microsecond=0) == datetime(2026, 9, 29, 2, 55, 36)
    assert back > sent


def _settings(name):
    return bp.league_settings(
        next(r for r in bp.parse(load(name)) if r.type == bp.CONFIG_UPDATE))


def test_league_settings_as_reset_left_them():
    s = _settings("relay_900B0103.002")
    assert (s.protection_turns, s.indiv_attacks_per_day, s.lost_attack_days) == (20, 1, 7)


def test_league_settings_after_the_editor_changed_them():
    # BRE EDITOR on node 1: protection 0, ten attacks a day, MIT after one day.
    s = _settings("results_late_901b0102.004")
    assert (s.protection_turns, s.indiv_attacks_per_day, s.lost_attack_days) == (0, 10, 1)
    assert s.game_started_at == datetime(2026, 9, 29, 2, 20, 4)


def test_a_damaged_record_fails_its_checksum_rather_than_decoding_quietly():
    raw = bytearray(load("attacks_901b0201.001"))
    raw[-10] ^= 0x01          # inside the last record's payload, before the trailer
    assert not all(r.crc_ok for r in bp.parse(bytes(raw)))


def test_a_literal_fd_survives_decompression():
    """Found in production: 0xFD inside an attack ID is sent as FD 00, or bare
    when it is the last byte. Treating either as a zero run shifts the ID."""
    assert bp.unrle(bytes.fromhex("41fd03fd0042")) == bytes.fromhex("41000000fd42")
    assert bp.unrle(bytes.fromhex("58cbfd")) == bytes.fromhex("58cbfd")


def test_truncation_is_an_error():
    with pytest.raises(bp.PacketFormatError):
        bp.parse(load("attacks_901b0201.001")[:100])
