"""The rest of the InterBBS traffic, strung into journeys like attacks are.

Three rig rounds in league 901B, real packets. Node 2's realm A on the first day:
two Terrorist Ops on planet 1's realm A (3 spies, 5 food bombings), a 3-day Spy
Guy, and three messages -- to realm 1A, to everyone on planet 1, and to every
planet. Back came a Spy Report and the bombings' result. Day two: a trade deal
to 1A (100 food, 1,000 gold) and 10 Demoralize ops on 1A, all of which worked;
back came the result and a Report that the deal arrived. Day three: 10
Demoralize ops on 1B, which had bought 80 agents -- 3 worked, "7 agents caught".

The rig cannot afford a Gooie or a Special Op. Their records are built here to
the layouts production's own traffic showed (not copied from it).
"""
import struct
from datetime import datetime

from backend.models.database import Packet, TrafficSighting
from backend.services import attack_trace, bre_packet, traffic_trace
from tests.test_attack_trace import HUB, api, db, league, raw, store, t  # noqa: F401

ROUNDS = [
    ("jets_901b0201.015", "901b0201.015", "jets_results_901b0102.012", "901b0102.012", 1),
    ("trade_901b0201.017", "901b0201.017", "trade_report_901b0102.014", "901b0102.014", 2),
    ("tops_901b0201.019", "901b0201.019", "tops_partial_901b0102.016", "901b0102.016", 3),
]
BASE = "/management/api/v1/traffic/"


def three_days(db, league):
    for out_fix, out_name, back_fix, back_name, day in ROUNDS:
        sent = store(db, league, out_fix, out_name, at=t("11:00", day=day, month=10),
                     taken=t("11:01", day=day, month=10))
        back = store(db, league, back_fix, back_name, at=t("11:02", day=day, month=10),
                     taken=t("11:05", day=day, month=10))
        sent.file_data, back.file_data = raw(out_fix), raw(back_fix)
    db.commit()


def journeys(db, **kw):
    return traffic_trace.journeys(
        traffic_trace.events(db, HUB, since=t("00:00", day=1, month=10), **kw))


def by_kind(js, kind):
    return [j for j in js if j.kind == kind]


# ── built records, for what the rig cannot afford ─────────────────────────
def built_packet(records):
    """A packet as BRE writes one. Payloads here hold no 0xFD, so the zero-run
    compressor would leave them as they are."""
    body = b""
    for rtype, src, dst, payload in records:
        assert b"\xfd" not in payload
        body += (bytes([rtype]) + struct.pack("<H", len(payload)) + bytes([src, dst])
                 + bre_packet.record_crc(payload) + payload)
    return bytes(12) + body + b"\x0f"


def news(src, dst, text):
    s = text.encode()
    return (bre_packet.NEWS, src, dst, bytes([src, dst, len(s)]) + s)


def store_built(db, league, name, records, at, taken):
    content = built_packet(records)
    p = Packet(filename=name, league_id=league.id, source_bbs_index=name[4:6],
               dest_bbs_index=name[6:8], sequence_number=int(name[-3:]),
               file_size=len(content), uploaded_at=at, file_data=content)
    if name[4:6] == HUB:
        p.processed_at = at
    if name[6:8] == HUB:
        p.processed_at = taken
    else:
        p.downloaded_at, p.is_downloaded = taken, True
    db.add(p)
    db.commit()
    attack_trace.record(db, p, content)


def a_gooie(db, league, killed=True):
    """Planet 2 funds a Gooie on planet 1: News of it, a warning, the Gooie, a
    day's result, and the kill."""
    store_built(db, league, "901B0201.101", [
        news(2, 1, "10/01/2026 00:25:00 - Gooie Kablooie funding completed on Raider Two."),
        news(2, 1, "10/02/2026 11:45:10 - Gooie Kablooie arrives from Raider Two in approximately 53 Hours."),
    ], t("01:00", day=2, month=10), t("01:05", day=2, month=10))
    store_built(db, league, "901B0201.102", [
        (bre_packet.GOOIE_ATTACK, 2, 1, bytes([1, 2, 0x64, 5]) + bytes(range(1, 9))),
    ], t("00:30", day=4, month=10), t("00:31", day=4, month=10))
    store_built(db, league, "901B0102.103", [
        (bre_packet.GOOIE_RESULTS, 1, 2, bytes([1, 2]) + struct.pack("<i", 7000) + b"\x64"),
    ] + ([news(1, 2, "Gooie Kablooie destroyed on Hub Target")] if killed else []),
        t("14:00", day=4, month=10), t("14:10", day=4, month=10))


