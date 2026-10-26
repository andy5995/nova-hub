"""
Re-read stored transcripts into movement rows, after a parser fix.

Until 0.9.0 the parser dropped cursor moves without a break, so a destination
could run into digits the game painted elsewhere (1->4240 on dev; 1->31194 and
1->683 on prod), and a record spaced with cursor-forward was lost. A run whose
transcript is still held is re-parsed and its rows rewritten. Each row keeps
its league: a run's rows are attributed per league as it finishes, and the
stored transcript is the leagues' outputs joined, so a re-parsed record takes
the league of the old row it matches, exactly or with only its nodes differing.
A multi-league run with a record that matches nothing is left alone and
reported.

A run whose transcript retention has blanked cannot be re-read. There a node
above 255, which no game can have, is set to unknown rather than left naming
a board that does not exist. A wrong but possible node cannot be told apart,
so those stay.
"""

from collections import defaultdict

from sqlalchemy.orm import Session

from backend.models.database import ProcessingRun, ProcessingRunItem
from backend.services.transcript_service import parse

MAX_NODE = 255


def _sizes(direction, item_type, src, before, after):
    return (direction, item_type, src, before, after)


def _new_rows(run_id, started_at, records, old):
    """The run's rows as the parser reads them now, or None if attribution is unsure."""
    leagues = {r.league_id for r in old}
    single = len(leagues) <= 1
    league = next(iter(leagues)) if leagues else None

    exact = defaultdict(list)
    loose = defaultdict(list)
    for r in old:
        exact[(r.direction, r.item_type, r.src_node, r.dst_node, r.size_before, r.size_after)].append(r)
        loose[_sizes(r.direction, r.item_type, r.src_node, r.size_before, r.size_after)].append(r)

    rows = []
    for rec in records:
        key = (rec["direction"], rec["type"], rec["src"], rec["dst"],
               rec["size_before"], rec["size_after"])
        if single:
            lg = league
        elif exact.get(key):
            lg = exact[key].pop().league_id
        else:
            near = {r.league_id for r in loose.get(_sizes(*key[:3], *key[4:]), [])}
            if len(near) != 1:
                return None
            lg = near.pop()
        rows.append(dict(
            processing_run_id=run_id, league_id=lg, occurred_at=started_at,
            direction=rec["direction"], item_type=rec["type"],
            src_node=rec["src"], dst_node=rec["dst"],
            size_before=rec["size_before"], size_after=rec["size_after"],
            phase=rec.get("phase"),
        ))
    return rows


def _key(row):
    if isinstance(row, dict):
        return (row["league_id"], row["direction"], row["item_type"], row["src_node"],
                row["dst_node"], row["size_before"], row["size_after"], row["phase"])
    return (row.league_id, row.direction, row.item_type, row.src_node,
            row.dst_node, row.size_before, row.size_after, row.phase)


def repair(db: Session, apply: bool = False) -> dict:
    counts = dict(runs_read=0, runs_changed=0, rows_before=0, rows_after=0,
                  unsure=[], purged_nodes_cleared=0)

    run_ids = [rid for (rid,) in db.query(ProcessingRun.id)
               .filter(ProcessingRun.dosemu_log.isnot(None), ProcessingRun.dosemu_log != "")
               .order_by(ProcessingRun.id)]
    for rid in run_ids:
        # Columns, not the run object: prod holds a month of transcripts, tens of
        # KB each, and the session would keep every one.
        log, started = (db.query(ProcessingRun.dosemu_log, ProcessingRun.started_at)
                        .filter(ProcessingRun.id == rid).one())
        counts["runs_read"] += 1
        records, _ = parse(log.encode("utf-8", errors="replace"))
        records = [r for r in records if r.get("kind") == "item"]
        old = db.query(ProcessingRunItem).filter(ProcessingRunItem.processing_run_id == rid).all()
        if not old:
            # Nothing was recorded (a run from before Movements, or a failed
            # one), so there is no league to give rows: correct, don't backfill.
            continue
        rows = _new_rows(rid, started, records, old)
        if rows is None:
            counts["unsure"].append(rid)
            continue
        if sorted(map(_key, rows), key=repr) == sorted(map(_key, old), key=repr):
            continue
        counts["runs_changed"] += 1
        counts["rows_before"] += len(old)
        counts["rows_after"] += len(rows)
        if apply:
            for r in old:
                db.delete(r)
            db.add_all(ProcessingRunItem(**r) for r in rows)
            db.flush()

    # Runs retention has blanked: only the impossible can be corrected.
    held = set(run_ids)
    for col in (ProcessingRunItem.src_node, ProcessingRunItem.dst_node):
        bad = db.query(ProcessingRunItem).filter(col > MAX_NODE).all()
        bad = [r for r in bad if r.processing_run_id not in held]
        counts["purged_nodes_cleared"] += len(bad)
        if apply:
            for r in bad:
                setattr(r, col.key, None)

    if apply:
        db.commit()
    return counts
