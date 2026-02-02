import os
import sys
from fastapi import FastAPI, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import func

# Dodajemy ścieżkę do projektu
sys.path.append(os.getcwd())

# Importujemy Twoje istniejące moduły
from app.db.session import SessionLocal, engine, Base
from app.db.models import Proposal

# Import Rule Engine
from app.services.rule_engine import (
    RuleEngine, 
    ProposalInput, 
    TriageResult,
    proposal_from_db_model
)

# Inicjalizacja bazy
Base.metadata.create_all(bind=engine)

# Inicjalizacja Rule Engine (singleton)
try:
    rule_engine = RuleEngine("rulebook.yaml")
    print(f"✅ Rule Engine initialized: v{rule_engine.version}, {len(rule_engine.rulebook['rules'])} rules")
except Exception as e:
    print(f"⚠️  Rule Engine initialization failed: {e}")
    rule_engine = None

app = FastAPI(
    title="Participation Architecture API",
    version="0.6.0",  # Updated for Milestone 1
    description="Governance Data Pipeline & Deterministic Triage Rules for DAOs"
)

# Dependency do pobierania sesji bazy danych
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ============================================================================
# MODELS - Existing (Fatigue)
# ============================================================================

class FatigueBreakdown(BaseModel):
    volume_impact: float
    time_scarcity: float
    dropout_risk: float

class FatigueMetrics(BaseModel):
    votes_last_30d: int
    avg_time_gap_hours: float
    participation_rate: float

class FatigueResponse(BaseModel):
    address: str
    fatigue_score: float
    status: str
    breakdown: FatigueBreakdown
    metrics: FatigueMetrics
    last_updated: datetime

class HealthCheck(BaseModel):
    status: str
    version: str
    database: str
    proposals_count: int
    rule_engine: str = "not_initialized"
    rulebook_version: Optional[str] = None

# ============================================================================
# MODELS - New (Proposals + Triage)
# ============================================================================

class ProposalMetadata(BaseModel):
    """Basic proposal metadata"""
    author: str
    state: str
    votes: int
    scores_total: float
    created_at: datetime
    start_at: datetime
    end_at: datetime

class ProposalTriageResponse(BaseModel):
    """Proposal with triage information"""
    id: str
    title: str
    priority_score: int = Field(..., ge=0, le=100, description="Priority score (0-100)")
    labels: List[str] = Field(..., description="Applied labels (e.g., SECURITY, TREASURY)")
    reasons: List[str] = Field(..., description="Rule IDs that fired")
    recommended_handling: str = Field(..., description="urgent_deep_review | deep_review | standard_review | fast_track_ok | informational_only")
    metadata: ProposalMetadata

class ProposalDetailResponse(ProposalTriageResponse):
    """Detailed proposal with full audit trail"""
    body: str
    explain: dict = Field(..., description="Full explanation of score calculation")

class ProposalsFeedResponse(BaseModel):
    """Paginated feed of proposals"""
    proposals: List[ProposalTriageResponse]
    total: int
    page: int
    limit: int
    has_next: bool

# ============================================================================
# ENDPOINTS - System
# ============================================================================

@app.get("/", tags=["System"])
async def root():
    return {
        "message": "Participation Architecture API v0.6.0",
        "status": "operational",
        "milestone": "M1 - Rule Engine + API v1",
        "docs": "/docs"
    }

@app.get("/health", response_model=HealthCheck, tags=["System"])
async def health_check(db: Session = Depends(get_db)):
    """System health check with rule engine status"""
    try:
        count = db.query(Proposal).count()
        db_status = "connected"
    except Exception as e:
        count = 0
        db_status = "disconnected"
    
    # Check rule engine
    engine_status = "initialized" if rule_engine else "not_initialized"
    rulebook_ver = rule_engine.version if rule_engine else None
    
    return HealthCheck(
        status="ok", 
        version="0.6.0", 
        database=db_status,
        proposals_count=count,
        rule_engine=engine_status,
        rulebook_version=rulebook_ver
    )

# ============================================================================
# ENDPOINTS - Proposals (NEW - Milestone 1)
# ============================================================================

