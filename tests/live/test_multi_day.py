"""Scenario 8 - game time, and what it does to sequence numbers.

`REDATE.COM` hooks int 21h AH=2Ah (GET-DATE), which is exactly where Turbo
Pascal's GetDate goes, so the game sees a faked date and nothing else does.
`node_rig.run(..., date="YYYYMMDD")` installs it, runs the command, and removes
it again.

The reason this scenario is worth more than "days pass": it is the only way to
see what a real game does to sequence numbers over time, and what it does is not
what the hub assumes.

Two things about game time that every test here has to respect, both learned the
hard way on 2026-10-27:

1. Dates only move forward. The game refuses to run a date before its own last
   run, and a fresh RESET stamps the fixture with today, so no hardcoded
   constant survives contact with the calendar. These dates are derived.

2. WHICH game day emits a packet is governed by the absolute date, not by the
   day's index in the run. The same calendar dates emit regardless of where in a
   run they fall, measured across windows starting +1, +2, +3, +20, +36 and +67
   days from the reset. So "three consecutive game days" is not a repeatable
   quantity of traffic, and anything that needs N packets has to play until it
   has N packets rather than assume a fixed number of days will supply them.
   That is what _play_until is for.
"""
from datetime import date, timedelta

import pytest

from backend.models.database import Packet
from rig import node as node_rig
from rig.layout import HUB_INDEX, LEAGUES, NODES

pytestmark = pytest.mark.asyncio

LEAGUE = LEAGUES["900B"]
NODE02 = NODES[2]
HUB = NODES[HUB_INDEX]

# Game dates have to be strictly ahead of the game's own last run -- BRE refuses
# to run if the date precedes it -- and a fresh RESET stamps the fixture with
# today's date. So hardcoded constants work only until the wall clock passes
# them. These were "20261001".."20261006" and on 2026-10-26 all nine tests in
# this file failed with "nothing reached the hub": the game silently declined to
# run 25 days backwards and emitted no packets, which looks like a routing bug
# and is not one. Derive them from today instead, starting the day after the
# reset so DAY1 is itself an unplayed game day.
#
# Only three are named. The tests that need a known quantity of traffic rather
# than a known number of days use _play_until, for the reason in point 2 of the
# module docstring.
_FIRST_GAME_DAY = date.today() + timedelta(days=1)
DAY1, DAY2, DAY3 = (
    (_FIRST_GAME_DAY + timedelta(days=n)).strftime("%Y%m%d") for n in range(3)
)

# Node 02's route to the hub, and the hub's to node 01. A packet filename is
# <league><game><source><dest>.<seq>, so these select "sent by that node".
ROUTE_02 = "900b0201."
ROUTE_HUB = "900b0102."


def _maintenance_fired(log_path) -> bool:
    text = log_path.read_bytes().decode("latin-1")
    return "Running Daily Maintenance" in text


def _play(node, prefix, days, tag):
    """Play `days` consecutive game days. Returns a list per day of filenames.

    Each day's packets are collected and removed, so a day's entry is what that
    day produced rather than everything still sitting in OUTBOUND.

    Asserts maintenance on every day, which is the control: an empty day has to
    mean "the game ran and had nothing to send", not "the game did not run".
    """
    out = []
    for n in range(days):
        day = (_FIRST_GAME_DAY + timedelta(days=n)).strftime("%Y%m%d")
        log = node_rig.run(LEAGUE, node, "PLANETARY", tag=f"{tag}{n}", date=day)
        assert _maintenance_fired(log), (
            f"game day {n + 1} ({day}) did not run maintenance, so a silent day "
            f"here would not mean anything"
        )
        out.append([
            name for name, _ in node_rig.take_outbound(LEAGUE, node)
            if name.lower().startswith(prefix)
        ])
    return out


