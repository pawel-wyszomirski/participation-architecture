"""Add measurement identity to fatigue_snapshots

Revision ID: 002
Revises: 001
Create Date: 2026-08-28

Grant review point 4 (/t/30604 post 18): each persisted per-event result must
bind a unique vote-event identity (not only the proposal id), the code commit,
and the source-capability state including unknown windows. Columns are nullable
because ecosystem-variant rows and rows written before this revision carry none.
"""
# <!-- catalog-read -->
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fatigue_snapshots",
                  sa.Column("vote_event_id", sa.String(), nullable=True))
    op.add_column("fatigue_snapshots",
                  sa.Column("code_commit", sa.String(), nullable=True))
    op.add_column("fatigue_snapshots",
                  sa.Column("source_state", sa.String(), nullable=True))
    op.create_index("ix_fatigue_snapshots_vote_event_id",
                    "fatigue_snapshots", ["vote_event_id"])


def downgrade() -> None:
    op.drop_index("ix_fatigue_snapshots_vote_event_id", "fatigue_snapshots")
    op.drop_column("fatigue_snapshots", "source_state")
    op.drop_column("fatigue_snapshots", "code_commit")
    op.drop_column("fatigue_snapshots", "vote_event_id")
