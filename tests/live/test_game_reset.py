"""Performing a game reset from the console, on the real games.

The unit tests drive a model of RESET's editor; this drives the editor itself,
through the same job the PERFORM RESET button starts: backup, editor, read-back,
save, league-wide, PLANETARY. Then it checks the result three ways: the game's
own EDITOR shows the settings, the Game Start the hub sent decodes to them, and
a member that runs the packet starts the new game.

And the case the backup exists for: a field that goes wrong mid-editor, after
RESET has already deleted GAME.DAT, must leave the hub's game byte-for-byte as
it was.
"""
import hashlib
import time
from datetime import date
from pathlib import Path

import pytest

from rig import node as node_rig
from rig.layout import HUB_INDEX, LEAGUES, NODES

pytestmark = pytest.mark.asyncio

BRE, FE = LEAGUES["900B"], LEAGUES["900F"]
HUB, NODE02 = NODES[HUB_INDEX], NODES[2]

BRE_CHANGES = {"turns_per_day": 12, "steady_investment": True, "buy_military": "L",
               "attack_rewards": "L", "sabre": "C", "sabre_dial": 7,
               "lost_attack_days": 3, "indiv_attacks": 2, "gooie": False}
FE_CHANGES = {"turns_per_day": 10, "start_runes": 50, "lost_attack_days": 5,
              "local_attacks": False}


