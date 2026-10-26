"""league_game_settings_full

Every reset-editor setting decoded from a league's Configupdate, now that the
whole BRE record is mapped (backend/services/bre_packet.py).

Revision ID: a3c8e1f6d092
Revises: e7b3d1a9c524
Create Date: 2026-10-16 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "a3c8e1f6d092"
down_revision = "e7b3d1a9c524"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("league_game_settings")}
    if "settings" not in columns:
        op.add_column("league_game_settings", sa.Column("settings", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("league_game_settings") as batch:
        batch.drop_column("settings")
