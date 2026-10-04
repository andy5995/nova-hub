"""add_traffic_sightings

The rest of the BRE InterBBS traffic -- Terrorist Ops and results, trade deals,
spy reports, messages (who to whom only), Gooie and Special Op traffic -- seen in
each packet. Purely additive like attack_sightings: a rollback loses this
history and nothing else, and backfill_attacks.py --redo rebuilds it.

Revision ID: c5f2a8d61e04
Revises: b8e3f6a2c519
Create Date: 2026-10-04 10:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "c5f2a8d61e04"
down_revision = "b8e3f6a2c519"
branch_labels = None
depends_on = None

TABLE = "traffic_sightings"


def upgrade() -> None:
    from sqlalchemy import inspect
    if inspect(op.get_bind()).has_table(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("event_key", sa.String(length=16), nullable=False),
        sa.Column("packet_id", sa.Integer(), sa.ForeignKey("packets.id"), nullable=False),
        sa.Column("league_id", sa.Integer(), sa.ForeignKey("leagues.id"), nullable=False),
        sa.Column("record_type", sa.Integer(), nullable=False),
        sa.Column("from_planet", sa.Integer(), nullable=False),
        sa.Column("to_planet", sa.Integer(), nullable=False),
        sa.Column("from_letter", sa.String(length=1), nullable=True),
        sa.Column("to_letter", sa.String(length=1), nullable=True),
        sa.Column("from_player", sa.Integer(), nullable=True),
        sa.Column("to_player", sa.Integer(), nullable=True),
        sa.Column("recipients", sa.String(length=300), nullable=True),
        sa.Column("pair_key", sa.String(length=20), nullable=True),
        sa.Column("stamp", sa.DateTime(), nullable=True),
    )
    for col in ("event_key", "packet_id", "league_id", "pair_key"):
        op.create_index(f"ix_{TABLE}_{col}", TABLE, [col])


def downgrade() -> None:
    from sqlalchemy import inspect
    if inspect(op.get_bind()).has_table(TABLE):
        op.drop_table(TABLE)
