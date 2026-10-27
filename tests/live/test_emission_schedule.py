"""Scenario 8b - WHICH game days emit, and why. Both games.

test_multi_day.py measures what a game day does to sequence numbers. This
measures which game days produce a packet at all, which turned out to be the
simpler question of the two once it was asked properly.

The schedule is a function of the ABSOLUTE date, not of the game day's index in
a run -- the same calendar dates emit wherever in a run they fall, measured
across windows starting +1, +2, +3, +20, +36 and +67 days from a reset. For a
while this looked irregular: a 20-day BRE window emitted on game days 1, 5, 6,
11, 12, 16 and 19, the inter-packet number gaps repeated on a 35-day cycle as
[5, 2, 6, 2, 5, 4, 3, 6, 6, 3, 4], and "day of month mod 5" fitted most of it
and then failed on two dates.

It is not irregular. It is two metronomes:

    BRE emits when (ordinal mod 5 == 1) or the day is a SATURDAY
    FE  emits when (ordinal mod 4 == 2)

where `ordinal` is date.toordinal(). BRE's 35-day "cycle" is just lcm(5, 7), its
11 packets per cycle are 7 + 5 - 1 for the single day the two series collide,
and the two dates that broke the mod-5 guess -- Nov 7 and Nov 14 2026 -- are
Saturdays. Nothing more complicated than a weekly event and a five-day one,
which is the level of machinery the rest of these games run on.

A coincidence day still produces ONE packet, not two: the schedule decides
whether the game has something to say, not how many times it says it.

The first game day after a restore always emits as well, whatever the date --
the opening packet, always `.002`. That is the world coming into existence
rather than a scheduled event, so it is excluded from the comparisons here.

Both windows are DERIVED from a phase rather than hardcoded, because dates only
move forward: the game refuses to run a date before its own last run, and a
fresh RESET stamps the fixture with today. A hardcoded window works until the
wall clock passes it, which has already broken this scenario's tests once. A
phase works forever -- `_window_from` walks to the next date with the phase it
needs, so the pattern under test is identical whenever it runs.

The rule is re-derivable with `rig/calendar_probe.py`, which plays a window and
fits (a mod p) or (b mod q) over every p and q up to 10 rather than assuming
this answer. Against BRE it returns exactly one fit; against FE every fit it
returns is the 4-day series restated.
"""
from datetime import date, timedelta

import pytest

from rig import node as node_rig
from rig.layout import LEAGUES, NODES

pytestmark = pytest.mark.asyncio

NODE02 = NODES[2]


def _window_from(phase: int, modulus: int) -> date:
    """The next date at or after tomorrow with `ordinal % modulus == phase`.

    Tomorrow, not today: a fresh fixture has already been stamped with today, so
    the first game day a scenario plays has to be ahead of it.
    """
    start = date.today() + timedelta(days=1)
    while start.toordinal() % modulus != phase:
        start += timedelta(days=1)
    return start


def _emissions(pristine, league_id, node, start, days, tag):
    """Play `days` game days from `start`. Returns a list of packets per day."""
    league = LEAGUES[league_id]
    pristine(league_id)
    prefix = f"{league.league_id}{node.index:02x}01.".lower()

    out = []
    for n in range(days):
        day = start + timedelta(days=n)
        node_rig.run(league, node, "PLANETARY", tag=f"{tag}{n}",
                     date=day.strftime("%Y%m%d"))
        out.append([
            name for name, _ in node_rig.take_outbound(league, node)
            if name.lower().startswith(prefix)
        ])
    return out


def _report(start, per_day, predicted):
    lines = []
    for n, (got, want) in enumerate(zip(per_day, predicted)):
        day = start + timedelta(days=n)
        mark = " " if len(got) == want else " <-- "
        lines.append(f"{mark}day {n + 1:2d} {day:%a %Y-%m-%d} "
                     f"predicted {want}, got {len(got)} {got}")
    return "\n".join(lines)


