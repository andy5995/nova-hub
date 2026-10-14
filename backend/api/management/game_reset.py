"""Drafting a league's game reset: the form, with every setting's help, and the
league's one saved draft. Performing it comes later. See backend/services/game_reset/."""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.core.database import get_db
from backend.core.security import require_admin
from backend.logging_config import get_logger
from backend.models.database import League, LeagueGameSettings, SysopUser
from backend.schemas.game_reset import (
    GameResetForm, ObservedSettings, ResetApplied, ResetChoice, ResetDraft,
    ResetDraftSave, ResetField, ResetWarning,
)
from backend.services import audit
from backend.services.game_reset import drafts
from backend.services.game_reset.fields import LEAGUE_WIDE_HELP, defaults, fields_for

router = APIRouter()
logger = get_logger(context="management_game_reset")


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat() if t else None


def _league(db: Session, league_id: int) -> League:
    league = db.query(League).filter(League.id == league_id).first()
    if league is None:
        raise HTTPException(status_code=404, detail="League not found")
    return league


def _draft(d, game_type: str) -> Optional[ResetDraft]:
    if d is None:
        return None
    return ResetDraft(id=d.id, version=d.version, settings=d.settings,
                      warnings=[ResetWarning(field=f, message=m)
                                for f, m in drafts.warnings(game_type, d.settings)],
                      notes=d.notes,
                      created_by=d.created_by, created_at=_iso(d.created_at),
                      updated_by=d.updated_by, updated_at=_iso(d.updated_at))


def _form(db: Session, league: League) -> GameResetForm:
    applied = drafts.last_applied(db, league)
    seen = db.query(LeagueGameSettings).filter(
        LeagueGameSettings.league_id == league.id).first()
    return GameResetForm(
        league_id=league.id,
        full_id=league.full_id,
        game_type=league.game_type,
        fields=[ResetField(id=f.id, label=f.label, page=f.page, group=f.group,
                           kind=f.kind, default=f.default, min=f.min, max=f.max,
                           choices=[ResetChoice(letter=l, name=n) for l, n in f.choices],
                           interbbs=f.interbbs, advised_min=f.advised_min,
                           advised_reason=f.advised_reason, note=f.note,
                           admin_note=f.admin_note,
                           depends_on=list(f.depends_on) if f.depends_on else None,
                           help_title=f.help_title, help=f.help)
                for f in fields_for(league.game_type)],
        defaults=defaults(league.game_type),
        league_wide_help=LEAGUE_WIDE_HELP[league.game_type][1],
        draft=_draft(drafts.current_draft(db, league), league.game_type),
        last_applied=None if applied is None else ResetApplied(
            id=applied.id, settings=applied.settings, applied_by=applied.applied_by,
            applied_at=_iso(applied.applied_at), game_start=_iso(applied.game_start)),
        observed=None if seen is None else ObservedSettings(
            game_started_at=_iso(seen.game_started_at),
            protection_turns=seen.protection_turns,
            indiv_attacks=seen.indiv_attacks_per_day,
            lost_attack_days=seen.lost_attack_days,
            seen_at=_iso(seen.seen_at)),
    )


@router.get("/{league_id}/reset", response_model=GameResetForm,
            summary="Get the Game Reset Form")
async def get_reset_form(
    league_id: int,
    current_user: SysopUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Every setting the game's reset editor offers, in the editor's order, with
    the game's own help, its default and our limits; the league's draft, if any;
    the settings of the last reset performed from the console; and what the hub
    last decoded from the league's Configupdate."""
    return _form(db, _league(db, league_id))


@router.put("/{league_id}/reset/draft", response_model=GameResetForm,
            summary="Save the Game Reset Draft")
async def save_reset_draft(
    league_id: int,
    body: ResetDraftSave,
    request: Request,
    current_user: SysopUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Check every setting against the game's limits and save the league's draft.

    A value below our advised minimum is saved, and listed in the draft's
    `warnings`.

    Answers 422 listing each field that fails, and 409 when someone else saved the
    draft since `version` was loaded. Fields left out take the game's defaults.
    """
    league = _league(db, league_id)
    settings, errors = drafts.validate(league.game_type, body.settings, date.today())
    if errors:
        raise HTTPException(status_code=422, detail=[
            {"loc": ["body", "settings", fid], "msg": msg, "type": "value_error"}
            for fid, msg in errors])
    try:
        draft = drafts.save_draft(db, league, settings, body.notes, body.version,
                                  current_user.username)
    except drafts.DraftConflict as e:
        raise HTTPException(status_code=409, detail=str(e))
    db.flush()
    audit.record(db, "game_reset.draft_saved", actor=current_user, target=league,
                 detail=f"version {draft.version}", request=request)
    db.commit()
    logger.info(f"Reset draft for {league.full_id} saved by {current_user.username}"
                f" (version {draft.version})")
    return _form(db, league)


@router.delete("/{league_id}/reset/draft", response_model=GameResetForm,
               summary="Discard the Game Reset Draft")
async def discard_reset_draft(
    league_id: int,
    request: Request,
    current_user: SysopUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    league = _league(db, league_id)
    draft = drafts.current_draft(db, league)
    if draft is None:
        raise HTTPException(status_code=404, detail="No draft to discard")
    db.delete(draft)
    audit.record(db, "game_reset.draft_discarded", actor=current_user, target=league,
                 detail=f"version {draft.version}", request=request)
    db.commit()
    logger.info(f"Reset draft for {league.full_id} discarded by {current_user.username}")
    return _form(db, league)
