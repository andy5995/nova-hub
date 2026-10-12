"""self_service

Sysops apply to join; the admin approves. Adds the applications queue, the
Verify step's first_token_at / first_upload_at on clients, and claim links
bound to an account. See backend/services/applications.py.

first_token_at and first_upload_at are backfilled for BBSes already running,
so they don't show as stuck at the first step: first_upload_at from the
earliest packet sent from one of the BBS's league indexes, and first_token_at
from last_seen, or from that first upload when it is earlier.

Revision ID: c3e7a1d9f402
Revises: 9a4b2e7c1f05
Create Date: 2026-10-12 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "c3e7a1d9f402"
down_revision = "9a4b2e7c1f05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "applications" not in inspector.get_table_names():
        op.create_table(
            "applications",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=10), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("applicant", sa.String(length=50), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=10), nullable=False),
            sa.Column("bbs_name", sa.String(length=100), nullable=False),
            sa.Column("sysop_name", sa.String(length=100), nullable=True),
            sa.Column("email", sa.String(length=100), nullable=True),
            sa.Column("city", sa.String(length=50), nullable=True),
            sa.Column("state", sa.String(length=50), nullable=True),
            sa.Column("country", sa.String(length=50), nullable=True),
            sa.Column("address", sa.String(length=200), nullable=True),
            sa.Column("os", sa.String(length=10), nullable=True),
            sa.Column("league_ids", sa.JSON(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("reviewed_by", sa.String(length=50), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("decision_note", sa.Text(), nullable=True),
            sa.Column("granted", sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["sysop_users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_applications_id", "applications", ["id"])
        op.create_index("ix_applications_user_id", "applications", ["user_id"])
        op.create_index("ix_applications_client_id", "applications", ["client_id"])
        op.create_index("ix_applications_status", "applications", ["status"])

    client_columns = {c["name"] for c in inspector.get_columns("clients")}
    if "first_token_at" not in client_columns:
        with op.batch_alter_table("clients") as batch:
            batch.add_column(sa.Column("first_token_at", sa.DateTime(), nullable=True))
            batch.add_column(sa.Column("first_upload_at", sa.DateTime(), nullable=True))
        _backfill(bind)

    link_columns = {c["name"] for c in inspector.get_columns("claim_links")}
    if "user_id" not in link_columns:
        with op.batch_alter_table("claim_links") as batch:
            batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
            batch.create_index("ix_claim_links_user_id", ["user_id"])
            batch.create_foreign_key("fk_claim_links_user_id", "sysop_users", ["user_id"], ["id"],
                                     ondelete="SET NULL")


def _backfill(bind) -> None:
    bind.execute(sa.text(
        "UPDATE clients SET first_token_at = last_seen WHERE first_token_at IS NULL"))
    rows = bind.execute(sa.text("""
        SELECT m.client_id, MIN(p.uploaded_at)
        FROM league_memberships m
        JOIN packets p ON p.league_id = m.league_id
             AND UPPER(p.source_bbs_index) = printf('%02X', m.bbs_index)
        WHERE m.bbs_index IS NOT NULL
        GROUP BY m.client_id
    """)).fetchall()
    for client_id, first in rows:
        if first is not None:
            bind.execute(sa.text("UPDATE clients SET first_upload_at = :t WHERE id = :id"),
                         {"t": first, "id": client_id})
    # last_seen is the latest sign-in, not the first; an upload needed one
    # no later than itself.
    bind.execute(sa.text(
        "UPDATE clients SET first_token_at = first_upload_at "
        "WHERE first_upload_at IS NOT NULL "
        "AND (first_token_at IS NULL OR first_upload_at < first_token_at)"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "user_id" in {c["name"] for c in inspector.get_columns("claim_links")}:
        with op.batch_alter_table("claim_links") as batch:
            batch.drop_constraint("fk_claim_links_user_id", type_="foreignkey")
            batch.drop_index("ix_claim_links_user_id")
            batch.drop_column("user_id")
    if "first_token_at" in {c["name"] for c in inspector.get_columns("clients")}:
        with op.batch_alter_table("clients") as batch:
            batch.drop_column("first_upload_at")
            batch.drop_column("first_token_at")
    if "applications" in inspector.get_table_names():
        op.drop_table("applications")
