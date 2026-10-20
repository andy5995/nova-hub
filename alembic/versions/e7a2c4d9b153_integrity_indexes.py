"""integrity_indexes

The hub now runs SQLite with foreign keys enforced (backend/core/database.py),
so the references it already had start to mean something. This adds what the
schema was missing: the client poll's index, the run lookups, and the
uniqueness the code has always assumed -- one row per league, one membership
per BBS per league, one reset under way at a time. All are indexes, which
SQLite can add without rebuilding a table.

Production had two packets naming processing runs that no longer exist. With
foreign keys on, any write to those columns would fail, so they are cleared.

Revision ID: e7a2c4d9b153
Revises: d4f1b7c2e980
Create Date: 2026-10-19 14:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "e7a2c4d9b153"
down_revision = "d4f1b7c2e980"
branch_labels = None
depends_on = None

INDEXES = (
    ("ix_packets_league_dest_downloaded", "packets",
     ["league_id", "dest_bbs_index", "downloaded_at"], False, None),
    ("ix_packets_processing_run_id", "packets", ["processing_run_id"], False, None),
    ("ix_processing_run_files_processing_run_id", "processing_run_files",
     ["processing_run_id"], False, None),
    ("uq_leagues_number_game", "leagues", ["league_id", "game_type"], True, None),
    ("uq_league_memberships_league_client", "league_memberships",
     ["league_id", "client_id"], True, None),
    ("uq_game_resets_one_applying", "game_resets", ["status"], True,
     sa.text("status = 'applying'")),
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE packets SET processing_run_id = NULL WHERE processing_run_id IS NOT NULL "
        "AND processing_run_id NOT IN (SELECT id FROM processing_runs)"))

    inspector = sa.inspect(bind)
    for name, table, columns, unique, where in INDEXES:
        if name in {i["name"] for i in inspector.get_indexes(table)}:
            continue
        kw = {"sqlite_where": where} if where is not None else {}
        op.create_index(name, table, columns, unique=unique, **kw)


def downgrade() -> None:
    for name, table, *_ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