def test_a_gooie_is_one_journey_from_its_funding_to_its_kill(db, league):
    a_gooie(db, league)
    j, = journeys(db)
    assert j.kind == "Gooie Kablooie" and j.stage == "destroyed"
    assert [e.kind for e in j.events] == ["Gooie Funded", "Gooie Warning", "Gooie Attack",
                                          "Gooie Results", "Gooie Destroyed"]
    assert (j.route.from_planet, j.route.to_planet) == (2, 1)


def test_a_gooie_not_yet_killed_is_active(db, league):
    a_gooie(db, league, killed=False)
    j, = journeys(db)
    assert j.stage == "active"


def test_news_that_is_not_about_a_gooie_is_not_recorded(db, league):
    store_built(db, league, "901B0201.104", [news(2, 1, "10/01/2026 Raider Two bought land.")],
                t("01:00", day=2, month=10), t("01:05", day=2, month=10))
    assert db.query(TrafficSighting).count() == 0


def test_special_and_bombing_ops_pair_with_their_results(db, league):
    who = b"AB" + struct.pack("<ii", 1000, 2000)
    store_built(db, league, "901B0201.105", [
        (bre_packet.SPECIAL_OP, 2, 1, who + bytes([2, 1, 1, 0, 0])),
        (bre_packet.BOMBING_OP, 2, 1, b"A" + struct.pack("<i", 1000) + bytes([2, 1, 4, 0, 46])),
    ], t("01:00", day=2, month=10), t("01:05", day=2, month=10))
    store_built(db, league, "901B0102.106", [
        (bre_packet.SPECIAL_RESULT, 1, 2, who + bytes([1, 2, 1, 16, 4])),
        (bre_packet.BOMBING_RESULT, 1, 2, b"A" + struct.pack("<i", 1000) + bytes([1, 2, 4, 0, 5])),
    ], t("02:00", day=2, month=10), t("02:05", day=2, month=10))
    js = journeys(db)
    assert sorted(j.kind for j in js) == ["Bombing Op", "Special Op"]
    assert all(j.stage == "result delivered" for j in js)
    sop, = by_kind(js, "Special Op")
    assert (sop.route.from_letter, sop.route.to_letter) == ("A", "B")


# ── the rig's rounds ──────────────────────────────────────────────────────
def test_every_send_finds_its_result(db, league):
    three_days(db, league)
    js = journeys(db)
    ops = by_kind(js, "Terrorist Op")
    assert len(ops) == 4 and all(j.stage == "result delivered" for j in ops)
    # The spies came home as a Spy Report; the rest as Terrorist Results.
    assert sorted(j.results[0].kind for j in ops) == \
        ["Spy Report", "Terrorist Result", "Terrorist Result", "Terrorist Result"]
    trade, = by_kind(js, "Trade Deal")
    assert [e.kind for e in trade.events] == ["Trade Deal", "Report"]
    assert trade.stage == "result delivered"


def test_who_did_what_to_whom(db, league):
    three_days(db, league)
    ops = by_kind(journeys(db), "Terrorist Op")
    assert {(j.route.from_planet, j.route.from_letter, j.route.to_planet, j.route.to_letter)
            for j in ops} == {(2, "A", 1, "A"), (2, "A", 1, "B")}


def test_a_result_whose_send_is_outside_the_window_still_shows(db, league):
    out_fix, out_name, back_fix, back_name, day = ROUNDS[2]
    store(db, league, back_fix, back_name, at=t("11:02", day=3, month=10))
    j, = journeys(db)
    assert j.send is None and j.kind == "Terrorist Result"
    assert (j.route.from_planet, j.route.to_letter) == (2, "B")


