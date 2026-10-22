"""Performing a game reset: the job behind the console's PERFORM RESET.

In order, each step recorded in the row's `progress`:

  queued      the draft became this reset (status "applying")
  lock        the processing lock is held: no batch runs until the reset is done
  backup      the game folder is archived; the only way back once RESET has
              been answered Y, which deletes GAME.DAT on the spot
  editor      editor.EditorDriver types the draft into `<EXE> RESET`
  saved       the read-back matched, ESC saved, league-wide was answered Y
  processing  a PLANETARY run for the league, even with no packets waiting
  sent        that run went through: the Game Start is on its way to members

Anything that goes wrong before "saved" kills dosemu, puts the backup back
byte for byte, and marks the reset failed with the driver's log. The draft's
settings come back as a new draft, so nothing typed is lost.

One reset runs at a time across the hub. The job holds the processing lock
throughout, so packets that arrive meanwhile wait for the run after it.
"""
import asyncio
import shutil
import tarfile
import time
import traceback
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy.orm import Session

from backend.core.clock import utcnow
from backend.core.database import get_session
from backend.logging_config import get_logger
from backend.models.database import GameReset, League
from backend.services.game_reset import drafts
from backend.services.game_reset.editor import EditorDriver, EditorError
from backend.services.games import game_for_letter

logger = get_logger(context="game_reset")

KEEP_BACKUPS = 5               # per league; the newest are kept
LOCK_WAIT = 15 * 60            # seconds to wait for a running batch to finish
GAME_EXIT_WAIT = 300           # seconds for the game to finish after league-wide

_jobs: set = set()             # running job tasks, so they aren't collected


class ResetRefused(Exception):
    """The reset can't start. `status` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


@dataclass
class GameSetup:
    """Where a league's game is, from [dosemu.<league>.<game>] in config.toml."""
    folder: Path
    dos_path: str
    exe: str
    dosemu: str


def game_setup(config: dict, league: League) -> GameSetup:
    game = game_for_letter(league.game_type)
    dosemu = config.get("dosemu", {})
    section = dosemu.get(league.league_id, {}).get(game.key)
    if not section:
        raise ResetRefused(f"config.toml has no [dosemu.{league.league_id}."
                           f"{game.key}] section for this league", 422)
    folder, dos_path = section.get("game_folder"), section.get("game_dos_path")
    # The game's EXE is the first word of the commands the hub already runs.
    command = section.get("reset_command") or section.get("processing_command") or ""
    exe = command.split()[0] if command.split() else ""
    if not (folder and dos_path and exe):
        raise ResetRefused(f"[dosemu.{league.league_id}.{game.key}] needs "
                           f"game_folder, game_dos_path and processing_command", 422)
    return GameSetup(Path(folder), dos_path, exe, dosemu.get("dosemu_path", "/usr/bin/dosemu"))


def _find(folder: Path, name: str) -> Optional[Path]:
    """`folder/name` matched as DOS would, ignoring case."""
    if not folder.is_dir():
        return None
    for entry in folder.iterdir():
        if entry.name.lower() == name.lower():
            return entry
    return None


def _now() -> datetime:
    return utcnow()


def _stage(db: Session, reset: GameReset, stage: str):
    reset.progress = [*(reset.progress or []), {"stage": stage, "at": _now().isoformat()}]
    db.commit()


# ── starting one ──────────────────────────────────────────────────────────
def start(db: Session, league: League, version: int, code: str, username: str,
          config: dict, today: date) -> GameReset:
    """Check everything that can be checked without touching the game, then
    turn the draft into a reset under way. The caller schedules run_job()."""
    if (code or "").strip().upper() != league.full_id.upper():
        raise ResetRefused(f"Type the league code, {league.full_id}, to confirm.", 422)
    draft = drafts.current_draft(db, league)
    if draft is None:
        raise ResetRefused("There is no draft to perform.", 404)
    if draft.version != version:
        raise ResetRefused(f"{draft.updated_by} saved this draft since you opened it. "
                           f"Check their changes before performing it.")
    busy = db.query(GameReset).filter(GameReset.status == "applying").first()
    if busy is not None:
        raise ResetRefused(f"A reset is already under way (league "
                           f"{busy.league.full_id if busy.league else busy.league_id}).")
    settings, errors = drafts.validate(league.game_type, draft.settings, today)
    if errors:
        raise ResetRefused("The draft no longer passes the game's limits: " +
                           "; ".join(f"{f}: {m}" for f, m in errors), 422)
    setup = game_setup(config, league)
    if not setup.folder.is_dir():
        raise ResetRefused(f"The game folder {setup.folder} isn't there.", 422)
    if _find(setup.folder, setup.exe) is None:
        raise ResetRefused(f"{setup.exe} isn't in {setup.folder}.", 422)
    if _find(setup.folder, "inuse.flg") is not None:
        raise ResetRefused("The game's inuse.flg is there: either the game is running, "
                           "or a run was killed and left it behind. Check before "
                           "resetting.", 409)

    draft.status = "applying"
    draft.settings = settings
    draft.applied_by = username
    draft.progress = []
    draft.error = None
    _stage(db, draft, "queued")
    logger.info(f"Reset {draft.id} of {league.full_id} started by {username}")
    return draft


