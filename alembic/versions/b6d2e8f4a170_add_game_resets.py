"""add_game_resets

Game resets drafted (and later performed) from the console: one row per reset,
at most one draft per league. See backend/services/game_reset/.

Revision ID: b6d2e8f4a170
Revises: c3e7a1d9f402
Create Date: 2026-10-15 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "b6d2e8f4a170"
down_revision = "c3e7a1d9f402"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "game_resets" not in inspector.get_table_names():
        op.create_table(
            "game_resets",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("league_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=10), nullable=False),
            sa.Column("source", sa.String(length=10), nullable=False),
            sa.Column("settings", sa.JSON(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(length=50), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_by", sa.String(length=50), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("applied_by", sa.String(length=50), nullable=True),
            sa.Column("applied_at", sa.DateTime(), nullable=True),
            sa.Column("game_start", sa.DateTime(), nullable=True),
            sa.Column("backup_path", sa.String(length=255), nullable=True),
            sa.Column("transcript", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("sent_config", sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(["league_id"], ["leagues.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_game_resets_id", "game_resets", ["id"])
        op.create_index("ix_game_resets_league_id", "game_resets", ["league_id"])
        op.create_index("uq_game_resets_one_draft", "game_resets", ["league_id"],
                        unique=True, sqlite_where=sa.text("status = 'draft'"))


def downgrade() -> None:
    op.drop_index("uq_game_resets_one_draft", table_name="game_resets")
    op.drop_index("ix_game_resets_league_id", table_name="game_resets")
    op.drop_index("ix_game_resets_id", table_name="game_resets")
    op.drop_table("game_resets")
