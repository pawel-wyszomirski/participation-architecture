"""Add fatigue_snapshots table

Revision ID: 001
Revises: (initial)
Create Date: 2026-02-23

Creates the fatigue_snapshots table for persisting DFI computations.
Supports the grant KPI: "reproducible computation stored in DB".
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "001"
down_revision = "943231068777"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fatigue_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        # Aggregate
        sa.Column("fatigue_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("config_version", sa.String(), nullable=False),
        # Component scores
        sa.Column("comp_volume", sa.Float(), nullable=False),
        sa.Column("comp_concurrency", sa.Float(), nullable=False),
        sa.Column("comp_burstiness", sa.Float(), nullable=False),
        sa.Column("comp_reading_time", sa.Float(), nullable=False),
        sa.Column("comp_novelty", sa.Float(), nullable=False),
        # Raw metrics
        sa.Column("metric_proposals_7d", sa.Integer(), nullable=False),
        sa.Column("metric_proposals_30d", sa.Integer(), nullable=False),
        sa.Column("metric_concurrent_active", sa.Integer(), nullable=False),
        sa.Column("metric_avg_word_count", sa.Float(), nullable=False),
        sa.Column("metric_weekly_avg", sa.Float(), nullable=False),
        sa.Column("metric_novelty_ratio", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_fatigue_snapshots_address",
        "fatigue_snapshots",
        ["address"],
    )
    op.create_index(
        "ix_fatigue_snapshots_computed_at",
        "fatigue_snapshots",
        ["computed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_fatigue_snapshots_computed_at", table_name="fatigue_snapshots")
    op.drop_index("ix_fatigue_snapshots_address", table_name="fatigue_snapshots")
    op.drop_table("fatigue_snapshots")