def schedule(reset_id: int, config: dict, **kw) -> asyncio.Task:
    task = asyncio.get_running_loop().create_task(run_job(reset_id, config, **kw))
    _jobs.add(task)
    task.add_done_callback(_jobs.discard)
    return task


# ── the game folder ───────────────────────────────────────────────────────
def backup(folder: Path, into: Path, stamp: str) -> Path:
    into.mkdir(parents=True, exist_ok=True)
    archive = into / f"{stamp}.tar.gz"
    partial = archive.with_suffix(".partial")
    with tarfile.open(partial, "w:gz") as tar:
        tar.add(folder, arcname=".")
    partial.rename(archive)
    return archive


def restore(archive: Path, folder: Path):
    """Put `folder` back exactly as `archive` holds it. The archive is unpacked
    beside it first, so a bad archive leaves the folder as it is, and the two
    are swapped by rename, so at no point is there no game folder at all."""
    staging = folder.with_name(f".{folder.name}.restoring")
    replaced = folder.with_name(f".{folder.name}.replaced")
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(replaced, ignore_errors=True)
    staging.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        # "data": nothing outside staging, no devices. A game folder holds
        # neither, and the archive is the hub's own, but a restore is no place
        # to find out otherwise.
        tar.extractall(staging, filter="data")
    folder.rename(replaced)
    staging.rename(folder)
    shutil.rmtree(replaced)


def prune(into: Path, keep: int = KEEP_BACKUPS):
    archives = sorted(into.glob("*.tar.gz"))
    for old in archives[:-keep] if keep else archives:
        old.unlink(missing_ok=True)


# ── driving the game ──────────────────────────────────────────────────────
def drive(setup: GameSetup, game_type: str, settings: dict, today: date,
          log: Callable[[str], None], transcript: Path) -> dict:
    """Run `<EXE> RESET` and type `settings` in. Blocking; run it in a thread.
    Returns the read-back, or raises EditorError with dosemu killed."""
    from sr_harness.install import Install

    install = Install(setup.folder, exe=setup.exe, dos_path=setup.dos_path,
                      dosemu=setup.dosemu)
    transcript.parent.mkdir(parents=True, exist_ok=True)
    session = install.session("RESET", transcript=str(transcript), batch="RESET.BAT")
    try:
        driver = EditorDriver(session, game_type, settings, today, log=log)
        readback = driver.run()
        log("waiting for the game to finish")
        if not session.drain(GAME_EXIT_WAIT):
            raise EditorError("the game didn't exit after the league-wide question")
        data = _find(setup.folder, "DATA")
        if data is None or _find(data, "GAME.DAT") is None:
            raise EditorError("the game exited without writing DATA/GAME.DAT")
        return readback
    finally:
        session.close(grace=2)
        (setup.folder / "RESET.BAT").unlink(missing_ok=True)


# ── the job ───────────────────────────────────────────────────────────────
async def _take_lock(wait: float) -> bool:
    from backend.services.processing_service import _processing_lock
    deadline = time.monotonic() + wait
    while not _processing_lock.acquire(blocking=False):
        if time.monotonic() > deadline:
            return False
        await asyncio.sleep(1)
    return True


def _release_lock():
    from backend.services.processing_service import _processing_lock
    _processing_lock.release()


def _keep_as_draft(db: Session, reset: GameReset):
    """A failed reset's settings come back as the league's draft, unless someone
    has started a new one meanwhile."""
    league = reset.league or db.get(League, reset.league_id)
    if drafts.current_draft(db, league) is None:
        now = _now()
        db.add(GameReset(league_id=reset.league_id, status="draft", source="console",
                         settings=reset.settings, notes=reset.notes, version=1,
                         created_by=reset.applied_by, created_at=now,
                         updated_by=reset.applied_by, updated_at=now))


async def run_job(reset_id: int, config: dict, drive_fn=drive,
                  lock_wait: float = LOCK_WAIT, today: Optional[date] = None):
    db = get_session()
    try:
        await _run(db, reset_id, config, drive_fn, lock_wait, today or date.today())
    except Exception as exc:                     # a bug, not an editor surprise
        logger.exception(f"Reset {reset_id} failed unexpectedly")
        db.rollback()
        reset = db.get(GameReset, reset_id)
        if reset is None:
            return
        if reset.status == "applying":
            # Before the editor: the game was never touched.
            reset.status = "failed"
            reset.error = f"The hub hit an error before the game was touched: {exc}"
            _keep_as_draft(db, reset)
            _stage(db, reset, "failed")
        elif reset.status == "applied" and not reset.error:
            reset.error = (f"The reset is saved, but the hub hit an error after it: "
                           f"{exc}. The Game Start goes out with the next run that works.")
            db.commit()
    finally:
        db.close()


