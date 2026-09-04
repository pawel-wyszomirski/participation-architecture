"""Add the complete measurement manifest to fatigue_snapshots

Revision ID: 003
Revises: 002
Create Date: 2026-09-04

<!-- catalog-read --> alembic/versions holds 001 (fatigue_snapshots) and 002
(measurement identity); this is the next revision in that chain.

Closure review (/t/30604, 2026-09-03), points 4 and 5: a persisted per-event
result must carry the complete, reconstructable measurement identity - not a
hash alone - and persistence must be idempotent on it. measurement_id is
UNIQUE; rows written before this revision keep NULL there (nullable, so the
constraint does not fire on them).
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fatigue_snapshots",
                  sa.Column("measurement_id", sa.String(), nullable=True))
    op.add_column("fatigue_snapshots",
                  sa.Column("instrument_hash", sa.String(), nullable=True))
    op.add_column("fatigue_snapshots",
                  sa.Column("eligibility", sa.String(), nullable=True))
    op.add_column("fatigue_snapshots",
                  sa.Column("manifest", sa.Text(), nullable=True))
    op.create_index("ix_fatigue_snapshots_measurement_id",
                    "fatigue_snapshots", ["measurement_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_fatigue_snapshots_measurement_id", "fatigue_snapshots")
    op.drop_column("fatigue_snapshots", "manifest")
    op.drop_column("fatigue_snapshots", "eligibility")
    op.drop_column("fatigue_snapshots", "instrument_hash")
    op.drop_column("fatigue_snapshots", "measurement_id")