def tree(folder: Path) -> dict:
    return {str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


def editor_pages(league) -> dict:
    """What the hub's game shows in `<EXE> EDITOR`, both pages: a check that
    doesn't go through the driver that wrote it."""
    from sr_harness.install import Install
    from backend.services.game_reset.editor import PGDN, page_rows

    install = Install(league.install_path(HUB), exe=league.g.exe,
                      dos_path=league.dos_path(HUB))
    s = install.session("EDITOR", batch="EDIT.BAT")
    try:
        assert s.wait_for(r"Configuration Editor", timeout=120)
        s.pump(2)
        rows = page_rows(s.screen_text())
        s.send(PGDN)
        time.sleep(1.5)
        s.pump(1)
        rows.update(page_rows(s.screen_text()))
        s.mash("\x1b", "Configuration Editor", max_presses=80)
        s.pump(5)
    finally:
        s.close(grace=2)
        install.clear_mutex()
        (league.install_path(HUB) / "EDIT.BAT").unlink(missing_ok=True)
    return rows


def perform_on(hub, league_id, changes, monkeypatch):
    """Draft `changes` for the league and start the reset; returns the row."""
    from sqlalchemy.orm import sessionmaker
    from backend.models.database import GameReset, League
    from backend.services.game_reset import perform
    from backend.services.game_reset.drafts import validate
    from backend.services.game_reset.fields import defaults

    monkeypatch.setattr(perform, "get_session", lambda: sessionmaker(bind=hub._engine)())
    league = LEAGUES[league_id]
    row = (hub.db.query(League)
           .filter_by(league_id=league.number, game_type=league.game).one())
    settings, errors = validate(league.game, {**defaults(league.game), **changes},
                                date.today())
    assert not errors, errors
    hub.db.add(GameReset(league_id=row.id, status="draft", source="console",
                         settings=settings, version=1, created_by="rig"))
    hub.db.commit()
    return perform.start(hub.db, row, 1, row.full_id, "rig", hub.config, date.today())


async def test_a_bre_reset_reaches_the_editor_the_packets_and_a_member(
        pristine, hub, monkeypatch):
    from backend.models.database import Packet
    from backend.services.game_reset import perform

    pristine("900B")
    hub.seed(["900B"])
    reset = perform_on(hub, "900B", BRE_CHANGES, monkeypatch)
    await perform.run_job(reset.id, hub.config)
    hub.db.expire_all()

    assert reset.status == "applied", f"{reset.error}\n{reset.transcript}"
    assert [p["stage"] for p in reset.progress][-1] == "sent", reset.error
    assert "read-back matches the draft on both pages" in reset.transcript

    # The game's own editor, opened afresh.
    rows = editor_pages(BRE)
    assert rows["Turns Per Day"] == "12"
    assert rows["Buy Military"] == "Limited"
    assert rows["Sabre Handling"] == "Constant Setting Of 7"
    assert rows['Days for "Lost Attacks"'] == "3"
    assert rows["Gooie Kablooies"] == "Disabled"
    assert rows["Tax Rate"] == "50", "a field the draft left alone changed"

    # The Game Start that went out says the same.
    assert reset.game_start is not None, "no Game Start was seen in the hub's packets"
    assert reset.sent_config["mismatches"] == [], reset.sent_config
    assert (reset.sent_config["lost_attack_days"], reset.sent_config["indiv_attacks"]) == (3, 2)
    members = {p.dest_bbs_index for p in
               hub.db.query(Packet).filter_by(processing_run_id=reset.processing_run_id)}
    assert {f"{i:02d}" for i in BRE.members if i != HUB_INDEX} <= members

    # A member runs its packet.
    outbound = hub.data_dir / "packets" / "outbound"
    name = next(p.name for p in outbound.iterdir()
                if p.name.upper().startswith("900B0102."))
    node_rig.give_inbound(BRE, NODE02, name, (outbound / name).read_bytes())
    log = node_rig.run(BRE, NODE02, "PLANETARY", tag="reset_member")
    text = log.read_bytes().decode("cp437", "replace")
    assert name.upper() not in [n.upper() for n in node_rig.inbound(BRE, NODE02)], (
        "the member never took the reset packet")
    # What a member's reset looks like from its own transcript (seen 15 Oct 2026):
    # it deletes its game and rebuilds its InterBBS data file.
    assert "DATA\\GAME.DAT removed." in text, "the member's game was not reset"
    assert "ReIniting IP Data File PLANET.BRE" in text


async def test_an_fe_reset_reaches_the_editor(pristine, hub, monkeypatch):
    from backend.services.game_reset import perform

    pristine("900F")
    hub.seed(["900F"])
    reset = perform_on(hub, "900F", FE_CHANGES, monkeypatch)
    await perform.run_job(reset.id, hub.config)
    hub.db.expire_all()

    assert reset.status == "applied", f"{reset.error}\n{reset.transcript}"
    rows = editor_pages(FE)
    assert rows["Turns Per Day"] == "10"
    assert rows["Starting Runes"] == "50"
    assert rows['Days for "Lost Attacks"'] == "5"
    assert rows["Local Attacks"] == "Disabled"
    assert rows["Starting Silver"] == "15000"


async def test_a_field_gone_wrong_restores_the_game_byte_for_byte(
        pristine, hub, monkeypatch):
    """An over-max value gets past validation (it can't, but say it did): the
    editor puts the maximum on the prompt and waits for a second Enter, by
    which time RESET has deleted GAME.DAT. The driver must notice, and the job
    must put the game back exactly."""
    from backend.models.database import GameReset
    from backend.services.game_reset import perform

    pristine("900B")
    hub.seed(["900B"])
    install = BRE.install_path(HUB)
    before = tree(install)
    reset = perform_on(hub, "900B", {"turns_per_day": 12}, monkeypatch)

    def overmax(setup, game_type, settings, today, log, transcript):
        return perform.drive(setup, game_type, {**settings, "turns_per_day": 25},
                             today, log, transcript)

    await perform.run_job(reset.id, hub.config, drive_fn=overmax)
    hub.db.expire_all()

    assert reset.status == "failed"
    assert "Turns Per Day" in reset.error and "put back" in reset.error, reset.error
    assert "the game is wiped from here on" in reset.transcript, (
        "the failure came before RESET wiped anything, so this proves nothing")
    assert tree(install) == before, "the game was not restored byte for byte"
    assert hub.db.query(GameReset).filter_by(status="draft").count() == 1
