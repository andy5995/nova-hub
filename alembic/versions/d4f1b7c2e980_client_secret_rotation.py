"""client_secret_rotation

A rotated secret can keep working for a few hours beside the new one, and a
rotation that stops it at once ends the access tokens issued before it
(backend/services/client_secrets.py).

Revision ID: d4f1b7c2e980
Revises: a3c8e1f6d092
Create Date: 2026-10-19 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "d4f1b7c2e980"
down_revision = "a3c8e1f6d092"
branch_labels = None
depends_on = None

COLUMNS = (
    ("previous_client_secret", sa.String(128)),
    ("previous_secret_expires_at", sa.DateTime()),
    ("tokens_valid_after", sa.DateTime()),
)


def upgrade() -> None:
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("clients")}
    for name, kind in COLUMNS:
        if name not in have:
            op.add_column("clients", sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        for name, _ in reversed(COLUMNS):
            batch.drop_column(name)
