"""mark_downloaded_packets

Packets with a download time but is_downloaded still false: 1,991 rows on prod,
all written 11-12 January 2026, before downloads set the flag. The outbound
collector took them for packets still waiting, so a new packet under one of
their names reused the row and inherited its January download time.

Revision ID: e7b3d1a9c524
Revises: d4a9c2e7b815
Create Date: 2026-10-16 10:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "e7b3d1a9c524"
down_revision = "d4a9c2e7b815"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE packets SET is_downloaded = 1 "
               "WHERE downloaded_at IS NOT NULL "
               "AND (is_downloaded IS NULL OR is_downloaded = 0)")


def downgrade() -> None:
    # Which rows were wrong isn't kept; and the flag was wrong, not the time.
    pass