def _play_until(node, prefix, want, tag, max_days=15):
    """Play game days until `want` packets have been emitted.

    Bounded-length rather than fixed-length ON PURPOSE. Which game day emits is
    a property of the calendar the faked dates land on, not of the game day's
    index -- see the module docstring -- so "three consecutive days" buys an
    unknown number of packets and "until three packets" buys a known one.

    Returns (days, packets): one entry per day played, and the flat list.
    """
    days, packets = [], []
    while len(packets) < want:
        if len(days) >= max_days:
            raise AssertionError(
                f"only {len(packets)} packet(s) in {max_days} game days "
                f"({packets}). An idle league is sparse but it is not silent; "
                f"if this is now reliably true the game's traffic has changed."
            )
        n = len(days)
        day = (_FIRST_GAME_DAY + timedelta(days=n)).strftime("%Y%m%d")
        log = node_rig.run(LEAGUE, node, "PLANETARY", tag=f"{tag}{n}", date=day)
        assert _maintenance_fired(log), (
            f"game day {n + 1} ({day}) did not run maintenance"
        )
        today = [
            (name, payload) for name, payload in node_rig.take_outbound(LEAGUE, node)
            if name.lower().startswith(prefix)
        ]
        days.append(today)
        packets.extend(today)
    return days, packets


def _numbers(packets):
    return [int(name.rsplit(".", 1)[1]) for name, _ in packets]


async def test_daily_maintenance_fires_once_per_game_day(pristine):
    """The control that makes every other date-based result meaningful.

    If maintenance fired on every invocation regardless, a faked date would
    prove nothing -- the game would just be doing the same thing twice. It does
    not: a repeat of a date already played is skipped.
    """
    pristine("900B")

    first = node_rig.run(LEAGUE, NODE02, "PLANETARY", tag="d2a", date=DAY2)
    assert _maintenance_fired(first), "maintenance did not run on a new game day"

    again = node_rig.run(LEAGUE, NODE02, "PLANETARY", tag="d2b", date=DAY2)
    assert not _maintenance_fired(again), (
        "maintenance ran twice for the same game day - the game is not tracking "
        "the faked date, so no date-based assertion here means anything"
    )


async def test_sequence_numbers_are_not_dense_across_days(pristine):
    """The finding this scenario exists for.

    The hub's gap detector assumes a route's sequence numbers are dense: any
    number it has not seen is a lost packet. A real game does not honour that.
    Playing consecutive days on one install skips numbers with nothing lost and
    nothing wrong -- the game consumes sequence numbers for traffic it decides
    not to send.

    This test does not assert a particular pattern of skips, because the pattern
    is not stable. It asserts the property that matters: the numbers advance by
    MORE than one per emitted packet, so density cannot be relied on.
    """
    pristine("900B")
    _, packets = _play_until(NODE02, ROUTE_02, 3, "m")
    seen = _numbers(packets)

    assert len(seen) >= 2, f"not enough packets: {seen}"
    assert seen == sorted(seen), f"sequence went backwards: {seen}"
    span = seen[-1] - seen[0]
    assert span > len(seen) - 1, (
        f"sequence numbers {seen} were dense across game days. If this is now "
        f"reliably true, the gap detector's assumption holds and "
        f"docs/ROLLOUT_PLAN.md card B-4 should be revisited"
    )


async def test_an_uncollected_packet_is_rewritten_in_place(pristine):
    """Running again while a packet is still pending rewrites it, same number.

    The sequence number is not re-allocated: the pending file keeps its name and
    gains the new traffic. Measured across three runs on one game day -- 176,
    232, then 288 bytes under the same filename, a different hash each time.

    This matters to the hub for a reason that has nothing to do with sequence
    numbers: a packet sitting in a game OUTBOUND folder is not a finished
    artefact. Its *contents* change under a stable name until something collects
    it. Anything that reads a packet, leaves it there, and trusts it later is
    reading a file that may since have grown.
    """
    pristine("900B")
    hub_node = HUB

    node_rig.run(LEAGUE, hub_node, "PLANETARY", tag="ip1", date=DAY1)
    first = node_rig.outbound(LEAGUE, hub_node)
    assert first, "no packet to rewrite"
    name = first[0]
    path = LEAGUE.install_path(hub_node) / "OUTBOUND" / name
    before = path.read_bytes()

    # Same game day, more traffic, packet deliberately left in place.
    node_rig.run(LEAGUE, hub_node, "REQUEST", tag="ip2", date=DAY1)
    node_rig.run(LEAGUE, hub_node, "OUTBOUND", tag="ip3", date=DAY1)

    after_names = node_rig.outbound(LEAGUE, hub_node)
    assert name in after_names, (
        f"the pending packet was renamed: {first} became {after_names}"
    )
    after = path.read_bytes()
    assert after != before, "the pending packet was not rewritten at all"
    assert len(after) > len(before), (
        f"expected the pending packet to gain traffic, {len(before)} -> {len(after)}"
    )


