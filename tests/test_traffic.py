"""The rest of the InterBBS traffic, from three rig rounds in league 901B.

Node 2's realm A on the first day: two Terrorist Ops on planet 1's realm A (3
spies, 5 food bombings), a 3-day Spy Guy, and three messages -- to realm 1A, to
everyone on planet 1, and to every planet. Back came a Spy Report and the
bombings' result. Day two: a trade deal to 1A (100 food, 1,000 gold) and 10
Demoralize ops on 1A, all of which worked; back came the result and a Report
that the deal arrived. Day three: 10 Demoralize ops on 1B, which had bought 80
agents -- 3 worked, "7 agents caught".
"""
import pytest

from backend.models.database import TrafficSighting
from backend.services import traffic_trace
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


def listed(db, **kw):
    return traffic_trace.events(db, HUB, since=t("00:00", day=1, month=10), **kw)


def kinds(events):
    return sorted(e.name for e in events)


def test_every_kind_of_traffic_is_recorded_once_per_event(db, league):
    three_days(db, league)
    assert kinds(listed(db)) == sorted(
        ["Terrorist Op"] * 4 + ["Terrorist Result"] * 3 + ["Message"] * 3
        + ["Spy Guy", "Spy Report", "Trade Deal", "Report"])


def test_who_did_what_to_whom(db, league):
    three_days(db, league)
    ops = [e for e in listed(db) if e.name == "Terrorist Op"]
    assert {(e.from_planet, e.from_letter, e.to_planet, e.to_letter) for e in ops} == \
        {(2, "A", 1, "A"), (2, "A", 1, "B")}
    trade, = listed(db, record_type=0x18)
    assert (trade.from_planet, trade.from_letter, trade.to_planet, trade.to_letter) == \
        (2, "A", 1, "A")
    # A result travels back, from the target's board.
    results = [e for e in listed(db) if e.name == "Terrorist Result"]
    assert {(e.from_planet, e.from_letter, e.to_planet, e.to_letter) for e in results} == \
        {(1, "A", 2, "A"), (1, "B", 2, "A")}
    assert all(e.delivered for e in listed(db))


def test_each_result_is_paired_with_its_op(db, league):
    three_days(db, league)
    events = {e.key: e for e in listed(db)}
    results = [e for e in events.values() if e.name == "Terrorist Result"]
    assert all(r.paired_with for r in results)
    for r in results:
        op = events[r.paired_with]
        assert op.name == "Terrorist Op" and op.paired_with == r.key
        assert (op.from_letter, op.to_letter) == (r.to_letter, r.from_letter)
    # The spies came back as a Spy Report instead, so one op has no result.
    assert sum(1 for e in events.values() if e.name == "Terrorist Op" and not e.paired_with) == 1


def test_messages_name_their_recipients_and_nothing_else(db, league):
    three_days(db, league)
    messages = listed(db, record_type=0x09)
    assert sorted(m.recipients for m in messages) == ["A", "AB", "all planets"]
    assert all(m.from_letter == "A" and m.from_planet == 2 for m in messages)


def test_a_recipient_never_seen_with_a_letter_is_a_question_mark(db, league):
    # Day one alone: nothing has yet named 1B, so "everyone on planet 1" is A?.
    out_fix, out_name, back_fix, back_name, day = ROUNDS[0]
    store(db, league, out_fix, out_name, at=t("11:00", day=1, month=10))
    assert sorted(m.recipients for m in listed(db, record_type=0x09)) == \
        ["A", "A?", "all planets"]


def test_sightings_hold_no_contents(db, league):
    three_days(db, league)
    columns = set(TrafficSighting.__table__.columns.keys())
    assert not columns & {"count", "sent", "succeeded", "goods", "text", "operation"}


# ── the endpoint ──────────────────────────────────────────────────────────
def key_of(api, kind, **match):
    for e in api.get(BASE, params={"days": 365}).json():
        if e["kind"] == kind and all(e[k] == v for k, v in match.items()):
            return e
    raise AssertionError(f"no {kind} {match}")


def test_listing_carries_no_contents(api, db, league):
    three_days(db, league)
    got = api.get(BASE, params={"days": 365}).json()
    assert len(got) == 14
    banned = {"details", "sent", "succeeded", "goods", "text", "operation", "troopers"}
    assert all(not banned & set(e) for e in got)


def test_an_admin_reveals_a_partly_failed_batch(api, db, league):
    three_days(db, league)
    e = key_of(api, "Terrorist Result", from_letter="B")
    got = api.get(BASE + e["key"] + "/details").json()
    assert got["details"] == {"operation": "Demoralize", "sent": 10, "succeeded": 3}


def test_an_admin_reveals_the_trade_goods_and_the_spy_report(api, db, league):
    three_days(db, league)
    trade = key_of(api, "Trade Deal")
    assert api.get(BASE + trade["key"] + "/details").json()["details"] == \
        {"goods": {"food": 100, "gold": 1000}}
    spy = key_of(api, "Spy Report")
    assert api.get(BASE + spy["key"] + "/details").json()["details"] == \
        {"realm": "Hub Target", "troopers": 69}
    report = key_of(api, "Report")
    assert api.get(BASE + report["key"] + "/details").json()["details"]["text"] == \
        "Trade Deal arrived at Hub Target (Test Hub 01)."


def test_a_message_is_never_revealed_even_to_an_admin(api, db, league):
    three_days(db, league)
    m = key_of(api, "Message", recipients="all planets")
    assert m["revealable"] is False
    assert api.get(BASE + m["key"] + "/details").status_code == 403


def test_only_an_admin_can_reveal(api, db, league):
    from tests.test_attack_trace import as_user
    three_days(db, league)
    trade = key_of(api, "Trade Deal")
    as_user(admin=False)
    assert api.get(BASE + trade["key"] + "/details").status_code == 403


def test_an_unknown_event_is_not_found(api):
    assert api.get(BASE + "0123456789abcdef/details").status_code == 404
