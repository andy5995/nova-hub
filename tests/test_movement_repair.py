"""Rewriting stored movement rows from their transcripts after the parser fix."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.models.database import League, ProcessingRun, ProcessingRunItem
from backend.services.movement_repair import repair

# The game wrote "4", then jumped the cursor to repaint another record's "240".
JUMPED = (
    "Compress: Old: 1448  Size:   36  %: 97.5%  Type: Recon Update  "
    " 1-> 4\x1b[18;22H240  \n"
)
FE = "DeCompress:  Old:  10  New:  20  %: 50.0%  Type: Message        3-> 1\n"


@pytest.fixture
def leagues(db_session):
    made = {}
    for number, game in (("015", "B"), ("015", "F")):
        lg = League(league_id=number, game_type=game, name="League 015", is_active=True)
        db_session.add(lg)
        made[game] = lg
    db_session.commit()
    return made


def _run(db, log):
    run = ProcessingRun(status="completed", dosemu_log=log)
    db.add(run)
    db.commit()
    return run


def _item(db, run, league, direction, item_type, src, dst, before, after):
    db.add(ProcessingRunItem(
        processing_run_id=run.id, league_id=league.id, occurred_at=run.started_at,
        direction=direction, item_type=item_type, src_node=src, dst_node=dst,
        size_before=before, size_after=after,
    ))
    db.commit()


def _moved(db, run):
    return {(r.league_id, r.item_type, r.src_node, r.dst_node)
            for r in db.query(ProcessingRunItem).filter_by(processing_run_id=run.id)}


def test_a_joined_node_is_reread_from_the_transcript_under_its_league(db_session, leagues):
    run = _run(db_session, JUMPED)
    _item(db_session, run, leagues["B"], "out", "Recon Update", 1, 4240, 1448, 36)

    counts = repair(db_session, apply=True)

    assert counts["runs_changed"] == 1
    assert _moved(db_session, run) == {(leagues["B"].id, "Recon Update", 1, 4)}


def test_in_a_two_league_run_each_row_keeps_its_own_league(db_session, leagues):
    run = _run(db_session, JUMPED + "\n\n" + FE)
    _item(db_session, run, leagues["B"], "out", "Recon Update", 1, 4240, 1448, 36)
    _item(db_session, run, leagues["F"], "in", "Message", 3, 1, 10, 20)

    repair(db_session, apply=True)

    assert _moved(db_session, run) == {
        (leagues["B"].id, "Recon Update", 1, 4),
        (leagues["F"].id, "Message", 3, 1),
    }


def test_without_apply_nothing_is_written(db_session, leagues):
    run = _run(db_session, JUMPED)
    _item(db_session, run, leagues["B"], "out", "Recon Update", 1, 4240, 1448, 36)

    counts = repair(db_session)

    assert counts["runs_changed"] == 1
    assert _moved(db_session, run) == {(leagues["B"].id, "Recon Update", 1, 4240)}


def test_a_purged_run_loses_only_impossible_nodes(db_session, leagues):
    run = _run(db_session, None)
    _item(db_session, run, leagues["B"], "out", "Configupdate", 1, 31194, 1448, 36)
    _item(db_session, run, leagues["B"], "out", "Configupdate", 1, 3, 1448, 36)

    counts = repair(db_session, apply=True)

    assert counts["purged_nodes_cleared"] == 1
    assert _moved(db_session, run) == {
        (leagues["B"].id, "Configupdate", 1, None),
        (leagues["B"].id, "Configupdate", 1, 3),
    }


def test_a_second_pass_changes_nothing(db_session, leagues):
    run = _run(db_session, JUMPED)
    _item(db_session, run, leagues["B"], "out", "Recon Update", 1, 4240, 1448, 36)
    repair(db_session, apply=True)

    counts = repair(db_session, apply=True)

    assert counts["runs_changed"] == 0
    assert counts["purged_nodes_cleared"] == 0
