"""add_attack_sightings

Two new tables for tracing BRE attacks through the hub: every attack or result
seen in a packet, and the league settings last broadcast by its coordinator.
Purely additive, like processing_run_items: a rollback loses the attack history
and nothing else, and the backfill script can rebuild it from packets on disk.

Revision ID: b8e3f6a2c519
Revises: a7d4e2f91b58
Create Date: 2026-09-29 14:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "b8e3f6a2c519"
down_revision = "a7d4e2f91b58"
branch_labels = None
depends_on = None

SIGHTINGS = "attack_sightings"
SETTINGS = "league_game_settings"


def upgrade() -> None:
    if not _table_exists(SIGHTINGS):
        op.create_table(
            SIGHTINGS,
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("attack_id", sa.String(length=16), nullable=False),
            sa.Column("is_result", sa.Boolean(), nullable=False),
            sa.Column("packet_id", sa.Integer(), sa.ForeignKey("packets.id"), nullable=False),
            sa.Column("league_id", sa.Integer(), sa.ForeignKey("leagues.id"), nullable=False),
            sa.Column("from_planet", sa.Integer(), nullable=False),
            sa.Column("to_planet", sa.Integer(), nullable=False),
            sa.Column("attacker", sa.String(length=1), nullable=False),
            sa.Column("target", sa.String(length=1), nullable=False),
            sa.Column("attack_type", sa.String(length=20), nullable=True),
            sa.Column("stamp", sa.DateTime(), nullable=True),
        )
        op.create_index(f"ix_{SIGHTINGS}_attack_id", SIGHTINGS, ["attack_id"])
        op.create_index(f"ix_{SIGHTINGS}_packet_id", SIGHTINGS, ["packet_id"])
        op.create_index(f"ix_{SIGHTINGS}_league_stamp", SIGHTINGS, ["league_id", "stamp"])

    if not _table_exists(SETTINGS):
        op.create_table(
            SETTINGS,
            sa.Column("league_id", sa.Integer(), sa.ForeignKey("leagues.id"), primary_key=True),
            sa.Column("game_started_at", sa.DateTime(), nullable=True),
            sa.Column("protection_turns", sa.Integer(), nullable=True),
            sa.Column("indiv_attacks_per_day", sa.Integer(), nullable=True),
            sa.Column("lost_attack_days", sa.Integer(), nullable=True),
            sa.Column("packet_id", sa.Integer(), sa.ForeignKey("packets.id"), nullable=True),
            sa.Column("seen_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    for table in (SETTINGS, SIGHTINGS):
        if _table_exists(table):
            op.drop_table(table)


def _table_exists(table: str) -> bool:
    from sqlalchemy import inspect
    return inspect(op.get_bind()).has_table(table)
