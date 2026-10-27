"""Probe: is the emission schedule two metronomes rather than an irregular cycle?

The recorded BRE finding was "irregular and not reducible to a simple rule",
with a 35-day cycle and delta pattern [5,2,6,2,5,4,3,6,6,3,4]. But 35 = 5 x 7,
and the day-gaps [4,1,5,1,4,3,2,5,5,2,3] fit the union of two fixed periodic
series exactly:

    emit when (ordinal mod 5 == 1) or (ordinal mod 7 == 6)   [= every Saturday]

That reproduces all three measured windows (the 20-day one, Dec 1-6 and
Jan 1-6) with no exceptions, and explains the "failures" of a mod-5 rule --
Nov 7 and Nov 14 -- as members of the weekly series. 11 packets per 35 days is
7 + 5 - 1 overlap, and lcm(5,7) = 35 is the whole of the "cycle".

So this plays a chosen window, records which game days emit, and fits
(a mod p) or (b mod q) over small p and q. It takes a league so the same
question can be put to Falcon's Eye, which is unmeasured.

Run from tests/live:

    sudo -u novahub-t env NOVATEST_RIG=1 /srv/novatest/venv/bin/python \
        rig/calendar_probe.py <league> <node> <start YYYYMMDD> <days> [forced]

Measured answers, 2027-03 windows on novatest-hl:

    900B  (ordinal mod 5 == 1) or (ordinal mod 7 == 6, i.e. Saturday)
          11 packets per 35 days; unique fit over all p, q <= 10
    900F  (ordinal mod 4 == 2)
          1 packet per 4 days; every fit returned is this one restated

Pass a forced count to drive it under load instead, which masks the schedule
(every day emits) but checks the consumption law on several packets a day.
"""
import getpass
import re
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

_LIVE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_LIVE))
sys.path.insert(0, str(_LIVE.parent.parent))

from rig import node as node_rig
from rig.layout import LEAGUES, NODES, VENV_PYTHON

_ANSI = re.compile(rb"\x1b\[[0-9;?]*[A-Za-z]")


def _restore(league):
    for index in league.members:
        node = NODES[index]
        prefix = [] if node.user == getpass.getuser() else ["sudo", "-u", node.user, "--"]
        subprocess.run(
            [*prefix, str(VENV_PYTHON), "-c",
             "import sys; sys.path.insert(0, '.'); "
             "from rig import fixtures; from rig.layout import LEAGUES, NODES; "
             f"fixtures.restore(LEAGUES[{league.league_id!r}], NODES[{index}])"],
            cwd=str(_LIVE), capture_output=True, text=True, check=True,
        )


def _lines(log):
    text = _ANSI.sub(b" ", log.read_bytes()).decode("latin-1")
    out = set()
    for raw in re.split(r"[\r\n]+", text):
        s = " ".join(raw.split())
        if 6 <= len(s) <= 70 and not s.startswith("C:"):
            out.add(s)
    return out


def fit(ordinals, emitted, first_ordinal):
    """Find every (p, a, q, b) whose union reproduces the observed emissions.

    The first game day after a restore always emits (the opening packet), so it
    is excluded from the comparison rather than allowed to prop up a bad fit.
    """
    obs = {o for o, e in zip(ordinals, emitted) if e} - {first_ordinal}
    pool = [o for o in ordinals if o != first_ordinal]
    hits = []
    for p in range(2, 11):
        for a in range(p):
            single = {o for o in pool if o % p == a}
            if single == obs:
                hits.append((p, a, None, None))
            for q in range(p, 11):
                for b in range(q):
                    if {o for o in pool if o % p == a or o % q == b} == obs:
                        hits.append((p, a, q, b))
    return hits


def main(league_id, node_index, start, ndays, forced):
    league = LEAGUES[league_id]
    node = NODES[node_index]
    prefix = f"{league_id[:3]}{league_id[3].lower()}{node_index:02x}01.".lower()

    _restore(league)
    first = date(int(start[:4]), int(start[4:6]), int(start[6:]))

    ordinals, emitted, numbers, per_day, marks = [], [], [], [], {}
    for n in range(ndays):
        d = first + timedelta(days=n)
        tag = f"cal{n}"
        log = node_rig.run(league, node, "PLANETARY", tag=tag, date=d.strftime("%Y%m%d"))
        got = [name for name, _ in node_rig.take_outbound(league, node)
               if name.lower().startswith(prefix)]
        for k in range(forced):
            node_rig.force_packet(league, node, "REQUEST", tag=f"{tag}f{k}",
                                 date=d.strftime("%Y%m%d"))
            got += [name for name, _ in node_rig.take_outbound(league, node)
                    if name.lower().startswith(prefix)]
        ordinals.append(d.toordinal())
        emitted.append(1 if got else 0)
        per_day.append(len(got))
        numbers.extend(int(g.rsplit(".", 1)[1]) for g in got)
        marks[n] = _lines(log)
        print(f"  day {n+1:2d}  {d:%a %Y-%m-%d}  packets={len(got)}  {got}", flush=True)

    print()
    print(f"league {league_id} node {node_index:02d}, {ndays} game days from {first}")
    print(f"emission pattern : {emitted}")
    print(f"packets per day  : {per_day}")
    print(f"numbers          : {numbers}")
    if numbers:
        print(f"number deltas    : {[b-a for a,b in zip(numbers, numbers[1:])]}")

    # the law, per packet: k-th number == game days elapsed + k
    days_of = [i+1 for i, c in enumerate(per_day) for _ in range(c)]
    bad = [(k, day, num) for k, (day, num) in enumerate(zip(days_of, numbers), 1)
           if day + k != num]
    print(f"law k-th==days+k : {'HOLDS for all %d' % len(numbers) if not bad else 'MISMATCH %s' % bad}")

    print()
    hits = fit(ordinals, emitted, ordinals[0])
    if not hits:
        print("NO (p,a)/(q,b) union in 2..10 reproduces this. Not two metronomes.")
    for p, a, q, b in hits:
        if q is None:
            print(f"FIT: ordinal mod {p} == {a}  (single series)")
        else:
            wk = ""
            if p == 7 or q == 7:
                per, res = (p, a) if p == 7 else (q, b)
                wk = f"   [the mod-{per} series is every "\
                     f"{date.fromordinal(next(o for o in ordinals if o % per == res)):%A}]"
            print(f"FIT: (ordinal mod {p} == {a}) or (ordinal mod {q} == {b}){wk}")

    emit_days = [n for n, e in enumerate(emitted) if e and n > 0]
    quiet_days = [n for n, e in enumerate(emitted) if not e]
    if emit_days and quiet_days:
        only_emit = set.intersection(*(marks[n] for n in emit_days)) - set.union(*(marks[n] for n in quiet_days))
        only_quiet = set.intersection(*(marks[n] for n in quiet_days)) - set.union(*(marks[n] for n in emit_days))
        print(f"\non every emitting day and no quiet day ({len(only_emit)}):")
        for s in sorted(only_emit)[:25]:
            print(f"   + {s}")
        print(f"on every quiet day and no emitting day ({len(only_quiet)}):")
        for s in sorted(only_quiet)[:25]:
            print(f"   - {s}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4]),
         int(sys.argv[5]) if len(sys.argv) > 5 else 0)
