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
    # Odcisk tresci i moment jej ostatniej zmiany (v0.2.0). Do v0.1.0 ponowny
    # import nie odswiezal tytulu ani tresci, wiec nie dalo sie stwierdzic, czy
    # etykieta opisuje wersje, ktora klasyfikator faktycznie widzial.
    content_hash = Column(String, nullable=True)
    content_updated_at = Column(DateTime, nullable=True)

    is_signal = Column(Boolean, default=False)
    fatigue_score = Column(Float, default=0.0)


class FatigueSnapshot(Base):
    """
    Persisted result of a Delegate Fatigue Index computation.

    Purpose: fulfil the grant KPI "reproducible computation stored in DB".
    Each call to GET /delegates/{address}/fatigue creates one row, allowing
    historical tracking of governance workload over time.

    All raw metrics and component scores are stored so that any past result
    can be fully reproduced and audited without re-running the engine.
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