def test_messages_and_spy_guys_stand_alone(db, league):
    three_days(db, league)
    js = journeys(db)
    messages = by_kind(js, "Message")
    assert sorted(j.first.recipients for j in messages) == ["A", "AB", "all planets"]
    assert all(not j.expects_result and j.stage == "delivered" for j in messages)
    spy_guy, = by_kind(js, "Spy Guy")
    assert not spy_guy.expects_result


def test_a_recipient_never_seen_with_a_letter_is_a_question_mark(db, league):
    # Day one alone: nothing has yet named 1B, so "everyone on planet 1" is A?.
    out_fix, out_name, back_fix, back_name, day = ROUNDS[0]
    store(db, league, out_fix, out_name, at=t("11:00", day=1, month=10))
    assert sorted(j.first.recipients for j in by_kind(journeys(db), "Message")) == \
        ["A", "A?", "all planets"]


def test_sightings_hold_no_contents(db, league):
    columns = set(TrafficSighting.__table__.columns.keys())
    assert not columns & {"count", "sent", "succeeded", "goods", "text", "operation"}


# ── the endpoint ──────────────────────────────────────────────────────────
def listing(api):
    return api.get(BASE, params={"days": 365}).json()


def event_of(api, kind, **match):
    for j in listing(api):
        for e in j["events"]:
            if e["kind"] == kind and all(e[k] == v for k, v in match.items()):
                return e
    raise AssertionError(f"no {kind} {match}")


def test_listing_is_journeys_with_no_contents(api, db, league):
    three_days(db, league)
    got = listing(api)
    assert sorted(j["kind"] for j in got) == sorted(
        ["Terrorist Op"] * 4 + ["Trade Deal", "Spy Guy"] + ["Message"] * 3)
    banned = {"details", "sent", "succeeded", "goods", "text", "operation", "troopers"}
    assert all(not banned & set(j) and all(not banned & set(e) for e in j["events"])
               for j in got)


def test_an_admin_reveals_a_partly_failed_batch(api, db, league):
    three_days(db, league)
    e = event_of(api, "Terrorist Result", from_letter="B")
    got = api.get(BASE + e["key"] + "/details").json()
    assert got["details"] == {"operation": "Demoralize", "sent": 10, "succeeded": 3}


def test_an_admin_reveals_the_trade_goods_and_the_spy_report(api, db, league):
    three_days(db, league)
    trade = event_of(api, "Trade Deal")
    assert api.get(BASE + trade["key"] + "/details").json()["details"] == \
        {"goods": {"food": 100, "gold": 1000}}
    spy = event_of(api, "Spy Report")
    assert api.get(BASE + spy["key"] + "/details").json()["details"] == \
        {"realm": "Hub Target", "troopers": 69}
    report = event_of(api, "Report")
    assert api.get(BASE + report["key"] + "/details").json()["details"]["text"] == \
        "Trade Deal arrived at Hub Target (Test Hub 01)."


def test_an_admin_reveals_a_gooie_warning(api, db, league):
    a_gooie(db, league)
    warning = event_of(api, "Gooie Warning")
    assert "53 Hours" in api.get(BASE + warning["key"] + "/details").json()["details"]["text"]


def test_a_message_is_never_revealed_even_to_an_admin(api, db, league):
    three_days(db, league)
    m = next(j for j in listing(api) if j["recipients"] == "all planets")["events"][0]
    assert m["revealable"] is False
    assert api.get(BASE + m["key"] + "/details").status_code == 403


def test_only_an_admin_can_reveal(api, db, league):
    from tests.test_attack_trace import as_user
    three_days(db, league)
    trade = event_of(api, "Trade Deal")
    as_user(admin=False)
    assert api.get(BASE + trade["key"] + "/details").status_code == 403


def test_an_unknown_event_is_not_found(api):
    assert api.get(BASE + "0123456789abcdef/details").status_code == 404
