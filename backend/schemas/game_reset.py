"""Schemas for drafting a game reset. The settings themselves are a plain
mapping keyed by field id; game_reset/fields.py says what each one may hold."""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ResetChoice(BaseModel):
    letter: str
    name: str


class ResetField(BaseModel):
    """One setting, as the reset editor offers it, with the game's own help."""
    id: str
    label: str
    page: int
    group: str
    kind: str = Field(description="number, choice, toggle or date")
    default: Any = None
    min: Optional[int] = None
    max: Optional[int] = None
    choices: List[ResetChoice] = []
    interbbs: bool = False
    advised_min: Optional[int] = Field(
        None, description="Ours, not the game's: below it the form warns but allows")
    advised_reason: Optional[str] = None
    note: Optional[str] = None
    admin_note: Optional[str] = None
    depends_on: Optional[List[Any]] = Field(
        None, description="[field id, value]: only asked when that field has that value")
    help_title: str
    help: str


class ResetWarning(BaseModel):
    field: str
    message: str


class ResetDraft(BaseModel):
    id: int
    version: int
    settings: Dict[str, Any]
    warnings: List[ResetWarning] = []
    notes: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: Optional[str] = None


class ResetApplied(BaseModel):
    id: int
    settings: Dict[str, Any]
    applied_by: Optional[str] = None
    applied_at: Optional[str] = None
    game_start: Optional[str] = None


class ObservedSettings(BaseModel):
    """What the hub last decoded from the league's Configupdate (BRE only, so far)."""
    game_started_at: Optional[str] = None
    protection_turns: Optional[int] = None
    indiv_attacks: Optional[int] = None
    lost_attack_days: Optional[int] = None
    seen_at: Optional[str] = None


class GameResetForm(BaseModel):
    league_id: int
    full_id: str
    game_type: str
    fields: List[ResetField]
    defaults: Dict[str, Any]
    league_wide_help: str
    draft: Optional[ResetDraft] = None
    last_applied: Optional[ResetApplied] = None
    observed: Optional[ObservedSettings] = None


class ResetDraftSave(BaseModel):
    settings: Dict[str, Any]
    notes: Optional[str] = Field(None, max_length=4000)
    version: Optional[int] = Field(
        None, description="The draft version being edited; omit when starting a new draft")