@app.get("/proposals/feed", response_model=ProposalsFeedResponse, tags=["Proposals"])
async def get_proposals_feed(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Items per page"),
    min_priority: Optional[int] = Query(None, ge=0, le=100, description="Filter by minimum priority score"),
    label: Optional[str] = Query(None, description="Filter by label (e.g., SECURITY, TREASURY)"),
    handling: Optional[str] = Query(None, description="Filter by recommended handling"),
    status: Optional[str] = Query(None, description="Filter by status (active, closed, etc.)"),
    db: Session = Depends(get_db)
):
    """
    Get normalized proposals feed with deterministic triage scores.
    
    Features:
    - Pagination (page, limit)
    - Filtering (min_priority, label, handling, status)
    - Sorted by priority_score (descending)
    
    Returns:
        Paginated list of proposals with triage metadata
    """
    if not rule_engine:
        raise HTTPException(status_code=503, detail="Rule engine not initialized")
    
    # Base query
    query = db.query(Proposal)
    
    # Apply status filter if provided
    if status:
        query = query.filter(Proposal.state == status)
    
    # Get total count
    total = query.count()
    
    # Pagination
    offset = (page - 1) * limit
    proposals = query.order_by(Proposal.start.desc()).offset(offset).limit(limit).all()
    
    # Evaluate each proposal through rule engine
    results = []
    for db_proposal in proposals:
        # Convert to ProposalInput
        proposal_input = proposal_from_db_model(db_proposal)
        
        # Evaluate
        triage_result = rule_engine.evaluate_proposal(proposal_input)
        
        # Apply filters
        if min_priority and triage_result.priority_score < min_priority:
            continue
        if label and label not in triage_result.labels:
            continue
        if handling and triage_result.recommended_handling != handling:
            continue
        
        # Build response
        results.append(ProposalTriageResponse(
            id=db_proposal.id,
            title=db_proposal.title,
            priority_score=triage_result.priority_score,
            labels=triage_result.labels,
            reasons=triage_result.reasons,
            recommended_handling=triage_result.recommended_handling,
            metadata=ProposalMetadata(
                author=db_proposal.author or "unknown",
                state=db_proposal.state or "unknown",
                votes=db_proposal.votes or 0,
                scores_total=db_proposal.scores_total or 0.0,
                created_at=datetime.fromtimestamp(db_proposal.created_at.timestamp() if hasattr(db_proposal.created_at, 'timestamp') else db_proposal.start, tz=timezone.utc),
                start_at=datetime.fromtimestamp(db_proposal.start, tz=timezone.utc),
                end_at=datetime.fromtimestamp(db_proposal.end, tz=timezone.utc)
            )
        ))
    
    # Sort by priority (highest first)
    results.sort(key=lambda x: x.priority_score, reverse=True)
    
    return ProposalsFeedResponse(
        proposals=results,
        total=total,
        page=page,
        limit=limit,
        has_next=(offset + limit) < total
    )

@app.get("/proposals/{proposal_id}", response_model=ProposalDetailResponse, tags=["Proposals"])
async def get_proposal_detail(
    proposal_id: str,
    db: Session = Depends(get_db)
):
    """
    Get detailed proposal with full rule audit trail.
    
    Returns:
        Proposal with priority score, labels, reasons, and explanation of how score was calculated
    """
    if not rule_engine:
        raise HTTPException(status_code=503, detail="Rule engine not initialized")
    
    # Fetch from DB
    db_proposal = db.query(Proposal).filter(Proposal.id == proposal_id).first()
    
    if not db_proposal:
        raise HTTPException(status_code=404, detail=f"Proposal {proposal_id} not found")
    
    # Convert to ProposalInput
    proposal_input = proposal_from_db_model(db_proposal)
    
    # Evaluate
    triage_result = rule_engine.evaluate_proposal(proposal_input)
    
    # Build response
    return ProposalDetailResponse(
        id=db_proposal.id,
        title=db_proposal.title,
        body=db_proposal.body or "",
        priority_score=triage_result.priority_score,
        labels=triage_result.labels,
        reasons=triage_result.reasons,
        recommended_handling=triage_result.recommended_handling,
        metadata=ProposalMetadata(
            author=db_proposal.author or "unknown",
            state=db_proposal.state or "unknown",
            votes=db_proposal.votes or 0,
            scores_total=db_proposal.scores_total or 0.0,
            created_at=datetime.fromtimestamp(db_proposal.created_at.timestamp() if hasattr(db_proposal.created_at, 'timestamp') else db_proposal.start, tz=timezone.utc),
            start_at=datetime.fromtimestamp(db_proposal.start, tz=timezone.utc),
            end_at=datetime.fromtimestamp(db_proposal.end, tz=timezone.utc)
        ),
        explain=triage_result.explain
    )