async def test_a_game_day_consumes_a_sequence_number_whether_it_emits_or_not(
    pristine,
):
    """Where production's gap alerts come from, stated exactly.

    This used to assert "one file per game day, numbering advances by two",
    measured as .002, .004, .006 across three consecutive days. That holds only
    when every day emits, and most days do not -- so the test was really
    asserting a property of the three calendar dates it happened to use.

    The actual law, measured over 60+ game days across seven different date
    windows with no exceptions:

        every game day consumes ONE sequence number;
        a day that emits consumes TWO and writes its packet at the second.

    So after D game days of which E emitted, the highest number issued is
    D + E. Worked through one 20-day window: days 1, 5, 6, 11, 12, 16 and 19
    emitted, giving .002 .007 .009 .015 .017 .022 .026 -- and 19 + 7 = 26.

    That is what the gap detector is up against. The unused numbers are not
    lost packets; they are quiet days.
    """
    pristine("900B")
    days, packets = _play_until(HUB, ROUTE_HUB, 3, "t")
    numbers = _numbers(packets)

    assert numbers == sorted(numbers), f"sequence went backwards: {numbers}"

    # The last day played is an emitting one -- _play_until stops on the packet
    # that completes the count -- so D + E is exactly the number it wrote.
    assert numbers[-1] == len(days) + len(packets), (
        f"the numbering law changed: {len(days)} game days and {len(packets)} "
        f"packets {numbers} should put the last packet at "
        f"{len(days) + len(packets)}, not {numbers[-1]}. Either a game day no "
        f"longer consumes a number, or an emitting day no longer consumes two."
    )

    steps = [b - a for a, b in zip(numbers, numbers[1:])]
    assert all(s > 1 for s in steps), (
        f"sequence numbers {numbers} advanced densely. If that is now reliably "
        f"true, the gap detector's assumption holds and ROLLOUT_PLAN card B-4 "
        f"should be revisited"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "B-4's stride learner only protects a REGULARLY emitting route. This "
        "one is sparse (steps of 5 then 2), no stride clears STRIDE_DOMINANCE, "
        "the learner falls back to a stride of 1, and five false alerts come "
        "back on a route where nothing was lost. Not a rig artefact and not a "
        "date artefact -- see the body. Raised as a finding rather than "
        "weakened; strict so that fixing the detector fails this and makes "
        "someone turn it back into a plain assertion."
    ),
)
async def test_the_gap_detector_stays_quiet_when_nothing_was_lost(pristine, hub):
    """The test that reproduced production's 705 false alerts, now inverted.

    Every packet this node produced is delivered to the hub. None is lost, none
    is delayed, nothing is out of order -- but the game skipped sequence numbers
    of its own accord on the days it stayed quiet. The detector used to alert on
    every one of those, which is the entire content of production's alert table.

    ROLLOUT_PLAN card B-4. This was xfail, then a plain assertion once the
    detector learned that a route's numbering is its own business, and is xfail
    again for a narrower and more interesting reason.

    B-4 learns the dominant step between a route's consecutive numbers and
    accepts it only when at least two steps agree and one value holds
    STRIDE_DOMINANCE (60%) of them. That works on production's BRE leagues,
    which number densely -- the validator's own notes record 1000 packets
    covering 1000 numbers, every step exactly 1 -- because those nodes run and
    emit every day.

    An idle league does not emit every day. Measured here: .002, .007, .009,
    steps of 5 and 2, no agreement, no stride, fall back to 1, and five alerts
    for numbers the game simply never issued:

        expected 003, received 007 (gap of 4)
        expected 004, received 007 (gap of 4)
        expected 005, received 007 (gap of 4)
        expected 006, received 007 (gap of 4)
        expected 008, received 009 (gap of 1)

    So the 705 false alerts are suppressed for a node that emits daily and
    return for one that does not. Production's BRE nodes currently emit daily,
    which is why the fix held there; a quiet or intermittently run BRE node
    would bring them back. Telling that apart from a real loss needs the game's
    own record of what it sent (ROUTEINFO), which is the same conclusion B-4
    reached for Falcon's Eye.
    """
    from backend.services.sequence_validator import SequenceValidator

    pristine("900B")
    hub.seed(["900B"])

    _, packets = _play_until(NODE02, ROUTE_02, 3, "g")
    delivered = []
    for name, payload in packets:
        hub.deliver(name, payload)
        delivered.append(name)

    assert len(delivered) >= 3, f"not enough traffic to test with: {delivered}"

    alerts = SequenceValidator(hub.db).check_sequences()
    assert alerts == [], (
        f"delivered every packet the game produced ({delivered}) and the gap "
        f"detector raised {len(alerts)} alert(s): "
        + "; ".join(a.description for a in alerts)
    )