async def test_bre_emits_on_a_five_day_series_and_every_saturday(pristine):
    """Thirteen game days chosen to contain one of each kind of day.

    Day 1 is the opening packet. Day 6 is the collision -- both series fire and
    the game still emits exactly one packet. Day 11 is the five-day series
    alone, day 13 is a Saturday alone, and the eight others are silent. A rule
    with one series, or a rule keyed to the day of the month, cannot produce
    this shape.
    """
    # ordinal % 35 == 1 puts day 1 on the five-day series with the collision on
    # day 6. 35 is lcm(5, 7), so this fixes the phase of both series at once.
    start = _window_from(phase=1, modulus=35)
    predicted = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 1]

    per_day = _emissions(pristine, "900B", NODE02, start, len(predicted), "es")

    assert [len(d) for d in per_day] == predicted, (
        "BRE's emission schedule is not (ordinal mod 5 == 1) or Saturday:\n"
        + _report(start, per_day, predicted)
    )

    # Say out loud which day was which, so a failure above is readable.
    assert (start + timedelta(days=5)).toordinal() % 5 == 1
    assert (start + timedelta(days=5)).weekday() == 5, "day 6 should be a Saturday"
    assert (start + timedelta(days=12)).weekday() == 5, "day 13 should be a Saturday"
    assert (start + timedelta(days=12)).toordinal() % 5 != 1, (
        "day 13 is meant to be the weekly series on its own"
    )


async def test_falcons_eye_emits_on_a_four_day_series_and_nothing_else(pristine):
    """FE is the simpler of the two: one metronome, every fourth day.

    No weekly component -- measured over 35 consecutive game days, where the
    number deltas were a flat 5 (four rollover days plus the packet) with no
    exceptions, and the fit search returned nothing but the four-day series
    restated. This is the cadence production FE has always appeared to run on.

    Twelve days with the phase set so day 1 is the opening packet only and the
    series lands on days 4, 8 and 12. Three emissions is the least that can tell
    a four-day period from an eight-day one.
    """
    start = _window_from(phase=3, modulus=4)
    predicted = [1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1]

    per_day = _emissions(pristine, "900F", NODE02, start, len(predicted), "ef")

    assert [len(d) for d in per_day] == predicted, (
        "FE's emission schedule is not (ordinal mod 4 == 2):\n"
        + _report(start, per_day, predicted)
    )
    assert all((start + timedelta(days=n)).toordinal() % 4 == 2 for n in (3, 7, 11))


async def test_the_two_games_do_not_share_a_schedule(pristine):
    """Stated as its own assertion because it is the reason FE needed measuring.

    The consumption law is the same in both games -- one number burned per game
    day, one per packet -- and it would have been easy to assume the schedule
    came with it. It does not. BRE's 11 packets per 35 days against FE's 1 per 4
    is the difference between a route the hub's density gate exempts and one it
    very nearly does not, and it is why the gate separates the two games rather
    than the busy nodes from the quiet ones.

    This plays the same twelve calendar days to both games, so the comparison is
    not an artefact of two different windows.
    """
    start = _window_from(phase=1, modulus=35)
    days = 12

    bre = [len(d) for d in _emissions(pristine, "900B", NODE02, start, days, "cb")]
    fe = [len(d) for d in _emissions(pristine, "900F", NODE02, start, days, "cf")]

    assert bre != fe, (
        f"both games emitted on the same days from {start} ({bre}), so either "
        f"the schedules have converged or this scenario is not measuring what "
        f"it thinks it is"
    )
    # Neither is a subset of the other: these are genuinely different series,
    # not one game emitting on a subset of the other's days.
    bre_days = {n for n, c in enumerate(bre) if c and n}
    fe_days = {n for n, c in enumerate(fe) if c and n}
    assert bre_days - fe_days and fe_days - bre_days, (
        f"BRE emitted on days {sorted(bre_days)} and FE on {sorted(fe_days)} "
        f"(0-based, opening day excluded); one series contains the other"
    )