# ============================================================================
# ENDPOINTS - Delegates (Existing - preserved)
# ============================================================================

@app.get("/v1/delegates/{address}/fatigue", response_model=FatigueResponse, tags=["Delegates"])
async def get_delegate_fatigue(address: str, db: Session = Depends(get_db)):
    """
    Returns Delegate Fatigue Score based on real data from the last 30 days.
    
    NOTE: This is a simplified version. Full implementation in Milestone 2 will include:
    - Volume (40%): proposals per 7d/30d windows
    - Concurrency (25%): simultaneous active votes
    - Burstiness (20%): cadence spike detection
    - Reading Time (10%): word count / baseline speed
    - Novelty (5%): new domain tags vs routine
    """
    # 1. Time window (30 days back)
    days_back = 30
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
    cutoff_timestamp = int(cutoff_date.timestamp())

    # 2. Fetch data with time filter
    proposals_in_window = db.query(Proposal).filter(Proposal.start >= cutoff_timestamp).count()
    
    # 3. Business logic (Fatigue Engine v1 - simplified)
    if proposals_in_window == 0:
        score = 0.0
        status = "LOW"
    else:
        # Algorithm: >30 votes/month (1 per day) = high load
        # Scaling: 15 votes/month = 50 pts (Moderate), 30 votes/month = 100 pts (Critical)
        raw_score = (proposals_in_window / 30.0) * 100 
        score = min(raw_score, 100.0)

        if score < 30: 
            status = "LOW"
        elif score < 70: 
            status = "MODERATE"
        else: 
            status = "CRITICAL"

    return FatigueResponse(
        address=address,
        fatigue_score=round(score, 1),
        status=status,
        breakdown=FatigueBreakdown(
            volume_impact=round(score/100, 2),
            time_scarcity=0.5,
            dropout_risk=0.2
        ),
        metrics=FatigueMetrics(
            votes_last_30d=proposals_in_window,
            avg_time_gap_hours=24.0,
            participation_rate=0.0
        ),
        last_updated=datetime.now(timezone.utc)
    )

# ============================================================================
# ENDPOINTS - Debug
# ============================================================================

@app.get("/debug/proposals", tags=["Debug"])
def get_raw_proposals(limit: int = 5, db: Session = Depends(get_db)):
    """Get raw proposals from database (for debugging)"""
    return db.query(Proposal).order_by(Proposal.start.desc()).limit(limit).all()

@app.get("/debug/rulebook", tags=["Debug"])
def get_rulebook_info():
    """Get rulebook metadata and stats"""
    if not rule_engine:
        raise HTTPException(status_code=503, detail="Rule engine not initialized")
    
    return rule_engine.get_rulebook_info()

# ============================================================================
# STARTUP MESSAGE
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """Log startup information"""
    print("\n" + "="*70)
    print("🚀 PARTICIPATION ARCHITECTURE API v0.6.0")
    print("="*70)
    print(f"📊 Database: SQLite/PostgreSQL")
    if rule_engine:
        print(f"⚙️  Rule Engine: v{rule_engine.version} ({len(rule_engine.rulebook['rules'])} rules)")
    else:
        print("⚠️  Rule Engine: NOT INITIALIZED")
    print(f"📡 API Docs: http://localhost:8000/docs")
    print("="*70 + "\n")