async def test_an_idle_league_emits_sparsely_but_never_stops(pristine):
    """An idle league is sparse. It does NOT go quiet, which is what this said.

    The claim here was "six game days, three packets, days four onward emit
    nothing at all", asserted as the exact pattern [1, 1, 1, 0, 0, 0]. That
    pattern was real but it was not a property of the game: it was a property of
    the six calendar dates the test hardcoded. Playing twenty consecutive game
    days instead gives

        [1, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 1, 0, 0, 0, 1, 0, 0, 1, 0]

    -- seven packets, still arriving on day 19, with maintenance firing on all
    twenty. Emission follows the absolute date, not the game day index: the same
    calendar dates emit no matter which day of the run they land on, confirmed
    across windows starting +1, +2, +3, +20, +36 and +67 days from the fixture's
    reset. Oct 31 and Nov 1 emitted in every window that contained them, at
    indices 4/5, 3/4 and 2/3 respectively.

    Two consequences. The first is that no derived date sequence can restore the
    old assertion, so this asserts the shape instead of the schedule. The second
    is the caution the old version was right about for the wrong reason: silence
    from a node is not evidence of a fault, and a health check built on "a
    packet a day" would cry wolf -- not because an idle node stops, but because
    it never emitted daily in the first place.
    """
    pristine("900B")

    produced = _play(NODE02, ROUTE_02, 8, "i")
    counts = [len(day) for day in produced]

    assert counts[0] == 1, (
        f"the first game day after a restore should emit the opening packet, "
        f"got {counts}"
    )
    assert all(c <= 1 for c in counts), (
        f"a game day emitted more than one packet on this route: {produced}"
    )
    assert 0 in counts[1:], (
        f"every game day emitted. An idle league is not supposed to be chatty: "
        f"{produced}"
    )
    assert 2 <= sum(counts) < len(counts), (
        f"expected sparse-but-present traffic over {len(counts)} game days, got "
        f"{sum(counts)} packet(s): {produced}. Nothing at all would mean the "
        f"game stopped running; one per day would mean it now emits densely, "
        f"and either is worth looking at rather than asserting around."
    )


