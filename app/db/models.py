from sqlalchemy import Column, String, Integer, Float, Text, DateTime, Boolean
from datetime import datetime
from app.db.session import Base


class Proposal(Base):
    __tablename__ = "proposals"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    state = Column(String)     # 'closed', 'active'
    author = Column(String)    # adres portfela autora

    # Metryki głosowania
    votes = Column(Integer, default=0)
    scores_total = Column(Float, default=0.0)

    # Czas (Unix Timestamp)
    start = Column(Integer)
    end = Column(Integer)

    # Metadane systemowe
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Pola dla algorytmu (legacy - zostawione dla kompatybilności)
    is_signal = Column(Boolean, default=False)
    fatigue_score = Column(Float, default=0.0)


class Vote(Base):
    """
    A single delegate vote on a proposal, sourced from the Snapshot `votes` API.

    Backs the PER-DELEGATE DFI variant (dissertation 5.3.5a): the set of
    proposals a delegate actually voted on is the delegate's *revealed
    activity*, which is the unit of analysis for compute_per_delegate().

    Note: distinct from Proposal.votes (an aggregate vote *count* on a
    proposal). This table holds individual (voter, proposal) records.
    """
    __tablename__ = "votes"

    id = Column(String, primary_key=True, index=True)   # Snapshot vote id
    voter = Column(String, index=True, nullable=False)  # delegate wallet address
    proposal_id = Column(String, index=True, nullable=False)  # references proposals.id
    created = Column(Integer)        # unix timestamp of the vote
    choice = Column(Text)            # raw Snapshot choice (int/list/dict) as JSON string
    space = Column(String)           # governance space, e.g. arbitrumfoundation.eth

    # Metadane systemowe
    created_at = Column(DateTime, default=datetime.utcnow)


class FatigueSnapshot(Base):
    """
    Persisted result of a Delegate Fatigue Index computation.

    Purpose: fulfil the grant KPI "reproducible computation stored in DB".
    Each call to GET /delegates/{address}/fatigue (ecosystem variant) creates
    one row, allowing historical tracking of governance workload over time.

    Per-event rows are different (closure review 2026-09-03, point 5): a GET
    never writes one. They are registered by POST, idempotently on
    `measurement_id` - the digest of the complete measurement identity - so a
    browser refresh cannot manufacture measurement history.

    All raw metrics and component scores are stored so that any past result
    can be fully reproduced and audited without re-running the engine; the
    per-event manifest (point 4) additionally names every input set.
    """
    __tablename__ = "fatigue_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identity
    address = Column(String, index=True, nullable=False)
    computed_at = Column(DateTime, nullable=False)

    # Aggregate output
    fatigue_score = Column(Float, nullable=False)
    status = Column(String, nullable=False)        # LOW | MODERATE | HIGH | CRITICAL
    config_version = Column(String, nullable=False)

    # Component scores (0-1 each, see fatigue_engine.py)
    comp_volume = Column(Float, nullable=False)
    comp_concurrency = Column(Float, nullable=False)
    comp_burstiness = Column(Float, nullable=False)
    comp_reading_time = Column(Float, nullable=False)
    comp_novelty = Column(Float, nullable=False)

    # Raw metrics (source of truth for each component)
    metric_proposals_7d = Column(Integer, nullable=False)
    metric_proposals_30d = Column(Integer, nullable=False)
    metric_concurrent_active = Column(Integer, nullable=False)
    metric_avg_word_count = Column(Float, nullable=False)
    metric_weekly_avg = Column(Float, nullable=False)
    metric_novelty_ratio = Column(Float, nullable=False)

    # Measurement identity (grant review point 4, /t/30604 post 18): each
    # persisted result binds the unique vote-event, the code commit and the
    # source-capability state (JSON). Nullable - ecosystem-variant rows and
    # rows older than 2026-08-28 carry none.
    vote_event_id = Column(String, nullable=True, index=True)
    code_commit = Column(String, nullable=True)
    source_state = Column(String, nullable=True)  # JSON text

    # Complete measurement identity (closure review 2026-09-03, points 4-5).
    # measurement_id is UNIQUE: the same vote-event measured on the same
    # instrument, code and input sets is one row, however many times it is
    # requested. manifest holds the reconstructable input object as JSON.
    measurement_id = Column(String, nullable=True, unique=True, index=True)
    instrument_hash = Column(String, nullable=True)
    eligibility = Column(String, nullable=True)   # PRIMARY_ELIGIBLE | NOT_ELIGIBLE_...
    manifest = Column(Text, nullable=True)        # JSON text
