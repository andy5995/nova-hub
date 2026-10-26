"""game_reset_progress

Performing a reset: where one under way has got to, and the processing run that
sent its Game Start. See backend/services/game_reset/perform.py.

Revision ID: d4a9c2e7b815
Revises: b6d2e8f4a170
Create Date: 2026-10-15 18:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "d4a9c2e7b815"
down_revision = "b6d2e8f4a170"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain ADD COLUMN rather than a batch rebuild: a rebuild re-creates the
    # table from reflection and could drop the one-draft index's WHERE clause.
    # So processing_run_id is a plain integer: alembic can't add a foreign key to
    # SQLite in place.
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("game_resets")}
    if "progress" not in columns:
        op.add_column("game_resets", sa.Column("progress", sa.JSON(), nullable=True))
    if "processing_run_id" not in columns:
        op.add_column("game_resets",
                      sa.Column("processing_run_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("game_resets", "processing_run_id")
    op.drop_column("game_resets", "progress")