async def test_a_stale_false_alert_resolves_itself(pristine, hub):
    """Production carries 705 of these. Nobody is going to close them by hand.

    Plant an alert at a number the games never issue -- exactly the shape of the
    rows sitting in production -- and confirm the next auto-resolve pass retires
    it with a note saying why, rather than leaving it for an operator to tell
    apart from a real one.
    """
    from backend.models.database import SequenceAlert
    from backend.services.sequence_validator import SequenceValidator

    pristine("900B")
    hub.seed(["900B"])

    for tag, date in (("s1", DAY1), ("s2", DAY2), ("s3", DAY3)):
        node_rig.run(LEAGUE, NODE02, "PLANETARY", tag=tag, date=date)
        for name, payload in node_rig.take_outbound(LEAGUE, NODE02):
            if name.lower().startswith("900b0201."):
                hub.deliver(name, payload)

    # source/dest are stored as the two-character hex text from the filename.
    packet = hub.db.query(Packet).filter(
        Packet.source_bbs_index == "02", Packet.dest_bbs_index == "01"
    ).order_by(Packet.sequence_number).first()
    assert packet is not None, "no packet reached the hub"

    stale = SequenceAlert(
        league_id=packet.league_id,
        source_bbs_index=packet.source_bbs_index,
        dest_bbs_index=packet.dest_bbs_index,
        expected_sequence=packet.sequence_number + 1,
        received_sequence=packet.sequence_number + 2,
        gap_size=1,
        description="planted: the shape of the rows in production",
    )
    hub.db.add(stale)
    hub.db.commit()

    assert SequenceValidator(hub.db).auto_resolve_alerts() == 1
    hub.db.refresh(stale)
    assert stale.is_resolved
    assert "never issued" in stale.resolution_note


async def test_a_processing_run_resolves_stale_alerts_by_itself(pristine, hub):
    """auto_resolve_alerts() had no caller anywhere until 2026-09-12.

    That is why production accumulated 213 alerts for packets that had arrived
    months earlier: nothing ever asked. Resolving is now part of a processing
    run, so this asserts the wiring and not just the function.
    """
    from backend.models.database import SequenceAlert

    pristine("900B")
    hub.seed(["900B"])

    for tag, date in (("w1", DAY1), ("w2", DAY2), ("w3", DAY3)):
        node_rig.run(LEAGUE, NODE02, "PLANETARY", tag=tag, date=date)
        for name, payload in node_rig.take_outbound(LEAGUE, NODE02):
            if name.lower().startswith("900b0201."):
                hub.deliver(name, payload)

    packet = hub.db.query(Packet).filter(
        Packet.source_bbs_index == "02", Packet.dest_bbs_index == "01"
    ).order_by(Packet.sequence_number).first()
    assert packet is not None, "no packet reached the hub"

    stale = SequenceAlert(
        league_id=packet.league_id,
        source_bbs_index=packet.source_bbs_index,
        dest_bbs_index=packet.dest_bbs_index,
        expected_sequence=packet.sequence_number + 1,
        received_sequence=packet.sequence_number + 2,
        gap_size=1,
        description="planted: the shape of the rows in production",
    )
    hub.db.add(stale)
    hub.db.commit()

    await hub.process()

    hub.db.refresh(stale)
    assert stale.is_resolved, (
        "a processing run did not resolve a stale alert -- "
        "auto_resolve_alerts() is unwired again"
    )


async def test_a_multi_day_round_trip_still_processes(pristine, hub):
    """Whatever the numbering does, the packets themselves must still flow.

    The point of separating this from the sequence assertions: a false alert is
    noise, but silently failing to process real multi-day traffic would be an
    outage.
    """
    pristine("900B")
    hub.seed(["900B"])

    for tag, date in (("r1", DAY1), ("r2", DAY2)):
        node_rig.run(LEAGUE, NODE02, "PLANETARY", tag=tag, date=date)
        for name, payload in node_rig.take_outbound(LEAGUE, NODE02):
            if name.lower().startswith("900b0201."):
                hub.deliver(name, payload)

    queued = hub.spool("inbound")
    assert queued, "nothing reached the hub across two game days"

    await hub.process()

    run = hub.last_run()
    assert run.status == "completed", f"run {run.status}: {run.error_message}"
    assert run.packets_unconsumed == 0
    assert hub.game_inbound("900B") == []
    assert hub.transcript(run).ingested_from(2)
    assert sorted(hub.spool("processed")) == sorted(queued)