async def _run(db: Session, reset_id: int, config: dict, drive_fn, lock_wait, today):
    reset = db.get(GameReset, reset_id)
    league = reset.league or db.get(League, reset.league_id)
    setup = game_setup(config, league)
    data_dir = Path(config.get("server", {}).get("data_dir", "./data"))
    stamp = _now().strftime("%Y%m%d-%H%M%S")
    log_lines = []

    def log(line: str):
        log_lines.append(f"{datetime.now():%H:%M:%S} {line}")

    if not await _take_lock(lock_wait):
        reset.status = "failed"
        reset.error = (f"A processing run held the lock for over {lock_wait // 60:.0f} "
                       f"minutes. Nothing was changed.")
        _keep_as_draft(db, reset)
        _stage(db, reset, "failed")
        return
    try:
        _stage(db, reset, "lock")
        into = data_dir / "reset_backups" / league.full_id
        archive = await asyncio.to_thread(backup, setup.folder, into, stamp)
        reset.backup_path = str(archive)
        _stage(db, reset, "backup")

        _stage(db, reset, "editor")
        transcript = data_dir / "logs" / "reset" / f"{league.full_id}_{stamp}.log"
        log(f"transcript: {transcript}")
        try:
            await asyncio.to_thread(drive_fn, setup, league.game_type, reset.settings,
                                    today, log, transcript)
        except Exception as exc:
            log(f"FAILED: {exc}")
            reset.status = "failed"
            try:
                await asyncio.to_thread(restore, archive, setup.folder)
                log(f"restored {setup.folder} from {archive}")
                reset.error = (f"{exc}. The game was put back as it was before the "
                               f"reset, and the settings are back in the draft.")
                ending = "restored"
            except Exception as restore_exc:
                log(f"RESTORE FAILED: {restore_exc}")
                reset.error = (f"{exc}. Putting the game back then failed too "
                               f"({restore_exc}): restore {archive} into "
                               f"{setup.folder} by hand before the next run.")
                ending = "failed"
            reset.transcript = "\n".join(log_lines)
            _keep_as_draft(db, reset)
            _stage(db, reset, ending)
            logger.warning(f"Reset {reset.id} of {league.full_id} failed ({ending}): "
                           f"{reset.error}")
            return

        reset.status = "applied"
        reset.applied_at = _now()
        reset.transcript = "\n".join(log_lines)
        _stage(db, reset, "saved")
        prune(into)
        logger.info(f"Reset {reset.id} of {league.full_id} saved; running PLANETARY")

        from backend.services.processing_service import ProcessingService
        game = game_for_letter(league.game_type)
        run = await ProcessingService(db, config).process_batch(
            also=((game.code, league.league_id),))
        db.refresh(reset)
        reset.processing_run_id = run.id if run is not None else None
        _stage(db, reset, "processing")
        if run is None or run.status != "completed":
            reset.error = ("The reset is saved, but the processing run after it failed"
                           + (f": {run.error_message}" if run is not None and
                              run.error_message else "")
                           + ". The Game Start goes out with the next run that works.")
            db.commit()
            return
        _stage(db, reset, "sent")
    finally:
        _release_lock()


# ── after a restart ───────────────────────────────────────────────────────
def recover(db: Session, config: dict):
    """Settle resets left "applying" by a hub that stopped mid-job.

    Stopped in the editor: the game is half-reset, so it is restored. Stopped
    after the save: the reset stands, and the next processing run sends it.
    Before the backup finished, nothing was touched.
    """
    for reset in db.query(GameReset).filter(GameReset.status == "applying").all():
        stages = [p["stage"] for p in reset.progress or []]
        last = stages[-1] if stages else "queued"
        if "saved" in stages:
            reset.status = "applied"
            reset.error = ("The hub stopped before the processing run after the reset. "
                           "The Game Start goes out with the next run.")
        elif last == "editor":
            league = reset.league or db.get(League, reset.league_id)
            try:
                folder = game_setup(config, league).folder
                restore(Path(reset.backup_path), folder)
                reset.error = ("The hub stopped while the editor was open. The game was "
                               "put back as it was before the reset.")
            except Exception as exc:
                reset.error = (f"The hub stopped while the editor was open, and putting "
                               f"the game back failed: {exc}. Restore {reset.backup_path} "
                               f"by hand before the next run.")
            reset.status = "failed"
            _keep_as_draft(db, reset)
        else:
            reset.status = "failed"
            reset.error = "The hub stopped before the game was touched."
            _keep_as_draft(db, reset)
        reset.progress = [*(reset.progress or []),
                          {"stage": "interrupted", "at": _now().isoformat()}]
        logger.warning(f"Reset {reset.id} was interrupted at {last}: {reset.error}")
    db.commit()
